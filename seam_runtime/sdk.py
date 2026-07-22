from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .runtime import SeamRuntime


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
            knowledge_refs=tuple(knowledge_refs),
            evidence_record_ids=tuple(evidence_refs),
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
