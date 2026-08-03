"""Atomic canonical restore after a failed runtime vector projection."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

import pytest

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.retrieval_orchestrator import RetrievalOrchestrator
from seam_runtime.runtime import SeamRuntime
from seam_runtime.sdk import SeamSDK
from seam_runtime.vector_adapters import MemoryVectorAdapter


class _ToggleEmbeddingModel:
    name = "test-toggle-embedding"
    dimension = 2

    def __init__(self) -> None:
        self.fail = False

    def embed(self, _text: str) -> list[float]:
        if self.fail and "trigger failure" in _text:
            raise RuntimeError(
                "private vector failure for ent:rollback-required-target"
            )
        return [1.0, 0.0]


class _BlockingFailingMemoryAdapter(MemoryVectorAdapter):
    def __init__(self, model: _ToggleEmbeddingModel) -> None:
        super().__init__(model)
        self.entered = threading.Event()
        self.release = threading.Event()
        self.failed_once = False

    def index_records(self, records: list[MIRLRecord]) -> None:
        should_fail = any(
            record.attrs.get("object") == "writer-a" for record in records
        )
        if should_fail and not self.failed_once:
            super().index_records(records)
            self.failed_once = True
            self.entered.set()
            if not self.release.wait(timeout=5):
                raise RuntimeError("timed out waiting to inject vector failure")
            raise RuntimeError("injected writer-a vector failure")
        super().index_records(records)


class _BlockingDeleteMemoryAdapter(MemoryVectorAdapter):
    def __init__(self, model: _ToggleEmbeddingModel) -> None:
        super().__init__(model)
        self.entered = threading.Event()
        self.release = threading.Event()

    def delete_records(self, record_ids: list[str]) -> None:
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise RuntimeError("timed out waiting to release derived deletion")
        super().delete_records(record_ids)


def _logical_table_hashes(path: Path) -> dict[str, str]:
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
            columns = [
                str(row[1])
                for row in connection.execute(
                    f'pragma table_info("{table}")'
                )
            ]
            order_by = ", ".join(f'"{column}"' for column in columns)
            rows = connection.execute(
                f'select * from "{table}" order by {order_by}'
            ).fetchall()
            schema = connection.execute(
                "select sql from sqlite_master where type = 'table' and name = ?",
                (table,),
            ).fetchone()[0]
            material = json.dumps(
                {"schema": schema, "rows": rows},
                sort_keys=True,
                separators=(",", ":"),
            )
            hashes[table] = hashlib.sha256(material.encode("utf-8")).hexdigest()
        return hashes


def test_vector_failure_atomically_restores_touched_required_target(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    path = tmp_path / "runtime-atomic-restore.sqlite3"
    model = _ToggleEmbeddingModel()
    runtime = SeamRuntime(path, embedding_model=model)
    source = MIRLRecord(
        id="ent:rollback-source",
        kind=RecordKind.ENT,
        attrs={"label": "Source", "entity_type": "test"},
    )
    target = MIRLRecord(
        id="ent:rollback-required-target",
        kind=RecordKind.ENT,
        attrs={"label": "Original target", "entity_type": "test"},
    )
    surviving_referrer = MIRLRecord(
        id="rel:rollback-surviving-referrer",
        kind=RecordKind.REL,
        attrs={"src": source.id, "predicate": "requires", "dst": target.id},
    )
    existing_claim = MIRLRecord(
        id="clm:a-rollback-existing",
        kind=RecordKind.CLM,
        attrs={
            "subject": source.id,
            "predicate": "mentions",
            "object": "original vector",
        },
    )
    try:
        runtime.persist_ir(
            IRBatch([source, target, surviving_referrer, existing_claim])
        )
        before_hashes = _logical_table_hashes(path)
        before_bytes = path.read_bytes()

        changed_target = MIRLRecord.from_dict(target.to_dict())
        changed_target.attrs["label"] = "Changed target"
        changed_claim = MIRLRecord.from_dict(existing_claim.to_dict())
        changed_claim.attrs["object"] = "changed vector"
        introduced_claim = MIRLRecord(
            id="clm:z-private-rollback-introduced",
            kind=RecordKind.CLM,
            attrs={
                "subject": source.id,
                "predicate": "mentions",
                "object": "trigger failure",
            },
        )
        model.fail = True
        caplog.clear()

        with pytest.raises(
            RuntimeError,
            match="canonical and vector writes were restored",
        ) as raised:
            runtime.persist_ir(
                IRBatch([changed_target, changed_claim, introduced_claim])
            )

        diagnostics = "\n".join(
            [str(raised.value), *(record.getMessage() for record in caplog.records)]
        )
        for private_id in (
            target.id,
            surviving_referrer.id,
            existing_claim.id,
            introduced_claim.id,
        ):
            assert private_id not in diagnostics
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None
        assert path.read_bytes() == before_bytes
        assert _logical_table_hashes(path) == before_hashes
        assert runtime.store.load_ir(ids=[introduced_claim.id]).records == []
        restored = runtime.store.load_ir(ids=[target.id]).records[0]
        assert restored.to_dict() == target.to_dict()
        restored_claim = runtime.store.load_ir(ids=[existing_claim.id]).records[0]
        assert restored_claim.to_dict() == existing_claim.to_dict()
        assert [
            record.id
            for record in runtime.store.load_ir(ids=[surviving_referrer.id]).records
        ] == [surviving_referrer.id]
    finally:
        runtime.close()


def test_partial_memory_adapter_write_is_compensated_to_prior_canonical_state(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime-memory-adapter-restore.sqlite3"
    model = _ToggleEmbeddingModel()
    adapter = MemoryVectorAdapter(model)
    runtime = SeamRuntime(path, embedding_model=model, vector_adapter=adapter)
    source = MIRLRecord(
        id="ent:memory-rollback-source",
        kind=RecordKind.ENT,
        attrs={"label": "Memory rollback source", "entity_type": "test"},
    )
    existing = MIRLRecord(
        id="clm:a-memory-rollback-existing",
        kind=RecordKind.CLM,
        attrs={
            "subject": source.id,
            "predicate": "mentions",
            "object": "original vector",
        },
    )
    try:
        runtime.persist_ir(IRBatch([source, existing]))
        before_hashes = _logical_table_hashes(path)
        before_record = adapter._rows[existing.id][0].to_dict()
        before_vector = list(adapter._rows[existing.id][1])

        changed = MIRLRecord.from_dict(existing.to_dict())
        changed.attrs["object"] = "changed vector"
        introduced = MIRLRecord(
            id="clm:z-memory-rollback-introduced",
            kind=RecordKind.CLM,
            attrs={
                "subject": source.id,
                "predicate": "mentions",
                "object": "trigger failure",
            },
        )
        model.fail = True

        with pytest.raises(
            RuntimeError,
            match="canonical and vector writes were restored",
        ):
            runtime.persist_ir(IRBatch([changed, introduced]))

        assert _logical_table_hashes(path) == before_hashes
        assert introduced.id not in adapter._rows
        restored_record, restored_vector = adapter._rows[existing.id]
        assert restored_record.to_dict() == before_record
        assert restored_vector == before_vector
        assert runtime.store.load_ir(ids=[existing.id]).records[0].to_dict() == (
            existing.to_dict()
        )
    finally:
        runtime.close()


def test_external_vector_restore_failure_is_explicit_and_content_free(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "runtime-external-restore-error.sqlite3"
    model = _ToggleEmbeddingModel()
    adapter = MemoryVectorAdapter(model)
    runtime = SeamRuntime(path, embedding_model=model, vector_adapter=adapter)
    source = MIRLRecord(
        id="ent:private-external-restore-source",
        kind=RecordKind.ENT,
        attrs={"label": "External restore source", "entity_type": "test"},
    )
    introduced = MIRLRecord(
        id="clm:private-external-restore-record",
        kind=RecordKind.CLM,
        attrs={
            "subject": source.id,
            "predicate": "mentions",
            "object": "trigger failure",
        },
    )
    try:
        runtime.persist_ir(IRBatch([source]))
        model.fail = True

        def fail_delete(_record_ids: list[str]) -> None:
            raise RuntimeError(
                "private adapter restore failure for "
                "clm:private-external-restore-record"
            )

        monkeypatch.setattr(adapter, "delete_records", fail_delete)
        caplog.clear()
        with pytest.raises(
            RuntimeError,
            match="external vector restore failed",
        ) as raised:
            runtime.persist_ir(IRBatch([introduced]))

        diagnostics = "\n".join(
            [str(raised.value), *(record.getMessage() for record in caplog.records)]
        )
        for private_id in (source.id, introduced.id):
            assert private_id not in diagnostics
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None
        assert runtime.store.load_ir(ids=[introduced.id]).records == []
    finally:
        runtime.close()


def test_failed_writer_cannot_restore_over_later_same_process_success(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime-concurrent-restore.sqlite3"
    model = _ToggleEmbeddingModel()
    adapter = _BlockingFailingMemoryAdapter(model)
    runtime_a = SeamRuntime(path, embedding_model=model, vector_adapter=adapter)
    runtime_b = SeamRuntime(path, embedding_model=model, vector_adapter=adapter)
    source = MIRLRecord(
        id="ent:concurrent-rollback-source",
        kind=RecordKind.ENT,
        attrs={"label": "Concurrent rollback source", "entity_type": "test"},
    )
    original = MIRLRecord(
        id="clm:concurrent-rollback-record",
        kind=RecordKind.CLM,
        attrs={
            "subject": source.id,
            "predicate": "value",
            "object": "original",
        },
    )
    writer_a = MIRLRecord.from_dict(original.to_dict())
    writer_a.attrs["object"] = "writer-a"
    writer_b = MIRLRecord.from_dict(original.to_dict())
    writer_b.attrs["object"] = "writer-b"
    outcomes: dict[str, object] = {}
    writer_b_done = threading.Event()

    def run_writer_a() -> None:
        try:
            runtime_a.persist_ir(IRBatch([writer_a]))
        except Exception as exc:  # noqa: BLE001 - capture the thread outcome
            outcomes["writer_a_error"] = exc

    def run_writer_b() -> None:
        try:
            outcomes["writer_b_report"] = runtime_b.persist_ir(IRBatch([writer_b]))
        except Exception as exc:  # noqa: BLE001 - capture the thread outcome
            outcomes["writer_b_error"] = exc
        finally:
            writer_b_done.set()

    try:
        runtime_a.persist_ir(IRBatch([source, original]))
        thread_a = threading.Thread(target=run_writer_a)
        thread_a.start()
        assert adapter.entered.wait(timeout=5)

        thread_b = threading.Thread(target=run_writer_b)
        thread_b.start()
        assert not writer_b_done.wait(timeout=0.1)

        adapter.release.set()
        thread_a.join(timeout=5)
        thread_b.join(timeout=5)
        assert not thread_a.is_alive()
        assert not thread_b.is_alive()
        assert isinstance(outcomes.get("writer_a_error"), RuntimeError)
        assert "writer_b_error" not in outcomes
        assert "writer_b_report" in outcomes

        canonical = runtime_a.store.load_ir(ids=[original.id]).records[0]
        assert canonical.attrs["object"] == "writer-b"
        projected = adapter._rows[original.id][0]
        assert projected.attrs["object"] == "writer-b"
    finally:
        adapter.release.set()
        runtime_a.close()
        runtime_b.close()


def test_reindex_cannot_publish_transient_canonical_write(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime-concurrent-reindex.sqlite3"
    model = _ToggleEmbeddingModel()
    adapter = _BlockingFailingMemoryAdapter(model)
    runtime_a = SeamRuntime(path, embedding_model=model, vector_adapter=adapter)
    runtime_b = SeamRuntime(path, embedding_model=model, vector_adapter=adapter)
    source = MIRLRecord(
        id="ent:concurrent-reindex-source",
        kind=RecordKind.ENT,
        attrs={"label": "Concurrent reindex source", "entity_type": "test"},
    )
    original = MIRLRecord(
        id="clm:concurrent-reindex-record",
        kind=RecordKind.CLM,
        attrs={
            "subject": source.id,
            "predicate": "value",
            "object": "original",
        },
    )
    transient = MIRLRecord.from_dict(original.to_dict())
    transient.attrs["object"] = "writer-a"
    outcomes: dict[str, object] = {}
    reindex_done = threading.Event()

    def run_writer() -> None:
        try:
            runtime_a.persist_ir(IRBatch([transient]))
        except Exception as exc:  # noqa: BLE001 - capture the thread outcome
            outcomes["writer_error"] = exc

    def run_reindex() -> None:
        try:
            outcomes["reindex_report"] = runtime_b.reindex_vectors(
                [original.id]
            )
        except Exception as exc:  # noqa: BLE001 - capture the thread outcome
            outcomes["reindex_error"] = exc
        finally:
            reindex_done.set()

    try:
        runtime_a.persist_ir(IRBatch([source, original]))
        writer = threading.Thread(target=run_writer)
        writer.start()
        assert adapter.entered.wait(timeout=5)

        reindexer = threading.Thread(target=run_reindex)
        reindexer.start()
        assert not reindex_done.wait(timeout=0.1)

        adapter.release.set()
        writer.join(timeout=5)
        reindexer.join(timeout=5)
        assert not writer.is_alive()
        assert not reindexer.is_alive()
        assert isinstance(outcomes.get("writer_error"), RuntimeError)
        assert "reindex_error" not in outcomes
        assert "reindex_report" in outcomes

        canonical = runtime_a.store.load_ir(ids=[original.id]).records[0]
        projected = adapter._rows[original.id][0]
        assert canonical.attrs["object"] == "original"
        assert projected.attrs["object"] == "original"
    finally:
        adapter.release.set()
        runtime_a.close()
        runtime_b.close()


def test_node_vector_projection_cannot_publish_transient_graph_write(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime-concurrent-node-projection.sqlite3"
    model = _ToggleEmbeddingModel()
    adapter = _BlockingFailingMemoryAdapter(model)
    runtime_a = SeamRuntime(path, embedding_model=model, vector_adapter=adapter)
    runtime_b = SeamRuntime(path, embedding_model=model, vector_adapter=adapter)
    source = MIRLRecord(
        id="ent:concurrent-node-source",
        kind=RecordKind.ENT,
        attrs={"label": "Concurrent node source", "entity_type": "test"},
    )
    original = MIRLRecord(
        id="clm:concurrent-node-record",
        kind=RecordKind.CLM,
        attrs={
            "subject": source.id,
            "predicate": "value",
            "object": "original",
        },
    )
    transient = MIRLRecord.from_dict(original.to_dict())
    transient.attrs["object"] = "writer-a"
    outcomes: dict[str, object] = {}
    projection_done = threading.Event()

    def run_writer() -> None:
        try:
            runtime_a.persist_ir(IRBatch([transient]))
        except Exception as exc:  # noqa: BLE001 - capture the thread outcome
            outcomes["writer_error"] = exc

    def run_projection() -> None:
        try:
            outcomes["projection_report"] = runtime_b.project_node_vectors()
        except Exception as exc:  # noqa: BLE001 - capture the thread outcome
            outcomes["projection_error"] = exc
        finally:
            projection_done.set()

    try:
        runtime_a.persist_ir(IRBatch([source, original]))
        before_hashes = _logical_table_hashes(path)
        writer = threading.Thread(target=run_writer)
        writer.start()
        assert adapter.entered.wait(timeout=5)

        projector = threading.Thread(target=run_projection)
        projector.start()
        assert not projection_done.wait(timeout=0.1)

        adapter.release.set()
        writer.join(timeout=5)
        projector.join(timeout=5)
        assert not writer.is_alive()
        assert not projector.is_alive()
        assert isinstance(outcomes.get("writer_error"), RuntimeError)
        assert "projection_error" not in outcomes
        assert "projection_report" in outcomes
        assert _logical_table_hashes(path) == before_hashes

        canonical = runtime_a.store.load_ir(ids=[original.id]).records[0]
        projected = adapter._rows[original.id][0]
        assert canonical.attrs["object"] == "original"
        assert projected.attrs["object"] == "original"
    finally:
        adapter.release.set()
        runtime_a.close()
        runtime_b.close()


def test_scoped_delete_cannot_erase_later_same_process_vector_write(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime-concurrent-scoped-delete.sqlite3"
    model = _ToggleEmbeddingModel()
    adapter = _BlockingDeleteMemoryAdapter(model)
    runtime_a = SeamRuntime(path, embedding_model=model, vector_adapter=adapter)
    runtime_b = SeamRuntime(path, embedding_model=model, vector_adapter=adapter)
    source = MIRLRecord(
        id="ent:concurrent-delete-source",
        kind=RecordKind.ENT,
        ns="tenant-a",
        scope="thread",
        attrs={"label": "Concurrent delete source", "entity_type": "test"},
    )
    original = MIRLRecord(
        id="clm:concurrent-delete-record",
        kind=RecordKind.CLM,
        ns="tenant-a",
        scope="thread",
        attrs={
            "subject": source.id,
            "predicate": "value",
            "object": "original",
        },
    )
    replacement = MIRLRecord.from_dict(original.to_dict())
    replacement.attrs["object"] = "writer-b"
    outcomes: dict[str, object] = {}
    writer_done = threading.Event()

    def run_delete(operation_id: str) -> None:
        try:
            outcomes["delete_report"] = runtime_a.apply_scoped_delete(
                tenant_id="tenant-a",
                operation_id=operation_id,
                actor="deleter",
            )
        except Exception as exc:  # noqa: BLE001 - capture the thread outcome
            outcomes["delete_error"] = exc

    def run_writer() -> None:
        try:
            outcomes["writer_report"] = runtime_b.persist_ir(
                IRBatch([replacement])
            )
        except Exception as exc:  # noqa: BLE001 - capture the thread outcome
            outcomes["writer_error"] = exc
        finally:
            writer_done.set()

    try:
        runtime_a.persist_ir(IRBatch([source, original]))
        operation = runtime_a.plan_scoped_delete(
            tenant_id="tenant-a",
            namespace="tenant-a",
            scope="thread",
            record_ids=[original.id],
            idempotency_key="concurrent-scoped-delete",
            actor="deleter",
        )
        deleter = threading.Thread(
            target=run_delete,
            args=(str(operation["operation_id"]),),
        )
        deleter.start()
        assert adapter.entered.wait(timeout=5)

        writer = threading.Thread(target=run_writer)
        writer.start()
        assert not writer_done.wait(timeout=0.1)

        adapter.release.set()
        deleter.join(timeout=5)
        writer.join(timeout=5)
        assert not deleter.is_alive()
        assert not writer.is_alive()
        assert "delete_error" not in outcomes
        assert "writer_error" not in outcomes
        assert outcomes["delete_report"]["state"] == "applied"  # type: ignore[index]

        canonical = runtime_a.store.load_ir(ids=[original.id]).records[0]
        projected = adapter._rows[original.id][0]
        assert canonical.status.value == "asserted"
        assert canonical.attrs["object"] == "writer-b"
        assert projected.attrs["object"] == "writer-b"
    finally:
        adapter.release.set()
        runtime_a.close()
        runtime_b.close()


def test_runtime_reconciliation_indexes_every_added_claim_like_record(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime-reconcile-vector-coverage.sqlite3"
    runtime = SeamRuntime(path, allow_pgvector_env=False)
    subject = MIRLRecord(
        id="ent:reconcile-vector-subject",
        kind=RecordKind.ENT,
        attrs={"label": "Reconcile vector subject", "entity_type": "test"},
    )
    claims = [
        MIRLRecord(
            id=f"clm:reconcile-vector-{index}",
            kind=RecordKind.CLM,
            attrs={
                "subject": subject.id,
                "predicate": "state",
                "object": value,
            },
        )
        for index, value in enumerate(("first", "second"))
    ]
    try:
        runtime.persist_ir(IRBatch([subject, *claims]))
        report = runtime.reconcile_ir([subject.id, *(claim.id for claim in claims)])
        added_ids = {
            record.id
            for record in report.added_records
            if record.kind in {RecordKind.REL, RecordKind.STA}
        }
        assert {record.kind for record in report.added_records} == {
            RecordKind.REL,
            RecordKind.STA,
        }
        with runtime.store._pool.checkout() as connection:
            placeholders = ",".join("?" for _ in added_ids)
            indexed_ids = {
                str(row[0])
                for row in connection.execute(
                    "select record_id from vector_index where model_name = ? "
                    f"and record_id in ({placeholders})",
                    [runtime.embedding_model.name, *sorted(added_ids)],
                ).fetchall()
            }
        assert indexed_ids == added_ids
    finally:
        runtime.close()


def test_graph_product_rebuild_cannot_snapshot_transient_graph_write(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime-concurrent-graph-products.sqlite3"
    model = _ToggleEmbeddingModel()
    adapter = _BlockingFailingMemoryAdapter(model)
    runtime_a = SeamRuntime(path, embedding_model=model, vector_adapter=adapter)
    runtime_b = SeamRuntime(path, embedding_model=model, vector_adapter=adapter)
    raw_records = [
        MIRLRecord(
            id=f"raw:transient-graph-product-{index}",
            kind=RecordKind.RAW,
            ns="tenant-a",
            scope="thread",
            attrs={
                "content": f"Transient graph fact {index}",
                "source_ref": f"local://race/{index}",
            },
        )
        for index in range(2)
    ]
    subject = MIRLRecord(
        id="ent:transient-graph-product",
        kind=RecordKind.ENT,
        ns="tenant-a",
        scope="thread",
        attrs={"label": "Transient subject", "entity_type": "test"},
    )
    transient = MIRLRecord(
        id="clm:transient-graph-product",
        kind=RecordKind.CLM,
        ns="tenant-a",
        scope="thread",
        evidence=[record.id for record in raw_records],
        attrs={
            "subject": subject.id,
            "predicate": "value",
            "object": "writer-a",
        },
    )
    outcomes: dict[str, object] = {}
    rebuild_done = threading.Event()

    def run_writer() -> None:
        try:
            runtime_a.persist_ir(IRBatch([*raw_records, subject, transient]))
        except Exception as exc:  # noqa: BLE001 - capture the thread outcome
            outcomes["writer_error"] = exc

    def run_rebuild() -> None:
        try:
                outcomes["rebuild_report"] = runtime_b.rebuild_graph_products(
                    namespace="tenant-a",
                    scope="thread",
                )
        except Exception as exc:  # noqa: BLE001 - capture the thread outcome
            outcomes["rebuild_error"] = exc
        finally:
            rebuild_done.set()

    try:
        writer = threading.Thread(target=run_writer)
        writer.start()
        assert adapter.entered.wait(timeout=5)

        rebuilder = threading.Thread(target=run_rebuild)
        rebuilder.start()
        assert not rebuild_done.wait(timeout=0.1)

        adapter.release.set()
        writer.join(timeout=5)
        rebuilder.join(timeout=5)
        assert not writer.is_alive()
        assert not rebuilder.is_alive()
        assert isinstance(outcomes.get("writer_error"), RuntimeError)
        assert "rebuild_error" not in outcomes
        report = outcomes["rebuild_report"]
        assert report["accepted_fact_count"] == 0  # type: ignore[index]
        assert runtime_a.store.load_ir().records == []
        products = runtime_b.graph_products(
            namespace="tenant-a",
            scope="thread",
        )
        assert all(
            transient.id not in sentence["supporting_record_ids"]
            for product in products
            for sentence in product["sentences"]
        )
    finally:
        adapter.release.set()
        runtime_a.close()
        runtime_b.close()


def test_persistent_index_sync_cannot_publish_transient_canonical_write(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime-concurrent-index-sync.sqlite3"
    model = _ToggleEmbeddingModel()
    adapter = _BlockingFailingMemoryAdapter(model)
    runtime_a = SeamRuntime(path, embedding_model=model, vector_adapter=adapter)
    runtime_b = SeamRuntime(path, embedding_model=model, vector_adapter=adapter)
    source = MIRLRecord(
        id="ent:transient-index-sync",
        kind=RecordKind.ENT,
        attrs={"label": "Transient index source", "entity_type": "test"},
    )
    transient = MIRLRecord(
        id="clm:transient-index-sync",
        kind=RecordKind.CLM,
        attrs={
            "subject": source.id,
            "predicate": "value",
            "object": "writer-a",
        },
    )
    outcomes: dict[str, object] = {}
    sync_done = threading.Event()

    def run_writer() -> None:
        try:
            runtime_a.persist_ir(IRBatch([source, transient]))
        except Exception as exc:  # noqa: BLE001 - capture the thread outcome
            outcomes["writer_error"] = exc

    def run_sync() -> None:
        try:
            outcomes["sync_report"] = RetrievalOrchestrator(
                runtime_b
            ).sync_persistent_indexes(record_ids=[source.id, transient.id])
        except Exception as exc:  # noqa: BLE001 - capture the thread outcome
            outcomes["sync_error"] = exc
        finally:
            sync_done.set()

    try:
        writer = threading.Thread(target=run_writer)
        writer.start()
        assert adapter.entered.wait(timeout=5)

        syncer = threading.Thread(target=run_sync)
        syncer.start()
        assert not sync_done.wait(timeout=0.1)

        adapter.release.set()
        writer.join(timeout=5)
        syncer.join(timeout=5)
        assert not writer.is_alive()
        assert not syncer.is_alive()
        assert isinstance(outcomes.get("writer_error"), RuntimeError)
        assert "sync_error" not in outcomes
        assert outcomes["sync_report"]["record_ids"] == []  # type: ignore[index]
        assert runtime_a.store.load_ir().records == []
        assert adapter._rows == {}
    finally:
        adapter.release.set()
        runtime_a.close()
        runtime_b.close()


def test_symbol_promotion_cannot_learn_from_transient_canonical_write(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime-concurrent-symbol-promotion.sqlite3"
    model = _ToggleEmbeddingModel()
    adapter = _BlockingFailingMemoryAdapter(model)
    runtime_a = SeamRuntime(path, embedding_model=model, vector_adapter=adapter)
    runtime_b = SeamRuntime(path, embedding_model=model, vector_adapter=adapter)
    subject = MIRLRecord(
        id="ent:transient-symbol-source",
        kind=RecordKind.ENT,
        attrs={"label": "Transient symbol source", "entity_type": "x"},
    )
    claims = [
        MIRLRecord(
            id=f"clm:transient-symbol-{index}",
            kind=RecordKind.CLM,
            attrs={
                "subject": subject.id,
                "predicate": "longpredicate",
                "object": "writer-a",
            },
        )
        for index in range(2)
    ]
    outcomes: dict[str, object] = {}
    promotion_done = threading.Event()

    def run_writer() -> None:
        try:
            runtime_a.persist_ir(IRBatch([subject, *claims]))
        except Exception as exc:  # noqa: BLE001 - capture the thread outcome
            outcomes["writer_error"] = exc

    def run_promotion() -> None:
        try:
            outcomes["promotion_report"] = runtime_b.promote_symbols(
                min_frequency=2
            )
        except Exception as exc:  # noqa: BLE001 - capture the thread outcome
            outcomes["promotion_error"] = exc
        finally:
            promotion_done.set()

    try:
        writer = threading.Thread(target=run_writer)
        writer.start()
        assert adapter.entered.wait(timeout=5)

        promoter = threading.Thread(target=run_promotion)
        promoter.start()
        assert not promotion_done.wait(timeout=0.1)

        adapter.release.set()
        writer.join(timeout=5)
        promoter.join(timeout=5)
        assert not writer.is_alive()
        assert not promoter.is_alive()
        assert isinstance(outcomes.get("writer_error"), RuntimeError)
        assert "promotion_error" not in outcomes
        assert outcomes["promotion_report"].stored_ids == []  # type: ignore[union-attr]
        assert runtime_a.store.load_ir().records == []
    finally:
        adapter.release.set()
        runtime_a.close()
        runtime_b.close()


def test_reasoning_retrieval_cannot_audit_transient_candidate(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime-concurrent-reasoning-retrieval.sqlite3"
    model = _ToggleEmbeddingModel()
    adapter = _BlockingFailingMemoryAdapter(model)
    runtime_a = SeamRuntime(path, embedding_model=model, vector_adapter=adapter)
    runtime_b = SeamRuntime(path, embedding_model=model, vector_adapter=adapter)
    sdk = SeamSDK(runtime=runtime_b)
    session = sdk.start_reasoning(
        "Inspect stable memory.",
        ns="tenant-a",
        scope="thread",
        agent_id="auditor",
    )
    subject = MIRLRecord(
        id="ent:transient-reasoning-source",
        kind=RecordKind.ENT,
        ns="tenant-a",
        scope="thread",
        attrs={"label": "Transient reasoning source", "entity_type": "test"},
    )
    transient = MIRLRecord(
        id="clm:transient-reasoning-candidate",
        kind=RecordKind.CLM,
        ns="tenant-a",
        scope="thread",
        attrs={
            "subject": subject.id,
            "predicate": "value",
            "object": "writer-a",
        },
    )
    outcomes: dict[str, object] = {}
    retrieval_done = threading.Event()

    def run_writer() -> None:
        try:
            runtime_a.persist_ir(IRBatch([subject, transient]))
        except Exception as exc:  # noqa: BLE001 - capture the thread outcome
            outcomes["writer_error"] = exc

    def run_retrieval() -> None:
        try:
            outcomes["retrieval"] = session.retrieve(
                "writer-a",
                semantic_graph_seeding=False,
            )
        except Exception as exc:  # noqa: BLE001 - capture the thread outcome
            outcomes["retrieval_error"] = exc
        finally:
            retrieval_done.set()

    try:
        writer = threading.Thread(target=run_writer)
        writer.start()
        assert adapter.entered.wait(timeout=5)

        retriever = threading.Thread(target=run_retrieval)
        retriever.start()
        assert not retrieval_done.wait(timeout=0.1)

        adapter.release.set()
        writer.join(timeout=5)
        retriever.join(timeout=5)
        assert not writer.is_alive()
        assert not retriever.is_alive()
        assert isinstance(outcomes.get("writer_error"), RuntimeError)
        assert "retrieval_error" not in outcomes
        reasoned = outcomes["retrieval"]
        assert reasoned.result.ranked == []  # type: ignore[union-attr]
        audits = session.retrievals(include_candidates=True)
        assert len(audits) == 1
        assert audits[0]["candidates"] == []
        assert runtime_a.store.load_ir().records == []
    finally:
        adapter.release.set()
        runtime_a.close()
        runtime_b.close()


def test_failed_record_index_preserves_indirect_provenance_node_vectors(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime-indirect-node-vector-restore.sqlite3"
    model = _ToggleEmbeddingModel()
    runtime = SeamRuntime(path, embedding_model=model)
    raw = MIRLRecord(
        id="raw:indirect-vector-source",
        kind=RecordKind.RAW,
        prov=["prov:indirect-vector-attribution"],
        attrs={"content": "Indirect vector source", "source_ref": "local://raw"},
    )
    subject = MIRLRecord(
        id="ent:indirect-vector-subject",
        kind=RecordKind.ENT,
        attrs={"label": "Indirect vector subject", "entity_type": "thing"},
    )
    provenance = MIRLRecord(
        id="prov:indirect-vector-attribution",
        kind=RecordKind.PROV,
        ext={"agent_id": "alpha"},
        attrs={"entity": raw.id, "activity": "observed"},
    )
    try:
        runtime.persist_ir(IRBatch([raw, subject, provenance]))
        with runtime.store._pool.checkout() as connection:
            alpha_node = connection.execute(
                "select id from knowledge_nodes where kind = 'agent' "
                "and agent_id = 'alpha'",
            ).fetchone()[0]
            assert connection.execute(
                "select 1 from knowledge_node_vectors where node_id = ?",
                (alpha_node,),
            ).fetchone() is not None
        before_hashes = _logical_table_hashes(path)
        before_bytes = path.read_bytes()

        changed_provenance = MIRLRecord.from_dict(provenance.to_dict())
        changed_provenance.ext["agent_id"] = "beta"
        introduced = MIRLRecord(
            id="clm:indirect-vector-failure",
            kind=RecordKind.CLM,
            attrs={
                "subject": subject.id,
                "predicate": "mentions",
                "object": "trigger failure",
            },
        )
        model.fail = True
        with pytest.raises(
            RuntimeError,
            match="canonical and vector writes were restored",
        ):
            runtime.persist_ir(IRBatch([changed_provenance, introduced]))

        assert path.read_bytes() == before_bytes
        assert _logical_table_hashes(path) == before_hashes
        with runtime.store._pool.checkout() as connection:
            assert connection.execute(
                "select 1 from knowledge_node_vectors where node_id = ?",
                (alpha_node,),
            ).fetchone() is not None
            assert connection.execute(
                "select 1 from knowledge_nodes where kind = 'agent' "
                "and agent_id = 'beta'",
            ).fetchone() is None
    finally:
        runtime.close()


def test_vector_and_restore_failures_do_not_expose_canonical_ids(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "runtime-restore-error-redaction.sqlite3"
    model = _ToggleEmbeddingModel()
    runtime = SeamRuntime(path, embedding_model=model)
    source = MIRLRecord(
        id="ent:private-restore-log-source",
        kind=RecordKind.ENT,
        attrs={"label": "Restore source", "entity_type": "test"},
    )
    introduced = MIRLRecord(
        id="clm:private-restore-log-record",
        kind=RecordKind.CLM,
        attrs={
            "subject": source.id,
            "predicate": "mentions",
            "object": "trigger failure",
        },
    )
    try:
        runtime.persist_ir(IRBatch([source]))
        model.fail = True

        def fail_restore(
            _previous: IRBatch,
            _touched_ids: list[str],
            *,
            previous_vector_rows: object,
        ) -> None:
            del previous_vector_rows
            raise RuntimeError(
                "private restore failure for clm:private-restore-log-record"
            )

        monkeypatch.setattr(
            runtime.store,
            "restore_ir_after_failed_projection",
            fail_restore,
        )
        caplog.clear()
        with pytest.raises(
            RuntimeError,
            match="canonical restore failed",
        ) as raised:
            runtime.persist_ir(IRBatch([introduced]))

        diagnostics = "\n".join(
            [str(raised.value), *(record.getMessage() for record in caplog.records)]
        )
        for private_id in (
            source.id,
            introduced.id,
            "ent:rollback-required-target",
        ):
            assert private_id not in diagnostics
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None
    finally:
        runtime.close()
