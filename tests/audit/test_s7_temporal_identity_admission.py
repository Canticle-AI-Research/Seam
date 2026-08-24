"""Track S S7 temporal, identity, boundary, and graph-admission contracts."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.nl import compile_nl
from seam_runtime.reconcile import PREDICATE_CARDINALITY_EXTENSION, reconcile_ir
from seam_runtime.reference_contracts import CanonicalReferenceIntegrityError
from seam_runtime.retrieval_orchestrator.adapters import (
    _CANONICAL_RELATION_EDGE_FROM,
    _canonical_relation_edge_where,
)
from seam_runtime.retrieval_orchestrator.planner import build_plan
from seam_runtime.runtime import SeamRuntime
from seam_runtime.storage import SQLiteStore


def _claim(
    record_id: str,
    value: object,
    *,
    t0: str | None,
    ns: str = "s7",
    scope: str = "thread",
    predicate: str = "color",
    cardinality: str = "functional",
    confidence: float = 1.0,
) -> MIRLRecord:
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.CLM,
        ns=ns,
        scope=scope,
        t0=t0,
        conf=confidence,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-04-01T00:00:00+00:00",
        ext={PREDICATE_CARDINALITY_EXTENSION: cardinality},
        attrs={"subject": "ent:person", "predicate": predicate, "object": value},
    )


def _state_value(report, predicate: str) -> object:
    state = next(record for record in report.added_records if record.kind is RecordKind.STA)
    return state.attrs["fields"][predicate]


def test_functional_reconciliation_uses_event_time_and_replays_exactly() -> None:
    older = _claim("clm:older", "blue", t0="2026-01-01T00:00:00+00:00")
    newer = _claim("clm:newer", "red", t0="2026-02-01T00:00:00+00:00")

    forward = reconcile_ir(IRBatch([older, newer]))
    reverse = reconcile_ir(IRBatch([newer, older]))

    assert forward.to_dict() == reverse.to_dict()
    assert forward.actions == [
        {"type": "supersedes", "winner": newer.id, "loser": older.id}
    ]
    assert _state_value(forward, "color") == "red"


def test_equal_and_missing_event_time_never_fabricate_supersession() -> None:
    equal_low = _claim(
        "clm:equal-low",
        "blue",
        t0="2026-02-01T00:00:00+00:00",
        confidence=0.2,
    )
    equal_high = _claim(
        "clm:equal-high",
        "red",
        t0="2026-02-01T00:00:00+00:00",
        confidence=0.9,
    )
    missing = _claim("clm:missing", "green", t0=None, confidence=1.0)

    report = reconcile_ir(IRBatch([missing, equal_low, equal_high]))

    assert _state_value(report, "color") == "red"
    assert {action["type"] for action in report.actions} == {"contradicts"}
    assert {action["loser"] for action in report.actions} == {
        equal_low.id,
        missing.id,
    }


def test_multivalued_reconciliation_retains_distinct_values() -> None:
    engineer = _claim(
        "clm:engineer",
        "engineer",
        t0="2026-01-01T00:00:00+00:00",
        predicate="roles",
        cardinality="multivalued",
    )
    mentor = _claim(
        "clm:mentor",
        "mentor",
        t0="2026-02-01T00:00:00+00:00",
        predicate="roles",
        cardinality="multivalued",
    )

    report = reconcile_ir(IRBatch([mentor, engineer]))

    assert report.actions == []
    assert _state_value(report, "roles") == ["engineer", "mentor"]


def test_reconciliation_never_groups_across_namespace_or_scope() -> None:
    claims = [
        _claim("clm:a", "red", t0=None, ns="a", scope="thread"),
        _claim("clm:b", "blue", t0=None, ns="b", scope="thread"),
        _claim("clm:c", "green", t0=None, ns="a", scope="project"),
    ]

    report = reconcile_ir(IRBatch(claims))

    assert report.actions == []
    assert report.added_records == []


def test_explicit_identity_separates_same_name_people_and_accumulates_mentions(
    tmp_path: Path,
) -> None:
    runtime = SeamRuntime(tmp_path / "identity.db", allow_pgvector_env=False)
    try:
        first = compile_nl(
            "Alex Morgan joined the review.",
            source_ref="fixture://s7/alex/one",
            ns="s7",
            scope="thread",
            allow_env_extractor=False,
        )
        second = compile_nl(
            "Alex Morgan approved the plan.",
            source_ref="fixture://s7/alex/two",
            ns="s7",
            scope="thread",
            allow_env_extractor=False,
        )
        for batch in (first, second):
            alex = next(
                record
                for record in batch.kind(RecordKind.ENT)
                if record.attrs.get("label") == "Alex Morgan"
            )
            alex.ext["seam.entity_identity"] = "person:alex-primary"
            runtime.persist_ir(batch)

        other = MIRLRecord(
            id="ent:alex-other",
            kind=RecordKind.ENT,
            ns="s7",
            scope="thread",
            ext={"seam.entity_identity": "person:alex-other"},
            attrs={"entity_type": "person", "label": "Alex Morgan"},
        )
        runtime.persist_ir(IRBatch([other]))

        alexes = [
            record
            for record in runtime.store.load_ir(ns="s7", scope="thread").records
            if record.kind is RecordKind.ENT
            and record.attrs.get("label") == "Alex Morgan"
        ]
        assert len(alexes) == 2
        primary = next(
            record
            for record in alexes
            if record.ext.get("seam.entity_identity") == "person:alex-primary"
        )
        assert len(primary.evidence) == 2
    finally:
        runtime.close()


def test_same_label_in_different_scopes_never_merges(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "scope-identity.db")
    try:
        records = [
            MIRLRecord(
                id=f"ent:alex:{scope}",
                kind=RecordKind.ENT,
                ns="s7",
                scope=scope,
                attrs={"entity_type": "person", "label": "Alex Morgan"},
            )
            for scope in ("thread", "project")
        ]
        store.persist_ir(IRBatch(records))
        assert {
            record.id
            for record in store.load_ir(ns="s7").records
            if record.kind is RecordKind.ENT
        } == {record.id for record in records}
    finally:
        store.close()


def test_cross_boundary_relation_fails_before_persistence(tmp_path: Path) -> None:
    store = SQLiteStore(tmp_path / "cross-boundary.db")
    try:
        source = MIRLRecord(
            id="ent:source",
            kind=RecordKind.ENT,
            ns="s7",
            scope="thread",
            attrs={"entity_type": "person", "label": "Source"},
        )
        target = MIRLRecord(
            id="ent:target",
            kind=RecordKind.ENT,
            ns="s7",
            scope="project",
            attrs={"entity_type": "person", "label": "Target"},
        )
        store.persist_ir(IRBatch([source, target]))
        relation = MIRLRecord(
            id="rel:cross-boundary",
            kind=RecordKind.REL,
            ns="s7",
            scope="thread",
            attrs={"src": source.id, "predicate": "mentors", "dst": target.id},
        )

        with pytest.raises(CanonicalReferenceIntegrityError, match="crosses"):
            store.persist_ir(IRBatch([relation]))
        assert store.load_ir(ids=[relation.id]).records == []

        foreign_raw = MIRLRecord(
            id="raw:foreign-provenance",
            kind=RecordKind.RAW,
            ns="s7",
            scope="project",
            attrs={"content": "Foreign source."},
        )
        foreign_prov = MIRLRecord(
            id="prov:foreign-provenance",
            kind=RecordKind.PROV,
            ns="s7",
            scope="project",
            attrs={"entity": foreign_raw.id, "activity": "fixture"},
        )
        store.persist_ir(IRBatch([foreign_raw, foreign_prov]))
        local_endpoints_foreign_prov = MIRLRecord(
            id="rel:foreign-provenance",
            kind=RecordKind.REL,
            ns="s7",
            scope="thread",
            prov=[foreign_prov.id],
            attrs={"src": source.id, "predicate": "mentors", "dst": source.id},
        )
        with pytest.raises(CanonicalReferenceIntegrityError, match="crosses"):
            store.persist_ir(IRBatch([local_endpoints_foreign_prov]))
        assert store.load_ir(ids=[local_endpoints_foreign_prov.id]).records == []
    finally:
        store.close()


def test_unregistered_relation_predicate_is_not_admitted_for_traversal(
    tmp_path: Path,
) -> None:
    runtime = SeamRuntime(tmp_path / "predicate-admission.db", allow_pgvector_env=False)
    try:
        raw = MIRLRecord(
            id="raw:predicate-admission",
            kind=RecordKind.RAW,
            ns="s7",
            scope="thread",
            attrs={"content": "Alice mentors Bob."},
        )
        span = MIRLRecord(
            id="span:predicate-admission",
            kind=RecordKind.SPAN,
            ns="s7",
            scope="thread",
            attrs={"raw_id": raw.id, "start": 0, "end": 18},
        )
        alice = MIRLRecord(
            id="ent:alice",
            kind=RecordKind.ENT,
            ns="s7",
            scope="thread",
            evidence=[span.id],
            attrs={"entity_type": "person", "label": "Alice"},
        )
        bob = MIRLRecord(
            id="ent:bob",
            kind=RecordKind.ENT,
            ns="s7",
            scope="thread",
            evidence=[span.id],
            attrs={"entity_type": "person", "label": "Bob"},
        )
        runtime.persist_ir(
            IRBatch(
                [
                    raw,
                    span,
                    alice,
                    bob,
                    MIRLRecord(
                        id="rel:known",
                        kind=RecordKind.REL,
                        ns="s7",
                        scope="thread",
                        evidence=[span.id],
                        attrs={"src": alice.id, "predicate": "mentors", "dst": bob.id},
                    ),
                    MIRLRecord(
                        id="rel:unknown",
                        kind=RecordKind.REL,
                        ns="s7",
                        scope="thread",
                        evidence=[span.id],
                        attrs={
                            "src": alice.id,
                            "predicate": "s7_unregistered_predicate",
                            "dst": bob.id,
                        },
                    ),
                ]
            )
        )
        plan = build_plan(
            "Alice",
            budget=5,
            mode="graph",
            scope="thread",
            namespace="s7",
        )
        where, params = _canonical_relation_edge_where(plan)
        with runtime.store._pool.checkout() as connection:
            predicates = {
                str(row[0])
                for row in connection.execute(
                    "select e.predicate "
                    + _CANONICAL_RELATION_EDGE_FROM
                    + f"where {' and '.join(where)}",
                    params,
                ).fetchall()
            }
        assert predicates == {"mentors"}
        graph = runtime.store.knowledge_graph(
            root_id=alice.id,
            namespace="s7",
            scope="thread",
            limit=20,
            hops=1,
        )
        assert "mentors" in {str(edge["predicate"]) for edge in graph["edges"]}
        assert "s7_unregistered_predicate" not in {
            str(edge["predicate"]) for edge in graph["edges"]
        }
        rebuild = runtime.store.rebuild_graph_products(
            namespace="s7",
            scope="thread",
        )
        assert rebuild["accepted_fact_count"] == 1
        products = runtime.store.graph_products(namespace="s7", scope="thread")
        assert products
        assert all(
            "s7 unregistered predicate" not in sentence["text"]
            for product in products
            for sentence in product["sentences"]
        )
        contexts = runtime.store.context_candidates(
            namespace="s7",
            scope="thread",
        )
        assert all(
            "s7 unregistered predicate" not in candidate.text
            for candidate in contexts
        )
    finally:
        runtime.close()


def test_graph_as_of_selects_the_correct_relation_interval(tmp_path: Path) -> None:
    runtime = SeamRuntime(tmp_path / "as-of.db", allow_pgvector_env=False)
    try:
        entities = [
            MIRLRecord(
                id=record_id,
                kind=RecordKind.ENT,
                ns="s7",
                scope="thread",
                created_at="2025-12-01T00:00:00+00:00",
                updated_at="2025-12-01T00:00:00+00:00",
                t0="2025-12-01T00:00:00+00:00",
                attrs={"entity_type": "person", "label": label},
            )
            for record_id, label in (("ent:alice", "Alice"), ("ent:bob", "Bob"))
        ]
        relations = [
            MIRLRecord(
                id="rel:old",
                kind=RecordKind.REL,
                ns="s7",
                scope="thread",
                created_at="2026-01-01T00:00:00+00:00",
                updated_at="2026-01-01T00:00:00+00:00",
                t0="2026-01-01T00:00:00+00:00",
                t1="2026-02-01T00:00:00+00:00",
                attrs={"src": "ent:alice", "predicate": "mentors", "dst": "ent:bob"},
            ),
            MIRLRecord(
                id="rel:new",
                kind=RecordKind.REL,
                ns="s7",
                scope="thread",
                created_at="2026-02-01T00:00:00+00:00",
                updated_at="2026-02-01T00:00:00+00:00",
                t0="2026-02-01T00:00:00+00:00",
                attrs={"src": "ent:alice", "predicate": "manages", "dst": "ent:bob"},
            ),
        ]
        runtime.persist_ir(IRBatch([*entities, *relations]))

        january = runtime.store.knowledge_graph(
            root_id="ent:alice",
            at="2026-01-15T00:00:00+00:00",
            include_history=True,
        )
        february = runtime.store.knowledge_graph(
            root_id="ent:alice",
            at="2026-02-15T00:00:00+00:00",
            include_history=True,
        )
        assert "mentors" in {edge["predicate"] for edge in january["edges"]}
        assert "manages" not in {edge["predicate"] for edge in january["edges"]}
        assert "manages" in {edge["predicate"] for edge in february["edges"]}
        assert "mentors" not in {edge["predicate"] for edge in february["edges"]}
    finally:
        runtime.close()


def test_reconciliation_is_idempotent_across_two_runtime_instances(
    tmp_path: Path,
) -> None:
    path = tmp_path / "two-runtime-reconcile.db"
    seed = SeamRuntime(path, allow_pgvector_env=False)
    subject = MIRLRecord(
        id="ent:person",
        kind=RecordKind.ENT,
        ns="s7",
        scope="thread",
        attrs={"entity_type": "person", "label": "Person"},
    )
    claims = [
        _claim("clm:old", "blue", t0="2026-01-01T00:00:00+00:00"),
        _claim("clm:new", "red", t0="2026-02-01T00:00:00+00:00"),
    ]
    seed.persist_ir(IRBatch([subject, *claims]))
    seed.close()

    first = SeamRuntime(path, allow_pgvector_env=False)
    second = SeamRuntime(path, allow_pgvector_env=False)
    record_ids = [subject.id, *(claim.id for claim in claims)]
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            reports = list(
                executor.map(lambda runtime: runtime.reconcile_ir(record_ids), (first, second))
            )
        assert reports[0].to_dict() == reports[1].to_dict()
        derived_ids = {record.id for record in reports[0].added_records}
        assert {
            record.id
            for record in first.store.load_ir(ids=sorted(derived_ids)).records
        } == derived_ids
        first.reconcile_ir(record_ids)
        assert {
            record.id
            for record in first.store.load_ir(ids=sorted(derived_ids)).records
        } == derived_ids
    finally:
        first.close()
        second.close()
