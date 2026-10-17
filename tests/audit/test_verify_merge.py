from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.agents import closeout_queue, session_end_closeout

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIRED_CHECKS = ("repo-hygiene", "chroma-real-smoke", "locomo-quickstart-bil2")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _merged_repo(
    tmp_path: Path,
    *,
    gate_stubs: bool = False,
    gate_sentinel: Path | None = None,
    delivery_plan: bool = False,
) -> tuple[Path, str, str]:
    repo = tmp_path / "merged"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "SEAM tests")
    if gate_stubs:
        for package in (
            "tools", "tools/git", "tools/history", "tools/streams", "tools/docs", "tools/release"
        ):
            directory = repo / package
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "__init__.py").write_text("")
        for module in (
            "tools/git/verify_agent_config.py", "tools/history/verify_integrity.py",
            "tools/history/verify_routing.py", "tools/history/verify_handoffs.py",
            "tools/history/verify_continuity.py", "tools/streams/verify_streams.py",
            "tools/docs/verify_wiki.py", "tools/docs/sync_references.py",
            "tools/docs/verify_audit_claims.py", "tools/release/verify_suite_manifest.py",
        ):
            body = ""
            if gate_sentinel is not None:
                body = (
                    "from pathlib import Path\n"
                    f"Path({str(gate_sentinel)!r}).write_text('ran')\n"
                )
            (repo / module).write_text(body)
    (repo / "README.md").write_text("base\n")
    if delivery_plan:
        plan = repo / "docs" / "delivery" / "current.json"
        plan.parent.mkdir(parents=True)
        plan.write_text(json.dumps({
            "schema": "seam-delivery-plan/v1",
            "delivery_id": "delivery-red-green",
            "repository": "acme/widget",
            "next_action_after_verified": "Continue with the next bounded repair.",
        }) + "\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-qb", "candidate")
    (repo / "README.md").write_text("candidate\n")
    _git(repo, "commit", "-qam", "candidate")
    candidate = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "--no-ff", "-qm", "merge candidate", candidate)
    return repo, candidate, _git(repo, "rev-parse", "HEAD")


def _qualification(tmp_path: Path, candidate: str) -> tuple[Path, Path]:
    state = tmp_path / "state"
    request_id = "merge-test-" + "d" * 16
    fingerprint = "d" * 64
    receipt_path = state.resolve() / "receipts" / f"{request_id}.json"
    request = {
        "schema": "seam-agent-closeout-request/v1",
        "request_id": request_id,
        "request_sha256": "0" * 64,
        "session_id": "merge-test",
        "created_at": "2026-10-16T12:00:00Z",
        "trigger": "SessionEnd",
        "repo": {
            "root": str((tmp_path / "integration").resolve()),
            "cwd": str((tmp_path / "integration").resolve()),
            "branch": "candidate",
            "head": candidate,
            "base_sha": "b" * 40,
            "origin_main": "b" * 40,
            "worktree": str((tmp_path / "integration").resolve()),
            "diff_fingerprint": fingerprint,
            "changed_paths": ["README.md"],
            "changed_paths_truncated": False,
        },
        "change_class": "non_runtime",
        "context": {
            "source": "root_session_state", "available": True, "objective": "merge candidate",
            "plan": [], "constraints": [], "affected_tests": [],
        },
        "tdd_evidence": {
            "status": "TDD_NOT_REQUIRED", "runtime_paths": [], "covered_runtime_paths": [],
            "missing_runtime_paths": [], "cycle_count": 0, "cycles": [],
        },
        "authority": {
            "mode": "verify_only", "allowed_writes": [], "forbidden_actions": ["merge"],
        },
        "required_checks": list(session_end_closeout.REQUIRED_CLOSEOUT_CHECKS),
        "receipt_path": str(receipt_path),
        "request_schema": "tools/agents/schemas/closeout-request.schema.json",
        "receipt_schema": "tools/agents/schemas/closeout-receipt.schema.json",
    }
    request["request_sha256"] = closeout_queue._request_hash(request)
    receipt = {
        "schema": "seam-agent-closeout-receipt/v1", "request_id": request_id,
        "request_sha256": request["request_sha256"], "session_id": "merge-test",
        "completed_at": "2026-10-16T12:09:00Z", "status": "QUALIFIED",
        "supersedes_request_ids": [],
        "scope": {"head": candidate, "diff_fingerprint": fingerprint, "matches_request": True},
        "tdd": {"status": "TDD_NOT_REQUIRED", "evidence": ["not runtime"]},
        "checks": [
            {"requirement": requirement, "command": requirement, "status": "PASS", "exit_code": 0,
             "evidence": "passed"}
            for requirement in session_end_closeout.REQUIRED_CLOSEOUT_CHECKS
        ],
        "continuity": {"status": "PASS", "evidence": ["passed"]},
        "project_alignment": {"status": "ALIGNED", "evidence": ["aligned"]},
        "next_action": "verify merge",
    }
    request_path = state / "requests" / f"{request_id}.json"
    request_path.parent.mkdir(parents=True)
    receipt_path.parent.mkdir(parents=True)
    request_path.write_text(json.dumps(request))
    receipt_path.write_text(json.dumps(receipt))
    return request_path, receipt_path


