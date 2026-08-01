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

# Weighted reciprocal-rank fusion.
#
# Plain RRF sums one unweighted 1/(k+rank) vote per leg, which is only sound
# when the legs are INDEPENDENT retrievers. HISTORY#505 measured that they are
# not: on LoCoMo the graph leg duplicated 87.43% of what SQL and vector already
# returned, so its "vote" is an echo rather than corroboration. The effect is
# that leg count outranks relevance -- a record ranked ~20th in all three legs
# (3/80 = 0.0375) beats a record ranked 1st in vector alone (1/61 = 0.0164) --
# and single-leg records made up only 1.63% of selections.
#
# This policy keeps the /2 contract exactly, but scales each leg's contribution
# by a weight. All weights default to 1.0, which reproduces /2 bit for bit, so
# the policy is inert until a weight is deliberately changed.
FUSION_POLICY_WEIGHTED = "weighted-reciprocal-rank-fusion/1"
FUSION_DEFAULT_LEG_WEIGHT = 1.0
FUSION_POLICY_WEIGHTED_CONTRACT = (
    "dedupe-per-leg=max(raw-score);"
    "rank-per-leg=sort(-raw-score,record-id);"
    "source-contribution=weight[leg]*1/(60+rank);"
    "fused-score=sum(source-contributions);"
    "sort(-fused-score,record-id)"
)
FUSION_POLICY_WEIGHTED_FINGERPRINT = hashlib.sha256(
    FUSION_POLICY_WEIGHTED_CONTRACT.encode("utf-8")
).hexdigest()


def normalize_leg_weights(
    weights: Mapping[str, float] | None,
) -> dict[str, float]:
    """Validate per-leg fusion weights.

    A weight of 0.0 disables a leg's contribution to ranking without removing it
    from the trace, which is what makes an honest leg ablation possible.
    """

    if not weights:
        return {}
    resolved: dict[str, float] = {}
    for leg, weight in weights.items():
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise TypeError(f"fusion weight for {leg!r} must be numeric")
        value = float(weight)
        if not 0.0 <= value <= 1_000.0:
            raise ValueError(
                f"fusion weight for {leg!r} must be within [0.0, 1000.0]"
            )
        resolved[str(leg)] = value
    return resolved


def weighted_fusion_score(
    source_contributions: Mapping[str, float],
    weights: Mapping[str, float] | None = None,
) -> float:
    """Weighted sum of per-leg reciprocal-rank contributions."""

    resolved = normalize_leg_weights(weights)
    return sum(
        float(score) * resolved.get(leg, FUSION_DEFAULT_LEG_WEIGHT)
        for leg, score in source_contributions.items()
    )

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
        "graph_node_semantic",
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
