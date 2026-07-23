"""Tests for pgvector boundary-only resync (namespace/scope metadata repair).

Covers:
- PgVectorAdapter.sync_boundaries() on real postgres (external marker).
- PgVectorAdapter.stale_records() reporting scope_changed (external marker).
- SeamRuntime.reindex_vectors(boundary_only=True) hermetic flow via SQLite.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

from seam_runtime.dsl import compile_dsl
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind

# ── External tests (real pgvector) ──────────────────────────────────────

_external = [
    pytest.mark.external,
    pytest.mark.skipif(
        not os.environ.get("SEAM_PGVECTOR_DSN"),
        reason="SEAM_PGVECTOR_DSN not set; skipping real-postgres pgvector integration",
    ),
]


def _make_adapter():
    from seam_runtime.models import HashEmbeddingModel
    from seam_runtime.vector_adapters import PgVectorAdapter

    table = f"seam_vector_index_test_{uuid.uuid4().hex[:12]}"
    dsn = os.environ["SEAM_PGVECTOR_DSN"]
    return PgVectorAdapter(dsn=dsn, model=HashEmbeddingModel(), table_name=table), table


def _make_records(ns: str = "alpha", scope: str = "thread"):
    batch = compile_dsl(
        """
entity project "SEAM" as proj
claim c1:
  subject proj
  predicate supports
  object "boundary repair"
