from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Callable

from seam_runtime.knowledge_graph import CURRENT_EXCLUDED_STATUSES
from seam_runtime.pack import pack_records
from seam_runtime.provenance import resolve_provenance_many
from seam_runtime.retrieval_policy import (
    FUSION_POLICY,
    FUSION_POLICY_WEIGHTED,
    FUSION_RANK_CONSTANT,
    candidate_set_fingerprint,
)
from seam_runtime.runtime import SeamRuntime

from .adapters import (
    ChromaSemanticAdapter,
    GraphNodeSemanticAdapter,
    LegacyWeightedAdapter,
    SeamVectorSearchAdapter,
    SemanticAdapter,
    SQLAdapter,
    SQLiteGraphAdapter,
    SQLiteIRAdapter,
    SQLiteTemporalAdapter,
)
from .merger import rank_hits, rank_legacy_weighted_hits
from .planner import build_plan
from .types import (
    RAGResult,
    RetrievalDecisionResult,
    RetrievalPlan,
    RetrievalSearchResult,
)

SEARCH_TRACE_SCHEMA = "seam-retrieval-search-trace/1"
_SEARCH_TRACE_ITEM_LIMIT = 128


class RetrievalOrchestrator:
    def __init__(
        self,
        runtime: SeamRuntime,
        sql_adapter: SQLAdapter | None = None,
        semantic_adapter: SemanticAdapter | None = None,
        semantic_backend: str = "seam",
        chroma_path: str = ".seam_chroma",
        chroma_collection: str = "seam_hybrid",
    ) -> None:
        self.runtime = runtime
        self.semantic_backend = semantic_backend
        self.sql_adapter = sql_adapter or SQLiteIRAdapter(runtime.store)
        self.graph_adapter = SQLiteGraphAdapter(runtime.store)
        self.temporal_adapter = SQLiteTemporalAdapter(runtime.store)
        self.legacy_weighted_adapter = LegacyWeightedAdapter(
            runtime.store, runtime.vector_adapter
        )
        self.graph_node_adapter = GraphNodeSemanticAdapter(
            runtime.store, runtime.embedding_model
        )
        if semantic_adapter is not None:
            self.semantic_adapter = semantic_adapter
        elif semantic_backend == "chroma":
            self.semantic_adapter = ChromaSemanticAdapter(
                runtime.store,
                runtime.embedding_model,
                persist_directory=chroma_path,
                collection_name=chroma_collection,
            )
        else:
            self.semantic_adapter = SeamVectorSearchAdapter(runtime.store, runtime.vector_adapter)
        if isinstance(self.semantic_adapter, ChromaSemanticAdapter):
            runtime.register_derived_delete_hook(
                self.semantic_adapter.delete_records
            )

    def plan(
        self,
        query: str,
        scope: str | None = None,
        budget: int = 5,
        mode: str = "hybrid",
        *,
        namespace: str | None = None,
        graph_hops: int = 1,
        semantic_graph_seeding: bool = False,
        graph_at: str | None = None,
        graph_include_history: bool = False,
        lens: str = "general",
        include_raw: bool = False,
        temporal_window: tuple[datetime, datetime] | None = None,
        temporal_reference: datetime | None = None,
        candidate_budget: int | None = None,
        ranking_policy: str = "reciprocal-rank-fusion/2",
    ) -> RetrievalPlan:
        return build_plan(
            query=query,
            scope=scope,
            budget=candidate_budget if candidate_budget is not None else budget,
            mode=mode,
            namespace=namespace,
            graph_hops=graph_hops,
            semantic_graph_seeding=semantic_graph_seeding,
            graph_at=graph_at,
            graph_include_history=graph_include_history,
            lens=lens,
            include_raw=include_raw,
            temporal_window=temporal_window,
            temporal_reference=temporal_reference,
            ranking_policy=ranking_policy,
        )

    def decide(
        self,
        query: str,
        scope: str | None = None,
        budget: int = 5,
        mode: str = "hybrid",
        *,
        namespace: str | None = None,
        graph_hops: int = 1,
        semantic_graph_seeding: bool = False,
        graph_at: str | None = None,
        graph_include_history: bool = False,
        candidate_trace_limit: int = 128,
        lens: str = "general",
        include_raw: bool = False,
        temporal_window: tuple[datetime, datetime] | None = None,
        temporal_reference: datetime | None = None,
        flags=None,
        ranking_policy: str = "reciprocal-rank-fusion/2",
    ) -> RetrievalDecisionResult:
        if isinstance(candidate_trace_limit, bool) or not isinstance(
            candidate_trace_limit, int
        ):
            raise TypeError("candidate_trace_limit must be an integer")
        if candidate_trace_limit < budget:
            raise ValueError("candidate_trace_limit cannot be smaller than budget")
        if candidate_trace_limit > 128:
            raise ValueError("candidate_trace_limit cannot exceed 128")
        resolved_flags = (
            flags if flags is not None else self.runtime._retrieval_flags_cached()
        )
        leg_weights = dict(getattr(resolved_flags, "fusion_leg_weights", ()) or ())
        (
            plan,
            leg_hits,
            leg_latency_ms,
            total_latency_ms,
            ranked,
            _graph_skipped_reason,
        ) = self._execute(
            query=query,
            scope=scope,
            budget=budget,
            mode=mode,
            namespace=namespace,
            graph_hops=graph_hops,
            semantic_graph_seeding=semantic_graph_seeding,
            graph_at=graph_at,
            graph_include_history=graph_include_history,
            lens=lens,
            include_raw=include_raw,
            temporal_window=temporal_window,
            temporal_reference=temporal_reference,
            flags=resolved_flags,
            ranking_policy=ranking_policy,
            candidate_budget=(
                int(resolved_flags.search_top_k)
                if resolved_flags.search_top_k
                else budget
            ),
        )
        retained = ranked[:candidate_trace_limit]
        return RetrievalDecisionResult(
            plan=plan,
            selected=retained[:budget],
            rejected=retained[budget:],
            # Same provenance rule as the search trace: a weighted run must not
            # report the unweighted policy id.
            policy=(
                FUSION_POLICY_WEIGHTED
                if leg_weights and ranking_policy == FUSION_POLICY
                else ranking_policy
            ),
            candidate_set_sha256=candidate_set_fingerprint(
                (candidate.record.id, candidate.score, candidate.sources)
                for candidate in ranked
            ),
            total_candidates=len(ranked),
            candidates_truncated=len(ranked) > len(retained),
            leg_hits=leg_hits,
            leg_latency_ms=leg_latency_ms,
            total_latency_ms=total_latency_ms,
        )

    def _execute(
        self,
        *,
        query: str,
        scope: str | None,
        budget: int,
        mode: str,
        namespace: str | None,
        graph_hops: int,
        semantic_graph_seeding: bool,
        graph_at: str | None,
        graph_include_history: bool,
        lens: str,
        include_raw: bool,
        temporal_window: tuple[datetime, datetime] | None,
        temporal_reference: datetime | None,
        flags,
        candidate_budget: int,
        ranking_policy: str,
    ) -> tuple[
        RetrievalPlan,
        dict[str, list],
        dict[str, float],
        float,
        list,
        str | None,
    ]:
        plan = self.plan(
            query=query,
            scope=scope,
            budget=budget,
            mode=mode,
            namespace=namespace,
            graph_hops=graph_hops,
            semantic_graph_seeding=semantic_graph_seeding,
            graph_at=graph_at,
            graph_include_history=graph_include_history,
            lens=lens,
            include_raw=include_raw,
            temporal_window=temporal_window,
            temporal_reference=temporal_reference,
            candidate_budget=candidate_budget,
            ranking_policy=ranking_policy,
        )
        leg_hits: dict[str, list] = {}
        leg_latency_ms: dict[str, float] = {}
        graph_skipped_reason: str | None = None
        started = perf_counter()

        for leg in plan.legs:
            leg_started = perf_counter()
            if leg.name == "legacy_weighted":
                leg_hits["legacy_weighted"] = self.legacy_weighted_adapter.search(
                    plan, leg.limit, flags=flags
                )
            elif leg.name == "sql":
                leg_hits["sql"] = _search_current_page(
                    lambda limit: self.sql_adapter.search(plan, limit=limit),
                    limit=leg.limit,
                    include_history=plan.graph_include_history,
                )
            elif leg.name == "vector":
                leg_hits["vector"] = _search_current_page(
                    lambda limit: self.semantic_adapter.search(
                        plan, limit=limit
                    ),
                    limit=leg.limit,
                    include_history=plan.graph_include_history,
                )
            elif leg.name == "graph":
                admitted_edges_exist = (
                    self.graph_adapter.has_admissible_relation_edges(plan)
                )
                graph_node_seed_ids: list[str] = []
                if plan.semantic_graph_seeding:
                    graph_node_started = perf_counter()
                    graph_node_seed_ids, graph_node_hits = (
                        self.graph_node_adapter.search(
                            plan,
                            limit=max(0, int(flags.graph_semantic_seeds)),
                            min_score=float(flags.graph_semantic_min_score),
                        )
                    )
                    if not plan.graph_include_history:
                        graph_node_hits = [
                            hit
                            for hit in graph_node_hits
                            if hit.record.status.value
                            not in CURRENT_EXCLUDED_STATUSES
                        ]
                        visible_node_ids = {
                            hit.record.id for hit in graph_node_hits
                        }
                        graph_node_seed_ids = [
                            node_id
                            for node_id in graph_node_seed_ids
                            if node_id in visible_node_ids
                        ]
                    leg_hits["graph_node"] = graph_node_hits
                    leg_latency_ms["graph_node"] = (
                        perf_counter() - graph_node_started
                    ) * 1000.0
                if not admitted_edges_exist:
                    leg_hits["graph"] = []
                    graph_skipped_reason = "no_semantic_relation_edges"
                else:
                    semantic_seed_ids = (
                        [
                            hit.record.id
                            for hit in leg_hits.get("vector", [])
                            if plan.graph_include_history
                            or hit.record.status.value
                            not in CURRENT_EXCLUDED_STATUSES
                        ]
                        if plan.semantic_graph_seeding
                        else []
                    )
                    leg_hits["graph"] = _search_current_page(
                        lambda limit: self.graph_adapter.search(
                            plan,
                            limit=limit,
                            seed_record_ids=semantic_seed_ids,
                            seed_node_ids=graph_node_seed_ids,
                            admitted_edges_exist=True,
                        ),
                        limit=leg.limit,
                        include_history=plan.graph_include_history,
                    )
            elif leg.name == "temporal":
                leg_hits["temporal"] = self.temporal_adapter.search(
                    plan, limit=leg.limit
                )
            leg_latency_ms[leg.name] = (perf_counter() - leg_started) * 1000.0

        # Empty weights reproduce unweighted `reciprocal-rank-fusion/2` exactly,
        # so this is inert unless an operator sets them.
        leg_weights = dict(getattr(flags, "fusion_leg_weights", ()) or ())
        ranked = (
            rank_legacy_weighted_hits(leg_hits["legacy_weighted"])
            if plan.ranking_policy == "legacy-weighted/1"
            else rank_hits([hits for hits in leg_hits.values()], leg_weights)
        )
        return (
            plan,
            leg_hits,
            leg_latency_ms,
            (perf_counter() - started) * 1000.0,
            ranked,
            graph_skipped_reason,
        )

    def search(
        self,
        query: str,
        scope: str | None = None,
        budget: int = 5,
        include_trace: bool = False,
        mode: str = "hybrid",
        *,
        namespace: str | None = None,
        graph_hops: int = 1,
        semantic_graph_seeding: bool = False,
        graph_at: str | None = None,
        graph_include_history: bool = False,
        lens: str = "general",
        include_raw: bool = False,
        temporal_window: tuple[datetime, datetime] | None = None,
        temporal_reference: datetime | None = None,
        flags=None,
        ranking_policy: str = "reciprocal-rank-fusion/2",
        include_provenance: bool = False,
    ) -> RetrievalSearchResult:
        resolved_flags = (
            flags if flags is not None else self.runtime._retrieval_flags_cached()
        )
        leg_weights = dict(getattr(resolved_flags, "fusion_leg_weights", ()) or ())
        candidate_budget = (
            int(resolved_flags.search_top_k)
            if resolved_flags.search_top_k
            else budget
        )
        (
            plan,
            leg_hits,
            leg_latency_ms,
            total_latency_ms,
            ranked,
            graph_skipped_reason,
        ) = self._execute(
            query=query,
            scope=scope,
            budget=budget,
            mode=mode,
            namespace=namespace,
            graph_hops=graph_hops,
            semantic_graph_seeding=semantic_graph_seeding,
            graph_at=graph_at,
            graph_include_history=graph_include_history,
            lens=lens,
            include_raw=include_raw,
            temporal_window=temporal_window,
            temporal_reference=temporal_reference,
            flags=resolved_flags,
            ranking_policy=ranking_policy,
            candidate_budget=candidate_budget,
        )
        selected = ranked[:budget]

        if include_provenance and selected:
            # Resolve the selected page in ONE pass: candidates routinely share
            # source turns, so per-candidate resolution would re-read the same
            # SPAN and RAW rows repeatedly. Only the returned page is resolved -
            # rejected candidates are never cited, so proving their origin is
            # wasted store reads.
            chains = resolve_provenance_many(
                self.runtime.store, [candidate.record for candidate in selected]
            )
            for candidate in selected:
                candidate.provenance = chains.get(candidate.record.id)

        trace = None
        if include_trace:
            trace = _serialize_search_trace(
                plan=plan,
                budget=budget,
                candidate_budget=candidate_budget,
                leg_hits=leg_hits,
                leg_latency_ms=leg_latency_ms,
                total_latency_ms=total_latency_ms,
                ranked=ranked,
                selected=selected,
                graph_skipped_reason=graph_skipped_reason,
                leg_weights=leg_weights,
            )
        return RetrievalSearchResult(
            query=query,
            normalized_query=plan.normalized_query,
            intent=plan.intent,
            candidates=selected,
            trace=trace,
        )

    def sync_persistent_indexes(
        self,
        record_ids: list[str] | None = None,
        scope: str | None = None,
        namespace: str | None = None,
    ) -> dict[str, object]:
        # Keep the canonical read and every configured persistent projection in
        # the same same-process critical section as Runtime persistence. A sync
        # must never publish rows from a transient write that is later restored.
        with self.runtime._persist_projection_lock:
            batch = self.runtime.store.load_ir(
                ids=record_ids,
                ns=namespace,
                scope=scope,
            )
            self.runtime.vector_adapter.index_records(batch.records)
            chroma_indexed = 0
            if isinstance(self.semantic_adapter, ChromaSemanticAdapter):
                chroma_indexed = self.semantic_adapter.sync_batch(batch)
            return {
                "record_ids": [record.id for record in batch.records],
                "sqlite_indexed": [
                    record.id
                    for record in batch.records
                    if record.kind.value in {"CLM", "STA", "EVT", "REL"}
                ],
                "chroma_indexed": chroma_indexed,
                "backend": self.semantic_backend,
            }

    def rag(
        self,
        query: str,
        scope: str | None = None,
        budget: int = 5,
        pack_budget: int = 512,
        lens: str = "rag",
        mode: str = "context",
        include_trace: bool = False,
        retrieval_mode: str = "hybrid",
    ) -> RAGResult:
        search_result = self.search(query=query, scope=scope, budget=budget, include_trace=include_trace, mode=retrieval_mode)
        records = [candidate.record for candidate in search_result.candidates]
        namespace = records[0].ns if records else None
        pack = pack_records(records, lens=lens, budget=pack_budget, mode=mode, namespace=namespace)
        trace = None
        if include_trace:
            trace = {
                "search": search_result.to_dict(),
                "pack_id": pack.pack_id,
            }
        return RAGResult(
            query=query,
            backend=f"{retrieval_mode}:{self.semantic_backend}",
            candidate_ids=[record.id for record in records],
            candidates=[candidate.to_dict() for candidate in search_result.candidates],
            records=[record.to_dict() for record in records],
            pack=pack.to_dict(),
            trace=trace,
        )


