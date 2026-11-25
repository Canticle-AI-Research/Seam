"""Behavioral contract for root-owned closeout request and receipt handling."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools.agents import assurance, closeout_queue, context_guardian, session_end_closeout


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


def test_admit_cli_blocks_retained_pending_queue_and_missing_registered_root(
    sample_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    retained = tmp_path / "retained"
    _git(sample_repo, "worktree", "add", "-qb", "retained-test", str(retained))
    retained_state = retained / ".seam" / "orchestration" / "session-end"
    (retained / "README.md").write_text("retained change\n", encoding="utf-8")
    queued = session_end_closeout.handle_session_end(
        {"session_id": "retained-queue", "cwd": str(retained)},
        repo_root=retained,
        state_root=retained_state,
        dispatch=False,
    )

    command = [
        "--repo-root",
        str(sample_repo),
        "admit",
        "--register-root",
        str(retained),
    ]
    assert closeout_queue.main(command) == 2
    assert queued["request_id"] in capsys.readouterr().err

    Path(str(queued["request_path"])).unlink()
    assert closeout_queue.main(command) == 0
    admitted = json.loads(capsys.readouterr().out)
    assert admitted["schema"] == "seam-queue-admission/v1"
    assert admitted["registered_roots"] == [str(retained.resolve())]

    common_dir = Path(
        _git(sample_repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    )
    (common_dir / "seam-orchestration" / "queue-admission.json").unlink()
    _git(sample_repo, "worktree", "remove", "--force", str(retained))
    assert closeout_queue.main(["--repo-root", str(sample_repo), "admit"]) == 2
    assert "registered root is missing" in capsys.readouterr().err


def test_admit_accepts_registered_receipt_only_root_after_worktree_metadata_is_removed(
    sample_repo: Path, tmp_path: Path
) -> None:
    (sample_repo / ".gitignore").write_text(".seam/\n", encoding="utf-8")
    _git(sample_repo, "add", ".gitignore")
    _git(sample_repo, "commit", "-qm", "ignore local orchestration")
    retained = tmp_path / "receipt-only"
    _git(sample_repo, "worktree", "add", "-qb", "receipt-only", str(retained))
    state_root = retained / ".seam" / "orchestration" / "session-end"
    (retained / "README.md").write_text("receipt-only change\n", encoding="utf-8")
    queued = session_end_closeout.handle_session_end(
        {"session_id": "receipt-only", "cwd": str(retained)},
        repo_root=retained,
        state_root=state_root,
        dispatch=False,
    )
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    closeout_queue.store_receipt(
        request, _qualified_receipt(request), state_root=state_root
    )
    (retained / ".git").unlink()

    admitted = closeout_queue.admit(sample_repo, register_roots=[retained])

    assert admitted["pending_request_ids"] == []
    assert admitted["registered_roots"] == [str(retained.resolve())]
    assert admitted["record_sha256s"]


def test_admit_detects_validated_receipt_mutation_between_inventory_reads(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (sample_repo / ".gitignore").write_text(".seam/\n", encoding="utf-8")
    _git(sample_repo, "add", ".gitignore")
    _git(sample_repo, "commit", "-qm", "ignore local orchestration")
    state_root = sample_repo / ".seam" / "orchestration" / "session-end"
    queued = _queued_request(sample_repo, state_root)
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    stored = closeout_queue.store_receipt(
        request, _qualified_receipt(request), state_root=state_root
    )
    receipt_path = Path(stored["receipt_path"])
    original_inventory = closeout_queue._admission_inventory
    calls = 0

    def mutate_after_first(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        result = original_inventory(*args, **kwargs)
        calls += 1
        if calls == 1:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["next_action"] = "A different valid next action."
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        return result

    monkeypatch.setattr(closeout_queue, "_admission_inventory", mutate_after_first)

    with pytest.raises(closeout_queue.CloseoutQueueError, match="changed while reading"):
        closeout_queue.admit(sample_repo)


def test_admit_rejects_symlinked_standard_queue_root(
    sample_repo: Path, tmp_path: Path
) -> None:
    external = tmp_path / "unrelated-empty-queue"
    external.mkdir()
    orchestration = sample_repo / ".seam" / "orchestration"
    orchestration.mkdir(parents=True)
    (orchestration / "session-end").symlink_to(external, target_is_directory=True)

    with pytest.raises(closeout_queue.CloseoutQueueError, match="queue path.*real directory"):
        closeout_queue.admit(sample_repo)


def test_admit_accepts_dispositive_request_canonically_hosted_by_primary_queue(
    sample_repo: Path, tmp_path: Path
) -> None:
    (sample_repo / ".gitignore").write_text(".seam/\n", encoding="utf-8")
    _git(sample_repo, "add", ".gitignore")
    _git(sample_repo, "commit", "-qm", "ignore local orchestration")
    retained = tmp_path / "historical-worktree"
    _git(sample_repo, "worktree", "add", "-qb", "historical-hosted", str(retained))
    (retained / "README.md").write_text("historical change\n", encoding="utf-8")
    primary_queue = sample_repo / ".seam" / "orchestration" / "session-end"
    queued = session_end_closeout.handle_session_end(
        {"session_id": "historical-hosted", "cwd": str(retained)},
        repo_root=retained,
        state_root=primary_queue,
        dispatch=False,
    )
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))

    with pytest.raises(
        closeout_queue.CloseoutQueueError, match="ownership is inconsistent"
    ):
        closeout_queue.admit(sample_repo)

    nonqualified = _qualified_receipt(request)
    nonqualified["status"] = "NOT_QUALIFIED"
    checks = nonqualified["checks"]
    assert isinstance(checks, list) and isinstance(checks[0], dict)
    checks[0]["status"] = "FAIL"
    checks[0]["exit_code"] = 1
    closeout_queue.store_receipt(request, nonqualified, state_root=primary_queue)
    with pytest.raises(
        closeout_queue.CloseoutQueueError, match="ownership is inconsistent"
    ):
        closeout_queue.admit(sample_repo)

    closeout_queue.store_receipt(
        request, _qualified_receipt(request), state_root=primary_queue
    )
    admitted = closeout_queue.admit(sample_repo)

    assert admitted["pending_request_ids"] == []
    assert any(
        f"|request|{request['request_id']}|" in item
        for item in admitted["record_sha256s"]
    )


def _runtime_queued_request(sample_repo: Path, state_root: Path) -> dict[str, object]:
    runtime_path = sample_repo / "seam_runtime" / "feature.py"
    runtime_path.parent.mkdir()
    runtime_path.write_text("VALUE = 2\n", encoding="utf-8")
    sessions = state_root / "sessions"
    sessions.mkdir(parents=True)
    session_state = {
        "schema": "seam-agent-session-state/v1",
        "session_id": "queue-runtime",
        "base_sha": _git(sample_repo, "rev-parse", "HEAD"),
        "objective": "Change the runtime feature.",
        "plan": ["Pin the behavior", "Implement it"],
        "constraints": [],
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
    (sessions / "queue-runtime.json").write_text(
        json.dumps(session_state), encoding="utf-8"
    )
    return session_end_closeout.handle_session_end(
        {"session_id": "queue-runtime", "cwd": str(sample_repo)},
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


def test_pending_accepts_v1_request_from_pre_cycle_evidence_producer(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    queued = _runtime_queued_request(sample_repo, state_root)
    request_path = Path(str(queued["request_path"]))
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["tdd_evidence"].pop("cycles")
    request["request_sha256"] = closeout_queue._request_hash(request)
    request_path.write_text(json.dumps(request), encoding="utf-8")

    result = closeout_queue.pending(state_root)

    assert [item["request_id"] for item in result["requests"]] == [
        request["request_id"]
    ]


def test_pending_preserves_immutable_legacy_documentation_classification(sample_repo, tmp_path):
    page = sample_repo / "installers/README.md"
    page.parent.mkdir()
    page.write_text("# Installer docs\n", encoding="utf-8")
    state_root = tmp_path / "state"
    queued = _queued_request(sample_repo, state_root)
    path = Path(str(queued["request_path"]))
    request = json.loads(path.read_text())
    # Original v1 producers treated every path under installers/ as runtime.
    request["change_class"] = "runtime"
    request["tdd_evidence"].update(
        status="TDD_UNPROVEN", runtime_paths=["installers/README.md"],
        covered_runtime_paths=[], missing_runtime_paths=["installers/README.md"], cycle_count=0,
    )
    request["request_sha256"] = closeout_queue._request_hash(request)
    original = json.dumps(request)
    path.write_text(original)
    pending = closeout_queue.pending(state_root)
    assert pending["requests"][0]["tdd_evidence"]["status"] == "TDD_UNPROVEN"
    assert path.read_text() == original


def test_legacy_documentation_compatibility_cannot_hide_executable_changes(sample_repo, tmp_path):
    installer = sample_repo / "installers"
    installer.mkdir()
    (installer / "README.md").write_text("# Installer docs\n", encoding="utf-8")
    (installer / "install.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    state_root = tmp_path / "state"
    queued = _queued_request(sample_repo, state_root)
    path = Path(str(queued["request_path"]))
    request = json.loads(path.read_text())
    request["tdd_evidence"].update(
        status="TDD_UNPROVEN", runtime_paths=["installers/README.md"],
        covered_runtime_paths=[], missing_runtime_paths=["installers/README.md"], cycle_count=0,
    )
    request["request_sha256"] = closeout_queue._request_hash(request)
    path.write_text(json.dumps(request))
    with pytest.raises(closeout_queue.CloseoutQueueError, match="runtime paths"):
        closeout_queue.pending(state_root)


def test_store_rejects_new_qualified_receipt_for_legacy_runtime_request(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    queued = _runtime_queued_request(sample_repo, state_root)
    request_path = Path(str(queued["request_path"]))
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["tdd_evidence"].pop("cycles")
    request["request_sha256"] = closeout_queue._request_hash(request)
    request_path.write_text(json.dumps(request), encoding="utf-8")

    with pytest.raises(closeout_queue.CloseoutQueueError, match="cycle evidence"):
        closeout_queue.store_receipt(
            request,
            _qualified_receipt(request),
            state_root=state_root,
        )
    assert not Path(request["receipt_path"]).exists()


def test_existing_legacy_qualified_receipt_is_historical_not_dispositive(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    queued = _runtime_queued_request(sample_repo, state_root)
    request_path = Path(str(queued["request_path"]))
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["tdd_evidence"].pop("cycles")
    request["request_sha256"] = closeout_queue._request_hash(request)
    request_path.write_text(json.dumps(request), encoding="utf-8")
    receipt_path = Path(request["receipt_path"])
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(
        json.dumps(_qualified_receipt(request)), encoding="utf-8"
    )

    result = closeout_queue.pending(state_root)

    assert [item["request_id"] for item in result["requests"]] == [
        request["request_id"]
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


def test_new_registered_qualified_receipt_requires_current_assurance_and_guardian(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    sessions = state_root / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "queue-test.json").write_text(
        json.dumps(
            {
                "schema": "seam-agent-session-state/v1",
                "session_id": "queue-test",
                "base_sha": _git(sample_repo, "rev-parse", "HEAD"),
                "objective": "Require exact-state assurance before qualification.",
                "plan": [],
                "constraints": [],
                "affected_tests": [],
                "tdd_cycles": [],
            }
        ),
        encoding="utf-8",
    )
    (sample_repo / "README.md").write_text("changed\n", encoding="utf-8")
    _git(sample_repo, "commit", "-qam", "candidate")
    queued = session_end_closeout.handle_session_end(
        {"session_id": "queue-test", "cwd": str(sample_repo)},
        repo_root=sample_repo,
        state_root=state_root,
        dispatch=False,
    )
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    receipt = _qualified_receipt(request)
    session_id = str(request["session_id"])
    repo = request["repo"]
    assert isinstance(repo, dict)
    assurance.register(sample_repo, session_id, str(repo["base_sha"]))

    with pytest.raises(closeout_queue.CloseoutQueueError, match="accepted assurance"):
        closeout_queue.store_receipt(request, receipt, state_root=state_root)

    report = {
        "schema": "seam-independent-assurance/v1",
        "repository": "Canticle-AI-Research/Seam",
        "session_id": session_id,
        "base_sha": repo["base_sha"],
        "head": repo["head"],
        "changed_paths": repo["changed_paths"],
        "content_sha256": repo["diff_fingerprint"],
        "reviewed_at": "2026-10-17T05:00:00Z",
        "reviewer": "independent-reviewer",
        "status": "PASS",
        "continuity_included": True,
        "summary": ["Reviewed exact closeout scope and continuity."],
    }
    report_path = tmp_path / "assurance.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    assert assurance.accept(sample_repo, session_id, report_path)["status"] == "ACCEPTED"
    context_guardian.recover_unexpected_compaction(
        session_id=session_id,
        event_id="unexpected-after-review",
        summary=["Automatic compaction occurred after assurance."],
        next_step="Create a successor session before qualification.",
        state_root=sample_repo / ".seam" / "orchestration" / "context",
        handoff_root=sample_repo / ".context-handoffs",
    )

    with pytest.raises(
        closeout_queue.CloseoutQueueError, match="unexpected compaction recovery"
    ):
        closeout_queue.store_receipt(request, receipt, state_root=state_root)


def test_assurance_cutover_rejects_new_qualified_request_without_registration(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    base = _git(sample_repo, "rev-parse", "HEAD")
    assurance.register(sample_repo, "different-session", base)
    queued = _queued_request(sample_repo, state_root)
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))

    with pytest.raises(closeout_queue.CloseoutQueueError, match="not registered"):
        closeout_queue.store_receipt(
            request, _qualified_receipt(request), state_root=state_root
        )


def test_request_bound_assurance_admits_pre_enforcement_queued_request(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    base = _git(sample_repo, "rev-parse", "HEAD")
    sessions = state_root / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "queue-test.json").write_text(
        json.dumps(
            {
                "schema": "seam-agent-session-state/v1",
                "session_id": "queue-test",
                "base_sha": base,
                "objective": "Close an immutable pre-enforcement request.",
                "plan": [],
                "constraints": [],
                "affected_tests": [],
                "tdd_cycles": [],
            }
        ),
        encoding="utf-8",
    )
    (sample_repo / "README.md").write_text("candidate\n", encoding="utf-8")
    _git(sample_repo, "commit", "-qam", "candidate")
    queued = session_end_closeout.handle_session_end(
        {"session_id": "queue-test", "cwd": str(sample_repo)},
        repo_root=sample_repo,
        state_root=state_root,
        dispatch=False,
    )
    request_path = Path(str(queued["request_path"]))
    request = json.loads(request_path.read_text(encoding="utf-8"))
    repo = request["repo"]
    assert isinstance(repo, dict)
    assurance.register(sample_repo, "different-session", base)
    report = {
        "schema": "seam-independent-assurance/v1",
        "repository": "Canticle-AI-Research/Seam",
        "session_id": "queue-test",
        "base_sha": repo["base_sha"],
        "head": repo["head"],
        "changed_paths": repo["changed_paths"],
        "content_sha256": repo["diff_fingerprint"],
        "reviewed_at": "2026-10-17T05:00:00Z",
        "reviewer": "independent-reviewer",
        "status": "PASS",
        "continuity_included": True,
        "summary": ["Reviewed the immutable queued request."],
    }
    report_path = tmp_path / "request-assurance.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    accepted = assurance.accept_request(
        sample_repo, request_path, report_path, state_root
    )
    stored = closeout_queue.store_receipt(
        request, _qualified_receipt(request), state_root=state_root
    )

    assert accepted["status"] == "ACCEPTED"
    assert stored["status"] == "STORED"


@pytest.mark.parametrize("drift", ["content", "head"])
def test_store_recomputes_live_scope_before_admitting_receipt(
    sample_repo: Path, tmp_path: Path, drift: str
) -> None:
    state_root = tmp_path / "state"
    queued = _queued_request(sample_repo, state_root)
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    receipt = _qualified_receipt(request)
    if drift == "content":
        (sample_repo / "README.md").write_text("drifted content\n", encoding="utf-8")
    else:
        _git(sample_repo, "add", "README.md")
        _git(sample_repo, "commit", "-qm", "drifted head")

    with pytest.raises(closeout_queue.CloseoutQueueError, match="live Git scope drifted"):
        closeout_queue.store_receipt(request, receipt, state_root=state_root)


def test_store_accepts_indeterminate_receipt_describing_stable_live_mismatch(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    stale_queued = _queued_request(sample_repo, state_root)
    stale_request = json.loads(
        Path(str(stale_queued["request_path"])).read_text(encoding="utf-8")
    )
    (sample_repo / "README.md").write_text("current state\n", encoding="utf-8")
    current_queued = session_end_closeout.handle_session_end(
        {"session_id": "queue-current", "cwd": str(sample_repo)},
        repo_root=sample_repo,
        state_root=state_root,
        dispatch=False,
    )
    current_request = json.loads(
        Path(str(current_queued["request_path"])).read_text(encoding="utf-8")
    )
    receipt = _qualified_receipt(stale_request)
    receipt["status"] = "INDETERMINATE"
    receipt["scope"] = {
        "head": current_request["repo"]["head"],
        "diff_fingerprint": current_request["repo"]["diff_fingerprint"],
        "matches_request": False,
    }
    receipt["next_action"] = "Qualify the newer exact-state request."

    stored = closeout_queue.store_receipt(
        stale_request, receipt, state_root=state_root
    )

    assert stored["status"] == "STORED"


def test_store_rejects_false_mismatch_when_live_scope_still_matches_request(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    queued = _queued_request(sample_repo, state_root)
    request = json.loads(
        Path(str(queued["request_path"])).read_text(encoding="utf-8")
    )
    receipt = _qualified_receipt(request)
    receipt["status"] = "INDETERMINATE"
    receipt["scope"] = {
        "head": "f" * 40,
        "diff_fingerprint": "f" * 64,
        "matches_request": False,
    }
    receipt["next_action"] = "Recompute the actual current scope."

    with pytest.raises(closeout_queue.CloseoutQueueError, match="claims drift"):
        closeout_queue.store_receipt(request, receipt, state_root=state_root)
    assert not Path(request["receipt_path"]).exists()


def test_current_qualified_request_supersedes_stale_indeterminate_mismatch(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    stale_queued = _queued_request(sample_repo, state_root)
    stale_request = json.loads(
        Path(str(stale_queued["request_path"])).read_text(encoding="utf-8")
    )
    (sample_repo / "README.md").write_text("current state\n", encoding="utf-8")
    current_queued = session_end_closeout.handle_session_end(
        {"session_id": "queue-current", "cwd": str(sample_repo)},
        repo_root=sample_repo,
        state_root=state_root,
        dispatch=False,
    )
    current_request = json.loads(
        Path(str(current_queued["request_path"])).read_text(encoding="utf-8")
    )
    stale_receipt = _qualified_receipt(stale_request)
    stale_receipt["status"] = "INDETERMINATE"
    stale_receipt["scope"] = {
        "head": current_request["repo"]["head"],
        "diff_fingerprint": current_request["repo"]["diff_fingerprint"],
        "matches_request": False,
    }
    stale_receipt["next_action"] = "Qualify the newer exact-state request."
    closeout_queue.store_receipt(
        stale_request, stale_receipt, state_root=state_root
    )
    current_receipt = _qualified_receipt(current_request)
    current_receipt["supersedes_request_ids"] = [stale_request["request_id"]]

    stored = closeout_queue.store_receipt(
        current_request, current_receipt, state_root=state_root
    )

    assert stored["status"] == "STORED"
    assert closeout_queue.pending(state_root)["requests"] == []


def test_store_rejects_mutation_between_repeated_live_scope_signatures(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_root = tmp_path / "state"
    queued = _queued_request(sample_repo, state_root)
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    receipt = _qualified_receipt(request)
    original_fingerprint = closeout_queue._fingerprint
    fingerprint_calls = 0

    def mutate_after_first_fingerprint(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal fingerprint_calls
        fingerprint = original_fingerprint(*args, **kwargs)
        fingerprint_calls += 1
        if fingerprint_calls == 1:
            (sample_repo / "README.md").write_text(
                "mutated between signatures\n", encoding="utf-8"
            )
        return fingerprint

    monkeypatch.setattr(closeout_queue, "_fingerprint", mutate_after_first_fingerprint)

    with pytest.raises(closeout_queue.CloseoutQueueError, match="did not remain stable"):
        closeout_queue.store_receipt(request, receipt, state_root=state_root)
    assert not Path(request["receipt_path"]).exists()


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


def test_request_tdd_summary_must_recompute_from_embedded_cycles(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = tmp_path / "state"
    queued = _runtime_queued_request(sample_repo, state_root)
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    request["tdd_evidence"]["status"] = "TDD_UNPROVEN"
    request["tdd_evidence"]["covered_runtime_paths"] = []
    request["tdd_evidence"]["missing_runtime_paths"] = ["seam_runtime/feature.py"]
    request["request_sha256"] = closeout_queue._request_hash(request)

    with pytest.raises(closeout_queue.CloseoutQueueError, match="recompute"):
        closeout_queue.validate_request(request, state_root=state_root)


@pytest.mark.parametrize("invalid", ["changed_path", "empty_forbidden_actions"])
def test_request_validator_enforces_schema_path_and_authority_bounds(
    sample_repo: Path, tmp_path: Path, invalid: str
) -> None:
    state_root = tmp_path / "state"
    queued = _queued_request(sample_repo, state_root)
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    if invalid == "changed_path":
        request["repo"]["changed_paths"] = ["x" * 1001]
    else:
        request["authority"]["forbidden_actions"] = []
    request["request_sha256"] = closeout_queue._request_hash(request)

    with pytest.raises(closeout_queue.CloseoutQueueError, match="changed_paths|forbidden"):
        closeout_queue.validate_request(request, state_root=state_root)


@pytest.mark.parametrize("field", ["command", "evidence", "next_action"])
def test_receipt_validator_enforces_schema_text_bounds(
    sample_repo: Path, tmp_path: Path, field: str
) -> None:
    state_root = tmp_path / "state"
    queued = _queued_request(sample_repo, state_root)
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    receipt = _qualified_receipt(request)
    if field == "next_action":
        receipt[field] = "x" * 2001
    else:
        receipt["checks"][0][field] = "x" * 2001

    with pytest.raises(closeout_queue.CloseoutQueueError, match=field):
        closeout_queue.validate_receipt(request, receipt, state_root=state_root)


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


def test_relative_state_root_queues_an_absolute_receipt_path(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    queued = _queued_request(sample_repo, Path("state"))
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))

    assert Path(request["receipt_path"]).is_absolute()
    assert [item["request_id"] for item in closeout_queue.pending(tmp_path / "state")["requests"]] == [
        request["request_id"]
    ]


def _repo_local_request(sample_repo: Path, receipt_path: str) -> tuple[Path, dict[str, object]]:
    (sample_repo / ".git" / "info" / "exclude").write_text(".seam/\n", encoding="utf-8")
    state_root = sample_repo / ".seam" / "orchestration" / "session-end"
    queued = _queued_request(sample_repo, state_root)
    request_path = Path(str(queued["request_path"]))
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["receipt_path"] = receipt_path.format(request_id=request["request_id"])
    request["request_sha256"] = closeout_queue._request_hash(request)
    request_path.write_text(json.dumps(request), encoding="utf-8")
    return state_root, request


def test_pending_accepts_legacy_repo_relative_receipt_path(sample_repo: Path) -> None:
    state_root, request = _repo_local_request(
        sample_repo, ".seam/orchestration/session-end/receipts/{request_id}.json"
    )

    result = closeout_queue.pending(state_root)

    assert [item["request_id"] for item in result["requests"]] == [request["request_id"]]


@pytest.mark.parametrize(
    "receipt_path",
    [
        "receipts/{request_id}.json",
        ".seam/orchestration/session-end/../session-end/receipts/{request_id}.json",
        "../outside/receipts/{request_id}.json",
        ".seam/orchestration/session-end/receipts/other.json",
    ],
)
def test_relative_receipt_path_must_name_the_exact_canonical_receipt(
    sample_repo: Path, receipt_path: str
) -> None:
    state_root, request = _repo_local_request(sample_repo, receipt_path)

    with pytest.raises(closeout_queue.CloseoutQueueError, match="receipt_path"):
        closeout_queue.validate_request(request, state_root=state_root)


# --- Operator-authorized retirement of queue records with no unique work ----


def _publish_origin(sample_repo: Path, tmp_path: Path) -> str:
    """Give the sample repository a real origin holding its current HEAD."""

    origin = tmp_path / "origin.git"
    if not origin.exists():
        _git(tmp_path, "init", "-q", "--bare", str(origin))
        _git(sample_repo, "remote", "add", "origin", str(origin))
    _git(sample_repo, "push", "-q", "-f", "origin", "HEAD:refs/heads/main")
    return _git(sample_repo, "rev-parse", "HEAD")


def _standard_queue(sample_repo: Path) -> Path:
    (sample_repo / ".gitignore").write_text(".seam/\n", encoding="utf-8")
    _git(sample_repo, "add", ".gitignore")
    _git(sample_repo, "commit", "-qm", "ignore local orchestration")
    return sample_repo / ".seam" / "orchestration" / "session-end"


def _sha(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _retirement_review(
    tmp_path: Path,
    *,
    kind: str,
    request: dict[str, object],
    state_root: Path,
    preserved_commit: str,
    receipt_bytes: bytes | None = None,
    missing: list[str] | None = None,
    **overrides: object,
) -> Path:
    from datetime import datetime, timedelta, timezone

    repo = request["repo"]
    assert isinstance(repo, dict)
    request_path = state_root / "requests" / f"{request['request_id']}.json"
    review = {
        "schema": "seam-closeout-retirement-review/v1",
        "repository_common_dir": overrides.pop("repository_common_dir", None) or _git(
            Path(str(repo["root"])), "rev-parse", "--path-format=absolute", "--git-common-dir"
        ),
        "queue_root": str(state_root.resolve()),
        "kind": kind,
        "request_id": request["request_id"],
        "request_sha256": _sha(request_path.read_bytes()),
        "receipt_sha256": _sha(receipt_bytes) if receipt_bytes is not None else None,
        "missing_request_ids": missing if missing is not None else [],
        "surviving_receipts": sorted(
            ({"path": str(path.relative_to(state_root)), "sha256": _sha(path.read_bytes())}
             for target in (missing or []) for path in [
                 state_root / "receipts" / f"{target}.json",
                 *(state_root / "receipt-attempts").glob(f"{target}-*.json"),
             ] if path.is_file()), key=lambda item: item["path"]
        ),
        "preserved_ref": "refs/heads/main",
        "preserved_commit": preserved_commit,
        "operator_authority": "HISTORY#702",
        "producer_session_id": "independent-reviewer",
        "reviewer": "independent-reviewer",
        "reviewed_at": (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat(),
        "status": "PASS",
        "reason": (
            "NO_UNIQUE_WORK_PRESERVED_COMMIT"
            if kind == "ABANDONED_REQUEST"
            else "UNRECOVERABLE_SUPERSESSION_TARGETS"
        ),
        "authority": "admission_only",
        "unresolved_findings": [],
    }
    review.update(overrides)
    path = tmp_path / f"{request['request_id']}-{kind}-review.json"
    path.write_text(json.dumps(review), encoding="utf-8")
    return path


def _authorization(
    tmp_path: Path, review_path: Path, request: dict[str, object], **overrides: object
) -> Path:
    review = json.loads(review_path.read_text(encoding="utf-8"))
    repo = request["repo"]
    assert isinstance(repo, dict)
    entry = {
        "queue_root": review["queue_root"],
        "request_id": review["request_id"],
        "request_sha256": review["request_sha256"],
        "receipt_sha256": review["receipt_sha256"],
        "kind": review["kind"],
        "missing_request_ids": review["missing_request_ids"],
        "surviving_receipts": review["surviving_receipts"],
        "scope_truncated": repo["changed_paths_truncated"],
        "omitted_scope_disposal_authorized": repo["changed_paths_truncated"],
        "acknowledged_hidden_paths": [],
        "captured_paths_sha256": closeout_queue._captured_paths_sha256(request),
    }
    entry.update(overrides)
    value = {
        "schema": "seam-closeout-retirement-authorization/v1",
        "repository_common_dir": review["repository_common_dir"],
        "operator_authority": "HISTORY#702",
        "approved_at": "2026-11-24T00:00:00+00:00",
        "reviewer": review["reviewer"],
        "entries": [entry],
    }
    path = review_path.with_name(review_path.stem + "-authorization.json")
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _retire(state_root: Path, request: dict[str, object], review: Path, **kwargs: object):
    return closeout_queue.retire(
        request_path=state_root / "requests" / f"{request['request_id']}.json",
        review_path=review,
        authorization_path=kwargs.pop("authorization", None) or _authorization(
            review.parent, review, request
        ),
        state_root=state_root,
        **kwargs,
    )


def _abandoned_request(
    sample_repo: Path, tmp_path: Path, *, stale: bool = True
) -> tuple[Path, dict[str, object], str]:
    state_root = _standard_queue(sample_repo)
    preserved = _publish_origin(sample_repo, tmp_path)
    (sample_repo / "scratch.txt").write_text("local scratch\n", encoding="utf-8")
    queued = session_end_closeout.handle_session_end(
        {"session_id": "abandoned-session", "cwd": str(sample_repo)},
        repo_root=sample_repo,
        state_root=state_root,
        dispatch=False,
    )
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    if stale:
        (sample_repo / "scratch.txt").write_text("scratch edited later\n", encoding="utf-8")
    return state_root, request, preserved


def _abandoned_review(tmp_path: Path, state_root: Path, request, preserved: str, **overrides):
    return _retirement_review(
        tmp_path, kind="ABANDONED_REQUEST", request=request,
        state_root=state_root, preserved_commit=preserved, **overrides,
    )


def test_retired_abandoned_request_stays_in_pending_and_admission_passes(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    with pytest.raises(closeout_queue.CloseoutQueueError, match="unresolved requests"):
        closeout_queue.admit(sample_repo)
    review = _abandoned_review(tmp_path, state_root, request, preserved)
    authorization = _authorization(tmp_path, review, request)

    result = _retire(state_root, request, review, authorization=authorization)

    assert result["status"] == "RETIRED"
    record = json.loads(Path(result["retirement_path"]).read_text(encoding="utf-8"))
    assert record["kind"] == "ABANDONED_REQUEST"
    assert record["authority"] == "admission_only"
    assert record["operator_authority"] == "HISTORY#702"
    queue = closeout_queue.pending(state_root)
    assert [item["request_id"] for item in queue["requests"]] == [request["request_id"]]
    assert [item["request_id"] for item in queue["retirements"]] == [request["request_id"]]
    assert closeout_queue.pending(state_root, honor_retirements=True)["requests"] == []
    admitted = closeout_queue.admit(sample_repo)
    assert admitted["pending_request_ids"] == []
    assert any("|retirement|" in item for item in admitted["record_sha256s"])
    # An identical retry is recognised before any network proof is attempted.
    _git(sample_repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    assert _retire(state_root, request, review, authorization=authorization)[
        "status"
    ] == "ALREADY_RETIRED"


def test_retirement_breaks_when_the_bound_request_bytes_change(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))
    request_path = state_root / "requests" / f"{request['request_id']}.json"

    request_path.chmod(0o600)
    request_path.write_bytes(request_path.read_bytes() + b"\n")

    with pytest.raises(closeout_queue.CloseoutQueueError, match="retirement artifact changed"):
        closeout_queue.pending(state_root)


def test_orphaned_retirement_fails_closed(sample_repo: Path, tmp_path: Path) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))

    (state_root / "requests" / f"{request['request_id']}.json").unlink()

    with pytest.raises(closeout_queue.CloseoutQueueError, match="orphaned retirement"):
        closeout_queue.pending(state_root)
    with pytest.raises(closeout_queue.CloseoutQueueError, match="orphaned retirement"):
        closeout_queue.admit(sample_repo)


def test_abandoned_retirement_requires_a_stale_scope(sample_repo: Path, tmp_path: Path) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path, stale=False)

    with pytest.raises(closeout_queue.CloseoutQueueError, match="still matches the live tree"):
        _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))


def test_abandoned_retirement_refuses_captured_untracked_work_that_is_gone(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    (sample_repo / "scratch.txt").unlink()

    with pytest.raises(closeout_queue.CloseoutQueueError, match="no longer present"):
        _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))


def test_abandoned_retirement_refuses_a_dirty_tracked_path(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = _standard_queue(sample_repo)
    preserved = _publish_origin(sample_repo, tmp_path)
    (sample_repo / "README.md").write_text("uncommitted tracked edit\n", encoding="utf-8")
    queued = session_end_closeout.handle_session_end(
        {"session_id": "dirty-tracked", "cwd": str(sample_repo)},
        repo_root=sample_repo, state_root=state_root, dispatch=False,
    )
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    (sample_repo / "README.md").write_text("edited again\n", encoding="utf-8")

    with pytest.raises(closeout_queue.CloseoutQueueError, match="dirty tracked path"):
        _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))


def test_retirement_rejects_head_not_contained_in_preserved_commit(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = _standard_queue(sample_repo)
    preserved = _publish_origin(sample_repo, tmp_path)
    (sample_repo / "unique.txt").write_text("unpublished commit\n", encoding="utf-8")
    _git(sample_repo, "add", "unique.txt")
    _git(sample_repo, "commit", "-qm", "unique local work")
    (sample_repo / "scratch.txt").write_text("local scratch\n", encoding="utf-8")
    queued = session_end_closeout.handle_session_end(
        {"session_id": "unique-session", "cwd": str(sample_repo)},
        repo_root=sample_repo, state_root=state_root, dispatch=False,
    )
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    (sample_repo / "scratch.txt").write_text("scratch edited later\n", encoding="utf-8")

    with pytest.raises(closeout_queue.CloseoutQueueError, match="not preserved"):
        _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))


def test_retirement_rejects_preserved_ref_that_origin_does_not_hold(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(
        tmp_path, state_root, request, preserved, preserved_ref="refs/pull/99/head"
    )

    with pytest.raises(closeout_queue.CloseoutQueueError, match="origin does not hold"):
        _retire(state_root, request, review)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"producer_session_id": "abandoned-session", "reviewer": "abandoned-session"}, "independent"),
        ({"reviewer": "someone-else"}, "independent"),
        ({"status": "FAIL"}, "PASS"),
        ({"reason": "UNCHANGED_NONRUNTIME_TAIL_ASSURANCE_BOUNDARY"}, "reason"),
        ({"authority": "qualification"}, "admission_only"),
        ({"unresolved_findings": ["dirty tracked file not preserved"]}, "findings"),
        ({"operator_authority": "the operator said so"}, "operator_authority"),
        ({"reviewed_at": "2020-01-01T00:00:00+00:00"}, "predates"),
        ({"request_sha256": "0" * 64}, "request_sha256"),
        ({"preserved_ref": "refs/heads/feature"}, "preserved_ref is invalid"),
    ],
)
def test_retirement_review_contract_is_strict(
    sample_repo: Path, tmp_path: Path, override: dict[str, object], message: str
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state_root, request, preserved, **override)

    with pytest.raises(closeout_queue.CloseoutQueueError, match=message):
        _retire(state_root, request, review)
    assert closeout_queue.pending(state_root)["requests"]


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"request_sha256": "1" * 64}, "not listed"),
        ({"scope_truncated": True}, "not listed"),
        ({"omitted_scope_disposal_authorized": True}, "not listed"),
        ({"kind": "MISSING_SUPERSESSION_TARGETS"}, "not listed"),
        ({"captured_paths_sha256": "2" * 64}, "not listed"),
        ({"queue_root": "/another/.seam/orchestration/session-end"}, "not listed"),
        ({"request_id": "another-session-0000000000000000"}, "not listed"),
        ({"receipt_sha256": "3" * 64}, "not listed"),
        ({"missing_request_ids": ["another-session-0000000000000000"]}, "not listed"),
    ],
)
def test_retirement_requires_an_exact_operator_authorization_entry(
    sample_repo: Path, tmp_path: Path, override: dict[str, object], message: str
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state_root, request, preserved)
    authorization = _authorization(tmp_path, review, request, **override)

    with pytest.raises(closeout_queue.CloseoutQueueError, match=message):
        _retire(state_root, request, review, authorization=authorization)


def test_abandoned_retirement_refuses_a_request_already_qualified(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path, stale=False)
    closeout_queue.store_receipt(request, _qualified_receipt(request), state_root=state_root)
    (sample_repo / "scratch.txt").write_text("scratch edited later\n", encoding="utf-8")

    with pytest.raises(closeout_queue.CloseoutQueueError, match="already has a dispositive"):
        _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))


def test_abandoned_retirement_refuses_a_root_local_registered_candidate(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    assurance.register(sample_repo, "abandoned-session", preserved)

    with pytest.raises(closeout_queue.CloseoutQueueError, match="registered candidate"):
        _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))


def test_recovery_claim_after_retirement_fails_admission_closed(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))
    context_guardian.recover_unexpected_compaction(
        session_id="abandoned-session",
        event_id="late-recovery",
        summary=["compaction after retirement"],
        next_step="resume from handoff",
        state_root=sample_repo / ".seam" / "orchestration" / "context",
        handoff_root=sample_repo / ".context-handoffs",
    )

    with pytest.raises(closeout_queue.CloseoutQueueError, match="unresolved requests"):
        closeout_queue.admit(sample_repo)


def test_successor_admission_does_not_honour_retirements(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))

    pending_ids, hashes, _ = closeout_queue._queue_record_sha256s(
        sample_repo.resolve(), allowed_dispositions=set()
    )

    assert pending_ids == [request["request_id"]]
    assert any("|retirement|" in item for item in hashes)
    assert [item["request_id"] for item in closeout_queue.pending(state_root)["requests"]] == [
        request["request_id"]
    ]


def _qualified_with_lost_target(
    sample_repo: Path,
    tmp_path: Path,
    *,
    blocked_first: bool = False,
    completed_at: str | None = None,
) -> tuple[Path, dict[str, object], Path, str, str, dict[str, object]]:
    state_root = _standard_queue(sample_repo)
    (sample_repo / "README.md").write_text("first state\n", encoding="utf-8")
    first_queued = session_end_closeout.handle_session_end(
        {"session_id": "lost-target", "cwd": str(sample_repo)},
        repo_root=sample_repo, state_root=state_root, dispatch=False,
    )
    first = json.loads(Path(str(first_queued["request_path"])).read_text(encoding="utf-8"))
    failed = _qualified_receipt(first)
    failed["status"] = "NOT_QUALIFIED"
    failed["checks"][0]["status"] = "FAIL"
    failed["checks"][0]["exit_code"] = 1
    failed["next_action"] = "Repair and qualify the resulting exact state."
    closeout_queue.store_receipt(first, failed, state_root=state_root)
    (sample_repo / "README.md").write_text("second state\n", encoding="utf-8")
    second_queued = session_end_closeout.handle_session_end(
        {"session_id": "qualified-successor", "cwd": str(sample_repo)},
        repo_root=sample_repo, state_root=state_root, dispatch=False,
    )
    second = json.loads(Path(str(second_queued["request_path"])).read_text(encoding="utf-8"))
    if blocked_first:
        not_yet = _qualified_receipt(second)
        not_yet["status"] = "NOT_QUALIFIED"
        not_yet["checks"][0]["status"] = "FAIL"
        not_yet["checks"][0]["exit_code"] = 1
        not_yet["next_action"] = "Retry qualification."
        closeout_queue.store_receipt(second, not_yet, state_root=state_root)
    qualified = _qualified_receipt(second)
    qualified["supersedes_request_ids"] = [first["request_id"]]
    if completed_at is not None:
        qualified["completed_at"] = completed_at
    stored = closeout_queue.store_receipt(second, qualified, state_root=state_root)
    preserved = _publish_origin(sample_repo, tmp_path)
    Path(str(first_queued["request_path"])).unlink()
    return state_root, second, Path(stored["receipt_path"]), str(first["request_id"]), preserved, qualified


@pytest.mark.parametrize("blocked_first", [False, True])
def test_retired_missing_supersession_targets_restore_admission_only(
    sample_repo: Path, tmp_path: Path, blocked_first: bool
) -> None:
    state_root, request, receipt_path, lost_id, preserved, qualified = (
        _qualified_with_lost_target(sample_repo, tmp_path, blocked_first=blocked_first)
    )
    assert ("receipt-attempts" in receipt_path.parts) is blocked_first
    with pytest.raises(closeout_queue.CloseoutQueueError, match="superseded closeout request is missing"):
        closeout_queue.admit(sample_repo)
    review = _retirement_review(
        tmp_path, kind="MISSING_SUPERSESSION_TARGETS", request=request,
        state_root=state_root, preserved_commit=preserved,
        receipt_bytes=receipt_path.read_bytes(), missing=[lost_id],
    )

    result = _retire(state_root, request, review, receipt_path=receipt_path)

    assert result["status"] == "RETIRED"
    with pytest.raises(
        closeout_queue.CloseoutQueueError, match="superseded closeout request is missing"
    ):
        closeout_queue.pending(state_root)
    assert closeout_queue.pending(state_root, honor_retirements=True)["requests"] == []
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []
    # Storage stays strict: the retirement never revalidates a receipt there.
    with pytest.raises(closeout_queue.CloseoutQueueError, match="request is missing"):
        closeout_queue.store_receipt(request, qualified, state_root=state_root)


def test_missing_target_retirement_rejects_targets_that_still_exist_or_were_not_superseded(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, receipt_path, lost_id, preserved, _ = _qualified_with_lost_target(
        sample_repo, tmp_path
    )
    for missing, message in (
        (["never-superseded-request"], "not superseded"),
        ([str(request["request_id"])], "still exists"),
        ([], "missing_request_ids"),
    ):
        review = _retirement_review(
            tmp_path, kind="MISSING_SUPERSESSION_TARGETS", request=request,
            state_root=state_root, preserved_commit=preserved,
            receipt_bytes=receipt_path.read_bytes(), missing=missing,
        )
        with pytest.raises(closeout_queue.CloseoutQueueError, match=message):
            _retire(state_root, request, review, receipt_path=receipt_path)


def test_repository_ignores_retirement_and_evidence_paths() -> None:
    repo_root = Path(__file__).resolve().parents[2]

    def ignored(path: str) -> bool:
        # Only the tracked .gitignore counts: a clone's private info/exclude
        # may ignore more, and is not part of the repository contract.
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-v", path],
            cwd=repo_root, check=False, capture_output=True, text=True,
        )
        assert result.returncode in (0, 1), path
        return result.returncode == 0 and result.stdout.startswith(".gitignore:")

    for path in (
        ".seam/orchestration/session-end/retirements/example.json",
        ".seam/orchestration/session-end/retirement-evidence/example.json",
        ".seam/orchestration/session-end/.retirement-staging/x.tmp",
    ):
        assert ignored(path), path
    # Round 12: task evidence stays visible, as on origin/main, so SessionEnd's
    # exact-state capture of a never-retired request is unchanged by this patch.
    assert not ignored(".seam/evidence/example-task/log.txt")


def test_retire_cli_round_trip(
    sample_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state_root, request, preserved)
    command = [
        "--state-root", str(state_root), "retire",
        "--request", str(state_root / "requests" / f"{request['request_id']}.json"),
        "--review", str(review),
        "--authorization", str(_authorization(tmp_path, review, request)),
    ]

    assert closeout_queue.main(command) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "RETIRED"
    assert closeout_queue.main(["--state-root", str(state_root), "pending"]) == 0
    pending_output = json.loads(capsys.readouterr().out)
    assert [item["request_id"] for item in pending_output["requests"]] == [
        request["request_id"]
    ]
    assert [item["request_id"] for item in pending_output["retirements"]] == [
        request["request_id"]
    ]
    assert closeout_queue.main(["--repo-root", str(sample_repo), "admit"]) == 0
    assert json.loads(capsys.readouterr().out)["pending_request_ids"] == []


def test_abandoned_retirement_refuses_a_dirty_non_ascii_tracked_path(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = _standard_queue(sample_repo)
    (sample_repo / "café.py").write_text("value = 1\n", encoding="utf-8")
    _git(sample_repo, "add", "café.py")
    _git(sample_repo, "commit", "-qm", "non-ascii tracked file")
    preserved = _publish_origin(sample_repo, tmp_path)
    (sample_repo / "café.py").write_text("value = 2\n", encoding="utf-8")
    queued = session_end_closeout.handle_session_end(
        {"session_id": "non-ascii", "cwd": str(sample_repo)},
        repo_root=sample_repo, state_root=state_root, dispatch=False,
    )
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    (sample_repo / "café.py").write_text("value = 3\n", encoding="utf-8")

    with pytest.raises(closeout_queue.CloseoutQueueError, match="dirty tracked path"):
        _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))


def test_truncated_abandoned_retirement_requires_a_clean_tracked_tree(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _truncated_request(sample_repo, tmp_path)
    (sample_repo / "README.md").write_text("unqualified tracked edit\n", encoding="utf-8")
    review = _abandoned_review(tmp_path, state_root, request, preserved)

    with pytest.raises(closeout_queue.CloseoutQueueError, match="clean tracked tree"):
        _retire(state_root, request, review)

    _git(sample_repo, "checkout", "--", "README.md")
    assert _retire(state_root, request, review)["status"] == "RETIRED"


def test_missing_target_retirement_survives_a_removed_source_checkout(
    sample_repo: Path, tmp_path: Path
) -> None:
    host_queue = _standard_queue(sample_repo)
    source = tmp_path / "source"
    _git(sample_repo, "worktree", "add", "-qb", "source-branch", str(source))
    (source / "README.md").write_text("first state\n", encoding="utf-8")
    first_queued = session_end_closeout.handle_session_end(
        {"session_id": "lost-target", "cwd": str(source)},
        repo_root=source, state_root=host_queue, dispatch=False,
    )
    first = json.loads(Path(str(first_queued["request_path"])).read_text(encoding="utf-8"))
    failed = _qualified_receipt(first)
    failed["status"] = "NOT_QUALIFIED"
    failed["checks"][0]["status"] = "FAIL"
    failed["checks"][0]["exit_code"] = 1
    failed["next_action"] = "Repair and qualify the resulting exact state."
    closeout_queue.store_receipt(first, failed, state_root=host_queue)
    (source / "README.md").write_text("second state\n", encoding="utf-8")
    second_queued = session_end_closeout.handle_session_end(
        {"session_id": "qualified-successor", "cwd": str(source)},
        repo_root=source, state_root=host_queue, dispatch=False,
    )
    second = json.loads(Path(str(second_queued["request_path"])).read_text(encoding="utf-8"))
    qualified = _qualified_receipt(second)
    qualified["supersedes_request_ids"] = [first["request_id"]]
    receipt_path = Path(
        closeout_queue.store_receipt(second, qualified, state_root=host_queue)["receipt_path"]
    )
    preserved = _publish_origin(sample_repo, tmp_path)
    Path(str(first_queued["request_path"])).unlink()
    _git(sample_repo, "worktree", "remove", "--force", str(source))
    with pytest.raises(closeout_queue.CloseoutQueueError, match="superseded closeout request is missing"):
        closeout_queue.pending(host_queue)
    review = _retirement_review(
        tmp_path, kind="MISSING_SUPERSESSION_TARGETS", request=second,
        state_root=host_queue, preserved_commit=preserved,
        receipt_bytes=receipt_path.read_bytes(), missing=[str(first["request_id"])],
        repository_common_dir=_git(
            sample_repo, "rev-parse", "--path-format=absolute", "--git-common-dir"
        ),
    )

    # An unrelated clone now occupies the removed source path.
    _git(tmp_path, "init", "-q", str(source))

    assert _retire(host_queue, second, review, receipt_path=receipt_path)["status"] == "RETIRED"
    with pytest.raises(
        closeout_queue.CloseoutQueueError, match="superseded closeout request is missing"
    ):
        closeout_queue.pending(host_queue)
    assert closeout_queue.pending(host_queue, honor_retirements=True)["requests"] == []
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []


def test_missing_target_retirement_survives_a_receipt_only_retained_host(
    sample_repo: Path, tmp_path: Path
) -> None:
    (sample_repo / ".gitignore").write_text(".seam/\n", encoding="utf-8")
    _git(sample_repo, "add", ".gitignore")
    _git(sample_repo, "commit", "-qm", "ignore local orchestration")
    host = tmp_path / "retained-host"
    _git(sample_repo, "worktree", "add", "-qb", "retained-host", str(host))
    host_queue = host / ".seam" / "orchestration" / "session-end"
    (host / "README.md").write_text("first state\n", encoding="utf-8")
    first_queued = session_end_closeout.handle_session_end(
        {"session_id": "lost-target", "cwd": str(host)},
        repo_root=host, state_root=host_queue, dispatch=False,
    )
    first = json.loads(Path(str(first_queued["request_path"])).read_text(encoding="utf-8"))
    failed = _qualified_receipt(first)
    failed["status"] = "NOT_QUALIFIED"
    failed["checks"][0]["status"] = "FAIL"
    failed["checks"][0]["exit_code"] = 1
    failed["next_action"] = "Repair and qualify the resulting exact state."
    closeout_queue.store_receipt(first, failed, state_root=host_queue)
    (host / "README.md").write_text("second state\n", encoding="utf-8")
    second_queued = session_end_closeout.handle_session_end(
        {"session_id": "qualified-successor", "cwd": str(host)},
        repo_root=host, state_root=host_queue, dispatch=False,
    )
    second = json.loads(Path(str(second_queued["request_path"])).read_text(encoding="utf-8"))
    qualified = _qualified_receipt(second)
    qualified["supersedes_request_ids"] = [first["request_id"]]
    receipt_path = Path(
        closeout_queue.store_receipt(second, qualified, state_root=host_queue)["receipt_path"]
    )
    preserved = _publish_origin(sample_repo, tmp_path)
    Path(str(first_queued["request_path"])).unlink()
    review = _retirement_review(
        tmp_path, kind="MISSING_SUPERSESSION_TARGETS", request=second,
        state_root=host_queue, preserved_commit=preserved,
        receipt_bytes=receipt_path.read_bytes(), missing=[str(first["request_id"])],
    )
    _retire(host_queue, second, review, receipt_path=receipt_path)

    # The host loses its worktree metadata before it is ever registered.
    (host / ".git").unlink()

    first_admission = closeout_queue.admit(sample_repo, register_roots=[host])
    assert first_admission["pending_request_ids"] == []
    assert str(host.resolve()) in first_admission["registered_roots"]
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []


def _committed_path_request(
    sample_repo: Path, tmp_path: Path, *, stage_unique_bytes: bool = False
) -> tuple[Path, dict[str, object], str]:
    """Queue a request whose captured scope includes a committed base..head path."""

    state_root = _standard_queue(sample_repo)
    base = _git(sample_repo, "rev-parse", "HEAD")
    (sample_repo / "doc.txt").write_text("committed\n", encoding="utf-8")
    _git(sample_repo, "add", "doc.txt")
    _git(sample_repo, "commit", "-qm", "committed doc")
    preserved = _publish_origin(sample_repo, tmp_path)
    if stage_unique_bytes:
        (sample_repo / "doc.txt").write_text("unique staged bytes\n", encoding="utf-8")
        _git(sample_repo, "add", "doc.txt")
        (sample_repo / "doc.txt").write_text("committed\n", encoding="utf-8")
    (sample_repo / "scratch.txt").write_text("scratch\n", encoding="utf-8")
    sessions = state_root / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "committed-session.json").write_text(
        json.dumps(
            {
                "schema": "seam-agent-session-state/v1",
                "session_id": "committed-session",
                "base_sha": base,
                "objective": "Document a change.",
                "plan": ["Write the doc"],
                "constraints": [],
                "affected_tests": [],
                "tdd_cycles": [],
            }
        ),
        encoding="utf-8",
    )
    queued = session_end_closeout.handle_session_end(
        {"session_id": "committed-session", "cwd": str(sample_repo)},
        repo_root=sample_repo, state_root=state_root, dispatch=False,
    )
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    assert request["repo"]["base_sha"] == base
    assert "doc.txt" in request["repo"]["changed_paths"]
    (sample_repo / "scratch.txt").write_text("scratch edited later\n", encoding="utf-8")
    return state_root, request, preserved


def test_abandoned_retirement_refuses_staged_bytes_on_a_committed_path(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _committed_path_request(
        sample_repo, tmp_path, stage_unique_bytes=True
    )

    with pytest.raises(closeout_queue.CloseoutQueueError, match="differs from its commit"):
        _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))


def test_abandoned_retirement_refuses_worktree_bytes_on_a_committed_path(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _committed_path_request(sample_repo, tmp_path)
    (sample_repo / "doc.txt").write_text("unique worktree bytes\n", encoding="utf-8")

    with pytest.raises(closeout_queue.CloseoutQueueError, match="differs from its commit"):
        _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))


def test_abandoned_retirement_accepts_committed_paths_identical_to_the_request_head(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _committed_path_request(sample_repo, tmp_path)

    result = _retire(
        state_root, request, _abandoned_review(tmp_path, state_root, request, preserved)
    )

    assert result["status"] == "RETIRED"
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []


def _retirement_entries(state_root: Path) -> list[str]:
    root = state_root / "retirements"
    return sorted(item.name for item in root.iterdir()) if root.exists() else []


def test_stale_retained_registration_cannot_bind_a_host_now_owned_by_another_repository(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    other = tmp_path / "other-repository"
    _git(tmp_path, "init", "-q", str(other))
    other_common = _git(other, "rev-parse", "--path-format=absolute", "--git-common-dir")
    # A stale registration in another repository names this live host.
    closeout_queue._store_root_registration(Path(other_common), sample_repo.resolve())
    foreign = _abandoned_review(
        tmp_path, state_root, request, preserved, repository_common_dir=other_common
    )

    with pytest.raises(closeout_queue.CloseoutQueueError, match="not bound"):
        _retire(state_root, request, foreign)
    assert _retirement_entries(state_root) == []

    review = _abandoned_review(tmp_path, state_root, request, preserved)
    assert _retire(state_root, request, review)["status"] == "RETIRED"


def test_request_source_cannot_stand_in_for_an_unrelated_queue_host(
    sample_repo: Path, tmp_path: Path
) -> None:
    host = tmp_path / "host-repository"
    host.mkdir()
    _git(host, "init", "-q")
    _git(host, "config", "user.email", "tests@example.invalid")
    _git(host, "config", "user.name", "SEAM tests")
    (host / ".gitignore").write_text(".seam/\n", encoding="utf-8")
    _git(host, "add", ".gitignore")
    _git(host, "commit", "-qm", "host baseline")
    host_queue = host / ".seam" / "orchestration" / "session-end"
    preserved = _publish_origin(sample_repo, tmp_path)
    (sample_repo / "scratch.txt").write_text("local scratch\n", encoding="utf-8")
    queued = session_end_closeout.handle_session_end(
        {"session_id": "foreign-source", "cwd": str(sample_repo)},
        repo_root=sample_repo, state_root=host_queue, dispatch=False,
    )
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    (sample_repo / "scratch.txt").write_text("scratch edited later\n", encoding="utf-8")
    # The review, authorization and preservation proofs all name the source
    # repository; the queue lives in a worktree of a different one.
    review = _abandoned_review(tmp_path, host_queue, request, preserved)

    with pytest.raises(closeout_queue.CloseoutQueueError, match="not bound"):
        _retire(host_queue, request, review)
    assert _retirement_entries(host_queue) == []


def test_admission_rejects_a_retirement_reviewed_for_another_repository(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))
    other = tmp_path / "admitting-repository"
    _git(tmp_path, "init", "-q", str(other))
    other_common = Path(
        _git(other, "rev-parse", "--path-format=absolute", "--git-common-dir")
    )
    own_common = Path(
        _git(sample_repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    )

    with pytest.raises(closeout_queue.CloseoutQueueError, match="another repository"):
        closeout_queue.pending(state_root, admitting_common_dir=other_common)
    with pytest.raises(closeout_queue.CloseoutQueueError, match="another repository"):
        closeout_queue._queue_record_sha256s(sample_repo.resolve(), common_dir=other_common)
    assert [
        item["request_id"]
        for item in closeout_queue.pending(state_root, admitting_common_dir=own_common)["requests"]
    ] == [request["request_id"]]
    assert (
        closeout_queue.pending(
            state_root, honor_retirements=True, admitting_common_dir=own_common
        )["requests"]
        == []
    )


def test_abandoned_retirement_requires_the_request_root_to_be_the_active_git_root(
    sample_repo: Path, tmp_path: Path
) -> None:
    host_queue = _standard_queue(sample_repo)
    preserved = _publish_origin(sample_repo, tmp_path)
    source = sample_repo / "nested-source"
    _git(sample_repo, "worktree", "add", "-qb", "nested-source", str(source))
    (source / "README.md").write_text("dirty tracked edit\n", encoding="utf-8")
    queued = session_end_closeout.handle_session_end(
        {"session_id": "nested-source", "cwd": str(source)},
        repo_root=source, state_root=host_queue, dispatch=False,
    )
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    assert request["repo"]["changed_paths"] == ["README.md"]
    # The worktree is removed; its old path is now a plain directory inside the
    # primary checkout, where Git would list paths relative to a subdirectory.
    _git(sample_repo, "worktree", "remove", "--force", str(source))
    source.mkdir()
    (source / "README.md").write_text("unrelated bytes\n", encoding="utf-8")

    with pytest.raises(closeout_queue.CloseoutQueueError, match="no longer the active Git root"):
        _retire(host_queue, request, _abandoned_review(
            tmp_path, host_queue, request, preserved,
            repository_common_dir=_git(
                sample_repo, "rev-parse", "--path-format=absolute", "--git-common-dir"
            ),
        ))
    assert _retirement_entries(host_queue) == []


def test_abandoned_retirement_refuses_an_unresolved_recovery_claim_at_publication(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    context_guardian.recover_unexpected_compaction(
        session_id="abandoned-session",
        event_id="early-recovery",
        summary=["compaction before retirement"],
        next_step="resume from handoff",
        state_root=sample_repo / ".seam" / "orchestration" / "context",
        handoff_root=sample_repo / ".context-handoffs",
    )
    # The handoff is local recovery state, not captured work.
    (sample_repo / ".git" / "info" / "exclude").write_text(
        ".context-handoffs/\n", encoding="utf-8"
    )

    with pytest.raises(closeout_queue.CloseoutQueueError, match="recovery claim"):
        _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))
    assert _retirement_entries(state_root) == []


def _truncated_request(
    sample_repo: Path, tmp_path: Path
) -> tuple[Path, dict[str, object], str]:
    state_root = _standard_queue(sample_repo)
    preserved = _publish_origin(sample_repo, tmp_path)
    scratch = sample_repo / "scratch"
    scratch.mkdir()
    for index in range(session_end_closeout.MAX_CHANGED_PATHS + 1):
        (scratch / f"{index:04d}.txt").write_text("scratch\n", encoding="utf-8")
    queued = session_end_closeout.handle_session_end(
        {"session_id": "truncated", "cwd": str(sample_repo)},
        repo_root=sample_repo, state_root=state_root, dispatch=False,
    )
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    assert request["repo"]["changed_paths_truncated"] is True
    (scratch / "0000.txt").write_text("edited later\n", encoding="utf-8")
    return state_root, request, preserved


def test_truncated_abandoned_retirement_requires_the_live_head_at_the_request_head(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, _ = _truncated_request(sample_repo, tmp_path)
    (sample_repo / "later.txt").write_text("committed after capture\n", encoding="utf-8")
    _git(sample_repo, "add", "later.txt")
    _git(sample_repo, "commit", "-qm", "commit after capture")
    preserved = _publish_origin(sample_repo, tmp_path)

    with pytest.raises(closeout_queue.CloseoutQueueError, match="live HEAD to equal"):
        _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))


def test_truncated_abandoned_retirement_refuses_staged_only_tracked_edits(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _truncated_request(sample_repo, tmp_path)
    (sample_repo / "README.md").write_text("unique staged bytes\n", encoding="utf-8")
    _git(sample_repo, "add", "README.md")
    (sample_repo / "README.md").write_text("baseline\n", encoding="utf-8")

    with pytest.raises(closeout_queue.CloseoutQueueError, match="clean tracked tree"):
        _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))


def test_retirement_rejects_a_preserved_commit_the_origin_ref_no_longer_names(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    (sample_repo / "newer.txt").write_text("origin moved on\n", encoding="utf-8")
    _git(sample_repo, "add", "newer.txt")
    _git(sample_repo, "commit", "-qm", "newer main")
    assert _publish_origin(sample_repo, tmp_path) != preserved

    with pytest.raises(
        closeout_queue.CloseoutQueueError, match="does not hold the preserved commit"
    ):
        _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))
    assert _retirement_entries(state_root) == []


def test_retirement_accepts_a_pull_request_head_as_the_preserved_ref(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    _git(sample_repo, "push", "-q", "origin", "HEAD:refs/pull/277/head")
    # main moves on; only the pull-request head still names the request commit.
    (sample_repo / "newer.txt").write_text("origin moved on\n", encoding="utf-8")
    _git(sample_repo, "add", "newer.txt")
    _git(sample_repo, "commit", "-qm", "newer main")
    _publish_origin(sample_repo, tmp_path)
    _git(sample_repo, "reset", "-q", "--hard", preserved)
    review = _abandoned_review(
        tmp_path, state_root, request, preserved, preserved_ref="refs/pull/277/head"
    )

    assert _retire(state_root, request, review)["status"] == "RETIRED"
    record = json.loads(
        (state_root / "retirements" / f"{request['request_id']}.json").read_text(encoding="utf-8")
    )
    assert record["preserved_ref"] == "refs/pull/277/head"
    assert record["preserved_commit"] == preserved


def test_every_read_reproves_preserved_ancestry_from_local_objects(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))
    assert [item["request_id"] for item in closeout_queue.pending(state_root)["requests"]] == [
        request["request_id"]
    ]
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []
    commit_object = sample_repo / ".git" / "objects" / preserved[:2] / preserved[2:]
    assert commit_object.is_file()

    # The record, request, review and authorization bytes are all unchanged;
    # only the local object that proves containment is gone.
    commit_object.unlink()

    with pytest.raises(closeout_queue.CloseoutQueueError, match="preserved commit"):
        closeout_queue.pending(state_root)


def _reserialize(path: Path) -> None:
    """Rewrite one record as equivalent JSON with different bytes."""

    value = json.loads(path.read_text(encoding="utf-8"))
    path.chmod(0o600)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")), encoding="utf-8")


@pytest.mark.parametrize("artifact", ["review_path", "authorization_path"])
def test_retirement_breaks_when_the_bound_review_or_authorization_bytes_change(
    sample_repo: Path, tmp_path: Path, artifact: str
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    result = _retire(
        state_root, request, _abandoned_review(tmp_path, state_root, request, preserved)
    )
    record = json.loads(Path(result["retirement_path"]).read_text(encoding="utf-8"))

    _reserialize(Path(record[artifact]))

    with pytest.raises(closeout_queue.CloseoutQueueError, match="retirement artifact changed"):
        closeout_queue.pending(state_root)
    with pytest.raises(closeout_queue.CloseoutQueueError, match="retirement artifact changed"):
        closeout_queue.admit(sample_repo)


def _missing_target_review(
    tmp_path: Path, state_root: Path, request, receipt_path: Path, lost_id: str,
    preserved: str, **overrides,
) -> Path:
    return _retirement_review(
        tmp_path, kind="MISSING_SUPERSESSION_TARGETS", request=request,
        state_root=state_root, preserved_commit=preserved,
        receipt_bytes=receipt_path.read_bytes(), missing=[lost_id], **overrides,
    )


def test_missing_target_retirement_breaks_when_the_bound_receipt_bytes_change(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, receipt_path, lost_id, preserved, _ = _qualified_with_lost_target(
        sample_repo, tmp_path
    )
    review = _missing_target_review(tmp_path, state_root, request, receipt_path, lost_id, preserved)
    _retire(state_root, request, review, receipt_path=receipt_path)
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []

    # Still a valid stored receipt with the same parsed content.
    _reserialize(receipt_path)

    with pytest.raises(closeout_queue.CloseoutQueueError, match="retirement artifact changed"):
        closeout_queue.pending(state_root)
    with pytest.raises(closeout_queue.CloseoutQueueError, match="retirement artifact changed"):
        closeout_queue.admit(sample_repo)


def test_missing_target_exception_applies_only_to_the_bound_receipt_path(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, receipt_path, lost_id, preserved, qualified = (
        _qualified_with_lost_target(sample_repo, tmp_path)
    )
    review = _missing_target_review(tmp_path, state_root, request, receipt_path, lost_id, preserved)
    _retire(state_root, request, review, receipt_path=receipt_path)
    assert closeout_queue.pending(state_root, honor_retirements=True)["requests"] == []
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []

    # An equivalent qualified receipt appears at a second stored path. The
    # authorization and the record name only the canonical slot.
    encoded = closeout_queue._canonical_record(qualified)
    attempt = closeout_queue._receipt_attempt_path(
        state_root, str(request["request_id"]), encoded
    )
    attempt.parent.mkdir(parents=True, exist_ok=True)
    attempt.write_bytes(encoded)

    with pytest.raises(
        closeout_queue.CloseoutQueueError, match="superseded closeout request is missing"
    ):
        closeout_queue.pending(state_root, honor_retirements=True)
    with pytest.raises(
        closeout_queue.CloseoutQueueError, match="superseded closeout request is missing"
    ):
        closeout_queue.admit(sample_repo)


def test_missing_target_retirement_requires_a_stored_dispositive_receipt(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, receipt_path, lost_id, preserved, _ = _qualified_with_lost_target(
        sample_repo, tmp_path
    )
    copy = tmp_path / "receipt-copy.json"
    copy.write_bytes(receipt_path.read_bytes())
    review = _missing_target_review(tmp_path, state_root, request, copy, lost_id, preserved)

    with pytest.raises(closeout_queue.CloseoutQueueError, match="not a stored receipt"):
        _retire(state_root, request, review, receipt_path=copy)
    with pytest.raises(closeout_queue.CloseoutQueueError, match="requires its qualified receipt"):
        _retire(
            state_root, request,
            _retirement_review(
                tmp_path, kind="MISSING_SUPERSESSION_TARGETS", request=request,
                state_root=state_root, preserved_commit=preserved, missing=[lost_id],
            ),
        )
    assert _retirement_entries(state_root) == []


def test_missing_target_retirement_review_must_postdate_the_receipt(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, receipt_path, lost_id, preserved, _ = _qualified_with_lost_target(
        sample_repo, tmp_path, completed_at="2099-01-01T00:00:00+00:00"
    )
    review = _missing_target_review(tmp_path, state_root, request, receipt_path, lost_id, preserved)

    with pytest.raises(closeout_queue.CloseoutQueueError, match="predates its receipt"):
        _retire(state_root, request, review, receipt_path=receipt_path)


def test_successor_admission_and_plain_pending_disagree_only_by_explicit_mode(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, receipt_path, lost_id, preserved, _ = _qualified_with_lost_target(
        sample_repo, tmp_path
    )
    review = _missing_target_review(tmp_path, state_root, request, receipt_path, lost_id, preserved)
    _retire(state_root, request, review, receipt_path=receipt_path)

    with pytest.raises(
        closeout_queue.CloseoutQueueError, match="superseded closeout request is missing"
    ):
        closeout_queue.pending(state_root)
    assert closeout_queue.pending(state_root, honor_retirements=True)["requests"] == []
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []
    with pytest.raises(
        closeout_queue.CloseoutQueueError, match="superseded closeout request is missing"
    ):
        closeout_queue._queue_record_sha256s(sample_repo.resolve(), allowed_dispositions=set())


def test_admit_successor_never_honours_an_abandoned_retirement(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []

    # A retirement published after a transition is not one of its named repairs.
    with pytest.raises(
        closeout_queue.CloseoutQueueError, match="unrelated unresolved requests"
    ) as rejected:
        closeout_queue.admit_successor(
            sample_repo,
            obligation_request_ids=set(),
            lineage_session_ids={"some-successor-lineage"},
            branch=_git(sample_repo, "rev-parse", "--abbrev-ref", "HEAD"),
            original_base_sha=preserved,
            repair_paths=[],
        )
    assert str(request["request_id"]) in str(rejected.value)


def test_unexpected_retirement_directory_entries_fail_closed(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    result = _retire(
        state_root, request, _abandoned_review(tmp_path, state_root, request, preserved)
    )
    record_path = Path(result["retirement_path"])
    stray = record_path.with_name(f".{record_path.name}.tmp.partial")
    stray.write_bytes(record_path.read_bytes())

    with pytest.raises(closeout_queue.CloseoutQueueError, match="unexpected entry"):
        closeout_queue.pending(state_root)
    with pytest.raises(closeout_queue.CloseoutQueueError, match="unexpected entry"):
        closeout_queue.admit(sample_repo)

    stray.unlink()
    alias = record_path.with_name("alias-request.json")
    alias.symlink_to(record_path)
    with pytest.raises(closeout_queue.CloseoutQueueError, match="unexpected entry"):
        closeout_queue.pending(state_root)


def test_orphaned_retirement_fails_closed_while_other_requests_remain(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    other = session_end_closeout.handle_session_end(
        {"session_id": "still-queued", "cwd": str(sample_repo)},
        repo_root=sample_repo, state_root=state_root, dispatch=False,
    )
    (sample_repo / "scratch.txt").write_text("edited a third time\n", encoding="utf-8")
    _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))
    assert [item["request_id"] for item in closeout_queue.pending(state_root)["requests"]] == sorted(
        [str(request["request_id"]), str(other["request_id"])]
    )
    assert [
        item["request_id"]
        for item in closeout_queue.pending(state_root, honor_retirements=True)["requests"]
    ] == [other["request_id"]]

    (state_root / "requests" / f"{request['request_id']}.json").unlink()

    with pytest.raises(closeout_queue.CloseoutQueueError, match="orphaned retirement"):
        closeout_queue.pending(state_root)
    with pytest.raises(closeout_queue.CloseoutQueueError, match="orphaned retirement"):
        closeout_queue.admit(sample_repo)


def test_interrupted_publication_never_leaves_an_entry_in_retirements(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state_root, request, preserved)
    authorization = _authorization(tmp_path, review, request)
    staged_in: list[Path] = []
    survivors: list[Path] = []

    def die_at_link(source, destination, **kwargs):  # type: ignore[no-untyped-def]
        staged_in.append(Path(source).parent)
        # Keep a second name so the staged bytes outlive cleanup, as after a kill.
        survivor = Path(source).with_name(Path(source).name + ".killed")
        real_link(source, survivor)
        survivors.append(survivor)
        raise OSError("process died before the record was linked")

    import os as real_os

    real_link = real_os.link
    monkeypatch.setattr(closeout_queue.os, "link", die_at_link)
    with pytest.raises(OSError, match="process died"):
        _retire(state_root, request, review, authorization=authorization)
    monkeypatch.undo()

    assert staged_in == [state_root / ".retirement-staging"]
    assert survivors and survivors[0].is_file()
    assert _retirement_entries(state_root) == []
    # The leftover staged file wedges neither the queue view nor a clean retry.
    assert [item["request_id"] for item in closeout_queue.pending(state_root)["requests"]] == [
        request["request_id"]
    ]
    assert _retire(state_root, request, review, authorization=authorization)["status"] == "RETIRED"
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []


def test_conflicting_retirement_for_the_same_request_is_rejected(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    first = _abandoned_review(tmp_path, state_root, request, preserved)
    result = _retire(state_root, request, first)
    original = Path(result["retirement_path"]).read_bytes()
    other_directory = tmp_path / "second-review"
    other_directory.mkdir()
    second = _abandoned_review(
        other_directory, state_root, request, preserved,
        producer_session_id="second-reviewer", reviewer="second-reviewer",
    )

    with pytest.raises(closeout_queue.CloseoutQueueError, match="conflicting retirement exists"):
        _retire(state_root, request, second)
    assert Path(result["retirement_path"]).read_bytes() == original


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("reviewer", "someone-else", "reviewer does not match"),
        ("operator_authority", "HISTORY#1", "operator_authority does not match"),
        ("repository_common_dir", "/another/repository/.git", "repository identity"),
        ("schema", "seam-closeout-administrative-review/v1", "strict contract"),
        ("entries", [], "entries are invalid"),
    ],
)
def test_retirement_authorization_manifest_contract_is_strict(
    sample_repo: Path, tmp_path: Path, field: str, value: object, message: str
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state_root, request, preserved)
    authorization = _authorization(tmp_path, review, request)
    manifest = json.loads(authorization.read_text(encoding="utf-8"))
    manifest[field] = value
    authorization.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(closeout_queue.CloseoutQueueError, match=message):
        _retire(state_root, request, review, authorization=authorization)
    assert _retirement_entries(state_root) == []


def test_retirement_grants_no_receipt_assurance_or_supersession(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))

    # No receipt was created, and the retired request cannot be superseded by
    # or qualified through its retirement: the stale scope still fails storage.
    assert not (state_root / "receipts").exists()
    assert not (state_root / "receipt-attempts").exists()
    with pytest.raises(closeout_queue.CloseoutQueueError, match="live Git scope drifted"):
        closeout_queue.store_receipt(
            request, _qualified_receipt(request), state_root=state_root
        )
    record = json.loads(
        (state_root / "retirements" / f"{request['request_id']}.json").read_text(encoding="utf-8")
    )
    assert record["authority"] == "admission_only"
    assert set(record) == closeout_queue.RETIREMENT_FIELDS


def test_abandoned_retirement_refuses_staged_addition_with_differing_worktree_bytes(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = _standard_queue(sample_repo)
    preserved = _publish_origin(sample_repo, tmp_path)
    (sample_repo / "added.txt").write_text("staged bytes A\n", encoding="utf-8")
    _git(sample_repo, "add", "added.txt")
    (sample_repo / "added.txt").write_text("worktree bytes B\n", encoding="utf-8")
    (sample_repo / "scratch.txt").write_text("local scratch\n", encoding="utf-8")
    queued = session_end_closeout.handle_session_end(
        {"session_id": "staged-addition", "cwd": str(sample_repo)},
        repo_root=sample_repo,
        state_root=state_root,
        dispatch=False,
    )
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    assert "added.txt" in request["repo"]["changed_paths"]
    (sample_repo / "scratch.txt").write_text("scratch edited later\n", encoding="utf-8")
    review = _abandoned_review(tmp_path, state_root, request, preserved)

    with pytest.raises(closeout_queue.CloseoutQueueError, match="staged addition"):
        _retire(state_root, request, review)

    assert _retirement_entries(state_root) == []
    assert [item["request_id"] for item in closeout_queue.pending(state_root)["requests"]] == [
        request["request_id"]
    ]


def test_truncated_abandoned_retirement_requires_explicit_omitted_scope_authorization(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _truncated_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state_root, request, preserved)
    denied = _authorization(
        tmp_path, review, request, omitted_scope_disposal_authorized=False
    )

    with pytest.raises(closeout_queue.CloseoutQueueError, match="not listed"):
        _retire(state_root, request, review, authorization=denied)
    assert _retirement_entries(state_root) == []
    assert [item["request_id"] for item in closeout_queue.pending(state_root)["requests"]] == [
        request["request_id"]
    ]

    approved = _authorization(
        tmp_path, review, request, omitted_scope_disposal_authorized=True
    )
    assert _retire(state_root, request, review, authorization=approved)["status"] == "RETIRED"
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []


def test_fifo_substituted_for_bound_review_is_rejected_without_blocking(
    sample_repo: Path, tmp_path: Path
) -> None:
    import os
    import threading

    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    result = _retire(
        state_root, request, _abandoned_review(tmp_path, state_root, request, preserved)
    )
    record = json.loads(Path(result["retirement_path"]).read_text(encoding="utf-8"))
    review_path = Path(record["review_path"])
    review_path.unlink()
    os.mkfifo(review_path)

    outcomes: list[BaseException | object] = []

    def run_admit() -> None:
        try:
            outcomes.append(closeout_queue.admit(sample_repo))
        except BaseException as exc:
            outcomes.append(exc)

    worker = threading.Thread(target=run_admit, daemon=True)
    worker.start()
    try:
        worker.join(timeout=5.0)
        timed_out = worker.is_alive()
    finally:
        if worker.is_alive():
            try:
                unblock_fd = os.open(review_path, os.O_WRONLY | os.O_NONBLOCK)
                os.close(unblock_fd)
            except OSError:
                pass
            worker.join(timeout=2.0)

    assert not timed_out, "admission blocked on FIFO bound review"
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], closeout_queue.CloseoutQueueError)
    assert "regular file" in str(outcomes[0])


def _committed_deletion_request(
    sample_repo: Path, tmp_path: Path
) -> tuple[Path, dict[str, object], str]:
    state_root = _standard_queue(sample_repo)
    (sample_repo / "obsolete.json").write_text('{"snapshot": 1}\n', encoding="utf-8")
    _git(sample_repo, "add", "obsolete.json")
    _git(sample_repo, "commit", "-qm", "add snapshot")
    base = _git(sample_repo, "rev-parse", "HEAD")
    _git(sample_repo, "rm", "-q", "obsolete.json")
    _git(sample_repo, "commit", "-qm", "delete snapshot")
    preserved = _publish_origin(sample_repo, tmp_path)
    (sample_repo / "scratch.txt").write_text("scratch\n", encoding="utf-8")
    sessions = state_root / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "deleted-session.json").write_text(
        json.dumps(
            {
                "schema": "seam-agent-session-state/v1",
                "session_id": "deleted-session",
                "base_sha": base,
                "objective": "Prune obsolete snapshot.",
                "plan": ["Remove obsolete snapshot"],
                "constraints": [],
                "affected_tests": [],
                "tdd_cycles": [],
            }
        ),
        encoding="utf-8",
    )
    queued = session_end_closeout.handle_session_end(
        {"session_id": "deleted-session", "cwd": str(sample_repo)},
        repo_root=sample_repo,
        state_root=state_root,
        dispatch=False,
    )
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    assert "obsolete.json" in request["repo"]["changed_paths"]
    (sample_repo / "scratch.txt").write_text("scratch edited later\n", encoding="utf-8")
    return state_root, request, preserved


def test_abandoned_retirement_accepts_committed_deletion_in_base_to_head(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _committed_deletion_request(sample_repo, tmp_path)

    result = _retire(
        state_root, request, _abandoned_review(tmp_path, state_root, request, preserved)
    )

    assert result["status"] == "RETIRED"
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []


@pytest.mark.parametrize("drift_kind", ["worktree", "index"])
def test_abandoned_retirement_refuses_recreated_or_restaged_committed_deletion(
    sample_repo: Path, tmp_path: Path, drift_kind: str
) -> None:
    state_root, request, preserved = _committed_deletion_request(sample_repo, tmp_path)
    target = sample_repo / "obsolete.json"
    target.write_text('{"recreated": true}\n', encoding="utf-8")
    if drift_kind == "index":
        _git(sample_repo, "add", "obsolete.json")
        target.unlink()

    with pytest.raises(closeout_queue.CloseoutQueueError, match="committed deletion"):
        _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))

    assert _retirement_entries(state_root) == []
    assert [item["request_id"] for item in closeout_queue.pending(state_root)["requests"]] == [
        request["request_id"]
    ]


@pytest.mark.parametrize("race", ["scope", "ownership"])
def test_abandoned_retirement_reproves_ownership_and_scope_before_publication(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, race: str
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state_root, request, preserved)

    def race_during_remote_lookup(common_dir: Path, ref: str) -> str:
        if race == "scope":
            (sample_repo / "scratch.txt").unlink()
        else:
            context_guardian.recover_unexpected_compaction(
                session_id="abandoned-session",
                event_id="race-recovery",
                summary=["compaction during remote lookup"],
                next_step="resume from handoff",
                state_root=sample_repo / ".seam" / "orchestration" / "context",
                handoff_root=sample_repo / ".context-handoffs",
            )
            (sample_repo / ".git" / "info" / "exclude").write_text(
                ".context-handoffs/\n", encoding="utf-8"
            )
        return preserved

    monkeypatch.setattr(closeout_queue, "_origin_ref_commit", race_during_remote_lookup)
    expected_match = "no longer present" if race == "scope" else "recovery claim"

    with pytest.raises(closeout_queue.CloseoutQueueError, match=expected_match):
        _retire(state_root, request, review)

    assert _retirement_entries(state_root) == []


def test_abandoned_retirement_refuses_staged_only_tracked_change_absent_from_capture(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = _standard_queue(sample_repo)
    preserved = _publish_origin(sample_repo, tmp_path)
    (sample_repo / "README.md").write_text("unique staged bytes\n", encoding="utf-8")
    _git(sample_repo, "add", "README.md")
    (sample_repo / "README.md").write_text("baseline\n", encoding="utf-8")
    (sample_repo / "scratch.txt").write_text("local scratch\n", encoding="utf-8")
    queued = session_end_closeout.handle_session_end(
        {"session_id": "staged-outside-capture", "cwd": str(sample_repo)},
        repo_root=sample_repo,
        state_root=state_root,
        dispatch=False,
    )
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    assert request["repo"]["changed_paths_truncated"] is False
    assert request["repo"]["changed_paths"] == ["scratch.txt"]
    (sample_repo / "scratch.txt").write_text("scratch edited later\n", encoding="utf-8")
    review = _abandoned_review(tmp_path, state_root, request, preserved)

    with pytest.raises(
        closeout_queue.CloseoutQueueError, match="staged path.*README.md"
    ):
        _retire(state_root, request, review)

    assert _retirement_entries(state_root) == []
    assert [item["request_id"] for item in closeout_queue.pending(state_root)["requests"]] == [
        request["request_id"]
    ]
    with pytest.raises(closeout_queue.CloseoutQueueError, match="unresolved requests"):
        closeout_queue.admit(sample_repo)


@pytest.mark.parametrize("addition_kind", ["content", "intent_to_add"])
def test_abandoned_retirement_refuses_staged_addition_absent_from_capture(
    sample_repo: Path, tmp_path: Path, addition_kind: str
) -> None:
    state_root = _standard_queue(sample_repo)
    preserved = _publish_origin(sample_repo, tmp_path)
    if addition_kind == "content":
        (sample_repo / "staged_only.txt").write_text("unique staged addition\n", encoding="utf-8")
        _git(sample_repo, "add", "staged_only.txt")
        (sample_repo / "staged_only.txt").unlink()
    (sample_repo / "scratch.txt").write_text("local scratch\n", encoding="utf-8")
    queued = session_end_closeout.handle_session_end(
        {"session_id": "staged-addition-outside", "cwd": str(sample_repo)},
        repo_root=sample_repo,
        state_root=state_root,
        dispatch=False,
    )
    request = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    assert request["repo"]["changed_paths_truncated"] is False
    assert request["repo"]["changed_paths"] == ["scratch.txt"]
    (sample_repo / "scratch.txt").write_text("scratch edited later\n", encoding="utf-8")
    if addition_kind == "intent_to_add":
        (sample_repo / "staged_only.txt").write_text("intent to add\n", encoding="utf-8")
        _git(sample_repo, "add", "-N", "staged_only.txt")
    review = _abandoned_review(tmp_path, state_root, request, preserved)

    with pytest.raises(
        closeout_queue.CloseoutQueueError, match="staged path.*staged_only.txt"
    ):
        _retire(state_root, request, review)

    assert _retirement_entries(state_root) == []
    assert [item["request_id"] for item in closeout_queue.pending(state_root)["requests"]] == [
        request["request_id"]
    ]


def test_missing_target_retirement_rejects_partial_missing_list_then_accepts_complete_list(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root = _standard_queue(sample_repo)
    lost_ids: list[str] = []
    lost_paths: list[Path] = []
    for index, session_id in enumerate(("lost-first", "lost-second"), start=1):
        (sample_repo / "README.md").write_text(f"state {index}\n", encoding="utf-8")
        queued = session_end_closeout.handle_session_end(
            {"session_id": session_id, "cwd": str(sample_repo)},
            repo_root=sample_repo,
            state_root=state_root,
            dispatch=False,
        )
        req_path = Path(str(queued["request_path"]))
        req = json.loads(req_path.read_text(encoding="utf-8"))
        failed = _qualified_receipt(req)
        failed["status"] = "NOT_QUALIFIED"
        failed["checks"][0]["status"] = "FAIL"
        failed["checks"][0]["exit_code"] = 1
        failed["next_action"] = "Repair and qualify resulting state."
        closeout_queue.store_receipt(req, failed, state_root=state_root)
        lost_ids.append(str(req["request_id"]))
        lost_paths.append(req_path)

    (sample_repo / "README.md").write_text("final qualified state\n", encoding="utf-8")
    successor_queued = session_end_closeout.handle_session_end(
        {"session_id": "qualified-final", "cwd": str(sample_repo)},
        repo_root=sample_repo,
        state_root=state_root,
        dispatch=False,
    )
    successor = json.loads(Path(str(successor_queued["request_path"])).read_text(encoding="utf-8"))
    qualified = _qualified_receipt(successor)
    qualified["supersedes_request_ids"] = list(lost_ids)
    receipt_path = Path(
        closeout_queue.store_receipt(successor, qualified, state_root=state_root)["receipt_path"]
    )
    preserved = _publish_origin(sample_repo, tmp_path)
    for req_path in lost_paths:
        req_path.unlink()

    partial_dir = tmp_path / "partial"
    partial_dir.mkdir()
    partial_review = _retirement_review(
        partial_dir,
        kind="MISSING_SUPERSESSION_TARGETS",
        request=successor,
        state_root=state_root,
        preserved_commit=preserved,
        receipt_bytes=receipt_path.read_bytes(),
        missing=[lost_ids[0]],
    )
    with pytest.raises(
        closeout_queue.CloseoutQueueError, match="omits absent superseded targets"
    ):
        _retire(state_root, successor, partial_review, receipt_path=receipt_path)
    assert _retirement_entries(state_root) == []

    full_dir = tmp_path / "full"
    full_dir.mkdir()
    full_review = _retirement_review(
        full_dir,
        kind="MISSING_SUPERSESSION_TARGETS",
        request=successor,
        state_root=state_root,
        preserved_commit=preserved,
        receipt_bytes=receipt_path.read_bytes(),
        missing=sorted(lost_ids),
    )
    assert _retire(state_root, successor, full_review, receipt_path=receipt_path)[
        "status"
    ] == "RETIRED"
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []


@pytest.mark.parametrize(
    ("defect", "expected_match"),
    [
        ("lineage", "another repository lineage"),
        ("age", "older exact-state request"),
        ("missing_nonqualified_receipt", "non-qualified evidence"),
    ],
)
def test_missing_target_retirement_rejects_invalid_present_superseded_target(
    sample_repo: Path, tmp_path: Path, defect: str, expected_match: str
) -> None:
    state_root = _standard_queue(sample_repo)
    (sample_repo / "README.md").write_text("lost state\n", encoding="utf-8")
    lost_queued = session_end_closeout.handle_session_end(
        {"session_id": "lost-target", "cwd": str(sample_repo)},
        repo_root=sample_repo,
        state_root=state_root,
        dispatch=False,
    )
    lost_path = Path(str(lost_queued["request_path"]))
    lost = json.loads(lost_path.read_text(encoding="utf-8"))
    lost_failed = _qualified_receipt(lost)
    lost_failed["status"] = "NOT_QUALIFIED"
    lost_failed["checks"][0]["status"] = "FAIL"
    lost_failed["checks"][0]["exit_code"] = 1
    lost_failed["next_action"] = "Repair lost state."
    closeout_queue.store_receipt(lost, lost_failed, state_root=state_root)

    (sample_repo / "README.md").write_text("present state\n", encoding="utf-8")
    present_queued = session_end_closeout.handle_session_end(
        {"session_id": "present-target", "cwd": str(sample_repo)},
        repo_root=sample_repo,
        state_root=state_root,
        dispatch=False,
    )
    present_path = Path(str(present_queued["request_path"]))
    present = json.loads(present_path.read_text(encoding="utf-8"))
    present_failed = _qualified_receipt(present)
    present_failed["status"] = "NOT_QUALIFIED"
    present_failed["checks"][0]["status"] = "FAIL"
    present_failed["checks"][0]["exit_code"] = 1
    present_failed["next_action"] = "Repair present state."
    present_receipt_path = Path(
        closeout_queue.store_receipt(present, present_failed, state_root=state_root)[
            "receipt_path"
        ]
    )

    (sample_repo / "README.md").write_text("qualified state\n", encoding="utf-8")
    successor_queued = session_end_closeout.handle_session_end(
        {"session_id": "qualified-successor", "cwd": str(sample_repo)},
        repo_root=sample_repo,
        state_root=state_root,
        dispatch=False,
    )
    successor = json.loads(Path(str(successor_queued["request_path"])).read_text(encoding="utf-8"))
    qualified = _qualified_receipt(successor)
    qualified["supersedes_request_ids"] = [
        str(lost["request_id"]),
        str(present["request_id"]),
    ]
    receipt_path = Path(
        closeout_queue.store_receipt(successor, qualified, state_root=state_root)["receipt_path"]
    )
    preserved = _publish_origin(sample_repo, tmp_path)
    lost_path.unlink()

    if defect == "lineage":
        present["repo"]["branch"] = "other-lineage-branch"
        present["request_sha256"] = closeout_queue._request_hash(present)
        present_path.chmod(0o600)
        present_path.write_text(json.dumps(present), encoding="utf-8")
        present_failed["request_sha256"] = present["request_sha256"]
        present_receipt_path.chmod(0o600)
        present_receipt_path.write_text(json.dumps(present_failed), encoding="utf-8")
    elif defect == "age":
        present["created_at"] = "2099-01-01T00:00:00+00:00"
        present["request_sha256"] = closeout_queue._request_hash(present)
        present_path.chmod(0o600)
        present_path.write_text(json.dumps(present), encoding="utf-8")
        present_failed["request_sha256"] = present["request_sha256"]
        present_receipt_path.chmod(0o600)
        present_receipt_path.write_text(json.dumps(present_failed), encoding="utf-8")
    else:
        present_receipt_path.unlink()

    review = _retirement_review(
        tmp_path,
        kind="MISSING_SUPERSESSION_TARGETS",
        request=successor,
        state_root=state_root,
        preserved_commit=preserved,
        receipt_bytes=receipt_path.read_bytes(),
        missing=[str(lost["request_id"])],
    )
    with pytest.raises(closeout_queue.CloseoutQueueError, match=expected_match):
        _retire(state_root, successor, review, receipt_path=receipt_path)
    assert _retirement_entries(state_root) == []


@pytest.mark.parametrize("bound_receipt", [True, False])
def test_round5_restored_target_on_later_reads(
    sample_repo: Path, tmp_path: Path, bound_receipt: bool
) -> None:
    state_root = _standard_queue(sample_repo)
    (sample_repo / "README.md").write_text("first state\n", encoding="utf-8")
    first_queued = session_end_closeout.handle_session_end(
        {"session_id": "lost-target", "cwd": str(sample_repo)},
        repo_root=sample_repo,
        state_root=state_root,
        dispatch=False,
    )
    first_path = Path(str(first_queued["request_path"]))
    first_bytes = first_path.read_bytes()
    first = json.loads(first_bytes.decode("utf-8"))
    failed = _qualified_receipt(first)
    failed["status"] = "NOT_QUALIFIED"
    failed["checks"][0]["status"] = "FAIL"
    failed["checks"][0]["exit_code"] = 1
    failed["next_action"] = "Repair and qualify."
    first_receipt_path = Path(
        closeout_queue.store_receipt(first, failed, state_root=state_root)["receipt_path"]
    )
    (sample_repo / "README.md").write_text("second state\n", encoding="utf-8")
    second_queued = session_end_closeout.handle_session_end(
        {"session_id": "qualified-successor", "cwd": str(sample_repo)},
        repo_root=sample_repo,
        state_root=state_root,
        dispatch=False,
    )
    second = json.loads(Path(str(second_queued["request_path"])).read_text(encoding="utf-8"))
    qualified = _qualified_receipt(second)
    qualified["supersedes_request_ids"] = [first["request_id"]]
    receipt_path = Path(
        closeout_queue.store_receipt(second, qualified, state_root=state_root)["receipt_path"]
    )
    preserved = _publish_origin(sample_repo, tmp_path)
    receipt_bytes = first_receipt_path.read_bytes()
    first_path.unlink()
    if not bound_receipt:
        first_receipt_path.unlink()

    review = _missing_target_review(
        tmp_path, state_root, second, receipt_path, str(first["request_id"]), preserved
    )
    assert _retire(state_root, second, review, receipt_path=receipt_path)["status"] == "RETIRED"
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []

    # Restore the superseded request; later reads validate it normally.
    first_path.write_bytes(first_bytes)
    if not bound_receipt:
        assert [
            r["request_id"]
            for r in closeout_queue.pending(state_root, honor_retirements=True)["requests"]
        ] == [first["request_id"]]
        with pytest.raises(closeout_queue.CloseoutQueueError, match=first["request_id"]):
            closeout_queue.admit(sample_repo)
        first_receipt_path.write_bytes(receipt_bytes)
    assert closeout_queue.pending(state_root)["requests"] == []
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []

    first_receipt_path.unlink()
    assert [
        r["request_id"]
        for r in closeout_queue.pending(state_root, honor_retirements=True)["requests"]
    ] == [first["request_id"]]
    (sample_repo / "README.md").write_text("first state\n", encoding="utf-8")
    failed["next_action"] = "Retry the failed check."
    closeout_queue.store_receipt(first, failed, state_root=state_root)
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []


def _unregistered_host_without_git(
    sample_repo: Path, tmp_path: Path, *, remove_git: bool = True
) -> tuple[Path, Path, dict[str, object], Path, str, str, Path]:
    (sample_repo / ".gitignore").write_text(".seam/\n", encoding="utf-8")
    _git(sample_repo, "add", ".gitignore")
    _git(sample_repo, "commit", "-qm", "ignore local orchestration")
    common_dir = Path(
        _git(sample_repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    )
    host = tmp_path / "retained-host"
    _git(sample_repo, "worktree", "add", "-qb", "retained-host", str(host))
    host_queue = host / ".seam" / "orchestration" / "session-end"
    (host / "README.md").write_text("first state\n", encoding="utf-8")
    first_queued = session_end_closeout.handle_session_end(
        {"session_id": "lost-target", "cwd": str(host)},
        repo_root=host,
        state_root=host_queue,
        dispatch=False,
    )
    first = json.loads(Path(str(first_queued["request_path"])).read_text(encoding="utf-8"))
    failed = _qualified_receipt(first)
    failed["status"] = "NOT_QUALIFIED"
    failed["checks"][0]["status"] = "FAIL"
    failed["checks"][0]["exit_code"] = 1
    failed["next_action"] = "Repair and qualify."
    closeout_queue.store_receipt(first, failed, state_root=host_queue)
    (host / "README.md").write_text("second state\n", encoding="utf-8")
    second_queued = session_end_closeout.handle_session_end(
        {"session_id": "qualified-successor", "cwd": str(host)},
        repo_root=host,
        state_root=host_queue,
        dispatch=False,
    )
    second = json.loads(Path(str(second_queued["request_path"])).read_text(encoding="utf-8"))
    qualified = _qualified_receipt(second)
    qualified["supersedes_request_ids"] = [first["request_id"]]
    receipt_path = Path(
        closeout_queue.store_receipt(second, qualified, state_root=host_queue)["receipt_path"]
    )
    preserved = _publish_origin(host, tmp_path)
    Path(str(first_queued["request_path"])).unlink()
    if remove_git:
        (host / ".git").unlink()
        _git(sample_repo, "worktree", "prune")
    return host, host_queue, second, receipt_path, str(first["request_id"]), preserved, common_dir


def test_retire_register_root_binds_host_without_git_and_allows_plain_admit(
    sample_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    host, host_queue, second, receipt_path, lost_id, preserved, common_dir = (
        _unregistered_host_without_git(sample_repo, tmp_path, remove_git=True)
    )
    assert closeout_queue._load_registered_roots(common_dir) == []
    with pytest.raises(
        closeout_queue.CloseoutQueueError, match="superseded closeout request is missing"
    ):
        closeout_queue.admit(sample_repo, register_roots=[host])
    assert closeout_queue._load_registered_roots(common_dir) == []

    review = _retirement_review(
        tmp_path,
        kind="MISSING_SUPERSESSION_TARGETS",
        request=second,
        state_root=host_queue,
        preserved_commit=preserved,
        receipt_bytes=receipt_path.read_bytes(),
        missing=[lost_id],
        repository_common_dir=str(common_dir),
    )
    authorization = _authorization(tmp_path, review, second)

    with pytest.raises(closeout_queue.CloseoutQueueError, match="not bound"):
        _retire(host_queue, second, review, authorization=authorization, receipt_path=receipt_path)
    assert _retirement_entries(host_queue) == []

    command = [
        "--state-root",
        str(host_queue),
        "retire",
        "--request",
        str(host_queue / "requests" / f"{second['request_id']}.json"),
        "--review",
        str(review),
        "--authorization",
        str(authorization),
        "--receipt",
        str(receipt_path),
        "--register-root",
        str(host),
    ]
    assert closeout_queue.main(command) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "RETIRED"
    assert closeout_queue._load_registered_roots(common_dir) == [host.resolve()]

    admitted = closeout_queue.admit(sample_repo)
    assert admitted["pending_request_ids"] == []
    assert str(host.resolve()) in admitted["registered_roots"]


def test_retire_register_root_rejects_live_git_host_and_non_canonical_paths(
    sample_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    host, host_queue, second, receipt_path, lost_id, preserved, common_dir = (
        _unregistered_host_without_git(sample_repo, tmp_path, remove_git=False)
    )
    review = _retirement_review(
        tmp_path,
        kind="MISSING_SUPERSESSION_TARGETS",
        request=second,
        state_root=host_queue,
        preserved_commit=preserved,
        receipt_bytes=receipt_path.read_bytes(),
        missing=[lost_id],
        repository_common_dir=str(common_dir),
    )
    authorization = _authorization(tmp_path, review, second)

    # Host still has .git metadata: --register-root must refuse it.
    assert (
        closeout_queue.main(
            [
                "--state-root",
                str(host_queue),
                "retire",
                "--request",
                str(host_queue / "requests" / f"{second['request_id']}.json"),
                "--review",
                str(review),
                "--authorization",
                str(authorization),
                "--receipt",
                str(receipt_path),
                "--register-root",
                str(host),
            ]
        )
        == 2
    )
    assert ".git" in capsys.readouterr().err
    assert closeout_queue._load_registered_roots(common_dir) == []
    assert _retirement_entries(host_queue) == []

    # Remove .git and verify non-canonical or mismatched paths are rejected.
    (host / ".git").unlink()
    _git(sample_repo, "worktree", "prune")
    alias = tmp_path / "alias-host"
    alias.symlink_to(host, target_is_directory=True)
    subdir = tmp_path / "subdir"
    subdir.mkdir()
    dotdot = subdir / ".." / host.name
    for bad_root in (alias, dotdot, Path("relative-host"), sample_repo):
        with pytest.raises(closeout_queue.CloseoutQueueError, match="canonical"):
            _retire(
                host_queue,
                second,
                review,
                authorization=authorization,
                receipt_path=receipt_path,
                register_root=bad_root,
            )
    assert closeout_queue._load_registered_roots(common_dir) == []
    assert _retirement_entries(host_queue) == []

    # A failing authorization must not persist a retained-root registration.
    bad_auth = _authorization(tmp_path, review, second, request_sha256="0" * 64)
    with pytest.raises(closeout_queue.CloseoutQueueError, match="not listed"):
        _retire(
            host_queue,
            second,
            review,
            authorization=bad_auth,
            receipt_path=receipt_path,
            register_root=host,
        )
    assert closeout_queue._load_registered_roots(common_dir) == []
    assert _retirement_entries(host_queue) == []


def test_public_pending_admit_and_successor_outcomes_are_distinct(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, request, preserved = _abandoned_request(sample_repo, tmp_path)
    _retire(state_root, request, _abandoned_review(tmp_path, state_root, request, preserved))

    public_pending = closeout_queue.pending(state_root)
    assert [item["request_id"] for item in public_pending["requests"]] == [
        request["request_id"]
    ]
    assert [item["request_id"] for item in public_pending["retirements"]] == [
        request["request_id"]
    ]

    admitted = closeout_queue.admit(sample_repo)
    assert admitted["pending_request_ids"] == []
    assert any(
        f"|retirement|{request['request_id']}|" in item
        for item in admitted["record_sha256s"]
    )

    with pytest.raises(
        closeout_queue.CloseoutQueueError, match="unrelated unresolved requests"
    ) as rejected:
        closeout_queue.admit_successor(
            sample_repo,
            obligation_request_ids=set(),
            lineage_session_ids={"successor-session"},
            branch=_git(sample_repo, "rev-parse", "--abbrev-ref", "HEAD"),
            original_base_sha=preserved,
            repair_paths=[],
        )
    assert str(request["request_id"]) in str(rejected.value)




@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
@pytest.mark.parametrize("edited", [False, True])
def test_captured_flagged_path(sample_repo, tmp_path, flag, edited):
    state, request, preserved = _committed_path_request(sample_repo, tmp_path)
    _git(sample_repo, "update-index", flag, "doc.txt")
    if edited:
        (sample_repo / "doc.txt").write_bytes(b"hidden edit")
    with pytest.raises(closeout_queue.CloseoutQueueError, match="doc.txt"):
        _retire(state, request, _abandoned_review(tmp_path, state, request, preserved))


@pytest.mark.parametrize("ack", ["absent", "wrong", "exact"])
def test_truncated_hidden_acknowledgement(sample_repo, tmp_path, ack):
    import hashlib

    state, request, preserved = _truncated_request(sample_repo, tmp_path)
    _git(sample_repo, "update-index", "--skip-worktree", "README.md")
    (sample_repo / "README.md").write_bytes(b"hidden")
    review = _abandoned_review(tmp_path, state, request, preserved)
    digest = hashlib.sha256(b"hidden" if ack == "exact" else b"wrong").hexdigest()
    paths = [] if ack == "absent" else [{"path": "README.md", "worktree_sha256": digest}]
    authorization = _authorization(tmp_path, review, request, acknowledged_hidden_paths=paths)
    if ack == "exact":
        assert _retire(state, request, review, authorization=authorization)["status"] == "RETIRED"
    else:
        with pytest.raises(closeout_queue.CloseoutQueueError, match="README.md"):
            _retire(state, request, review, authorization=authorization)


def test_grafts_rejected(sample_repo, tmp_path):
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state, request, preserved)
    (sample_repo / ".git/info/grafts").touch()
    with pytest.raises(closeout_queue.CloseoutQueueError, match="grafts"):
        _retire(state, request, review)


def test_clean_index_on_newer_head(sample_repo, tmp_path):
    state, request, preserved = _committed_path_request(sample_repo, tmp_path)
    (sample_repo / "later").write_bytes(b"later")
    _git(sample_repo, "add", "later")
    _git(sample_repo, "commit", "-qm", "unrelated")
    # Round 12: a newer live HEAD must itself be published before retirement.
    preserved = _publish_origin(sample_repo, tmp_path)
    assert _retire(state, request, _abandoned_review(tmp_path, state, request, preserved))["status"] == "RETIRED"


@pytest.mark.parametrize("attempt", [False, True])
def test_orphaned_receipt_without_requests(sample_repo, tmp_path, attempt):
    state, request, _ = _abandoned_request(sample_repo, tmp_path, stale=False)
    closeout_queue.store_receipt(request, _qualified_receipt(request), state_root=state)
    if attempt:
        path = state / "receipts" / f"{request['request_id']}.json"
        stored = closeout_queue._receipt_attempt_path(state, request["request_id"], path.read_bytes())
        stored.parent.mkdir(exist_ok=True)
        path.rename(stored)
    (state / "requests" / f"{request['request_id']}.json").unlink()
    # origin/main parity: a receipt no retirement covers is ignored, not rejected.
    assert closeout_queue.pending(state)["requests"] == []
    admitted = closeout_queue.admit(sample_repo)
    assert admitted["pending_request_ids"] == []
    assert not any(str(request["request_id"]) in item for item in admitted["record_sha256s"])


def test_missing_target_receipt_inventory(sample_repo, tmp_path):
    import hashlib

    state, request, receipt, lost, preserved, _ = _qualified_with_lost_target(sample_repo, tmp_path)
    # Before retirement the lost target fails as on origin/main, through its
    # supersession, and its orphan receipt is not what rejects the queue.
    with pytest.raises(closeout_queue.CloseoutQueueError, match="^superseded closeout request is missing$") as error:
        closeout_queue.admit(sample_repo)
    assert "orphaned receipt" not in str(error.value)
    review = _retirement_review(tmp_path, kind="MISSING_SUPERSESSION_TARGETS", request=request,
                                state_root=state, preserved_commit=preserved,
                                receipt_bytes=receipt.read_bytes(), missing=[lost])
    _retire(state, request, review, receipt_path=receipt)
    _, hashes, _ = closeout_queue._queue_record_sha256s(sample_repo)
    digest = hashlib.sha256((state / "receipts" / f"{lost}.json").read_bytes()).hexdigest()
    assert f"{sample_repo}|receipt|{lost}|{lost}.json|{digest}" in hashes


def test_uncovered_orphan_receipt_is_ignored_like_origin_main(sample_repo, tmp_path):
    # Never-retired queue: one qualified request, then receipts whose request
    # does not exist. origin/main reads receipts per queued request only, so
    # these files are never opened, never rejected and never hashed.
    state, request, _ = _abandoned_request(sample_repo, tmp_path, stale=False)
    closeout_queue.store_receipt(request, _qualified_receipt(request), state_root=state)
    pending_before = closeout_queue.pending(state)
    inventory_before = closeout_queue._queue_record_sha256s(sample_repo)
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []

    gone = "gone-session-0000000000000000"
    (state / "receipts" / f"{gone}.json").write_bytes(b"not json")
    (state / "receipt-attempts").mkdir(exist_ok=True)
    (state / "receipt-attempts" / f"{gone}-{'0' * 64}.json").write_bytes(b"not json")

    assert not (state / "retirements").exists()
    assert closeout_queue.pending(state) == pending_before
    assert closeout_queue.pending(state, honor_retirements=True) == pending_before
    assert closeout_queue._queue_record_sha256s(sample_repo) == inventory_before
    admitted = closeout_queue.admit(sample_repo)
    assert admitted["pending_request_ids"] == []
    assert not any(gone in item for item in admitted["record_sha256s"])


def test_covered_orphan_receipt_stays_strict(sample_repo, tmp_path):
    state, request, receipt, lost, preserved, _ = _qualified_with_lost_target(sample_repo, tmp_path)
    review = _retirement_review(tmp_path, kind="MISSING_SUPERSESSION_TARGETS", request=request,
                                state_root=state, preserved_commit=preserved,
                                receipt_bytes=receipt.read_bytes(), missing=[lost])
    _retire(state, request, review, receipt_path=receipt)
    covered = state / "receipts" / f"{lost}.json"
    original = covered.read_bytes()
    digest = _sha(original)
    admitted = closeout_queue.admit(sample_repo)
    assert f"{sample_repo}|receipt|{lost}|{lost}.json|{digest}" in admitted["record_sha256s"]

    # The retirement covers only its own targets: another orphan beside it is
    # still ignored and unhashed, as on origin/main.
    gone = "gone-session-0000000000000000"
    honoured = closeout_queue.pending(state, honor_retirements=True)
    (state / "receipts" / f"{gone}.json").write_bytes(b"not json")
    assert closeout_queue.pending(state, honor_retirements=True) == honoured
    assert closeout_queue.admit(sample_repo)["record_sha256s"] == admitted["record_sha256s"]

    # Once a retirement covers the receipt, tampering with it is rejected.
    covered.chmod(0o600)
    covered.write_bytes(original + b"\n")
    with pytest.raises(closeout_queue.CloseoutQueueError, match="retirement surviving receipt inventory changed"):
        closeout_queue.pending(state)
    with pytest.raises(closeout_queue.CloseoutQueueError, match="retirement surviving receipt inventory changed"):
        closeout_queue.admit(sample_repo)
    covered.write_bytes(original)
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []

    # So is deleting it.
    covered.unlink()
    with pytest.raises(closeout_queue.CloseoutQueueError, match="retirement surviving receipt inventory changed"):
        closeout_queue.pending(state)
    with pytest.raises(closeout_queue.CloseoutQueueError, match="retirement surviving receipt inventory changed"):
        closeout_queue.admit(sample_repo)
    covered.write_bytes(original)

    # And a later receipt under a covered id is still read and identity-checked.
    extra = state / "receipt-attempts" / f"{lost}-{'0' * 64}.json"
    extra.parent.mkdir(exist_ok=True)
    extra.write_bytes(original)
    with pytest.raises(closeout_queue.CloseoutQueueError, match="invalid surviving target receipt"):
        closeout_queue.admit(sample_repo)


def test_read_rejects_retirement_whose_candidate_left_preserved_ancestry(sample_repo, tmp_path):
    # Preserved commit is a real descendant of the retired request head.
    state, request, _ = _abandoned_request(sample_repo, tmp_path)
    (sample_repo / "later").write_bytes(b"later")
    _git(sample_repo, "add", "later")
    _git(sample_repo, "commit", "-qm", "unrelated")
    preserved = _publish_origin(sample_repo, tmp_path)
    assert preserved != request["repo"]["head"]
    _retire(state, request, _abandoned_review(tmp_path, state, request, preserved))
    assert closeout_queue.pending(state, honor_retirements=True)["requests"] == []

    # Every bound byte is unchanged and the preserved commit is still present;
    # only its local history is cut, so it no longer contains the request head.
    (sample_repo / ".git" / "shallow").write_text(preserved + "\n", encoding="utf-8")
    assert _git(sample_repo, "cat-file", "-t", preserved) == "commit"

    with pytest.raises(closeout_queue.CloseoutQueueError, match="no longer contained in its preserved commit"):
        closeout_queue.pending(state)
    with pytest.raises(closeout_queue.CloseoutQueueError, match="no longer contained in its preserved commit"):
        closeout_queue.admit(sample_repo)


def test_retirement_review_must_name_this_queue_root(sample_repo, tmp_path):
    # The authorization entry names the right queue, so only the review's own
    # queue_root check stands between a review of another queue and a retirement.
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(
        tmp_path, state, request, preserved,
        queue_root="/another/.seam/orchestration/session-end",
    )
    authorization = _authorization(tmp_path, review, request, queue_root=str(state.resolve()))

    with pytest.raises(closeout_queue.CloseoutQueueError, match="retirement review queue root is invalid"):
        _retire(state, request, review, authorization=authorization)
    assert not (state / "retirements").exists()
    assert closeout_queue.pending(state, honor_retirements=True)["requests"]


def test_retirement_ignores_replacement_ancestry(sample_repo, tmp_path, monkeypatch):
    # Model a Git installation with a misleading replacement ancestry answer.
    original = subprocess.run
    inspected = []

    def run(command, *args, **kwargs):
        if "merge-base" in command and "--is-ancestor" in command:
            inspected.append(command)
            if "--no-replace-objects" not in command:
                return subprocess.CompletedProcess(command, 0, "", "")
        return original(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    test_retirement_rejects_head_not_contained_in_preserved_commit(sample_repo, tmp_path)
    assert inspected


def test_round4_captured_mode_respects_core_filemode(sample_repo, tmp_path):
    state, request, preserved = _committed_path_request(sample_repo, tmp_path)
    _git(sample_repo, "config", "core.filemode", "false")
    (sample_repo / "doc.txt").chmod(0o755)
    assert _retire(state, request, _abandoned_review(tmp_path, state, request, preserved))["status"] == "RETIRED"


def test_replacement_ref_cannot_remove_genuine_ancestry(sample_repo, tmp_path):
    state, request, _ = _abandoned_request(sample_repo, tmp_path)
    (sample_repo / "later").write_bytes(b"later")
    _git(sample_repo, "add", "later")
    _git(sample_repo, "commit", "-qm", "unrelated")
    preserved = _publish_origin(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state, request, preserved)
    _git(sample_repo, "replace", preserved, _git(sample_repo, "rev-parse", "HEAD~2"))
    assert _retire(state, request, review)["status"] == "RETIRED"
    assert closeout_queue.pending(state, honor_retirements=True)["requests"] == []


def test_round4_temp_attempt(sample_repo, tmp_path):
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    _retire(state, request, _abandoned_review(tmp_path, state, request, preserved))
    directory = state / "receipt-attempts"
    directory.mkdir(exist_ok=True)
    (directory / ".example.json.tmp.leftover").touch()
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []
    before = closeout_queue.admit(sample_repo)["record_sha256s"]
    (directory / "orphan.json").touch()
    # origin/main parity: an attempt no retirement covers is ignored.
    admitted = closeout_queue.admit(sample_repo)
    assert admitted["pending_request_ids"] == []
    assert admitted["record_sha256s"] == before


@pytest.mark.parametrize("ack", [True, False])
@pytest.mark.parametrize("filemode", ["true", "false"])
def test_round4_hidden_at_capture(sample_repo, tmp_path, ack, filemode):
    _git(sample_repo, "config", "core.filemode", filemode)
    _git(sample_repo, "update-index", "--skip-worktree", "README.md")
    hidden = sample_repo / "README.md"
    hidden.chmod(0o755)
    hidden.write_bytes(b"unique hidden bytes")
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    assert "README.md" not in request["repo"]["changed_paths"]
    review = _abandoned_review(tmp_path, state, request, preserved)
    if ack:
        paths = [{"path": hidden.name, "worktree_sha256": _sha(hidden.read_bytes())}]
        authorization = _authorization(tmp_path, review, request, acknowledged_hidden_paths=paths)
        assert _retire(state, request, review, authorization=authorization)["status"] == "RETIRED"
    else:
        with pytest.raises(closeout_queue.CloseoutQueueError, match="README.md"):
            _retire(state, request, review)


def test_round4_canonical_index(sample_repo, tmp_path, monkeypatch):
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state, request, preserved)
    alternate = tmp_path / "alt-index"
    alternate.write_bytes((sample_repo / ".git/index").read_bytes())
    tracked = sample_repo / "README.md"
    before = tracked.read_bytes()
    tracked.write_bytes(b"staged only")
    _git(sample_repo, "add", "README.md")
    tracked.write_bytes(before)
    monkeypatch.setenv("GIT_INDEX_FILE", str(alternate))
    with pytest.raises(closeout_queue.CloseoutQueueError, match="staged path"):
        _retire(state, request, review)


@pytest.mark.parametrize("attempt", [True, False])
def test_round4_survivor_mutation(sample_repo, tmp_path, attempt):
    state, request, receipt, lost, preserved, _ = _qualified_with_lost_target(sample_repo, tmp_path)
    survivor = state / "receipts" / f"{lost}.json"
    if attempt:
        retry = closeout_queue._receipt_attempt_path(state, lost, survivor.read_bytes())
        retry.parent.mkdir(exist_ok=True)
        survivor.rename(retry)
        survivor = retry
    review = _missing_target_review(tmp_path, state, request, receipt, lost, preserved)
    result = _retire(state, request, review, receipt_path=receipt)
    from jsonschema import Draft202012Validator

    for name, path in (
        ("closeout-retirement", Path(result["retirement_path"])),
        ("closeout-retirement-review", review),
        ("closeout-retirement-authorization", review.with_name(review.stem + "-authorization.json")),
    ):
        schema_path = closeout_queue.REPO_ROOT / "tools/agents/schemas" / (name + ".schema.json")
        schema = json.loads(schema_path.read_text())
        Draft202012Validator.check_schema(schema)
        Draft202012Validator(schema).validate(json.loads(path.read_text()))
    survivor.write_bytes(survivor.read_bytes() + b" ")
    with pytest.raises(
        closeout_queue.CloseoutQueueError,
        match="inventory changed; restore the bound receipt bytes from backup, "
        "or restore the target request so it validates normally",
    ):
        closeout_queue.admit(sample_repo)


def test_round4_resumed_session(sample_repo, tmp_path):
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    _retire(state, request, _abandoned_review(tmp_path, state, request, preserved))
    assurance.register(sample_repo, request["session_id"], preserved)
    with pytest.raises(closeout_queue.CloseoutQueueError, match="unresolved requests"):
        closeout_queue.admit(sample_repo)


def test_round4_preserved_object_remedy(sample_repo, tmp_path):
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    _retire(state, request, _abandoned_review(tmp_path, state, request, preserved))
    (sample_repo / ".git/objects" / preserved[:2] / preserved[2:]).unlink()
    with pytest.raises(closeout_queue.CloseoutQueueError, match="git fetch origin refs/heads/main"):
        closeout_queue.pending(state)


def test_round5_durable_evidence(sample_repo, tmp_path):
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state, request, preserved)
    authorization = _authorization(tmp_path, review, request)
    result = _retire(state, request, review, authorization=authorization)
    record = json.loads(Path(result["retirement_path"]).read_bytes())
    for name, source in (("review", review), ("authorization", authorization)):
        digest = record[name + "_bytes_sha256"]
        durable = state / "retirement-evidence" / (digest + ".json")
        assert record[name + "_path"] == str(durable)
        assert durable.read_bytes() == source.read_bytes()
        source.unlink()
    admission = closeout_queue.admit(sample_repo)
    for name in ("review", "authorization"):
        assert (
            f"{sample_repo}|retirement-evidence|{request['request_id']}|{name}|"
            f"{record[name + '_bytes_sha256']}"
        ) in admission["record_sha256s"]
    (durable.parent / "unexpected").touch()
    with pytest.raises(closeout_queue.CloseoutQueueError, match="orphaned retirement evidence"):
        closeout_queue.pending(state)

@pytest.mark.parametrize("field", ["review", "authorization"])
def test_round5_evidence_collision(sample_repo, tmp_path, field):
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state, request, preserved)
    authorization = _authorization(tmp_path, review, request)
    source = review if field == "review" else authorization
    durable = state / "retirement-evidence" / (_sha(source.read_bytes()) + ".json")
    durable.parent.mkdir()
    durable.write_bytes(b"{}")
    with pytest.raises(closeout_queue.CloseoutQueueError, match="copy differs"):
        _retire(state, request, review, authorization=authorization)
    assert durable.read_bytes() == b"{}"
    assert _retirement_entries(state) == []


@pytest.mark.parametrize("field", ["review", "authorization"])
def test_round5_external_binding_rejected(sample_repo, tmp_path, field):
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state, request, preserved)
    authorization = _authorization(tmp_path, review, request)
    result = _retire(state, request, review, authorization=authorization)
    path = Path(result["retirement_path"])
    record = json.loads(path.read_bytes())
    record[field + "_path"] = str(review if field == "review" else authorization)
    path.write_text(json.dumps(record))
    with pytest.raises(closeout_queue.CloseoutQueueError, match="content-addressed"):
        closeout_queue.admit(sample_repo)


def _second_abandoned_request(sample_repo: Path, state_root: Path) -> dict[str, object]:
    queued = session_end_closeout.handle_session_end(
        {"session_id": "abandoned-second", "cwd": str(sample_repo)},
        repo_root=sample_repo, state_root=state_root, dispatch=False,
    )
    (sample_repo / "scratch.txt").write_text("scratch edited a third time\n", encoding="utf-8")
    return json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))


def _die_before_record_link(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kill retire after its evidence copies exist and before its record is linked."""

    real_publish = closeout_queue._publish_retirement_once

    def publish(path, encoded, *, state_root):  # type: ignore[no-untyped-def]
        if path.parent.name == "retirements":
            raise OSError("process died before the record was linked")
        return real_publish(path, encoded, state_root=state_root)

    monkeypatch.setattr(closeout_queue, "_publish_retirement_once", publish)


