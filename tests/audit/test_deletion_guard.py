"""The deletion guard must block every agent-side deletion path.

HISTORY#613 (2026-08-25): an agent deleted ``test_seam/ab_A..ab_D`` during a
disk-full event, inferring "disposable" from git-ignore status. Written rules
existed; they were ignored. ``tools/claude/deletion_guard.sh`` is the
mechanical enforcement -- a PreToolUse hook that blocks destructive Bash
commands -- and this test keeps it from silently weakening or disappearing.

The expected blocked commands below are drawn from the actual incident and
obvious variants of it. The expected pass-throughs guard against false
positives that would train operators to disable the hook.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest import mock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "tools" / "claude" / "deletion_guard.sh"


def _run_guard(command: str) -> subprocess.CompletedProcess[str]:
    payload = json.dumps({"tool_input": {"command": command}})
    return subprocess.run(
        ["bash", str(GUARD)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=30,
    )


BLOCKED = [
    # The exact incident shape.
    "rm -rf test_seam/ab_A test_seam/ab_B",
    "rm -rf /home/terrabyte/Documents/Projects/Seam/test_seam/ab_A",
    # Plain deletes.
    "rm somefile.txt",
    "cd tools && rm guard.py",
    "rm -f HISTORY.md",
    "rm -r docs/",
    "rmdir empty_dir",
    "shred secret.key",
    "unlink hardlink",
    "truncate -s 0 HISTORY.md",
    # Destructive git.
    "git clean -fd",
    "git stash drop",
    "git stash clear",
    "git branch -D feat/x",
    "git push --delete origin feat/x",
    "git filter-branch --tree-filter 'rm refs' HEAD",
    "git worktree remove Seam-tui-concept-shell",
    # find-based deletion.
    "find . -name '*.pyc' -delete",
    "find test_seam -type f -exec rm {} +",
    # Truncating redirection into the repo.
    "cat foo > HISTORY.md",
    "echo > PROJECT_STATUS.md",
    "python gen.py > docs/INDEX.md",
    # Moving repo content out of the tree.
    "mv test_seam /tmp/",
    "mv seam_runtime ../elsewhere",
]

ALLOWED = [
    # Ordinary work must pass: reads, appends, builds, git status.
    "ls -la test_seam/",
    "python -m pytest tests/audit -q",
    "git status --short",
    "git add tools/claude/deletion_guard.sh",
    "grep -rn 'rm' AGENTS.md",
    # Append redirection is fine (HISTORY is append-only).
    "echo 'append' >> /tmp/notes.txt",
    "echo 'append' >> scratch.log",
    # Redirect to /dev/null and /tmp is not repo truncation.
    "pytest -q > /dev/null 2>&1",
    "python x.py > /tmp/out.log",
    # fd duplication must not trip the redirect rule.
    "cmd 2>&1",
    # External caches: outside the repo, operator-directed cleanups of
    # non-repo paths are not this guard's concern.
    "du -sh ~/.cache",
    # mv inside the repo is a rename, not a removal.
    "mv notes.txt docs/notes.txt",
]


@pytest.mark.parametrize("command", BLOCKED)
def test_guard_blocks_deletion_commands(command: str) -> None:
    assert GUARD.exists(), "deletion_guard.sh is missing -- rebuild it from HISTORY#613"
    result = _run_guard(command)
    assert result.returncode != 0, f"guard ALLOWED a deletion: {command!r}"
    assert "SEAM deletion guard" in result.stderr


@pytest.mark.parametrize("command", ALLOWED)
def test_guard_allows_ordinary_commands(command: str) -> None:
    result = _run_guard(command)
    assert result.returncode == 0, (
        f"guard blocked ordinary work ({command!r}) -- a false positive trains "
        f"operators to disable the guard: {result.stderr}"
    )


def test_settings_json_registers_the_guard_before_the_preflight() -> None:
    """The guard must actually be wired as a PreToolUse hook, and first.

    Order matters: a deletion attempt must be blocked before any other hook
    spends time on gates, and a missing registration is how a guard silently
    disappears while its file still exists.
    """
    settings = json.loads((REPO_ROOT / ".claude" / "settings.json").read_text())
    hooks = settings["hooks"]["PreToolUse"]
    bash_hooks = [h for entry in hooks if entry.get("matcher") == "Bash" for h in entry["hooks"]]
    commands = [h["command"] for h in bash_hooks]
    guard_commands = [c for c in commands if "deletion_guard.sh" in c]
    assert guard_commands, "deletion_guard.sh is not registered in .claude/settings.json"
    assert commands.index(guard_commands[0]) == 0, "deletion guard must run first"


def test_guard_script_is_executable_and_referenced() -> None:
    assert GUARD.exists()
    mode = GUARD.stat().st_mode
    assert mode & 0o111, "deletion_guard.sh must remain executable"


def test_malformed_hook_input_fails_open_as_a_nop() -> None:
    """Bad JSON must not crash the hook or block unrelated commands."""
    result = subprocess.run(
        ["bash", str(GUARD)],
        input="not json at all",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