def _serialize_search_trace(
    *,
    plan: RetrievalPlan,
    budget: int,
    candidate_budget: int,
    leg_hits: dict[str, list],
    leg_latency_ms: dict[str, float],
    total_latency_ms: float,
    ranked: list,
    selected: list,
    graph_skipped_reason: str | None,
    leg_weights: dict[str, float],
) -> dict[str, object]:
    """Export a bounded allowlist trace without serializing retrieval content."""

    rejected = ranked[budget : budget + _SEARCH_TRACE_ITEM_LIMIT]
    retained_leg_hits = {
        name: [
            {
                "rank": rank,
                "record_id": hit.record.id,
                "score": round(float(hit.score), 6),
            }
            for rank, hit in enumerate(
                hits[:_SEARCH_TRACE_ITEM_LIMIT],
                start=1,
            )
        ]
        for name, hits in leg_hits.items()
    }
    trace: dict[str, object] = {
        "schema": SEARCH_TRACE_SCHEMA,
        "plan": {
            "mode": plan.mode,
            "intent": plan.intent.value,
            "budget": budget,
            "candidate_budget": candidate_budget,
            "ranking_policy": plan.ranking_policy,
            "graph_hops": plan.graph_hops,
            "semantic_graph_seeding": plan.semantic_graph_seeding,
            "graph_at_applied": plan.graph_at is not None,
            "graph_include_history": plan.graph_include_history,
            "include_raw": plan.include_raw,
            "temporal_window_applied": plan.temporal_window is not None,
            "temporal_reference_applied": plan.temporal_reference is not None,
            "filters_applied": plan.filters.active(),
            "legs": [
                {
                    "name": leg.name,
                    "limit": leg.limit,
                }
                for leg in plan.legs
            ],
        },
        "legs": retained_leg_hits,
        "leg_counts": {
            name: {
                "total": len(hits),
                "retained": len(retained_leg_hits[name]),
                "truncated": len(hits) > _SEARCH_TRACE_ITEM_LIMIT,
            }
            for name, hits in leg_hits.items()
        },
        "fusion": {
            # Preserve the current weighted-RRF provenance contract while
            # keeping the exported trace content-free.
            "policy": (
                FUSION_POLICY_WEIGHTED
                if leg_weights and plan.ranking_policy == FUSION_POLICY
                else plan.ranking_policy
            ),
            "leg_weights": dict(sorted(leg_weights.items())) or None,
            "normalization": {
                "method": "reciprocal_rank",
                "rank_constant": FUSION_RANK_CONSTANT,
                "source_value": "1/(rank_constant+rank)",
            }
            if plan.ranking_policy == FUSION_POLICY
            else {"method": "legacy_weighted"},
            "tie_breaker": (
                "record_id"
                if plan.ranking_policy == FUSION_POLICY
                else "legacy_stable_record_order"
            ),
            "candidate_set_sha256": candidate_set_fingerprint(
                (candidate.record.id, candidate.score, candidate.sources)
                for candidate in ranked
            ),
            "total_candidates": len(ranked),
            "selected_ids": [candidate.record.id for candidate in selected],
            "rejected_ids": [candidate.record.id for candidate in rejected],
            "candidates_truncated": len(ranked) > budget + len(rejected),
        },
        "latency_ms": {
            "legs": {
                name: round(float(value), 6)
                for name, value in leg_latency_ms.items()
            },
            "total": round(float(total_latency_ms), 6),
        },
    }
    if graph_skipped_reason is not None:
        trace["graph_skipped_reason"] = graph_skipped_reason
    return trace


def _search_current_page(
    search: Callable[[int], list],
    *,
    limit: int,
    include_history: bool,
    max_scan: int = 100_000,
) -> list:
    """Fill a current-state page without letting tombstones consume top-K."""

    requested = max(1, limit)
    while True:
        hits = search(requested)
        if include_history:
            return hits[:limit]
        current = [
            hit
            for hit in hits
            if hit.record.status.value not in CURRENT_EXCLUDED_STATUSES
        ]
        if (
            len(current) >= limit
            or len(hits) < requested
            or requested >= max_scan
        ):
            return current[:limit]
        requested = min(requested * 2, max_scan)


HybridOrchestrator = RetrievalOrchestrator
