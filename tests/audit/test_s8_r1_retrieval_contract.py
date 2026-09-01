"""Track S R1: one retrieval contract across flags, fusion, and surfaces."""

import pytest

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.retrieval import _fuse_rrf
from seam_runtime.retrieval_orchestrator.adapters import _build_structured_sql
from seam_runtime.retrieval_orchestrator.merger import rank_hits
from seam_runtime.retrieval_orchestrator.planner import build_plan
from seam_runtime.retrieval_orchestrator.types import LegHit
from seam_runtime.runtime import SeamRuntime
from seam_runtime.sdk import SeamSDK


def test_two_boundary_filters_admit_the_nonlexical_graph_seed_tail(tmp_path):
    runtime = SeamRuntime(tmp_path / "boundary-tail.db", allow_pgvector_env=False)
    try:
        entity = MIRLRecord(
            id="ent:alpha",
            kind=RecordKind.ENT,
            ns="alpha",
            scope="thread",
            attrs={"name": "Alpha"},
        )
        record = MIRLRecord(
            id="clm:boundary-only",
            kind=RecordKind.CLM,
            ns="alpha",
            scope="thread",
            attrs={
                "subject": "ent:alpha",
                "predicate": "stores",
                "object": "content without the query token",
            },
        )
        runtime.store.persist_ir(IRBatch([entity, record]))
        plan = build_plan(
            "unmatched ns:alpha scope:thread",
            mode="graph",
        )
        query, params = _build_structured_sql(
            plan,
            ["unmatched"],
            10,
            include_graph_kinds=False,
        )
        with runtime.store._pool.checkout() as connection:
            rows = connection.execute(query, params).fetchall()

        rows_by_id = {row["id"]: row for row in rows}
        assert "clm:boundary-only" in rows_by_id
        assert rows_by_id["clm:boundary-only"]["structured_score"] == 0.8
        assert rows_by_id["clm:boundary-only"]["lexical_hits"] == 0
    finally:
        runtime.close()


def test_graph_seed_sql_refuses_the_boundary_only_tail(tmp_path):
    runtime = SeamRuntime(tmp_path / "graph-boundary-tail.db", allow_pgvector_env=False)
    try:
        record = MIRLRecord(
            id="ent:boundary-only",
            kind=RecordKind.ENT,
            ns="alpha",
            scope="thread",
            attrs={"name": "No lexical overlap"},
        )
        runtime.store.persist_ir(IRBatch([record]))
        plan = build_plan(
            "unmatched",
            namespace="alpha",
            scope="thread",
            mode="graph",
        )
        query, params = _build_structured_sql(
            plan,
            ["unmatched"],
            10,
            include_graph_kinds=True,
        )
        with runtime.store._pool.checkout() as connection:
            rows = connection.execute(query, params).fetchall()

        assert rows == []
    finally:
        runtime.close()


def test_component_and_orchestrator_rrf_use_the_same_one_based_rank():
    first = MIRLRecord(id="clm:a", kind=RecordKind.CLM)
    second = MIRLRecord(id="clm:b", kind=RecordKind.CLM)
    channels = [
        (first, {"lexical": 1.0, "semantic": 0.5, "graph": 0.0, "temporal": 0.0}),
        (second, {"lexical": 0.5, "semantic": 1.0, "graph": 0.0, "temporal": 0.0}),
    ]

    component = {
        candidate.record.id: candidate.score
        for candidate in _fuse_rrf(
            channels,
            {first.id: first, second.id: second},
            k=60,
        )
    }
    orchestrated = {
        candidate.record.id: candidate.score
        for candidate in rank_hits(
            [
                [LegHit("lexical", first, 1.0), LegHit("lexical", second, 0.5)],
                [LegHit("semantic", second, 1.0), LegHit("semantic", first, 0.5)],
            ]
        )
    }

    assert component == pytest.approx(orchestrated)


@pytest.mark.parametrize("semantic_seed_count", [0, 4])
def test_graph_semantic_seed_policy_resolves_identically_across_surfaces(
    tmp_path,
    semantic_seed_count,
):
    from seam_runtime.mcp import dispatch_tool

    runtime = SeamRuntime(
        tmp_path / f"surface-flags-{semantic_seed_count}.db",
        allow_pgvector_env=False,
    )
    try:
        runtime.ingest_conversation_turn(
            "Alpha stores retrieval contract evidence.",
            source_ref=f"test://r1/surface-flags/{semantic_seed_count}",
        )
        runtime.store.upsert_retrieval_flag_state(
            flag_key="graph_semantic_seeds",
            flag_value=semantic_seed_count,
        )
        runtime.refresh_retrieval_flags()
        expected = semantic_seed_count > 0

        direct = runtime.retrieve(
            "retrieval contract",
            ns="local.default",
            scope="thread",
            budget=1,
            mode="mix",
            include_trace=True,
        )
        assert direct.trace is not None

        mcp = dispatch_tool(
            runtime,
            {
                "tool": "seam_retrieve",
                "arguments": {
                    "query": "retrieval contract",
                    "scope": "thread",
                    "budget": 1,
                    "mode": "mix",
                    "include_trace": True,
                },
            },
        )
        session = SeamSDK(runtime=runtime).start_reasoning(
            "Verify retrieval policy parity.",
            ns="local.default",
            scope="thread",
            recommend_patterns=False,
        )
        sdk = session.retrieve("retrieval contract", budget=1, mode="mix")

        assert direct.trace["plan"]["semantic_graph_seeding"] is expected
        assert mcp["result"]["trace"]["plan"]["semantic_graph_seeding"] is expected
        assert sdk.result.plan.semantic_graph_seeding is expected
    finally:
        runtime.close()
