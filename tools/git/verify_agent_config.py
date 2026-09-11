"""Keep agent state local; permit only the portable SEAM memory pin in Git."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

PIN_PATH = ".claude/settings.json"
PIN = {"autoMemoryDirectory": "~/.claude/memory-shared/seam"}
LOCAL_DIRS = {".claude", ".opencode", ".agents"}


def _unique_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate setting key")
        result[key] = value
    return result


def validate_pin(content: bytes, mode: str = "100644") -> bool:
    """Reject extra settings, duplicate keys, alternate destinations and links."""
    if mode != "100644" or len(content) > 1024:
        return False
    try:
        return json.loads(content, object_pairs_hook=_unique_keys) == PIN
    except (ValueError, UnicodeError):
        return False


def _valid_worktree_pin(path: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        with path.open("rb") as handle:
            return validate_pin(handle.read(1025))
    except OSError:
        return False


def verify(repo: Path, *, staged: bool = False) -> list[str]:
    """Inspect tracked paths and the exact staged blobs at the commit boundary."""
    entries = subprocess.check_output(
        ["git", "ls-files", "--stage", "-z"], cwd=repo
    ).split(b"\0")
    changed = set(subprocess.check_output(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z"],
        cwd=repo,
    ).decode("utf-8", errors="surrogateescape").split("\0"))
    problems = []
    saw_pin = False
    for entry in filter(None, entries):
        metadata, raw_path = entry.split(b"\t", 1)
        mode, oid, stage = metadata.decode().split()
        path = raw_path.decode("utf-8", errors="surrogateescape")
        if path == PIN_PATH:
            saw_pin = True
            if stage != "0":
                problems.append(f"{path}: unresolved index entry")
                continue
            valid = False
            try:
                if mode == "100644":
                    if staged:
                        size = int(subprocess.check_output(
                            ["git", "cat-file", "-s", oid], cwd=repo
                        ))
                        if size <= 1024:
                            valid = validate_pin(subprocess.check_output(
                                ["git", "cat-file", "blob", oid], cwd=repo
                            ))
                    else:
                        valid = _valid_worktree_pin(repo / path)
            except (OSError, subprocess.CalledProcessError):
                valid = False
            if not valid:
                problems.append(f"{path}: only the fixed autoMemoryDirectory pin is allowed")
        elif ".claude" in {part.casefold() for part in Path(path).parts} or (path in changed and (
            any(part in LOCAL_DIRS for part in Path(path).parts) or path in {
                "opencode.json", "opencode.jsonc"
            }
        )):
            problems.append(f"{path}: agent-local state must not be tracked")
    if not saw_pin:
        path = repo / PIN_PATH
        if staged or not _valid_worktree_pin(path):
            problems.append(f"{PIN_PATH}: portable memory pin is missing")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true")
    args = parser.parse_args()
    repo = Path(subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True
    ).strip())
    problems = verify(repo, staged=args.staged)
    for problem in problems:
        print(problem)
    if not problems:
        print("Agent configuration scope OK")
    return bool(problems)


if __name__ == "__main__":
    raise SystemExit(main())
