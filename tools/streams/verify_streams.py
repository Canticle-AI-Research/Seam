"""Verify the Context Streams substrate.

Checks:
  - Each stream's log.md is parseable; ids are strictly increasing.
  - History stream mirror matches root HISTORY.md / HISTORY_INDEX.md byte-for-byte.
  - Each stream's index.md exists and references the current log totals.
  - .seam/cross_index.md exists and matches a fresh rebuild for the listed totals.
  - Each stream's content_hash in index.md matches the computed hash of log.md
    events (backward-compatible: does not fail if content_hash field is absent).
  - The future-ideas/plans/executed roadmap lifecycle has valid linear
    supersession, promotion references, and a fresh derived state view.

Exits non-zero on any failure.
"""
from __future__ import annotations

import hashlib
import re
import sys

from tools.streams.history_adapter import verify_history_mirror
from tools.streams.rebuild_cross_index import collect_all_events
from tools.streams.roadmap_lifecycle import verify_workflow
from tools.streams.streams_lib import (
    CROSS_INDEX_PATH,
    STREAMS_ROOT,
    index_path,
    list_stream_kinds,
    parse_events,
    read_log,
)


def verify_all() -> list[str]:
    errors: list[str] = []

    if not STREAMS_ROOT.exists():
        errors.append("streams root missing: .seam/streams (run seed)")
        return errors

    kinds = list_stream_kinds()
    if "history" not in kinds:
        errors.append("history stream missing from .seam/streams/")

    errors.extend(verify_history_mirror())
    errors.extend(verify_workflow())

    for kind in kinds:
        data = read_log(kind)
        if data:
            try:
                events = parse_events(data, kind)
            except ValueError as exc:
                errors.append(f"[{kind}] log.md parse error: {exc}")
                continue
        else:
            events = []
        idx = index_path(kind)
        if not idx.exists():
            errors.append(f"[{kind}] index.md missing; run tools.streams.rebuild_index")
            continue
        index_text = idx.read_text(encoding="utf-8", errors="replace")
        expected_total = f"total_events: {len(events)}" if kind != "history" else None
        if expected_total and expected_total not in index_text:
            errors.append(
                f"[{kind}] index.md disagrees with log.md event count "
                f"(expected '{expected_total}')"
            )

        # Content hash verification (backward-compatible: skip if field absent)
        if events and kind != "history":
            normalized = b"".join(e.raw for e in events)
            computed_hash = hashlib.sha256(normalized).hexdigest()
            expected_match = re.search(
                r"^content_hash:\s*([0-9a-f]{64})", index_text, re.MULTILINE
            )
            if expected_match:
                expected_hash = expected_match.group(1)
                if expected_hash != computed_hash:
                    errors.append(
                        f"[{kind}] content_hash mismatch: "
                        f"index={expected_hash[:16]}... "
                        f"computed={computed_hash[:16]}..."
                    )

    if not CROSS_INDEX_PATH.exists():
        errors.append("cross_index.md missing; run tools.streams.rebuild_cross_index")
    else:
        cross_text = CROSS_INDEX_PATH.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"^total_events:\s*(\d+)", cross_text, re.MULTILINE)
        actual_total = len(collect_all_events())
        if match is None:
            errors.append(
                f"cross_index.md is stale: total_events header missing or unparseable; "
                f"streams report {actual_total}; run tools.streams.rebuild_cross_index"
            )
        else:
            recorded_total = int(match.group(1))
            if recorded_total != actual_total:
                errors.append(
                    f"cross_index.md is stale: total_events={recorded_total} but "
                    f"streams report {actual_total}; run tools.streams.rebuild_cross_index"
                )
    return errors


def main() -> int:
    errors = verify_all()
    if errors:
        for err in errors:
            print(f"streams: {err}", file=sys.stderr)
        return 1
    print("streams OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
