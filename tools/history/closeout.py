"""One-shot HISTORY closeout: append the entry, rebuild every derived artifact,
and run the exact gates the commit preflight enforces -- in a single command.

The AGENTS.md Session-End chain is otherwise eight separate steps (new_entry,
rebuild_index, streams mirror, rebuild_cross_index, write_snapshot, then
verify_integrity / verify_routing / verify_continuity). This wrapper runs them in
dependency order so the temporal chain is prepared and verified before `git add`,
which means the preflight hook passes on the first try instead of blocking-and-
retrying as each missing artifact is discovered.

It changes NO gate behavior: it shells out to the same tested modules and uses
the SAME flags as tools/claude/preflight_protocol.sh -- in particular
`verify_continuity --no-recorded-fact-audit`, so it never fires the recorded-fact
audit the hook deliberately disables. Pure orchestration; on any step failure it
exits non-zero and you fall back to the manual steps.

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

# The four gates tools/claude/preflight_protocol.sh runs on git add/commit/push,
# with identical flags. Kept in one place so this wrapper can never drift from
# what actually gates the commit.
PREFLIGHT_GATES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("verify_integrity", ("tools.history.verify_integrity",)),
    ("verify_routing", ("tools.history.verify_routing",)),
    ("verify_continuity", ("tools.history.verify_continuity", "--no-recorded-fact-audit")),
    ("verify_streams", ("tools.streams.verify_streams",)),
)

STAGE_HINT = (
    "HISTORY.md HISTORY_INDEX.md PROJECT_STATUS.md "
    ".seam/streams/history/index.md .seam/streams/history/log.md "
    ".seam/cross_index.md .seam/cross_index_archive/"
)


def _run(label: str, module_args: tuple[str, ...] | list[str]) -> None:
    print(f"[closeout] {label} ...", flush=True)
    result = subprocess.run([sys.executable, "-m", *module_args], cwd=REPO_ROOT)
    if result.returncode != 0:
        print(
            f"[closeout] FAILED at '{label}' (exit {result.returncode}). "
            "Chain left as-is; fix and re-run or fall back to manual steps.",
            file=sys.stderr,
        )
        sys.exit(result.returncode)


def _latest_entry_ids(count: int) -> str:
    entries = parse_entries(read_history_bytes(HISTORY_PATH))
    ids = [entry.id for entry in entries][-count:]
    return ",".join(str(i) for i in reversed(ids))


def main() -> None:
    parser = argparse.ArgumentParser(description="One-shot HISTORY closeout + preflight gate run.")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--topics", required=True, help="Comma-separated tags.")
    parser.add_argument("--commits", default="pending")
    parser.add_argument("--refs", default="none")
    parser.add_argument("--supersedes", default=None)
    parser.add_argument("--body-file", required=True, help="Path to the entry body text.")
    parser.add_argument(
        "--snapshot-entries",
        type=int,
        default=4,
        help="How many most-recent entries the handoff snapshot references (default 4).",
    )
    args = parser.parse_args()

    body = Path(args.body_file).read_text(encoding="utf-8")

    new_entry_args = [
        "tools.history.new_entry",
        "--agent", args.agent,
        "--status", args.status,
        "--topics", args.topics,
        "--commits", args.commits,
        "--refs", args.refs,
        "--body", body,
    ]
    if args.supersedes:
        new_entry_args += ["--supersedes", args.supersedes]

    _run("append HISTORY entry", new_entry_args)
    _run("rebuild HISTORY_INDEX", ("tools.history.rebuild_index",))
    _run("mirror history streams", ("tools.streams.history_adapter",))
    _run("rebuild cross-index", ("tools.streams.rebuild_cross_index",))
    _run(
        "write snapshot",
        ("tools.history.write_snapshot", "--agent", args.agent, "--entries", _latest_entry_ids(args.snapshot_entries)),
    )
    for label, module_args in PREFLIGHT_GATES:
        _run(label, module_args)

    print(
        "\n[closeout] OK -- chain prepared and all preflight gates pass.\n"
        "Update PROJECT_STATUS.md if the current focus changed, then stage the "
        "chain + your source files, e.g.:\n"
        f"    git add <your source files> {STAGE_HINT}"
    )


if __name__ == "__main__":
    main()
