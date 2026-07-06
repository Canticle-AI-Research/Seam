"""Public/private separation gate: tools/release/verify_public_safe.py.

Covers the pure per-blob scan rules directly, then exercises scan_push
against real throwaway git repos to prove the "every object newly reachable
by the push" design actually catches content introduced and later removed
within the same push -- not just a diff of tip trees, which would miss it.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools.release.verify_public_safe import ZERO_SHA, scan_blob, scan_push


# --- pure per-blob rules -----------------------------------------------------

@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.local",
        "nested/.env.production",
        "seam.db",
        "test_seam/pgvector/state.sqlite3",
        ".claude/settings.json",
        ".opencode/config.json",
        ".agents/notes.md",
        "id_rsa",
        "id_ed25519.pub",
        "keys/server.pem",
        "keys/server.key",
        "secrets/api.txt",
        "config/credentials.json",
        "credentials",
    ],
)
def test_denied_paths_block_regardless_of_content(path: str) -> None:
    findings = scan_blob(path, b"harmless content")
    assert findings
    assert findings[0].severity == "BLOCK"


def test_env_example_is_not_blocked() -> None:
    findings = scan_blob(".env.example", b"API_KEY=<your-key-here>")
    assert findings == []


@pytest.mark.parametrize("path", ["README.md", "seam_runtime/mcp.py"])
def test_clean_content_has_no_findings(path: str) -> None:
    assert scan_blob(path, b"nothing sensitive here\n") == []


def test_aws_key_shape_blocks() -> None:
    # Fixture value is split across a `+` so the AKIA-prefixed run is not
    # contiguous in this file's own source text (the repo's own
    # verify_continuity secret scanner would otherwise flag this file).
    # Path is allow-listed so this exercises content detection, not the
    # allow-list check (see test_path_not_on_allow_list_blocks for that).
    findings = scan_blob("seam_runtime/notes.md", b"key: AKIA" + b"ABCDEFGHIJKLMNOP")
    assert any(f.severity == "BLOCK" for f in findings)


def test_anthropic_key_shape_blocks() -> None:
    findings = scan_blob("seam_runtime/notes.md", b"sk-ant-" + b"a" * 30)
    assert any(f.severity == "BLOCK" for f in findings)


def test_private_key_header_blocks() -> None:
    findings = scan_blob(
        "seam_runtime/notes.txt", b"-----BEGIN RSA " + b"PRIVATE KEY-----\nMIIB...\n"
    )
    assert any(f.severity == "BLOCK" for f in findings)


def test_dsn_with_embedded_credentials_blocks() -> None:
    findings = scan_blob(
        "seam_runtime/notes.md", b"dsn = postgresql:" + b"//user:hunter2@db.internal:5432/seam"
    )
    assert any(f.severity == "BLOCK" for f in findings)


def test_dsn_with_placeholder_password_does_not_block() -> None:
    # Regression: seam_runtime/webui/dashboard.html ships a UI default of
    # 'postgres://user:pw@host:5432/seam' as an example connector value.
    # That's not a credential; it must not block every future push.
    findings = scan_blob(
        "seam_runtime/webui/dashboard.html", b"baseUrl: 'postgres:" + b"//user:pw@host:5432/seam'"
    )
    assert findings == []


def test_claude_share_link_blocks() -> None:
    # HISTORY.md is public-owned (allow-listed), so this exercises content
    # detection on a real path this rule protects.
    findings = scan_blob(
        "HISTORY.md", b"see https://claude" + b".ai/share/abc123-def456"
    )
    assert any(f.severity == "BLOCK" for f in findings)


def test_generic_password_pattern_warns_but_does_not_block() -> None:
    findings = scan_blob("seam_runtime/config.py", b'password = "not-a-real-secret"')
    assert findings
    assert all(f.severity == "WARN" for f in findings)


# --- allow-list rules ---------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "docs/audits/2026-05-28-deep-health-audit.md",
        "docs/SOP_TRACK_K_BIL_PHASE1_DEEPSEEK.md",
        "docs/handoffs/2026-06-08-h2-self-improvement-loop.md",
        "docs/roadmap/COMPETITIVE_ROADMAP.md",
        "skills/seam-engineer/SKILL.md",
        "archive/code/README.md",
        "tools/release/verify_public_safe.py",
        "tools/claude/preflight_protocol.sh",
        "some/brand/new/path/nobody/added/yet.md",
    ],
)
def test_path_not_on_allow_list_blocks(path: str) -> None:
    findings = scan_blob(path, b"harmless content")
    assert findings
    assert findings[0].severity == "BLOCK"
    assert "allow-list" in findings[0].reason


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "seam_runtime/mcp.py",
        "tests/audit/test_public_safe_gate.py",
        "docs/MACOS.md",
        "tools/h2/holdout_split.py",
        "tools/history/new_entry.py",
        # public-owned paths (the public repo's own bookkeeping) must also pass
        "HISTORY.md",
        "PROJECT_STATUS.md",
        ".seam/streams/history/log.md",
    ],
)
def test_allow_listed_paths_pass(path: str) -> None:
    assert scan_blob(path, b"nothing sensitive here\n") == []


def test_binary_extension_skips_content_scan() -> None:
    # A secret-shaped string inside a binary-extension file should not be
    # flagged by content scanning -- only the path rules apply to binaries.
    findings = scan_blob("branding/logo.png", b"AKIA" + b"ABCDEFGHIJKLMNOP")
    assert findings == []


# --- scan_push against real throwaway git repos ------------------------------

def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()


@pytest.fixture()
def throwaway_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    return repo


def _commit(repo: Path, files: dict[str, str], message: str) -> str:
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def test_scan_push_clean_range_passes(throwaway_repo: Path) -> None:
    old_sha = _commit(throwaway_repo, {"README.md": "hello\n"}, "old state")
    new_sha = _commit(throwaway_repo, {"seam_runtime/notes.md": "more docs\n"}, "new state")
    result = scan_push(old_sha, new_sha, throwaway_repo)
    assert result.ok


def test_scan_push_flags_path_outside_allow_list(throwaway_repo: Path) -> None:
    old_sha = _commit(throwaway_repo, {"README.md": "hello\n"}, "old state")
    new_sha = _commit(
        throwaway_repo, {"docs/audits/2026-99-99-some-internal-audit.md": "notes\n"}, "new state"
    )
    result = scan_push(old_sha, new_sha, throwaway_repo)
    assert not result.ok
    assert any("allow-list" in f.reason for f in result.blocking)


def test_scan_push_flags_new_bad_file(throwaway_repo: Path) -> None:
    old_sha = _commit(throwaway_repo, {"README.md": "hello\n"}, "old state")
    new_sha = _commit(
        throwaway_repo,
        {".env": "SEAM_PGVECTOR_DSN=postgresql://u:p@host/db\n"},
        "leaks a dotenv file",
    )
    result = scan_push(old_sha, new_sha, throwaway_repo)
    assert not result.ok
    assert any(f.path == ".env" for f in result.blocking)


def test_scan_push_catches_content_introduced_then_removed(throwaway_repo: Path) -> None:
    """A secret added in an intermediate commit and deleted before the push
    tip still gets pushed as a git object; scan_push must see it because it
    walks every new object, not just the tip tree diff."""
    old_sha = _commit(throwaway_repo, {"README.md": "hello\n"}, "old state")
    _commit(throwaway_repo, {"leaked_key.txt": "sk-ant-" + "a" * 30}, "oops, added a key")
    (throwaway_repo / "leaked_key.txt").unlink()
    _git(throwaway_repo, "add", "-A")
    new_sha = _commit(throwaway_repo, {"README.md": "hello again\n"}, "removed the key file")

    # Confirm the tip tree genuinely no longer contains the file, i.e. a
    # naive tip-diff approach would see nothing wrong here.
    tip_diff = _git(throwaway_repo, "diff", "--name-only", old_sha, new_sha)
    assert "leaked_key.txt" not in tip_diff

    result = scan_push(old_sha, new_sha, throwaway_repo)
    assert not result.ok
    assert any(f.path == "leaked_key.txt" for f in result.blocking)


def test_scan_push_new_branch_scans_full_history(throwaway_repo: Path) -> None:
    _commit(throwaway_repo, {".env": "SECRET=1\n"}, "bad first commit")
    new_sha = _commit(throwaway_repo, {"README.md": "hi\n"}, "second commit")
    result = scan_push(ZERO_SHA, new_sha, throwaway_repo)
    assert not result.ok
    assert any(f.path == ".env" for f in result.blocking)
