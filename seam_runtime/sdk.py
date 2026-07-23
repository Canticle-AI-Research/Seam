from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .reasoning_graph import ReasoningRetrievalCandidate
from .retrieval_policy import mirl_record_fingerprint
from .runtime import SeamRuntime

if TYPE_CHECKING:
    from .retrieval_orchestrator import RetrievalDecisionResult


@dataclass(frozen=True)
class ReasonedRetrieval:
    result: RetrievalDecisionResult
    reasoning: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "retrieval": self.result.to_dict(),
            "reasoning": dict(self.reasoning),
        }


_REASON_CODE_MAP = {
    "matched=id": "matched_id",
    "matched=kind": "matched_kind",
    "matched=ns": "matched_namespace",
    "matched=scope": "matched_scope",
    "matched=predicate": "matched_predicate",
    "matched=subject": "matched_subject",
    "matched=object": "matched_object",
    "structured": "structured_score",
    "lexical": "lexical_score",
    "token_hits": "token_hits",
    "semantic": "semantic_score",
    "graph_neighbors": "graph_neighbors",
    "graph_hop": "graph_hop",
    "semantic_seed": "semantic_seed",
    "chroma": "chroma_score",
}


def _reason_codes(reasons: Iterable[str]) -> tuple[str, ...]:
    codes: list[str] = []
    for reason in reasons:
        signal = reason.split(":", 1)[-1]
        key = signal.split("=", 1)[0]
        code = _REASON_CODE_MAP.get(signal) or _REASON_CODE_MAP.get(key)
        if code is None:
            raise ValueError(f"unsupported retrieval reason emitted by adapter: {reason}")
        if code not in codes:
            codes.append(code)
    return tuple(codes)


class ReasoningSession:
    """Run-scoped SDK handle for SEAM's public reasoning graph."""

    def __init__(self, runtime: SeamRuntime, run_id: str) -> None:
        self._runtime = runtime
        run = runtime.store.get_workspace_run(run_id, include_events=False)["run"]
        self.run_id = run_id
        self.ns = str(run["ns"])
        self.scope = str(run["scope"])
        self.agent_id = run.get("agent_id")

    def add_node(
        self,
        kind: str,
        summary: str,
        *,
        confidence: float | None = None,
        operation: str | None = None,
        knowledge_refs: Iterable[str] = (),
        evidence_refs: Iterable[str] = (),
    ) -> dict[str, object]:
        """Append a concise reasoning artifact, never hidden chain-of-thought."""

        return self._runtime.store.add_reasoning_node(
            run_id=self.run_id,
            kind=kind,
            summary=summary,
            confidence=confidence,
            agent_id=self.agent_id if isinstance(self.agent_id, str) else None,
            operation=operation,
            knowledge_refs=knowledge_refs,
            evidence_record_ids=evidence_refs,
        )

    def link(
        self, src_node_id: str, relation: str, dst_node_id: str
    ) -> dict[str, object]:
        return self._runtime.store.add_reasoning_edge(
            run_id=self.run_id,
            src_node_id=src_node_id,
            relation=relation,
            dst_node_id=dst_node_id,
            agent_id=self.agent_id if isinstance(self.agent_id, str) else None,
        )

    def transition(
        self,
        node_id: str,
        status: str,
        *,
        reason: str | None = None,
        actor: str | None = None,
    ) -> dict[str, object]:
        node = self._runtime.store.reasoning_node(node_id, include_history=False)
        if node["run_id"] != self.run_id:
            raise ValueError("reasoning node does not belong to this session")
        return self._runtime.store.transition_reasoning_node(
            node_id=node_id,
            status=status,
            reason=reason,
            actor=actor or (self.agent_id if isinstance(self.agent_id, str) else None),
        )

    def finalize(
        self,
        summary: str,
        *,
        confidence: float | None = None,
        knowledge_refs: Iterable[str] = (),
        evidence_refs: Iterable[str] = (),
        supporting_node_ids: Iterable[str] = (),
    ) -> dict[str, object]:
        """Append and accept a supported outcome for the run."""

        outcome = self.add_node(
            "outcome",
            summary,
            confidence=confidence,
            knowledge_refs=knowledge_refs,
            evidence_refs=evidence_refs,
        )
        for node_id in supporting_node_ids:
            self.link(node_id, "supports", str(outcome["node_id"]))
        self.transition(
            str(outcome["node_id"]),
            "accepted",
            reason="session outcome finalized",
        )
        return self._runtime.store.reasoning_node(str(outcome["node_id"]))

    def node(self, node_id: str) -> dict[str, object]:
        node = self._runtime.store.reasoning_node(node_id)
        if node["run_id"] != self.run_id:
            raise ValueError("reasoning node does not belong to this session")
        return node

    def graph(self) -> dict[str, object]:
        return self._runtime.store.reasoning_graph(self.run_id)

    def retrieve(
        self,
        query: str,
        *,
        budget: int = 5,
        mode: str = "mix",
        graph_hops: int = 1,
        semantic_graph_seeding: bool = True,
        semantic_backend: str = "seam",
    ) -> ReasonedRetrieval:
        """Run and atomically record a bounded retrieval decision."""

        if not isinstance(query, str):
            raise TypeError("retrieval query must be a string")
        if len(query) > 4096:
            raise ValueError("retrieval query exceeds 4096 characters")
        resolved_query = query.strip()
        if not resolved_query:
            raise ValueError("retrieval query is required")
        if isinstance(budget, bool) or not isinstance(budget, int):
            raise TypeError("reasoning retrieval budget must be an integer")
        if not 1 <= budget <= 64:
            raise ValueError("reasoning retrieval budget must be between 1 and 64")
        if isinstance(graph_hops, bool) or not isinstance(graph_hops, int):
            raise TypeError("graph_hops must be an integer")
        if not 0 <= graph_hops <= 3:
            raise ValueError("graph_hops must be between 0 and 3")
        if not isinstance(semantic_graph_seeding, bool):
            raise TypeError("semantic_graph_seeding must be a boolean")
        if semantic_backend not in {"seam", "chroma"}:
            raise ValueError("semantic_backend must be 'seam' or 'chroma'")
        from .retrieval_orchestrator import RetrievalOrchestrator

        orchestrator = RetrievalOrchestrator(
            self._runtime, semantic_backend=semantic_backend
        )
        result = orchestrator.decide(
            query=resolved_query,
            scope=self.scope,
            namespace=self.ns,
            budget=budget,
            mode=mode,
            graph_hops=graph_hops,
            semantic_graph_seeding=semantic_graph_seeding,
            candidate_trace_limit=128,
        )
        selected_count = len(result.selected)
        candidates = tuple(
            ReasoningRetrievalCandidate(
                record_id=candidate.record.id,
                rank=rank,
                score=candidate.score,
                selected=rank <= selected_count,
                sources=dict(candidate.sources),
                record_sha256=mirl_record_fingerprint(candidate.record.to_dict()),
                reasons=_reason_codes(candidate.reasons),
            )
            for rank, candidate in enumerate(result.ranked, start=1)
        )
        reasoning = self._runtime.store.record_reasoning_retrieval(
            run_id=self.run_id,
            query=resolved_query,
            normalized_query=result.plan.normalized_query,
            filter_ids=result.plan.filters.ids,
            filter_kinds=result.plan.filters.kinds,
            filter_predicate=result.plan.filters.predicate,
            filter_subject=result.plan.filters.subject,
            filter_object_text=result.plan.filters.object_text,
            leg_limits={leg.name: leg.limit for leg in result.plan.legs},
            mode=result.plan.mode,
            intent=result.plan.intent.value,
            budget=budget,
            graph_hops=result.plan.graph_hops,
            semantic_graph_seeding=result.plan.semantic_graph_seeding,
            semantic_backend=semantic_backend,
            semantic_adapter=(
                "chroma-embedded"
                if semantic_backend == "chroma"
                else str(getattr(self._runtime.vector_adapter, "name", "unknown"))
            ),
            embedding_model=str(self._runtime.embedding_model.name),
            embedding_dimension=int(self._runtime.embedding_model.dimension),
            embedding_revision=(
                str(revision)
                if (revision := getattr(self._runtime.embedding_model, "revision", None))
                is not None
                else None
            ),
            candidates=candidates,
            total_candidates=result.total_candidates,
            candidates_truncated=result.candidates_truncated,
            candidate_set_sha256=result.candidate_set_sha256,
            leg_latency_ms=result.leg_latency_ms,
            total_latency_ms=result.total_latency_ms,
            policy=result.policy,
            agent_id=self.agent_id if isinstance(self.agent_id, str) else None,
        )
        return ReasonedRetrieval(result=result, reasoning=reasoning)

    def retrieval(self, retrieval_id: str) -> dict[str, object]:
        retrieval = self._runtime.store.reasoning_retrieval(retrieval_id)
        if retrieval["run_id"] != self.run_id:
            raise ValueError("reasoning retrieval does not belong to this session")
        return retrieval

    def retrievals(
        self,
        *,
        limit: int = 100,
        after: str | None = None,
        include_candidates: bool = False,
    ) -> list[dict[str, object]]:
        return self._runtime.store.reasoning_retrievals(
            run_id=self.run_id,
            limit=limit,
            after=after,
            include_candidates=include_candidates,
        )


