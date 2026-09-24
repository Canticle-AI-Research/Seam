"""Regression tests for the one-shot history closeout orchestrator."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import pytest

from tools.history import closeout


def _base_args(body_file: Path) -> list[str]:
    return [
        "--agent",
        "codex",
        "--status",
        "done",
        "--topics",
        "history,verify",
        "--body-file",
        str(body_file),
    ]


# A gate may be invoked two ways in the hook, and the second is the stricter
# one: `run_gate` records a failure and lets the remaining gates run so one
# commit reports every problem, while a bare `... || exit 1` scope block aborts
# immediately. `verify_agent_config` deliberately uses the bare form and sits
# ahead of the merge/rebase early-exit, so it applies during merges when the
# run_gate chain is skipped (b623032). An earlier version of this test matched
# only `run_gate` lines in positional order, so that hardening read as a missing
# gate. Assert the invariant instead: every canonical gate is enforced, none in
# a form weaker than run_gate, and the shared chain keeps canonical order.
RUN_GATE_RE = re.compile(r'^run_gate "([^"]+)"\s+"\$PY" -m (\S+)(.*)$')
# Presence and strictness are matched independently: requiring `|| exit 1` to
# match at all would make the abort assertion below vacuously true, since every
# captured gate would already be an aborting one.
BARE_GATE_RE = re.compile(r'^"\$PY" -m (tools\.\S+?)((?: [^|]*?)?)\s*(\|\|\s*exit 1)?\s*$')

# Hook-only scoping arguments that narrow a gate to the staged tree. They make
# a gate cheaper, never weaker, so they are not drift.
STAGED_SCOPED = {"verify_wiki", "verify_agent_config"}


def _hook_gates() -> tuple[dict[str, tuple[str, ...]], list[str], set[str]]:
    """Return {module: args}, the run_gate module order, and aborting modules."""

    hook = (closeout.REPO_ROOT / "tools/git-hooks/pre-commit").read_text(
        encoding="utf-8"
    )
    gates: dict[str, tuple[str, ...]] = {}
    chain_order: list[str] = []
    aborting: set[str] = set()
    for line in hook.splitlines():
        run_gate = RUN_GATE_RE.match(line)
        if run_gate:
            module = run_gate.group(2)
            gates[module] = (module, *run_gate.group(3).strip().split())
            chain_order.append(module)
            continue
        bare = BARE_GATE_RE.match(line)
        if bare:
            module = bare.group(1)
            gates[module] = (module, *bare.group(2).strip().split())
            if bare.group(3):
                aborting.add(module)
    return gates, chain_order, aborting


def test_commit_hook_enforces_every_canonical_preflight_gate() -> None:
    """The hook must not omit a gate the closeout orchestrator claims to run."""

    gates, _chain_order, _aborting = _hook_gates()
    canonical = {args[0] for _label, args in closeout.PREFLIGHT_GATES}
    missing = canonical - set(gates)
    assert not missing, f"pre-commit hook omits canonical gates: {sorted(missing)}"


def test_commit_hook_gate_arguments_match_canonical_invocations() -> None:
    """A gate must not be narrowed in the hook beyond documented staged scoping."""

    gates, _chain_order, _aborting = _hook_gates()
    for label, args in closeout.PREFLIGHT_GATES:
        module = args[0]
        observed = gates[module]
        allowed = {args}
        if label in STAGED_SCOPED:
            allowed.add((*args, "--staged"))
        assert observed in allowed, (
            f"{label} runs as {observed} in the hook; canonical is {args}"
        )


def test_commit_hook_chain_preserves_canonical_gate_order() -> None:
    """Gates sharing the run_gate chain must keep their canonical order."""

    _gates, chain_order, _aborting = _hook_gates()
    canonical = [args[0] for _label, args in closeout.PREFLIGHT_GATES]
    expected = [module for module in canonical if module in set(chain_order)]
    assert chain_order == expected


def test_gates_outside_the_run_gate_chain_abort_the_commit() -> None:
    """A gate lifted out of the chain must abort, not merely be skipped."""

    gates, chain_order, aborting = _hook_gates()
    canonical = {args[0] for _label, args in closeout.PREFLIGHT_GATES}
    lifted = (canonical & set(gates)) - set(chain_order)
    assert lifted <= aborting, (
        f"canonical gates run outside the chain without `|| exit 1`: "
        f"{sorted(lifted - aborting)}"
    )


@pytest.mark.parametrize("value", ["0", "-1"])
def test_positive_int_rejects_non_positive_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError, match="at least 1"):
        closeout._positive_int(value)


@pytest.mark.parametrize("roadmap_changed", [False, True])
def test_resume_rebuilds_without_appending_duplicate(
    monkeypatch: pytest.MonkeyPatch,
    roadmap_changed: bool,
) -> None:
    calls: list[tuple[str, tuple[str, ...] | list[str]]] = []

    monkeypatch.setattr(closeout, "_latest_entry_id", lambda: 459)
    monkeypatch.setattr(closeout, "_latest_entry_ids", lambda count: "459,458")
    monkeypatch.setattr(closeout, "_roadmap_changed", lambda: roadmap_changed)
    monkeypatch.setattr(closeout, "_run", lambda label, args: calls.append((label, args)))

    result = closeout.main(["--agent", "codex", "--resume-entry", "459"])

    assert result == 0
    labels = [label for label, _ in calls]
    assert "append HISTORY entry" not in labels
    assert labels[:2] == ["rebuild HISTORY_INDEX", "mirror history streams"]
    if roadmap_changed:
        assert labels[2:5] == [
            "refresh roadmap stream + state",
            "rebuild roadmap stream index",
            "rebuild cross-index",
        ]
        assert calls[3] == (
            "rebuild roadmap stream index",
            ("tools.streams.rebuild_index", "--stream", "roadmap"),
        )
    else:
        assert labels[2] == "rebuild cross-index"
    gate_count = len(closeout.PREFLIGHT_GATES)
    assert labels[-gate_count:] == [label for label, _ in closeout.PREFLIGHT_GATES]


def test_failure_after_append_prints_safe_resume_hint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    body_file = tmp_path / "body.md"
    body_file.write_text("closeout body", encoding="utf-8")
    latest_ids = iter([459, 460, 460])

    monkeypatch.setattr(closeout, "_latest_entry_id", lambda: next(latest_ids))

    def fail_after_append(label: str, args: tuple[str, ...] | list[str]) -> None:
        del args
        if label == "rebuild HISTORY_INDEX":
            raise closeout.CloseoutStepError(label, 7)

    monkeypatch.setattr(closeout, "_run", fail_after_append)

    result = closeout.main(_base_args(body_file))

    assert result == 7
    assert "--resume-entry 460" in capsys.readouterr().err


def test_snapshot_entry_count_rejects_zero(
    tmp_path: Path,
) -> None:
    body_file = tmp_path / "body.md"
    body_file.write_text("closeout body", encoding="utf-8")

    with pytest.raises(SystemExit) as exc:
        closeout.main([*_base_args(body_file), "--snapshot-entries", "0"])

    assert exc.value.code == 2
