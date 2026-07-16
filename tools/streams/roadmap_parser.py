"""ROADMAP.md → roadmap stream bootstrap parser.

Walks the operator-authored ROADMAP.md and emits one synthetic status-change
event per `<!-- seam:item ... -->` marker block. Authored-canonical reconcile
model: ROADMAP.md stays the source of truth for prose; the roadmap stream
records structural state transitions over time, joinable across other streams
via cross_index.md.

This is one-shot bootstrap; future status changes append events at runtime.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from tools.streams.streams_lib import (
    REPO_ROOT,
    estimate_tokens,
    format_event,
    write_log,
)

ROADMAP_PATH = REPO_ROOT / "ROADMAP.md"

MARKER_RE = re.compile(
    r"<!--\s*seam:item\s*\n(?P<body>.*?)\n\s*-->",
    re.DOTALL,
)


@dataclass
class RoadmapItem:
    fields: dict[str, str]
    source_line: int

    @property
    def item_id(self) -> str:
        return self.fields.get("id", "")

    @property
    def status(self) -> str:
        return self.fields.get("status", "unknown")

    @property
    def status_since(self) -> str:
        return self.fields.get("status-since", "")

    @property
    def status_by(self) -> str:
        return self.fields.get("status-by", "")

    @property
    def topics(self) -> str:
        return self.fields.get("topics", "")


def parse_roadmap_markers(text: str) -> list[RoadmapItem]:
    items: list[RoadmapItem] = []
    for match in MARKER_RE.finditer(text):
        block = match.group("body")
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            fields[k.strip()] = v.strip()
        if not fields.get("id"):
            continue
        line_no = text.count("\n", 0, match.start()) + 1
        items.append(RoadmapItem(fields=fields, source_line=line_no))
    return items


def items_to_events(items: list[RoadmapItem]) -> list[dict[str, object]]:
    """Sort items into a deterministic bootstrap order and shape events.

    Order: (status-since asc with empty last, then source order). Events get
    sequential ids starting at 1.
    """
    def sort_key(it: RoadmapItem) -> tuple[str, int]:
        return (it.status_since or "9999-99-99", it.source_line)

    ordered = sorted(items, key=sort_key)
    events: list[dict[str, object]] = []
    for it in ordered:
        date = it.status_since or "2026-05-15"
        date_iso = date if "T" in date else f"{date}T00:00:00Z"
        topics = it.topics or "roadmap"
        caused_by = it.status_by or "none"
        body = (
            f"Bootstrap status capture for {it.item_id}: status={it.status}"
            + (f", status-since={it.status_since}" if it.status_since else "")
            + (f", caused-by={it.status_by}" if it.status_by else "")
            + ". Sourced from ROADMAP.md seam:item marker."
        )
        events.append({
            "date": date_iso,
            "agent": "bootstrap",
            "fields": {
                "kind": "status-change",
                "item": it.item_id,
                "event": "bootstrap",
                "from": "(initial)",
                "to": it.status,
                "caused-by": caused_by,
                "supersedes": "none",
                "refs": f"ROADMAP.md:{it.source_line}",
                "topics": topics,
                "tokens": str(estimate_tokens(body)),
            },
            "body": body,
        })
    return events


def render_state_md(items: list[RoadmapItem]) -> str:
    """Compact agent-facing state view of the roadmap stream.

    Lists items grouped by status. Designed so agents reading roadmap state at
    session start can skip ROADMAP.md prose entirely and pull only the active
    set into context.
    """
    by_status: dict[str, list[RoadmapItem]] = {}
    for it in items:
        by_status.setdefault(it.status, []).append(it)
    order = ["now", "in-progress", "planned", "later", "deferred", "done", "abandoned"]
    seen_statuses = set(by_status.keys())
    ordered_statuses = [s for s in order if s in seen_statuses] + sorted(seen_statuses - set(order))

    lines: list[str] = [
        "# Roadmap State (derived)",
        "",
        "Source: ROADMAP.md (authored-canonical).",
        "Regenerate: `python -m tools.streams.roadmap_parser --emit-state`.",
        "",
    ]
    for status in ordered_statuses:
        bucket = by_status[status]
        lines.append(f"## {status} ({len(bucket)})")
        lines.append("")
        for it in sorted(bucket, key=lambda x: x.item_id):
            since = it.status_since or "?"
            by = it.status_by or "?"
            topics = it.topics or "-"
            lines.append(
                f"- `{it.item_id}` — since {since} via {by} — topics: {topics}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_roadmap_stream(events: list[dict[str, object]]) -> Path:
    """Render events sequentially and write to .seam/streams/roadmap/log.md."""
    blocks: list[str] = []
    for idx, evt in enumerate(events, start=1):
        block = format_event(
            kind="roadmap",
            id=idx,
            date=evt["date"],
            agent=evt["agent"],
            fields=evt["fields"],
            body=evt["body"],
        )
        blocks.append(block)
    data = "\n".join(blocks).encode("utf-8")
    write_log("roadmap", data)
    return Path(".seam/streams/roadmap/log.md")


def write_roadmap_state(items: list[RoadmapItem]) -> Path:
    from tools.streams.streams_lib import STREAMS_ROOT
    state_path = STREAMS_ROOT / "roadmap" / "state.md"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(render_state_md(items), encoding="utf-8")
    return state_path


def bootstrap_roadmap_stream() -> dict[str, object]:
    if not ROADMAP_PATH.exists():
        return {"status": "skipped", "reason": "ROADMAP.md missing"}
    text = ROADMAP_PATH.read_text(encoding="utf-8")
    items = parse_roadmap_markers(text)
    events = items_to_events(items)
    write_roadmap_stream(events)
    state_path = write_roadmap_state(items)
    return {
        "status": "ok",
        "items": len(items),
        "events": len(events),
        "state_path": str(state_path),
    }


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--emit-state", action="store_true", help="Only rewrite state.md (skip log.md)")
    args = parser.parse_args()
    text = ROADMAP_PATH.read_text(encoding="utf-8")
    items = parse_roadmap_markers(text)
    if args.emit_state:
        state_path = write_roadmap_state(items)
        print(f"roadmap state.md rewritten ({len(items)} items): {state_path}")
        return 0
    result = bootstrap_roadmap_stream()
    print(f"roadmap stream bootstrapped: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
