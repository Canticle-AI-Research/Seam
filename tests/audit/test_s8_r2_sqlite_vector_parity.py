"""Exact SQLite vector membership, cache freshness, and snapshot contracts."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

import seam_runtime.models as models
import seam_runtime.vector as vectors
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.runtime import SeamRuntime
from seam_runtime.vector_adapters import SQLiteVectorAdapter


class _FixedEmbedding:
    name = "r2-sqlite-exact-fixture/1"
    dimension = 2

    def embed(self, text):
        if "near-lower" in text:
            return [1.0, 1.0 + 2**-25]
        if "near-higher" in text or "diagonal" in text:
            return [1.0, 1.0]
        if "negative" in text:
            return [-1.0, 0.0]
        if "zero" in text:
            return [0.0, 0.0]
        return [1.0, 0.0]


def _record(record_id, content="positive", *, ns="selected", scope="thread"):
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.RAW,
        ns=ns,
        scope=scope,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        attrs={"content": content},
    )


def _reference_cosine(left, right):
    """Test-owned baseline arithmetic; no production ranking/scoring helper."""
    if models._numpy is not None:
        np = models._numpy
        left_array = np.asarray(left, dtype=np.float64)
        right_array = np.asarray(right, dtype=np.float64)
        denominator = float(np.linalg.norm(left_array)) * float(np.linalg.norm(right_array))
        return float(left_array @ right_array) / denominator if denominator else 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    denominator = math.sqrt(sum(a * a for a in left)) * math.sqrt(sum(b * b for b in right))
    return numerator / denominator if denominator else 0.0


def _oracle(records, model, limit):
    scored = [
        (record.id, _reference_cosine(model.embed("query"), model.embed(record.attrs["content"])))
        for record in records
        if record.ns == "selected" and record.scope == "thread"
    ]
    return dict(sorted((item for item in scored if item[1] > 0), key=lambda item: (-item[1], item[0]))[:limit])


_PATHS = ["scan", "python"] + (["cached"] if vectors._numpy is not None else [])


@pytest.fixture(params=_PATHS)
def numeric_path(request, monkeypatch):
    if request.param != "cached":
        monkeypatch.setattr(vectors, "_numpy", None)
    if request.param == "python":
        monkeypatch.setattr(models, "_numpy", None)
    return request.param


@pytest.mark.parametrize("reverse", [False, True])
def test_public_vector_ties_choose_smallest_ids_before_backend_and_runtime_cutoffs(
    tmp_path, numeric_path, reverse
):
    model = _FixedEmbedding()
    runtime = SeamRuntime(tmp_path / "ties.db", embedding_model=model, allow_pgvector_env=False)
    try:
        records = [_record(f"raw:{index:03d}") for index in range(48)]
        records += [_record("raw:negative", "negative"), _record("raw:zero", "zero")]
        records += [_record("raw:outside", ns="other"), _record("raw:scope", scope="other")]
        if reverse:
            records.reverse()
        runtime.store.persist_ir(IRBatch(records))
        runtime.vector_adapter.index_records(records)
        for limit in (1, 5, 17, 100):
            expected = _oracle(records, model, limit)
            for _ in range(2):
                actual = runtime.vector_adapter.search("query", limit=limit, namespace="selected", scope="thread")
                assert list(actual) == list(expected)
                assert actual == expected
        result = runtime.retrieve(
            "query", mode="vector", ns="selected", scope="thread", budget=3,
            include_raw=True, include_trace=True,
        )
        assert [candidate.record.id for candidate in result.candidates] == ["raw:000", "raw:001", "raw:002"]
        assert [hit["record_id"] for hit in result.trace["legs"]["vector"]] == [f"raw:{index:03d}" for index in range(3)]
        # Reindexing changes SQLite row order; rank membership must remain stable.
        runtime.vector_adapter.index_records(list(reversed(records)))
        assert list(runtime.vector_adapter.search("query", limit=5, namespace="selected", scope="thread")) == [f"raw:{index:03d}" for index in range(5)]
    finally:
        runtime.close()


def test_exact_vector_near_tie_preserves_original_precision(tmp_path, numeric_path):
    adapter = SQLiteVectorAdapter(str(tmp_path / "precision.db"), _FixedEmbedding())
    records = [_record("raw:a", "near-lower"), _record("raw:z", "near-higher")]
    adapter.index_records(records)
    expected = _oracle(records, adapter.model, 2)
    assert list(expected) == ["raw:z", "raw:a"]
    for _ in range(2):
        actual = adapter.search("query", limit=2, namespace="selected", scope="thread")
        assert list(actual) == list(expected)
        assert actual == expected
        assert list(adapter.search("query", limit=1, namespace="selected", scope="thread")) == ["raw:z"]


@pytest.mark.parametrize("replacement_timestamp", ["2026-01-01T00:00:00Z", "2025-01-01T00:00:00Z"])
def test_public_vector_cache_refreshes_same_count_without_new_max_timestamp(tmp_path, replacement_timestamp):
    path = str(tmp_path / "replacement.db")
    reader = SQLiteVectorAdapter(path, _FixedEmbedding())
    writer = SQLiteVectorAdapter(path, _FixedEmbedding())
    target, fallback = _record("raw:target"), _record("raw:fallback", "diagonal")
    writer.index_records([target, fallback])
    assert list(reader.search("query", limit=1, namespace="selected", scope="thread")) == [target.id]
    writer.index_records([replace(target, attrs={"content": "negative"}, updated_at=replacement_timestamp)])
    assert list(reader.search("query", limit=1, namespace="selected", scope="thread")) == [fallback.id]


@pytest.mark.parametrize("boundary", ["ns", "scope"])
def test_public_vector_cache_refreshes_same_count_boundary_membership(tmp_path, boundary):
    path = str(tmp_path / "boundary.db")
    reader = SQLiteVectorAdapter(path, _FixedEmbedding())
    writer = SQLiteVectorAdapter(path, _FixedEmbedding())
    selected = _record("raw:selected")
    outside = replace(_record("raw:outside"), **{boundary: "other"})
    writer.index_records([selected, outside])
    assert list(reader.search("query", namespace="selected", scope="thread")) == [selected.id]
    writer.index_records([
        replace(selected, **{boundary: "other"}),
        replace(outside, **{boundary: getattr(selected, boundary)}),
    ])
    assert list(reader.search("query", namespace="selected", scope="thread")) == [outside.id]


def test_public_vector_cache_follows_old_and_new_bound_snapshots(tmp_path):
    model = _FixedEmbedding()
    runtime = SeamRuntime(tmp_path / "snapshots.db", embedding_model=model, allow_pgvector_env=False)
    try:
        reader = runtime.vector_adapter
        writer = SQLiteVectorAdapter(runtime.store.path, model)
        target, fallback = _record("raw:target"), _record("raw:fallback", "diagonal")
        runtime.store.persist_ir(IRBatch([target, fallback]))
        writer.index_records([target, fallback])
        def retrieve():
            return [candidate.record.id for candidate in runtime.retrieve(
                "query", mode="vector", ns="selected", scope="thread", budget=1,
                include_raw=True,
            ).candidates]
        with runtime.store.read_snapshot():
            assert retrieve() == [target.id]
            writer.index_records([replace(target, attrs={"content": "negative"})])
            assert retrieve() == [target.id]
        assert retrieve() == [fallback.id]
        assert list(reader.search("query", limit=1, namespace="selected", scope="thread")) == [fallback.id]
    finally:
        runtime.close()


def test_standalone_public_vector_search_pins_fingerprint_and_refill_to_one_snapshot(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    path = str(tmp_path / "standalone-snapshot.db")
    reader = SQLiteVectorAdapter(path, _FixedEmbedding())
    writer = SQLiteVectorAdapter(path, _FixedEmbedding())
    target, fallback = _record("raw:target"), _record("raw:fallback", "diagonal")
    writer.index_records([target, fallback])
    original = reader.index._fingerprint
    changed = False
    def mutate_after_fingerprint(*args):
        nonlocal changed
        fingerprint = original(*args)
        if not changed:
            changed = True
            writer.index_records([replace(target, attrs={"content": "negative"})])
        return fingerprint
    monkeypatch.setattr(reader.index, "_fingerprint", mutate_after_fingerprint)
    assert list(reader.search("query", limit=1, namespace="selected", scope="thread")) == [target.id]
    assert list(reader.search("query", limit=1, namespace="selected", scope="thread")) == [fallback.id]


def test_sqlite_vector_reports_exact_mode(tmp_path):
    adapter = SQLiteVectorAdapter(str(tmp_path / "mode.db"), _FixedEmbedding())
    assert adapter.index.search_mode == "exact"


def test_cached_scoped_growth_separates_retained_vectors_decoding_and_sql_work(tmp_path, monkeypatch):
    pytest.importorskip("numpy")
    runtime = SeamRuntime(tmp_path / "growth.db", embedding_model=_FixedEmbedding(), allow_pgvector_env=False)
    try:
        adapter = runtime.vector_adapter
        selected = [_record(f"raw:selected-{i}") for i in range(8)]
        adapter.index_records(selected)
        adapter.search("query", namespace="selected", scope="thread", limit=3)
        original_loads, original_connect = vectors.json.loads, adapter.index._connect
        work = {"decoded": 0, "steps": 0}
        def loads(*args, **kwargs):
            work["decoded"] += 1
            return original_loads(*args, **kwargs)
        def connect():
            connection = original_connect()
            connection.set_progress_handler(lambda: work.__setitem__("steps", work["steps"] + 1) or 0, 1)
            return connection
        monkeypatch.setattr(vectors.json, "loads", loads)
        monkeypatch.setattr(adapter.index, "_connect", connect)
        writer = SQLiteVectorAdapter(runtime.store.path, _FixedEmbedding())
        measurements = []
        for count in (0, 128, 1024):
            if count:
                writer.index_records([_record(f"raw:other-{i}", ns="other") for i in range(count)])
            work.update(decoded=0, steps=0)
            result = adapter.search("query", namespace="selected", scope="thread", limit=3)
            cache = adapter.index._cache[(adapter.model.name, adapter.model.dimension, "selected", "thread")]
            assert list(result) == ["raw:selected-0", "raw:selected-1", "raw:selected-2"]
            assert len(cache.ids) == len(selected)
            assert work["decoded"] == 0
            assert work["steps"] > 0
            measurements.append({"unrelated_rows": count, "retained_vectors": len(cache.ids), **work})
        print(f"sqlite_scoped_cache_measurements={measurements}")
        # Fixed selected rows must not require a scan of unrelated namespaces.
        assert max(row["steps"] for row in measurements) < 2 * min(row["steps"] for row in measurements)
    finally:
        runtime.close()
