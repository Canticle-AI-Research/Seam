"""One-shot HISTORY closeout: append the entry, rebuild every derived artifact,
and run the exact gates the canonical pre-commit hook enforces -- in one command.

The AGENTS.md Session-End chain otherwise requires a history append/index
rebuild, history-stream mirroring, conditional roadmap refresh, cross-index
rebuild, snapshot write, and five verification gates. This wrapper runs them in
dependency order so the temporal chain is prepared and verified before `git add`,
which means the pre-commit hook passes on the first try instead of blocking and
retrying as each missing artifact is discovered.

It changes NO gate behavior: it shells out to the same tested modules with the
SAME flags as the canonical commit gate AND the required `repo-hygiene` CI check.
As of HISTORY#536 that includes the recorded-fact audit, so a green closeout is
no longer weaker than the check that will run on the PR. Pure orchestration; on
any step failure it exits non-zero. If HISTORY was already appended, re-run with
``--resume-entry`` so the derived chain is repaired without appending a duplicate
entry.

It does NOT stage or commit. It prints the suggested `git add` and leaves the
commit to you (honoring the "wait for push it" rule).

Usage:
    python -m tools.history.closeout \
        --agent claude-opus-4-8 --status done \
        --topics "graph, verify" --supersedes 458 \
        --refs docs/roadmap/GRAPH_MEMORY_MATURITY.md \
        --body-file /path/to/body.txt
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from tools.history.history_lib import HISTORY_PATH, parse_entries, read_history_bytes

REPO_ROOT = Path(__file__).resolve().parents[2]

# The six gates tools/git-hooks/pre-commit runs, in identical order. The commit
# hook adds ``--staged`` to verify_wiki because it owns the Git-index boundary;
# closeout intentionally verifies the complete working tree before files are
# staged. Kept in one place so this wrapper cannot omit a canonical gate.
PREFLIGHT_GATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("verify_integrity", ("tools.history.verify_integrity",)),
    ("verify_routing", ("tools.history.verify_routing",)),
    ("verify_handoffs", ("tools.history.verify_handoffs",)),
    ("verify_continuity", ("tools.history.verify_continuity",)),
    ("verify_streams", ("tools.streams.verify_streams",)),
    ("verify_wiki", ("tools.docs.verify_wiki",)),
)

STAGE_HINT = (
    "HISTORY.md HISTORY_INDEX.md PROJECT_STATUS.md "
    ".seam/streams/history/index.md .seam/streams/history/log.md "
    ".seam/cross_index.md .seam/cross_index_archive/"
)


class CloseoutStepError(RuntimeError):
    """A closeout subprocess failed."""

    def __init__(self, label: str, returncode: int):
        super().__init__(f"{label} failed with exit {returncode}")
        self.label = label
        self.returncode = returncode


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _run(label: str, module_args: tuple[str, ...] | list[str]) -> None:
    print(f"[closeout] {label} ...", flush=True)
    result = subprocess.run([sys.executable, "-m", *module_args], cwd=REPO_ROOT)
    if result.returncode != 0:
        print(
            f"[closeout] FAILED at '{label}' (exit {result.returncode}). "
            "Chain left as-is; fix and re-run or fall back to manual steps.",
            file=sys.stderr,
        )
        raise CloseoutStepError(label, result.returncode)


def _latest_entry_ids(count: int) -> str:
    entries = parse_entries(read_history_bytes(HISTORY_PATH))
    ids = [entry.id for entry in entries][-count:]
    return ",".join(str(i) for i in reversed(ids))


def _latest_entry_id() -> int | None:
    entries = parse_entries(read_history_bytes(HISTORY_PATH))
    return entries[-1].id if entries else None


def _roadmap_changed() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no", "--", "ROADMAP.md"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise CloseoutStepError("inspect ROADMAP.md state", result.returncode)
    return bool(result.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="One-shot HISTORY closeout + preflight gate run.")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--status")
    parser.add_argument("--topics", help="Comma-separated tags.")
    parser.add_argument("--commits", default="pending")
    parser.add_argument("--refs", default="none")
    parser.add_argument("--supersedes", default=None)
    parser.add_argument("--body-file", help="Path to the entry body text.")
    parser.add_argument(
        "--resume-entry",
        type=_positive_int,
        help="Skip append and resume derived rebuilds for this latest HISTORY entry id.",
    )
    parser.add_argument(
        "--snapshot-entries",
        type=_positive_int,
        default=4,
        help="How many most-recent entries the handoff snapshot references (default 4).",
    )
    args = parser.parse_args(argv)
    if args.resume_entry is None:
        missing = [
            option
            for option, value in (
                ("--status", args.status),
                ("--topics", args.topics),
                ("--body-file", args.body_file),
            )
            if value is None
        ]
        if missing:
            parser.error(
                f"{', '.join(missing)} required unless --resume-entry is provided"
            )

    starting_latest = _latest_entry_id()
    active_entry_id = args.resume_entry
    try:
        if args.resume_entry is not None:
            if starting_latest != args.resume_entry:
                parser.error(
                    f"--resume-entry must name the latest HISTORY entry "
                    f"({starting_latest if starting_latest is not None else 'none'})"
                )
            _run("rebuild HISTORY_INDEX", ("tools.history.rebuild_index",))
        else:
            body = Path(args.body_file).read_text(encoding="utf-8")
            new_entry_args = [
                "tools.history.new_entry",
                "--agent",
                args.agent,
                "--status",
                args.status,
                "--topics",
                args.topics,
                "--commits",
                args.commits,
                "--refs",
                args.refs,
                "--body",
                body,
            ]
            if args.supersedes:
                new_entry_args += ["--supersedes", args.supersedes]
            _run("append HISTORY entry", new_entry_args)
            active_entry_id = _latest_entry_id()
            if active_entry_id is None or active_entry_id == starting_latest:
                raise CloseoutStepError("confirm appended HISTORY entry", 1)
            # new_entry rebuilds the index itself; this explicit rebuild keeps the
            # manual Session-End dependency visible and repairs partial old runs.
            _run("rebuild HISTORY_INDEX", ("tools.history.rebuild_index",))

        _run("mirror history streams", ("tools.streams.history_adapter",))
        if _roadmap_changed():
            _run("refresh roadmap stream + state", ("tools.streams.roadmap_parser",))
            _run(
                "rebuild roadmap stream index",
                ("tools.streams.rebuild_index", "--stream", "roadmap"),
            )
        _run("rebuild cross-index", ("tools.streams.rebuild_cross_index",))
        _run(
            "write snapshot",
            (
                "tools.history.write_snapshot",
                "--agent",
                args.agent,
                "--entries",
                _latest_entry_ids(args.snapshot_entries),
            ),
        )
        for label, module_args in PREFLIGHT_GATES:
            _run(label, module_args)
    except CloseoutStepError as exc:
        latest_after_failure = _latest_entry_id()
        if latest_after_failure is not None and latest_after_failure != starting_latest:
            print(
                f"[closeout] HISTORY entry #{latest_after_failure:03d} was already appended. "
                f"After fixing the failure, re-run the same command with "
                f"--resume-entry {latest_after_failure} to avoid a duplicate entry.",
                file=sys.stderr,
            )
        elif active_entry_id is not None:
            print(
                f"[closeout] Re-run the same --resume-entry {active_entry_id} command "
                "after fixing the failure.",
                file=sys.stderr,
            )
        return exc.returncode

    print(
        "\n[closeout] OK -- chain prepared and all preflight gates pass.\n"
        "Stage the chain + your source files (including PROJECT_STATUS.md if you "
        "updated it before closeout), e.g.:\n"
        f"    git add <your source files> {STAGE_HINT}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