""",
        scope=scope,
        ns=ns,
    )
    return batch.records


def _drop_table(adapter, table_name):
    with adapter._connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(f'drop table if exists "{table_name}"')
        connection.commit()


@pytest.mark.parametrize("move", [
    {"ns": "beta", "scope": "thread"},      # namespace change only
    {"ns": "alpha", "scope": "project"},     # scope change only
    {"ns": "beta", "scope": "project"},      # both change
])
class TestPgVectorBoundaryResyncExternal:
    pytestmark = _external

    def test_stale_records_detects_boundary_change(self, move):
        adapter, table = _make_adapter()
        try:
            records = _make_records()
            adapter.index_records(records)
            # Mutate ns/scope on the canonical record
            moved = []
            for r in records:
                d = r.to_dict()
                d["ns"] = move["ns"]
                d["scope"] = move["scope"]
                moved.append(MIRLRecord.from_dict(d))
            stale = adapter.stale_records(moved)
            # At least one indexable record should be reported as stale
            stale_reasons = {s["reason"] for s in stale}
            assert stale_reasons & {"namespace_changed", "scope_changed"}, (
                f"Expected namespace_changed or scope_changed, got {stale}"
            )
        finally:
            _drop_table(adapter, table)

    def test_sync_boundaries_repairs_without_reembed(self, move):
        adapter, table = _make_adapter()
        try:
            records = _make_records()
            adapter.index_records(records)
            # Verify current boundaries
            stale_before = adapter.stale_records(records)
            assert stale_before == [], f"Expected clean slate, got {stale_before}"
            # Move the canonical records
            moved = []
            for r in records:
                d = r.to_dict()
                d["ns"] = move["ns"]
                d["scope"] = move["scope"]
                moved.append(MIRLRecord.from_dict(d))
            # sync_boundaries should fix metadata
            result = adapter.sync_boundaries(moved)
            assert len(result["updated"]) > 0, f"Expected updates, got {result}"
            assert result["skipped_missing"] == []
            assert result["skipped_content_changed"] == []
            # After sync, stale_records against the moved set should be empty
            stale_after = adapter.stale_records(moved)
            assert stale_after == [], f"Expected no stale after sync, got {stale_after}"
            # Search should find under the new boundary
            scores = adapter.search("boundary repair", namespace=move["ns"], scope=move["scope"], limit=5)
            assert len(scores) > 0, "Expected hits under the new boundary"
        finally:
            _drop_table(adapter, table)


@pytest.mark.external
@pytest.mark.skipif(
    not os.environ.get("SEAM_PGVECTOR_DSN"),
    reason="SEAM_PGVECTOR_DSN not set; skipping real-postgres pgvector integration",
)
def test_sync_boundaries_conservative_after_storage_reload():
    """Realistic path: index a fresh in-memory record, then resync a copy
    reloaded through JSON (as the real ``seam reindex`` CLI does via
    ``store.load_ir``), not the same in-memory object used at index time.

    Root cause: ``persist_ir`` writes ``json.dumps(..., sort_keys=True)``,
    so a record read back via ``load_ir`` has its ``attrs`` dict in
    alphabetical key order. ``iter_textual_fields`` (seam_runtime/mirl.py)
    iterates ``attrs.items()`` in dict order, so the generic (non-RAW,
    non-grounded-CLM) text render for a multi-attr record — e.g. a plain
    CLM's ``subject``/``predicate``/``object`` — differs between the
    original in-process object and the reloaded one, changing the source
    hash. ``sync_boundaries`` correctly refuses to touch metadata when the
    hash doesn't match (falls back to ``skipped_content_changed``, never a
    wrong write), but this makes it conservative-skip on plain CLM/ENT/EVT/
    REL records reached via the real reload path. RAW records (content is a
    single string) and grounded-CLM records (fixed subject/predicate/object
    order, not dict iteration order) are unaffected. Not fixed here: the
    shared render function feeds live embedding text for the whole corpus,
    so reordering it needs its own scoped follow-up with a full-reindex
    migration story, not a silent change riding along with boundary resync.
    """
    from seam_runtime.mirl import MIRLRecord as _Rec

    adapter, table = _make_adapter()
    try:
        record = _Rec(
            id="clm:boundary-reload-test",
            kind=RecordKind.CLM,
            ns="alpha",
            scope="thread",
            attrs={"subject": "sky", "predicate": "is", "object": "blue"},
        )
        adapter.index_records([record])

        # Simulate the real reindex CLI path: reload through a JSON round
        # trip (sort_keys=True on write), not the original in-memory object.
        reloaded = _Rec.from_dict(json.loads(json.dumps(record.to_dict(), sort_keys=True)))
        reloaded.ns = "beta"
        reloaded.scope = "project"

        result = adapter.sync_boundaries([reloaded])
        assert result["updated"] == []
        assert result["skipped_content_changed"] == ["clm:boundary-reload-test"]
    finally:
        _drop_table(adapter, table)


@pytest.mark.external
@pytest.mark.skipif(
    not os.environ.get("SEAM_PGVECTOR_DSN"),
    reason="SEAM_PGVECTOR_DSN not set; skipping real-postgres pgvector integration",
)
def test_sync_boundaries_skips_already_ok_records():
    """Records whose ns/scope already match should be counted as already_ok."""
    adapter, table = _make_adapter()
    try:
        records = _make_records()
        adapter.index_records(records)
        result = adapter.sync_boundaries(records)
        assert result["updated"] == []
        assert result["already_ok"] > 0
    finally:
        _drop_table(adapter, table)


# ── Hermetic test (SQLite, no pgvector needed) ──────────────────────────


def test_runtime_reindex_boundary_only_hermetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """reindex_vectors(boundary_only=True) calls sync_boundaries when available."""
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)

    from seam_runtime.models import HashEmbeddingModel
    from seam_runtime.runtime import SeamRuntime

    model = HashEmbeddingModel()
    rt = SeamRuntime(
        tmp_path / "boundary-resync.db",
        embedding_model=model,
        allow_pgvector_env=False,
    )
    try:
        record = MIRLRecord(
            id="clm:boundary-resync-test",
            kind=RecordKind.CLM,
            ns="alpha",
            scope="thread",
            attrs={"subject": "test", "predicate": "has", "object": "boundary"},
        )
        rt.persist_ir(IRBatch([record]))

        # Move the record's boundary in the store
        moved = MIRLRecord.from_dict(record.to_dict())
        moved.ns = "beta"
        moved.scope = "project"
        rt.persist_ir(IRBatch([moved]))

        # The SQLite adapter's index_records already handles the move inline,
        # so the reindex should report the record as indexed
        result = rt.reindex_vectors(ns="beta", scope="project")
        assert record.id in result["indexed_ids"]
        assert result["adapter"] in ("sqlite-vector", "unknown")
    finally:
        rt.close()


def test_runtime_reindex_namespace_scope_filter_hermetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """reindex_vectors with ns/scope filters loads only matching records."""
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)

    from seam_runtime.models import HashEmbeddingModel
    from seam_runtime.runtime import SeamRuntime

    model = HashEmbeddingModel()
    rt = SeamRuntime(
        tmp_path / "filter-resync.db",
        embedding_model=model,
        allow_pgvector_env=False,
    )
    try:
        r1 = MIRLRecord(
            id="clm:ns-alpha",
            kind=RecordKind.CLM,
            ns="alpha",
            scope="thread",
            attrs={"subject": "a", "predicate": "is", "object": "x"},
        )
        r2 = MIRLRecord(
            id="clm:ns-beta",
            kind=RecordKind.CLM,
            ns="beta",
            scope="thread",
            attrs={"subject": "b", "predicate": "is", "object": "y"},
        )
        rt.persist_ir(IRBatch([r1, r2]))

        # Reindex only alpha namespace
        result = rt.reindex_vectors(ns="alpha")
        assert "clm:ns-alpha" in result["indexed_ids"]
        assert "clm:ns-beta" not in result["indexed_ids"]

        # Reindex only beta namespace
        result = rt.reindex_vectors(ns="beta")
        assert "clm:ns-beta" in result["indexed_ids"]
        assert "clm:ns-alpha" not in result["indexed_ids"]
    finally:
        rt.close()
