from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from seam_runtime.knowledge_graph import _time_reached
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.reconcile import PREDICATE_CARDINALITY_EXTENSION, reconcile_ir
from seam_runtime.retrieval import search_batch
from seam_runtime.runtime import SeamRuntime
from seam_runtime.temporal import parse_iso


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-01-01T00:00:00Z", datetime(2026, 1, 1)),
        ("2025-12-31T19:00:00-05:00", datetime(2026, 1, 1)),
        ("2026-01-01T00:00:00", datetime(2026, 1, 1)),
        ("2026-01-01", datetime(2026, 1, 1)),
        (None, None),
        ("", None),
        ("not-a-timestamp", None),
    ],
)
def test_one_timestamp_policy_normalizes_supported_forms_to_utc_naive(
    value: str | None,
    expected: datetime | None,
) -> None:
    assert parse_iso(value) == expected


def test_equivalent_instants_produce_identical_temporal_scores_and_id_order() -> None:
    batch = IRBatch(
        [
            _event("evt:b", "2026-01-01T00:00:00Z"),
            _event("evt:a", "2025-12-31T19:00:00-05:00"),
        ]
    )

    result = search_batch(
        batch,
        query="unmatched",
        temporal_reference=datetime(2026, 1, 1),
        limit=2,
    )

    assert [candidate.record.id for candidate in result.candidates] == [
        "evt:a",
        "evt:b",
    ]
    assert result.candidates[0].score == result.candidates[1].score


def test_legacy_search_normalizes_aware_reference_and_window_inputs() -> None:
    batch = IRBatch(
        [
            _event("evt:z", "2026-01-01T00:00:00Z"),
            _event("evt:offset", "2025-12-31T19:00:00-05:00"),
        ]
    )
    aware = datetime(2026, 1, 1, tzinfo=timezone.utc)

    reference = search_batch(
        batch,
        query="unmatched",
        temporal_reference=aware,
        limit=2,
    )
    window = search_batch(
        batch,
        query="unmatched",
        temporal_window=(
            datetime(2025, 12, 31, 23, 59, tzinfo=timezone.utc),
            datetime(2026, 1, 1, 0, 1),
        ),
        limit=2,
    )

    assert [candidate.record.id for candidate in reference.candidates] == [
        "evt:offset",
        "evt:z",
    ]
    assert [candidate.record.id for candidate in window.candidates] == [
        "evt:offset",
        "evt:z",
    ]


def test_reconciliation_treats_equivalent_missing_and_invalid_times_as_not_newer() -> None:
    report = reconcile_ir(
        IRBatch(
            [
                _claim("clm:z", "blue", "2026-01-01T00:00:00Z"),
                _claim("clm:offset", "red", "2025-12-31T19:00:00-05:00"),
                _claim("clm:missing", "green", None),
                _claim("clm:invalid", "yellow", "not-a-timestamp"),
            ]
        )
    )

    assert report.actions
    assert {action["type"] for action in report.actions} == {"contradicts"}


def test_reconciliation_metadata_uses_instant_order_not_lexical_order() -> None:
    older = _claim("clm:older", "blue", "2025-12-31T23:30:00Z")
    older.created_at = "2026-01-01T00:30:00+01:00"
    older.updated_at = "2026-01-01T00:30:00+01:00"
    newer = _claim("clm:newer", "red", "2025-12-31T23:45:00Z")
    newer.created_at = "2025-12-31T23:45:00Z"
    newer.updated_at = "2025-12-31T23:45:00Z"

    report = reconcile_ir(IRBatch([older, newer]))

    assert report.added_records
    assert {record.created_at for record in report.added_records} == {
        "2025-12-31T23:30:00.000000Z"
    }
    assert {record.updated_at for record in report.added_records} == {
        "2025-12-31T23:45:00.000000Z"
    }


