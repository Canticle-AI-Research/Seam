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


def test_preflight_gates_match_canonical_commit_hook() -> None:
    hook = (closeout.REPO_ROOT / "tools/git-hooks/pre-commit").read_text(
        encoding="utf-8"
    )
    observed: list[tuple[str, tuple[str, ...]]] = []
    for line in hook.splitlines():
        match = re.match(r'^run_gate "([^"]+)"\s+"\$PY" -m (\S+)(.*)$', line)
        if match:
            observed.append(
                (
                    match.group(1),
                    (match.group(2), *match.group(3).strip().split()),
                )
            )

    expected = tuple(
        (label, (*args, "--staged") if label == "verify_wiki" else args)
        for label, args in closeout.PREFLIGHT_GATES
    )
    assert tuple(observed) == expected


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
