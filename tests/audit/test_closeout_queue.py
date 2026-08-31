"""Behavioral contract for root-owned closeout request and receipt handling."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools.agents import closeout_queue, session_end_closeout


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "SEAM tests")
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "baseline")
    return repo


def _queued_request(sample_repo: Path, state_root: Path) -> dict[str, object]:
    (sample_repo / "README.md").write_text("changed\n", encoding="utf-8")
    return session_end_closeout.handle_session_end(
        {"session_id": "queue-test", "cwd": str(sample_repo)},
        repo_root=sample_repo,
        state_root=state_root,
        dispatch=False,
    )


def test_pending_returns_a_hash_validated_request_for_the_release_profile(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    queued = _queued_request(sample_repo, state_root)

    result = closeout_queue.pending(state_root)

    assert result["profile"] == "seam_release_orchestrator"
    assert [request["request_id"] for request in result["requests"]] == [
        queued["request_id"]
    ]


def _qualified_receipt(request: dict[str, object]) -> dict[str, object]:
    repo = request["repo"]
    assert isinstance(repo, dict)
    tdd = request["tdd_evidence"]
    assert isinstance(tdd, dict)
    checks = request["required_checks"]
    assert isinstance(checks, list)
    return {
        "schema": "seam-agent-closeout-receipt/v1",
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "session_id": request["session_id"],
        "completed_at": "2026-08-31T22:30:00Z",
        "status": "QUALIFIED",
        "supersedes_request_ids": [],
        "scope": {
            "head": repo["head"],
            "diff_fingerprint": repo["diff_fingerprint"],
            "matches_request": True,
        },
        "tdd": {"status": tdd["status"], "evidence": ["request evidence checked"]},
        "checks": [
            {
                "requirement": requirement,
                "command": requirement,
                "status": "PASS",
                "exit_code": 0,
                "evidence": "passed",
            }
            for requirement in checks
        ],
        "continuity": {"status": "PASS", "evidence": ["all continuity gates passed"]},
        "project_alignment": {"status": "ALIGNED", "evidence": ["plan matched"]},
        "next_action": "Root may complete closeout.",
    }


def test_root_stores_a_qualified_receipt_atomically_and_idempotently(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    queued = _queued_request(sample_repo, state_root)
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    receipt = _qualified_receipt(request)

    first = closeout_queue.store_receipt(request, receipt, state_root=state_root)
    receipt_path = Path(first["receipt_path"])

    assert first["status"] == "STORED"
    assert receipt_path.stat().st_mode & 0o777 == 0o600
    assert closeout_queue.pending(state_root)["requests"] == []
    assert closeout_queue.store_receipt(request, receipt, state_root=state_root)[
        "status"
    ] == "ALREADY_STORED"

    conflicting = {**receipt, "next_action": "Different content."}
    with pytest.raises(closeout_queue.CloseoutQueueError, match="conflicting"):
        closeout_queue.store_receipt(request, conflicting, state_root=state_root)


def test_cli_surfaces_pending_requests_and_stores_only_validated_receipts(
    sample_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_root = tmp_path / "state"
    queued = _queued_request(sample_repo, state_root)
    request_path = Path(str(queued["request_path"]))
    request = json.loads(request_path.read_text(encoding="utf-8"))
    receipt_path = tmp_path / "candidate-receipt.json"
    receipt_path.write_text(
        json.dumps(_qualified_receipt(request)), encoding="utf-8"
    )

    assert closeout_queue.main(["--state-root", str(state_root), "pending"]) == 0
    pending_output = json.loads(capsys.readouterr().out)
    assert pending_output["profile"] == "seam_release_orchestrator"
    assert len(pending_output["requests"]) == 1

    assert (
        closeout_queue.main(
            [
                "--state-root",
                str(state_root),
                "store",
                "--request",
                str(request_path),
                "--receipt",
                str(receipt_path),
            ]
        )
        == 0
    )
    stored_output = json.loads(capsys.readouterr().out)
    assert stored_output["status"] == "STORED"
    assert closeout_queue.pending(state_root)["requests"] == []


def test_pending_rejects_symlinked_queue_records(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    queued = _queued_request(sample_repo, state_root)
    request_path = Path(str(queued["request_path"]))
    (request_path.parent / "symlinked.json").symlink_to(request_path)

    with pytest.raises(closeout_queue.CloseoutQueueError, match="regular file"):
        closeout_queue.pending(state_root)


def test_pending_rejects_semantically_tampered_tdd_even_with_a_fresh_hash(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    queued = _queued_request(sample_repo, state_root)
    request_path = Path(str(queued["request_path"]))
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["tdd_evidence"]["status"] = "TDD_PROVEN"
    request["tdd_evidence"]["cycle_count"] = -1
    request["request_sha256"] = closeout_queue._request_hash(request)
    request_path.write_text(json.dumps(request), encoding="utf-8")

    with pytest.raises(closeout_queue.CloseoutQueueError, match="TDD"):
        closeout_queue.pending(state_root)


def test_pending_rejects_runtime_path_reclassified_as_non_runtime(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    queued = _queued_request(sample_repo, state_root)
    request_path = Path(str(queued["request_path"]))
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["repo"]["changed_paths"].append("seam_runtime/hidden.py")
    request["request_sha256"] = closeout_queue._request_hash(request)
    request_path.write_text(json.dumps(request), encoding="utf-8")

    with pytest.raises(closeout_queue.CloseoutQueueError, match="runtime classification"):
        closeout_queue.pending(state_root)


def test_non_qualified_receipt_remains_pending(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    queued = _queued_request(sample_repo, state_root)
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    receipt = _qualified_receipt(request)
    receipt["status"] = "NOT_QUALIFIED"
    receipt["checks"][0]["status"] = "FAIL"
    receipt["checks"][0]["exit_code"] = 1
    receipt["next_action"] = "Repair the failed check and produce a new exact-state request."

    closeout_queue.store_receipt(request, receipt, state_root=state_root)

    assert [item["request_id"] for item in closeout_queue.pending(state_root)["requests"]] == [
        request["request_id"]
    ]


def test_non_qualified_status_requires_matching_failure_semantics(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    queued = _queued_request(sample_repo, state_root)
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    receipt = _qualified_receipt(request)
    receipt["status"] = "BLOCKED"

    with pytest.raises(closeout_queue.CloseoutQueueError, match="BLOCKED"):
        closeout_queue.store_receipt(request, receipt, state_root=state_root)


def test_qualified_receipt_rejects_truncated_request_scope(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_root = tmp_path / "state"
    (sample_repo / "README.md").write_text("changed\n", encoding="utf-8")
    (sample_repo / "notes.txt").write_text("second\n", encoding="utf-8")
    monkeypatch.setattr(session_end_closeout, "MAX_CHANGED_PATHS", 1)
    queued = session_end_closeout.handle_session_end(
        {"session_id": "queue-truncated", "cwd": str(sample_repo)},
        repo_root=sample_repo,
        state_root=state_root,
        dispatch=False,
    )
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))

    with pytest.raises(closeout_queue.CloseoutQueueError, match="truncated"):
        closeout_queue.store_receipt(
            request, _qualified_receipt(request), state_root=state_root
        )


def test_store_rejects_symlinked_receipt_directory(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    queued = _queued_request(sample_repo, state_root)
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    external = tmp_path / "external-receipts"
    external.mkdir()
    (state_root / "receipts").symlink_to(external, target_is_directory=True)

    with pytest.raises(closeout_queue.CloseoutQueueError, match="receipt directory"):
        closeout_queue.store_receipt(
            request, _qualified_receipt(request), state_root=state_root
        )
    assert list(external.iterdir()) == []


def test_non_qualified_receipt_can_be_superseded_by_immutable_qualified_attempt(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    queued = _queued_request(sample_repo, state_root)
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    failed = _qualified_receipt(request)
    failed["status"] = "NOT_QUALIFIED"
    failed["checks"][0]["status"] = "FAIL"
    failed["checks"][0]["exit_code"] = 1
    failed["next_action"] = "Retry after repair."
    closeout_queue.store_receipt(request, failed, state_root=state_root)

    retry = _qualified_receipt(request)
    retry["completed_at"] = "2026-08-31T22:31:00Z"
    result = closeout_queue.store_receipt(request, retry, state_root=state_root)

    assert result["status"] == "STORED_ATTEMPT"
    assert Path(result["receipt_path"]).is_file()
    assert closeout_queue.pending(state_root)["requests"] == []
    assert len(list((state_root / "receipt-attempts").glob("*.json"))) == 1


def test_pending_rejects_dangling_receipt_symlink(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    queued = _queued_request(sample_repo, state_root)
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    receipt_path = Path(request["receipt_path"])
    receipt_path.parent.mkdir(parents=True)
    receipt_path.symlink_to(tmp_path / "missing-receipt.json")

    with pytest.raises(closeout_queue.CloseoutQueueError, match="regular file"):
        closeout_queue.pending(state_root)


def test_qualified_new_exact_state_supersedes_failed_request(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    first_queued = _queued_request(sample_repo, state_root)
    first = json.loads(
        Path(str(first_queued["request_path"])).read_text(encoding="utf-8")
    )
    failed = _qualified_receipt(first)
    failed["status"] = "NOT_QUALIFIED"
    failed["checks"][0]["status"] = "FAIL"
    failed["checks"][0]["exit_code"] = 1
    failed["next_action"] = "Repair and qualify the resulting exact state."
    closeout_queue.store_receipt(first, failed, state_root=state_root)

    (sample_repo / "README.md").write_text("repaired\n", encoding="utf-8")
    second_queued = session_end_closeout.handle_session_end(
        {"session_id": "queue-successor", "cwd": str(sample_repo)},
        repo_root=sample_repo,
        state_root=state_root,
        dispatch=False,
    )
    second = json.loads(
        Path(str(second_queued["request_path"])).read_text(encoding="utf-8")
    )
    qualified = _qualified_receipt(second)
    qualified["supersedes_request_ids"] = [first["request_id"]]

    closeout_queue.store_receipt(second, qualified, state_root=state_root)

    assert closeout_queue.pending(state_root)["requests"] == []


def test_qualified_request_cannot_supersede_unreviewed_request(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    first_queued = _queued_request(sample_repo, state_root)
    first = json.loads(
        Path(str(first_queued["request_path"])).read_text(encoding="utf-8")
    )
    (sample_repo / "README.md").write_text("new exact state\n", encoding="utf-8")
    second_queued = session_end_closeout.handle_session_end(
        {"session_id": "queue-successor", "cwd": str(sample_repo)},
        repo_root=sample_repo,
        state_root=state_root,
        dispatch=False,
    )
    second = json.loads(
        Path(str(second_queued["request_path"])).read_text(encoding="utf-8")
    )
    qualified = _qualified_receipt(second)
    qualified["supersedes_request_ids"] = [first["request_id"]]

    with pytest.raises(closeout_queue.CloseoutQueueError, match="non-qualified"):
        closeout_queue.store_receipt(second, qualified, state_root=state_root)


def test_pending_rejects_mismatched_receipt_attempt_content_address(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    queued = _queued_request(sample_repo, state_root)
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    failed = _qualified_receipt(request)
    failed["status"] = "NOT_QUALIFIED"
    failed["checks"][0]["status"] = "FAIL"
    failed["checks"][0]["exit_code"] = 1
    failed["next_action"] = "Retry after repair."
    closeout_queue.store_receipt(request, failed, state_root=state_root)
    retry = _qualified_receipt(request)
    retry["completed_at"] = "2026-08-31T22:31:00Z"
    stored = closeout_queue.store_receipt(request, retry, state_root=state_root)
    attempt = Path(stored["receipt_path"])
    forged_name = attempt.parent / f"{request['request_id']}-{'f' * 64}.json"
    forged_name.write_bytes(attempt.read_bytes())

    with pytest.raises(closeout_queue.CloseoutQueueError, match="content address"):
        closeout_queue.pending(state_root)


def test_pending_rejects_symlinked_populated_receipt_directory(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    queued = _queued_request(sample_repo, state_root)
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    external = tmp_path / "external-receipts"
    external.mkdir()
    external_receipt = external / f"{request['request_id']}.json"
    external_receipt.write_text(
        json.dumps(_qualified_receipt(request)), encoding="utf-8"
    )
    (state_root / "receipts").symlink_to(external, target_is_directory=True)

    with pytest.raises(closeout_queue.CloseoutQueueError, match="receipt directory"):
        closeout_queue.pending(state_root)