def _fake_gh(
    tmp_path: Path,
    *,
    pr: dict,
    main: str,
    checks: list[dict],
    ruleset_checks: tuple[str, ...] = REQUIRED_CHECKS,
) -> dict[str, str]:
    responses = {
        "auth status --hostname github.com": {},
        "api --method GET repos/acme/widget/pulls/7": pr,
        "api --method GET repos/acme/widget/git/ref/heads/main": {"object": {"sha": main}},
        "api --method GET repos/acme/widget/rules/branches/main?per_page=100 --paginate": {
            "pages": [[{
                "type": "required_status_checks", "ruleset_id": 44,
                "parameters": {"required_status_checks": [
                    {"context": name, "integration_id": None} for name in ruleset_checks
                ]},
            }]]
        },
        (
            f"api --method GET repos/acme/widget/commits/{pr['head']['sha']}"
            "/check-runs?per_page=100 --paginate"
        ): {"pages": [{"check_runs": checks}]},
    }
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    gh = bin_dir / "gh"
    gh.write_text(
        """#!/usr/bin/env python3
import json, os, sys
data = json.loads(os.environ['FAKE_GH_RESPONSES'])
key = ' '.join(sys.argv[1:])
if key not in data:
    print('unexpected gh invocation: ' + key, file=sys.stderr); raise SystemExit(97)
item = data[key]
if isinstance(item, dict) and 'pages' in item:
    for page in item['pages']: print(json.dumps(page))
else: print(json.dumps(item))
"""
    )
    gh.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FAKE_GH_RESPONSES"] = json.dumps(responses)
    return env


def _run(
    tmp_path: Path,
    repo: Path,
    candidate: str,
    merged: str,
    pr: dict,
    checks: list[dict],
    *,
    qualification: tuple[Path, Path] | None = None,
    ruleset_checks: tuple[str, ...] = REQUIRED_CHECKS,
    plan: Path | None = None,
):
    request, receipt = qualification or _qualification(tmp_path, candidate)
    command = [
        sys.executable, "-m", "tools.ci.verify_merge", "--repo", "acme/widget", "--pr", "7",
        "--expected-candidate", candidate, "--expected-main", merged, "--worktree", str(repo),
        "--request", str(request), "--receipt", str(receipt),
        "--evidence", str(tmp_path / "evidence.json"),
    ]
    if plan is not None:
        command.extend(("--plan", str(plan)))
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=_fake_gh(
            tmp_path, pr=pr, main=merged, checks=checks, ruleset_checks=ruleset_checks
        ),
        capture_output=True, text=True, timeout=30,
    )


def _pr(candidate: str, merge_sha: str, *, head_repo: str = "acme/widget", **updates) -> dict:
    value = {
        "number": 7, "state": "closed", "merged": True, "merged_at": "2026-10-16T12:10:00Z",
        "merge_commit_sha": merge_sha,
        "head": {"sha": candidate, "repo": {"full_name": head_repo}},
        "base": {"ref": "main", "repo": {"full_name": "acme/widget"}},
    }
    value.update(updates)
    return value


def _checks(candidate: str) -> list[dict]:
    return [
        {"name": name, "head_sha": candidate, "status": "completed", "conclusion": "success",
         "started_at": "2026-10-16T12:08:00Z", "completed_at": "2026-10-16T12:09:00Z",
         "app": {"slug": "github-actions", "id": 15368}}
        for name in REQUIRED_CHECKS
    ]


