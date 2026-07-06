"""Regenerate HISTORY_INDEX.md from HISTORY.md.

The index is compact by design so startup context stays small.
"""
from __future__ import annotations

import sys
from pathlib import Path

from tools.history.history_lib import (
    # Not read as bare names here (call sites use the live
    # history_lib.HISTORY_PATH/history_lib.INDEX_PATH so test monkeypatching
    # of history_lib takes effect) -- re-exported only so
    # test_history_tools.py's _MultiPatch can also patch this module's own
    # attribute of the same name.
    HISTORY_PATH,  # noqa: F401
    INDEX_PATH,  # noqa: F401
    Entry,
    parse_entries,
    read_history_bytes,
    resolve_supersedes_chain,
)


def _status_counts(entries: list[Entry]) -> dict[str, int]:
    out: dict[str, int] = {}
    for e in entries:
        out[e.status] = out.get(e.status, 0) + 1
    return out


def build_index_text(entries: list[Entry]) -> str:
    total_tokens = sum(e.tokens for e in entries)
    latest_id = entries[-1].id if entries else 0
    status_counts = _status_counts(entries)

    out: list[str] = []
    out.append("# History Index")
    out.append("")
    out.append(f"total_entries: {len(entries)}")
    out.append(f"total_tokens: ~{total_tokens}")
    out.append(f"latest_id: {latest_id:03d}" if entries else "latest_id: none")
    out.append("source: HISTORY.md")
    out.append("schema: v1")
    out.append("compact: true")
    out.append("")
    out.append("## entries (newest first)")
    out.append("")
    out.append("| id | date | status | hash | topics | supersedes |")
    out.append("|---|---|---|---|---|---|")

    for e in reversed(entries):
        date = e.date[:10]
        topics_str = ",".join(e.topics[:4])
        if len(e.topics) > 4:
            topics_str += ",+"
        row = (
            f"| {e.id:03d} | {date} | {e.status} | {e.hash_short} | "
            f"{topics_str} | {e.supersedes} |"
        )
        out.append(row)

    out.append("")
    out.append("## topic index (latest ids, max 5)")
    out.append("")
    topic_map: dict[str, list[int]] = {}
    for e in entries:
        for t in e.topics:
            topic_map.setdefault(t, []).append(e.id)
    for topic in sorted(topic_map):
        ids = sorted(topic_map[topic], reverse=True)
        latest = ", ".join(f"#{i:03d}" for i in ids[:5])
        out.append(f"- {topic}: count={len(ids)} latest={latest}")

    out.append("")
    out.append("## status rollup")
    out.append("")
    rollup = resolve_supersedes_chain(entries)
    out.append(f"- roots: {len(rollup)}")
    for st in sorted(status_counts):
        out.append(f"- {st}: {status_counts[st]}")
    out.append("")
    return "\n".join(out)


def rebuild(history_path: Path | None = None, index_path: Path | None = None) -> int:
    from tools.history import history_lib

    if history_path is None:
        history_path = history_lib.HISTORY_PATH
    if index_path is None:
        index_path = history_lib.INDEX_PATH

    data = read_history_bytes(history_path)
    if not data:
        index_path.write_text(
            (
                "# History Index\n\n"
                "total_entries: 0\n"
                "total_tokens: ~0\n"
                "latest_id: none\n"
                "source: HISTORY.md\n"
                "schema: v1\n"
                "compact: true\n"
            ),
            encoding="utf-8",
        )
        return 0

    entries = parse_entries(data)
    index_path.write_text(build_index_text(entries), encoding="utf-8")
    return len(entries)


if __name__ == "__main__":
    n = rebuild()
    print(f"Rebuilt HISTORY_INDEX.md - {n} entries")
    sys.exit(0)
