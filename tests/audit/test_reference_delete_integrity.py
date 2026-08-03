"""Hard-delete closure and current-payload reference integrity gates."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

import seam_runtime.migrations as migration_module
from seam_runtime.identity_resolution import (
    STATUS_CONFLICT,
    accept_merge,
    propose_merge,
)
from seam_runtime.migrations import DatabaseIntegrityError
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.reference_contracts import (
    VIRTUAL_REFS_EXTENSION,
    CanonicalReferenceIntegrityError,
)
from seam_runtime.storage import SQLiteStore


def _all_table_hashes(path: Path) -> dict[str, str]:
    with closing(sqlite3.connect(path)) as connection:
        tables = [
            str(row[0])
            for row in connection.execute(
                "select name from sqlite_master where type = 'table' "
                "and name not like 'sqlite_%' order by name"
            )
        ]
        hashes: dict[str, str] = {}
        for table in tables:
            schema = connection.execute(
                "select sql from sqlite_master where type = 'table' and name = ?",
                (table,),
            ).fetchone()[0]
            rows = connection.execute(
                f'select * from "{table}" order by rowid'
            ).fetchall()
            payload = json.dumps(
                {"schema": schema, "rows": rows},
                sort_keys=True,
                separators=(",", ":"),
            )
            hashes[table] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return hashes


def _entity(record_id: str, label: str) -> MIRLRecord:
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.ENT,
        attrs={"label": label, "entity_type": "test"},
    )


def _relation(
    record_id: str,
    source_id: str,
    target_id: str,
) -> MIRLRecord:
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.REL,
        attrs={"src": source_id, "predicate": "requires", "dst": target_id},
    )


def test_delete_refuses_surviving_required_reference_without_any_table_change(
    tmp_path: Path,
) -> None:
    path = tmp_path / "required-delete-refusal.db"
    source = _entity("ent:private-delete-source", "Source")
    target = _entity("ent:private-delete-target", "Target")
    relation = _relation(
        "rel:private-delete-owner",
        source.id,
        target.id,
    )
    # A canonical endpoint cannot silently become virtual during deletion.
    relation.ext[VIRTUAL_REFS_EXTENSION] = [target.id]
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([relation, target, source]))
        before_hashes = _all_table_hashes(path)
        before_bytes = path.read_bytes()

        with pytest.raises(
            CanonicalReferenceIntegrityError,
            match="delete would violate required canonical reference closure",
        ) as raised:
            store.delete_ir([target.id])

        diagnostics = str(raised.value)
        assert source.id not in diagnostics
        assert target.id not in diagnostics
        assert relation.id not in diagnostics
        assert path.read_bytes() == before_bytes
        assert _all_table_hashes(path) == before_hashes
    finally:
        store.close()


def test_delete_allows_optional_reference_to_become_literal(tmp_path: Path) -> None:
    path = tmp_path / "optional-delete.db"
    source = _entity("ent:optional-source", "Source")
    target = _entity("ent:optional-target", "Target")
    claim = MIRLRecord(
        id="clm:optional-reference",
        kind=RecordKind.CLM,
        attrs={
            "subject": source.id,
            "predicate": "mentions",
            "object": target.id,
        },
    )
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([claim, target, source]))
        with closing(store._connect()) as connection:
            connection.execute(
                "insert into knowledge_node_vectors "
                "(node_id, model_name, dimension, source_text, source_hash, "
                "render_version, ns, scope, vector_json, updated_at) "
                "values (?, 'test-model', 1, 'stale canonical target', "
                "'stale-hash', 'knowledge-node-vector-text/2', '', '', "
                "'[1.0]', '2026-08-03T00:00:00+00:00')",
                (target.id,),
            )
            connection.commit()
        store.delete_ir([target.id])

        stored_claim = store.load_ir(ids=[claim.id]).records[0]
        assert stored_claim.attrs["object"] == target.id
        with closing(store._connect()) as connection:
            assert connection.execute(
                "select 1 from ir_records where id = ?", (target.id,)
            ).fetchone() is None
            assert connection.execute(
                "select count(*) from ir_edges where src_id = ? or dst_id = ?",
                (target.id, target.id),
            ).fetchone()[0] == 0
            assert connection.execute(
                "select 1 from knowledge_nodes where id = ?", (target.id,)
            ).fetchone() is None
            literal = connection.execute(
                "select nodes.id, nodes.kind, nodes.properties_json "
                "from knowledge_edges edges join knowledge_nodes nodes "
                "on nodes.id = edges.dst_id where edges.source_record_id = ? "
                "and edges.predicate = 'object'",
                (claim.id,),
            ).fetchone()
            assert literal is not None
            assert literal["id"].startswith("value:")
            assert literal["kind"] == "value"
            assert json.loads(literal["properties_json"])["reference"] == target.id
            assert connection.execute(
                "select 1 from knowledge_node_vectors where node_id = ?",
                (target.id,),
            ).fetchone() is None
    finally:
        store.close()

    reopened = SQLiteStore(path)
    try:
        with closing(reopened._connect()) as connection:
            assert connection.execute(
                "select 1 from knowledge_nodes where id = ?", (target.id,)
            ).fetchone() is None
            assert connection.execute(
                "select nodes.kind from knowledge_edges edges "
                "join knowledge_nodes nodes on nodes.id = edges.dst_id "
                "where edges.source_record_id = ? and edges.predicate = 'object'",
                (claim.id,),
            ).fetchone()[0] == "value"
    finally:
        reopened.close()


def test_late_canonical_target_promotes_batched_optional_literal_and_reopens(
    tmp_path: Path,
) -> None:
    path = tmp_path / "late-optional-promotion.db"
    source = _entity("ent:late-promotion-source", "Late promotion source")
    target_id = "ent:late-promotion-target"
    affected = MIRLRecord(
        id="clm:zz-late-promotion-affected",
        kind=RecordKind.CLM,
        attrs={
            "subject": source.id,
            "predicate": "mentions",
            "object": target_id,
        },
    )
    fillers = [
        MIRLRecord(
            id=f"meta:late-promotion-{index:04d}",
            kind=RecordKind.META,
            attrs={"schema": "late-promotion", "value": index},
        )
        for index in range(505)
    ]
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([source, *fillers, affected]))
        with closing(store._connect()) as connection:
            assert connection.execute(
                "select 1 from ir_edges where dst_id = ?",
                (target_id,),
            ).fetchone() is None
            literal_id = connection.execute(
                "select dst_id from knowledge_edges where source_record_id = ? "
                "and predicate = 'object'",
                (affected.id,),
            ).fetchone()[0]
            assert str(literal_id).startswith("value:")

        target = _entity(target_id, "Late promotion target")
        store.persist_ir(IRBatch([target]))
        with closing(store._connect()) as connection:
            assert tuple(
                connection.execute(
                    "select src_ref_type, dst_ref_type from ir_edges "
                    "where src_id = ? and edge_type = 'mentions' and dst_id = ?",
                    (source.id, target.id),
                ).fetchone()
            ) == ("ENT", "ENT")
            assert connection.execute(
                "select dst_id from knowledge_edges where source_record_id = ? "
                "and predicate = 'object'",
                (affected.id,),
            ).fetchone()[0] == target.id
            assert connection.execute(
                "select 1 from knowledge_nodes where id = ? and synthetic = 0",
                (target.id,),
            ).fetchone() is not None
    finally:
        store.close()

    reopened = SQLiteStore(path)
    try:
        with closing(reopened._connect()) as connection:
            assert connection.execute(
                "select dst_ref_type from ir_edges where dst_id = ?",
                (target_id,),
            ).fetchone()[0] == "ENT"
            assert connection.execute(
                "select dst_id from knowledge_edges where source_record_id = ? "
                "and predicate = 'object'",
                (affected.id,),
            ).fetchone()[0] == target_id
    finally:
        reopened.close()


def test_late_canonical_target_promotes_declared_virtual_projection(
    tmp_path: Path,
) -> None:
    path = tmp_path / "late-virtual-promotion.db"
    source = _entity("ent:late-virtual-source", "Late virtual source")
    target_id = "ent:late-virtual-target"
    claim = MIRLRecord(
        id="clm:late-virtual-claim",
        kind=RecordKind.CLM,
        ext={VIRTUAL_REFS_EXTENSION: [target_id]},
        attrs={
            "subject": source.id,
            "predicate": "mentions",
            "object": target_id,
        },
    )
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([source, claim]))
        with closing(store._connect()) as connection:
            assert connection.execute(
                "select dst_ref_type from ir_edges where dst_id = ?",
                (target_id,),
            ).fetchone()[0] == "virtual"
            assert connection.execute(
                "select synthetic from knowledge_nodes where id = ?",
                (target_id,),
            ).fetchone()[0] == 1

        store.persist_ir(IRBatch([_entity(target_id, "Late virtual target")]))
        with closing(store._connect()) as connection:
            assert connection.execute(
                "select dst_ref_type from ir_edges where dst_id = ?",
                (target_id,),
            ).fetchone()[0] == "ENT"
            assert connection.execute(
                "select synthetic from knowledge_nodes where id = ?",
                (target_id,),
            ).fetchone()[0] == 0
    finally:
        store.close()


def test_late_target_preserves_shared_edge_identity_across_bounded_queue(
    tmp_path: Path,
) -> None:
    path = tmp_path / "late-shared-virtual-promotion.db"
    source = _entity("ent:late-shared-source", "Late shared source")
    target_id = "ent:late-shared-target"
    claims = [
        MIRLRecord(
            id=f"clm:late-shared-owner-{index:04d}",
            kind=RecordKind.CLM,
            ext={VIRTUAL_REFS_EXTENSION: [target_id]},
            attrs={
                "subject": source.id,
                "predicate": "mentions",
                "object": target_id,
            },
        )
        for index in range(503)
    ]
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([source, *claims]))
        with closing(store._connect()) as connection:
            before = connection.execute(
                "select id, dst_ref_type from ir_edges where src_id = ? "
                "and edge_type = 'mentions' and dst_id = ?",
                (source.id, target_id),
            ).fetchone()
            assert before is not None
            edge_id = int(before[0])
            assert before[1] == "virtual"
            assert connection.execute(
                "select count(*) from ir_edge_sources where src_id = ? "
                "and edge_type = 'mentions' and dst_id = ?",
                (source.id, target_id),
            ).fetchone()[0] == 503

        store.persist_ir(IRBatch([_entity(target_id, "Late shared target")]))
        with closing(store._connect()) as connection:
            after = connection.execute(
                "select id, dst_ref_type from ir_edges where src_id = ? "
                "and edge_type = 'mentions' and dst_id = ?",
                (source.id, target_id),
            ).fetchone()
            assert tuple(after) == (edge_id, "ENT")
            assert connection.execute(
                "select count(*) from ir_edge_sources where src_id = ? "
                "and edge_type = 'mentions' and dst_id = ?",
                (source.id, target_id),
            ).fetchone()[0] == 503

        store.delete_ir([target_id])
        with closing(store._connect()) as connection:
            after_delete = connection.execute(
                "select id, dst_ref_type from ir_edges where src_id = ? "
                "and edge_type = 'mentions' and dst_id = ?",
                (source.id, target_id),
            ).fetchone()
            assert tuple(after_delete) == (edge_id, "virtual")
            assert connection.execute(
                "select count(*) from ir_edge_sources where src_id = ? "
                "and edge_type = 'mentions' and dst_id = ?",
                (source.id, target_id),
            ).fetchone()[0] == 503
    finally:
        store.close()

    reopened = SQLiteStore(path)
    try:
        with closing(reopened._connect()) as connection:
            assert connection.execute(
                "select count(*) from ir_edge_sources where src_id = ? "
                "and edge_type = 'mentions' and dst_id = ?",
                (source.id, target_id),
            ).fetchone()[0] == 503
            assert connection.execute(
                "select dst_ref_type from ir_edges where src_id = ? "
                "and edge_type = 'mentions' and dst_id = ?",
                (source.id, target_id),
            ).fetchone()[0] == "virtual"
    finally:
        reopened.close()


def test_late_target_mixed_batch_promotes_touched_and_untouched_shared_owners(
    tmp_path: Path,
) -> None:
    path = tmp_path / "late-shared-mixed-promotion.db"
    source = _entity("ent:late-mixed-source", "Late mixed source")
    target_id = "ent:late-mixed-target"
    claims = [
        MIRLRecord(
            id=f"clm:late-mixed-owner-{index}",
            kind=RecordKind.CLM,
            ext={VIRTUAL_REFS_EXTENSION: [target_id]},
            attrs={
                "subject": source.id,
                "predicate": "mentions",
                "object": target_id,
            },
        )
        for index in range(2)
    ]
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([source, *claims]))
        touched = MIRLRecord.from_dict(claims[0].to_dict())
        store.persist_ir(
            IRBatch([_entity(target_id, "Late mixed target"), touched])
        )
        with closing(store._connect()) as connection:
            assert connection.execute(
                "select dst_ref_type from ir_edges where src_id = ? "
                "and edge_type = 'mentions' and dst_id = ?",
                (source.id, target_id),
            ).fetchone()[0] == "ENT"
            assert connection.execute(
                "select count(*) from ir_edge_sources where src_id = ? "
                "and edge_type = 'mentions' and dst_id = ?",
                (source.id, target_id),
            ).fetchone()[0] == 2
    finally:
        store.close()


def test_delete_reprojects_optional_declared_virtual_target(tmp_path: Path) -> None:
    path = tmp_path / "optional-virtual-delete.db"
    source = _entity("ent:optional-virtual-source", "Source")
    target = _entity("ent:optional-virtual-target", "Canonical target")
    claim = MIRLRecord(
        id="clm:optional-virtual-reference",
        kind=RecordKind.CLM,
        attrs={
            "subject": source.id,
            "predicate": "mentions",
            "object": target.id,
        },
        ext={VIRTUAL_REFS_EXTENSION: [target.id]},
    )
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([source, target, claim]))
        store.delete_ir([target.id])

        with closing(store._connect()) as connection:
            node = connection.execute(
                "select kind, label, synthetic, source_record_id, properties_json "
                "from knowledge_nodes where id = ?",
                (target.id,),
            ).fetchone()
            assert node is not None
            assert tuple(node[:4]) == (
                "entity",
                "optional virtual target",
                1,
                None,
            )
            assert json.loads(node["properties_json"]) == {"reference": target.id}
            assert connection.execute(
                "select dst_ref_type from ir_edges where dst_id = ?",
                (target.id,),
            ).fetchone()[0] == "virtual"
    finally:
        store.close()

    reopened = SQLiteStore(path)
    try:
        with closing(reopened._connect()) as connection:
            assert tuple(
                connection.execute(
                    "select kind, synthetic from knowledge_nodes where id = ?",
                    (target.id,),
                ).fetchone()
            ) == ("entity", 1)
    finally:
        reopened.close()


def test_optional_target_delete_revalidates_identity_merge_after_reprojection(
    tmp_path: Path,
) -> None:
    path = tmp_path / "optional-delete-identity-merge.db"
    source = _entity("ent:delete-merge-source", "Delete merge source")
    target = _entity("ent:delete-merge-target", "Delete merge target")
    claim = MIRLRecord(
        id="clm:delete-merge-optional-owner",
        kind=RecordKind.CLM,
        attrs={
            "subject": source.id,
            "predicate": "mentions",
            "object": target.id,
        },
    )
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([source, target, claim]))
        with closing(store._connect()) as connection:
            merge_id = propose_merge(
                connection,
                canonical_node_id=source.id,
                alias_node_id=target.id,
                ns=source.ns,
                scope=source.scope,
            )
            assert accept_merge(connection, merge_id) == "accepted"
            connection.commit()

        store.delete_ir([target.id])

        merge = next(
            item for item in store.identity_merges() if item["id"] == merge_id
        )
        assert merge["status"] == STATUS_CONFLICT
        with closing(store._connect()) as connection:
            assert connection.execute(
                "select 1 from knowledge_nodes where id = ?",
                (target.id,),
            ).fetchone() is None
    finally:
        store.close()

    reopened = SQLiteStore(path)
    try:
        merge = next(
            item for item in reopened.identity_merges() if item["id"] == merge_id
        )
        assert merge["status"] == STATUS_CONFLICT
    finally:
        reopened.close()


def test_delete_reprojection_scan_reaches_a_later_bounded_batch(
    tmp_path: Path,
) -> None:
    path = tmp_path / "optional-delete-bounded-scan.db"
    source = _entity("ent:bounded-delete-source", "Bounded source")
    target = _entity("ent:bounded-delete-target", "Bounded target")
    fillers = [
        MIRLRecord(
            id=f"clm:bounded-filler-{index:03d}",
            kind=RecordKind.CLM,
            attrs={
                "subject": source.id,
                "predicate": "describes",
                "object": f"literal {index}",
            },
        )
        for index in range(505)
    ]
    affected = MIRLRecord(
        id="clm:z-bounded-optional-reference",
        kind=RecordKind.CLM,
        attrs={
            "subject": source.id,
            "predicate": "mentions",
            "object": target.id,
        },
    )
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([source, target, *fillers, affected]))
        store.delete_ir([target.id])

        with closing(store._connect()) as connection:
            destination = connection.execute(
                "select nodes.kind, nodes.properties_json "
                "from knowledge_edges edges join knowledge_nodes nodes "
                "on nodes.id = edges.dst_id where edges.source_record_id = ? "
                "and edges.predicate = 'object'",
                (affected.id,),
            ).fetchone()
            assert destination is not None
            assert destination["kind"] == "value"
            assert json.loads(destination["properties_json"])["reference"] == target.id
    finally:
        store.close()


def test_kind_change_is_rejected_before_entity_reconciliation_can_skip_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "kind-change-before-reconciliation.db"
    canonical = _entity("ent:canonical-label", "Shared label")
    colliding_id = MIRLRecord(
        id="meta:colliding-identifier",
        kind=RecordKind.META,
        attrs={"name": "stored metadata"},
    )
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([canonical, colliding_id]))
        before_hashes = _all_table_hashes(path)
        before_bytes = path.read_bytes()
        attempted_entity = _entity(colliding_id.id, "Shared label")

        with pytest.raises(
            CanonicalReferenceIntegrityError,
            match="canonical record kind cannot change",
        ) as raised:
            store.persist_ir(IRBatch([attempted_entity]))

        assert colliding_id.id not in str(raised.value)
        assert path.read_bytes() == before_bytes
        assert _all_table_hashes(path) == before_hashes
        stored = store.load_ir(ids=[colliding_id.id]).records[0]
        assert stored.kind is RecordKind.META
    finally:
        store.close()


def test_delete_allows_target_when_every_required_referrer_is_deleted(
    tmp_path: Path,
) -> None:
    path = tmp_path / "closed-multi-delete.db"
    source = _entity("ent:closed-source", "Source")
    target = _entity("ent:closed-target", "Target")
    relation = _relation("rel:closed-owner", source.id, target.id)
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([source, target, relation]))
        store.delete_ir([target.id, relation.id])

        assert store.load_ir(ids=[target.id, relation.id]).records == []
        assert [
            record.id for record in store.load_ir(ids=[source.id]).records
        ] == [source.id]
        with closing(store._connect()) as connection:
            assert connection.execute(
                "select count(*) from ir_edge_sources "
                "where source_record_id = ? or src_id = ? or dst_id = ?",
                (relation.id, target.id, target.id),
            ).fetchone()[0] == 0
    finally:
        store.close()


def test_multi_id_delete_refuses_atomically_when_one_referrer_survives(
    tmp_path: Path,
) -> None:
    path = tmp_path / "open-multi-delete.db"
    source = _entity("ent:multi-source", "Source")
    first_target = _entity("ent:multi-target-one", "Target one")
    second_target = _entity("ent:multi-target-two", "Target two")
    first_relation = _relation(
        "rel:multi-owner-one",
        source.id,
        first_target.id,
    )
    surviving_relation = _relation(
        "rel:multi-owner-two",
        source.id,
        second_target.id,
    )
    records = [
        source,
        first_target,
        second_target,
        first_relation,
        surviving_relation,
    ]
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch(records))
        before_hashes = _all_table_hashes(path)
        before_bytes = path.read_bytes()

        with pytest.raises(CanonicalReferenceIntegrityError):
            store.delete_ir(
                [first_relation.id, first_target.id, second_target.id]
            )

        assert path.read_bytes() == before_bytes
        assert _all_table_hashes(path) == before_hashes
        assert {record.id for record in store.load_ir().records} >= {
            record.id for record in records
        }
    finally:
        store.close()


def test_delete_refuses_required_self_loop_suppressed_from_edge_projection(
    tmp_path: Path,
) -> None:
    path = tmp_path / "suppressed-self-loop-delete.db"
    target = _entity("ent:private-loop-target", "Loop target")
    relation = _relation(
        "rel:private-loop-owner",
        target.id,
        target.id,
    )
    store = SQLiteStore(path)
    try:
        store.persist_ir(IRBatch([relation, target]))
        with closing(store._connect()) as connection:
            assert connection.execute(
                "select count(*) from ir_edges where edge_type = 'requires'"
            ).fetchone()[0] == 0

        with pytest.raises(
            CanonicalReferenceIntegrityError,
            match="required canonical reference closure",
        ):
            store.delete_ir([target.id])

        assert [
            record.id
            for record in store.load_ir(ids=[target.id, relation.id]).records
        ] == [target.id, relation.id]
    finally:
        store.close()


def test_current_store_reopen_rejects_payload_only_dangling_reference_read_only(
    tmp_path: Path,
) -> None:
    path = tmp_path / "payload-only-dangling-reference.db"
    target = _entity("ent:private-reopen-target", "Target")
    relation = _relation(
        "rel:private-reopen-owner",
        target.id,
        target.id,
    )
    store = SQLiteStore(path)
    store.persist_ir(IRBatch([target, relation]))
    store.close()

    with closing(sqlite3.connect(path)) as connection:
        connection.execute("pragma foreign_keys = off")
        connection.execute(
            "delete from ir_records where id = ?",
            (target.id,),
        )
        connection.commit()

    before_hashes = _all_table_hashes(path)
    before_bytes = path.read_bytes()
    backup_dir = tmp_path / "payload-reference-backups"
    with pytest.raises(
        DatabaseIntegrityError,
        match="invalid canonical payload reference",
    ) as raised:
        SQLiteStore(path, _migration_backup_dir=backup_dir)

    diagnostics = str(raised.value)
    assert target.id not in diagnostics
    assert relation.id not in diagnostics
    assert path.read_bytes() == before_bytes
    assert _all_table_hashes(path) == before_hashes
    assert not backup_dir.exists()


def test_current_store_reopen_validates_reserved_reference_metadata_read_only(
    tmp_path: Path,
) -> None:
    path = tmp_path / "malformed-reference-metadata.db"
    record = MIRLRecord(
        id="meta:private-reference-metadata",
        kind=RecordKind.META,
        attrs={"key": "test", "value": "metadata"},
    )
    store = SQLiteStore(path)
    store.persist_ir(IRBatch([record]))
    store.close()

    with closing(sqlite3.connect(path)) as connection:
        payload = record.to_dict()
        payload["ext"] = {VIRTUAL_REFS_EXTENSION: "private-malformed-id"}
        connection.execute(
            "update ir_records set payload_json = ? where id = ?",
            (
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                record.id,
            ),
        )
        connection.commit()

    before_hashes = _all_table_hashes(path)
    before_bytes = path.read_bytes()
    backup_dir = tmp_path / "metadata-reference-backups"
    with pytest.raises(
        DatabaseIntegrityError,
        match="invalid canonical payload reference",
    ) as raised:
        SQLiteStore(path, _migration_backup_dir=backup_dir)

    diagnostics = str(raised.value)
    assert record.id not in diagnostics
    assert "private-malformed-id" not in diagnostics
    assert path.read_bytes() == before_bytes
    assert _all_table_hashes(path) == before_hashes
    assert not backup_dir.exists()


def test_payload_reference_scan_is_deterministic_and_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SQLiteStore(":memory:")
    records = [
        MIRLRecord(
            id=f"meta:bounded-{index}",
            kind=RecordKind.META,
            attrs={"key": "bounded", "value": index},
        )
        for index in range(5)
    ]
    try:
        store.persist_ir(IRBatch(list(reversed(records))))
        observed_batches: list[tuple[str, ...]] = []
        monkeypatch.setattr(migration_module, "_MIGRATION_BATCH_SIZE", 2)

        with closing(store._connect()) as connection:
            class TrackingCursor:
                def __init__(self, cursor: sqlite3.Cursor) -> None:
                    self._cursor = cursor

                def fetchmany(self, size: int | None = None):
                    assert size == 2
                    rows = self._cursor.fetchmany(size)
                    observed_batches.append(
                        tuple(str(row[0]) for row in rows)
                    )
                    return rows

            class TrackingConnection:
                def execute(self, statement: str, parameters=()):
                    cursor = connection.execute(statement, parameters)
                    if " ".join(statement.casefold().split()) == (
                        "select id, kind, payload_json from ir_records order by id"
                    ):
                        return TrackingCursor(cursor)
                    return cursor

            migration_module.validate_canonical_reference_payloads(
                TrackingConnection()  # type: ignore[arg-type]
            )

        assert observed_batches == [
            ("meta:bounded-0", "meta:bounded-1"),
            ("meta:bounded-2", "meta:bounded-3"),
            ("meta:bounded-4",),
            (),
        ]
    finally:
        store.close()