def test_verify_merge_rejects_closed_unmerged_and_wrong_identity(tmp_path: Path) -> None:
    repo, candidate, merged = _merged_repo(tmp_path)
    result = _run(tmp_path, repo, candidate, merged, _pr(candidate, merged, merged=False, merged_at=None), _checks(candidate))
    assert result.returncode == 1
    assert "not merged" in result.stderr


def test_verify_merge_accepts_exact_candidate_from_valid_fork(tmp_path: Path) -> None:
    repo, candidate, merged = _merged_repo(tmp_path, gate_stubs=True)

    result = _run(
        tmp_path,
        repo,
        candidate,
        merged,
        _pr(candidate, merged, head_repo="contributor/widget"),
        _checks(candidate),
    )

    assert result.returncode == 0, result.stderr


def test_verify_merge_rejects_qualification_completed_after_merge(tmp_path: Path) -> None:
    gate_sentinel = tmp_path / "gate-ran"
    repo, candidate, merged = _merged_repo(
        tmp_path, gate_stubs=True, gate_sentinel=gate_sentinel
    )
    request, receipt = _qualification(tmp_path, candidate)
    receipt_value = json.loads(receipt.read_text())
    receipt_value["completed_at"] = "2026-10-16T12:11:00Z"
    receipt.write_text(json.dumps(receipt_value))
    (repo / "README.md").write_text("dirty merged worktree\n")

    result = _run(
        tmp_path / "run",
        repo,
        candidate,
        merged,
        _pr(candidate, merged),
        _checks(candidate),
        qualification=(request, receipt),
    )

    assert result.returncode == 1
    assert "qualification completed after pull request merge" in result.stderr
    assert not gate_sentinel.exists()


def test_verify_merge_rejects_missing_or_stale_required_check(tmp_path: Path) -> None:
    repo, candidate, merged = _merged_repo(tmp_path)
    checks = _checks(candidate)[:-1]
    result = _run(tmp_path, repo, candidate, merged, _pr(candidate, merged), checks)
    assert result.returncode == 1
    assert "locomo-quickstart-bil2" in result.stderr


def test_verify_merge_rejects_required_check_completed_before_it_started(tmp_path: Path) -> None:
    repo, candidate, merged = _merged_repo(tmp_path, gate_stubs=True)
    checks = _checks(candidate)
    checks[0]["completed_at"] = "2026-10-16T12:07:00Z"

    result = _run(tmp_path, repo, candidate, merged, _pr(candidate, merged), checks)

    assert result.returncode == 1
    assert "required check completed before it started: repo-hygiene" in result.stderr


def test_verify_merge_rejects_required_check_completed_after_qualification(tmp_path: Path) -> None:
    repo, candidate, merged = _merged_repo(tmp_path, gate_stubs=True)
    checks = _checks(candidate)
    checks[0]["completed_at"] = "2026-10-16T12:09:01Z"

    result = _run(tmp_path, repo, candidate, merged, _pr(candidate, merged), checks)

    assert result.returncode == 1
    assert "required check completed after qualification: repo-hygiene" in result.stderr


def test_verify_merge_accepts_equal_instants_fractional_seconds_and_offsets(
    tmp_path: Path,
) -> None:
    repo, candidate, merged = _merged_repo(tmp_path, gate_stubs=True)
    request, receipt = _qualification(tmp_path, candidate)
    receipt_value = json.loads(receipt.read_text())
    receipt_value["completed_at"] = "2026-10-16T07:09:00-05:00"
    receipt.write_text(json.dumps(receipt_value))
    checks = _checks(candidate)
    for check in checks:
        check["started_at"] = "2026-10-16T07:08:00.500000-05:00"
        check["completed_at"] = "2026-10-16T12:09:00.000000+00:00"
    merged_at = "2026-10-16T12:09:00.000001Z"

    result = _run(
        tmp_path / "run",
        repo,
        candidate,
        merged,
        _pr(candidate, merged, merged_at=merged_at),
        checks,
        qualification=(request, receipt),
    )

    assert result.returncode == 0, result.stderr
    evidence = json.loads((tmp_path / "run" / "evidence.json").read_text())
    assert evidence["merged_at"] == merged_at
    assert evidence["qualification"]["receipt_completed_at"] == "2026-10-16T07:09:00-05:00"
    assert evidence["required_checks"][0]["started_at"] == "2026-10-16T07:08:00.500000-05:00"
    assert evidence["required_checks"][0]["completed_at"] == "2026-10-16T12:09:00.000000+00:00"


