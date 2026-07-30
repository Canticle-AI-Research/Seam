from __future__ import annotations

from time import perf_counter
from typing import Callable

from seam_runtime.knowledge_graph import CURRENT_EXCLUDED_STATUSES
from seam_runtime.pack import pack_records
from seam_runtime.retrieval_policy import (
    FUSION_POLICY,
    FUSION_RANK_CONSTANT,
    candidate_set_fingerprint,
)
from seam_runtime.runtime import SeamRuntime

from .adapters import (
    ChromaSemanticAdapter,
    GraphNodeSemanticAdapter,
    SeamVectorSearchAdapter,
    SemanticAdapter,
    SQLAdapter,
    SQLiteGraphAdapter,
    SQLiteIRAdapter,
)
from .merger import rank_hits
from .planner import build_plan
from .types import (
    RAGResult,
    RetrievalDecisionResult,
    RetrievalPlan,
    RetrievalSearchResult,
)


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
    ) -> RetrievalPlan:
        return build_plan(
            query=query,
            scope=scope,
            budget=budget,
            mode=mode,
            namespace=namespace,
            graph_hops=graph_hops,
            semantic_graph_seeding=semantic_graph_seeding,
            graph_at=graph_at,
            graph_include_history=graph_include_history,
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
    ) -> RetrievalDecisionResult:
        if isinstance(candidate_trace_limit, bool) or not isinstance(
            candidate_trace_limit, int
        ):
            raise TypeError("candidate_trace_limit must be an integer")
        if candidate_trace_limit < budget:
            raise ValueError("candidate_trace_limit cannot be smaller than budget")
        if candidate_trace_limit > 128:
            raise ValueError("candidate_trace_limit cannot exceed 128")
        plan, leg_hits, leg_latency_ms, total_latency_ms, ranked = self._execute(
            query=query,
            scope=scope,
            budget=budget,
            mode=mode,
            namespace=namespace,
            graph_hops=graph_hops,
            semantic_graph_seeding=semantic_graph_seeding,
            graph_at=graph_at,
            graph_include_history=graph_include_history,
        )
        retained = ranked[:candidate_trace_limit]
        return RetrievalDecisionResult(
            plan=plan,
            selected=retained[:budget],
            rejected=retained[budget:],
            policy=FUSION_POLICY,
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
    ) -> tuple[RetrievalPlan, dict[str, list], dict[str, float], float, list]:
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
        )
        leg_hits: dict[str, list] = {}
        leg_latency_ms: dict[str, float] = {}
        started = perf_counter()

        for leg in plan.legs:
            leg_started = perf_counter()
            if leg.name == "sql":
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
                graph_node_seed_ids: list[str] = []
                if plan.semantic_graph_seeding:
                    graph_node_started = perf_counter()
                    flags = self.runtime._retrieval_flags_cached()
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
                    ),
                    limit=leg.limit,
                    include_history=plan.graph_include_history,
                )
            leg_latency_ms[leg.name] = (perf_counter() - leg_started) * 1000.0

        ranked = rank_hits([hits for hits in leg_hits.values()])
        return (
            plan,
            leg_hits,
            leg_latency_ms,
            (perf_counter() - started) * 1000.0,
            ranked,
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
    ) -> RetrievalSearchResult:
        plan, leg_hits, leg_latency_ms, total_latency_ms, ranked = self._execute(
            query=query,
            scope=scope,
            budget=budget,
            mode=mode,
            namespace=namespace,
            graph_hops=graph_hops,
            semantic_graph_seeding=semantic_graph_seeding,
            graph_at=graph_at,
            graph_include_history=graph_include_history,
        )
        selected = ranked[:budget]
        rejected_trace = ranked[budget : budget + 128]

        trace = None
        if include_trace:
            trace = {
                "plan": plan.to_dict(),
                "legs": {
                    name: [hit.to_dict() for hit in hits]
                    for name, hits in leg_hits.items()
                },
                "fusion": {
                    "policy": FUSION_POLICY,
                    "normalization": {
                        "method": "reciprocal_rank",
                        "rank_constant": FUSION_RANK_CONSTANT,
                        "source_value": "1/(rank_constant+rank)",
                    },
                    "tie_breaker": "record_id",
                    "total_candidates": len(ranked),
                    "selected_ids": [
                        candidate.record.id for candidate in selected
                    ],
                    "rejected_ids": [
                        candidate.record.id for candidate in rejected_trace
                    ],
                    "candidates_truncated": len(ranked) > budget + len(rejected_trace),
                },
                "latency_ms": {
                    "legs": dict(leg_latency_ms),
                    "total": total_latency_ms,
                },
            }
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
        batch = self.runtime.store.load_ir(ids=record_ids, ns=namespace, scope=scope)
        self.runtime.vector_adapter.index_records(batch.records)
        chroma_indexed = 0
        if isinstance(self.semantic_adapter, ChromaSemanticAdapter):
            chroma_indexed = self.semantic_adapter.sync_batch(batch)
        return {
            "record_ids": [record.id for record in batch.records],
            "sqlite_indexed": [record.id for record in batch.records if record.kind.value in {"CLM", "STA", "EVT", "REL"}],
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
