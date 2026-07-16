"""Append a new entry to HISTORY.md and regenerate HISTORY_INDEX.md.

Usage:
    python -m tools.history.new_entry \\
        --agent claude-sonnet-4-6 \\
        --status done \\
        --topics dashboard,tui \\
        --commits 8f2a6bb \\
        --refs ROADMAP.md#track-a0 \\
        --body "Entry body text..."

Or with body from stdin:
    echo "body text" | python -m tools.history.new_entry --agent ... --status ... --topics ...
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
import threading

from tools.history.history_lib import (
    HISTORY_PATH,
    INDEX_PATH,
    estimate_tokens,
    format_entry,
    next_entry_id,
    parse_entries,
    read_history_bytes,
)
from tools.history.rebuild_index import rebuild

_PROCESS_LOCK = threading.Lock()


def _acquire_history_lock():
    """Acquire an exclusive advisory lock for HISTORY.md/HISTORY_INDEX.md updates.

    Returns a (lock_fd, release_fn) pair. Callers must invoke release_fn in a
    ``finally`` block.
    """
    git_dir = INDEX_PATH.parent / ".git"
    lock_path = git_dir / "seam-history.lock" if git_dir.is_dir() else INDEX_PATH.with_name(f"{INDEX_PATH.name}.lock")
    fd = -1
    try:
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)

            def _release():
                try:
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                finally:
                    os.close(fd)

        else:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_EX)

            def _release():
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                finally:
                    os.close(fd)

        return fd, _release
    except Exception:
        if fd >= 0:
            os.close(fd)
        raise


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Append a history entry.")
    p.add_argument("--agent", required=True)
    p.add_argument("--status", required=True)
    p.add_argument("--topics", required=True, help="comma-separated tags")
    p.add_argument("--commits", default="none")
    p.add_argument("--refs", default="none")
    p.add_argument("--supersedes", default="none")
    p.add_argument("--date", default=None, help="ISO 8601; defaults to now UTC")
    p.add_argument("--body", default=None, help="body text; if omitted, read stdin")
    args = p.parse_args(argv)

    body = args.body if args.body is not None else sys.stdin.read()
    body = body.strip()
    if not body:
        print("ERROR: body is empty", file=sys.stderr)
        return 2

    date = args.date or _now_iso()
    topics = [t.strip() for t in args.topics.split(",") if t.strip()]
    tokens = estimate_tokens(body)

    _PROCESS_LOCK.acquire()
    unlock = None
    try:
        lock_fd, unlock = _acquire_history_lock()
        existing = read_history_bytes()
        entries = parse_entries(existing) if existing else []
        new_id = next_entry_id(entries)

        # Normalize supersedes format: accept "042" or "#042" → store as "042"
        supersedes = args.supersedes
        if supersedes != "none":
            supersedes = supersedes.lstrip("#")
            try:
                supersedes_id = int(supersedes)
            except ValueError:
                print("ERROR: --supersedes must be an entry id or 'none'", file=sys.stderr)
                return 2
            if supersedes_id not in {e.id for e in entries}:
                print(
                    f"ERROR: --supersedes #{supersedes_id:03d} not found in HISTORY.md "
                    f"(highest existing id is #{max((e.id for e in entries), default=0):03d})",
                    file=sys.stderr,
                )
                return 2

        entry_text = format_entry(
            id=new_id,
            date=date,
            agent=args.agent,
            status=args.status,
            topics=topics,
            commits=args.commits,
            refs=args.refs,
            supersedes=supersedes,
            tokens=tokens,
            body=body,
        )

        # Append with a blank line separator if file is non-empty
        with open(HISTORY_PATH, "ab") as f:
            if existing and not existing.endswith(b"\n\n"):
                if existing.endswith(b"\n"):
                    f.write(b"\n")
                else:
                    f.write(b"\n\n")
            f.write(entry_text.encode("utf-8"))

        n = rebuild()
        print(f"Appended #{new_id:03d}. HISTORY.md now has {n} entries.")
        return 0
    finally:
        try:
            if unlock is not None:
                unlock()
        finally:
            _PROCESS_LOCK.release()


if __name__ == "__main__":
    sys.exit(main())
