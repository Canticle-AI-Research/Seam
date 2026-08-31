"""Public CLI contract for bounded root session state and TDD receipts."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools.agents import session_state


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "tests@example.invalid")
    _git(path, "config", "user.name", "SEAM tests")
    (path / "README.md").write_text("test\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-qm", "baseline")
    return path


def test_init_and_record_tdd_cycle(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEX_SESSION_ID", "session-cli-1")
    state_root = tmp_path / "sessions"

    assert session_state.main(
        [
            "--repo-root",
            str(repo),
            "--state-root",
            str(state_root),
            "init",
            "--objective",
            "Implement bounded orchestration.",
            "--plan",
            "Write the failing test",
            "--plan",
            "Implement the slice",
            "--constraint",
            "Do not read full history",
            "--affected-test",
            "tests/audit/test_agent_session_state.py",
        ]
    ) == 0
    assert session_state.main(
        [
            "--repo-root",
            str(repo),
            "--state-root",
            str(state_root),
            "record-tdd",
            "--behavior",
            "runtime changes carry red/green evidence",
            "--test-ref",
            "tests/audit/test_agent_session_state.py::test_init_and_record_tdd_cycle",
            "--implementation-ref",
            "tools/agents/session_state.py",
            "--red-command",
            "pytest tests/audit/test_agent_session_state.py -q",
            "--red-exit",
            "1",
            "--red-fingerprint",
            "missing-module",
            "--green-command",
            "pytest tests/audit/test_agent_session_state.py -q",
            "--green-exit",
            "0",
            "--green-fingerprint",
            "one-pass",
        ]
    ) == 0

    state = json.loads((state_root / "session-cli-1.json").read_text(encoding="utf-8"))
    assert state["schema"] == "seam-agent-session-state/v1"
    assert state["base_sha"] == _git(repo, "rev-parse", "HEAD")
    assert state["objective"] == "Implement bounded orchestration."
    assert state["tdd_cycles"][0]["red"]["exit_code"] == 1
    assert state["tdd_cycles"][0]["green"]["exit_code"] == 0


def test_init_rejects_secret_shaped_context(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODEX_SESSION_ID", "session-cli-2")

    assert session_state.main(
        [
            "--repo-root",
            str(repo),
            "--state-root",
            str(tmp_path / "sessions"),
            "init",
            "--objective",
            "Use token=not-a-real-secret-but-still-forbidden",
        ]
    ) == 1
