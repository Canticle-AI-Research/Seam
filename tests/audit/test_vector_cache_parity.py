"""SQLiteVectorIndex numpy-cache fast path must be a byte-identical no-op.

HISTORY#364: SQLiteVectorIndex.search gained a numpy matrix cache keyed by
(model, dimension, namespace) with a (count, max updated_at) fingerprint, to
kill the per-query json.loads that profiling showed was ~88% of the default
local vector scan (HISTORY#363). numpy is optional, so both paths stay live:
the cached path when numpy is importable, the pure-Python per-row scan
otherwise. This pins the cached path to return byte-identical results (same
record ids, same order, same scores) to the scan, and pins cache invalidation
on writes -- a perf change must never reorder retrieval.
"""
from __future__ import annotations

import json
import random
from contextlib import closing

import pytest

import seam_runtime.vector as vmod
from seam_runtime.models import HashEmbeddingModel
from seam_runtime.vector import SQLiteVectorIndex

numpy = pytest.importorskip("numpy")


def _seed_corpus(idx: SQLiteVectorIndex, model: HashEmbeddingModel, n: int = 400) -> None:
    rng = random.Random(11)
    words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
    with closing(idx._connect()) as connection:
        for i in range(n):
            text = f"record {i} " + " ".join(rng.choice(words) for _ in range(8))
            vector = model.embed(text)
            namespace = "nsA" if i % 2 == 0 else "nsB"
            connection.execute(
                "insert or replace into vector_index "
                "(record_id, model_name, dimension, source_text, source_hash, namespace, vector_json, updated_at) "
                "values (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"r{i}", model.name, len(vector), text, f"h{i}", namespace,
                 json.dumps(vector), f"2026-01-01T00:00:{i % 60:02d}"),
            )
        connection.commit()
    idx._cache.clear()


def _search_all(idx: SQLiteVectorIndex, queries: list[str]) -> list[dict]:
    out = []
    for q in queries:
        for namespace in (None, "nsA", "nsB"):
            out.append(idx.search(q, limit=10, namespace=namespace))
    return out


def test_numpy_branch_is_active() -> None:
    assert vmod._numpy is not None


def test_cached_path_is_byte_identical_to_scan(tmp_path, monkeypatch) -> None:
    model = HashEmbeddingModel()
    idx = SQLiteVectorIndex(str(tmp_path / "v.db"), model)
    idx.ensure_schema()
    _seed_corpus(idx, model)
    queries = [f"query about {w} number {i}" for i, w in enumerate(["alpha", "beta", "gamma", "delta"] * 6)]

    # Reference: force the pure-Python scan by hiding numpy.
    monkeypatch.setattr(vmod, "_numpy", None)
    idx._cache.clear()
    reference = _search_all(idx, queries)

    # Candidate: the numpy cached path.
    monkeypatch.setattr(vmod, "_numpy", numpy)
    idx._cache.clear()
    candidate = _search_all(idx, queries)

    assert len(reference) == len(candidate)
    for ref, cand in zip(reference, candidate):
        # Same ids in the same order (rankings) AND identical float scores.
        assert list(ref.keys()) == list(cand.keys())
        assert ref == cand


def test_cache_invalidates_on_external_write(tmp_path) -> None:
    model = HashEmbeddingModel()
    idx = SQLiteVectorIndex(str(tmp_path / "v.db"), model)
    idx.ensure_schema()
    _seed_corpus(idx, model, n=50)
    # Warm the cache.
    idx.search("alpha beta gamma", limit=10, namespace="nsA")
    # Write a new row on a separate connection WITHOUT clearing the cache; the
    # per-search fingerprint must notice and rebuild.
    vector = model.embed("alpha alpha alpha alpha alpha alpha alpha alpha")
    with closing(idx._connect()) as connection:
        connection.execute(
            "insert or replace into vector_index "
            "(record_id, model_name, dimension, source_text, source_hash, namespace, vector_json, updated_at) "
            "values (?, ?, ?, ?, ?, ?, ?, ?)",
            ("rNEW", model.name, len(vector), "alpha " * 8, "hNEW", "nsA",
             json.dumps(vector), "2026-09-09T00:00:00"),
        )
        connection.commit()
    result = idx.search("alpha alpha alpha", limit=30, namespace="nsA")
    assert "rNEW" in result


def test_index_records_clears_cache(tmp_path) -> None:
    from seam_runtime.mirl import MIRLRecord, RecordKind

    model = HashEmbeddingModel()
    idx = SQLiteVectorIndex(str(tmp_path / "v.db"), model)
    idx.ensure_schema()
    _seed_corpus(idx, model, n=20)
    idx.search("alpha", limit=5, namespace="nsA")
    assert idx._cache  # warmed
    idx.index_records([
        MIRLRecord(id="raw:new", kind=RecordKind.RAW,
                   attrs={"content": "gamma gamma gamma delta"}, ns="nsA"),
    ])
    assert idx._cache == {}  # cleared by the write


def test_empty_namespace_returns_empty(tmp_path) -> None:
    model = HashEmbeddingModel()
    idx = SQLiteVectorIndex(str(tmp_path / "v.db"), model)
    idx.ensure_schema()
    _seed_corpus(idx, model, n=20)
    assert idx.search("alpha", limit=5, namespace="does-not-exist") == {}
    assert idx.search("alpha", limit=0, namespace="nsA") == {}
