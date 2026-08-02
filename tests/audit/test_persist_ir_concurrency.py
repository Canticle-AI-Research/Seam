"""Concurrency regressions for canonical MIRL persistence."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.storage import SQLiteStore


def _entity_batch(index: int) -> IRBatch:
    entity_id = f"ent:melanie:{index}"
    return IRBatch(
        [
            MIRLRecord(
                id=entity_id,
                kind=RecordKind.ENT,
                ns="tenant-a",
                scope="thread",
                attrs={"entity_type": "person", "label": "Melanie"},
            ),
            MIRLRecord(
                id=f"clm:melanie:{index}",
                kind=RecordKind.CLM,
                ns="tenant-a",
                scope="thread",
                attrs={
                    "subject": entity_id,
                    "predicate": "content",
                    "object": f"memory {index}",
                },
            ),
        ]
    )


def test_persist_helper_locks_before_entity_reconciliation(
    tmp_path: Path, monkeypatch
) -> None:
    store = SQLiteStore(tmp_path / "helper-transaction.db")
    transaction_states: list[bool] = []
    reconcile = store._reconcile_entities

    def capture_transaction_state(connection, batch):
        transaction_states.append(connection.in_transaction)
        return reconcile(connection, batch)

    monkeypatch.setattr(store, "_reconcile_entities", capture_transaction_state)
    try:
        with store._pool.checkout() as connection:
            assert not connection.in_transaction
            store._persist_ir_on_connection(connection, _entity_batch(0))
            assert connection.in_transaction
            connection.rollback()
        assert store.load_ir(ns="tenant-a").records == []
    finally:
        store.close()

    assert transaction_states == [True]


def test_concurrent_persist_ir_preserves_one_canonical_entity(tmp_path: Path) -> None:
    worker_count = 8
    store = SQLiteStore(
        tmp_path / "concurrent-coreference.db", pool_size=worker_count
    )
    start = Barrier(worker_count, timeout=10)

    def persist(index: int) -> list[str]:
        start.wait()
        return store.persist_ir(_entity_batch(index)).stored_ids

    try:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            stored_ids = list(executor.map(persist, range(worker_count)))
        records = store.load_ir(ns="tenant-a").records
    finally:
        store.close()

    entities = [record for record in records if record.kind == RecordKind.ENT]
    claims = [record for record in records if record.kind == RecordKind.CLM]

    assert len(entities) == 1
    assert len(claims) == worker_count
    assert {claim.attrs["subject"] for claim in claims} == {entities[0].id}
    assert sum(len(report_ids) for report_ids in stored_ids) == worker_count + 1
