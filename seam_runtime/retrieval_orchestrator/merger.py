from __future__ import annotations

import math

from seam_runtime.retrieval_policy import (
    fusion_score,
    rank_normalized_contribution,
)

from .types import LegHit, RetrievalCandidate


def rank_hits(grouped_hits: list[list[LegHit]]) -> list[RetrievalCandidate]:
    """Fuse heterogeneous leg scores through fixed reciprocal-rank normalization."""

    hits_by_leg: dict[str, dict[str, LegHit]] = {}
    reasons_by_leg_record: dict[tuple[str, str], list[str]] = {}
    for hits in grouped_hits:
        for hit in hits:
            if not math.isfinite(float(hit.score)) or abs(float(hit.score)) > 1_000_000:
                raise ValueError("retrieval leg scores must be finite and bounded")
            by_record = hits_by_leg.setdefault(hit.leg, {})
            existing = by_record.get(hit.record.id)
            if existing is None or (
                (-hit.score, _path_key(hit)) < (-existing.score, _path_key(existing))
            ):
                by_record[hit.record.id] = hit
            key = (hit.leg, hit.record.id)
            reasons_by_leg_record.setdefault(key, []).extend(hit.reasons)

    merged: dict[str, RetrievalCandidate] = {}
    for leg in sorted(hits_by_leg):
        ranked_leg = sorted(
            hits_by_leg[leg].values(),
            key=lambda hit: (-hit.score, hit.record.id),
        )
        for rank, hit in enumerate(ranked_leg, start=1):
            candidate = merged.get(hit.record.id)
            if candidate is None:
                candidate = RetrievalCandidate(record=hit.record, score=0.0)
                merged[hit.record.id] = candidate
            candidate.sources[leg] = rank_normalized_contribution(rank)
            candidate.source_ranks[leg] = rank
            candidate.reasons.extend(
                f"{leg}:{reason}"
                for reason in reasons_by_leg_record[(leg, hit.record.id)]
            )
            if leg == "graph" and hit.path and not candidate.graph_path:
                candidate.graph_path = hit.path

    for candidate in merged.values():
        candidate.score = fusion_score(candidate.sources)
        candidate.reasons = sorted(set(candidate.reasons))

    return sorted(merged.values(), key=lambda item: (-item.score, item.record.id))


def merge_hits(grouped_hits: list[list[LegHit]], limit: int) -> list[RetrievalCandidate]:
    return rank_hits(grouped_hits)[:limit]


def _path_key(hit: LegHit) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            hop.edge_id,
            hop.predicate,
            hop.src_id,
            hop.dst_id,
            hop.source_record_id or "",
            hop.episode_ids,
        )
        for hop in hit.path
    )
