from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

RETRIEVAL_PLANNER = "retrieval-planner/1"
FUSION_RANK_CONSTANT = 60
FUSION_MAX_LEG_RANK = 1_000_000
FUSION_POLICY = "reciprocal-rank-fusion/2"
FUSION_POLICY_CONTRACT = (
    "dedupe-per-leg=max(raw-score);"
    "rank-per-leg=sort(-raw-score,record-id);"
    "source-contribution=1/(60+rank);"
    "fused-score=sum(source-contributions);"
    "sort(-fused-score,record-id)"
)
FUSION_POLICY_FINGERPRINT = hashlib.sha256(
    FUSION_POLICY_CONTRACT.encode("utf-8")
).hexdigest()

RETRIEVAL_REASON_CODES = frozenset(
    {
        "matched_id",
        "matched_kind",
        "matched_namespace",
        "matched_scope",
        "matched_predicate",
        "matched_subject",
        "matched_object",
        "structured_score",
        "lexical_score",
        "token_hits",
        "semantic_score",
        "graph_neighbors",
        "graph_hop",
        "semantic_seed",
        "chroma_score",
    }
)


def rank_normalized_contribution(rank: int) -> float:
    """Return the fixed reciprocal-rank contribution for one retrieval leg."""

    if isinstance(rank, bool) or not isinstance(rank, int):
        raise TypeError("retrieval leg rank must be an integer")
    if not 1 <= rank <= FUSION_MAX_LEG_RANK:
        raise ValueError(
            f"retrieval leg rank must be between 1 and {FUSION_MAX_LEG_RANK}"
        )
    return 1.0 / (FUSION_RANK_CONSTANT + rank)


def contribution_rank(score: float) -> int:
    """Recover and validate the exact leg rank encoded by a contribution."""

    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise TypeError("retrieval source contribution must be numeric")
    resolved = float(score)
    if not 0.0 < resolved <= rank_normalized_contribution(1):
        raise ValueError("retrieval source contribution is outside the pinned policy")
    rank = round((1.0 / resolved) - FUSION_RANK_CONSTANT)
    if not 1 <= rank <= FUSION_MAX_LEG_RANK or not _close(
        resolved, rank_normalized_contribution(rank)
    ):
        raise ValueError("retrieval source contribution is outside the pinned policy")
    return rank


def fusion_score(source_contributions: Mapping[str, float]) -> float:
    """Recompute the pinned policy score from normalized per-leg contributions."""

    return sum(float(score) for score in source_contributions.values())


def _close(left: float, right: float) -> bool:
    return abs(left - right) <= max(1e-15, 1e-12 * max(abs(left), abs(right)))


def candidate_set_fingerprint(
    candidates: Iterable[tuple[str, float, Mapping[str, float]]],
) -> str:
    """Hash the ordered, content-free candidate score set."""

    lines = []
    for rank, (record_id, score, sources) in enumerate(candidates, start=1):
        source_text = ",".join(
            f"{name}={float(value):.17g}" for name, value in sorted(sources.items())
        )
        lines.append(f"{rank}\t{record_id}\t{float(score):.17g}\t{source_text}")
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def mirl_record_fingerprint(record: Mapping[str, Any]) -> str:
    """Hash the canonical MIRL JSON that SQLite persists."""

    payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