def test_round6_retirements_sharing_one_authorization_admit_repeatedly(
    sample_repo: Path, tmp_path: Path
) -> None:
    state, first, preserved = _abandoned_request(sample_repo, tmp_path)
    second = _second_abandoned_request(sample_repo, state)
    requests = (first, second)
    reviews = [_abandoned_review(tmp_path, state, item, preserved) for item in requests]
    merged = json.loads(_authorization(tmp_path, reviews[0], first).read_text())
    merged["entries"].extend(
        json.loads(_authorization(tmp_path, reviews[1], second).read_text())["entries"]
    )
    shared = tmp_path / "shared-authorization.json"
    shared.write_text(json.dumps(merged), encoding="utf-8")

    for item, review in zip(requests, reviews):
        assert _retire(state, item, review, authorization=shared)["status"] == "RETIRED"

    records = [
        json.loads((state / "retirements" / f"{item['request_id']}.json").read_text())
        for item in requests
    ]
    assert records[0]["authorization_bytes_sha256"] == records[1]["authorization_bytes_sha256"]
    admitted = closeout_queue.admit(sample_repo)
    # The second admission reads back the record the first one wrote.
    again = closeout_queue.admit(sample_repo)
    assert again["record_sha256s"] == admitted["record_sha256s"]
    lines = [item for item in again["record_sha256s"] if "|retirement-evidence|" in item]
    assert len(lines) == len(set(lines)) == 4
    for record in records:
        for name in ("review", "authorization"):
            assert (
                f"{sample_repo}|retirement-evidence|{record['request_id']}|{name}|"
                f"{record[name + '_bytes_sha256']}"
            ) in lines
    # Successor validation loads the same stored admission record.
    closeout_queue.validate_successor_inventory(
        sample_repo,
        {
            "repair_artifacts": [],
            "queue_roots": again["observed_roots"],
            "queue_record_sha256s": again["record_sha256s"],
            "worktree_root": str(sample_repo),
            "branch": _git(sample_repo, "rev-parse", "--abbrev-ref", "HEAD"),
            "original_base_sha": preserved,
        },
        obligation_request_ids={str(item["request_id"]) for item in requests},
        lineage_session_ids=set(),
    )