@pytest.mark.parametrize(
    "field,value",
    [
        ("started_at", None),
        ("started_at", "not-a-time"),
        ("started_at", "2026-10-16T12:08:00"),
        ("completed_at", None),
        ("completed_at", "not-a-time"),
        ("completed_at", "2026-10-16T12:09:00"),
    ],
)
def test_verify_merge_rejects_invalid_required_check_times_before_gates(
    tmp_path: Path, field: str, value: str | None
) -> None:
    gate_sentinel = tmp_path / "gate-ran"
    repo, candidate, merged = _merged_repo(
        tmp_path, gate_stubs=True, gate_sentinel=gate_sentinel
    )
    checks = _checks(candidate)
    checks[0][field] = value
    evidence_path = tmp_path / "evidence.json"

    result = _run(tmp_path, repo, candidate, merged, _pr(candidate, merged), checks)

    assert result.returncode == 1
    assert not gate_sentinel.exists()
    assert not evidence_path.exists()


@pytest.mark.parametrize(
    "source,value",
    [
        ("qualification", None),
        ("qualification", "not-a-time"),
        ("qualification", "2026-10-16T12:09:00"),
        ("merge", None),
        ("merge", "not-a-time"),
        ("merge", "2026-10-16T12:10:00"),
    ],
)
def test_verify_merge_rejects_invalid_phase_times_before_gates(
    tmp_path: Path, source: str, value: str | None
) -> None:
    gate_sentinel = tmp_path / "gate-ran"
    repo, candidate, merged = _merged_repo(
        tmp_path, gate_stubs=True, gate_sentinel=gate_sentinel
    )
    request, receipt = _qualification(tmp_path, candidate)
    pr = _pr(candidate, merged)
    if source == "qualification":
        receipt_value = json.loads(receipt.read_text())
        receipt_value["completed_at"] = value
        receipt.write_text(json.dumps(receipt_value))
    else:
        pr["merged_at"] = value

    result = _run(
        tmp_path / "run",
        repo,
        candidate,
        merged,
        pr,
        _checks(candidate),
        qualification=(request, receipt),
    )

    assert result.returncode == 1
    assert not gate_sentinel.exists()
    assert not (tmp_path / "run" / "evidence.json").exists()


def test_verify_merge_rejects_squash_or_rebase_shape(tmp_path: Path) -> None:
    repo, candidate, _merge = _merged_repo(tmp_path)
    _git(repo, "reset", "--hard", candidate)
    result = _run(tmp_path, repo, candidate, candidate, _pr(candidate, candidate), _checks(candidate))
    assert result.returncode == 1
    assert "ordinary merge commit" in result.stderr


