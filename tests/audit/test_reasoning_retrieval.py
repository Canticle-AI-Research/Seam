"""R2 retrieval decisions and G3a bounded semantic-seeded traversal."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.models import HashEmbeddingModel
from seam_runtime.reasoning_graph import (
    ReasoningRetrievalCandidate,
    _retrieval_candidate_rows,
)
from seam_runtime.retrieval_orchestrator import RetrievalOrchestrator
from seam_runtime.retrieval_orchestrator.adapters import (
    ChromaSemanticAdapter,
    SeamVectorSearchAdapter,
    SQLiteGraphAdapter,
    SQLiteIRAdapter,
)
from seam_runtime.retrieval_orchestrator.merger import rank_hits
from seam_runtime.retrieval_orchestrator.planner import build_plan
from seam_runtime.retrieval_orchestrator.types import LegHit
from seam_runtime.retrieval_policy import (
    FUSION_POLICY,
    FUSION_POLICY_FINGERPRINT,
    candidate_set_fingerprint,
    mirl_record_fingerprint,
)
from seam_runtime.runtime import SeamRuntime
from seam_runtime.sdk import SeamSDK


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    instance = SeamRuntime(tmp_path / "reasoning-retrieval.db", allow_pgvector_env=False)
    try:
        yield instance
    finally:
        instance.close()


def _seed_text(runtime: SeamRuntime, text: str, source: str, *, ns: str = "work") -> None:
    runtime.persist_ir(
        runtime.compile_nl(
            text,
            source_ref=source,
            ns=ns,
            scope="thread",
            allow_env_extractor=False,
        )
    )


def _seed_chain(runtime: SeamRuntime) -> None:
    runtime.persist_ir(
        IRBatch(
            [
                MIRLRecord(
                    id="ent:alpha",
                    kind=RecordKind.ENT,
                    ns="work",
                    scope="thread",
                    attrs={"label": "Alpha", "entity_type": "concept"},
                ),
                MIRLRecord(
                    id="ent:beta",
                    kind=RecordKind.ENT,
                    ns="work",
                    scope="thread",
                    attrs={"label": "Beta", "entity_type": "concept"},
                ),
                MIRLRecord(
                    id="ent:gamma",
                    kind=RecordKind.ENT,
                    ns="work",
                    scope="thread",
                    attrs={"label": "Gamma", "entity_type": "concept"},
                ),
                MIRLRecord(
                    id="rel:alpha-beta",
                    kind=RecordKind.REL,
                    ns="work",
                    scope="thread",
                    attrs={"src": "ent:alpha", "predicate": "connects", "dst": "ent:beta"},
                ),
                MIRLRecord(
                    id="rel:beta-gamma",
                    kind=RecordKind.REL,
                    ns="work",
                    scope="thread",
                    attrs={"src": "ent:beta", "predicate": "connects", "dst": "ent:gamma"},
                ),
            ]
        )
    )


def test_sdk_records_selected_and_rejected_retrieval_candidates(runtime: SeamRuntime) -> None:
    _seed_text(runtime, "Ada owns the compiler rollback plan.", "local://ada")
    _seed_text(runtime, "Lin reviews compiler migrations.", "local://lin")
    _seed_text(runtime, "Mira documents rollback drills.", "local://mira")
    ir_count = len(runtime.store.load_ir(ns="work", scope="thread").records)
    session = SeamSDK(runtime=runtime).start_reasoning(
        "Choose evidence for the compiler migration.", ns="work", scope="thread"
    )

    recorded = session.retrieve(
        "compiler rollback", budget=1, mode="mix", graph_hops=2
    )
    retrieval = recorded.reasoning

    assert retrieval["policy"] == FUSION_POLICY
    assert retrieval["policy_fingerprint"] == FUSION_POLICY_FINGERPRINT
    assert retrieval["planner"] == "retrieval-planner/1"
    assert retrieval["semantic_adapter"] == "sqlite-vector"
    assert retrieval["embedding_model"] == "hash-bow-v1"
    assert retrieval["embedding_dimension"] == 64
    assert retrieval["filters"]["namespace"] == "work"
    assert retrieval["filters"]["scope"] == "thread"
    assert set(retrieval["leg_limits"]) == {"sql", "vector", "graph"}
    assert all(value is not None for value in retrieval["leg_limits"].values())
    assert retrieval["selected_count"] == 1
    assert retrieval["recorded_candidates"] >= 2
    assert retrieval["candidates"][0]["selected"] is True
    assert all(
        candidate["selected"] is False for candidate in retrieval["candidates"][1:]
    )
    assert all("record" not in candidate for candidate in retrieval["candidates"])
    assert all(
        candidate["record_integrity"] == "current"
        for candidate in retrieval["candidates"]
    )
    assert all(
        isinstance(code, str)
        for candidate in retrieval["candidates"]
        for code in candidate["reason_codes"]
    )

    decision = session.node(str(retrieval["decision_node_id"]))
    assert decision["status"] == "accepted"
    assert decision["evidence_record_ids"] == [
        retrieval["candidates"][0]["record_id"]
    ]
    assert len(runtime.store.load_ir(ns="work", scope="thread").records) == ir_count

    graph = session.graph()
    assert len(graph["retrievals"]) == 1
    assert "candidates" not in graph["retrievals"][0]
    relations = {edge["relation"] for edge in graph["edges"]}
    assert {"decomposes", "produces"} <= relations


def test_empty_retrieval_is_a_finalized_noncanonical_decision(runtime: SeamRuntime) -> None:
    session = SeamSDK(runtime=runtime).start_reasoning(
        "Find evidence if any exists.", ns="empty", scope="thread"
    )
    recorded = session.retrieve("nothing here", budget=3, mode="mix")

    assert recorded.reasoning["total_candidates"] == 0
    assert recorded.reasoning["selected_count"] == 0
    assert recorded.reasoning["candidates"] == []
    decision = session.node(str(recorded.reasoning["decision_node_id"]))
    assert decision["status"] == "accepted"
    assert decision["evidence_record_ids"] == []
    assert session.graph()["canonical_truth"] is False


def test_session_boundary_rejects_inline_namespace_and_scope_overrides(
    runtime: SeamRuntime,
) -> None:
    session = SeamSDK(runtime=runtime).start_reasoning(
        "Keep retrieval isolated.", ns="alpha", scope="thread"
    )
    before = session.graph()

    with pytest.raises(ValueError, match="namespace conflicts"):
        session.retrieve("ns:beta secret", mode="mix")
    with pytest.raises(ValueError, match="scope conflicts"):
        session.retrieve("scope:project secret", mode="mix")

    after = session.graph()
    assert after["nodes"] == before["nodes"]
    assert after["retrievals"] == []


def test_candidate_cap_fails_atomically_before_reasoning_nodes(runtime: SeamRuntime) -> None:
    _seed_text(runtime, "One bounded record.", "local://bounded")
    record_id = runtime.store.load_ir(ns="work", scope="thread").records[0].id
    session = SeamSDK(runtime=runtime).start_reasoning(
        "Reject an oversized trace.", ns="work", scope="thread"
    )
    record_sha256 = mirl_record_fingerprint(
        runtime.store.load_ir(ids=[record_id]).records[0].to_dict()
    )
    oversized = (
        ReasoningRetrievalCandidate(
            record_id=record_id,
            rank=index,
            score=1.0,
            selected=index == 1,
            sources={"sql": 1.0},
            record_sha256=record_sha256,
            reasons=("lexical_score",),
        )
        for index in range(1, 130)
    )

    with pytest.raises(ValueError, match="at most 128"):
        runtime.store.record_reasoning_retrieval(
            run_id=session.run_id,
            query="bounded",
            normalized_query="bounded",
            filter_ids=(),
            filter_kinds=(),
            filter_predicate=None,
            filter_subject=None,
            filter_object_text=None,
            leg_limits={"sql": 5, "vector": 5},
            mode="hybrid",
            intent="hybrid",
            budget=1,
            graph_hops=1,
            semantic_graph_seeding=False,
            semantic_backend="seam",
            semantic_adapter="sqlite-vector",
            embedding_model="hash-bow-v1",
            embedding_dimension=64,
            embedding_revision=None,
            candidates=oversized,
            total_candidates=129,
            candidates_truncated=False,
            candidate_set_sha256="0" * 64,
            leg_latency_ms={},
            total_latency_ms=1.0,
            policy=FUSION_POLICY,
        )
    assert len(session.graph()["nodes"]) == 1
    assert session.retrievals() == []


def test_retrieval_tables_block_mutation_and_post_finalize_append(
    runtime: SeamRuntime,
) -> None:
    _seed_text(runtime, "Ada owns the compiler.", "local://append-only")
    session = SeamSDK(runtime=runtime).start_reasoning(
        "Audit retrieval immutably.", ns="work", scope="thread"
    )
    retrieval = session.retrieve("compiler", budget=1, mode="hybrid").reasoning

    with runtime.store._pool.checkout() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "update reasoning_retrieval set budget = 2 where retrieval_id = ?",
                (retrieval["retrieval_id"],),
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="finalized"):
            connection.execute(
                """
                insert into reasoning_retrieval_candidate
                    (candidate_id, retrieval_id, record_id, rank, score, selected,
                     sources_json, reasons_json, disposition_reason, created_at,
                     schema_version)
                values ('late', ?, ?, 99, 0, 0, '{"sql":0}', '["lexical_score"]',
                        'below ranked cutoff', '2026-01-01T00:00:00Z', 1)
                """,
                (
                    retrieval["retrieval_id"],
                    retrieval["candidates"][0]["record_id"],
                ),
            )
        connection.rollback()


def test_rank_fusion_ties_are_stable_across_leg_order() -> None:
    first = MIRLRecord(id="clm:a", kind=RecordKind.CLM)
    second = MIRLRecord(id="clm:b", kind=RecordKind.CLM)
    sql = [LegHit("sql", second, 1.0), LegHit("sql", first, 1.0)]
    vector = [LegHit("vector", first, 0.5), LegHit("vector", second, 0.5)]

    forward = [candidate.record.id for candidate in rank_hits([sql, vector])]
    reverse = [candidate.record.id for candidate in rank_hits([list(reversed(vector)), list(reversed(sql))])]
    assert forward == reverse == ["clm:a", "clm:b"]


def test_ordinary_search_keeps_large_budget_compatibility(runtime: SeamRuntime) -> None:
    result = RetrievalOrchestrator(runtime).search(
        "empty", budget=300, mode="hybrid", include_trace=True
    )
    assert result.candidates == []
    assert result.trace["fusion"]["policy"] == FUSION_POLICY


def test_graph_hops_are_real_and_bounded(runtime: SeamRuntime) -> None:
    _seed_chain(runtime)
    adapter = SQLiteGraphAdapter(runtime.store)

    def ids(hops: int) -> set[str]:
        plan = build_plan(
            "Alpha",
            scope="thread",
            namespace="work",
            budget=20,
            mode="graph",
            graph_hops=hops,
        )
        return {hit.record.id for hit in adapter.search(plan, limit=20)}

    assert "ent:alpha" in ids(0)
    assert "ent:beta" not in ids(0)
    assert "ent:beta" in ids(1)
    assert "ent:gamma" not in ids(1)
    assert "ent:gamma" in ids(2)


class _EmptySQL:
    def search(self, plan, limit):
        return []


class _StaticLeg:
    def __init__(self, leg: str, records: list[MIRLRecord]) -> None:
        self.leg = leg
        self.records = records

    def search(self, plan, limit):
        reason = "lexical=1.00" if self.leg == "sql" else "semantic=1.00"
        return [
            LegHit(self.leg, record, 1.0, reasons=[reason])
            for record in self.records[:limit]
        ]


class _SemanticRelation:
    def __init__(self, record: MIRLRecord) -> None:
        self.record = record

    def search(self, plan, limit):
        return [
            LegHit(
                leg="vector",
                record=self.record,
                score=0.9,
                reasons=["semantic=0.90"],
            )
        ]


def test_semantic_fact_hits_seed_bounded_graph_traversal(runtime: SeamRuntime) -> None:
    _seed_chain(runtime)
    relation = runtime.store.load_ir(ids=["rel:alpha-beta"]).records[0]
    orchestrator = RetrievalOrchestrator(
        runtime,
        sql_adapter=_EmptySQL(),
        semantic_adapter=_SemanticRelation(relation),
    )
    result = orchestrator.decide(
        "unmatched semantic query",
        scope="thread",
        namespace="work",
        budget=5,
        mode="mix",
        graph_hops=1,
        semantic_graph_seeding=True,
    )
    by_id = {candidate.record.id: candidate for candidate in result.ranked}

    assert "rel:alpha-beta" in by_id
    assert {"ent:alpha", "ent:beta"} <= set(by_id)
    assert any(
        reason == "graph:semantic_seed=true"
        for reason in by_id["rel:alpha-beta"].reasons
    )


def test_isolated_semantic_seed_does_not_gain_graph_credit(
    runtime: SeamRuntime,
) -> None:
    record = MIRLRecord(
        id="raw:isolated",
        kind=RecordKind.RAW,
        ns="work",
        scope="thread",
        attrs={"content": "isolated semantic evidence"},
    )
    runtime.persist_ir(IRBatch([record]))
    orchestrator = RetrievalOrchestrator(
        runtime,
        sql_adapter=_EmptySQL(),
        semantic_adapter=_SemanticRelation(record),
    )

    for hops in (0, 1):
        result = orchestrator.decide(
            "unmatched query",
            scope="thread",
            namespace="work",
            budget=5,
            mode="mix",
            graph_hops=hops,
            semantic_graph_seeding=True,
        )
        candidate = next(item for item in result.ranked if item.record.id == record.id)
        assert set(candidate.sources) == {"vector"}
        assert result.leg_hits["graph"] == []


def test_graph_seed_loading_never_materializes_the_whole_scope(
    runtime: SeamRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_chain(runtime)
    original = runtime.store.load_ir
    calls: list[list[str]] = []

    def guarded_load_ir(*, ids=None, ns=None, scope=None, limit=None, offset=0):
        assert ids is not None
        assert len(ids) <= 512
        calls.append(list(ids))
        return original(ids=ids, ns=ns, scope=scope, limit=limit, offset=offset)

    monkeypatch.setattr(runtime.store, "load_ir", guarded_load_ir)
    plan = build_plan(
        "Alpha", scope="thread", namespace="work", mode="graph", graph_hops=2
    )
    assert SQLiteGraphAdapter(runtime.store).search(plan, limit=20)
    assert calls


class _NamespaceVector:
    def __init__(self, record_id: str) -> None:
        self.record_id = record_id
        self.namespace = None
        self.scope = None

    def search(
        self,
        query: str,
        limit: int = 10,
        namespace: str | None = None,
        scope: str | None = None,
    ):
        self.namespace = namespace
        self.scope = scope
        return {self.record_id: 1.0}


class _LegacyNamespaceVector:
    def __init__(self, record_id: str) -> None:
        self.record_id = record_id

    def search(self, query: str, limit: int = 10, namespace: str | None = None):
        return {self.record_id: 1.0}


def test_vector_leg_forwards_namespace_before_top_k(runtime: SeamRuntime) -> None:
    _seed_text(runtime, "Scoped compiler evidence.", "local://scoped", ns="alpha")
    record = next(
        item
        for item in runtime.store.load_ir(ns="alpha", scope="thread").records
        if item.kind == RecordKind.CLM
    )
    vector = _NamespaceVector(record.id)
    adapter = SeamVectorSearchAdapter(runtime.store, vector)
    plan = build_plan(
        "compiler", scope="thread", namespace="alpha", mode="vector"
    )

    hits = adapter.search(plan, limit=5)
    assert vector.namespace == "alpha"
    assert vector.scope == "thread"
    assert [hit.record.id for hit in hits] == [record.id]


def test_scope_search_keeps_legacy_custom_vector_adapter_compatible(
    runtime: SeamRuntime,
) -> None:
    _seed_text(runtime, "Legacy scoped evidence.", "local://legacy", ns="alpha")
    record = next(
        item
        for item in runtime.store.load_ir(ns="alpha", scope="thread").records
        if item.kind == RecordKind.CLM
    )
    adapter = SeamVectorSearchAdapter(
        runtime.store, _LegacyNamespaceVector(record.id)
    )
    plan = build_plan(
        "evidence", scope="thread", namespace="alpha", mode="vector"
    )
    assert [hit.record.id for hit in adapter.search(plan, limit=5)] == [record.id]


def test_vector_reindexes_an_unchanged_record_when_namespace_moves(
    runtime: SeamRuntime,
) -> None:
    record = MIRLRecord(
        id="clm:namespace-move",
        kind=RecordKind.CLM,
        ns="alpha",
        scope="thread",
        attrs={"subject": "compiler", "predicate": "has", "object": "rollback"},
    )
    runtime.persist_ir(IRBatch([record]))
    assert record.id in runtime.vector_adapter.search(
        "compiler rollback", namespace="alpha"
    )

    moved = MIRLRecord.from_dict(record.to_dict())
    moved.ns = "beta"
    runtime.persist_ir(IRBatch([moved]))
    assert record.id not in runtime.vector_adapter.search(
        "compiler rollback", namespace="alpha"
    )
    assert record.id in runtime.vector_adapter.search(
        "compiler rollback", namespace="beta"
    )


class _CountingHashEmbedding(HashEmbeddingModel):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def embed(self, text: str) -> list[float]:
        self.calls += 1
        return super().embed(text)


def test_boundary_only_vector_move_does_not_reembed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    model = _CountingHashEmbedding()
    active_runtime = SeamRuntime(
        tmp_path / "boundary-move.db",
        embedding_model=model,
        allow_pgvector_env=False,
    )
    try:
        record = MIRLRecord(
            id="clm:cheap-boundary-move",
            kind=RecordKind.CLM,
            ns="alpha",
            scope="thread",
            attrs={"subject": "same", "predicate": "is", "object": "content"},
        )
        active_runtime.persist_ir(IRBatch([record]))
        initial_calls = model.calls
        moved = MIRLRecord.from_dict(record.to_dict())
        moved.ns = "beta"
        moved.scope = "project"
        active_runtime.persist_ir(IRBatch([moved]))
        assert model.calls == initial_calls
    finally:
        active_runtime.close()


def test_native_vector_top_k_prefilters_scope(runtime: SeamRuntime) -> None:
    records = [
        MIRLRecord(
            id=f"clm:z-project-{index:02d}",
            kind=RecordKind.CLM,
            ns="shared",
            scope="project",
            attrs={"subject": "same", "predicate": "is", "object": "evidence"},
        )
        for index in range(20)
    ]
    target = MIRLRecord(
        id="clm:a-thread-target",
        kind=RecordKind.CLM,
        ns="shared",
        scope="thread",
        attrs={"subject": "same", "predicate": "is", "object": "evidence"},
    )
    runtime.persist_ir(IRBatch([*records, target]))
    result = RetrievalOrchestrator(runtime).search(
        "same evidence",
        namespace="shared",
        scope="thread",
        budget=1,
        mode="vector",
    )
    assert [candidate.record.id for candidate in result.candidates] == [target.id]


def test_sqlite_scope_column_upgrade_backfills_from_canonical_ir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / "vector-scope-upgrade.db"
    first = SeamRuntime(path, allow_pgvector_env=False)
    record = MIRLRecord(
        id="clm:scope-upgrade",
        kind=RecordKind.CLM,
        ns="shared",
        scope="thread",
        attrs={"subject": "scope", "predicate": "is", "object": "preserved"},
    )
    first.persist_ir(IRBatch([record]))
    first.close()
    with sqlite3.connect(path) as connection:
        connection.execute("alter table vector_index drop column scope")

    second = SeamRuntime(path, allow_pgvector_env=False)
    try:
        assert record.id in second.vector_adapter.search(
            "scope preserved", namespace="shared", scope="thread"
        )
    finally:
        second.close()


class _BoundaryCollection:
    def __init__(self) -> None:
        self.options = None

    def query(self, **options):
        self.options = options
        return {"ids": [[]], "distances": [[]]}


class _Embedding:
    def embed(self, text: str) -> list[float]:
        return [1.0]


def test_chroma_leg_filters_namespace_and_scope_before_top_k(
    runtime: SeamRuntime,
) -> None:
    collection = _BoundaryCollection()
    adapter = ChromaSemanticAdapter(runtime.store, _Embedding())
    adapter._collection = lambda: collection
    plan = build_plan(
        "compiler", scope="thread", namespace="alpha", mode="vector"
    )

    assert adapter.search(plan, limit=5) == []
    assert collection.options["where"] == {
        "$and": [
            {"vector_text_version": {"$eq": "mirl-vector-text/2"}},
            {"ns": {"$eq": "alpha"}},
            {"scope": {"$eq": "thread"}},
        ]
    }


def test_candidate_fingerprint_is_order_sensitive_and_content_free() -> None:
    first = candidate_set_fingerprint(
        [("clm:a", 1.0, {"sql": 1.0}), ("clm:b", 0.5, {"vector": 0.5})]
    )
    second = candidate_set_fingerprint(
        [("clm:b", 0.5, {"vector": 0.5}), ("clm:a", 1.0, {"sql": 1.0})]
    )
    assert first != second
    assert len(first) == 64


def test_r1_database_reopens_with_additive_r2_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / "r1-upgrade.db"
    first = SeamRuntime(path, allow_pgvector_env=False)
    session = SeamSDK(runtime=first).start_reasoning(
        "Preserve the R1 run.", ns="upgrade", scope="thread"
    )
    run_id = session.run_id
    first.close()

    with sqlite3.connect(path) as connection:
        connection.execute("drop trigger reasoning_retrieval_finalize_guard")
        connection.execute("drop table reasoning_retrieval_candidate")
        connection.execute("drop table reasoning_retrieval")

    second = SeamRuntime(path, allow_pgvector_env=False)
    try:
        resumed = SeamSDK(runtime=second).reasoning(run_id)
        assert resumed.graph()["nodes"][0]["kind"] == "objective"
        assert resumed.retrieve("no upgraded evidence", mode="mix").reasoning[
            "schema_version"
        ] == 1
    finally:
        second.close()

    third = SeamRuntime(path, allow_pgvector_env=False)
    try:
        assert SeamSDK(runtime=third).reasoning(run_id).retrievals(limit=1)
    finally:
        third.close()


def test_reasoning_retrieval_pagination_uses_monotonic_run_sequence(
    runtime: SeamRuntime,
) -> None:
    session = SeamSDK(runtime=runtime).start_reasoning(
        "Page retrieval decisions.", ns="page", scope="thread"
    )
    first = session.retrieve("first empty query", mode="mix").reasoning
    second = session.retrieve("second empty query", mode="mix").reasoning

    page = session.retrievals(limit=1)
    assert [item["retrieval_id"] for item in page] == [first["retrieval_id"]]
    next_page = session.retrievals(limit=1, after=str(first["retrieval_id"]))
    assert [item["retrieval_id"] for item in next_page] == [second["retrieval_id"]]
    assert [first["seq"], second["seq"]] == [1, 2]


def test_candidate_snapshot_reports_post_decision_boundary_drift(
    runtime: SeamRuntime,
) -> None:
    record = MIRLRecord(
        id="clm:evidence-drift",
        kind=RecordKind.CLM,
        ns="alpha",
        scope="thread",
        attrs={"subject": "compiler", "predicate": "has", "object": "evidence"},
    )
    runtime.persist_ir(IRBatch([record]))
    session = SeamSDK(runtime=runtime).start_reasoning(
        "Audit evidence identity.", ns="alpha", scope="thread"
    )
    retrieval = session.retrieve("compiler evidence", budget=1).reasoning

    moved = MIRLRecord.from_dict(record.to_dict())
    moved.ns = "beta"
    runtime.store.persist_ir(IRBatch([moved]))
    detail = session.retrieval(str(retrieval["retrieval_id"]))
    candidate = detail["candidates"][0]
    assert candidate["record_namespace"] == "alpha"
    assert candidate["record_scope"] == "thread"
    assert candidate["record_integrity"] == "boundary_changed"


def test_candidate_hash_rejects_search_to_record_race(runtime: SeamRuntime) -> None:
    record = MIRLRecord(
        id="clm:race",
        kind=RecordKind.CLM,
        ns="work",
        scope="thread",
        attrs={"subject": "old", "predicate": "is", "object": "evidence"},
    )
    runtime.store.persist_ir(IRBatch([record]))
    stale_candidate = ReasoningRetrievalCandidate(
        record_id=record.id,
        rank=1,
        score=1.0,
        selected=True,
        sources={"sql": 1.0},
        record_sha256=mirl_record_fingerprint(record.to_dict()),
        reasons=("lexical_score",),
    )
    changed = MIRLRecord.from_dict(record.to_dict())
    changed.attrs["subject"] = "new"
    runtime.store.persist_ir(IRBatch([changed]))
    session = SeamSDK(runtime=runtime).start_reasoning(
        "Reject stale candidates.", ns="work", scope="thread"
    )

    with pytest.raises(ValueError, match="changed before recording"):
        runtime.store.record_reasoning_retrieval(
            run_id=session.run_id,
            query="evidence",
            normalized_query="evidence",
            filter_ids=(),
            filter_kinds=(),
            filter_predicate=None,
            filter_subject=None,
            filter_object_text=None,
            leg_limits={"sql": 5},
            mode="hybrid",
            intent="hybrid",
            budget=1,
            graph_hops=1,
            semantic_graph_seeding=False,
            semantic_backend="seam",
            semantic_adapter="sqlite-vector",
            embedding_model="hash-bow-v1",
            embedding_dimension=64,
            embedding_revision=None,
            candidates=(stale_candidate,),
            total_candidates=1,
            candidates_truncated=False,
            candidate_set_sha256=candidate_set_fingerprint(
                [(record.id, 1.0, {"sql": 1.0})]
            ),
            leg_latency_ms={"sql": 1.0},
            total_latency_ms=1.0,
            policy=FUSION_POLICY,
        )
    assert len(session.graph()["nodes"]) == 1


def test_candidate_rows_recompute_pinned_fusion_score(runtime: SeamRuntime) -> None:
    record = MIRLRecord(
        id="clm:bad-fusion",
        kind=RecordKind.CLM,
        ns="work",
        scope="thread",
        attrs={"subject": "fusion", "predicate": "is", "object": "audited"},
    )
    runtime.store.persist_ir(IRBatch([record]))
    malformed = ReasoningRetrievalCandidate(
        record_id=record.id,
        rank=1,
        score=999.0,
        selected=True,
        sources={"sql": 1.0},
        record_sha256=mirl_record_fingerprint(record.to_dict()),
        reasons=("lexical_score",),
    )
    with runtime.store._pool.checkout() as connection:
        with pytest.raises(ValueError, match="pinned policy"):
            _retrieval_candidate_rows(
                connection,
                ns="work",
                scope="thread",
                candidates=(malformed,),
                budget=1,
                total_candidates=1,
            )


def test_sdk_records_a_truncated_real_orchestrator_pool(
    runtime: SeamRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records = [
        MIRLRecord(
            id=f"clm:pool-{index:03d}",
            kind=RecordKind.CLM,
            ns="work",
            scope="thread",
            attrs={"subject": f"candidate {index}", "predicate": "is", "object": "ranked"},
        )
        for index in range(256)
    ]
    runtime.store.persist_ir(IRBatch(records))
    sql_records = records[:128]
    vector_records = records[128:]
    orchestrator_type = RetrievalOrchestrator

    def orchestrator_factory(active_runtime, semantic_backend="seam"):
        return orchestrator_type(
            active_runtime,
            sql_adapter=_StaticLeg("sql", sql_records),
            semantic_adapter=_StaticLeg("vector", vector_records),
            semantic_backend=semantic_backend,
        )

    import seam_runtime.retrieval_orchestrator as retrieval_module

    monkeypatch.setattr(
        retrieval_module, "RetrievalOrchestrator", orchestrator_factory
    )
    session = SeamSDK(runtime=runtime).start_reasoning(
        "Persist a bounded candidate prefix.", ns="work", scope="thread"
    )
    retrieval = session.retrieve("ranked", budget=64, mode="hybrid").reasoning
    assert retrieval["total_candidates"] == 256
    assert retrieval["recorded_candidates"] == 128
    assert retrieval["selected_count"] == 64
    assert retrieval["candidates_truncated"] is True
    assert [item["rank"] for item in retrieval["candidates"]] == list(range(1, 129))


def test_ordinary_search_keeps_300_populated_results(runtime: SeamRuntime) -> None:
    records = [
        MIRLRecord(id=f"clm:legacy-{index:03d}", kind=RecordKind.CLM)
        for index in range(300)
    ]
    orchestrator = RetrievalOrchestrator(
        runtime,
        sql_adapter=_StaticLeg("sql", records),
        semantic_adapter=_StaticLeg("vector", []),
    )
    result = orchestrator.search("legacy", budget=300, mode="hybrid")
    assert len(result.candidates) == 300
    assert result.candidates[0].record.id == "clm:legacy-000"
    assert result.candidates[-1].record.id == "clm:legacy-299"
    assert orchestrator.plan("legacy").semantic_graph_seeding is False


def test_sdk_rejects_oversized_query_and_filter_plan_before_search(
    runtime: SeamRuntime,
) -> None:
    session = SeamSDK(runtime=runtime).start_reasoning(
        "Bound retrieval inputs.", ns="work", scope="thread"
    )
    with pytest.raises(ValueError, match="4096"):
        session.retrieve(" " * 4097)
    with pytest.raises(ValueError, match="at most 64 id filters"):
        session.retrieve("id:" + ",".join(f"clm:{index}" for index in range(65)))
    assert len(session.graph()["nodes"]) == 1


def test_sql_leg_breaks_cutoff_ties_by_record_id(runtime: SeamRuntime) -> None:
    timestamp = "2026-01-01T00:00:00Z"
    records = [
        MIRLRecord(
            id=record_id,
            kind=RecordKind.CLM,
            ns="work",
            scope="thread",
            attrs={"subject": "same", "predicate": "is", "object": "evidence"},
            created_at=timestamp,
            updated_at=timestamp,
        )
        for record_id in ("clm:b", "clm:a")
    ]
    runtime.store.persist_ir(IRBatch(records))
    plan = build_plan(
        "same evidence", scope="thread", namespace="work", mode="hybrid"
    )
    hits = SQLiteIRAdapter(runtime.store).search(plan, limit=1)
    assert [hit.record.id for hit in hits] == ["clm:a"]


def test_public_sdk_exports_reasoned_retrieval() -> None:
    from seam import ReasonedRetrieval as SeamModuleReasonedRetrieval
    from seam_runtime import ReasonedRetrieval as RuntimeReasonedRetrieval

    assert SeamModuleReasonedRetrieval is RuntimeReasonedRetrieval
