"""The portable memory pin must not admit local hooks, secrets or symlinks."""

from __future__ import annotations

import json
import subprocess

import pytest

from tools.git.verify_agent_config import PIN, PIN_PATH, validate_pin, verify


@pytest.mark.parametrize("content", [
    b"{}",
    b"not json",
    b'{"autoMemoryDirectory":"~/elsewhere"}',
    json.dumps({**PIN, "hooks": {}}).encode(),
    json.dumps({**PIN, "env": {"EXAMPLE": "value"}}).encode(),
    b'{"autoMemoryDirectory":"~/other","autoMemoryDirectory":"~/.claude/memory-shared/seam"}',
    b"\xff",
])
def test_pin_rejects_nonportable_or_additional_settings(content):
    assert not validate_pin(content)


def test_pin_requires_a_regular_nonexecutable_file():
    content = json.dumps(PIN).encode()
    assert validate_pin(content)
    assert not validate_pin(content, "120000")
    assert not validate_pin(content, "100755")


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = tmp_path / PIN_PATH
    path.parent.mkdir()
    path.write_text(json.dumps(PIN))
    subprocess.run(["git", "add", PIN_PATH], cwd=tmp_path, check=True)
    return tmp_path


def test_staged_bad_config_cannot_hide_behind_clean_working_copy(repo):
    path = repo / PIN_PATH
    path.write_text(json.dumps({**PIN, "hooks": {}}))
    subprocess.run(["git", "add", PIN_PATH], cwd=repo, check=True)
    path.write_text(json.dumps(PIN))
    assert verify(repo) == []
    assert verify(repo, staged=True)


def test_removed_pin_cannot_hide_behind_an_untracked_copy(repo):
    subprocess.run(["git", "rm", "--cached", PIN_PATH], cwd=repo, check=True)
    assert verify(repo) == []
    assert verify(repo, staged=True)


def test_worktree_link_is_rejected_before_opening(repo, monkeypatch):
    from pathlib import Path

    original = Path.open
    monkeypatch.setattr(Path, "is_symlink", lambda self: self == repo / PIN_PATH)

    def forbid_pin_open(self, *args, **kwargs):
        assert self != repo / PIN_PATH, "validator opened a symlink target"
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", forbid_pin_open)
    assert verify(repo)


def test_oversized_index_blob_is_rejected(repo):
    (repo / PIN_PATH).write_bytes(b" " * 100000 + json.dumps(PIN).encode())
    subprocess.run(["git", "add", PIN_PATH], cwd=repo, check=True)
    assert verify(repo)
    assert verify(repo, staged=True)


@pytest.mark.parametrize("path", [
    ".claude/settings.local.json",
    ".claude/agents/helper.md",
    ".opencode/config.json",
    ".agents/notes.md",
    "nested/.claude/settings.json",
    ".CLAUDE/settings.json",
    "opencode.jsonc",
])
def test_other_agent_files_remain_blocked(repo, path):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("local data")
    subprocess.run(["git", "add", "-f", path], cwd=repo, check=True)
    assert any(path.casefold() in problem.casefold() for problem in verify(repo, staged=True))


def test_staged_symlink_is_rejected(repo):
    subprocess.run(
        ["git", "update-index", "--cacheinfo", "120000,"
         + subprocess.check_output(
             ["git", "hash-object", "-w", "--stdin"], input=b"elsewhere", cwd=repo
         ).decode().strip() + "," + PIN_PATH],
        cwd=repo, check=True,
    )
    assert verify(repo, staged=True)


def test_gitignore_exposes_only_the_root_pin(tmp_path):
    from pathlib import Path

    source = Path(__file__).resolve().parents[2]
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_bytes((source / ".gitignore").read_bytes())
    for path, ignored in [(PIN_PATH, False), (".claude/settings.local.json", True),
                          (".claude/worktrees/example/a.md", True),
                          ("nested/.claude/settings.json", True)]:
        result = subprocess.run(["git", "check-ignore", "-q", path], cwd=tmp_path)
        assert (result.returncode == 0) is ignored, path