class SeamSDK:
    """Stable programmatic entry point for SEAM runtimes and reasoning runs."""

    def __init__(
        self,
        path: str | Path = "seam.db",
        *,
        runtime: SeamRuntime | None = None,
        allow_pgvector_env: bool = True,
        **runtime_options: Any,
    ) -> None:
        if runtime is not None and runtime_options:
            raise ValueError("runtime_options cannot be used with an existing runtime")
        self._owns_runtime = runtime is None
        self.runtime = runtime or SeamRuntime(
            store_path=path,
            allow_pgvector_env=allow_pgvector_env,
            **runtime_options,
        )

    def close(self) -> None:
        if self._owns_runtime:
            self.runtime.close()

    def __enter__(self) -> "SeamSDK":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def start_reasoning(
        self,
        objective: str,
        *,
        ns: str = "local.reasoning",
        scope: str = "thread",
        agent_id: str | None = None,
        model: str | None = None,
        provider: str | None = None,
    ) -> ReasoningSession:
        run, _objective = self.runtime.store.create_reasoning_run(
            objective=objective,
            ns=ns,
            scope=scope,
            agent_id=agent_id,
            model=model,
            provider=provider,
        )
        return ReasoningSession(self.runtime, str(run["run_id"]))

    def reasoning(self, run_id: str) -> ReasoningSession:
        return ReasoningSession(self.runtime, run_id)

    def ingest(self, text: str, **options: Any) -> object:
        """Compile and persist text through the underlying SEAM runtime."""

        return self.runtime.ingest_text(text, **options)

    def knowledge(self, **query: Any) -> dict[str, object]:
        """Query the canonical knowledge plane without exposing storage details."""

        return self.runtime.store.knowledge_graph(**query)
