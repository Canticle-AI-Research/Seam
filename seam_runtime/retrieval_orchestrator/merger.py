from __future__ import annotations

import math

from .types import LegHit, RetrievalCandidate


def rank_hits(grouped_hits: list[list[LegHit]]) -> list[RetrievalCandidate]:
    """Fuse all leg hits into one deterministic ranked candidate pool."""

    merged: dict[str, RetrievalCandidate] = {}
    for hits in grouped_hits:
        for hit in hits:
            if not math.isfinite(float(hit.score)) or abs(float(hit.score)) > 1_000_000:
                raise ValueError("retrieval leg scores must be finite and bounded")
            candidate = merged.get(hit.record.id)
            if candidate is None:
                candidate = RetrievalCandidate(record=hit.record, score=0.0)
                merged[hit.record.id] = candidate
            candidate.sources[hit.leg] = max(candidate.sources.get(hit.leg, 0.0), hit.score)
            candidate.reasons.extend(f"{hit.leg}:{reason}" for reason in hit.reasons)
            if hit.leg == "graph" and hit.path and not candidate.graph_path:
                candidate.graph_path = hit.path

    for candidate in merged.values():
        overlap_bonus = 0.15 * max(len(candidate.sources) - 1, 0)
        candidate.score = sum(candidate.sources.values()) + overlap_bonus
        candidate.reasons = list(dict.fromkeys(candidate.reasons))

    return sorted(merged.values(), key=lambda item: (-item.score, item.record.id))


def merge_hits(grouped_hits: list[list[LegHit]], limit: int) -> list[RetrievalCandidate]:
    return rank_hits(grouped_hits)[:limit]
