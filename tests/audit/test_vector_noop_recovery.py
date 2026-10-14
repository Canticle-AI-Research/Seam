"""No-op replay reuses vectors without changing public search correctness."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

import pytest

import seam_runtime.vector as vectors
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.models import HashEmbeddingModel
from seam_runtime.runtime import SeamRuntime
from seam_runtime.vector import SQLiteVectorIndex
from seam_runtime.vector_adapters import SQLiteVectorAdapter
from seam_runtime.vector_outbox import enqueue_index_intents


@pytest.fixture(autouse=True)
def require_matrix_path():
    pytest.importorskip("numpy")
    assert vectors._numpy is not None


def _record(record_id: str = "raw:stable", content: str = "alpha") -> MIRLRecord:
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.RAW,
        ns="noop-recovery",
        scope="thread",
        attrs={"content": content},
        updated_at="2026-01-01T00:00:00Z",
    )


def _search(index):
    return index.search("alpha", limit=5, namespace="noop-recovery", scope="thread")


def _track_vector_loads(monkeypatch):
    loads = []
    original = vectors.json.loads

    def tracked(payload, *args, **kwargs):
        # Canonical record objects may also be decoded during outbox replay.
        # Count only numeric vector arrays, not those unrelated record reads.
        if isinstance(payload, str) and payload.startswith("["):
            loads.append(payload)
        return original(payload, *args, **kwargs)

    monkeypatch.setattr(vectors.json, "loads", tracked)
    return loads


@pytest.mark.parametrize("replay", ["same", "empty", "nonindexable", "timestamp-only"])
def test_noop_index_replay_keeps_search_order_scores_without_vector_reload(
    tmp_path, monkeypatch, replay,
):
    index = SQLiteVectorIndex(str(tmp_path / "noop.db"), HashEmbeddingModel())
    record = _record()
    index.index_records([record, _record("raw:second", "alpha beta")])
    expected = _search(index)
    assert list(expected)[0] == record.id
    loads = _track_vector_loads(monkeypatch)
    replay_records = {
        "same": [record],
        "empty": [],
        "nonindexable": [replace(record, id="meta:ignored", kind=RecordKind.META)],
        "timestamp-only": [replace(record, updated_at="2026-02-01T00:00:00Z")],
    }[replay]

    index.index_records(iter(replay_records))

    actual = _search(index)
    assert list(actual) == list(expected)
    assert actual == expected
    assert loads == [], "no-op replay must not deserialize the warmed vectors"


def test_duplicate_outbox_replay_keeps_warmed_public_search(tmp_path, monkeypatch):
    runtime = SeamRuntime(
        tmp_path / "outbox.db", embedding_model=HashEmbeddingModel(),
        allow_pgvector_env=False,
    )
    try:
        record = _record()
        runtime.persist_ir(IRBatch([record]))
        expected = _search(runtime.vector_adapter)
        assert expected
        # Reproduce a crash after indexing but before its durable acknowledgement.
        with runtime.store._pool.checkout() as connection:
            enqueue_index_intents(connection, [record.id])
            connection.commit()
        loads = _track_vector_loads(monkeypatch)

        summary = runtime.replay_vector_outbox()
        actual = _search(runtime.vector_adapter)

        assert summary["reindexed"] == 1
        assert summary["acknowledged"] == 1
        assert summary["failed"] == 0
        assert runtime.store.pending_vector_outbox_count() == 0
        assert list(actual) == list(expected)
        assert actual == expected
        assert loads == [], "duplicate outbox intent must reuse the warmed vectors"
    finally:
        runtime.close()


@pytest.mark.parametrize("mutation", ["insert", "content", "namespace", "scope"])
def test_actual_index_mutations_refresh_search(tmp_path, monkeypatch, mutation):
    index = SQLiteVectorIndex(str(tmp_path / "mutations.db"), HashEmbeddingModel())
    original = _record()
    index.index_records([original])
    expected = _search(index)
    assert list(expected) == [original.id]
    loads = _track_vector_loads(monkeypatch)
    replacement = {
        "insert": _record("raw:new", "alpha"),
        "content": replace(original, attrs={"content": "alpha beta"}),
        "namespace": replace(original, ns="other"),
        "scope": replace(original, scope="project"),
    }[mutation]

    index.index_records([replacement])
    actual = _search(index)

    if mutation == "insert":
        assert list(actual) == [replacement.id, original.id]
        assert loads
    elif mutation == "content":
        assert list(actual) == [original.id]
        assert actual != expected
        assert loads
    else:
        assert actual == {}
        assert index.search("alpha", namespace=replacement.ns, scope=replacement.scope) == expected


def test_noop_replay_still_detects_same_source_timestamp_external_vector_change(tmp_path):
    path = tmp_path / "external.db"
    model = HashEmbeddingModel()
    reader = SQLiteVectorIndex(str(path), model)
    record = _record()
    reader.index_records([record])
    assert list(_search(reader)) == [record.id]
    with sqlite3.connect(path) as connection:
        # Hold source hash, ID, timestamp and row count fixed. Only actual vector
        # bytes change, as with a same-source external replacement/restore.
        connection.execute(
            "update vector_index set vector_json = ? where record_id = ?",
            (json.dumps([0.0] * model.dimension), record.id),
        )

    reader.index_records([record])

    assert _search(reader) == {}


def test_warmed_search_respects_old_and_new_cross_instance_snapshots(tmp_path):
    model = HashEmbeddingModel()
    runtime = SeamRuntime(
        tmp_path / "snapshots.db", embedding_model=model, allow_pgvector_env=False,
    )
    try:
        record = _record()
        runtime.persist_ir(IRBatch([record]))
        reader = runtime.vector_adapter
        writer = SQLiteVectorAdapter(runtime.store.path, model)
        expected = _search(reader)
        reader.index_records([record])
        with runtime.store.read_snapshot():
            assert _search(reader) == expected
            writer.index_records([replace(record, attrs={"content": "beta"})])
            assert _search(reader) == expected
        assert _search(reader) == {}
    finally:
        runtime.close()


def test_late_embedding_failure_does_not_replace_warmed_committed_results(tmp_path):
    class FailingModel(HashEmbeddingModel):
        def embed(self, text):
            if text == "fail":
                raise RuntimeError("synthetic embedding failure")
            return super().embed(text)

    index = SQLiteVectorIndex(str(tmp_path / "rollback.db"), FailingModel())
    record = _record()
    index.index_records([record])
    expected = _search(index)

    with pytest.raises(RuntimeError, match="synthetic embedding failure"):
        index.index_records([
            replace(record, attrs={"content": "beta"}),
            _record("raw:failing", "fail"),
        ])

    assert _search(index) == expected
    assert index.search("beta", namespace=record.ns, scope=record.scope) == {}