def test_round6_interrupted_retire_leaves_inert_evidence_and_a_retry_succeeds(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state, request, preserved)
    authorization = _authorization(tmp_path, review, request)
    abandoned_copy = state / "retirement-evidence" / (_sha(review.read_bytes()) + ".json")
    _die_before_record_link(monkeypatch)
    with pytest.raises(OSError, match="process died"):
        _retire(state, request, review, authorization=authorization)
    monkeypatch.undo()

    assert len(list((state / "retirement-evidence").iterdir())) == 2
    assert abandoned_copy.is_file()
    assert _retirement_entries(state) == []
    queue = closeout_queue.pending(state)
    assert [item["request_id"] for item in queue["requests"]] == [request["request_id"]]
    assert "retirements" not in queue
    # Admission reaches its ordinary verdict; the unbound copies are not hashed.
    with pytest.raises(closeout_queue.CloseoutQueueError, match="unresolved requests"):
        closeout_queue.admit(sample_repo)
    _, hashes, _ = closeout_queue._queue_record_sha256s(
        sample_repo.resolve(), allowed_dispositions=set()
    )
    assert not any("retirement-evidence" in item for item in hashes)

    # The tree moves on and the retry carries a fresh review.
    (sample_repo / "scratch.txt").write_text("edited after the crash\n", encoding="utf-8")
    fresh = _abandoned_review(
        tmp_path, state, request, preserved, reviewed_at="2099-01-01T00:00:00+00:00"
    )
    assert _sha(fresh.read_bytes()) != abandoned_copy.stem
    assert _retire(state, request, fresh)["status"] == "RETIRED"
    admitted = closeout_queue.admit(sample_repo)
    assert admitted["pending_request_ids"] == []
    assert abandoned_copy.is_file()
    assert not any(abandoned_copy.stem in item for item in admitted["record_sha256s"])
    assert closeout_queue.admit(sample_repo)["record_sha256s"] == admitted["record_sha256s"]


