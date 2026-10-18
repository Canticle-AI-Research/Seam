"""Public CLI contract for recovery-bound same-worktree successor sessions."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tools.agents import (
    assurance,
    closeout_queue,
    context_guardian,
    session_end_closeout,
    session_state,
    successor,
)

SOURCE_ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _state(session_id: str, base: str) -> dict[str, object]:
    cycle = {
        "behavior": "the predecessor captured one witnessed behavior",
        "test_refs": ["tests/audit/test_successor_transition.py::test_successor_cli_preserves_predecessor_and_resumes_immutable_intent"],
        "implementation_refs": ["seam_runtime/feature.py"],
        "red": {
            "command": "pytest predecessor-red",
            "exit_code": 1,
            "observed_at": "2026-10-17T12:00:00Z",
            "fingerprint": "predecessor-red",
        },
        "green": {
            "command": "pytest predecessor-green",
            "exit_code": 0,
            "observed_at": "2026-10-17T12:01:00Z",
            "fingerprint": "predecessor-green",
        },
    }
    return {
        "schema": "seam-agent-session-state/v1",
        "session_id": session_id,
        "base_sha": base,
        "objective": "Complete the interrupted candidate.",
        "plan": ["Preserve predecessor evidence."],
        "constraints": ["Use one same-root successor."],
        "affected_tests": ["tests/audit/test_successor_transition.py"],
        "tdd_cycles": [cycle],
    }


def _blocked_receipt(request: dict[str, object]) -> dict[str, object]:
    repo = request["repo"]
    tdd = request["tdd_evidence"]
    assert isinstance(repo, dict) and isinstance(tdd, dict)
    return {
        "schema": "seam-agent-closeout-receipt/v1",
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "session_id": request["session_id"],
        "completed_at": (
            datetime.fromisoformat(str(request["created_at"]).replace("Z", "+00:00"))
            + timedelta(minutes=1)
        ).isoformat(),
        "status": "BLOCKED",
        "supersedes_request_ids": [],
        "scope": {
            "head": repo["head"],
            "diff_fingerprint": repo["diff_fingerprint"],
            "matches_request": True,
        },
        "tdd": {"status": tdd["status"], "evidence": ["predecessor evidence checked"]},
        "checks": [
            {
                "requirement": requirement,
                "command": requirement,
                "status": "PASS",
                "exit_code": 0,
                "evidence": "passed",
            }
            for requirement in request["required_checks"]  # type: ignore[index]
        ],
        "continuity": {
            "status": "BLOCKED",
            "evidence": ["Recovery requires an explicit successor transition."],
        },
        "project_alignment": {"status": "ALIGNED", "evidence": ["aligned"]},
        "next_action": "Create the same-root successor.",
    }


@pytest.fixture
def recovered_repo(tmp_path: Path) -> tuple[Path, str, str, Path, dict[str, object]]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "SEAM tests")
    (repo / ".gitignore").write_text(".seam/\n.context-handoffs/\n", encoding="utf-8")
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    runtime = repo / "seam_runtime" / "feature.py"
    runtime.parent.mkdir()
    runtime.write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "add", ".gitignore", "README.md", "seam_runtime/feature.py")
    _git(repo, "commit", "-qm", "baseline")
    base = _git(repo, "rev-parse", "HEAD")
    predecessor = "predecessor-session"
    state_root = repo / ".seam" / "orchestration" / "sessions"
    state_root.mkdir(parents=True)
    state_path = state_root / f"{predecessor}.json"
    state_path.write_text(json.dumps(_state(predecessor, base)), encoding="utf-8")
    assurance.register(repo, predecessor, base)
    runtime.write_text("VALUE = 2\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "candidate")
    context_guardian.observe(
        session_id=predecessor,
        used_tokens=45,
        context_limit=100,
        at_coherent_milestone=False,
        summary=["The runtime candidate and TDD evidence are durable."],
        next_step="Complete the exact candidate review.",
        state_root=repo / ".seam" / "orchestration" / "context",
        handoff_root=repo / ".context-handoffs",
    )
    context_guardian.recover_unexpected_compaction(
        session_id=predecessor,
        event_id="automatic-compaction-1",
        summary=["The predecessor stopped after an unexpected compaction."],
        next_step="Resume through a same-root successor.",
        state_root=repo / ".seam" / "orchestration" / "context",
        handoff_root=repo / ".context-handoffs",
    )
    queue_root = repo / ".seam" / "orchestration" / "session-end"
    queued = session_end_closeout.handle_session_end(
        {"session_id": predecessor, "cwd": str(repo)},
        repo_root=repo,
        state_root=queue_root,
        dispatch=False,
    )
    request_path = Path(str(queued["request_path"]))
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request["repo"]["base_sha"] == base
    assert request["tdd_evidence"]["status"] == "TDD_PROVEN"
    assert request["tdd_evidence"]["cycles"] == _state(predecessor, base)["tdd_cycles"]
    closeout_queue.store_receipt(request, _blocked_receipt(request), state_root=queue_root)
    return repo, base, predecessor, state_root, request


def _session_cli(repo: Path, state_root: Path, session_id: str, *arguments: str):
    env = os.environ.copy()
    env["CODEX_SESSION_ID"] = session_id
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.agents.session_state",
            "--repo-root",
            str(repo),
            "--state-root",
            str(state_root),
            *arguments,
        ],
        cwd=SOURCE_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_successor_cli_preserves_predecessor_and_resumes_immutable_intent(
    recovered_repo: tuple[Path, str, str, Path, dict[str, object]],
) -> None:
    repo, base, predecessor, state_root, request = recovered_repo
    protected = [
        state_root / f"{predecessor}.json",
        repo / ".seam" / "orchestration" / "context" / "recoveries" / predecessor / "automatic-compaction-1.json",
        repo / ".seam" / "orchestration" / "context" / "checkpoints" / f"{predecessor}.json",
        repo / ".context-handoffs" / f"context-handoff-{predecessor}.md",
        repo / ".seam" / "orchestration" / "session-end" / "requests" / f"{request['request_id']}.json",
        repo / ".seam" / "orchestration" / "session-end" / "receipts" / f"{request['request_id']}.json",
    ]
    before = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in protected}
    args = (
        "successor",
        "--predecessor-session",
        predecessor,
        "--request-id",
        str(request["request_id"]),
        "--recovery-event",
        "automatic-compaction-1",
        "--objective",
        "Resume the interrupted candidate without resetting evidence.",
        "--plan",
        "Finish the reviewed slice.",
        "--constraint",
        "Preserve the predecessor bytes.",
        "--affected-test",
        "tests/audit/test_successor_transition.py",
    )
    created = _session_cli(repo, state_root, "successor-session", *args)
    assert created.returncode == 0, created.stderr
    repeated = _session_cli(repo, state_root, "successor-session", *args)
    assert repeated.returncode == 0, repeated.stderr
    assert {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in protected} == before
    successor_state = json.loads((state_root / "successor-session.json").read_text())
    predecessor_state = json.loads((state_root / f"{predecessor}.json").read_text())
    assert successor_state["base_sha"] == base
    assert successor_state["tdd_cycles"] == predecessor_state["tdd_cycles"]
    appended = _session_cli(
        repo,
        state_root,
        "successor-session",
        "record-tdd",
        "--behavior", "the successor appends a new witnessed cycle",
        "--test-ref", "tests/audit/test_successor_transition.py::test_successor_cli_preserves_predecessor_and_resumes_immutable_intent",
        "--implementation-ref", "seam_runtime/feature.py",
        "--red-command", "pytest successor-red",
        "--red-exit", "1",
        "--red-fingerprint", "successor-red",
        "--green-command", "pytest successor-green",
        "--green-exit", "0",
        "--green-fingerprint", "successor-green",
    )
    assert appended.returncode == 0, appended.stderr
    appended_state = json.loads((state_root / "successor-session.json").read_text())
    assert appended_state["tdd_cycles"][:-1] == predecessor_state["tdd_cycles"]
    common = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    registration = json.loads(
        (common / "seam-orchestration" / "assurance" / "registrations" / "successor-session.json").read_text()
    )
    assert len(registration["successor_transition_sha256"]) == 64


def test_public_registration_cannot_bypass_recovered_active_binding(
    recovered_repo: tuple[Path, str, str, Path, dict[str, object]],
) -> None:
    repo, base, _, _, _ = recovered_repo
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.agents.assurance",
            "--repo-root",
            str(repo),
            "register",
            "--session-id",
            "bypass-session",
            "--base-sha",
            base,
        ],
        cwd=SOURCE_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "successor transition CLI" in result.stderr


def test_successor_retry_preserves_valid_appended_runtime_cycle(
    recovered_repo: tuple[Path, str, str, Path, dict[str, object]],
) -> None:
    repo, _, predecessor, state_root, request = recovered_repo
    arguments = (
        "successor",
        "--predecessor-session", predecessor,
        "--request-id", str(request["request_id"]),
        "--recovery-event", "automatic-compaction-1",
        "--objective", "Resume and preserve successor-authored coverage.",
    )
    created = _session_cli(repo, state_root, "successor-appended", *arguments)
    assert created.returncode == 0, created.stderr
    runtime = repo / "seam_runtime" / "successor_added.py"
    runtime.write_text("VALUE = 3\n", encoding="utf-8")
    appended = _session_cli(
        repo,
        state_root,
        "successor-appended",
        "record-tdd",
        "--behavior", "the successor covers its newly added runtime module",
        "--test-ref", "tests/audit/test_successor_transition.py::test_successor_retry_preserves_valid_appended_runtime_cycle",
        "--implementation-ref", "seam_runtime/successor_added.py",
        "--red-command", "pytest successor-appended-red",
        "--red-exit", "1",
        "--red-fingerprint", "successor-appended-red",
        "--green-command", "pytest successor-appended-green",
        "--green-exit", "0",
        "--green-fingerprint", "successor-appended-green",
    )
    assert appended.returncode == 0, appended.stderr
    before = (state_root / "successor-appended.json").read_bytes()

    retried = _session_cli(repo, state_root, "successor-appended", *arguments)

    assert retried.returncode == 0, retried.stderr
    assert (state_root / "successor-appended.json").read_bytes() == before


def test_concurrent_competing_successor_claim_is_rejected(
    recovered_repo: tuple[Path, str, str, Path, dict[str, object]],
) -> None:
    repo, _, predecessor, state_root, request = recovered_repo
    common = (
        "successor",
        "--predecessor-session", predecessor,
        "--request-id", str(request["request_id"]),
        "--recovery-event", "automatic-compaction-1",
        "--objective", "Resume safely.",
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda session_id: _session_cli(repo, state_root, session_id, *common),
                ("successor-one", "successor-two"),
            )
        )
    assert sorted(result.returncode for result in results) == [0, 1]
    assert "competing or conflicting" in next(result.stderr for result in results if result.returncode)
    common_dir = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    active = list((common_dir / "seam-orchestration" / "assurance" / "active").glob("*.json"))
    registrations = list((common_dir / "seam-orchestration" / "assurance" / "registrations").glob("successor-*.json"))
    assert len(active) == 1
    assert len(registrations) == 1
    assert json.loads(active[0].read_text())["session_id"] in {"successor-one", "successor-two"}


def test_concurrent_identical_successor_retry_reuses_immutable_timestamp(
    recovered_repo: tuple[Path, str, str, Path, dict[str, object]],
) -> None:
    repo, _, predecessor, state_root, request = recovered_repo
    arguments = (
        "successor",
        "--predecessor-session", predecessor,
        "--request-id", str(request["request_id"]),
        "--recovery-event", "automatic-compaction-1",
        "--objective", "Resume the same immutable successor intent.",
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _: _session_cli(
                    repo, state_root, "successor-identical", *arguments
                ),
                range(2),
            )
        )
    assert [result.returncode for result in results] == [0, 0], [
        result.stderr for result in results
    ]
    common = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    assert len(list((common / "seam-orchestration" / "successors").glob("*.json"))) == 1


def test_retry_resumes_after_crash_immediately_after_immutable_intent(
    recovered_repo: tuple[Path, str, str, Path, dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo, _, predecessor, state_root, request = recovered_repo
    monkeypatch.setenv("CODEX_SESSION_ID", "crash-resume-successor")
    original = successor._publish_once
    calls = 0

    def fail_after_intent(path: Path, encoded: bytes) -> bool:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected crash after immutable intent")
        return original(path, encoded)

    monkeypatch.setattr(successor, "_publish_once", fail_after_intent)
    arguments = [
        "--repo-root", str(repo),
        "--state-root", str(state_root),
        "successor",
        "--predecessor-session", predecessor,
        "--request-id", str(request["request_id"]),
        "--recovery-event", "automatic-compaction-1",
        "--objective", "Resume the immutable intent after a crash.",
    ]
    assert session_state.main(arguments) == 1
    common = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    transition_path = next((common / "seam-orchestration" / "successors").glob("*.json"))
    intent_bytes = transition_path.read_bytes()
    assert not (state_root / "crash-resume-successor.json").exists()
    monkeypatch.setattr(successor, "_publish_once", original)
    assert session_state.main(arguments) == 0
    assert transition_path.read_bytes() == intent_bytes


@pytest.mark.parametrize("failure_point", ["state", "registration", "active"])
def test_retry_recovers_each_partial_activation_step(
    recovered_repo: tuple[Path, str, str, Path, dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    repo, _, predecessor, state_root, request = recovered_repo
    session_id = f"partial-{failure_point}"
    monkeypatch.setenv("CODEX_SESSION_ID", session_id)
    arguments = [
        "--repo-root", str(repo),
        "--state-root", str(state_root),
        "successor",
        "--predecessor-session", predecessor,
        "--request-id", str(request["request_id"]),
        "--recovery-event", "automatic-compaction-1",
        "--objective", f"Resume after {failure_point} failure.",
    ]
    restore: tuple[object, str, object]
    if failure_point == "state":
        original = successor._publish_once
        calls = 0

        def fail_state(path: Path, encoded: bytes) -> bool:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected state failure")
            return original(path, encoded)

        monkeypatch.setattr(successor, "_publish_once", fail_state)
        restore = (successor, "_publish_once", original)
    elif failure_point == "registration":
        original = assurance._publish_once

        def fail_registration(path: Path, encoded: bytes) -> bool:
            raise OSError("injected registration failure")

        monkeypatch.setattr(assurance, "_publish_once", fail_registration)
        restore = (assurance, "_publish_once", original)
    else:
        original = assurance._write_replace

        def fail_active(path: Path, value: dict[str, object]) -> None:
            raise OSError("injected active failure")

        monkeypatch.setattr(assurance, "_write_replace", fail_active)
        restore = (assurance, "_write_replace", original)
    assert session_state.main(arguments) == 1
    try:
        incomplete = assurance.check_session(repo, session_id)
    except assurance.AssuranceError:
        incomplete = {"status": "FAIL_CLOSED"}
    assert incomplete["status"] != "PASS"
    monkeypatch.setattr(restore[0], restore[1], restore[2])
    assert session_state.main(arguments) == 0
    registration_path = assurance._registration_path(assurance._common_dir(repo), session_id)
    assert registration_path.is_file()
    assert "successor_transition_sha256" in json.loads(registration_path.read_text())


def test_successor_exact_assurance_allows_push_before_qualified_supersession(
    recovered_repo: tuple[Path, str, str, Path, dict[str, object]], tmp_path: Path
) -> None:
    repo, base, predecessor, state_root, predecessor_request = recovered_repo
    created = _session_cli(
        repo,
        state_root,
        "successor-reviewed",
        "successor",
        "--predecessor-session", predecessor,
        "--request-id", str(predecessor_request["request_id"]),
        "--recovery-event", "automatic-compaction-1",
        "--objective", "Finish and independently review the same candidate.",
        "--affected-test", "tests/audit/test_successor_transition.py",
    )
    assert created.returncode == 0, created.stderr
    head = _git(repo, "rev-parse", "HEAD")
    paths, _ = session_end_closeout._changed_paths(repo, base)
    report = {
        "schema": "seam-independent-assurance/v1",
        "repository": "Canticle-AI-Research/Seam",
        "session_id": "successor-reviewed",
        "base_sha": base,
        "head": head,
        "changed_paths": paths,
        "content_sha256": session_end_closeout._fingerprint(repo, head, base, paths),
        "reviewed_at": "2026-10-17T13:00:00Z",
        "reviewer": "independent-reviewer",
        "status": "PASS",
        "continuity_included": True,
        "summary": ["Reviewed the exact successor candidate and transition."],
    }
    report_path = tmp_path / "successor-assurance.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    assert assurance.accept(repo, "successor-reviewed", report_path)["status"] == "ACCEPTED"
    assert assurance.check_push(repo, head)["status"] == "PASS"
    with pytest.raises(assurance.AssuranceError, match="outgoing head"):
        assurance.check_push(repo, base)

    queue_root = repo / ".seam" / "orchestration" / "session-end"
    queued = session_end_closeout.handle_session_end(
        {"session_id": "successor-reviewed", "cwd": str(repo)},
        repo_root=repo,
        state_root=queue_root,
        dispatch=False,
    )
    request = json.loads(Path(str(queued["request_path"])).read_text())
    assert request["repo"]["base_sha"] == base
    assert request["tdd_evidence"]["status"] == "TDD_PROVEN"
    assert request["tdd_evidence"]["cycles"] == json.loads(
        (state_root / f"{predecessor}.json").read_text()
    )["tdd_cycles"]
    receipt = _blocked_receipt(request)
    receipt["status"] = "QUALIFIED"
    receipt["continuity"] = {"status": "PASS", "evidence": ["hosted checks passed"]}
    receipt["next_action"] = "Merge the exact reviewed successor candidate."
    with pytest.raises(closeout_queue.CloseoutQueueError, match="supersede.*predecessor"):
        closeout_queue.store_receipt(request, receipt, state_root=queue_root)
    receipt["supersedes_request_ids"] = [predecessor_request["request_id"]]
    stored = closeout_queue.store_receipt(request, receipt, state_root=queue_root)
    assert stored["status"] == "STORED"
    assert closeout_queue.pending(queue_root)["requests"] == []
    (repo / "seam_runtime" / "feature.py").write_text("VALUE = 2  \n", encoding="utf-8")
    with pytest.raises(assurance.AssuranceError, match="clean committed candidate"):
        assurance.check_push(repo, head)


def test_successor_assurance_rejects_inherited_mutation_and_missing_new_runtime_coverage(
    recovered_repo: tuple[Path, str, str, Path, dict[str, object]],
) -> None:
    repo, _, predecessor, state_root, predecessor_request = recovered_repo
    created = _session_cli(
        repo, state_root, "successor-evidence",
        "successor",
        "--predecessor-session", predecessor,
        "--request-id", str(predecessor_request["request_id"]),
        "--recovery-event", "automatic-compaction-1",
        "--objective", "Preserve inherited evidence.",
    )
    assert created.returncode == 0, created.stderr
    successor_path = state_root / "successor-evidence.json"
    original = successor_path.read_bytes()
    state = json.loads(original)
    state["tdd_cycles"][0]["green"]["fingerprint"] = "mutated"
    successor_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises((assurance.AssuranceError, successor.SuccessorError), match="inherited"):
        assurance.check_session(repo, "successor-evidence")
    successor_path.write_bytes(original)
    new_runtime = repo / "seam_runtime" / "uncovered.py"
    new_runtime.write_text("VALUE = 1\n", encoding="utf-8")
    queue_root = repo / ".seam" / "orchestration" / "session-end"
    queued = session_end_closeout.handle_session_end(
        {"session_id": "successor-evidence", "cwd": str(repo)},
        repo_root=repo,
        state_root=queue_root,
        dispatch=False,
    )
    request = json.loads(Path(str(queued["request_path"])).read_text())
    assert request["tdd_evidence"]["status"] == "TDD_UNPROVEN"
    assert "seam_runtime/uncovered.py" in request["tdd_evidence"]["missing_runtime_paths"]


@pytest.mark.parametrize("dependency", ["checkpoint", "registration", "active"])
def test_successor_dependency_loss_or_tampering_fails_closed(
    recovered_repo: tuple[Path, str, str, Path, dict[str, object]],
    dependency: str,
) -> None:
    repo, _, predecessor, state_root, request = recovered_repo
    created = _session_cli(
        repo, state_root, "successor-dependency",
        "successor",
        "--predecessor-session", predecessor,
        "--request-id", str(request["request_id"]),
        "--recovery-event", "automatic-compaction-1",
        "--objective", "Bind every predecessor dependency.",
    )
    assert created.returncode == 0, created.stderr
    common = assurance._common_dir(repo)
    if dependency == "checkpoint":
        checkpoint = repo / ".seam" / "orchestration" / "context" / "checkpoints" / f"{predecessor}.json"
        value = json.loads(checkpoint.read_text())
        value["next_step"] = "tampered"
        checkpoint.write_text(json.dumps(value), encoding="utf-8")
    elif dependency == "registration":
        assurance._registration_path(common, "successor-dependency").unlink()
    else:
        assurance._active_path(common, repo).unlink()
    with pytest.raises((assurance.AssuranceError, successor.SuccessorError)):
        assurance.check_session(repo, "successor-dependency")


def test_successor_rejects_symlinked_transition_directory(
    recovered_repo: tuple[Path, str, str, Path, dict[str, object]], tmp_path: Path
) -> None:
    repo, _, predecessor, state_root, request = recovered_repo
    common = assurance._common_dir(repo)
    external = tmp_path / "external-successors"
    external.mkdir()
    transition_root = common / "seam-orchestration" / "successors"
    transition_root.parent.mkdir(parents=True, exist_ok=True)
    transition_root.symlink_to(external, target_is_directory=True)
    rejected = _session_cli(
        repo, state_root, "successor-symlink",
        "successor",
        "--predecessor-session", predecessor,
        "--request-id", str(request["request_id"]),
        "--recovery-event", "automatic-compaction-1",
        "--objective", "Reject linked state.",
    )
    assert rejected.returncode == 1
    assert "directory" in rejected.stderr
    assert list(external.iterdir()) == []


def test_transition_tampering_fails_closed_on_retry(
    recovered_repo: tuple[Path, str, str, Path, dict[str, object]],
) -> None:
    repo, _, predecessor, state_root, request = recovered_repo
    arguments = (
        "successor",
        "--predecessor-session", predecessor,
        "--request-id", str(request["request_id"]),
        "--recovery-event", "automatic-compaction-1",
        "--objective", "Resume safely.",
    )
    first = _session_cli(repo, state_root, "tamper-successor", *arguments)
    assert first.returncode == 0, first.stderr
    common = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    transition_path = next((common / "seam-orchestration" / "successors").glob("*.json"))
    transition = json.loads(transition_path.read_text())
    transition["activation_sha"] = "0" * 40
    transition_path.write_text(json.dumps(transition), encoding="utf-8")
    retry = _session_cli(repo, state_root, "tamper-successor", *arguments)
    assert retry.returncode == 1
    assert "transition" in retry.stderr


def _receipt(
    request: dict[str, object], *, status: str, completed_at: str
) -> dict[str, object]:
    result = _blocked_receipt(request)
    result["status"] = status
    result["completed_at"] = completed_at
    if status == "QUALIFIED":
        result["continuity"] = {"status": "PASS", "evidence": ["continuity passed"]}
        result["next_action"] = "The administrative baseline is complete."
    else:
        result["continuity"] = {
            "status": "BLOCKED",
            "evidence": ["Administrative assurance boundary requires reconciliation."],
        }
        result["next_action"] = "Reconcile the repeated administrative duplicate."
    return result


def _administrative_duplicates(tmp_path: Path) -> tuple[Path, Path, dict[str, object], dict[str, object]]:
    repo = tmp_path / "admin-repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "SEAM tests")
    (repo / ".gitignore").write_text(".seam/\n", encoding="utf-8")
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", ".gitignore", "README.md")
    _git(repo, "commit", "-qm", "baseline")
    note = repo / "docs" / "administrative.md"
    note.parent.mkdir()
    note.write_text("unchanged administrative tail\n", encoding="utf-8")
    state_root = repo / ".seam" / "orchestration" / "session-end"
    prior_queued = session_end_closeout.handle_session_end(
        {"session_id": "administrative-prior", "cwd": str(repo)},
        repo_root=repo,
        state_root=state_root,
        dispatch=False,
    )
    prior_path = Path(str(prior_queued["request_path"]))
    prior = json.loads(prior_path.read_text())
    closeout_queue.store_receipt(
        prior,
        _receipt(prior, status="QUALIFIED", completed_at=str(prior["created_at"])),
        state_root=state_root,
    )
    tail_queued = session_end_closeout.handle_session_end(
        {"session_id": "administrative-tail", "cwd": str(repo)},
        repo_root=repo,
        state_root=state_root,
        dispatch=False,
    )
    tail_path = Path(str(tail_queued["request_path"]))
    tail = json.loads(tail_path.read_text())
    closeout_queue.store_receipt(
        tail,
        _receipt(
            tail,
            status="BLOCKED",
            completed_at=(
                datetime.fromisoformat(str(tail["created_at"]).replace("Z", "+00:00"))
                + timedelta(minutes=1)
            ).isoformat(),
        ),
        state_root=state_root,
    )
    return repo, state_root, prior, tail


def _queue_cli(repo: Path, state_root: Path, *arguments: str):
    env = os.environ.copy()
    env["CODEX_SESSION_ID"] = "administrative-reviewer"
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.agents.closeout_queue",
            "--repo-root", str(repo),
            "--state-root", str(state_root),
            *arguments,
        ],
        cwd=SOURCE_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _administrative_review(
    repo: Path,
    state_root: Path,
    prior: dict[str, object],
    tail: dict[str, object],
) -> Path:
    prior_request = state_root / "requests" / f"{prior['request_id']}.json"
    tail_request = state_root / "requests" / f"{tail['request_id']}.json"
    prior_receipt = state_root / "receipts" / f"{prior['request_id']}.json"
    tail_receipt = state_root / "receipts" / f"{tail['request_id']}.json"
    blocked = json.loads(tail_receipt.read_text(encoding="utf-8"))
    reviewed_at = (
        datetime.fromisoformat(str(blocked["completed_at"]).replace("Z", "+00:00"))
        + timedelta(minutes=1)
    ).isoformat()
    review = {
        "schema": "seam-closeout-administrative-review/v1",
        "repository_common_dir": _git(
            repo, "rev-parse", "--path-format=absolute", "--git-common-dir"
        ),
        "queue_root": str(state_root),
        "current_request_id": tail["request_id"],
        "current_request_sha256": hashlib.sha256(tail_request.read_bytes()).hexdigest(),
        "current_receipt_sha256": hashlib.sha256(tail_receipt.read_bytes()).hexdigest(),
        "prior_request_id": prior["request_id"],
        "prior_request_sha256": hashlib.sha256(prior_request.read_bytes()).hexdigest(),
        "prior_receipt_sha256": hashlib.sha256(prior_receipt.read_bytes()).hexdigest(),
        "producer_session_id": "independent-administrative-reviewer",
        "reviewer": "independent-administrative-reviewer",
        "reviewed_at": reviewed_at,
        "status": "PASS",
        "reason": "UNCHANGED_NONRUNTIME_TAIL_ASSURANCE_BOUNDARY",
        "authority": "admission_only",
        "unresolved_findings": [],
    }
    path = state_root / "independent-administrative-review.json"
    path.write_text(json.dumps(review), encoding="utf-8")
    return path


def test_actual_ignore_excludes_only_administrative_dispositions_from_git_scope(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "ignore-repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "SEAM tests")
    _git(repo, "config", "core.excludesFile", "/dev/null")
    (repo / ".gitignore").write_bytes((SOURCE_ROOT / ".gitignore").read_bytes())
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", ".gitignore", "README.md")
    _git(repo, "commit", "-qm", "baseline")

    ordinary_source = repo / "tools" / "agents" / "ordinary.py"
    ordinary_source.parent.mkdir(parents=True)
    ordinary_source.write_text("VISIBLE = True\n", encoding="utf-8")
    sibling_state = (
        repo
        / ".seam"
        / "orchestration"
        / "session-end"
        / "other-state"
        / "visible.json"
    )
    sibling_state.parent.mkdir(parents=True)
    sibling_state.write_text("{}\n", encoding="utf-8")
    before = _git(repo, "status", "--short", "--untracked-files=all")

    disposition = (
        repo
        / ".seam"
        / "orchestration"
        / "session-end"
        / "administrative-dispositions"
        / "disposition.json"
    )
    disposition.parent.mkdir(parents=True)
    disposition.write_text("{}\n", encoding="utf-8")
    after = _git(repo, "status", "--short", "--untracked-files=all")

    assert before == after
    assert "?? tools/agents/ordinary.py" in before.splitlines()
    assert (
        "?? .seam/orchestration/session-end/other-state/visible.json"
        in before.splitlines()
    )
    ignored = subprocess.run(
        [
            "git",
            "check-ignore",
            "--no-index",
            "-v",
            str(disposition.relative_to(repo)),
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ignored.returncode == 0, ignored.stderr
    matched_rule, matched_path = ignored.stdout.rstrip("\n").split("\t", maxsplit=1)
    assert matched_rule.rsplit(":", maxsplit=1)[-1] == (
        ".seam/orchestration/session-end/administrative-dispositions/"
    )
    assert matched_path == str(disposition.relative_to(repo))


def test_administrative_duplicate_cli_records_admission_only_disposition(
    tmp_path: Path,
) -> None:
    repo, state_root, prior, tail = _administrative_duplicates(tmp_path)
    review = _administrative_review(repo, state_root, prior, tail)
    disposition = state_root / "administrative-dispositions" / f"{tail['request_id']}.json"
    reconciled = _queue_cli(
        repo,
        state_root,
        "reconcile-duplicate",
        "--request", str(state_root / "requests" / f"{tail['request_id']}.json"),
        "--prior-request", str(state_root / "requests" / f"{prior['request_id']}.json"),
        "--prior-receipt", str(state_root / "receipts" / f"{prior['request_id']}.json"),
        "--review", str(review),
        "--disposition", str(disposition),
    )
    assert reconciled.returncode == 0, reconciled.stderr
    record = json.loads(disposition.read_text())
    assert record["schema"] == "seam-closeout-administrative-disposition/v1"
    assert record["status"] == "RECONCILED_DUPLICATE"
    assert record["authority"] == "admission_only"
    assert record["review_path"] == str(review)
    assert record["review_bytes_sha256"] == hashlib.sha256(review.read_bytes()).hexdigest()
    assert "qualification" not in record
    visible = json.loads(_queue_cli(repo, state_root, "pending").stdout)
    assert [item["request_id"] for item in visible["requests"]] == [tail["request_id"]]
    assert visible["administrative_dispositions"][0]["receipt_status"] == "BLOCKED"
    admitted = _queue_cli(repo, state_root, "admit")
    assert admitted.returncode == 0, admitted.stderr
    admitted_record = json.loads(admitted.stdout)
    assert admitted_record["pending_request_ids"] == []
    assert any("administrative-disposition" in item for item in admitted_record["record_sha256s"])


def test_administrative_reconciliation_rejects_nonidentical_tail(
    tmp_path: Path,
) -> None:
    repo, state_root, prior, tail = _administrative_duplicates(tmp_path)
    tail_path = state_root / "requests" / f"{tail['request_id']}.json"
    changed = json.loads(tail_path.read_text())
    changed["context"]["objective"] = "different administrative work"
    changed["request_sha256"] = closeout_queue._request_hash(changed)
    tail_path.write_text(json.dumps(changed), encoding="utf-8")
    blocked_path = state_root / "receipts" / f"{tail['request_id']}.json"
    blocked = json.loads(blocked_path.read_text())
    blocked["request_sha256"] = changed["request_sha256"]
    blocked_path.write_text(json.dumps(blocked), encoding="utf-8")
    disposition = state_root / "administrative-dispositions" / f"{tail['request_id']}.json"
    review = _administrative_review(repo, state_root, prior, changed)
    rejected = _queue_cli(
        repo,
        state_root,
        "reconcile-duplicate",
        "--request", str(tail_path),
        "--prior-request", str(state_root / "requests" / f"{prior['request_id']}.json"),
        "--prior-receipt", str(state_root / "receipts" / f"{prior['request_id']}.json"),
        "--review", str(review),
        "--disposition", str(disposition),
    )
    assert rejected.returncode == 2
    assert "exact duplicates" in rejected.stderr
    assert not disposition.exists()


def test_administrative_rejection_never_publishes_a_disposition(
    tmp_path: Path,
) -> None:
    repo, state_root, prior, tail = _administrative_duplicates(tmp_path)
    assurance.register(repo, str(tail["session_id"]), _git(repo, "rev-parse", "HEAD"))
    review = _administrative_review(repo, state_root, prior, tail)
    disposition = state_root / "administrative-dispositions" / f"{tail['request_id']}.json"

    rejected = _queue_cli(
        repo,
        state_root,
        "reconcile-duplicate",
        "--request", str(state_root / "requests" / f"{tail['request_id']}.json"),
        "--prior-request", str(state_root / "requests" / f"{prior['request_id']}.json"),
        "--prior-receipt", str(state_root / "receipts" / f"{prior['request_id']}.json"),
        "--review", str(review),
        "--disposition", str(disposition),
    )

    assert rejected.returncode == 2
    assert "root-local registered candidate" in rejected.stderr
    assert not disposition.exists()


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.pop("authority"), "review"),
        (lambda value: value.update({"extra": True}), "review"),
        (lambda value: value.update({"authority": "qualification"}), "authority"),
        (lambda value: value.update({"status": "BLOCKED"}), "status"),
        (lambda value: value.update({"reason": "UNCHANGED"}), "reason"),
        (lambda value: value.update({"queue_root": "/wrong"}), "queue root"),
        (lambda value: value.update({"repository_common_dir": "/wrong"}), "repository"),
        (lambda value: value.update({"current_request_sha256": "0" * 64}), "current_request_sha256"),
        (lambda value: value.update({"unresolved_findings": ["open"]}), "findings"),
        (lambda value: value.update({"reviewer": "administrative-tail"}), "independent"),
        (lambda value: value.pop("producer_session_id"), "strict contract"),
        (lambda value: value.update({"producer_session_id": "different-producer"}), "provenance"),
    ],
)
def test_administrative_review_is_strict_and_independent(
    tmp_path: Path, mutation, message: str
) -> None:
    repo, state_root, prior, tail = _administrative_duplicates(tmp_path)
    review = _administrative_review(repo, state_root, prior, tail)
    value = json.loads(review.read_text(encoding="utf-8"))
    mutation(value)
    review.write_text(json.dumps(value), encoding="utf-8")
    disposition = state_root / "administrative-dispositions" / f"{tail['request_id']}.json"
    rejected = _queue_cli(
        repo,
        state_root,
        "reconcile-duplicate",
        "--request", str(state_root / "requests" / f"{tail['request_id']}.json"),
        "--prior-request", str(state_root / "requests" / f"{prior['request_id']}.json"),
        "--prior-receipt", str(state_root / "receipts" / f"{prior['request_id']}.json"),
        "--review", str(review),
        "--disposition", str(disposition),
    )
    assert rejected.returncode == 2
    assert message in rejected.stderr
    assert not disposition.exists()


def test_administrative_review_uses_typed_decision_for_real_shaped_blocker(
    tmp_path: Path,
) -> None:
    repo, state_root, prior, tail = _administrative_duplicates(tmp_path)
    blocked_path = state_root / "receipts" / f"{tail['request_id']}.json"
    blocked = json.loads(blocked_path.read_text(encoding="utf-8"))
    blocked["continuity"]["evidence"] = [
        "Independent assurance is required before continuity can be finalized."
    ]
    blocked["next_action"] = "Obtain independent admission review for this duplicate."
    blocked_path.write_text(json.dumps(blocked), encoding="utf-8")
    review = _administrative_review(repo, state_root, prior, tail)
    disposition = state_root / "administrative-dispositions" / f"{tail['request_id']}.json"

    reconciled = _queue_cli(
        repo,
        state_root,
        "reconcile-duplicate",
        "--request", str(state_root / "requests" / f"{tail['request_id']}.json"),
        "--prior-request", str(state_root / "requests" / f"{prior['request_id']}.json"),
        "--prior-receipt", str(state_root / "receipts" / f"{prior['request_id']}.json"),
        "--review", str(review),
        "--disposition", str(disposition),
    )

    assert reconciled.returncode == 0, reconciled.stderr
    assert disposition.is_file()


def test_administrative_review_cannot_mask_incomplete_receipt(
    tmp_path: Path,
) -> None:
    repo, state_root, prior, tail = _administrative_duplicates(tmp_path)
    blocked_path = state_root / "receipts" / f"{tail['request_id']}.json"
    blocked = json.loads(blocked_path.read_text(encoding="utf-8"))
    blocked["checks"].pop()
    blocked_path.write_text(json.dumps(blocked), encoding="utf-8")
    review = _administrative_review(repo, state_root, prior, tail)
    disposition = state_root / "administrative-dispositions" / f"{tail['request_id']}.json"
    rejected = _queue_cli(
        repo,
        state_root,
        "reconcile-duplicate",
        "--request", str(state_root / "requests" / f"{tail['request_id']}.json"),
        "--prior-request", str(state_root / "requests" / f"{prior['request_id']}.json"),
        "--prior-receipt", str(state_root / "receipts" / f"{prior['request_id']}.json"),
        "--review", str(review),
        "--disposition", str(disposition),
    )
    assert rejected.returncode == 2
    assert not disposition.exists()


def test_administrative_review_rejects_symlinked_ancestor_and_retry_is_exact(
    tmp_path: Path,
) -> None:
    repo, state_root, prior, tail = _administrative_duplicates(tmp_path)
    review = _administrative_review(repo, state_root, prior, tail)
    real = tmp_path / "real-review"
    real.mkdir()
    real_review = real / "review.json"
    real_review.write_bytes(review.read_bytes())
    linked = tmp_path / "linked-review"
    linked.symlink_to(real, target_is_directory=True)
    disposition = state_root / "administrative-dispositions" / f"{tail['request_id']}.json"
    rejected = _queue_cli(
        repo,
        state_root,
        "reconcile-duplicate",
        "--request", str(state_root / "requests" / f"{tail['request_id']}.json"),
        "--prior-request", str(state_root / "requests" / f"{prior['request_id']}.json"),
        "--prior-receipt", str(state_root / "receipts" / f"{prior['request_id']}.json"),
        "--review", str(linked / "review.json"),
        "--disposition", str(disposition),
    )
    assert rejected.returncode == 2
    assert "unsafe" in rejected.stderr
    first = _queue_cli(
        repo,
        state_root,
        "reconcile-duplicate",
        "--request", str(state_root / "requests" / f"{tail['request_id']}.json"),
        "--prior-request", str(state_root / "requests" / f"{prior['request_id']}.json"),
        "--prior-receipt", str(state_root / "receipts" / f"{prior['request_id']}.json"),
        "--review", str(review),
        "--disposition", str(disposition),
    )
    assert first.returncode == 0, first.stderr
    original = disposition.read_bytes()
    repeated = _queue_cli(
        repo,
        state_root,
        "reconcile-duplicate",
        "--request", str(state_root / "requests" / f"{tail['request_id']}.json"),
        "--prior-request", str(state_root / "requests" / f"{prior['request_id']}.json"),
        "--prior-receipt", str(state_root / "receipts" / f"{prior['request_id']}.json"),
        "--review", str(review),
        "--disposition", str(disposition),
    )
    assert repeated.returncode == 0, repeated.stderr
    assert disposition.read_bytes() == original


def test_stored_administrative_review_is_caller_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, state_root, prior, tail = _administrative_duplicates(tmp_path)
    review = _administrative_review(repo, state_root, prior, tail)
    disposition = state_root / "administrative-dispositions" / f"{tail['request_id']}.json"
    reconciled = _queue_cli(
        repo,
        state_root,
        "reconcile-duplicate",
        "--request", str(state_root / "requests" / f"{tail['request_id']}.json"),
        "--prior-request", str(state_root / "requests" / f"{prior['request_id']}.json"),
        "--prior-receipt", str(state_root / "receipts" / f"{prior['request_id']}.json"),
        "--review", str(review),
        "--disposition", str(disposition),
    )
    assert reconciled.returncode == 0, reconciled.stderr
    monkeypatch.setenv("CODEX_SESSION_ID", "independent-administrative-reviewer")

    loaded = closeout_queue._load_administrative_disposition(
        state_root, str(tail["request_id"])
    )

    assert loaded is not None
    assert loaded[1]["status"] == "RECONCILED_DUPLICATE"


def test_one_administrative_review_cannot_clear_a_second_tail(tmp_path: Path) -> None:
    repo, state_root, prior, tail = _administrative_duplicates(tmp_path)
    second_queued = session_end_closeout.handle_session_end(
        {"session_id": "administrative-second-tail", "cwd": str(repo)},
        repo_root=repo,
        state_root=state_root,
        dispatch=False,
    )
    second = json.loads(Path(str(second_queued["request_path"])).read_text())
    closeout_queue.store_receipt(
        second,
        _receipt(
            second,
            status="BLOCKED",
            completed_at=(
                datetime.fromisoformat(str(second["created_at"]).replace("Z", "+00:00"))
                + timedelta(minutes=1)
            ).isoformat(),
        ),
        state_root=state_root,
    )
    review = _administrative_review(repo, state_root, prior, tail)
    disposition = state_root / "administrative-dispositions" / f"{tail['request_id']}.json"
    reconciled = _queue_cli(
        repo,
        state_root,
        "reconcile-duplicate",
        "--request", str(state_root / "requests" / f"{tail['request_id']}.json"),
        "--prior-request", str(state_root / "requests" / f"{prior['request_id']}.json"),
        "--prior-receipt", str(state_root / "receipts" / f"{prior['request_id']}.json"),
        "--review", str(review),
        "--disposition", str(disposition),
    )
    assert reconciled.returncode == 0, reconciled.stderr
    rejected = _queue_cli(repo, state_root, "admit")
    assert rejected.returncode == 2
    assert str(second["request_id"]) in rejected.stderr


def test_administrative_review_must_follow_the_canonical_blocked_receipt(
    tmp_path: Path,
) -> None:
    repo, state_root, prior, tail = _administrative_duplicates(tmp_path)
    review = _administrative_review(repo, state_root, prior, tail)
    value = json.loads(review.read_text(encoding="utf-8"))
    blocked = json.loads(
        (state_root / "receipts" / f"{tail['request_id']}.json").read_text()
    )
    value["reviewed_at"] = blocked["completed_at"]
    review.write_text(json.dumps(value), encoding="utf-8")
    disposition = state_root / "administrative-dispositions" / f"{tail['request_id']}.json"
    rejected = _queue_cli(
        repo,
        state_root,
        "reconcile-duplicate",
        "--request", str(state_root / "requests" / f"{tail['request_id']}.json"),
        "--prior-request", str(state_root / "requests" / f"{prior['request_id']}.json"),
        "--prior-receipt", str(state_root / "receipts" / f"{prior['request_id']}.json"),
        "--review", str(review),
        "--disposition", str(disposition),
    )
    assert rejected.returncode == 2
    assert "predates" in rejected.stderr


def test_administrative_tail_allows_same_session_registration_in_other_root(
    tmp_path: Path,
) -> None:
    repo, state_root, prior, tail = _administrative_duplicates(tmp_path)
    other = tmp_path / "other-worktree"
    _git(repo, "worktree", "add", "--detach", str(other), "HEAD")
    assurance.register(
        other,
        str(tail["session_id"]),
        _git(other, "rev-parse", "HEAD"),
    )
    review = _administrative_review(repo, state_root, prior, tail)
    disposition = state_root / "administrative-dispositions" / f"{tail['request_id']}.json"
    reconciled = _queue_cli(
        repo,
        state_root,
        "reconcile-duplicate",
        "--request", str(state_root / "requests" / f"{tail['request_id']}.json"),
        "--prior-request", str(state_root / "requests" / f"{prior['request_id']}.json"),
        "--prior-receipt", str(state_root / "receipts" / f"{prior['request_id']}.json"),
        "--review", str(review),
        "--disposition", str(disposition),
    )
    assert reconciled.returncode == 0, reconciled.stderr


def _external_recovery_binding(
    tmp_path: Path,
    *,
    missing_checkpoint: bool = True,
    result_status: str = "RETAINED",
    result_name: str = "unexpected-compaction-result.json",
) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    external_root = tmp_path / "external-bootstrap"
    external_root.mkdir()
    session_id = "external-bootstrap-session"
    event_id = "automatic-compaction-1"
    context_root = external_root / "context"
    handoff_root = external_root / "context-handoffs"
    context_guardian.observe(
        session_id=session_id,
        used_tokens=10 if missing_checkpoint else 50,
        context_limit=100,
        at_coherent_milestone=False,
        summary=["The external recovery fixture preserves exact context state."],
        next_step="Create one bound successor.",
        state_root=context_root,
        handoff_root=handoff_root,
    )
    result = context_guardian.recover_unexpected_compaction(
        session_id=session_id,
        event_id=event_id,
        summary=["The external client stopped during recovery."],
        next_step="Resume through the bound successor.",
        state_root=context_root,
        handoff_root=handoff_root,
    )
    assert result["missing_checkpoint"] is missing_checkpoint
    result_path = external_root / result_name
    if result_status == "RETAINED":
        result_path.write_text(json.dumps(result), encoding="utf-8")
    guardian_path = context_root / f"{session_id}.json"
    handoff_path = Path(str(result["handoff_path"]))
    recovery_path = Path(str(result["recovery_path"]))
    evidence_path = external_root / "review-evidence.txt"
    evidence_path.write_text("independent external recovery evidence\n", encoding="utf-8")
    members = [guardian_path, handoff_path, recovery_path, evidence_path]
    if result_status == "RETAINED":
        members.append(result_path)
    checkpoint_path = context_root / "checkpoints" / f"{session_id}.json"
    if not missing_checkpoint:
        members.append(checkpoint_path)
    manifest_path = external_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                str(path.relative_to(external_root)): {
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "size_bytes": len(path.read_bytes()),
                }
                for path in members
            }
        ),
        encoding="utf-8",
    )
    artifacts = {
        "guardian_state": {
            "path": str(guardian_path),
            "sha256": hashlib.sha256(guardian_path.read_bytes()).hexdigest(),
        },
        "handoff": {
            "path": str(handoff_path),
            "sha256": hashlib.sha256(handoff_path.read_bytes()).hexdigest(),
        },
        "recovery_event": {
            "path": str(recovery_path),
            "sha256": hashlib.sha256(recovery_path.read_bytes()).hexdigest(),
        },
        "evidence_manifest": {
            "path": str(manifest_path),
            "sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        },
    }
    if not missing_checkpoint:
        artifacts["checkpoint"] = {
            "path": str(checkpoint_path),
            "sha256": hashlib.sha256(checkpoint_path.read_bytes()).hexdigest(),
        }
    if result_status == "RETAINED":
        artifacts["result"] = {
            "path": str(result_path),
            "sha256": hashlib.sha256(result_path.read_bytes()).hexdigest(),
        }
    binding = {
        "schema": "seam-external-recovery-binding/v1",
        "external_root": str(external_root),
        "session_id": session_id,
        "event_id": event_id,
        "status": "INHERITED_UNQUALIFIED",
        "result_status": result_status,
        "missing_checkpoint": missing_checkpoint,
        "compaction_count": 1,
        **artifacts,
    }
    path = tmp_path / "external-recovery-binding.json"
    path.write_text(json.dumps(binding), encoding="utf-8")
    return path


def _refresh_external_binding(binding_path: Path, *changed_paths: Path) -> None:
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    external_root = Path(binding["external_root"])
    manifest_path = Path(binding["evidence_manifest"]["path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for changed_path in changed_paths:
        member = {
            "sha256": hashlib.sha256(changed_path.read_bytes()).hexdigest(),
            "size_bytes": len(changed_path.read_bytes()),
        }
        manifest[str(changed_path.relative_to(external_root))] = member
        for field in ("guardian_state", "handoff", "recovery_event", "result", "checkpoint"):
            artifact = binding.get(field)
            if isinstance(artifact, dict) and artifact.get("path") == str(changed_path):
                artifact["sha256"] = member["sha256"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    binding["evidence_manifest"]["sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    binding_path.write_text(json.dumps(binding), encoding="utf-8")


def test_external_recovery_rejects_recomputed_wrong_handoff_bytes(
    tmp_path: Path,
) -> None:
    external = _external_recovery_binding(tmp_path)
    binding = json.loads(external.read_text(encoding="utf-8"))
    handoff_path = Path(binding["handoff"]["path"])
    handoff_path.write_text(
        handoff_path.read_text(encoding="utf-8") + "\nforged but rehashed\n",
        encoding="utf-8",
    )
    _refresh_external_binding(external, handoff_path)

    with pytest.raises(successor.SuccessorError, match="handoff"):
        successor._load_external_recovery(external)


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("action", "CONTINUE"),
        ("compactions_completed", 2),
        ("handoff_path", "/tmp/wrong-handoff.md"),
        ("recovery_path", "/tmp/wrong-recovery.json"),
        ("missing_checkpoint", False),
        ("previous_last_action", "CHECKPOINT_NOW"),
        ("previous_highest_usage_percent", 99.0),
    ],
)
def test_external_recovery_rejects_each_recomputed_result_mismatch(
    tmp_path: Path, field: str, replacement: object
) -> None:
    external = _external_recovery_binding(tmp_path)
    binding = json.loads(external.read_text(encoding="utf-8"))
    result_path = Path(binding["result"]["path"])
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result[field] = replacement
    result_path.write_text(json.dumps(result), encoding="utf-8")
    _refresh_external_binding(external, result_path)

    with pytest.raises(successor.SuccessorError, match="external recovery"):
        successor._load_external_recovery(external)


def test_external_recovery_result_presence_is_explicit_and_conditional(
    tmp_path: Path,
) -> None:
    retained = _external_recovery_binding(tmp_path / "retained")
    assert successor._load_external_recovery(retained)["result_status"] == "RETAINED"
    retained_value = json.loads(retained.read_text(encoding="utf-8"))
    retained_value["result_status"] = "NOT_RETAINED"
    retained.write_text(json.dumps(retained_value), encoding="utf-8")
    with pytest.raises(successor.SuccessorError, match="result"):
        successor._load_external_recovery(retained)

    absent = _external_recovery_binding(
        tmp_path / "absent", result_status="NOT_RETAINED"
    )
    assert successor._load_external_recovery(absent)["result_status"] == "NOT_RETAINED"
    absent_value = json.loads(absent.read_text(encoding="utf-8"))
    absent_value["result_status"] = "RETAINED"
    absent.write_text(json.dumps(absent_value), encoding="utf-8")
    with pytest.raises(successor.SuccessorError, match="result"):
        successor._load_external_recovery(absent)


def test_external_recovery_detects_omitted_malformed_and_multiple_result_candidates(
    tmp_path: Path,
) -> None:
    omitted = _external_recovery_binding(
        tmp_path / "omitted", result_status="NOT_RETAINED"
    )
    omitted_value = json.loads(omitted.read_text(encoding="utf-8"))
    omitted_result = Path(omitted_value["external_root"]) / "unexpected-compaction-result.json"
    omitted_result.write_text("{malformed", encoding="utf-8")
    _refresh_external_binding(omitted, omitted_result)
    with pytest.raises(successor.SuccessorError, match="result"):
        successor._load_external_recovery(omitted)

    multiple = _external_recovery_binding(tmp_path / "multiple")
    multiple_value = json.loads(multiple.read_text(encoding="utf-8"))
    result_path = Path(multiple_value["result"]["path"])
    duplicate = Path(multiple_value["external_root"]) / "renamed-result.json"
    duplicate.write_bytes(result_path.read_bytes())
    _refresh_external_binding(multiple, duplicate)
    with pytest.raises(successor.SuccessorError, match="ambiguous"):
        successor._load_external_recovery(multiple)


def test_external_recovery_accepts_renamed_bound_result(tmp_path: Path) -> None:
    external = _external_recovery_binding(
        tmp_path, result_name="retained-output-with-arbitrary-name.json"
    )

    assert successor._load_external_recovery(external)["result_status"] == "RETAINED"


def test_external_recovery_stream_verifies_large_non_json_manifest_member(
    tmp_path: Path,
) -> None:
    external = _external_recovery_binding(tmp_path)
    binding = json.loads(external.read_text(encoding="utf-8"))
    large_evidence = Path(binding["external_root"]) / "HISTORY.md"
    large_evidence.write_bytes(b"# frozen evidence\n" + b"x" * (successor.MAX_BYTES + 1))
    _refresh_external_binding(external, large_evidence)

    assert successor._load_external_recovery(external)["status"] == "INHERITED_UNQUALIFIED"


@pytest.mark.parametrize("oversized", [False, True], ids=["small", "oversized"])
def test_external_recovery_rejects_bom_encoded_arbitrary_result_candidate(
    tmp_path: Path, oversized: bool
) -> None:
    external = _external_recovery_binding(
        tmp_path,
        result_name="arbitrary-retained-output.bin",
    )
    binding = json.loads(external.read_text(encoding="utf-8"))
    result_path = Path(binding["result"]["path"])
    padding = b" " * successor.MAX_BYTES if oversized else b""
    result_path.write_bytes(b"\xef\xbb\xbf" + result_path.read_bytes() + padding)
    _refresh_external_binding(external, result_path)
    binding = json.loads(external.read_text(encoding="utf-8"))
    binding["result_status"] = "NOT_RETAINED"
    del binding["result"]
    external.write_text(json.dumps(binding), encoding="utf-8")

    with pytest.raises(successor.SuccessorError):
        successor._load_external_recovery(external)


@pytest.mark.parametrize(
    "encoding", ["utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"]
)
@pytest.mark.parametrize("oversized", [False, True], ids=["small", "oversized"])
@pytest.mark.parametrize(
    "leading_whitespace", [False, True], ids=["direct", "leading-whitespace"]
)
def test_external_recovery_rejects_no_bom_unicode_result_candidate(
    tmp_path: Path,
    encoding: str,
    oversized: bool,
    leading_whitespace: bool,
) -> None:
    external = _external_recovery_binding(
        tmp_path,
        result_name="arbitrary-unicode-output.bin",
    )
    binding = json.loads(external.read_text(encoding="utf-8"))
    result_path = Path(binding["result"]["path"])
    result_text = result_path.read_text(encoding="utf-8")
    prefix = " \t\r\n" if leading_whitespace else ""
    padding = ""
    if oversized:
        encoded_space_size = len(" ".encode(encoding))
        padding = " " * (successor.MAX_BYTES // encoded_space_size + 1)
    result_path.write_bytes((prefix + result_text + padding).encode(encoding))
    _refresh_external_binding(external, result_path)
    binding = json.loads(external.read_text(encoding="utf-8"))
    binding["result_status"] = "NOT_RETAINED"
    del binding["result"]
    external.write_text(json.dumps(binding), encoding="utf-8")

    with pytest.raises(successor.SuccessorError):
        successor._load_external_recovery(external)


def test_external_recovery_rejects_nul_prefix_after_cross_chunk_whitespace(
    tmp_path: Path,
) -> None:
    external = _external_recovery_binding(
        tmp_path,
        result_name="arbitrary-cross-chunk-output.bin",
    )
    binding = json.loads(external.read_text(encoding="utf-8"))
    result_path = Path(binding["result"]["path"])
    result_text = result_path.read_text(encoding="utf-8")
    result_path.write_bytes(b" " * 65537 + result_text.encode("utf-16-be"))
    _refresh_external_binding(external, result_path)
    binding = json.loads(external.read_text(encoding="utf-8"))
    binding["result_status"] = "NOT_RETAINED"
    del binding["result"]
    external.write_text(json.dumps(binding), encoding="utf-8")

    with pytest.raises(successor.SuccessorError, match="unsupported JSON encoding"):
        successor._load_external_recovery(external)


@pytest.mark.parametrize("short_read_size", [1, 2, 3])
def test_external_recovery_rejects_nul_prefix_split_across_short_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    short_read_size: int,
) -> None:
    external = _external_recovery_binding(
        tmp_path,
        result_name="arbitrary-short-read-output.bin",
    )
    binding = json.loads(external.read_text(encoding="utf-8"))
    result_path = Path(binding["result"]["path"])
    result_text = result_path.read_text(encoding="utf-8")
    result_path.write_bytes(result_text.encode("utf-32-be"))
    _refresh_external_binding(external, result_path)
    binding = json.loads(external.read_text(encoding="utf-8"))
    binding["result_status"] = "NOT_RETAINED"
    del binding["result"]
    external.write_text(json.dumps(binding), encoding="utf-8")

    target = result_path.stat()
    original_read = os.read

    def _short_result_read(descriptor: int, size: int) -> bytes:
        observed = os.fstat(descriptor)
        if (observed.st_dev, observed.st_ino) == (target.st_dev, target.st_ino):
            size = min(size, short_read_size)
        return original_read(descriptor, size)

    monkeypatch.setattr(successor.os, "read", _short_result_read)
    with pytest.raises(successor.SuccessorError, match="unsupported JSON encoding"):
        successor._load_external_recovery(external)


@pytest.mark.parametrize(
    "candidate_size",
    [successor.MAX_BYTES - 1, successor.MAX_BYTES, successor.MAX_BYTES + 1],
    ids=["below-retention-limit", "at-retention-limit", "above-retention-limit"],
)
def test_external_recovery_rejects_nul_prefix_at_retention_boundary(
    tmp_path: Path,
    candidate_size: int,
) -> None:
    external = _external_recovery_binding(
        tmp_path,
        result_name="arbitrary-retention-boundary-output.bin",
    )
    binding = json.loads(external.read_text(encoding="utf-8"))
    result_path = Path(binding["result"]["path"])
    encoded = result_path.read_text(encoding="utf-8").encode("utf-16-be")
    assert len(encoded) < candidate_size
    result_path.write_bytes(encoded + b" " * (candidate_size - len(encoded)))
    _refresh_external_binding(external, result_path)
    binding = json.loads(external.read_text(encoding="utf-8"))
    binding["result_status"] = "NOT_RETAINED"
    del binding["result"]
    external.write_text(json.dumps(binding), encoding="utf-8")

    with pytest.raises(successor.SuccessorError, match="unsupported JSON encoding"):
        successor._load_external_recovery(external)


def test_external_recovery_requires_event_and_all_bound_manifest_members(
    tmp_path: Path,
) -> None:
    external = _external_recovery_binding(tmp_path)
    binding = json.loads(external.read_text(encoding="utf-8"))
    manifest_path = Path(binding["evidence_manifest"]["path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    event_path = Path(binding["recovery_event"]["path"])
    del manifest[str(event_path.relative_to(Path(binding["external_root"])))]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    binding["evidence_manifest"]["sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    external.write_text(json.dumps(binding), encoding="utf-8")

    with pytest.raises(successor.SuccessorError, match="manifest"):
        successor._load_external_recovery(external)


@pytest.mark.parametrize(
    ("target", "field"),
    [("binding", "compaction_count"), ("result", "previous_highest_usage_percent")],
)
def test_external_recovery_rejects_bool_numeric_values(
    tmp_path: Path, target: str, field: str
) -> None:
    external = _external_recovery_binding(tmp_path)
    binding = json.loads(external.read_text(encoding="utf-8"))
    if target == "binding":
        binding[field] = True
        external.write_text(json.dumps(binding), encoding="utf-8")
    else:
        result_path = Path(binding["result"]["path"])
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result[field] = False
        result_path.write_text(json.dumps(result), encoding="utf-8")
        _refresh_external_binding(external, result_path)

    with pytest.raises(successor.SuccessorError, match="external recovery"):
        successor._load_external_recovery(external)


def test_external_recovery_rejects_hash_valid_semantic_fakes(
    recovered_repo: tuple[Path, str, str, Path, dict[str, object]], tmp_path: Path
) -> None:
    repo, _, predecessor, state_root, request = recovered_repo
    external = _external_recovery_binding(tmp_path)
    binding = json.loads(external.read_text(encoding="utf-8"))
    guardian_path = Path(binding["guardian_state"]["path"])
    guardian = json.loads(guardian_path.read_text(encoding="utf-8"))
    guardian["session_id"] = "forged-session"
    guardian_path.write_text(json.dumps(guardian), encoding="utf-8")
    guardian_sha = hashlib.sha256(guardian_path.read_bytes()).hexdigest()
    binding["guardian_state"]["sha256"] = guardian_sha
    manifest_path = Path(binding["evidence_manifest"]["path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[str(guardian_path.relative_to(Path(binding["external_root"])))] = {
        "sha256": guardian_sha,
        "size_bytes": len(guardian_path.read_bytes()),
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    binding["evidence_manifest"]["sha256"] = hashlib.sha256(
        manifest_path.read_bytes()
    ).hexdigest()
    external.write_text(json.dumps(binding), encoding="utf-8")

    rejected = _session_cli(
        repo,
        state_root,
        "successor-fake-external",
        "successor",
        "--predecessor-session", predecessor,
        "--request-id", str(request["request_id"]),
        "--recovery-event", "automatic-compaction-1",
        "--external-recovery", str(external),
        "--objective", "Reject hash-valid files without recovery semantics.",
    )

    assert rejected.returncode == 1
    assert "external recovery" in rejected.stderr


def test_successor_binds_external_unqualified_recovery_and_allows_descendant_head(
    recovered_repo: tuple[Path, str, str, Path, dict[str, object]], tmp_path: Path
) -> None:
    repo, _, predecessor, state_root, request = recovered_repo
    external = _external_recovery_binding(tmp_path)
    created = _session_cli(
        repo,
        state_root,
        "successor-external",
        "successor",
        "--predecessor-session", predecessor,
        "--request-id", str(request["request_id"]),
        "--recovery-event", "automatic-compaction-1",
        "--external-recovery", str(external),
        "--objective", "Bind the unfinished external bootstrap.",
    )
    assert created.returncode == 0, created.stderr
    transition_root = (
        Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        / "seam-orchestration"
        / "successors"
    )
    transition = json.loads(next(transition_root.glob("*.json")).read_text())
    assert transition["external_recoveries"][0]["status"] == "INHERITED_UNQUALIFIED"
    assert transition["external_recoveries"][0]["missing_checkpoint"] is True
    (repo / "README.md").write_text("descendant\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "descendant")
    registration = json.loads(
        assurance._registration_path(
            assurance._common_dir(repo), "successor-external"
        ).read_text()
    )
    assert successor.validate_registration_binding(repo, registration)["activation_sha"] != _git(
        repo, "rev-parse", "HEAD"
    )


def test_successor_schema_accepts_truthful_checkpoint_present_recovery(
    recovered_repo: tuple[Path, str, str, Path, dict[str, object]], tmp_path: Path
) -> None:
    repo, _, predecessor, state_root, request = recovered_repo
    external = _external_recovery_binding(tmp_path, missing_checkpoint=False)
    created = _session_cli(
        repo,
        state_root,
        "successor-checkpoint-present",
        "successor",
        "--predecessor-session", predecessor,
        "--request-id", str(request["request_id"]),
        "--recovery-event", "automatic-compaction-1",
        "--external-recovery", str(external),
        "--objective", "Bind the truthful checkpoint-present recovery.",
    )
    assert created.returncode == 0, created.stderr
    transition_root = (
        Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        / "seam-orchestration"
        / "successors"
    )
    transition = json.loads(next(transition_root.glob("*.json")).read_text())
    recovery = transition["external_recoveries"][0]
    assert recovery["missing_checkpoint"] is False
    assert "checkpoint" in recovery
    schema = json.loads(
        (SOURCE_ROOT / "tools/agents/schemas/successor-transition.schema.json").read_text()
    )

    Draft202012Validator(schema).validate(transition)


def test_successor_schema_and_python_accept_honest_not_retained_result(
    recovered_repo: tuple[Path, str, str, Path, dict[str, object]], tmp_path: Path
) -> None:
    repo, _, predecessor, state_root, request = recovered_repo
    external = _external_recovery_binding(
        tmp_path, result_status="NOT_RETAINED"
    )
    created = _session_cli(
        repo,
        state_root,
        "successor-no-retained-result",
        "successor",
        "--predecessor-session", predecessor,
        "--request-id", str(request["request_id"]),
        "--recovery-event", "automatic-compaction-1",
        "--external-recovery", str(external),
        "--objective", "Bind the honestly absent external recovery result.",
    )
    assert created.returncode == 0, created.stderr
    transition_root = (
        Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        / "seam-orchestration"
        / "successors"
    )
    transition = json.loads(next(transition_root.glob("*.json")).read_text())
    recovery = transition["external_recoveries"][0]
    assert recovery["result_status"] == "NOT_RETAINED"
    assert "result" not in recovery
    schema = json.loads(
        (SOURCE_ROOT / "tools/agents/schemas/successor-transition.schema.json").read_text()
    )
    Draft202012Validator(schema).validate(transition)

    recovery["result_status"] = "RETAINED"
    assert list(Draft202012Validator(schema).iter_errors(transition))
    with pytest.raises(successor.SuccessorError, match="result"):
        successor.validate_transition(
            transition, next(transition_root.glob("*.json"))
        )


def test_successor_schema_rejects_missing_external_recovery_event(
    recovered_repo: tuple[Path, str, str, Path, dict[str, object]], tmp_path: Path
) -> None:
    repo, _, predecessor, state_root, request = recovered_repo
    external = _external_recovery_binding(tmp_path)
    created = _session_cli(
        repo,
        state_root,
        "successor-missing-event-schema",
        "successor",
        "--predecessor-session", predecessor,
        "--request-id", str(request["request_id"]),
        "--recovery-event", "automatic-compaction-1",
        "--external-recovery", str(external),
        "--objective", "Require the directly bound external recovery event.",
    )
    assert created.returncode == 0, created.stderr
    transition_root = (
        Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
        / "seam-orchestration"
        / "successors"
    )
    transition_path = next(transition_root.glob("*.json"))
    transition = json.loads(transition_path.read_text())
    del transition["external_recoveries"][0]["recovery_event"]
    schema = json.loads(
        (SOURCE_ROOT / "tools/agents/schemas/successor-transition.schema.json").read_text()
    )

    assert list(Draft202012Validator(schema).iter_errors(transition))
    with pytest.raises(successor.SuccessorError, match="contract"):
        successor.validate_transition(transition, transition_path)


def test_successor_external_evidence_tamper_and_retained_root_drift_fail_closed(
    recovered_repo: tuple[Path, str, str, Path, dict[str, object]], tmp_path: Path
) -> None:
    repo, _, predecessor, state_root, request = recovered_repo
    external = _external_recovery_binding(tmp_path)
    created = _session_cli(
        repo,
        state_root,
        "successor-tamper",
        "successor",
        "--predecessor-session", predecessor,
        "--request-id", str(request["request_id"]),
        "--recovery-event", "automatic-compaction-1",
        "--external-recovery", str(external),
        "--objective", "Keep external evidence and root inventory stable.",
    )
    assert created.returncode == 0, created.stderr
    binding = json.loads(external.read_text(encoding="utf-8"))
    guardian = Path(binding["guardian_state"]["path"])
    original_guardian = guardian.read_bytes()
    guardian.write_text("tampered\n", encoding="utf-8")
    with pytest.raises((assurance.AssuranceError, successor.SuccessorError), match="external"):
        assurance.check_session(repo, "successor-tamper")
    guardian.write_bytes(original_guardian)
    added = tmp_path / "late-worktree"
    _git(repo, "worktree", "add", "--detach", str(added), "HEAD")
    with pytest.raises((assurance.AssuranceError, successor.SuccessorError), match="inventory"):
        assurance.check_session(repo, "successor-tamper")


def test_successor_does_not_exempt_same_session_request_from_foreign_root(
    recovered_repo: tuple[Path, str, str, Path, dict[str, object]], tmp_path: Path
) -> None:
    repo, _, predecessor, state_root, request = recovered_repo
    foreign = tmp_path / "foreign-worktree"
    _git(repo, "worktree", "add", "--detach", str(foreign), "HEAD")
    created = _session_cli(
        repo,
        state_root,
        "successor-lineage",
        "successor",
        "--predecessor-session", predecessor,
        "--request-id", str(request["request_id"]),
        "--recovery-event", "automatic-compaction-1",
        "--objective", "Bind successor closeout only to its own lineage.",
    )
    assert created.returncode == 0, created.stderr
    foreign_note = foreign / "docs" / "foreign.md"
    foreign_note.parent.mkdir()
    foreign_note.write_text("foreign same-session work\n", encoding="utf-8")
    queued = session_end_closeout.handle_session_end(
        {"session_id": "successor-lineage", "cwd": str(foreign)},
        repo_root=foreign,
        state_root=foreign / ".seam" / "orchestration" / "session-end",
        dispatch=False,
    )
    registration = json.loads(
        assurance._registration_path(
            assurance._common_dir(repo), "successor-lineage"
        ).read_text()
    )

    with pytest.raises(successor.SuccessorError, match=str(queued["request_id"])):
        successor.validate_registration_binding(repo, registration)


def test_successor_own_compaction_blocks_assurance(
    recovered_repo: tuple[Path, str, str, Path, dict[str, object]], tmp_path: Path
) -> None:
    repo, base, predecessor, state_root, request = recovered_repo
    created = _session_cli(
        repo,
        state_root,
        "successor-compacted",
        "successor",
        "--predecessor-session", predecessor,
        "--request-id", str(request["request_id"]),
        "--recovery-event", "automatic-compaction-1",
        "--objective", "Fail closed if the successor itself compacts.",
    )
    assert created.returncode == 0, created.stderr
    context_guardian.recover_unexpected_compaction(
        session_id="successor-compacted",
        event_id="successor-automatic-compaction",
        summary=["The successor compacted before assurance."],
        next_step="Create another explicit successor.",
        state_root=repo / ".seam" / "orchestration" / "context",
        handoff_root=repo / ".context-handoffs",
    )
    head = _git(repo, "rev-parse", "HEAD")
    paths, _ = session_end_closeout._changed_paths(repo, base)
    report = {
        "schema": "seam-independent-assurance/v1",
        "repository": "Canticle-AI-Research/Seam",
        "session_id": "successor-compacted",
        "base_sha": base,
        "head": head,
        "changed_paths": paths,
        "content_sha256": session_end_closeout._fingerprint(repo, head, base, paths),
        "reviewed_at": "2026-10-17T13:00:00Z",
        "reviewer": "independent-reviewer",
        "status": "PASS",
        "continuity_included": True,
        "summary": ["Reviewed the exact successor before its own recovery."],
    }
    report_path = tmp_path / "compacted-assurance.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(assurance.AssuranceError, match="successor session"):
        assurance.accept(repo, "successor-compacted", report_path)