def test_verify_merge_rejects_invalid_stored_qualification(tmp_path: Path) -> None:
    repo, candidate, merged = _merged_repo(tmp_path)
    request, receipt = _qualification(tmp_path, candidate)
    value = json.loads(receipt.read_text())
    value["status"] = "INDETERMINATE"
    receipt.write_text(json.dumps(value))
    result = subprocess.run(
        [sys.executable, "-m", "tools.ci.verify_merge", "--repo", "acme/widget", "--pr", "7",
         "--expected-candidate", candidate, "--expected-main", merged, "--worktree", str(repo),
         "--request", str(request), "--receipt", str(receipt), "--evidence", str(tmp_path / "out.json")],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 1
    assert "qualification" in result.stderr


def test_verify_merge_rejects_qualification_outside_canonical_queue(tmp_path: Path) -> None:
    repo, candidate, merged = _merged_repo(tmp_path, gate_stubs=True)
    request, receipt = _qualification(tmp_path, candidate)
    request_value = json.loads(request.read_text())
    receipt_value = json.loads(receipt.read_text())
    forged_request = tmp_path / "forged-request.json"
    forged_receipt = (
        tmp_path / "forged-state" / "receipts" / f"{request_value['request_id']}.json"
    )
    forged_receipt.parent.mkdir(parents=True)
    request_value["receipt_path"] = str(forged_receipt)
    request_value["request_sha256"] = closeout_queue._request_hash(request_value)
    receipt_value["request_sha256"] = request_value["request_sha256"]
    forged_request.write_text(json.dumps(request_value))
    forged_receipt.write_text(json.dumps(receipt_value))

    result = _run(
        tmp_path / "run",
        repo,
        candidate,
        merged,
        _pr(candidate, merged),
        _checks(candidate),
        qualification=(forged_request, forged_receipt),
    )

    assert result.returncode == 1
    assert "queued" in result.stderr or "queue" in result.stderr


def test_verify_merge_accepts_content_addressed_qualified_retry(tmp_path: Path) -> None:
    repo, candidate, merged = _merged_repo(tmp_path, gate_stubs=True)
    request_path, canonical = _qualification(tmp_path, candidate)
    request = json.loads(request_path.read_text())
    qualified = json.loads(canonical.read_text())
    failed = json.loads(canonical.read_text())
    failed["status"] = "NOT_QUALIFIED"
    failed["checks"][0]["status"] = "FAIL"
    failed["checks"][0]["exit_code"] = 1
    failed["next_action"] = "retry"
    canonical.write_text(json.dumps(failed))
    encoded = closeout_queue._canonical_record(qualified)
    attempt = closeout_queue._receipt_attempt_path(
        canonical.parent.parent, request["request_id"], encoded
    )
    attempt.parent.mkdir()
    attempt.write_bytes(encoded)

    result = _run(
        tmp_path / "run",
        repo,
        candidate,
        merged,
        _pr(candidate, merged),
        _checks(candidate),
        qualification=(request_path, attempt),
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "updates,message",
    [
        ({"head": {"sha": "9" * 40, "repo": {"full_name": "acme/widget"}}}, "head does not match"),
        ({"base": {"ref": "release", "repo": {"full_name": "acme/widget"}}}, "base is not protected main"),
    ],
)
def test_verify_merge_rejects_wrong_live_pr_head_or_base(tmp_path: Path, updates, message) -> None:
    repo, candidate, merged = _merged_repo(tmp_path)

    result = _run(tmp_path, repo, candidate, merged, _pr(candidate, merged, **updates), _checks(candidate))

    assert result.returncode == 1
    assert message in result.stderr


def test_verify_merge_rejects_merge_that_does_not_have_candidate_as_second_parent(tmp_path: Path) -> None:
    repo, candidate, merged = _merged_repo(tmp_path)
    first_parent = _git(repo, "rev-parse", f"{merged}^1")

    result = _run(tmp_path, repo, first_parent, merged, _pr(first_parent, merged), _checks(first_parent))

    assert result.returncode == 1
    assert "second parent" in result.stderr


def test_verify_merge_rejects_a_failing_canonical_gate(tmp_path: Path) -> None:
    repo, candidate, merged = _merged_repo(tmp_path)

    result = _run(tmp_path, repo, candidate, merged, _pr(candidate, merged), _checks(candidate))

    assert result.returncode == 1
    assert "canonical gate failed" in result.stderr


@pytest.mark.parametrize(
    "status,conclusion,started_at,completed_at",
    [
        ("in_progress", None, "2026-10-16T12:10:00Z", None),
        ("completed", "failure", "2026-10-16T12:08:30Z", "2026-10-16T12:08:45Z"),
    ],
)
def test_verify_merge_rejects_newer_non_successful_run_even_when_an_older_run_succeeded(
    tmp_path: Path,
    status: str,
    conclusion: str | None,
    started_at: str,
    completed_at: str | None,
) -> None:
    repo, candidate, merged = _merged_repo(tmp_path)
    checks = _checks(candidate)
    checks.append({
        "name": "repo-hygiene", "head_sha": candidate, "status": status,
        "conclusion": conclusion, "started_at": started_at, "completed_at": completed_at,
        "app": {"slug": "github-actions", "id": 15368},
    })

    result = _run(tmp_path, repo, candidate, merged, _pr(candidate, merged), checks)

    assert result.returncode == 1
    assert "stale or unsuccessful: repo-hygiene" in result.stderr


def test_verify_merge_rejects_newer_success_completed_after_qualification(
    tmp_path: Path,
) -> None:
    repo, candidate, merged = _merged_repo(tmp_path, gate_stubs=True)
    checks = _checks(candidate)
    checks.append({
        "name": "repo-hygiene", "head_sha": candidate, "status": "completed",
        "conclusion": "success", "started_at": "2026-10-16T12:09:01Z",
        "completed_at": "2026-10-16T12:09:02Z",
        "app": {"slug": "github-actions", "id": 15368},
    })

    result = _run(tmp_path, repo, candidate, merged, _pr(candidate, merged), checks)

    assert result.returncode == 1
    assert "required check completed after qualification: repo-hygiene" in result.stderr


def test_verify_merge_enforces_every_live_ruleset_context(tmp_path: Path) -> None:
    repo, candidate, merged = _merged_repo(tmp_path, gate_stubs=True)
    live_contexts = (*REQUIRED_CHECKS, "new-required-check")

    result = _run(
        tmp_path,
        repo,
        candidate,
        merged,
        _pr(candidate, merged),
        _checks(candidate),
        ruleset_checks=live_contexts,
    )

    assert result.returncode == 1
    assert "new-required-check" in result.stderr


def test_verify_merge_writes_exact_identity_and_gate_evidence_after_all_proofs_pass(tmp_path: Path) -> None:
    repo, candidate, merged = _merged_repo(tmp_path, gate_stubs=True)

    result = _run(tmp_path, repo, candidate, merged, _pr(candidate, merged), _checks(candidate))

    assert result.returncode == 0, result.stderr
    evidence = json.loads((tmp_path / "evidence.json").read_text())
    assert evidence["expected_candidate"] == candidate
    assert evidence["result_main"] == merged
    assert evidence["merge"]["second_parent"] == candidate
    assert [item["name"] for item in evidence["required_checks"]] == list(REQUIRED_CHECKS)
    assert evidence["required_checks"][0]["app_slug"] == "github-actions"
    assert evidence["required_checks"][0]["ruleset_id"] == 44
    assert evidence["required_checks"][0]["ruleset_integration_id"] is None
    assert len(evidence["canonical_gates"]) == 11
    assert all(item["exit_code"] == 0 for item in evidence["canonical_gates"])


def test_planned_delivery_completion_survives_verification_worktree_removal(
    tmp_path: Path,
) -> None:
    repo, candidate, merged = _merged_repo(
        tmp_path, gate_stubs=True, delivery_plan=True
    )
    verification = tmp_path / "exact-main-verification"
    _git(repo, "worktree", "add", "--detach", str(verification), merged)

    result = _run(
        tmp_path / "run",
        verification,
        candidate,
        merged,
        _pr(candidate, merged),
        _checks(candidate),
        plan=verification / "docs" / "delivery" / "current.json",
    )

    assert result.returncode == 0, result.stderr
    common_dir = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    completion = (
        common_dir
        / "seam-orchestration"
        / "delivery-completions"
        / "delivery-red-green.json"
    )
    record = json.loads(completion.read_text())
    assert record["schema"] == "seam-delivery-completion/v1"
    assert record["plan"]["delivery_id"] == "delivery-red-green"
    assert record["proof"]["result_main"] == merged
    assert record["request"]["repo"]["head"] == candidate
    assert record["receipt"]["status"] == "QUALIFIED"

    # Canonical Python gates leave disposable __pycache__ files in this minimal
    # fixture repository, so remove the temporary linked worktree explicitly.
    _git(repo, "worktree", "remove", "--force", str(verification))
    status = subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.agents.delivery_status",
            "--repo-root",
            str(repo),
            "--plan",
            str(repo / "docs" / "delivery" / "current.json"),
            "--json",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["status"] == "VERIFIED"

    first_parent = _git(repo, "rev-parse", f"{merged}^1")
    _git(repo, "reset", "--hard", first_parent)
    wrong_ancestry = subprocess.run(
        status.args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert wrong_ancestry.returncode != 0
    assert "ancestry" in json.loads(wrong_ancestry.stdout)["reason"]
    _git(repo, "reset", "--hard", merged)

    original_plan = (repo / "docs" / "delivery" / "current.json").read_text()
    successor_plan = json.loads(original_plan)
    successor_plan["delivery_id"] = "delivery-successor"
    (repo / "docs" / "delivery" / "current.json").write_text(
        json.dumps(successor_plan) + "\n"
    )
    _git(repo, "add", "docs/delivery/current.json")
    _git(repo, "commit", "-qm", "advance delivery plan")
    (repo / "docs" / "delivery" / "current.json").write_text(original_plan)
    restored_old_plan = subprocess.run(
        status.args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert restored_old_plan.returncode != 0
    assert "HEAD" in json.loads(restored_old_plan.stdout)["reason"]
    _git(repo, "reset", "--hard", merged)

    changed_plan = json.loads(original_plan)
    changed_plan["next_action_after_verified"] = "A different next action."
    (repo / "docs" / "delivery" / "current.json").write_text(json.dumps(changed_plan) + "\n")
    mismatched_plan = subprocess.run(
        status.args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert mismatched_plan.returncode != 0
    assert "plan" in json.loads(mismatched_plan.stdout)["reason"]
    (repo / "docs" / "delivery" / "current.json").write_text(original_plan)

    original_record = json.loads(completion.read_text())

    def status_for_forged_record(mutator) -> subprocess.CompletedProcess[str]:
        forged = json.loads(json.dumps(original_record))
        mutator(forged)
        for artifact in ("request", "receipt", "proof"):
            blob = (
                json.dumps(forged[artifact], indent=2, sort_keys=True) + "\n"
            ).encode()
            forged[f"{artifact}_blob_base64"] = base64.b64encode(blob).decode()
            forged[f"{artifact}_blob_sha256"] = hashlib.sha256(blob).hexdigest()
        completion.write_text(json.dumps(forged))
        return subprocess.run(
            status.args,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

    one_required_check = status_for_forged_record(
        lambda forged: forged["proof"].__setitem__(
            "required_checks", forged["proof"]["required_checks"][:1]
        )
    )
    assert one_required_check.returncode != 0
    assert "required checks" in json.loads(one_required_check.stdout)["reason"]

    fake_gate_command = status_for_forged_record(
        lambda forged: forged["proof"]["canonical_gates"][0].__setitem__(
            "command", ["true"]
        )
    )
    assert fake_gate_command.returncode != 0
    assert "canonical gates" in json.loads(fake_gate_command.stdout)["reason"]

    impossible_ci_time = status_for_forged_record(
        lambda forged: forged["proof"]["required_checks"][0].update({
            "started_at": "2099-01-01T00:00:00Z",
            "completed_at": "2099-01-01T00:01:00Z",
        })
    )
    assert impossible_ci_time.returncode != 0
    assert "time" in json.loads(impossible_ci_time.stdout)["reason"]

    def forge_qualification_candidate(forged: dict) -> None:
        other_candidate = "0" * 40
        forged["request"]["repo"]["head"] = other_candidate
        forged["request"]["request_sha256"] = closeout_queue._request_hash(
            forged["request"]
        )
        forged["receipt"]["request_sha256"] = forged["request"]["request_sha256"]
        forged["receipt"]["scope"]["head"] = other_candidate
        forged["proof"]["qualification"]["request_sha256"] = forged["request"][
            "request_sha256"
        ]

    wrong_qualified_candidate = status_for_forged_record(
        forge_qualification_candidate
    )
    assert wrong_qualified_candidate.returncode != 0
    assert "candidate" in json.loads(wrong_qualified_candidate.stdout)["reason"]

    record = json.loads(json.dumps(original_record))
    record["proof"]["status"] = "FAIL"
    completion.write_text(json.dumps(record))
    tampered = subprocess.run(
        status.args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert tampered.returncode != 0
    assert "proof" in json.loads(tampered.stdout)["reason"]


def test_planned_delivery_never_completes_when_a_canonical_gate_fails(
    tmp_path: Path,
) -> None:
    repo, candidate, merged = _merged_repo(tmp_path, delivery_plan=True)

    result = _run(
        tmp_path / "run",
        repo,
        candidate,
        merged,
        _pr(candidate, merged),
        _checks(candidate),
        plan=repo / "docs" / "delivery" / "current.json",
    )

    assert result.returncode == 1
    common_dir = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    completion = (
        common_dir
        / "seam-orchestration"
        / "delivery-completions"
        / "delivery-red-green.json"
    )
    assert not completion.exists()