@pytest.mark.parametrize("stray", ["misnamed", "not-json", "symlink", "directory"])
def test_round6_other_unbound_evidence_entries_fail_closed_naming_the_remedy(
    sample_repo: Path, tmp_path: Path, stray: str
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    _retire(state, request, _abandoned_review(tmp_path, state, request, preserved))
    evidence = state / "retirement-evidence"
    if stray == "misnamed":
        (evidence / ("0" * 64 + ".json")).write_bytes(b"{}")
    elif stray == "not-json":
        (evidence / (_sha(b"not json") + ".json")).write_bytes(b"not json")
    elif stray == "symlink":
        outside = tmp_path / "outside.json"
        outside.write_bytes(b"{}")
        (evidence / (_sha(b"{}") + ".json")).symlink_to(outside)
    else:
        (evidence / (_sha(b"{}") + ".json")).mkdir()

    for check in (lambda: closeout_queue.pending(state), lambda: closeout_queue.admit(sample_repo)):
        with pytest.raises(
            closeout_queue.CloseoutQueueError,
            match="orphaned retirement evidence: .*; move this entry out of the "
            "retirement-evidence directory, or restore the retirement record",
        ):
            check()


def test_round6_unreachable_origin_is_distinguished_from_an_absent_ref(
    sample_repo: Path, tmp_path: Path
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    absent = _abandoned_review(
        tmp_path, state, request, preserved, preserved_ref="refs/pull/99/head"
    )
    with pytest.raises(closeout_queue.CloseoutQueueError) as held:
        _retire(state, request, absent)
    assert "origin does not hold it" in str(held.value)
    assert "cannot reach origin" not in str(held.value)

    review = _abandoned_review(tmp_path, state, request, preserved)
    _git(sample_repo, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    with pytest.raises(closeout_queue.CloseoutQueueError) as unreachable:
        _retire(state, request, review)
    assert "cannot reach origin" in str(unreachable.value)
    assert "does not hold" not in str(unreachable.value)
    assert _retirement_entries(state) == []

    _git(sample_repo, "remote", "set-url", "origin", str(tmp_path / "origin.git"))
    assert _retire(state, request, review)["status"] == "RETIRED"


def test_round6_register_root_is_bound_only_after_the_retirement_link(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    host, host_queue, second, receipt_path, lost_id, preserved, common_dir = (
        _unregistered_host_without_git(sample_repo, tmp_path, remove_git=True)
    )
    review = _retirement_review(
        tmp_path,
        kind="MISSING_SUPERSESSION_TARGETS",
        request=second,
        state_root=host_queue,
        preserved_commit=preserved,
        receipt_bytes=receipt_path.read_bytes(),
        missing=[lost_id],
        repository_common_dir=str(common_dir),
    )
    authorization = _authorization(tmp_path, review, second)
    arguments = {
        "authorization": authorization, "receipt_path": receipt_path, "register_root": host,
    }
    _die_before_record_link(monkeypatch)
    with pytest.raises(OSError, match="process died"):
        _retire(host_queue, second, review, **arguments)
    monkeypatch.undo()

    assert len(list((host_queue / "retirement-evidence").iterdir())) == 2
    assert _retirement_entries(host_queue) == []
    assert closeout_queue._load_registered_roots(common_dir) == []

    assert _retire(host_queue, second, review, **arguments)["status"] == "RETIRED"
    assert closeout_queue._load_registered_roots(common_dir) == [host.resolve()]
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []


def _round7_restored_target_without_evidence(
    sample_repo: Path, tmp_path: Path
) -> tuple[Path, str]:
    """Retire a lost supersession target, then restore it without its receipt."""

    state_root = _standard_queue(sample_repo)
    (sample_repo / "README.md").write_text("first state\n", encoding="utf-8")
    first_queued = session_end_closeout.handle_session_end(
        {"session_id": "lost-target", "cwd": str(sample_repo)},
        repo_root=sample_repo, state_root=state_root, dispatch=False,
    )
    first_path = Path(str(first_queued["request_path"]))
    first_bytes = first_path.read_bytes()
    first = json.loads(first_bytes.decode("utf-8"))
    (sample_repo / "README.md").write_text("second state\n", encoding="utf-8")
    second_queued = session_end_closeout.handle_session_end(
        {"session_id": "qualified-successor", "cwd": str(sample_repo)},
        repo_root=sample_repo, state_root=state_root, dispatch=False,
    )
    second = json.loads(Path(str(second_queued["request_path"])).read_text(encoding="utf-8"))
    failed = _qualified_receipt(first)
    failed["status"] = "NOT_QUALIFIED"
    failed["checks"][0]["status"] = "FAIL"
    failed["checks"][0]["exit_code"] = 1
    failed["next_action"] = "Repair and qualify."
    (sample_repo / "README.md").write_text("first state\n", encoding="utf-8")
    first_receipt = Path(
        closeout_queue.store_receipt(first, failed, state_root=state_root)["receipt_path"]
    )
    (sample_repo / "README.md").write_text("second state\n", encoding="utf-8")
    qualified = _qualified_receipt(second)
    qualified["supersedes_request_ids"] = [first["request_id"]]
    receipt_path = Path(
        closeout_queue.store_receipt(second, qualified, state_root=state_root)["receipt_path"]
    )
    preserved = _publish_origin(sample_repo, tmp_path)
    first_path.unlink()
    first_receipt.unlink()
    review = _missing_target_review(
        tmp_path, state_root, second, receipt_path, str(first["request_id"]), preserved
    )
    assert _retire(state_root, second, review, receipt_path=receipt_path)["status"] == "RETIRED"
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []
    first_path.write_bytes(first_bytes)
    return state_root, str(first["request_id"])


def test_round7_successor_mode_never_swallows_an_invalid_restored_target(
    sample_repo: Path, tmp_path: Path
) -> None:
    state_root, restored_id = _round7_restored_target_without_evidence(sample_repo, tmp_path)
    refusal = "closeout supersession requires validated non-qualified evidence"

    # Successor inventory and public pending never honour the retirement.
    with pytest.raises(closeout_queue.CloseoutQueueError, match=refusal):
        closeout_queue._queue_record_sha256s(sample_repo.resolve(), allowed_dispositions=set())
    with pytest.raises(closeout_queue.CloseoutQueueError, match=refusal):
        closeout_queue.pending(state_root)
    with pytest.raises(closeout_queue.CloseoutQueueError, match=refusal):
        closeout_queue.admit_successor(
            sample_repo,
            obligation_request_ids={restored_id},
            lineage_session_ids=set(),
            branch=_git(sample_repo, "rev-parse", "--abbrev-ref", "HEAD"),
            original_base_sha=_git(sample_repo, "rev-parse", "HEAD"),
            repair_paths=[],
        )

    # Ordinary admission is unchanged: the restored target is simply pending again.
    assert [
        item["request_id"]
        for item in closeout_queue.pending(state_root, honor_retirements=True)["requests"]
    ] == [restored_id]
    with pytest.raises(closeout_queue.CloseoutQueueError, match="unresolved requests") as held:
        closeout_queue.admit(sample_repo)
    assert restored_id in str(held.value)


def _round7_anchor(preserved: str) -> str:
    return f"refs/seam/preserved/{preserved}"


def test_round7_retire_anchors_the_preserved_commit_idempotently(
    sample_repo: Path, tmp_path: Path
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state, request, preserved)
    authorization = _authorization(tmp_path, review, request)
    anchor = _round7_anchor(preserved)
    assert anchor not in _git(sample_repo, "for-each-ref", "--format=%(refname)").splitlines()

    assert _retire(state, request, review, authorization=authorization)["status"] == "RETIRED"

    assert _git(sample_repo, "rev-parse", "--verify", anchor) == preserved
    # A retry leaves the anchor alone, and recreates it if it was removed.
    assert _retire(state, request, review, authorization=authorization)[
        "status"
    ] == "ALREADY_RETIRED"
    assert _git(sample_repo, "rev-parse", "--verify", anchor) == preserved
    _git(sample_repo, "update-ref", "-d", anchor)
    assert _retire(state, request, review, authorization=authorization)[
        "status"
    ] == "ALREADY_RETIRED"
    assert _git(sample_repo, "rev-parse", "--verify", anchor) == preserved


def _round8_remedy(preserved_ref: str, preserved: str) -> str:
    return (
        f"git fetch origin {preserved_ref} && "
        f'git update-ref {_round7_anchor(preserved)} {preserved} ""'
    )


def _round9_unavailable(sample_repo: Path, remedy: str) -> str:
    return f"preserved commit unavailable; run in {sample_repo / '.git'}: {remedy}"


def _round8_run_remedy(message: str) -> None:
    """Run the printed remedy where it says to, as an operator would paste it."""

    where, command = message.removeprefix("preserved commit unavailable; run in ").split(": ", 1)
    subprocess.run(command, shell=True, cwd=where, check=True, capture_output=True)


def _round7_prune_everything_but(sample_repo: Path, keep: set[str]) -> None:
    for ref in _git(sample_repo, "for-each-ref", "--format=%(refname)").splitlines():
        if ref not in keep:
            _git(sample_repo, "update-ref", "-d", ref)
    _git(sample_repo, "reflog", "expire", "--expire=now", "--all")
    _git(sample_repo, "gc", "-q", "--prune=now")


def test_round7_anchor_keeps_admission_passing_after_branch_deletion_and_gc(
    sample_repo: Path, tmp_path: Path
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    _git(sample_repo, "push", "-q", "origin", "HEAD:refs/pull/277/head")
    review = _abandoned_review(
        tmp_path, state, request, preserved, preserved_ref="refs/pull/277/head"
    )
    assert _retire(state, request, review)["status"] == "RETIRED"
    anchor = _round7_anchor(preserved)

    # The work moves to unrelated history and every other holder of the commit goes.
    _git(sample_repo, "checkout", "-q", "--orphan", "unrelated")
    _git(sample_repo, "commit", "-qm", "unrelated history")
    _round7_prune_everything_but(sample_repo, {anchor, "refs/heads/unrelated"})

    assert _git(
        sample_repo, "for-each-ref", "--format=%(refname)", "--contains", preserved
    ).splitlines() == [anchor]
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []

    # Without the anchor the same pruning loses the commit; the remedy restores it.
    _round7_prune_everything_but(sample_repo, {"refs/heads/unrelated"})
    remedy = _round8_remedy("refs/pull/277/head", preserved)
    with pytest.raises(closeout_queue.CloseoutQueueError) as lost:
        closeout_queue.admit(sample_repo)
    assert str(lost.value) == _round9_unavailable(sample_repo, remedy)
    _round8_run_remedy(str(lost.value))
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []


@pytest.mark.parametrize("conflict", ["other-commit", "symbolic"])
def test_round7_conflicting_preserved_anchor_is_refused_before_publication(
    sample_repo: Path, tmp_path: Path, conflict: str
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    anchor = _round7_anchor(preserved)
    other = _git(sample_repo, "rev-parse", "HEAD~1")
    if conflict == "other-commit":
        _git(sample_repo, "update-ref", anchor, other)
    else:
        _git(sample_repo, "symbolic-ref", anchor, "HEAD")
    review = _abandoned_review(tmp_path, state, request, preserved)

    with pytest.raises(
        closeout_queue.CloseoutQueueError,
        match=f"anchor {anchor} exists and does not point at the preserved commit",
    ):
        _retire(state, request, review)

    assert _retirement_entries(state) == []
    assert not (state / "retirement-evidence").exists()
    if conflict == "other-commit":
        assert _git(sample_repo, "rev-parse", "--verify", anchor) == other
    else:
        assert _git(sample_repo, "symbolic-ref", anchor) == _git(
            sample_repo, "symbolic-ref", "HEAD"
        )
    with pytest.raises(closeout_queue.CloseoutQueueError, match="unresolved requests"):
        closeout_queue.admit(sample_repo)


def test_round7_remedies_name_the_operator_action(sample_repo: Path, tmp_path: Path) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    _retire(state, request, _abandoned_review(tmp_path, state, request, preserved))
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []

    # A retired session that registers again makes its retirement inactive.
    assurance.register(sample_repo, request["session_id"], preserved)
    with pytest.raises(closeout_queue.CloseoutQueueError) as inactive:
        closeout_queue.admit(sample_repo)
    assert "unresolved requests: " + str(request["request_id"]) in str(inactive.value)
    assert "retirement is inactive" in str(inactive.value)
    # The remedy names actions the tools provide; nothing deregisters a session.
    assert (
        "qualify the request or supersede it with a same-lineage QUALIFIED receipt"
        in str(inactive.value)
    )
    assert "deregister" not in str(inactive.value)
    # Successor inventory never honoured it, so it reports the request as before.
    pending_ids, _, _ = closeout_queue._queue_record_sha256s(
        sample_repo.resolve(), allowed_dispositions=set()
    )
    assert pending_ids == [request["request_id"]]

    request_path = state / "requests" / f"{request['request_id']}.json"
    request_path.unlink()
    for check in (lambda: closeout_queue.pending(state), lambda: closeout_queue.admit(sample_repo)):
        with pytest.raises(
            closeout_queue.CloseoutQueueError,
            match="orphaned retirement record: .*; restore the matching request from backup",
        ):
            check()


def test_round7_preserved_commit_remedy_names_the_anchor_destination(
    sample_repo: Path, tmp_path: Path
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    _retire(state, request, _abandoned_review(tmp_path, state, request, preserved))
    (sample_repo / ".git/objects" / preserved[:2] / preserved[2:]).unlink()

    with pytest.raises(closeout_queue.CloseoutQueueError) as lost:
        closeout_queue.pending(state)
    assert str(lost.value) == _round9_unavailable(
        sample_repo, _round8_remedy("refs/heads/main", preserved)
    )


def test_round8_remedy_anchors_the_exact_commit_after_the_preserved_ref_advanced(
    sample_repo: Path, tmp_path: Path
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state, request, preserved)
    authorization = _authorization(tmp_path, review, request)
    assert _retire(state, request, review, authorization=authorization)["status"] == "RETIRED"
    anchor = _round7_anchor(preserved)

    # Origin's preserved ref moves on past the preserved commit.
    advanced = _git(
        sample_repo, "commit-tree", "-m", "later work", "-p", preserved, preserved + "^{tree}"
    )
    _git(sample_repo, "push", "-q", "origin", f"{advanced}:refs/heads/main")
    assert _git(sample_repo, "ls-remote", "origin", "refs/heads/main").split()[0] == advanced

    # Every local holder of the commit goes, the anchor included.
    _git(sample_repo, "checkout", "-q", "--orphan", "unrelated")
    _git(sample_repo, "commit", "-qm", "unrelated history")
    _round7_prune_everything_but(sample_repo, {"refs/heads/unrelated"})
    remedy = _round8_remedy("refs/heads/main", preserved)
    with pytest.raises(closeout_queue.CloseoutQueueError) as lost:
        closeout_queue.admit(sample_repo)
    assert str(lost.value) == _round9_unavailable(sample_repo, remedy)

    _round8_run_remedy(str(lost.value))

    # The anchor names the preserved commit, not the advanced tip of the ref.
    assert _git(sample_repo, "rev-parse", "--verify", anchor) == preserved
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []
    assert _retire(state, request, review, authorization=authorization)[
        "status"
    ] == "ALREADY_RETIRED"
    assert _git(sample_repo, "rev-parse", "--verify", anchor) == preserved


@pytest.mark.parametrize(
    "output",
    [b"", b"not json", b"[]", b"null", b'[["a", [], "b"]]', b'[["a", [], "b"], ["a", []]]',
     b'[["a", [], "b"], {"head": "a"}]', b'[[1, [], "b"], [1, [], "b"]]'],
)
def test_round7_malformed_signature_child_output_is_a_queue_error(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch, output: bytes
) -> None:
    head = _git(sample_repo, "rev-parse", "HEAD")
    first, final = closeout_queue._retirement_signatures(sample_repo, None)
    assert first == final and first[0] == head and len(first) == 3

    real_run = subprocess.run
    monkeypatch.setattr(
        closeout_queue.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, output, b""),
    )
    with pytest.raises(closeout_queue.CloseoutQueueError, match="could not be recomputed"):
        closeout_queue._retirement_signatures(sample_repo, None)
    monkeypatch.setattr(closeout_queue.subprocess, "run", real_run)


def test_round7_signature_child_is_bounded_by_a_timeout(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state, request, preserved)
    real_run = subprocess.run
    seen: list[object] = []

    def hang_signature_child(command, **kwargs):
        if command[0] != "git":
            seen.append(kwargs.get("timeout"))
            raise subprocess.TimeoutExpired(command, kwargs.get("timeout") or 0)
        return real_run(command, **kwargs)

    monkeypatch.setattr(closeout_queue.subprocess, "run", hang_signature_child)
    with pytest.raises(closeout_queue.CloseoutQueueError, match="could not be recomputed"):
        _retire(state, request, review)
    monkeypatch.undo()

    assert seen == [closeout_queue.RETIREMENT_SIGNATURE_TIMEOUT_SECONDS]
    assert isinstance(seen[0], int) and seen[0] > 0
    assert _retirement_entries(state) == []
    assert _retire(state, request, review)["status"] == "RETIRED"


def test_round9_ordinary_admit_honours_caller_git_config_environment(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Ordinary admission reads Git exactly as the caller would: a checkout Git
    # refuses stays refused, and the caller's safe.directory entry admits it.
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")
    with pytest.raises(closeout_queue.CloseoutQueueError, match="cannot inspect Git worktrees"):
        closeout_queue.admit(sample_repo)

    monkeypatch.setenv("GIT_CONFIG_COUNT", "2")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "safe.directory")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "*")
    monkeypatch.setenv("GIT_CONFIG_KEY_1", "seam.round9probe")
    monkeypatch.setenv("GIT_CONFIG_VALUE_1", "caller-supplied")
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []
    assert (
        closeout_queue._git_inventory_text(sample_repo, "config", "--get", "seam.round9probe")
        == "caller-supplied"
    )
    # The retirement proofs do not inherit it.
    assert closeout_queue._git_retirement(
        sample_repo, "config", "--get", "seam.round9probe"
    ).returncode == 1


def test_round9_retirement_proofs_ignore_a_caller_git_dir(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state, request, preserved)
    authorization = _authorization(tmp_path, review, request)
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    # Ordinary inventory follows the caller; the proofs stay in the reviewed repository.
    assert closeout_queue._common_dir(sample_repo) == other / ".git"
    assert closeout_queue._retirement_git_common_dir(sample_repo) == sample_repo / ".git"
    assert _retire(state, request, review, authorization=authorization)["status"] == "RETIRED"
    assert [item["request_id"] for item in closeout_queue.pending(state)["retirements"]] == [
        request["request_id"]
    ]


# --- Round 11 -----------------------------------------------------------------


@pytest.mark.parametrize("flag", ["skip-worktree", "assume-unchanged"])
@pytest.mark.parametrize("ack", ["absent", "wrong", "exact"])
def test_round11_edit_hidden_at_capture_needs_acknowledgement_after_its_flag_is_cleared(
    sample_repo: Path, tmp_path: Path, flag: str, ack: str
) -> None:
    _git(sample_repo, "update-index", f"--{flag}", "README.md")
    hidden = sample_repo / "README.md"
    hidden.write_bytes(b"unique hidden bytes")
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    assert request["repo"]["changed_paths_truncated"] is False
    assert "README.md" not in request["repo"]["changed_paths"]
    # The flag is cleared after capture; the bytes remain as an unstaged edit.
    _git(sample_repo, "update-index", f"--no-{flag}", "README.md")
    assert _git(sample_repo, "ls-files", "-v", "README.md") == "H README.md"
    assert _git(sample_repo, "diff", "--name-only") == "README.md"
    assert _git(sample_repo, "diff", "--cached", "--name-only") == ""
    review = _abandoned_review(tmp_path, state, request, preserved)
    digest = _sha(b"unique hidden bytes" if ack == "exact" else b"other bytes")
    paths = [] if ack == "absent" else [{"path": "README.md", "worktree_sha256": digest}]
    authorization = _authorization(tmp_path, review, request, acknowledged_hidden_paths=paths)
    if ack != "exact":
        with pytest.raises(
            closeout_queue.CloseoutQueueError,
            match=r"hidden paths differ from authorization: \['README.md'\]",
        ):
            _retire(state, request, review, authorization=authorization)
        assert _retirement_entries(state) == []
        with pytest.raises(closeout_queue.CloseoutQueueError, match="unresolved requests"):
            closeout_queue.admit(sample_repo)
        return
    assert _retire(state, request, review, authorization=authorization)["status"] == "RETIRED"
    admitted = closeout_queue.admit(sample_repo)
    assert admitted["pending_request_ids"] == []
    # The acknowledgement is bound when the record is written: later reads do
    # not depend on the working tree staying dirty, or becoming clean.
    hidden.write_bytes(b"edited again after retirement")
    assert closeout_queue.admit(sample_repo)["record_sha256s"] == admitted["record_sha256s"]
    hidden.write_bytes(b"baseline\n")
    assert closeout_queue.admit(sample_repo)["record_sha256s"] == admitted["record_sha256s"]


@pytest.mark.parametrize("drift", ["edit", "mode", "delete"])
def test_round11_unflagged_tracked_drift_outside_the_capture_needs_acknowledgement(
    sample_repo: Path, tmp_path: Path, drift: str
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    tracked = sample_repo / "README.md"
    if drift == "edit":
        tracked.write_bytes(b"edited after capture")
    elif drift == "mode":
        tracked.chmod(0o755)
    else:
        tracked.unlink()
    review = _abandoned_review(tmp_path, state, request, preserved)
    with pytest.raises(closeout_queue.CloseoutQueueError, match="README.md"):
        _retire(state, request, review)
    assert _retirement_entries(state) == []
    if drift == "delete":
        # A deletion has no bytes to acknowledge.
        paths = [{"path": "README.md", "worktree_sha256": _sha(b"")}]
        with pytest.raises(
            closeout_queue.CloseoutQueueError, match="clean tracked tree: README.md"
        ):
            _retire(state, request, review, authorization=_authorization(
                tmp_path, review, request, acknowledged_hidden_paths=paths
            ))
        return
    paths = [{"path": "README.md", "worktree_sha256": _sha(tracked.read_bytes())}]
    authorization = _authorization(tmp_path, review, request, acknowledged_hidden_paths=paths)
    assert _retire(state, request, review, authorization=authorization)["status"] == "RETIRED"


def test_round11_acknowledging_a_clean_tracked_path_is_refused(
    sample_repo: Path, tmp_path: Path
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state, request, preserved)
    paths = [{"path": "README.md", "worktree_sha256": _sha(b"baseline\n")}]
    with pytest.raises(
        closeout_queue.CloseoutQueueError,
        match=r"hidden paths differ from authorization: \['README.md'\]",
    ):
        _retire(state, request, review, authorization=_authorization(
            tmp_path, review, request, acknowledged_hidden_paths=paths
        ))


_NEVER_RETIRED_PENDING_KEYS = ["profile", "requests", "administrative_dispositions"]


def test_round11_pending_shape_for_never_retired_queues_matches_origin_main(
    sample_repo: Path, tmp_path: Path
) -> None:
    empty = tmp_path / "empty-state"
    assert closeout_queue.pending(empty) == {
        "profile": "seam_release_orchestrator",
        "requests": [],
        "administrative_dispositions": [],
    }
    assert list(closeout_queue.pending(empty)) == _NEVER_RETIRED_PENDING_KEYS

    state = tmp_path / "state"
    _queued_request(sample_repo, state)
    request = closeout_queue._load_queued_requests(state.resolve())[0]
    for honor in (False, True):
        populated = closeout_queue.pending(state, honor_retirements=honor)
        assert populated == {
            "profile": "seam_release_orchestrator",
            "requests": [request],
            "administrative_dispositions": [],
        }
        assert list(populated) == _NEVER_RETIRED_PENDING_KEYS

    # A populated queue whose only request is no longer pending.
    closeout_queue.store_receipt(request, _qualified_receipt(request), state_root=state)
    assert closeout_queue.pending(state) == {
        "profile": "seam_release_orchestrator",
        "requests": [],
        "administrative_dispositions": [],
    }


def test_round11_pending_cli_output_has_no_retirements_key_until_one_exists(
    sample_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    assert closeout_queue.main(["--state-root", str(state), "pending"]) == 0
    before = json.loads(capsys.readouterr().out)
    assert sorted(before) == sorted(_NEVER_RETIRED_PENDING_KEYS)
    assert before["requests"] == [request]

    _retire(state, request, _abandoned_review(tmp_path, state, request, preserved))
    assert closeout_queue.main(["--state-root", str(state), "pending"]) == 0
    after = json.loads(capsys.readouterr().out)
    assert sorted(after) == sorted([*_NEVER_RETIRED_PENDING_KEYS, "retirements"])
    assert {key: after[key] for key in _NEVER_RETIRED_PENDING_KEYS} == before


def test_round11_unbound_evidence_is_name_checked_first_and_read_bounded(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    _retire(state, request, _abandoned_review(tmp_path, state, request, preserved))
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []
    evidence = state / "retirement-evidence"
    oversized = json.dumps({"pad": "x" * closeout_queue.MAX_RECORD_BYTES}).encode()
    assert len(oversized) > closeout_queue.MAX_RECORD_BYTES
    real_read_bytes = Path.read_bytes

    def no_unbounded_read(self: Path) -> bytes:
        if self.parent == evidence:
            raise AssertionError(f"unbounded read of {self.name}")
        return real_read_bytes(self)

    real_load = closeout_queue._load_json_record
    loaded: list[Path] = []

    def recording_load(path: Path):
        loaded.append(path)
        return real_load(path)

    monkeypatch.setattr(Path, "read_bytes", no_unbounded_read)
    monkeypatch.setattr(closeout_queue, "_load_json_record", recording_load)
    remedy = (
        "orphaned retirement evidence: .*; move this entry out of the "
        "retirement-evidence directory, or restore the retirement record"
    )

    # Content-addressed, valid JSON, but past the record bound: never inert.
    addressed = evidence / (_sha(oversized) + ".json")
    addressed.write_bytes(oversized)
    for check in (lambda: closeout_queue.pending(state), lambda: closeout_queue.admit(sample_repo)):
        with pytest.raises(closeout_queue.CloseoutQueueError, match=remedy):
            check()
    assert addressed in loaded
    addressed.unlink()

    # A name that is not a content address is rejected before anything is read.
    loaded.clear()
    misnamed = evidence / "stray.json"
    misnamed.write_bytes(oversized)
    with pytest.raises(closeout_queue.CloseoutQueueError, match=remedy):
        closeout_queue.admit(sample_repo)
    assert misnamed not in loaded
    misnamed.unlink()
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []


def test_round11_read_rejects_a_retirement_bound_to_a_non_canonical_request_copy(
    sample_repo: Path, tmp_path: Path
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    result = _retire(state, request, _abandoned_review(tmp_path, state, request, preserved))
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []
    queued = state / "requests" / f"{request['request_id']}.json"
    copy = tmp_path.resolve() / "request-copy.json"
    copy.write_bytes(queued.read_bytes())
    record_path = Path(result["retirement_path"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    assert record["request_path"] == str(queued)
    # Same bytes and digest, so only the canonical-path check can refuse it.
    record["request_path"] = str(copy)
    record_path.write_text(json.dumps(record), encoding="utf-8")

    for check in (lambda: closeout_queue.pending(state), lambda: closeout_queue.admit(sample_repo)):
        with pytest.raises(
            closeout_queue.CloseoutQueueError,
            match="retirement request is not canonically queued",
        ):
            check()


def test_round11_read_rejects_a_record_whose_kind_differs_from_its_review(
    sample_repo: Path, tmp_path: Path
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    result = _retire(state, request, _abandoned_review(tmp_path, state, request, preserved))
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []
    record_path = Path(result["retirement_path"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    evidence = state / "retirement-evidence"

    # Forge a self-consistent review and authorization of the other kind, and
    # leave the record claiming ABANDONED_REQUEST. Every byte binding holds.
    review = json.loads(Path(record["review_path"]).read_text(encoding="utf-8"))
    review["kind"] = "MISSING_SUPERSESSION_TARGETS"
    review["reason"] = "UNRECOVERABLE_SUPERSESSION_TARGETS"
    authorization = json.loads(Path(record["authorization_path"]).read_text(encoding="utf-8"))
    authorization["entries"][0]["kind"] = "MISSING_SUPERSESSION_TARGETS"
    for field, value in (("review", review), ("authorization", authorization)):
        encoded = json.dumps(value).encode("utf-8")
        forged = evidence / (_sha(encoded) + ".json")
        forged.write_bytes(encoded)
        record[f"{field}_path"] = str(forged)
        record[f"{field}_bytes_sha256"] = _sha(encoded)
    assert record["kind"] == "ABANDONED_REQUEST"
    record_path.write_text(json.dumps(record), encoding="utf-8")

    for check in (lambda: closeout_queue.pending(state), lambda: closeout_queue.admit(sample_repo)):
        with pytest.raises(
            closeout_queue.CloseoutQueueError,
            match="retirement kind does not match its review",
        ):
            check()


# --- Round 12 -----------------------------------------------------------------


def _commit_all(repo: Path, message: str) -> str:
    _git(repo, "commit", "-qam", message)
    return _git(repo, "rev-parse", "HEAD")


@pytest.mark.parametrize("flag", ["skip-worktree", "assume-unchanged"])
@pytest.mark.parametrize("worktree", ["captured-bytes", "indexed-bytes"])
def test_round12_flagged_path_is_compared_with_the_index_not_the_captured_commit(
    sample_repo: Path, tmp_path: Path, flag: str, worktree: str
) -> None:
    state, request, _ = _abandoned_request(sample_repo, tmp_path)
    tracked = sample_repo / "README.md"
    # A later, published commit changes the file; the captured commit and the
    # index now hold different blobs for it, and the flag is still set.
    tracked.write_bytes(b"changed by a later commit\n")
    _commit_all(sample_repo, "later change")
    preserved = _publish_origin(sample_repo, tmp_path)
    _git(sample_repo, "update-index", f"--{flag}", "README.md")
    if worktree == "captured-bytes":
        # An unstaged edit restores the captured bytes: equal to the captured
        # commit, different from the index.
        tracked.write_bytes(b"baseline\n")
    assert _git(sample_repo, "ls-files", "-v", "README.md")[0] in {"S", "h"}
    assert _git(sample_repo, "status", "--porcelain", "--untracked-files=no") == ""
    review = _abandoned_review(tmp_path, state, request, preserved)
    exact = [{"path": "README.md", "worktree_sha256": _sha(tracked.read_bytes())}]
    needed, refused = ([], exact) if worktree == "indexed-bytes" else (exact, [])

    with pytest.raises(
        closeout_queue.CloseoutQueueError,
        match=r"hidden paths differ from authorization: \['README.md'\]",
    ):
        _retire(state, request, review, authorization=_authorization(
            tmp_path, review, request, acknowledged_hidden_paths=refused
        ))
    assert _retirement_entries(state) == []
    authorization = _authorization(tmp_path, review, request, acknowledged_hidden_paths=needed)
    assert _retire(state, request, review, authorization=authorization)["status"] == "RETIRED"
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []


def test_round12_unpublished_local_commit_refuses_a_non_truncated_retirement(
    sample_repo: Path, tmp_path: Path
) -> None:
    _git(sample_repo, "update-index", "--skip-worktree", "README.md")
    hidden = sample_repo / "README.md"
    hidden.write_bytes(b"unique hidden bytes")
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    assert request["repo"]["changed_paths_truncated"] is False
    assert "README.md" not in request["repo"]["changed_paths"]
    # The flag is cleared and the hidden bytes are committed, never pushed: the
    # tree, the index and the live HEAD now agree, so nothing is left to
    # acknowledge, and the bytes exist nowhere but in this clone.
    _git(sample_repo, "update-index", "--no-skip-worktree", "README.md")
    unpublished = _commit_all(sample_repo, "local only")
    assert _git(sample_repo, "status", "--porcelain", "--untracked-files=no") == ""
    review = _abandoned_review(tmp_path, state, request, preserved)

    with pytest.raises(closeout_queue.CloseoutQueueError) as refusal:
        _retire(state, request, review)
    message = str(refusal.value)
    assert f"live HEAD {unpublished} is not published" in message
    assert "publish its commits to origin main" in message
    assert "checked out at a published commit" in message
    assert _retirement_entries(state) == []
    assert not (state / "retirement-evidence").exists()
    with pytest.raises(closeout_queue.CloseoutQueueError, match="unresolved requests"):
        closeout_queue.admit(sample_repo)

    # The named remedy works: once origin main holds the commit, it retires.
    published = _publish_origin(sample_repo, tmp_path)
    assert published == unpublished
    review = _abandoned_review(tmp_path, state, request, published)
    assert _retire(state, request, review)["status"] == "RETIRED"
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []


def _pull_request_subject(
    sample_repo: Path, tmp_path: Path
) -> tuple[Path, dict[str, object], str, str]:
    """A request preserved by a pull-request head that origin main never merged."""

    state, request, request_head = _abandoned_request(sample_repo, tmp_path)
    (sample_repo / "pull.txt").write_text("pull request work\n", encoding="utf-8")
    _git(sample_repo, "add", "pull.txt")
    pull_head = _commit_all(sample_repo, "pull request head")
    _git(sample_repo, "push", "-q", "origin", "HEAD:refs/pull/277/head")
    _git(sample_repo, "reset", "-q", "--hard", request_head)
    (sample_repo / "main.txt").write_text("main moved on\n", encoding="utf-8")
    _git(sample_repo, "add", "main.txt")
    main_head = _commit_all(sample_repo, "main moved on")
    assert _publish_origin(sample_repo, tmp_path) == main_head
    for ancestor, descendant in ((pull_head, main_head), (main_head, pull_head)):
        assert subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant], cwd=sample_repo
        ).returncode == 1
    return state, request, pull_head, main_head


def test_round12_live_head_at_origin_main_retires_a_pull_request_preserved_subject(
    sample_repo: Path, tmp_path: Path
) -> None:
    state, request, pull_head, main_head = _pull_request_subject(sample_repo, tmp_path)
    assert _git(sample_repo, "rev-parse", "HEAD") == main_head
    review = _abandoned_review(
        tmp_path, state, request, pull_head, preserved_ref="refs/pull/277/head"
    )

    assert _retire(state, request, review)["status"] == "RETIRED"
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []


def test_round12_pull_request_preserved_subject_refuses_an_unpublished_live_head(
    sample_repo: Path, tmp_path: Path
) -> None:
    state, request, pull_head, _ = _pull_request_subject(sample_repo, tmp_path)
    (sample_repo / "README.md").write_bytes(b"committed locally, never pushed\n")
    unpublished = _commit_all(sample_repo, "local only")
    review = _abandoned_review(
        tmp_path, state, request, pull_head, preserved_ref="refs/pull/277/head"
    )

    with pytest.raises(
        closeout_queue.CloseoutQueueError, match=f"live HEAD {unpublished} is not published"
    ):
        _retire(state, request, review)
    assert _retirement_entries(state) == []


def test_round12_live_head_contained_in_the_preserved_commit_retires(
    sample_repo: Path, tmp_path: Path
) -> None:
    state, request, request_head = _abandoned_request(sample_repo, tmp_path)
    (sample_repo / "newer.txt").write_text("origin moved on\n", encoding="utf-8")
    _git(sample_repo, "add", "newer.txt")
    _commit_all(sample_repo, "newer main")
    preserved = _publish_origin(sample_repo, tmp_path)
    _git(sample_repo, "reset", "-q", "--hard", request_head)
    assert _git(sample_repo, "rev-parse", "HEAD") != preserved

    review = _abandoned_review(tmp_path, state, request, preserved)
    assert _retire(state, request, review)["status"] == "RETIRED"


def _filler_qualified_requests(state: Path, template: dict[str, object], count: int) -> None:
    """Queue ``count`` resolved requests: each adds a request and a receipt entry."""

    for index in range(count):
        clone = json.loads(json.dumps(template))
        session = f"filler-{index:03d}"
        clone["session_id"] = session
        clone["request_id"] = f"{session}-{str(template['request_id']).rsplit('-', 1)[1]}"
        clone["receipt_path"] = str(state / "receipts" / f"{clone['request_id']}.json")
        clone["request_sha256"] = closeout_queue._request_hash(clone)
        (state / "requests" / f"{clone['request_id']}.json").write_bytes(
            closeout_queue._canonical_record(clone)
        )
        (state / "receipts").mkdir(exist_ok=True)
        (state / "receipts" / f"{clone['request_id']}.json").write_bytes(
            closeout_queue._canonical_record(_qualified_receipt(clone))
        )


@pytest.mark.parametrize("fillers", [254, 255])
def test_round12_retire_refuses_an_inventory_the_admission_reader_would_reject(
    sample_repo: Path, tmp_path: Path, fillers: int
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    _filler_qualified_requests(state, request, fillers)
    before = 2 * fillers + 1
    hashes = closeout_queue._queue_record_sha256s(sample_repo)[1]
    assert len(hashes) == before
    review = _abandoned_review(tmp_path, state, request, preserved)

    if before + 3 > 512:
        assert before == 511
        with pytest.raises(
            closeout_queue.CloseoutQueueError,
            match="grow the admission inventory to 514 entries and admission reads at most 512",
        ):
            _retire(state, request, review)
        # Nothing was published: no record, no evidence copy, no anchor.
        assert _retirement_entries(state) == []
        assert not (state / "retirement-evidence").exists()
        assert _git(sample_repo, "for-each-ref", "refs/seam/preserved") == ""
        assert closeout_queue._queue_record_sha256s(sample_repo)[1] == hashes
        return
    assert before == 509
    assert _retire(state, request, review)["status"] == "RETIRED"
    admitted = closeout_queue.admit(sample_repo)
    assert len(admitted["record_sha256s"]) == 512
    # The stored inventory is read back by every later admission.
    assert closeout_queue.admit(sample_repo)["record_sha256s"] == admitted["record_sha256s"]


@pytest.mark.parametrize("room", [0, 1])
def test_round12_inventory_bound_is_exact_and_counts_covered_orphan_receipts(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, room: int
) -> None:
    state, request, receipt_path, lost_id, preserved, _ = _qualified_with_lost_target(
        sample_repo, tmp_path
    )
    review = _retirement_review(
        tmp_path, kind="MISSING_SUPERSESSION_TARGETS", request=request, state_root=state,
        preserved_commit=preserved, receipt_bytes=receipt_path.read_bytes(), missing=[lost_id],
    )
    survivors = json.loads(review.read_text(encoding="utf-8"))["surviving_receipts"]
    assert survivors
    stored = len(closeout_queue._stored_receipts(request, state_root=state))
    # The request, its receipts, the three retirement entries and each
    # surviving receipt of a missing target.
    expected = 1 + stored + 3 + len(survivors)
    monkeypatch.setattr(closeout_queue, "ADMISSION_INVENTORY_LIMIT", expected - 1 + room)

    if not room:
        with pytest.raises(
            closeout_queue.CloseoutQueueError,
            match=f"grow the admission inventory to {expected} entries",
        ):
            _retire(state, request, review, receipt_path=receipt_path)
        assert _retirement_entries(state) == []
        return
    assert _retire(state, request, review, receipt_path=receipt_path)["status"] == "RETIRED"
    admitted = closeout_queue.admit(sample_repo)
    assert len(admitted["record_sha256s"]) == expected
    assert closeout_queue.admit(sample_repo)["record_sha256s"] == admitted["record_sha256s"]


def test_round12_never_retired_queue_over_the_bound_admits_as_on_origin_main(
    sample_repo: Path, tmp_path: Path
) -> None:
    state = _standard_queue(sample_repo)
    (sample_repo / "scratch.txt").write_text("scratch\n", encoding="utf-8")
    queued = session_end_closeout.handle_session_end(
        {"session_id": "template", "cwd": str(sample_repo)},
        repo_root=sample_repo, state_root=state, dispatch=False,
    )
    template = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    (state / "requests" / f"{template['request_id']}.json").unlink()
    _filler_qualified_requests(state, template, 257)

    # Pre-existing behaviour, deliberately untouched: admission publishes the
    # oversized inventory and only the next read rejects it.
    assert len(closeout_queue.admit(sample_repo)["record_sha256s"]) == 514
    with pytest.raises(
        closeout_queue.CloseoutQueueError, match="closeout admission record_sha256s is invalid"
    ):
        closeout_queue.admit(sample_repo)


def test_round12_file_replaced_by_a_symlink_with_a_matching_digest_is_refused(
    sample_repo: Path, tmp_path: Path
) -> None:
    link_text = b"elsewhere/target"
    (sample_repo / "link").symlink_to("README.md")
    _git(sample_repo, "add", "link")
    _commit_all(sample_repo, "tracked symlink")
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state, request, preserved)
    tracked = sample_repo / "README.md"
    pair = [{"path": "README.md", "worktree_sha256": _sha(link_text)}]
    authorization = _authorization(tmp_path, review, request, acknowledged_hidden_paths=pair)

    tracked.unlink()
    tracked.symlink_to(link_text.decode())
    with pytest.raises(
        closeout_queue.CloseoutQueueError, match="requires a clean tracked tree: README.md"
    ):
        _retire(state, request, review, authorization=authorization)
    assert _retirement_entries(state) == []

    # A retargeted tracked symlink is not acknowledgeable either.
    tracked.unlink()
    tracked.write_bytes(b"baseline\n")
    (sample_repo / "link").unlink()
    (sample_repo / "link").symlink_to(link_text.decode())
    retargeted = [{"path": "link", "worktree_sha256": _sha(link_text)}]
    with pytest.raises(
        closeout_queue.CloseoutQueueError, match="requires a clean tracked tree: link"
    ):
        _retire(state, request, review, authorization=_authorization(
            tmp_path, review, request, acknowledged_hidden_paths=retargeted
        ))
    assert _retirement_entries(state) == []

    # The clean tracked symlink still compares equal, and the same path/digest
    # pair is accepted for the regular file whose bytes it actually names.
    (sample_repo / "link").unlink()
    (sample_repo / "link").symlink_to("README.md")
    tracked.write_bytes(link_text)
    authorization = _authorization(tmp_path, review, request, acknowledged_hidden_paths=pair)
    assert _retire(state, request, review, authorization=authorization)["status"] == "RETIRED"


def test_round12_edit_during_the_per_file_proof_is_refused_before_publication(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state, request, preserved)
    real_blob = closeout_queue._worktree_blob
    compared: list[str] = []

    def edit_after_comparison(root, name, mode, oid, filemode):  # type: ignore[no-untyped-def]
        result = real_blob(root, name, mode, oid, filemode)
        compared.append(name)
        if name == "README.md":
            # README.md has just been proven clean; it changes before the
            # record is published.
            (root / name).write_bytes(b"edited while the proof ran")
        return result

    monkeypatch.setattr(closeout_queue, "_worktree_blob", edit_after_comparison)

    with pytest.raises(
        closeout_queue.CloseoutQueueError, match="live scope did not remain stable"
    ):
        _retire(state, request, review)
    assert "README.md" in compared
    assert _retirement_entries(state) == []
    assert not (state / "retirement-evidence").exists()


@pytest.mark.parametrize("root_kind", ["canonical", "relative", "symlinked"])
def test_round12_valid_unbound_evidence_copy_is_inert_for_any_spelling_of_the_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, root_kind: str
) -> None:
    host = tmp_path.resolve() / "host"
    state = host / ".seam" / "orchestration" / "session-end"
    evidence = state / "retirement-evidence"
    evidence.mkdir(parents=True)
    leftover = json.dumps({"schema": "seam-closeout-retirement-review/v1"}).encode("utf-8")
    (evidence / (_sha(leftover) + ".json")).write_bytes(leftover)
    if root_kind == "relative":
        monkeypatch.chdir(tmp_path)
        root = Path("host")
    elif root_kind == "symlinked":
        root = tmp_path.resolve() / "alias"
        root.symlink_to(host, target_is_directory=True)
    else:
        root = host
    relative_state = root / ".seam" / "orchestration" / "session-end"

    # No retirement exists, so the copy is ignored exactly as origin/main
    # ignores the whole directory.
    assert closeout_queue._queue_record_sha256s(root) == ([], [], set())
    assert closeout_queue.pending(relative_state) == {
        "profile": "seam_release_orchestrator",
        "requests": [],
        "administrative_dispositions": [],
    }

    # A stray entry is still refused for every spelling of the root.
    (evidence / "stray.json").write_bytes(leftover)
    with pytest.raises(
        closeout_queue.CloseoutQueueError, match="unexpected orphaned retirement evidence"
    ):
        closeout_queue._queue_record_sha256s(root)


# --- Round 13 -----------------------------------------------------------------


def _round13_edit_at(
    monkeypatch: pytest.MonkeyPatch, boundary: str, change
) -> list[str]:  # type: ignore[no-untyped-def]
    """Run ``change`` once, at a named point after the per-file comparison.

    ``before-evidence``: straight after the stability signature that follows
    the proof, before anything is published. ``before-link``: after the proof
    has returned, before the evidence copies and the retirement record.
    """

    fired: list[str] = []
    if boundary == "before-evidence":
        real_signatures = closeout_queue._retirement_signatures
        calls: list[int] = []

        def signatures(root, base):  # type: ignore[no-untyped-def]
            result = real_signatures(root, base)
            calls.append(1)
            if len(calls) == 2:
                fired.append(boundary)
                change()
            return result

        monkeypatch.setattr(closeout_queue, "_retirement_signatures", signatures)
    else:
        real_anchor = closeout_queue._anchor_preserved_commit

        def anchor(common_dir, commit):  # type: ignore[no-untyped-def]
            if not fired:
                fired.append(boundary)
                change()
            return real_anchor(common_dir, commit)

        monkeypatch.setattr(closeout_queue, "_anchor_preserved_commit", anchor)
    return fired


@pytest.mark.parametrize("boundary", ["before-evidence", "before-link"])
@pytest.mark.parametrize(
    "subject",
    ["skip-worktree", "assume-unchanged", "unflagged", "acknowledged", "acknowledged-mode"],
)
def test_round13_change_after_comparison_and_before_publication_is_refused(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    boundary: str, subject: str,
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    tracked = sample_repo / "README.md"
    acknowledged: list[dict[str, str]] = []
    if subject in {"skip-worktree", "assume-unchanged"}:
        _git(sample_repo, "update-index", f"--{subject}", "README.md")
    elif subject.startswith("acknowledged"):
        # As for the real subjects: a flagged path whose bytes differ from the
        # index and are acknowledged exactly.
        _git(sample_repo, "update-index", "--skip-worktree", "README.md")
        tracked.write_bytes(b"acknowledged bytes")
        acknowledged = [{"path": "README.md", "worktree_sha256": _sha(b"acknowledged bytes")}]
    compared_bytes = tracked.read_bytes()
    review = _abandoned_review(tmp_path, state, request, preserved)
    authorization = _authorization(
        tmp_path, review, request, acknowledged_hidden_paths=acknowledged
    )

    def change() -> None:
        if subject == "acknowledged-mode":
            tracked.chmod(0o755)
        else:
            tracked.write_bytes(b"edited after it was compared")

    fired = _round13_edit_at(monkeypatch, boundary, change)
    with pytest.raises(
        closeout_queue.CloseoutQueueError,
        match="live scope did not remain stable: README.md changed after it was compared",
    ):
        _retire(state, request, review, authorization=authorization)
    assert fired == [boundary]
    if subject != "unflagged":
        # Git reports nothing for the flagged path, before or after the edit.
        assert _git(sample_repo, "status", "--porcelain", "--untracked-files=no") == ""
    assert _retirement_entries(state) == []
    if boundary == "before-evidence":
        # Nothing was published: no record, no evidence copy, no anchor.
        assert not (state / "retirement-evidence").exists()
        assert _git(sample_repo, "for-each-ref", "refs/seam/preserved") == ""
    with pytest.raises(closeout_queue.CloseoutQueueError, match="unresolved requests"):
        closeout_queue.admit(sample_repo)

    # With the compared state restored, the same authorization retires it; an
    # evidence copy left by the refused attempt is inert.
    tracked.write_bytes(compared_bytes)
    tracked.chmod(0o644)
    assert _retire(state, request, review, authorization=authorization)["status"] == "RETIRED"
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []


@pytest.mark.parametrize("boundary", ["before-evidence", "before-link"])
@pytest.mark.parametrize("subject", ["skip-worktree", "unflagged", "acknowledged"])
def test_round13_unchanged_tree_retires_through_both_final_checks(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    boundary: str, subject: str,
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    acknowledged: list[dict[str, str]] = []
    if subject != "unflagged":
        _git(sample_repo, "update-index", "--skip-worktree", "README.md")
    if subject == "acknowledged":
        (sample_repo / "README.md").write_bytes(b"acknowledged bytes")
        acknowledged = [{"path": "README.md", "worktree_sha256": _sha(b"acknowledged bytes")}]
    review = _abandoned_review(tmp_path, state, request, preserved)
    authorization = _authorization(
        tmp_path, review, request, acknowledged_hidden_paths=acknowledged
    )
    real_reprove = closeout_queue._reprove_abandoned_scope
    reproved: list[set[str]] = []

    def reprove(proof):  # type: ignore[no-untyped-def]
        reproved.append(set(proof["examined"]))
        return real_reprove(proof)

    monkeypatch.setattr(closeout_queue, "_reprove_abandoned_scope", reprove)
    fired = _round13_edit_at(monkeypatch, boundary, lambda: None)

    assert _retire(state, request, review, authorization=authorization)["status"] == "RETIRED"
    assert fired == [boundary]
    # Once before anything is published and once at the record link, each over
    # every indexed path outside the capture.
    indexed = set(_git(sample_repo, "ls-files").splitlines())
    assert reproved == [indexed, indexed]
    assert "README.md" in indexed
    assert closeout_queue.admit(sample_repo)["pending_request_ids"] == []


def test_round13_retirement_bearing_inventory_over_the_bound_keeps_the_stored_record(
    sample_repo: Path, tmp_path: Path
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    _filler_qualified_requests(state, request, 254)
    review = _abandoned_review(tmp_path, state, request, preserved)
    assert _retire(state, request, review)["status"] == "RETIRED"
    admitted = closeout_queue.admit(sample_repo)
    assert len(admitted["record_sha256s"]) == 512
    common_dir = closeout_queue._common_dir(sample_repo)
    record_path = closeout_queue._admission_path(common_dir)
    stored = record_path.read_bytes()

    # Ordinary growth after the retirement: one more resolved request.
    _filler_qualified_requests(state, request, 255)
    grown = sorted(path for kind in ("requests", "receipts")
                   for path in (state / kind).glob("filler-254-*.json"))
    assert len(grown) == 2
    assert len(closeout_queue._queue_record_sha256s(sample_repo)[1]) == 514
    for _ in range(2):
        with pytest.raises(
            closeout_queue.CloseoutQueueError,
            match=(
                "closeout admission record_sha256s is invalid: admission reads at most "
                "512 entries per list and this inventory holds 514 record entries over "
                "1 roots; the stored admission record was left unchanged"
            ),
        ):
            closeout_queue.admit(sample_repo)
        # The last readable inventory is still stored, byte for byte.
        assert record_path.read_bytes() == stored
        assert closeout_queue._load_admission(record_path, common_dir) == admitted

    # Shrinking the queue repairs admission, because the stored record was
    # never replaced by one its reader rejects.
    for path in grown:
        path.unlink()
    again = closeout_queue.admit(sample_repo)
    assert again["record_sha256s"] == admitted["record_sha256s"]
    assert closeout_queue.admit(sample_repo)["record_sha256s"] == admitted["record_sha256s"]


@pytest.mark.parametrize("room", [0, 1])
def test_round13_inventory_bound_counts_the_records_of_every_admitted_root(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, room: int
) -> None:
    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    # A linked worktree is a second root admission reads; its queue holds two
    # resolved requests, each a request entry and a receipt entry.
    linked = tmp_path / "linked"
    _git(sample_repo, "worktree", "add", "-q", "-b", "other-root", str(linked))
    other_state = linked / ".seam" / "orchestration" / "session-end"
    (other_state / "requests").mkdir(parents=True)
    _filler_qualified_requests(other_state, request, 2)
    assert len(closeout_queue._queue_record_sha256s(linked)[1]) == 4
    assert len(closeout_queue._queue_record_sha256s(sample_repo)[1]) == 1
    # The subject's request and its three retirement entries, plus the other root.
    expected = 1 + 3 + 4
    monkeypatch.setattr(closeout_queue, "ADMISSION_INVENTORY_LIMIT", expected - 1 + room)
    review = _abandoned_review(tmp_path, state, request, preserved)

    if not room:
        with pytest.raises(
            closeout_queue.CloseoutQueueError,
            match=f"grow the admission inventory to {expected} entries",
        ):
            _retire(state, request, review)
        assert _retirement_entries(state) == []
        assert not (state / "retirement-evidence").exists()
        return
    assert _retire(state, request, review)["status"] == "RETIRED"
    admitted = closeout_queue.admit(sample_repo)
    assert len(admitted["record_sha256s"]) == expected
    assert len(admitted["observed_roots"]) == 2
    assert closeout_queue.admit(sample_repo)["record_sha256s"] == admitted["record_sha256s"]


_ROUND14_DATETIME = closeout_queue.datetime


class _Round14Clock(_ROUND14_DATETIME):
    """A fixed admitted_at, so an admission record's encoded size is exact."""

    @classmethod
    def now(cls, tz=None):  # type: ignore[no-untyped-def,override]
        return _ROUND14_DATETIME(2026, 11, 25, 12, 0, 0, tzinfo=tz)


def _round14_files(directory: Path) -> dict[str, bytes]:
    if not directory.exists():
        return {}
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }


def _round14_admit(repo: Path, **kwargs: object) -> tuple[str, object]:
    """``admit`` with the writer/reader invariant asserted around it.

    Refused: the stored record and the root registrations are byte for byte
    what they were, and still readable. Admitted: the reader accepts what was
    stored, and so does the next plain ``admit``.
    """

    common_dir = closeout_queue._common_dir(repo)
    record_path = closeout_queue._admission_path(common_dir)
    stored_state = common_dir / "seam-orchestration"
    before = _round14_files(stored_state)
    try:
        record = closeout_queue.admit(repo, **kwargs)
    except closeout_queue.CloseoutQueueError as exc:
        assert _round14_files(stored_state) == before, (
            f"a refused admit changed the stored admission state: {exc}"
        )
        closeout_queue._load_admission(record_path, common_dir)
        closeout_queue._load_registered_roots(common_dir)
        return "refused", str(exc)
    try:
        assert closeout_queue._load_admission(record_path, common_dir) == record
        closeout_queue._load_registered_roots(common_dir)
        again = closeout_queue.admit(repo)
    except closeout_queue.CloseoutQueueError as exc:
        pytest.fail(
            "admit stored a record its own reader rejects on the next call: "
            f"{exc} ({len(record['record_sha256s'])} record entries over "
            f"{len(record['observed_roots'])} roots, "
            f"{record_path.stat().st_size} stored bytes)"
        )
    assert again["record_sha256s"] == record["record_sha256s"]
    return "admitted", record


def _round14_directory_of_length(parent: Path, length: int) -> Path:
    """A new directory under ``parent`` whose path is exactly ``length`` characters."""

    path = parent
    assert len(str(path)) <= length - 2
    while len(str(path)) < length:
        room = length - len(str(path)) - 1
        take = min(200, room)
        if room - take == 1:
            # Never leave one character: a component needs its separator too.
            take -= 1
        path = path / ("d" * take)
    path.mkdir(parents=True)
    assert len(str(path)) == length
    return path


def _round14_largest_other_record(repo: Path, state: Path) -> int:
    record_path = closeout_queue._admission_path(closeout_queue._common_dir(repo))
    return max(
        path.stat().st_size
        for root in (state, record_path.parent)
        for path in root.rglob("*")
        if path.is_file() and path != record_path
    )


def test_round14_record_byte_bound_is_checked_before_the_stored_record_is_replaced(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reader bounds the whole encoded record, not only its four lists.

    MAX_RECORD_BYTES is shrunk here, as other tests shrink
    ADMISSION_INVENTORY_LIMIT: at the real 1 MiB it takes about 170 roots with
    paths near 1000 characters on top of a full 512-entry inventory.
    """

    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state, request, preserved)
    assert _retire(state, request, review)["status"] == "RETIRED"
    monkeypatch.setattr(closeout_queue, "datetime", _Round14Clock)
    status, admitted = _round14_admit(sample_repo)
    assert status == "admitted"
    common_dir = closeout_queue._common_dir(sample_repo)
    record_path = closeout_queue._admission_path(common_dir)
    stored = record_path.read_bytes()
    assert stored == closeout_queue._canonical_record(admitted)

    _filler_qualified_requests(state, request, 40)
    bound = _round14_largest_other_record(sample_repo, state) + 1024
    monkeypatch.setattr(closeout_queue, "MAX_RECORD_BYTES", bound)
    entries = closeout_queue._queue_record_sha256s(sample_repo)[1]
    # Every list is inside its limits; only the encoded record is too large.
    assert len(entries) == 84 < closeout_queue.ADMISSION_INVENTORY_LIMIT
    assert sum(len(entry) for entry in entries) > bound

    for _ in range(2):
        status, detail = _round14_admit(sample_repo)
        assert status == "refused", detail
        assert (
            f"closeout admission record is invalid: admission reads a record of at "
            f"most {bound} bytes and this inventory encodes to "
        ) in str(detail)
        assert "84 record entries over 1 roots" in str(detail)
        assert "the stored admission record was left unchanged" in str(detail)
        assert record_path.read_bytes() == stored
        assert closeout_queue._load_admission(record_path, common_dir) == admitted

    # Shrinking the queue repairs admission: the stored record stayed readable.
    for kind in ("requests", "receipts"):
        for path in (state / kind).glob("filler-*.json"):
            path.unlink()
    status, again = _round14_admit(sample_repo)
    assert status == "admitted"
    assert again["record_sha256s"] == admitted["record_sha256s"]


def test_round14_never_retired_queue_keeps_origin_main_behaviour_at_the_byte_bound(
    sample_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The byte check belongs to retirement-bearing inventories only."""

    state = _standard_queue(sample_repo)
    (sample_repo / "scratch.txt").write_text("scratch\n", encoding="utf-8")
    queued = session_end_closeout.handle_session_end(
        {"session_id": "template", "cwd": str(sample_repo)},
        repo_root=sample_repo,
        state_root=state,
        dispatch=False,
    )
    template = json.loads(Path(str(queued["request_path"])).read_text(encoding="utf-8"))
    (state / "requests" / f"{template['request_id']}.json").unlink()
    _filler_qualified_requests(state, template, 40)
    assert not (state / "retirements").exists()
    monkeypatch.setattr(closeout_queue, "datetime", _Round14Clock)
    common_dir = closeout_queue._common_dir(sample_repo)
    record_path = closeout_queue._admission_path(common_dir)
    size = len(closeout_queue._canonical_record(closeout_queue.admit(sample_repo)))
    assert record_path.stat().st_size == size
    record_path.unlink()
    assert _round14_largest_other_record(sample_repo, state) < size - 1
    monkeypatch.setattr(closeout_queue, "MAX_RECORD_BYTES", size - 1)

    # As on origin/main: the oversized record is stored, and the next read fails.
    assert len(closeout_queue.admit(sample_repo)["record_sha256s"]) == 80
    assert record_path.stat().st_size == size
    with pytest.raises(closeout_queue.CloseoutQueueError, match="closeout record exceeds 1 MiB"):
        closeout_queue.admit(sample_repo)


@pytest.mark.parametrize("length", [1000, 1001])
def test_round14_retire_register_root_never_stores_a_registration_its_reader_rejects(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, length: int
) -> None:
    """The registry reader takes a root of at most 1000 characters."""

    monkeypatch.setattr(closeout_queue, "datetime", _Round14Clock)
    # A request's own repo.root is limited to 1000 characters, so the long
    # host holds a request captured in another root, as retained hosts may.
    _, _, captured, _, lost_id, preserved, common_dir = _unregistered_host_without_git(
        sample_repo, tmp_path, remove_git=True
    )
    host = _round14_directory_of_length(tmp_path / "long", length)
    host_queue = host / ".seam" / "orchestration" / "session-end"
    (host_queue / "requests").mkdir(parents=True)
    (host_queue / "receipts").mkdir()
    second = json.loads(json.dumps(captured))
    receipt_path = host_queue / "receipts" / f"{second['request_id']}.json"
    second["receipt_path"] = str(receipt_path)
    second["request_sha256"] = closeout_queue._request_hash(second)
    (host_queue / "requests" / f"{second['request_id']}.json").write_bytes(
        closeout_queue._canonical_record(second)
    )
    qualified = _qualified_receipt(second)
    qualified["supersedes_request_ids"] = [lost_id]
    receipt_path.write_bytes(closeout_queue._canonical_record(qualified))
    review = _retirement_review(
        tmp_path,
        kind="MISSING_SUPERSESSION_TARGETS",
        request=second,
        state_root=host_queue,
        preserved_commit=preserved,
        receipt_bytes=receipt_path.read_bytes(),
        missing=[lost_id],
        repository_common_dir=str(common_dir),
    )
    authorization = _authorization(tmp_path, review, second)
    # The host is neither a worktree nor registered: the repository admits.
    assert _round14_admit(sample_repo)[0] == "admitted"
    queue_before = _round14_files(host_queue)
    stored_before = _round14_files(common_dir / "seam-orchestration")
    refs_before = _git(sample_repo, "for-each-ref")
    assert "refs/seam/preserved" not in refs_before

    def retire() -> dict[str, str]:
        return _retire(
            host_queue, second, review, authorization=authorization,
            receipt_path=receipt_path, register_root=host,
        )

    if length == 1000:
        # Exactly at the reader's limit: registered, and admission reads it.
        assert retire()["status"] == "RETIRED"
        assert closeout_queue._load_registered_roots(common_dir) == [host]
        status, admitted = _round14_admit(sample_repo)
        assert status == "admitted"
        assert str(host) in admitted["registered_roots"]
        return
    for _ in range(2):
        with pytest.raises(
            closeout_queue.CloseoutQueueError,
            match=(
                "retirement register_root cannot be registered: closeout retained-root "
                "path is invalid: the registry reads a root of at most 1000 characters "
                "and this one has 1001; nothing was published"
            ),
        ):
            retire()
        # Nothing was published: no evidence, anchor, record or registration.
        assert _round14_files(host_queue) == queue_before
        assert _retirement_entries(host_queue) == []
        assert not (host_queue / "retirement-evidence").exists()
        assert _round14_files(common_dir / "seam-orchestration") == stored_before
        assert _git(sample_repo, "for-each-ref") == refs_before
        assert closeout_queue._load_registered_roots(common_dir) == []
        # The repository is not wedged: admission reads its state and passes.
        assert _round14_admit(sample_repo)[0] == "admitted"


@pytest.mark.parametrize("boundary", ["list-length", "item-length", "byte-size"])
def test_round14_every_successful_retirement_bearing_admit_stores_a_readable_record(
    sample_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    """After ANY successful admit of a retirement-bearing queue the stored
    record is readable by ``_load_admission``; a refusal changes nothing.

    Each case walks one reader limit: exactly at it (admitted), one step over
    (refused, with the cause named), back inside (admitted). Every admit goes
    through ``_round14_admit``, which asserts the invariant either way.
    """

    state, request, preserved = _abandoned_request(sample_repo, tmp_path)
    review = _abandoned_review(tmp_path, state, request, preserved)
    assert _retire(state, request, review)["status"] == "RETIRED"
    _filler_qualified_requests(state, request, 3)
    monkeypatch.setattr(closeout_queue, "datetime", _Round14Clock)
    common_dir = closeout_queue._common_dir(sample_repo)
    record_path = closeout_queue._admission_path(common_dir)

    def one_more_filler() -> list[Path]:
        _filler_qualified_requests(state, request, 4)
        added = sorted(
            path for kind in ("requests", "receipts")
            for path in (state / kind).glob("filler-003-*.json")
        )
        assert len(added) == 2
        return added

    if boundary == "list-length":
        entries = len(closeout_queue._queue_record_sha256s(sample_repo)[1])
        assert entries == 4 + 6
        monkeypatch.setattr(closeout_queue, "ADMISSION_INVENTORY_LIMIT", entries)
        grow = one_more_filler
        cause = (
            f"closeout admission record_sha256s is invalid: admission reads at most "
            f"{entries} entries per list and this inventory holds {entries + 2} record "
            "entries over 1 roots; the stored admission record was left unchanged. "
            "Reduce the queued records"
        )
    elif boundary == "item-length":
        at_limit = _round14_directory_of_length(tmp_path / "at-limit", 1000)
        _git(sample_repo, "worktree", "add", "-q", "-b", "at-limit", str(at_limit))

        def grow() -> list[Path]:
            over = _round14_directory_of_length(tmp_path / "over-limit", 1001)
            _git(sample_repo, "worktree", "add", "-q", "-b", "over-limit", str(over))
            return [over]

        cause = (
            "closeout admission observed_roots is invalid: admission reads entries of "
            "at most 1000 characters in observed_roots and this inventory holds one of "
            "1001; the stored admission record was left unchanged. Remove or shorten"
        )
    else:
        added = one_more_filler()
        size = len(closeout_queue._canonical_record(closeout_queue.admit(sample_repo)))
        assert record_path.stat().st_size == size
        for path in added:
            path.unlink()
        assert _round14_largest_other_record(sample_repo, state) < size - 2
        with_three = len(closeout_queue._canonical_record(closeout_queue.admit(sample_repo)))
        assert with_three < size - 1
        # One byte short of what the grown inventory needs.
        monkeypatch.setattr(closeout_queue, "MAX_RECORD_BYTES", size - 1)
        grow = one_more_filler
        cause = (
            f"closeout admission record is invalid: admission reads a record of at "
            f"most {size - 1} bytes and this inventory encodes to {size} bytes (12 "
            "record entries over 1 roots); the stored admission record was left "
            "unchanged. Reduce the queued records"
        )

    status, at_the_limit = _round14_admit(sample_repo)
    assert status == "admitted", at_the_limit
    stored = record_path.read_bytes()

    added = grow()
    for _ in range(2):
        status, detail = _round14_admit(sample_repo)
        assert status == "refused", detail
        assert cause in str(detail)
        assert record_path.read_bytes() == stored

    if boundary == "byte-size":
        # Exactly the reader's limit is a record the reader accepts.
        monkeypatch.setattr(closeout_queue, "MAX_RECORD_BYTES", size)
        status, grown = _round14_admit(sample_repo)
        assert status == "admitted", grown
        assert record_path.stat().st_size == size
        monkeypatch.setattr(closeout_queue, "MAX_RECORD_BYTES", size - 1)
        record_path.write_bytes(stored)
    for path in added:
        if boundary == "item-length":
            _git(sample_repo, "worktree", "remove", "--force", str(path))
        else:
            path.unlink()
    status, back_inside = _round14_admit(sample_repo)
    assert status == "admitted", back_inside
    assert back_inside["record_sha256s"] == at_the_limit["record_sha256s"]
