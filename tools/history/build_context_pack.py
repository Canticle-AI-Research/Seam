"""Build a small task-specific history pack without reading all history into context."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from tools.history.history_lib import HISTORY_PATH, Entry, parse_entries, read_history_bytes
from tools.history.verify_routing import MANIFEST_PATH, load_manifest, verify_routing


@dataclass(frozen=True)
class ContextPack:
    """Selected history entries plus routing metadata."""

    selected_ids: list[int]
    included_ids: list[int]
    skipped_ids: list[int]
    tokens_used: int
    token_budget: int
    pack: str

    def as_dict(self) -> dict:
        return {
            "selected_ids": [f"{i:03d}" for i in self.selected_ids],
            "included_ids": [f"{i:03d}" for i in self.included_ids],
            "skipped_ids": [f"{i:03d}" for i in self.skipped_ids],
            "tokens_used": self.tokens_used,
            "token_budget": self.token_budget,
            "pack": self.pack,
        }


def _parse_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    out: list[int] = []
    for item in raw.split(","):
        item = item.strip().lstrip("#")
        if not item:
            continue
        out.append(int(item))
    return out


def _topic_set(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def _route_criteria(route_id: str | None, manifest_path: Path) -> tuple[set[str], list[str]]:
    if not route_id:
        return set(), []
    ok, errors = verify_routing(manifest_path)
    if not ok:
        joined = "; ".join(errors)
        raise ValueError(f"routing manifest invalid: {joined}")
    manifest = load_manifest(manifest_path)
    routes = {route["id"]: route for route in manifest["routes"]}
    route = routes.get(route_id)
    if route is None:
        raise ValueError(f"route {route_id!r} not found")
    if route["status"] != "active":
        target = route.get("moved_to")
        suffix = f"; moved_to={target}" if target else ""
        raise ValueError(f"route {route_id!r} is not active{suffix}")
    topics = set(route.get("match_topics", []))
    refs = list(route.get("match_refs", []))
    return topics, refs


def _children_by_parent(entries: list[Entry]) -> dict[int, list[int]]:
    out: dict[int, list[int]] = {}
    for e in entries:
        if e.supersedes == "none":
            continue
        try:
            parent = int(e.supersedes.lstrip("#"))
        except ValueError:
            continue
        out.setdefault(parent, []).append(e.id)
    return out


def _add_chain(entry_id: int, by_id: dict[int, Entry], selected: set[int]) -> None:
    current = by_id.get(entry_id)
    while current is not None and current.supersedes != "none":
        try:
            parent_id = int(current.supersedes.lstrip("#"))
        except ValueError:
            return
        if parent_id in selected:
            return
        selected.add(parent_id)
        current = by_id.get(parent_id)


def _add_forward_chain(entry_id: int, children: dict[int, list[int]], selected: set[int]) -> None:
    current = entry_id
    while current in children and children[current]:
        next_id = max(children[current])
        if next_id in selected:
            return
        selected.add(next_id)
        current = next_id


def build_context_pack(
    entries: list[Entry],
    *,
    latest: int = 3,
    topics: set[str] | None = None,
    explicit_ids: list[int] | None = None,
    refs_pattern: str | None = None,
    refs_patterns: list[str] | None = None,
    topic_limit: int = 5,
    include_chain: bool = True,
    token_budget: int = 1800,
) -> ContextPack:
    """Select a compact set of entries for the next agent context."""
    if topics is None:
        topics = set()
    if explicit_ids is None:
        explicit_ids = []

    by_id = {e.id: e for e in entries}
    selected: set[int] = set()

    if latest > 0:
        selected.update(e.id for e in entries[-latest:])

    for entry_id in explicit_ids:
        if entry_id not in by_id:
            raise ValueError(f"Entry #{entry_id:03d} not found")
        selected.add(entry_id)

    if topics:
        counts = {topic: 0 for topic in topics}
        for e in reversed(entries):
            matched = topics.intersection(e.topics)
            if not matched:
                continue
            if any(counts[t] < topic_limit for t in matched):
                selected.add(e.id)
                for topic in matched:
                    counts[topic] += 1
            if all(count >= topic_limit for count in counts.values()):
                break

    all_ref_patterns = []
    if refs_pattern:
        all_ref_patterns.append(refs_pattern)
    if refs_patterns:
        all_ref_patterns.extend(refs_patterns)

    for pattern in all_ref_patterns:
        rx = re.compile(re.escape(pattern), re.IGNORECASE)
        for e in reversed(entries):
            if rx.search(e.refs) or rx.search(e.body):
                selected.add(e.id)

    if include_chain:
        children = _children_by_parent(entries)
        for entry_id in list(selected):
            _add_chain(entry_id, by_id, selected)
            _add_forward_chain(entry_id, children, selected)

    selected_ids = sorted(selected, reverse=True)
    included: list[int] = []
    skipped: list[int] = []
    chunks: list[str] = []
    tokens_used = 0
    for entry_id in selected_ids:
        entry = by_id[entry_id]
        if tokens_used + entry.tokens > token_budget:
            skipped.append(entry_id)
            continue
        included.append(entry_id)
        chunks.append(entry.raw.decode("utf-8", errors="replace").strip())
        tokens_used += entry.tokens

    pack = "\n\n".join(chunks)
    return ContextPack(
        selected_ids=selected_ids,
        included_ids=included,
        skipped_ids=skipped,
        tokens_used=tokens_used,
        token_budget=token_budget,
        pack=pack,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build a compact HISTORY.md context pack.")
    p.add_argument("--topics", default="", help="comma-separated topic tags")
    p.add_argument("--route", default=None, help="classification route from routing_manifest.json")
    p.add_argument("--routing-manifest", type=Path, default=MANIFEST_PATH)
    p.add_argument("--entries", default="", help="comma-separated explicit entry ids")
    p.add_argument("--refs", default=None, help="regex matched against refs/body")
    p.add_argument("--latest", type=int, default=3, help="latest entries to include")
    p.add_argument("--topic-limit", type=int, default=5, help="max entries per topic")
    p.add_argument("--token-budget", type=int, default=1800)
    p.add_argument("--no-chain", action="store_true", help="do not include supersedes chains")
    p.add_argument("--json", action="store_true", help="emit JSON payload instead of pack text")
    p.add_argument("--history", type=Path, default=HISTORY_PATH)
    args = p.parse_args(argv)

    data = read_history_bytes(args.history)
    entries = parse_entries(data) if data else []
    try:
        route_topics, route_refs = _route_criteria(args.route, args.routing_manifest)
        topics = _topic_set(args.topics).union(route_topics)
        pack = build_context_pack(
            entries,
            latest=args.latest,
            topics=topics,
            explicit_ids=_parse_ids(args.entries),
            refs_pattern=args.refs,
            refs_patterns=route_refs,
            topic_limit=args.topic_limit,
            include_chain=not args.no_chain,
            token_budget=args.token_budget,
        )
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(pack.as_dict(), indent=2))
    else:
        print(pack.pack)
        if pack.skipped_ids:
            skipped = ", ".join(f"#{i:03d}" for i in pack.skipped_ids)
            print(f"\n[context-pack skipped over budget: {skipped}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
