"""Generic stream-aware context pack builder.

For `--stream history`, delegates to the canonical tools.history.build_context_pack
so output is byte-equivalent to the legacy path. For other streams (roadmap,
experience, library/*), reads from .seam/streams/<kind>/log.md and returns the
latest N events filtered by topics under a token budget.

This is the H1 implementation of CONTEXT_STREAMS.md §10 point 3 (generic pack
parity for history). H3 will extend this with cross-stream filtering
(--include history,roadmap,experience), default exclusion of completed items,
and --around <event_id> cross-index walking.
"""
from __future__ import annotations

import argparse

from tools.streams.streams_lib import (
    StreamEvent,
    estimate_tokens,
    parse_events,
    read_log,
)


def _topic_filter(events: list[StreamEvent], topics: set[str]) -> list[StreamEvent]:
    if not topics:
        return events
    return [e for e in events if topics & set(e.topics_list())]


def _budgeted_latest(
    events: list[StreamEvent], latest: int | None, budget: int | None
) -> tuple[list[StreamEvent], list[StreamEvent], int]:
    pool = events if latest is None else events[-latest:]
    pool_rev = list(reversed(pool))
    included: list[StreamEvent] = []
    skipped: list[StreamEvent] = []
    used = 0
    for evt in pool_rev:
        cost = estimate_tokens(evt.raw.decode("utf-8", errors="replace"))
        if budget is not None and used + cost > budget and included:
            skipped.append(evt)
            continue
        included.append(evt)
        used += cost
    included.reverse()
    skipped.reverse()
    return included, skipped, used


def build_stream_pack(
    kind: str,
    *,
    latest: int | None = None,
    topics: set[str] | None = None,
    budget: int | None = None,
) -> dict[str, object]:
    data = read_log(kind)
    if not data:
        return {
            "stream": kind,
            "selected_ids": [],
            "included_ids": [],
            "skipped_ids": [],
            "tokens_used": 0,
            "token_budget": budget,
            "pack": "",
        }
    events = parse_events(data, kind)
    filtered = _topic_filter(events, topics or set())
    included, skipped, used = _budgeted_latest(filtered, latest, budget)
    pack_text = "\n".join(e.raw.decode("utf-8", errors="replace") for e in included)
    return {
        "stream": kind,
        "selected_ids": [e.id for e in filtered],
        "included_ids": [e.id for e in included],
        "skipped_ids": [e.id for e in skipped],
        "tokens_used": used,
        "token_budget": budget,
        "pack": pack_text,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--stream", required=True, help="stream kind (history, roadmap, experience, ...)")
    p.add_argument("--latest", type=int, default=None)
    p.add_argument("--topics", default=None, help="comma-separated topics filter")
    p.add_argument("--token-budget", type=int, default=None, dest="token_budget")
    p.add_argument("--format", choices=["pack", "json"], default="pack")
    args = p.parse_args(argv)

    if args.stream == "history":
        # Delegate to the canonical history pack so output is byte-equivalent.
        from tools.history import build_context_pack as legacy
        forwarded: list[str] = []
        if args.latest is not None:
            forwarded += ["--latest", str(args.latest)]
        if args.topics:
            forwarded += ["--topics", args.topics]
        if args.token_budget is not None:
            forwarded += ["--token-budget", str(args.token_budget)]
        if args.format == "json":
            forwarded += ["--json"]
        return legacy.main(forwarded)

    topics = {t.strip() for t in (args.topics or "").split(",") if t.strip()}
    result = build_stream_pack(
        args.stream,
        latest=args.latest,
        topics=topics,
        budget=args.token_budget,
    )
    if args.format == "json":
        import json
        print(json.dumps({k: v for k, v in result.items() if k != "pack"}, indent=2))
        print(result["pack"])
    else:
        print(result["pack"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
