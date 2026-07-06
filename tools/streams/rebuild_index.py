"""Generic per-stream index rebuilder.

For each stream, walks log.md and produces a compact index.md mapping ids to
date, hash, topics, kind/item/event/supersedes, and byte ranges. The index is
derived state — safe to regenerate any time.

History is special: its log.md is a derived mirror of root HISTORY.md and its
index.md is a derived mirror of root HISTORY_INDEX.md. Calling rebuild on the
history stream first re-syncs the mirror (root → .seam/streams/history/),
then trusts the root index.
"""
from __future__ import annotations

import hashlib
import os

from tools.streams.history_adapter import sync_history_mirror
from tools.streams.streams_lib import (
    index_path,
    list_stream_kinds,
    parse_events,
    read_log,
)


def rebuild_index(kind: str) -> dict[str, object]:
    if kind == "history":
        result = sync_history_mirror()
        return {"kind": "history", **result}
    data = read_log(kind)
    if not data:
        index_path(kind).parent.mkdir(parents=True, exist_ok=True)
        tmp = index_path(kind).with_name(index_path(kind).name + ".tmp")
        tmp.write_text(
            f"# {kind.capitalize()} Index\n\ntotal_events: 0\nlatest_id: 0\nsource: streams/{kind}/log.md\nschema: seam-stream-index/v1\n",
            encoding="utf-8",
        )
        os.replace(tmp, index_path(kind))
        return {"kind": kind, "events": 0}
    events = parse_events(data, kind)
    content_hash = (
        hashlib.sha256(b"".join(e.raw for e in events)).hexdigest()
        if events
        else ""
    )
    lines: list[str] = [
        f"# {kind.capitalize()} Index",
        "",
        f"total_events: {len(events)}",
        f"latest_id: {events[-1].id if events else 0}",
        f"source: streams/{kind}/log.md",
        "schema: seam-stream-index/v1",
    ]
    if content_hash:
        lines.append(f"content_hash: {content_hash}")
    lines.extend([
        "",
        "## entries (newest first)",
        "",
        "| id | date | kind | item | event | hash | supersedes | topics |",
        "|---|---|---|---|---|---|---|---|",
    ])
    for evt in reversed(events):
        topics = evt.fields.get("topics", "")
        topics_disp = topics if len(topics) <= 40 else topics[:37] + "..."
        lines.append(
            f"| {evt.id:03d} | {evt.date} | {evt.fields.get('kind','')} | "
            f"{evt.fields.get('item','')} | {evt.fields.get('event','')} | "
            f"{evt.hash_short} | {evt.fields.get('supersedes','')} | {topics_disp} |"
        )
    index_path(kind).parent.mkdir(parents=True, exist_ok=True)
    tmp = index_path(kind).with_name(index_path(kind).name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, index_path(kind))
    return {"kind": kind, "events": len(events)}


def rebuild_all() -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    kinds = list_stream_kinds() or ["history", "roadmap", "experience"]
    if "history" not in kinds:
        kinds.insert(0, "history")
    for kind in kinds:
        results.append(rebuild_index(kind))
    return results


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--stream", help="single stream kind; default: all")
    args = p.parse_args()
    if args.stream:
        result = rebuild_index(args.stream)
        print(result)
    else:
        for r in rebuild_all():
            print(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
