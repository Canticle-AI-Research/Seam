"""Public CLI contract for exact-state independent assurance."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.agents import context_guardian
from tools.agents.session_end_closeout import _changed_paths, _fingerprint


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "SEAM tests")
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "baseline")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "README.md").write_text("reviewed candidate\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "candidate")
    return repo, base


def _report(repo: Path, base: str, session_id: str) -> dict[str, object]:
    head = _git(repo, "rev-parse", "HEAD")
    paths, _ = _changed_paths(repo, base)
    return {
        "schema": "seam-independent-assurance/v1",
        "repository": "Canticle-AI-Research/Seam",
        "session_id": session_id,
        "base_sha": base,
        "head": head,
        "changed_paths": paths,
        "content_sha256": _fingerprint(repo, head, base, paths),
        "reviewed_at": "2026-10-17T05:00:00Z",
        "reviewer": "independent-reviewer",
        "status": "PASS",
        "continuity_included": True,
        "summary": ["Reviewed the exact committed candidate and continuity evidence."],
    }


def _common_dir(repo: Path) -> Path:
    path = Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    return path if path.is_absolute() else repo / path


def _cli(repo: Path, *arguments: str, env: dict[str, str] | None = None):
    command_env = os.environ.copy()
    command_env.update(env or {})
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "tools.agents.assurance",
            "--repo-root",
            str(repo),
            *arguments,
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=command_env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_subprocess_assurance_is_immutable_and_whitespace_edit_invalidates_push(
    tmp_path: Path,
) -> None:
    repo, base = _repo(tmp_path)
    session_id = "assurance-session"
    report_path = tmp_path / "assurance.json"
    report_path.write_text(
        json.dumps(_report(repo, base, session_id)), encoding="utf-8"
    )

    registered = _cli(
        repo, "register", "--session-id", session_id, "--base-sha", base
    )
    assert registered.returncode == 0, registered.stderr
    accepted = _cli(
        repo,
        "accept",
        "--session-id",
        session_id,
        "--report",
        str(report_path),
    )
    assert accepted.returncode == 0, accepted.stderr
    assert json.loads(accepted.stdout)["status"] == "ACCEPTED"
    repeated = _cli(
        repo,
        "accept",
        "--session-id",
        session_id,
        "--report",
        str(report_path),
    )
    assert repeated.returncode == 0, repeated.stderr
    assert json.loads(repeated.stdout)["status"] == "ALREADY_ACCEPTED"

    checked = _cli(
        repo, "check-push", "--head", _git(repo, "rev-parse", "HEAD"),
        env={"CODEX_SESSION_ID": ""},
    )
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["status"] == "PASS"

    (repo / "README.md").write_text("reviewed candidate \n", encoding="utf-8")
    invalidated = _cli(
        repo, "check-push", "--head", _git(repo, "rev-parse", "HEAD"),
        env={"CODEX_SESSION_ID": ""},
    )
    assert invalidated.returncode == 2
    assert "clean committed candidate" in invalidated.stderr


def test_unregistered_non_codex_push_is_explicitly_not_applicable(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)

    checked = _cli(
        repo, "check-push", "--head", _git(repo, "rev-parse", "HEAD"),
        env={"CODEX_SESSION_ID": ""},
    )

    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout) == {
        "sessions": [],
        "status": "NOT_APPLICABLE",
    }


def test_unexpected_compaction_blocks_assurance_acceptance(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    session_id = "assurance-recovery"
    report_path = tmp_path / "assurance.json"
    report_path.write_text(
        json.dumps(_report(repo, base, session_id)), encoding="utf-8"
    )
    assert _cli(
        repo, "register", "--session-id", session_id, "--base-sha", base
    ).returncode == 0
    context_guardian.recover_unexpected_compaction(
        session_id=session_id,
        event_id="unexpected-1",
        summary=["Automatic compaction interrupted the reviewed session."],
        next_step="Create a successor handoff.",
        state_root=repo / ".seam" / "orchestration" / "context",
        handoff_root=repo / ".context-handoffs",
    )

    accepted = _cli(
        repo,
        "accept",
        "--session-id",
        session_id,
        "--report",
        str(report_path),
    )

    assert accepted.returncode == 2
    assert "unexpected compaction recovery" in accepted.stderr


def test_real_pre_push_hook_enforces_registered_assurance_without_environment_id(
    tmp_path: Path,
) -> None:
    repo, base = _repo(tmp_path)
    session_id = "assurance-hook"
    report_path = tmp_path / "assurance.json"
    report_path.write_text(
        json.dumps(_report(repo, base, session_id)), encoding="utf-8"
    )
    assert _cli(
        repo, "register", "--session-id", session_id, "--base-sha", base
    ).returncode == 0
    assert _cli(
        repo, "accept", "--session-id", session_id, "--report", str(report_path)
    ).returncode == 0
    (repo / "README.md").write_text("reviewed candidate \n", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "CODEX_SESSION_ID": "",
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
            "SEAM_HOOK_PYTHON": sys.executable,
        }
    )

    result = subprocess.run(
        [
            "bash",
            str(Path(__file__).resolve().parents[2] / "tools/git-hooks/pre-push"),
            "origin",
            "git@example.invalid:repo",
        ],
        cwd=repo,
        env=env,
        input=(
            f"refs/heads/main {_git(repo, 'rev-parse', 'HEAD')} "
            f"refs/heads/main {'0' * 40}\n"
        ),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "clean committed candidate" in result.stderr


def test_real_pre_push_hook_rejects_unreviewed_outgoing_sha_from_reviewed_checkout(
    tmp_path: Path,
) -> None:
    repo, base = _repo(tmp_path)
    session_id = "assurance-outgoing"
    reviewed_head = _git(repo, "rev-parse", "HEAD")
    report_path = tmp_path / "assurance.json"
    report_path.write_text(json.dumps(_report(repo, base, session_id)), encoding="utf-8")
    assert _cli(
        repo, "register", "--session-id", session_id, "--base-sha", base
    ).returncode == 0
    assert _cli(
        repo, "accept", "--session-id", session_id, "--report", str(report_path)
    ).returncode == 0
    (repo / "README.md").write_text("unreviewed outgoing commit\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "unreviewed")
    unreviewed_head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "reset", "--hard", reviewed_head)
    env = os.environ.copy()
    env.update(
        {
            "CODEX_SESSION_ID": "",
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
            "SEAM_HOOK_PYTHON": sys.executable,
        }
    )

    result = subprocess.run(
        [
            "bash",
            str(Path(__file__).resolve().parents[2] / "tools/git-hooks/pre-push"),
            "origin",
            "git@example.invalid:repo",
        ],
        cwd=repo,
        env=env,
        input=(
            f"refs/heads/main {unreviewed_head} refs/heads/main {'0' * 40}\n"
        ),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "outgoing head" in result.stderr


def test_accept_binds_reviewer_registered_base_and_clean_committed_state(
    tmp_path: Path,
) -> None:
    repo, base = _repo(tmp_path)
    session_id = "assurance-contract"
    assert _cli(
        repo, "register", "--session-id", session_id, "--base-sha", base
    ).returncode == 0

    wrong_base = _git(repo, "rev-parse", "HEAD")
    wrong_report = _report(repo, wrong_base, session_id)
    wrong_path = tmp_path / "wrong-base.json"
    wrong_path.write_text(json.dumps(wrong_report), encoding="utf-8")
    rejected = _cli(
        repo, "accept", "--session-id", session_id, "--report", str(wrong_path)
    )
    assert rejected.returncode == 2
    assert "registered base" in rejected.stderr

    (repo / "README.md").write_text("reviewed candidate \n", encoding="utf-8")
    dirty_report = _report(repo, base, session_id)
    dirty_path = tmp_path / "dirty.json"
    dirty_path.write_text(json.dumps(dirty_report), encoding="utf-8")
    rejected = _cli(
        repo, "accept", "--session-id", session_id, "--report", str(dirty_path)
    )
    assert rejected.returncode == 2
    assert "clean committed candidate" in rejected.stderr

    dirty_report.pop("reviewer")
    missing_reviewer_path = tmp_path / "missing-reviewer.json"
    missing_reviewer_path.write_text(json.dumps(dirty_report), encoding="utf-8")
    rejected = _cli(
        repo,
        "accept",
        "--session-id",
        session_id,
        "--report",
        str(missing_reviewer_path),
    )
    assert rejected.returncode == 2
    assert "contract" in rejected.stderr


def test_check_push_binds_outgoing_head_and_ignores_removed_historical_worktree(
    tmp_path: Path,
) -> None:
    repo, base = _repo(tmp_path)
    session_id = "assurance-current"
    report_path = tmp_path / "current.json"
    report_path.write_text(json.dumps(_report(repo, base, session_id)), encoding="utf-8")
    assert _cli(
        repo, "register", "--session-id", session_id, "--base-sha", base
    ).returncode == 0
    assert _cli(
        repo, "accept", "--session-id", session_id, "--report", str(report_path)
    ).returncode == 0

    linked = tmp_path / "historical"
    _git(repo, "worktree", "add", "-qb", "historical", str(linked), base)
    assert _cli(
        linked,
        "register",
        "--session-id",
        "historical-session",
        "--base-sha",
        base,
    ).returncode == 0
    _git(repo, "worktree", "remove", "--force", str(linked))

    mismatch = _cli(repo, "check-push", "--head", base)
    assert mismatch.returncode == 2
    assert "outgoing head" in mismatch.stderr
    current = _cli(repo, "check-push", "--head", _git(repo, "rev-parse", "HEAD"))
    assert current.returncode == 0, current.stderr


def test_orphan_recovery_without_state_blocks_assurance(tmp_path: Path, monkeypatch) -> None:
    repo, base = _repo(tmp_path)
    session_id = "assurance-orphan"
    report_path = tmp_path / "orphan.json"
    report_path.write_text(json.dumps(_report(repo, base, session_id)), encoding="utf-8")
    assert _cli(
        repo, "register", "--session-id", session_id, "--base-sha", base
    ).returncode == 0
    original = context_guardian._atomic_write

    def fail_handoff(path: Path, encoded: bytes) -> None:
        if path.suffix == ".md":
            raise OSError("stop after recovery event")
        original(path, encoded)

    monkeypatch.setattr(context_guardian, "_atomic_write", fail_handoff)
    with pytest.raises(OSError, match="stop after recovery"):
        context_guardian.recover_unexpected_compaction(
            session_id=session_id,
            event_id="unexpected-orphan",
            summary=["Automatic compaction stopped before state publication."],
            next_step="Create a successor session.",
            state_root=repo / ".seam" / "orchestration" / "context",
            handoff_root=repo / ".context-handoffs",
        )

    accepted = _cli(
        repo, "accept", "--session-id", session_id, "--report", str(report_path)
    )
    assert accepted.returncode == 2
    assert "unexpected compaction recovery" in accepted.stderr


def test_corrected_candidate_can_select_a_new_immutable_assurance_report(
    tmp_path: Path,
) -> None:
    repo, base = _repo(tmp_path)
    session_id = "assurance-correction"
    first_path = tmp_path / "first.json"
    first_path.write_text(json.dumps(_report(repo, base, session_id)), encoding="utf-8")
    assert _cli(
        repo, "register", "--session-id", session_id, "--base-sha", base
    ).returncode == 0
    first = _cli(
        repo, "accept", "--session-id", session_id, "--report", str(first_path)
    )
    assert first.returncode == 0, first.stderr

    (repo / "README.md").write_text("corrected candidate\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "correction")
    second_path = tmp_path / "second.json"
    second_path.write_text(json.dumps(_report(repo, base, session_id)), encoding="utf-8")
    second = _cli(
        repo, "accept", "--session-id", session_id, "--report", str(second_path)
    )

    assert second.returncode == 0, second.stderr
    assert json.loads(second.stdout)["report_sha256"] != json.loads(first.stdout)[
        "report_sha256"
    ]
    checked = _cli(repo, "check-push", "--head", _git(repo, "rev-parse", "HEAD"))
    assert checked.returncode == 0, checked.stderr


def test_check_push_rejects_deleted_registration_or_active_binding(
    tmp_path: Path,
) -> None:
    for removed in ("registration", "active"):
        case_root = tmp_path / removed
        case_root.mkdir()
        repo, base = _repo(case_root)
        session_id = f"assurance-delete-{removed}"
        report_path = tmp_path / f"{removed}.json"
        report_path.write_text(json.dumps(_report(repo, base, session_id)), encoding="utf-8")
        assert _cli(
            repo, "register", "--session-id", session_id, "--base-sha", base
        ).returncode == 0
        assert _cli(
            repo, "accept", "--session-id", session_id, "--report", str(report_path)
        ).returncode == 0
        common = _common_dir(repo)
        if removed == "registration":
            (common / "seam-orchestration" / "assurance" / "registrations" / f"{session_id}.json").unlink()
        else:
            active_root = common / "seam-orchestration" / "assurance" / "active"
            next(active_root.glob("*.json")).unlink()

        checked = _cli(repo, "check-push", "--head", _git(repo, "rev-parse", "HEAD"))

        assert checked.returncode == 2
        assert "binding" in checked.stderr


def test_check_rejects_report_mutation_without_matching_source_hash(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    session_id = "assurance-report-tamper"
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_report(repo, base, session_id)), encoding="utf-8")
    assert _cli(
        repo, "register", "--session-id", session_id, "--base-sha", base
    ).returncode == 0
    accepted = _cli(
        repo, "accept", "--session-id", session_id, "--report", str(report_path)
    )
    assert accepted.returncode == 0
    digest = json.loads(accepted.stdout)["report_sha256"]
    stored = (
        _common_dir(repo)
        / "seam-orchestration"
        / "assurance"
        / "accepted"
        / session_id
        / f"{digest}.json"
    )
    value = json.loads(stored.read_text(encoding="utf-8"))
    value["report"]["reviewer"] = "substituted-reviewer"
    stored.write_text(json.dumps(value), encoding="utf-8")

    checked = _cli(repo, "check-push", "--head", _git(repo, "rev-parse", "HEAD"))

    assert checked.returncode == 2
    assert "report hash" in checked.stderr


def test_registered_outgoing_candidate_is_enforced_from_unregistered_sibling(
    tmp_path: Path,
) -> None:
    repo, base = _repo(tmp_path)
    session_id = "assurance-sibling"
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_report(repo, base, session_id)), encoding="utf-8")
    assert _cli(
        repo, "register", "--session-id", session_id, "--base-sha", base
    ).returncode == 0
    assert _cli(
        repo, "accept", "--session-id", session_id, "--report", str(report_path)
    ).returncode == 0
    sibling = tmp_path / "sibling"
    _git(repo, "worktree", "add", "--detach", str(sibling), _git(repo, "rev-parse", "HEAD"))

    checked = _cli(sibling, "check-push", "--head", _git(repo, "rev-parse", "HEAD"))

    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout)["sessions"] == [
        {"session_id": session_id, "status": "PASS"}
    ]


def test_unregistered_sibling_rejects_live_registered_unreviewed_head(
    tmp_path: Path,
) -> None:
    repo, base = _repo(tmp_path)
    session_id = "assurance-sibling-drift"
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(_report(repo, base, session_id)), encoding="utf-8")
    assert _cli(
        repo, "register", "--session-id", session_id, "--base-sha", base
    ).returncode == 0
    assert _cli(
        repo, "accept", "--session-id", session_id, "--report", str(report_path)
    ).returncode == 0
    (repo / "README.md").write_text("unreviewed correction\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "unreviewed correction")
    unreviewed = _git(repo, "rev-parse", "HEAD")
    sibling = tmp_path / "sibling-drift"
    _git(repo, "worktree", "add", "--detach", str(sibling), unreviewed)

    checked = _cli(sibling, "check-push", "--head", unreviewed)

    assert checked.returncode == 2
    assert "outgoing head" in checked.stderr
