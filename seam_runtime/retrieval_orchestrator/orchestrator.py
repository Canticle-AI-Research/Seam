from __future__ import annotations

from seam_runtime.pack import pack_records
from seam_runtime.runtime import SeamRuntime

from .adapters import (
    ChromaSemanticAdapter,
    SeamVectorSearchAdapter,
    SemanticAdapter,
    SQLAdapter,
    SQLiteGraphAdapter,
    SQLiteIRAdapter,
)
from .merger import merge_hits
from .planner import build_plan
from .types import RAGResult, RetrievalPlan, RetrievalSearchResult


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

    def plan(self, query: str, scope: str | None = None, budget: int = 5, mode: str = "hybrid") -> RetrievalPlan:
        return build_plan(query=query, scope=scope, budget=budget, mode=mode)

    def search(self, query: str, scope: str | None = None, budget: int = 5, include_trace: bool = False, mode: str = "hybrid") -> RetrievalSearchResult:
        plan = self.plan(query=query, scope=scope, budget=budget, mode=mode)
        leg_hits: dict[str, list] = {}

        for leg in plan.legs:
            if leg.name == "sql":
                leg_hits["sql"] = self.sql_adapter.search(plan, limit=leg.limit)
            elif leg.name == "vector":
                leg_hits["vector"] = self.semantic_adapter.search(plan, limit=leg.limit)
            elif leg.name == "graph":
                leg_hits["graph"] = self.graph_adapter.search(plan, limit=leg.limit)

        candidates = merge_hits([hits for hits in leg_hits.values()], limit=budget)
        trace = None
        if include_trace:
            trace = {
                "plan": plan.to_dict(),
                "legs": {name: [hit.to_dict() for hit in hits] for name, hits in leg_hits.items()},
            }
        return RetrievalSearchResult(
            query=query,
            normalized_query=plan.normalized_query,
            intent=plan.intent,
            candidates=candidates,
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


HybridOrchestrator = RetrievalOrchestrator
