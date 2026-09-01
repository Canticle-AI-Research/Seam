"""Behavioral tests for the project SessionEnd closeout dispatcher."""

from __future__ import annotations

import io
import json
import os
import subprocess
from pathlib import Path

import pytest

from tools.agents import session_end_closeout

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOKS_CONFIG = REPO_ROOT / ".codex" / "hooks.json"
RECEIPT_SCHEMA = REPO_ROOT / "tools" / "agents" / "schemas" / "closeout-receipt.schema.json"
REQUEST_SCHEMA = REPO_ROOT / "tools" / "agents" / "schemas" / "closeout-request.schema.json"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "SEAM tests")
    (repo / "seam_runtime").mkdir()
    (repo / "seam_runtime" / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", "seam_runtime/feature.py")
    _git(repo, "commit", "-qm", "baseline")
    return repo


def _event(repo: Path, session_id: str = "session-123") -> dict[str, str]:
    return {
        "hook_event_name": "SessionEnd",
        "session_id": session_id,
        "cwd": str(repo),
        "transcript_path": "/private/transcript/that-must-not-be-read.jsonl",
    }


def test_runtime_change_without_red_green_evidence_is_unproven(
    sample_repo: Path, tmp_path: Path
) -> None:
    (sample_repo / "seam_runtime" / "feature.py").write_text("VALUE = 2\n", encoding="utf-8")

    result = session_end_closeout.handle_session_end(
        _event(sample_repo),
        repo_root=sample_repo,
        state_root=tmp_path / "state",
        dispatch=False,
    )

    request = json.loads(Path(result["request_path"]).read_text(encoding="utf-8"))
    request_schema = json.loads(REQUEST_SCHEMA.read_text(encoding="utf-8"))
    assert request["schema"] == "seam-agent-closeout-request/v1"
    assert set(request) == set(request_schema["required"]) == set(request_schema["properties"])
    assert request["change_class"] == "runtime"
    assert request["tdd_evidence"]["status"] == "TDD_UNPROVEN"
    assert request["context"]["source"] == "root_session_state"
    assert request["context"]["available"] is False
    assert request["authority"]["allowed_writes"] == []
    assert "transcript_path" not in json.dumps(request)


def test_root_supplied_session_state_can_prove_red_green_cycle(
    sample_repo: Path, tmp_path: Path
) -> None:
    (sample_repo / "seam_runtime" / "feature.py").write_text("VALUE = 2\n", encoding="utf-8")
    state_root = tmp_path / "state"
    sessions = state_root / "sessions"
    sessions.mkdir(parents=True)
    session_state = {
        "schema": "seam-agent-session-state/v1",
        "session_id": "session-123",
        "base_sha": _git(sample_repo, "rev-parse", "HEAD"),
        "objective": "Change the public feature value.",
        "plan": ["Pin the behavior", "Implement the change", "Verify closeout"],
        "constraints": ["Keep the public interface stable"],
        "affected_tests": ["tests/test_feature.py"],
        "tdd_cycles": [
            {
                "behavior": "feature exposes the new value",
                "test_refs": ["tests/test_feature.py::test_feature_value"],
                "implementation_refs": ["seam_runtime/feature.py"],
                "red": {
                    "command": "pytest tests/test_feature.py::test_feature_value -q",
                    "exit_code": 1,
                    "observed_at": "2026-08-31T18:00:00Z",
                    "fingerprint": "red-fingerprint",
                },
                "green": {
                    "command": "pytest tests/test_feature.py::test_feature_value -q",
                    "exit_code": 0,
                    "observed_at": "2026-08-31T18:02:00Z",
                    "fingerprint": "green-fingerprint",
                },
            }
        ],
    }
    (sessions / "session-123.json").write_text(
        json.dumps(session_state), encoding="utf-8"
    )

    result = session_end_closeout.handle_session_end(
        _event(sample_repo),
        repo_root=sample_repo,
        state_root=state_root,
        dispatch=False,
    )

    request = json.loads(Path(result["request_path"]).read_text(encoding="utf-8"))
    assert request["context"]["available"] is True
    assert request["context"]["objective"] == "Change the public feature value."
    assert request["tdd_evidence"]["status"] == "TDD_PROVEN"
    assert request["tdd_evidence"]["covered_runtime_paths"] == [
        "seam_runtime/feature.py"
    ]
    assert request["tdd_evidence"]["cycles"] == session_state["tdd_cycles"]


def test_schema_invalid_session_state_cannot_prove_tdd(
    sample_repo: Path, tmp_path: Path
) -> None:
    (sample_repo / "seam_runtime" / "feature.py").write_text("VALUE = 2\n", encoding="utf-8")
    state_root = tmp_path / "state"
    sessions = state_root / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "session-123.json").write_text(
        json.dumps(
            {
                "schema": "seam-agent-session-state/v1",
                "session_id": "session-123",
                "objective": "Missing required base_sha.",
                "plan": [],
                "constraints": [],
                "affected_tests": [],
                "tdd_cycles": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(session_end_closeout.SessionEndError, match="base_sha"):
        session_end_closeout.handle_session_end(
            _event(sample_repo),
            repo_root=sample_repo,
            state_root=state_root,
            dispatch=False,
        )


def test_unresolvable_session_base_fails_closed(sample_repo: Path, tmp_path: Path) -> None:
    (sample_repo / "seam_runtime" / "feature.py").write_text("VALUE = 2\n", encoding="utf-8")
    state_root = tmp_path / "state"
    sessions = state_root / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "session-123.json").write_text(
        json.dumps(
            {
                "schema": "seam-agent-session-state/v1",
                "session_id": "session-123",
                "base_sha": "f" * 40,
                "objective": "Use the recorded session base.",
                "plan": [],
                "constraints": [],
                "affected_tests": [],
                "tdd_cycles": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(session_end_closeout.SessionEndError, match="base_sha.*resolve"):
        session_end_closeout.handle_session_end(
            _event(sample_repo),
            repo_root=sample_repo,
            state_root=state_root,
            dispatch=False,
        )


def test_session_state_rejects_timestamp_without_time_and_timezone(sample_repo: Path) -> None:
    state = {
        "schema": "seam-agent-session-state/v1",
        "session_id": "session-123",
        "base_sha": _git(sample_repo, "rev-parse", "HEAD"),
        "objective": "Require RFC 3339 evidence.",
        "plan": [],
        "constraints": [],
        "affected_tests": [],
        "tdd_cycles": [
            {
                "behavior": "timestamps have timezones",
                "test_refs": ["tests/test_feature.py::test_feature_value"],
                "implementation_refs": ["seam_runtime/feature.py"],
                "red": {
                    "command": "pytest tests/test_feature.py -q",
                    "exit_code": 1,
                    "observed_at": "2026-08-31",
                    "fingerprint": "red",
                },
                "green": {
                    "command": "pytest tests/test_feature.py -q",
                    "exit_code": 0,
                    "observed_at": "2026-08-31T18:00:00",
                    "fingerprint": "green",
                },
            }
        ],
    }

    with pytest.raises(session_end_closeout.SessionEndError, match="RFC 3339"):
        session_end_closeout.validate_session_state(state)


def test_clean_tree_does_not_queue_a_request(sample_repo: Path, tmp_path: Path) -> None:
    result = session_end_closeout.handle_session_end(
        _event(sample_repo),
        repo_root=sample_repo,
        state_root=tmp_path / "state",
        dispatch=False,
    )

    assert result == {"status": "CLEAN_NO_REQUEST"}
    assert not (tmp_path / "state").exists()


def test_green_timestamp_before_red_does_not_prove_tdd() -> None:
    state = {
        "tdd_cycles": [
            {
                "behavior": "ordered TDD evidence",
                "test_refs": ["tests/test_feature.py::test_feature_value"],
                "implementation_refs": ["seam_runtime/feature.py"],
                "red": {
                    "command": "pytest tests/test_feature.py -q",
                    "exit_code": 1,
                    "observed_at": "2026-08-31T18:02:00Z",
                    "fingerprint": "red",
                },
                "green": {
                    "command": "pytest tests/test_feature.py -q",
                    "exit_code": 0,
                    "observed_at": "2026-08-31T18:00:00Z",
                    "fingerprint": "green",
                },
            }
        ]
    }

    result = session_end_closeout.assess_tdd(["seam_runtime/feature.py"], state)

    assert result["status"] == "TDD_UNPROVEN"
    assert result["cycle_count"] == 0


def test_duplicate_delivery_is_idempotent(sample_repo: Path, tmp_path: Path) -> None:
    (sample_repo / "seam_runtime" / "feature.py").write_text("VALUE = 2\n", encoding="utf-8")
    state_root = tmp_path / "state"

    first = session_end_closeout.handle_session_end(
        _event(sample_repo), repo_root=sample_repo, state_root=state_root, dispatch=False
    )
    second = session_end_closeout.handle_session_end(
        _event(sample_repo), repo_root=sample_repo, state_root=state_root, dispatch=False
    )

    assert first["status"] == "QUEUED"
    assert second["status"] == "ALREADY_QUEUED"
    assert first["request_id"] == second["request_id"]
    assert len(list((state_root / "requests").glob("*.json"))) == 1


def test_conflicting_existing_request_fails_closed(
    sample_repo: Path, tmp_path: Path
) -> None:
    (sample_repo / "seam_runtime" / "feature.py").write_text(
        "VALUE = 2\n", encoding="utf-8"
    )
    state_root = tmp_path / "state"
    first = session_end_closeout.handle_session_end(
        _event(sample_repo), repo_root=sample_repo, state_root=state_root, dispatch=False
    )
    request_path = Path(first["request_path"])
    request_path.write_text('{"schema":"tampered"}\n', encoding="utf-8")

    with pytest.raises(session_end_closeout.SessionEndError, match="conflicting"):
        session_end_closeout.handle_session_end(
            _event(sample_repo),
            repo_root=sample_repo,
            state_root=state_root,
            dispatch=False,
        )


def test_untracked_content_change_creates_a_new_exact_state_request(
    sample_repo: Path, tmp_path: Path
) -> None:
    untracked = sample_repo / "seam_runtime" / "new_feature.py"
    untracked.write_text("VALUE = 1\n", encoding="utf-8")
    state_root = tmp_path / "state"

    first = session_end_closeout.handle_session_end(
        _event(sample_repo), repo_root=sample_repo, state_root=state_root, dispatch=False
    )
    untracked.write_text("VALUE = 2\n", encoding="utf-8")
    second = session_end_closeout.handle_session_end(
        _event(sample_repo), repo_root=sample_repo, state_root=state_root, dispatch=False
    )

    assert first["status"] == second["status"] == "QUEUED"
    assert first["request_id"] != second["request_id"]
    assert len(list((state_root / "requests").glob("*.json"))) == 2


def test_truncated_display_paths_still_fail_closed_for_runtime_and_fingerprint(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (sample_repo / "a.txt").write_text("a\n", encoding="utf-8")
    (sample_repo / "b.txt").write_text("b\n", encoding="utf-8")
    omitted_runtime = sample_repo / "seam_runtime" / "omitted.py"
    omitted_runtime.write_text("VALUE = 1\n", encoding="utf-8")
    state_root = tmp_path / "state"
    monkeypatch.setattr(session_end_closeout, "MAX_CHANGED_PATHS", 2)

    first = session_end_closeout.handle_session_end(
        _event(sample_repo), repo_root=sample_repo, state_root=state_root, dispatch=False
    )
    first_request = json.loads(Path(first["request_path"]).read_text(encoding="utf-8"))

    assert first_request["repo"]["changed_paths"] == ["a.txt", "b.txt"]
    assert first_request["repo"]["changed_paths_truncated"] is True
    assert first_request["change_class"] == "runtime"
    assert first_request["tdd_evidence"]["status"] == "TDD_UNPROVEN"

    omitted_runtime.write_text("VALUE = 2\n", encoding="utf-8")
    second = session_end_closeout.handle_session_end(
        _event(sample_repo), repo_root=sample_repo, state_root=state_root, dispatch=False
    )

    assert second["request_id"] != first["request_id"]


def test_truncated_request_bounds_tdd_paths_and_stays_consumable(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in range(4):
        (sample_repo / "seam_runtime" / f"new_{index}.py").write_text(
            f"VALUE = {index}\n", encoding="utf-8"
        )
    state_root = tmp_path / "state"
    monkeypatch.setattr(session_end_closeout, "MAX_CHANGED_PATHS", 2)

    queued = session_end_closeout.handle_session_end(
        _event(sample_repo), repo_root=sample_repo, state_root=state_root, dispatch=False
    )
    request = json.loads(Path(queued["request_path"]).read_text(encoding="utf-8"))

    assert request["repo"]["changed_paths_truncated"] is True
    assert request["change_class"] == "runtime"
    assert request["tdd_evidence"]["status"] == "TDD_UNPROVEN"
    assert len(request["tdd_evidence"]["runtime_paths"]) <= 2


def test_git_timeout_fails_closed_before_writing_a_request(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (sample_repo / "seam_runtime" / "feature.py").write_text(
        "VALUE = 2\n", encoding="utf-8"
    )
    state_root = tmp_path / "state"

    def timing_out(command, *args, **kwargs):  # type: ignore[no-untyped-def]
        timeout = kwargs.get("timeout")
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise AssertionError("every Git subprocess must carry a positive deadline")
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(session_end_closeout.subprocess, "run", timing_out)

    with pytest.raises(session_end_closeout.SessionEndError, match="timed out|deadline"):
        session_end_closeout.handle_session_end(
            _event(sample_repo),
            repo_root=sample_repo,
            state_root=state_root,
            dispatch=False,
        )

    assert not state_root.exists()


def test_tracked_content_fingerprint_enforces_the_content_bound(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (sample_repo / "seam_runtime" / "feature.py").write_text(
        "VALUE = 200\n", encoding="utf-8"
    )
    state_root = tmp_path / "state"
    monkeypatch.setattr(session_end_closeout, "MAX_UNTRACKED_HASH_BYTES", 4)

    with pytest.raises(session_end_closeout.SessionEndError, match="content exceeds"):
        session_end_closeout.handle_session_end(
            _event(sample_repo),
            repo_root=sample_repo,
            state_root=state_root,
            dispatch=False,
        )

    assert not state_root.exists()


def test_untracked_replacement_between_stat_and_open_fails_closed(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    untracked = sample_repo / "seam_runtime" / "racy.py"
    untracked.write_bytes(b"12")
    original_os_open = os.open
    replaced = False

    def replacing_open(path, flags, *args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal replaced
        if Path(path) == untracked and flags & os.O_RDONLY == os.O_RDONLY and not replaced:
            replaced = True
            with Path(path).open("wb") as handle:
                handle.write(b"12345678")
        return original_os_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(session_end_closeout, "MAX_UNTRACKED_HASH_BYTES", 4)
    monkeypatch.setattr(session_end_closeout.os, "open", replacing_open)

    with pytest.raises(session_end_closeout.SessionEndError, match="untracked path changed|bound"):
        session_end_closeout.handle_session_end(
            _event(sample_repo),
            repo_root=sample_repo,
            state_root=tmp_path / "state",
            dispatch=False,
        )


def test_recursion_guard_does_not_create_or_dispatch_another_request(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(session_end_closeout.RECURSION_GUARD_ENV, "1")
    result = session_end_closeout.handle_session_end(
        _event(sample_repo),
        repo_root=sample_repo,
        state_root=tmp_path / "state",
        dispatch=False,
    )

    assert result["status"] == "SKIPPED_RECURSION_GUARD"
    assert not (tmp_path / "state").exists()


def test_cli_recursion_guard_runs_before_stdin_read(monkeypatch: pytest.MonkeyPatch) -> None:
    class FailingBuffer(io.BytesIO):
        def read(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("stdin must not be read under recursion guard")

    class GuardedStdin:
        buffer = FailingBuffer()

    monkeypatch.setenv(session_end_closeout.RECURSION_GUARD_ENV, "1")
    monkeypatch.setattr(session_end_closeout.sys, "stdin", GuardedStdin())

    assert session_end_closeout.main([]) == 0


def test_session_end_hook_is_additive_bounded_and_points_at_dispatcher() -> None:
    config = json.loads(HOOKS_CONFIG.read_text(encoding="utf-8"))
    session_end = config["hooks"]["SessionEnd"]
    command_hooks = [hook for group in session_end for hook in group["hooks"]]

    assert len(command_hooks) == 1
    hook = command_hooks[0]
    assert hook["type"] == "command"
    assert hook["command"] == (
        '/usr/bin/python3 "$(git rev-parse --show-toplevel)/tools/agents/'
        'session_end_closeout.py"'
    )
    # Codex caps SessionEnd hooks at three seconds.
    assert 1 <= hook["timeout"] <= 3


def test_closeout_receipt_schema_is_fail_closed() -> None:
    schema = json.loads(RECEIPT_SCHEMA.read_text(encoding="utf-8"))
    status_values = schema["properties"]["status"]["enum"]

    assert status_values == [
        "QUALIFIED",
        "NOT_QUALIFIED",
        "BLOCKED",
        "INDETERMINATE",
    ]
    assert schema["additionalProperties"] is False
    assert {"request_sha256", "tdd", "checks", "continuity", "next_action"} <= set(
        schema["required"]
    )


def test_closeout_request_schema_pins_bounded_context_and_authority() -> None:
    schema = json.loads(REQUEST_SCHEMA.read_text(encoding="utf-8"))

    assert schema["additionalProperties"] is False
    assert {"context", "tdd_evidence", "authority", "request_sha256"} <= set(
        schema["required"]
    )
    assert schema["properties"]["authority"]["properties"]["mode"]["const"] == "verify_only"
    assert schema["properties"]["authority"]["properties"]["allowed_writes"]["maxItems"] == 0
    assert schema["properties"]["repo"]["properties"]["changed_paths"]["maxItems"] == 512
    assert (
        schema["properties"]["repo"]["properties"]["changed_paths"]["items"][
            "maxLength"
        ]
        == 1000
    )
    forbidden = schema["properties"]["authority"]["properties"]["forbidden_actions"]
    assert forbidden["minItems"] == 1
    assert forbidden["maxItems"] == 32
    assert forbidden["items"] == {
        "type": "string",
        "minLength": 1,
        "maxLength": 1000,
    }