def test_graph_as_of_equivalent_horizons_produce_identical_truth(
    tmp_path: Path,
) -> None:
    runtime = SeamRuntime(tmp_path / "temporal-policy.db", allow_pgvector_env=False)
    try:
        runtime.persist_ir(
            IRBatch(
                [
                    MIRLRecord(
                        id="ent:alice",
                        kind=RecordKind.ENT,
                        ns="temporal",
                        scope="thread",
                        created_at="2025-01-01T00:00:00Z",
                        updated_at="2025-01-01T00:00:00Z",
                        t0="2025-01-01T00:00:00Z",
                        attrs={"entity_type": "person", "label": "Alice"},
                    ),
                    MIRLRecord(
                        id="ent:bob",
                        kind=RecordKind.ENT,
                        ns="temporal",
                        scope="thread",
                        created_at="2025-01-01T00:00:00Z",
                        updated_at="2025-01-01T00:00:00Z",
                        t0="2025-01-01T00:00:00Z",
                        attrs={"entity_type": "person", "label": "Bob"},
                    ),
                    MIRLRecord(
                        id="rel:offset",
                        kind=RecordKind.REL,
                        ns="temporal",
                        scope="thread",
                        created_at="2026-01-01T00:30:00+01:00",
                        updated_at="2026-01-01T00:30:00+01:00",
                        t0="2026-01-01T00:30:00+01:00",
                        attrs={
                            "src": "ent:alice",
                            "predicate": "mentors",
                            "dst": "ent:bob",
                        },
                    ),
                    MIRLRecord(
                        id="rel:invalid",
                        kind=RecordKind.REL,
                        ns="temporal",
                        scope="thread",
                        created_at="2025-01-01T00:00:00Z",
                        updated_at="2025-01-01T00:00:00Z",
                        t0="not-a-timestamp",
                        attrs={
                            "src": "ent:alice",
                            "predicate": "manages",
                            "dst": "ent:bob",
                        },
                    ),
                ]
            )
        )

        utc = runtime.store.knowledge_graph(
            root_id="ent:alice",
            namespace="temporal",
            scope="thread",
            at="2025-12-31T23:45:00Z",
            include_history=True,
        )
        offset = runtime.store.knowledge_graph(
            root_id="ent:alice",
            namespace="temporal",
            scope="thread",
            at="2026-01-01T00:45:00+01:00",
            include_history=True,
        )

        assert "mentors" in {edge["predicate"] for edge in utc["edges"]}
        assert "mentors" in {edge["predicate"] for edge in offset["edges"]}
        assert "manages" not in {edge["predicate"] for edge in utc["edges"]}
        assert "manages" not in {edge["predicate"] for edge in offset["edges"]}

        utc_detail = runtime.store.knowledge_node(
            "ent:alice",
            at="2025-12-31T23:45:00Z",
        )
        offset_detail = runtime.store.knowledge_node(
            "ent:alice",
            at="2026-01-01T00:45:00+01:00",
        )
        assert {edge["predicate"] for edge in utc_detail["outgoing"]} == {
            edge["predicate"] for edge in offset_detail["outgoing"]
        }
    finally:
        runtime.close()


def test_graph_as_of_distinguishes_open_end_from_invalid_end(
    tmp_path: Path,
) -> None:
    runtime = SeamRuntime(tmp_path / "open-intervals.db", allow_pgvector_env=False)
    try:
        runtime.persist_ir(
            IRBatch(
                [
                    _entity("ent:none", "Open None", None),
                    _entity("ent:empty", "Open Empty", ""),
                    _entity("ent:invalid", "Invalid End", "not-a-timestamp"),
                ]
            )
        )

        graph = runtime.store.knowledge_graph(
            namespace="temporal",
            scope="thread",
            at="2026-01-01T00:00:00Z",
            include_history=True,
            limit=100,
        )

        node_ids = {str(node["id"]) for node in graph["nodes"]}
        assert {"ent:none", "ent:empty"} <= node_ids
        assert "ent:invalid" not in node_ids
    finally:
        runtime.close()


