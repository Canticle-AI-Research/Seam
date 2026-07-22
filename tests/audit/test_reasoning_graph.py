"""R1 contract: durable public reasoning alongside canonical knowledge."""

from __future__ import annotations

import inspect
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from seam_runtime.mirl import RecordKind
from seam_runtime.runtime import SeamRuntime
from seam_runtime.sdk import ReasoningSession, SeamSDK


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    instance = SeamRuntime(tmp_path / "reasoning.db", allow_pgvector_env=False)
    try:
        yield instance
    finally:
        instance.close()


def _seed_evidence(
    runtime: SeamRuntime, *, ns: str = "work", scope: str = "thread"
) -> tuple[str, str]:
    batch = runtime.compile_nl(
        "Ada owns the compiler.",
        source_ref="local://reasoning-test",
        ns=ns,
        scope=scope,
        allow_env_extractor=False,
    )
    runtime.persist_ir(batch)
    raw_id = next(record.id for record in batch.records if record.kind == RecordKind.RAW)
    graph = runtime.store.knowledge_graph(
        query="Ada", namespace=ns, scope=scope, limit=100
    )
    knowledge_id = next(
        str(node["id"])
        for node in graph["nodes"]
        if node["kind"] in {"entity", "claim"}
    )
    return knowledge_id, raw_id


def test_sdk_builds_grounded_append_only_reasoning_graph(runtime: SeamRuntime) -> None:
    knowledge_id, raw_id = _seed_evidence(runtime)
    sdk = SeamSDK(runtime=runtime)
    session = sdk.start_reasoning(
        "Determine who owns the compiler.", ns="work", scope="thread", agent_id="codex"
    )
    premise = session.add_node(
        "premise",
        "The stored source attributes compiler ownership to Ada.",
        confidence=0.95,
        knowledge_refs=[knowledge_id],
        evidence_refs=[raw_id],
    )
    inference = session.add_node(
        "inference", "Ada is the compiler owner.", confidence=0.9
    )
    session.link(str(premise["node_id"]), "supports", str(inference["node_id"]))
    session.transition(
        str(inference["node_id"]), "accepted", reason="supported by stored evidence"
    )
    outcome = session.finalize(
        "Ada owns the compiler.",
        confidence=0.9,
        supporting_node_ids=[str(inference["node_id"])],
    )

    graph = session.graph()
    assert graph["canonical_truth"] is False
    assert graph["automatic_promotion"] is False
    assert [node["kind"] for node in graph["nodes"]] == [
        "objective",
        "premise",
        "inference",
        "outcome",
    ]
    assert outcome["status"] == "accepted"
    assert outcome["state_history"][-1]["reason"] == "session outcome finalized"
    assert {edge["relation"] for edge in graph["edges"]} == {"supports"}


def test_premises_require_real_same_scope_evidence(runtime: SeamRuntime) -> None:
    knowledge_id, raw_id = _seed_evidence(runtime, ns="alpha", scope="thread")
    session = SeamSDK(runtime=runtime).start_reasoning(
        "Test evidence boundaries.", ns="beta", scope="thread"
    )

    with pytest.raises(ValueError, match="premise nodes require"):
        session.add_node("premise", "An ungrounded premise.")
    with pytest.raises(ValueError, match="crosses namespace or scope"):
        session.add_node(
            "premise", "Wrong namespace.", knowledge_refs=[knowledge_id]
        )
    with pytest.raises(ValueError, match="crosses namespace or scope"):
        session.add_node("premise", "Wrong namespace.", evidence_refs=[raw_id])
    with pytest.raises(KeyError, match="knowledge node not found"):
        session.add_node("premise", "Missing reference.", knowledge_refs=["ent:missing"])


def test_accepting_a_conclusion_requires_explicit_support(runtime: SeamRuntime) -> None:
    session = SeamSDK(runtime=runtime).start_reasoning("Reach a grounded conclusion.")
    inference = session.add_node("inference", "A possible conclusion.")

    with pytest.raises(ValueError, match="require explicit support"):
        session.transition(str(inference["node_id"]), "accepted")

    hypothesis = session.add_node("hypothesis", "A testable possibility.")
    session.link(str(hypothesis["node_id"]), "tests", str(inference["node_id"]))
    session.transition(str(inference["node_id"]), "accepted")
    with pytest.raises(ValueError, match="accepted -> rejected"):
        session.transition(str(inference["node_id"]), "rejected")
    session.transition(str(inference["node_id"]), "superseded")


def test_edges_and_session_operations_cannot_cross_runs(runtime: SeamRuntime) -> None:
    sdk = SeamSDK(runtime=runtime)
    first = sdk.start_reasoning("First objective.")
    second = sdk.start_reasoning("Second objective.")
    first_node = first.graph()["nodes"][0]
    second_node = second.graph()["nodes"][0]

    with pytest.raises(ValueError, match="cannot cross runs"):
        runtime.store.add_reasoning_edge(
            run_id=first.run_id,
            src_node_id=str(first_node["node_id"]),
            relation="supports",
            dst_node_id=str(second_node["node_id"]),
        )
    with pytest.raises(ValueError, match="does not belong"):
        first.transition(str(second_node["node_id"]), "supported")


def test_reasoning_tables_are_append_only(runtime: SeamRuntime) -> None:
    session = SeamSDK(runtime=runtime).start_reasoning("Preserve the audit trail.")
    objective_id = str(session.graph()["nodes"][0]["node_id"])

    with runtime.store._pool.checkout() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "update reasoning_node set summary = 'rewritten' where node_id = ?",
                (objective_id,),
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "delete from reasoning_state where node_id = ?", (objective_id,)
            )
        connection.rollback()


def test_reasoning_never_promotes_itself_or_exposes_hidden_trace_fields(
    runtime: SeamRuntime,
) -> None:
    before = len(runtime.store.load_ir().records)
    session = SeamSDK(runtime=runtime).start_reasoning("Do not mutate canonical truth.")
    session.add_node("hypothesis", "This remains a non-canonical hypothesis.")
    after = len(runtime.store.load_ir().records)

    assert after == before
    parameters = set(inspect.signature(ReasoningSession.add_node).parameters)
    assert not parameters & {
        "chain_of_thought",
        "hidden_thoughts",
        "raw_reasoning",
        "activations",
        "logits",
    }


def test_sdk_can_resume_a_run_without_taking_runtime_ownership(
    runtime: SeamRuntime,
) -> None:
    sdk = SeamSDK(runtime=runtime)
    started = sdk.start_reasoning("Resume this work.")
    resumed = sdk.reasoning(started.run_id)
    resumed.add_node("question", "What remains unresolved?")
    sdk.close()

    # An SDK attached to an existing runtime must not close operator-owned state.
    assert len(runtime.store.list_workspace_runs()) == 1
    assert len(resumed.graph()["nodes"]) == 2


def test_start_is_atomic_and_concurrent_sequence_allocation_is_unique(
    runtime: SeamRuntime,
) -> None:
    sdk = SeamSDK(runtime=runtime)
    with pytest.raises(ValueError, match="reasoning summary is required"):
        sdk.start_reasoning("   ")
    assert runtime.store.list_workspace_runs() == []

    session = sdk.start_reasoning("Allocate nodes safely.")
    with ThreadPoolExecutor(max_workers=5) as executor:
        nodes = list(
            executor.map(
                lambda index: session.add_node("question", f"Question {index}?"),
                range(20),
            )
        )
    assert len({node["seq"] for node in nodes}) == 20
    assert [node["seq"] for node in session.graph()["nodes"]] == list(range(1, 22))
