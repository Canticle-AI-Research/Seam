from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tools.security.secret_scan import (
    MAX_SCAN_BYTES,
    ZERO_SHA,
    scan_bytes,
    scan_git_range,
    scan_worktree_summary,
)

REPO = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str, input_text: str | None = None) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        input=input_text,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _commit(repo: Path, path: str, content: str, message: str) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", path)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    return repo


def test_canonical_patterns_cover_project_key_and_provider_session_url():
    content = (
        b"key=sk-proj-" + b"a" * 24 + b"\n"
        b"ref=https://chatgpt" + b".com/share/private-thread\n"
    )
    assert {item.kind for item in scan_bytes("candidate.txt", content)} == {
        "api_key",
        "provider_session_url",
    }


def test_commit_range_catches_secret_added_then_deleted(tmp_path):
    repo = _repo(tmp_path)
    old_sha = _commit(repo, "README.md", "clean\n", "base")
    _commit(repo, "temporary.txt", "sk-proj-" + "b" * 24, "introduce")
    (repo / "temporary.txt").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "remove")
    new_sha = _git(repo, "rev-parse", "HEAD")

    findings = scan_git_range(old_sha, new_sha, repo)

    assert [(item.path, item.kind) for item in findings] == [
        ("temporary.txt", "api_key")
    ]


def test_new_ref_excludes_remote_objects_but_scans_local_only_history(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "remote.txt", "sk-proj-" + "r" * 24, "remote secret")
    base = _commit(repo, "README.md", "clean\n", "base")
    _git(repo, "update-ref", "refs/remotes/origin/main", base)
    _commit(repo, "temporary.txt", "sk-proj-" + "d" * 24, "introduce")
    (repo / "temporary.txt").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "remove")
    new_sha = _git(repo, "rev-parse", "HEAD")

    findings = scan_git_range(ZERO_SHA, new_sha, repo, remote="origin")

    assert [(item.path, item.kind) for item in findings] == [
        ("temporary.txt", "api_key")
    ]


def test_oversized_text_fails_closed_and_binary_skip_is_reported(tmp_path):
    assert [item.kind for item in scan_bytes("large.txt", b"x" * (MAX_SCAN_BYTES + 1))] == [
        "scan_size_limit"
    ]
    repo = _repo(tmp_path)
    image = repo / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    _git(repo, "add", "image.png")

    summary = scan_worktree_summary(repo)

    assert summary.findings == ()
    assert summary.skipped == (("image.png", "binary_extension"),)


def test_private_origin_pre_push_scans_the_full_commit_range(tmp_path):
    repo = _repo(tmp_path)
    old_sha = _commit(repo, "README.md", "clean\n", "base")
    _commit(repo, "temporary.txt", "sk-proj-" + "c" * 24, "introduce")
    (repo / "temporary.txt").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "remove")
    new_sha = _git(repo, "rev-parse", "HEAD")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO)

    result = subprocess.run(
        [
            "bash",
            str(REPO / "tools" / "git-hooks" / "pre-push"),
            "origin",
            "git@github.com:BlackhatShiftey/Seam.git",
        ],
        cwd=repo,
        env=env,
        input=f"refs/heads/test {new_sha} refs/heads/test {old_sha}\n",
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "temporary.txt" in result.stderr
    assert "api_key" in result.stderr
    assert "sk-proj" not in result.stderr