def test_graph_as_of_falls_back_from_blank_start_to_created_at(
    tmp_path: Path,
) -> None:
    runtime = SeamRuntime(tmp_path / "blank-starts.db", allow_pgvector_env=False)
    try:
        alice = _entity("ent:alice", "Alice", None)
        alice.t0 = ""
        bob = _entity("ent:bob", "Bob", None)
        bob.t0 = "   "
        empty_edge = MIRLRecord(
            id="rel:empty-start",
            kind=RecordKind.REL,
            ns="temporal",
            scope="thread",
            created_at="2025-01-01T00:00:00Z",
            updated_at="2025-01-01T00:00:00Z",
            t0="",
            attrs={"src": alice.id, "predicate": "mentors", "dst": bob.id},
        )
        whitespace_edge = MIRLRecord(
            id="rel:whitespace-start",
            kind=RecordKind.REL,
            ns="temporal",
            scope="thread",
            created_at="2025-01-01T00:00:00Z",
            updated_at="2025-01-01T00:00:00Z",
            t0="   ",
            attrs={"src": bob.id, "predicate": "supports", "dst": alice.id},
        )
        runtime.persist_ir(IRBatch([alice, bob, empty_edge, whitespace_edge]))

        graph = runtime.store.knowledge_graph(
            namespace="temporal",
            scope="thread",
            at="2026-01-01T00:00:00Z",
            include_history=True,
            limit=100,
        )

        assert {"ent:alice", "ent:bob"} <= {
            str(node["id"]) for node in graph["nodes"]
        }
        assert {"mentors", "supports"} <= {
            str(edge["predicate"]) for edge in graph["edges"]
        }
    finally:
        runtime.close()


def test_graph_as_of_works_inside_a_bound_read_snapshot(tmp_path: Path) -> None:
    runtime = SeamRuntime(tmp_path / "snapshot-graph.db", allow_pgvector_env=False)
    try:
        runtime.persist_ir(IRBatch([_entity("ent:snapshot", "Snapshot", None)]))

        with runtime.store.read_snapshot():
            graph = runtime.store.knowledge_graph(
                root_id="ent:snapshot",
                at="2026-01-01T00:00:00Z",
                include_history=True,
            )

        assert "ent:snapshot" in {str(node["id"]) for node in graph["nodes"]}
    finally:
        runtime.close()


def test_graph_projection_metadata_uses_canonical_instant_extremes(
    tmp_path: Path,
) -> None:
    runtime = SeamRuntime(tmp_path / "graph-metadata.db", allow_pgvector_env=False)
    try:
        subject = _entity("ent:alice", "Alice", None)
        older = _claim("clm:older", "Orbit", "2025-12-31T23:30:00Z")
        older.attrs["subject"] = subject.id
        older.attrs["predicate"] = "owns"
        older.created_at = "2026-01-01T00:30:00+01:00"
        older.updated_at = "2026-01-01T00:30:00+01:00"
        newer = _claim("clm:newer", "Orbit", "2025-12-31T23:45:00Z")
        newer.attrs["subject"] = subject.id
        newer.attrs["predicate"] = "owns"
        newer.created_at = "2025-12-31T23:45:00Z"
        newer.updated_at = "2025-12-31T23:45:00Z"
        runtime.persist_ir(IRBatch([subject, older, newer]))

        graph = runtime.store.knowledge_graph(
            query="Orbit",
            namespace="temporal",
            scope="thread",
            include_history=True,
            limit=100,
        )
        orbit = next(
            node
            for node in graph["nodes"]
            if node["kind"] == "value" and node["label"] == "Orbit"
        )

        assert orbit["created_at"] == "2025-12-31T23:30:00.000000Z"
        assert orbit["updated_at"] == "2025-12-31T23:45:00.000000Z"
    finally:
        runtime.close()


def test_blank_expiration_is_open_for_products_trace_and_self_improvement(
    tmp_path: Path,
) -> None:
    runtime = SeamRuntime(tmp_path / "blank-consumers.db", allow_pgvector_env=False)
    try:
        batch = runtime.compile_nl(
            "Alice owns Orbit.",
            source_ref="local://temporal/blank-consumers",
            ns="temporal",
            scope="thread",
        )
        claim = next(
            record
            for record in batch.records
            if record.kind == RecordKind.CLM
        )
        runtime.persist_ir(batch)
        with runtime.store._pool.checkout() as connection:
            connection.execute(
                "update knowledge_edges set expired_at = '   ' "
                "where source_record_id = ?",
                (claim.id,),
            )
            connection.commit()

        rebuild = runtime.store.rebuild_graph_products(
            namespace="temporal",
            scope="thread",
        )
        trace = runtime.trace(claim.id)
        probes = runtime.store.generate_graph_probes(
            namespace="temporal",
            scope="thread",
            sample=100,
        )

        assert rebuild["accepted_fact_count"] >= 1
        assert trace.edges
        assert probes
    finally:
        runtime.close()


