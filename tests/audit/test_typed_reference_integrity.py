"""Track S S4 typed-reference and orphan-integrity exit gate."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing

from seam_runtime.migrations import PROJECTION_TABLE
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.nl import compile_nl
from seam_runtime.reference_contracts import (
    VIRTUAL_REFS_EXTENSION,
    CanonicalReferenceIntegrityError,
)
from seam_runtime.storage import SQLiteStore


def _edge_rows(store: SQLiteStore) -> set[tuple[str, str, str, str, str]]:
    with closing(store._connect()) as connection:
        rows = connection.execute(
            "select src_id, src_ref_type, edge_type, dst_id, dst_ref_type "
            "from ir_edges"
        ).fetchall()
    return {tuple(str(value) for value in row) for row in rows}


def test_whole_message_colon_text_projects_only_literal_value_nodes() -> None:
    message = (
        "Meet at 09:30. Visit https://example.com/a:b. "
        "Keep arbitrary:key literal."
    )
    store = SQLiteStore(":memory:")
    try:
        batch = compile_nl(message, allow_env_extractor=False)
        store.persist_ir(batch)
        literal_claims = {
            str(record.attrs["object"])
            for record in batch.records
            if record.kind is RecordKind.CLM
        }
        assert literal_claims == {
            "Meet at 09:30.",
            "Visit https://example.com/a:b.",
            "Keep arbitrary:key literal.",
        }

        with closing(store._connect()) as connection:
            nodes = connection.execute(
                "select id, kind, properties_json from knowledge_nodes"
            ).fetchall()
        assert not literal_claims.intersection(str(row["id"]) for row in nodes)
        for literal in literal_claims:
            matches = [
                row
                for row in nodes
                if json.loads(str(row["properties_json"])).get("reference")
                == literal
            ]
            assert len(matches) == 1
            assert matches[0]["kind"] == "value"
            assert str(matches[0]["id"]).startswith("value:")
    finally:
        store.close()


def test_same_batch_and_stored_optional_references_resolve_as_records() -> None:
    store = SQLiteStore(":memory:")
    try:
        same_batch_target = MIRLRecord(
            id="ent:same-batch",
            kind=RecordKind.ENT,
            attrs={"entity_type": "thing", "label": "same batch"},
        )
        same_batch_subject = MIRLRecord(
            id="ent:subject",
            kind=RecordKind.ENT,
            attrs={"entity_type": "person", "label": "subject"},
        )
        same_batch_claim = MIRLRecord(
            id="clm:same-batch",
            kind=RecordKind.CLM,
            attrs={
                "subject": same_batch_subject.id,
                "predicate": "references",
                "object": same_batch_target.id,
            },
        )
        # Put the claim first to prove resolution is independent of batch order.
        store.persist_ir(
            IRBatch([same_batch_claim, same_batch_target, same_batch_subject])
        )
        same_batch_edge = (
            same_batch_subject.id,
            "ENT",
            "references",
            same_batch_target.id,
            "ENT",
        )
        assert same_batch_edge in _edge_rows(store)

        stored_target = MIRLRecord(
            id="ent:stored",
            kind=RecordKind.ENT,
            attrs={"entity_type": "thing", "label": "stored"},
        )
        store.persist_ir(IRBatch([stored_target]))
        stored_claim = MIRLRecord(
            id="clm:stored",
            kind=RecordKind.CLM,
            attrs={
                "subject": same_batch_subject.id,
                "predicate": "references",
                "object": stored_target.id,
            },
        )
        store.persist_ir(IRBatch([stored_claim]))

        edges = _edge_rows(store)
        assert (
            same_batch_subject.id,
            "ENT",
            "references",
            stored_target.id,
            "ENT",
        ) in edges
    finally:
        store.close()


def test_reference_lookup_ignores_unrelated_invalid_rows_but_fails_closed_when_referenced() -> None:
    store = SQLiteStore(":memory:")
    try:
        valid_target = MIRLRecord(
            id="ent:valid-target",
            kind=RecordKind.ENT,
            attrs={"entity_type": "thing", "label": "valid"},
        )
        subject = MIRLRecord(
            id="ent:lookup-subject",
            kind=RecordKind.ENT,
            attrs={"entity_type": "person", "label": "subject"},
        )
        store.persist_ir(IRBatch([valid_target, subject]))
        with closing(store._connect()) as connection:
            connection.execute(
                "insert into ir_records "
                "(id, kind, ns, scope, status, conf, created_at, updated_at, payload_json) "
                "values ('unrelated-corrupt-row', 'NOT_A_KIND', 'default', 'global', "
                "'asserted', 1.0, '2026-01-01T00:00:00Z', "
                "'2026-01-01T00:00:00Z', '{}')"
            )
            connection.commit()

        valid_claim = MIRLRecord(
            id="clm:valid-lookup",
            kind=RecordKind.CLM,
            attrs={
                "subject": subject.id,
                "predicate": "references",
                "object": valid_target.id,
            },
        )
        store.persist_ir(IRBatch([valid_claim]))
        assert (
            subject.id,
            "ENT",
            "references",
            valid_target.id,
            "ENT",
        ) in _edge_rows(store)

        corrupt_reference = MIRLRecord(
            id="clm:corrupt-lookup",
            kind=RecordKind.CLM,
            attrs={
                "subject": subject.id,
                "predicate": "references",
                "object": "unrelated-corrupt-row",
            },
        )
        try:
            store.persist_ir(IRBatch([corrupt_reference]))
        except CanonicalReferenceIntegrityError as exc:
            assert str(exc) == "stored canonical reference has an invalid MIRL kind"
            assert "unrelated-corrupt-row" not in str(exc)
        else:
            raise AssertionError("referenced invalid canonical kind did not fail closed")
    finally:
        store.close()


def test_orphan_sweep_is_kind_agnostic_and_checks_both_typed_endpoints() -> None:
    store = SQLiteStore(":memory:")
    try:
        anchor = MIRLRecord(
            id="ent:anchor",
            kind=RecordKind.ENT,
            attrs={"entity_type": "thing", "label": "anchor"},
        )
        store.persist_ir(IRBatch([anchor]))
        with closing(store._connect()) as connection:
            for kind in RecordKind:
                missing = f"missing-{kind.value.lower()}"
                connection.execute(
                    "insert into ir_edges "
                    "(src_id, src_ref_type, edge_type, dst_id, dst_ref_type) "
                    "values (?, ?, ?, ?, 'ENT')",
                    (missing, kind.value, f"src-{kind.value}", anchor.id),
                )
                connection.execute(
                    "insert into ir_edges "
                    "(src_id, src_ref_type, edge_type, dst_id, dst_ref_type) "
                    "values (?, 'ENT', ?, ?, ?)",
                    (anchor.id, f"dst-{kind.value}", missing, kind.value),
                )
            store._cleanup_orphan_edges(connection)
            remaining = connection.execute(
                "select count(*) from ir_edges where edge_type like 'src-%' "
                "or edge_type like 'dst-%'"
            ).fetchone()[0]
        assert remaining == 0
    finally:
        store.close()


def test_orphan_sweep_rejects_wrong_kind_on_either_endpoint() -> None:
    store = SQLiteStore(":memory:")
    try:
        anchor = MIRLRecord(
            id="ent:typed-anchor",
            kind=RecordKind.ENT,
            attrs={"entity_type": "thing", "label": "typed anchor"},
        )
        store.persist_ir(IRBatch([anchor]))
        with closing(store._connect()) as connection:
            connection.execute(
                "insert into ir_edges "
                "(src_id, src_ref_type, edge_type, dst_id, dst_ref_type) "
                "values (?, 'CLM', 'wrong-src-kind', ?, 'ENT')",
                (anchor.id, anchor.id),
            )
            connection.execute(
                "insert into ir_edges "
                "(src_id, src_ref_type, edge_type, dst_id, dst_ref_type) "
                "values (?, 'ENT', 'wrong-dst-kind', ?, 'RAW')",
                (anchor.id, anchor.id),
            )
            store._cleanup_orphan_edges(connection)
            assert connection.execute(
                "select count(*) from ir_edges where edge_type like 'wrong-%'"
            ).fetchone()[0] == 0
    finally:
        store.close()


def test_explicit_virtual_entity_survives_reopen_and_repeat_cleanup(
    tmp_path,
) -> None:
    path = tmp_path / "virtual.db"
    virtual_id = "graph-only-turn-7"
    anchor = MIRLRecord(
        id="ent:anchor",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "anchor"},
    )
    relation = MIRLRecord(
        id="rel:virtual",
        kind=RecordKind.REL,
        ext={VIRTUAL_REFS_EXTENSION: [virtual_id]},
        attrs={"src": virtual_id, "predicate": "mentions", "dst": anchor.id},
    )
    store = SQLiteStore(path)
    store.persist_ir(IRBatch([relation, anchor]))
    expected = (virtual_id, "virtual", "mentions", anchor.id, "ENT")
    assert expected in _edge_rows(store)
    store.close()

    for _ in range(2):
        reopened = SQLiteStore(path)
        try:
            with closing(reopened._connect()) as connection:
                reopened._cleanup_orphan_edges(connection)
                connection.commit()
            assert expected in _edge_rows(reopened)
        finally:
            reopened.close()


def test_core_storage_v1_migration_rebuilds_endpoint_types_idempotently(
    tmp_path,
) -> None:
    path = tmp_path / "typed-migration.db"
    source = MIRLRecord(
        id="ent:source",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "source"},
    )
    target = MIRLRecord(
        id="ent:target",
        kind=RecordKind.ENT,
        attrs={"entity_type": "thing", "label": "target"},
    )
    relation = MIRLRecord(
        id="rel:migrate",
        kind=RecordKind.REL,
        attrs={"src": source.id, "predicate": "links", "dst": target.id},
    )
    store = SQLiteStore(path)
    store.persist_ir(IRBatch([relation, target, source]))
    store.close()

    connection = sqlite3.connect(path)
    connection.execute("alter table ir_edges drop column src_ref_type")
    connection.execute("alter table ir_edges drop column dst_ref_type")
    connection.execute(
        f"update {PROJECTION_TABLE} set projection_version = 'core-storage/1' "
        "where projection_name = 'core_storage'"
    )
    connection.commit()
    connection.close()

    migrated = SQLiteStore(path)
    try:
        assert migrated.migration_result.applied_steps == (
            "typed-ir-edge-endpoints",
        )
        expected = (source.id, "ENT", "links", target.id, "ENT")
        assert expected in _edge_rows(migrated)
    finally:
        migrated.close()

    reopened = SQLiteStore(path)
    try:
        assert reopened.migration_result.applied_steps == ()
        assert expected in _edge_rows(reopened)
    finally:
        reopened.close()


def test_knowledge_graph_v5_migration_removes_colon_phantoms_idempotently(
    tmp_path,
) -> None:
    path = tmp_path / "typed-knowledge.db"
    batch = compile_nl("Meet at 09:30.", allow_env_extractor=False)
    claim = next(record for record in batch.records if record.kind is RecordKind.CLM)
    store = SQLiteStore(path)
    store.persist_ir(batch)
    store.close()

    phantom_id = "Meet at 09:30."
    connection = sqlite3.connect(path)
    connection.execute(
        "insert into knowledge_nodes "
        "select ?, 'concept', ?, ns, scope, status, confidence, valid_from, "
        "valid_to, created_at, updated_at, agent_id, ?, 1, ? "
        "from knowledge_nodes where id = ?",
        (
            phantom_id,
            phantom_id,
            claim.id,
            json.dumps({"reference": phantom_id}),
            claim.id,
        ),
    )
    connection.execute(
        "insert into knowledge_edges "
        "select 'kge:legacy-colon-phantom', src_id, ?, predicate, edge_kind, "
        "ns, scope, status, confidence, valid_from, valid_to, created_at, "
        "updated_at, expired_at, agent_id, source_record_id, properties_json "
        "from knowledge_edges where source_record_id = ? limit 1",
        (phantom_id, claim.id),
    )
    connection.execute(
        "update knowledge_graph_meta set value = 'knowledge-graph/5' "
        "where key = 'projection_version'"
    )
    connection.execute(
        f"update {PROJECTION_TABLE} set projection_version = 'knowledge-graph/5' "
        "where projection_name = 'knowledge_graph'"
    )
    connection.commit()
    connection.close()

    migrated = SQLiteStore(path)
    try:
        assert migrated.migration_result.applied_steps == (
            "typed-knowledge-references",
        )
        with closing(migrated._connect()) as connection:
            assert connection.execute(
                "select count(*) from knowledge_nodes where id = ?",
                (phantom_id,),
            ).fetchone()[0] == 0
            assert connection.execute(
                "select value from knowledge_graph_meta "
                "where key = 'projection_version'"
            ).fetchone()[0] == "knowledge-graph/6"
    finally:
        migrated.close()

    reopened = SQLiteStore(path)
    try:
        assert reopened.migration_result.applied_steps == ()
        with closing(reopened._connect()) as connection:
            assert connection.execute(
                "select count(*) from knowledge_nodes where id = ?",
                (phantom_id,),
            ).fetchone()[0] == 0
    finally:
        reopened.close()
