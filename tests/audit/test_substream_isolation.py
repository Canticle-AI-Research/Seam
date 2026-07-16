"""Regression tests for substream (namespace) isolation in retrieval.

The leak: ``runtime.search_ir`` historically filtered the candidate load by
``scope`` only, and the vector search was global, so a single store holding
multiple namespaces under the same scope could return another namespace's
records. These tests DEMONSTRATE the leak (ns=None still mixes namespaces, the
prior default) and prove the SEAL (passing ``ns`` confines retrieval to that
namespace) at both the vector-adapter and the runtime layers.

All hermetic: HashEmbeddingModel (no model download), SQLite backend (no
Docker). The pgvector equivalent is gated on PGVECTOR_TEST_DSN below.
"""

import os

import pytest

from seam_runtime.mirl import MIRLRecord, RecordKind
from seam_runtime.models import HashEmbeddingModel
from seam_runtime.runtime import SeamRuntime
from seam_runtime.vector_adapters import PgVectorAdapter, SQLiteVectorAdapter


def _rec(rid: str, ns: str, text: str) -> MIRLRecord:
    return MIRLRecord(
        id=rid, kind=RecordKind.CLM, ns=ns, scope="thread", t0="2024-01-01",
        attrs={"subject": "ent:1", "predicate": "says", "object": text},
    )


# --- vector-adapter layer: namespace filter -------------------------------

def test_sqlite_vector_adapter_namespace_filter(tmp_path):
    adapter = SQLiteVectorAdapter(str(tmp_path / "vec.db"), HashEmbeddingModel())
    adapter.index_records([
        _rec("clm:a", "tenant:a", "alpha apples orchard"),
        _rec("clm:b", "tenant:b", "beta bananas grove"),
    ])
    # Leak by default: ns=None searches the whole pool.
    both = adapter.search("apples bananas", limit=10, namespace=None)
    assert {"clm:a", "clm:b"} <= set(both)
    # Sealed: namespace confines results to that substream only.
    only_a = adapter.search("apples bananas", limit=10, namespace="tenant:a")
    assert set(only_a) == {"clm:a"}
    only_b = adapter.search("apples bananas", limit=10, namespace="tenant:b")
    assert set(only_b) == {"clm:b"}


# --- runtime layer: the actual leak-seal ----------------------------------

def _sqlite_runtime(path) -> SeamRuntime:
    """Runtime forced onto the SQLite vector backend (hermetic; ignores any
    SEAM_PGVECTOR_DSN in the ambient environment)."""
    model = HashEmbeddingModel()
    return SeamRuntime(str(path), embedding_model=model, vector_adapter=SQLiteVectorAdapter(str(path), model))


def _ingest_two_namespaces(rt: SeamRuntime) -> None:
    rt.ingest_text("Alpha team shipped the apples orchard project.", ns="tenant:a", scope="thread")
    rt.ingest_text("Beta team shipped the bananas grove project.", ns="tenant:b", scope="thread")


def _result_namespaces(result) -> set[str]:
    return {c.record.ns for c in result.candidates}


def test_search_ir_leaks_across_namespaces_without_ns(tmp_path):
    """DEMONSTRATE the leak: with ns=None (the prior default) a single store
    holding two namespaces returns records from both."""
    rt = _sqlite_runtime(tmp_path / "store.db")
    _ingest_two_namespaces(rt)
    result = rt.search_ir("project shipped", scope="thread", budget=10, include_raw=True)
    seen = _result_namespaces(result)
    assert "tenant:a" in seen and "tenant:b" in seen, (
        f"expected both namespaces to leak with ns=None, saw {seen}"
    )


def test_search_ir_seals_to_requested_namespace(tmp_path):
    """SEAL: passing ns confines retrieval to that substream; no other
    namespace's records appear."""
    rt = _sqlite_runtime(tmp_path / "store.db")
    _ingest_two_namespaces(rt)
    result = rt.search_ir("project shipped", scope="thread", budget=10, include_raw=True, ns="tenant:a")
    seen = _result_namespaces(result)
    assert seen, "expected at least one candidate from tenant:a"
    assert seen == {"tenant:a"}, f"leak: ns=tenant:a returned foreign namespaces {seen - {'tenant:a'}}"


def test_search_ir_ns_none_is_backward_compatible(tmp_path):
    """A single-namespace store behaves identically with ns omitted vs ns set
    -- the seal is a no-op when there is nothing to isolate."""
    rt = _sqlite_runtime(tmp_path / "store.db")
    rt.ingest_text("Solo team shipped the apples orchard project.", ns="tenant:a", scope="thread")
    a = rt.search_ir("project shipped", scope="thread", budget=10, include_raw=True)
    b = rt.search_ir("project shipped", scope="thread", budget=10, include_raw=True, ns="tenant:a")
    assert [c.record.id for c in a.candidates] == [c.record.id for c in b.candidates]


# --- pgvector parity (the shared-pool backend that motivated the seal) -----

@pytest.mark.external  # real pgvector service; deselect with -m "not external" without it
@pytest.mark.skipif(not os.environ.get("PGVECTOR_TEST_DSN"), reason="PGVECTOR_TEST_DSN not set")
def test_pgvector_adapter_namespace_filter():
    dsn = os.environ["PGVECTOR_TEST_DSN"]
    table = "seam_vector_index_nstest"
    adapter = PgVectorAdapter(dsn=dsn, model=HashEmbeddingModel(name="model-x", dimension=64), table_name=table)
    try:
        adapter.index_records([
            _rec("clm:a", "tenant:a", "alpha apples orchard"),
            _rec("clm:b", "tenant:b", "beta bananas grove"),
        ])
        both = adapter.search("apples bananas", limit=10, namespace=None)
        assert {"clm:a", "clm:b"} <= set(both)
        only_a = adapter.search("apples bananas", limit=10, namespace="tenant:a")
        assert set(only_a) == {"clm:a"}
    finally:
        with adapter._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"drop table if exists {table}")
            conn.commit()
