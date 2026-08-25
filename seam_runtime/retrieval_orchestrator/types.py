from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from seam_runtime.mirl import MIRLRecord
from seam_runtime.provenance import ProvenanceChain


class QueryIntent(str, Enum):
    STRUCTURED = "structured"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"
    GRAPH = "graph"
    MIX = "mix"


@dataclass
class QueryFilters:
    ids: list[str] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    namespace: str | None = None
    scope: str | None = None
    predicate: str | None = None
    subject: str | None = None
    object_text: str | None = None

    def matches(self, record: MIRLRecord) -> bool:
        if self.ids and record.id not in self.ids:
            return False
        if self.kinds and record.kind.value not in self.kinds:
            return False
        if self.namespace and record.ns != self.namespace:
            return False
        if self.scope and record.scope != self.scope:
            return False
        if self.predicate and str(record.attrs.get("predicate", "")).lower() != self.predicate.lower():
            return False
        if self.subject and str(record.attrs.get("subject", "")).lower() != self.subject.lower():
            return False
        if self.object_text:
            value = str(record.attrs.get("object", "")).lower()
            if self.object_text.lower() not in value:
                return False
        return True

    def active(self) -> bool:
        return any(
            [
                self.ids,
                self.kinds,
                self.namespace,
                self.scope,
                self.predicate,
                self.subject,
                self.object_text,
            ]
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ids": list(self.ids),
            "kinds": list(self.kinds),
            "namespace": self.namespace,
            "scope": self.scope,
            "predicate": self.predicate,
            "subject": self.subject,
            "object_text": self.object_text,
        }


@dataclass
class RetrievalLeg:
    name: str
    limit: int
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "limit": self.limit, "rationale": self.rationale}


@dataclass
class RetrievalPlan:
    query: str
    normalized_query: str
    intent: QueryIntent
    filters: QueryFilters
    legs: list[RetrievalLeg]
    mode: str = "hybrid"
    graph_hops: int = 1
    semantic_graph_seeding: bool = False
    graph_at: str | None = None
    graph_include_history: bool = False
    lens: str = "general"
    include_raw: bool = False
    temporal_window: tuple[datetime, datetime] | None = None
    temporal_reference: datetime | None = None
    ranking_policy: str = "reciprocal-rank-fusion/2"

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "normalized_query": self.normalized_query,
            "intent": self.intent.value,
            "mode": self.mode,
            "graph_hops": self.graph_hops,
            "semantic_graph_seeding": self.semantic_graph_seeding,
            "graph_at": self.graph_at,
            "graph_include_history": self.graph_include_history,
            "lens": self.lens,
            "include_raw": self.include_raw,
            "temporal_window": (
                [value.isoformat() for value in self.temporal_window]
                if self.temporal_window is not None
                else None
            ),
            "temporal_reference": (
                self.temporal_reference.isoformat()
                if self.temporal_reference is not None
                else None
            ),
            "ranking_policy": self.ranking_policy,
            "filters": self.filters.to_dict(),
            "legs": [leg.to_dict() for leg in self.legs],
        }


@dataclass(frozen=True)
class GraphPathHop:
    """One traversed edge on the deterministic shortest path from a graph seed.

    The endpoints preserve the edge's canonical direction, which can differ
    from traversal direction. ``episode_ids`` names only episodes visible in
    the plan's graph-time view.
    """

    edge_id: str
    predicate: str
    src_id: str
    dst_id: str
    source_record_id: str | None
    episode_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "predicate": self.predicate,
            "src_id": self.src_id,
            "dst_id": self.dst_id,
            "source_record_id": self.source_record_id,
            "episode_ids": list(self.episode_ids),
        }


@dataclass
class LegHit:
    leg: str
    record: MIRLRecord
    score: float
    reasons: list[str] = field(default_factory=list)
    path: tuple[GraphPathHop, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "leg": self.leg,
            "record": self.record.to_dict(),
            "score": round(self.score, 6),
            "reasons": list(self.reasons),
            "path": [hop.to_dict() for hop in self.path],
        }


@dataclass
class RetrievalCandidate:
    record: MIRLRecord
    score: float
    sources: dict[str, float] = field(default_factory=dict)
    source_ranks: dict[str, int] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    graph_path: tuple[GraphPathHop, ...] = ()
    # The verified route back to source bytes, populated only when the caller
    # asks (``include_provenance``); resolving it costs extra store reads.
    # ``graph_path`` says HOW retrieval reached this record; ``provenance`` says
    # WHERE the record came from. Together they are the full verified chain.
    provenance: ProvenanceChain | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "record": self.record.to_dict(),
            "score": round(self.score, 6),
            "sources": {key: round(value, 6) for key, value in self.sources.items()},
            "source_ranks": dict(sorted(self.source_ranks.items())),
            "reasons": list(self.reasons),
            "graph_path": [hop.to_dict() for hop in self.graph_path],
            "provenance": (
                self.provenance.to_dict() if self.provenance is not None else None
            ),
        }


@dataclass
class RetrievalSearchResult:
    query: str
    normalized_query: str
    intent: QueryIntent
    candidates: list[RetrievalCandidate]
    trace: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "normalized_query": self.normalized_query,
            "intent": self.intent.value,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "trace": self.trace,
        }


@dataclass
class RetrievalDecisionResult:
    plan: RetrievalPlan
    selected: list[RetrievalCandidate]
    rejected: list[RetrievalCandidate]
    policy: str
    candidate_set_sha256: str
    total_candidates: int
    candidates_truncated: bool
    leg_hits: dict[str, list[LegHit]] = field(default_factory=dict)
    leg_latency_ms: dict[str, float] = field(default_factory=dict)
    total_latency_ms: float = 0.0
    # The exact normalized weights this result was ranked under. Persistence
    # needs them to re-derive `candidate.score`; without them a weighted
    # retrieval is unreplayable.
    leg_weights: dict[str, float] = field(default_factory=dict)

    @property
    def ranked(self) -> list[RetrievalCandidate]:
        return [*self.selected, *self.rejected]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_dict(),
            "policy": self.policy,
            "candidate_set_sha256": self.candidate_set_sha256,
            "selected": [candidate.to_dict() for candidate in self.selected],
            "rejected": [candidate.to_dict() for candidate in self.rejected],
            "total_candidates": self.total_candidates,
            "candidates_truncated": self.candidates_truncated,
            "leg_latency_ms": {
                name: round(value, 6) for name, value in self.leg_latency_ms.items()
            },
            "total_latency_ms": round(self.total_latency_ms, 6),
            "leg_weights": dict(sorted(self.leg_weights.items())),
        }


@dataclass
class RAGResult:
    query: str
    backend: str
    candidate_ids: list[str]
    candidates: list[dict[str, Any]]
    records: list[dict[str, Any]]
    pack: dict[str, Any]
    trace: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "backend": self.backend,
            "candidate_ids": list(self.candidate_ids),
            "candidates": list(self.candidates),
            "records": list(self.records),
            "pack": self.pack,
            "trace": self.trace,
        }


# Legacy compatibility aliases for the previous experimental stage naming.
HybridCandidate = RetrievalCandidate
HybridSearchResult = RetrievalSearchResult
