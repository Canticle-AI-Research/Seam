from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

RETRIEVAL_PLANNER = "retrieval-planner/1"
FUSION_POLICY = "sum-max-per-leg-overlap/1"
FUSION_POLICY_CONTRACT = (
    "sum(max-score-per-leg)+0.15*(distinct-legs-1);"
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