def test_entity_coreference_metadata_uses_instant_order(tmp_path: Path) -> None:
    runtime = SeamRuntime(tmp_path / "entity-metadata.db", allow_pgvector_env=False)
    try:
        canonical = _entity("ent:canonical", "Alice", None)
        canonical.updated_at = "2026-01-01T00:30:00+01:00"
        canonical.prov = ["prov:old"]
        mention = _entity("ent:mention", "Alice", None)
        mention.updated_at = "2025-12-31T23:45:00Z"
        mention.prov = ["prov:new"]
        prov_old = _provenance("prov:old", canonical.id)
        prov_new = _provenance("prov:new", mention.id)

        runtime.persist_ir(IRBatch([canonical, prov_old]))
        runtime.persist_ir(IRBatch([mention, prov_new]))
        stored = runtime.store.load_ir(ns="temporal", scope="thread").by_id()

        assert "ent:mention" not in stored
        assert stored["ent:canonical"].updated_at == (
            "2025-12-31T23:45:00.000000Z"
        )
        assert stored["ent:canonical"].prov == ["prov:new", "prov:old"]
    finally:
        runtime.close()


def test_stale_horizon_uses_policy_and_invalid_values_fail_closed() -> None:
    horizon = "2026-01-01T00:00:00Z"

    assert _time_reached("2025-12-31T19:00:00-05:00", horizon) is True
    assert _time_reached("2030-01-01", horizon) is False
    assert _time_reached("not-a-timestamp", horizon) is True


def test_invalid_graph_horizon_is_rejected_before_query(tmp_path: Path) -> None:
    runtime = SeamRuntime(tmp_path / "invalid-horizon.db", allow_pgvector_env=False)
    try:
        with pytest.raises(ValueError, match="timestamp"):
            runtime.store.knowledge_graph(at="not-a-timestamp")
    finally:
        runtime.close()


def test_context_candidates_emit_the_shared_canonical_timestamp(tmp_path: Path) -> None:
    runtime = SeamRuntime(tmp_path / "context-time.db", allow_pgvector_env=False)
    try:
        batch = runtime.compile_nl(
            "Alice owns Orbit.",
            source_ref="local://temporal/context",
            ns="temporal",
            scope="thread",
        )
        runtime.persist_ir(batch)
        claim_id = next(record.id for record in batch.records if record.kind == RecordKind.CLM)
        with runtime.store._pool.checkout() as connection:
            connection.execute(
                "update ir_records set t0 = ?, updated_at = ? where id = ?",
                (
                    "2026-01-01T00:00:00z",
                    "2027-01-01T00:00:00Z",
                    claim_id,
                ),
            )
            connection.commit()
        runtime.store.rebuild_graph_products(namespace="temporal", scope="thread")

        candidates = runtime.store.context_candidates(
            namespace="temporal",
            scope="thread",
        )
        claim_candidates = [
            candidate
            for candidate in candidates
            if candidate.candidate_id == f"fact:{claim_id}"
        ]

        assert claim_candidates
        assert {candidate.occurred_at for candidate in claim_candidates} == {
            "2026-01-01T00:00:00.000000Z"
        }
    finally:
        runtime.close()


def _event(record_id: str, t0: str) -> MIRLRecord:
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.EVT,
        ns="temporal",
        scope="thread",
        t0=t0,
        attrs={"summary": "event"},
    )


def _claim(record_id: str, value: str, t0: str | None) -> MIRLRecord:
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.CLM,
        ns="temporal",
        scope="thread",
        t0=t0,
        ext={PREDICATE_CARDINALITY_EXTENSION: "functional"},
        attrs={
            "subject": "ent:person",
            "predicate": "color",
            "object": value,
        },
    )


def _entity(record_id: str, label: str, t1: str | None) -> MIRLRecord:
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.ENT,
        ns="temporal",
        scope="thread",
        created_at="2025-01-01T00:00:00Z",
        updated_at="2025-01-01T00:00:00Z",
        t0="2025-01-01T00:00:00Z",
        t1=t1,
        attrs={"entity_type": "concept", "label": label},
    )


def _provenance(record_id: str, entity_id: str) -> MIRLRecord:
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.PROV,
        ns="temporal",
        scope="thread",
        attrs={"entity": entity_id, "activity": "test", "agent": "test"},
    )
