"""Tests for pgvector boundary-only resync (namespace/scope metadata repair).

Covers:
- PgVectorAdapter.sync_boundaries() on real postgres (external marker).
- PgVectorAdapter.stale_records() reporting scope_changed (external marker).
- SeamRuntime.reindex_vectors(boundary_only=True) hermetic success and
  unsupported-adapter fail-closed behavior with zero embedding calls.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest

from seam_runtime.dsl import compile_dsl
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.reference_contracts import VIRTUAL_REFS_EXTENSION

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
            assert result["skipped_render_version"] == []
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
def test_sync_boundaries_repairs_after_storage_reload():
    """Realistic path: index a fresh in-memory record, then resync a copy
    reloaded through JSON (as the real ``seam reindex`` CLI does via
    ``store.load_ir``), not the same in-memory object used at index time.

    Vector text v2 canonicalizes the generic attrs traversal, so a JSON storage
    round trip no longer changes the source hash. Boundary-only repair can now
    update realistic plain CLM/ENT/EVT/REL records without embedding.
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
        assert result["updated"] == ["clm:boundary-reload-test"]
        assert result["skipped_render_version"] == []
        assert result["skipped_content_changed"] == []
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


# ── Hermetic tests (no pgvector needed) ─────────────────────────────────


class _NoEmbeddingModel:
    name = "no-embedding"
    dimension = 8

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, text: str) -> list[float]:
        self.calls += 1
        raise AssertionError(f"boundary-only reindex attempted to embed: {text}")


class _BoundarySyncAdapter:
    name = "boundary-sync-spy"

    def __init__(self) -> None:
        self.index_calls = 0
        self.synced_records: list[MIRLRecord] = []

    def index_records(self, records: list[MIRLRecord]) -> None:
        self.index_calls += 1
        raise AssertionError(f"boundary-only reindex attempted full indexing: {records}")

    def stale_records(self, records: list[MIRLRecord]) -> list[dict[str, object]]:
        return [{"record_id": record.id, "reason": "namespace_changed"} for record in records]

    def sync_boundaries(self, records: list[MIRLRecord]) -> dict[str, object]:
        self.synced_records = list(records)
        return {
            "mode": "untrusted-adapter-mode",
            "record_count": 999,
            "model": "untrusted-adapter-model",
            "adapter": "untrusted-adapter-name",
            "vector_text_version": "untrusted-vector-text-version",
            "stale_before": [],
            "updated": [record.id for record in records],
            "already_ok": 0,
            "skipped_missing": [],
            "skipped_content_changed": [],
        }

    def search(
        self,
        query: str,
        limit: int = 10,
        namespace: str | None = None,
        scope: str | None = None,
    ) -> dict[str, float]:
        return {}


def test_runtime_reindex_boundary_only_hermetic(tmp_path: Path):
    """Boundary-only sync preserves filters and never indexes or embeds."""
    from seam_runtime.runtime import SeamRuntime

    model = _NoEmbeddingModel()
    adapter = _BoundarySyncAdapter()
    rt = SeamRuntime(
        tmp_path / "boundary-resync.db",
        embedding_model=model,
        vector_adapter=adapter,
        allow_pgvector_env=False,
    )
    try:
        selected = MIRLRecord(
            id="clm:boundary-selected",
            kind=RecordKind.CLM,
            ns="beta",
            scope="project",
            ext={VIRTUAL_REFS_EXTENSION: ["test"]},
            attrs={"subject": "test", "predicate": "has", "object": "boundary"},
        )
        excluded = MIRLRecord(
            id="clm:boundary-excluded",
            kind=RecordKind.CLM,
            ns="alpha",
            scope="thread",
            ext={VIRTUAL_REFS_EXTENSION: ["other"]},
            attrs={"subject": "other", "predicate": "has", "object": "boundary"},
        )
        rt.store.persist_ir(IRBatch([selected, excluded]))

        result = rt.reindex_vectors(
            ns="beta",
            scope="project",
            boundary_only=True,
        )

        assert [record.id for record in adapter.synced_records] == [selected.id]
        assert adapter.index_calls == 0
        assert model.calls == 0
        assert result == {
            "mode": "boundary_only",
            "record_count": 1,
            "model": model.name,
            "adapter": adapter.name,
            "vector_text_version": "mirl-vector-text/2",
            "stale_before": [
                {"record_id": selected.id, "reason": "namespace_changed"}
            ],
            "updated": [selected.id],
            "already_ok": 0,
            "skipped_missing": [],
            "skipped_content_changed": [],
        }
    finally:
        rt.close()


def test_runtime_reindex_boundary_only_unsupported_adapter_fails_closed(
    tmp_path: Path,
):
    """An adapter without sync_boundaries never falls through to full indexing."""
    from seam_runtime.runtime import SeamRuntime
    from seam_runtime.vector_adapters import SQLiteVectorAdapter

    model = _NoEmbeddingModel()
    store_path = tmp_path / "unsupported-boundary-resync.db"
    adapter = SQLiteVectorAdapter(str(store_path), model)
    rt = SeamRuntime(
        store_path,
        embedding_model=model,
        vector_adapter=adapter,
        allow_pgvector_env=False,
    )
    try:
        record = MIRLRecord(
            id="clm:boundary-unsupported",
            kind=RecordKind.CLM,
            ns="beta",
            scope="project",
            ext={VIRTUAL_REFS_EXTENSION: ["test"]},
            attrs={"subject": "test", "predicate": "has", "object": "boundary"},
        )
        rt.store.persist_ir(IRBatch([record]))

        with pytest.raises(
            NotImplementedError,
            match=r"Unsupported boundary-only reindex.*sqlite-vector",
        ):
            rt.reindex_vectors(
                ns="beta",
                scope="project",
                boundary_only=True,
            )

        assert model.calls == 0
        assert adapter.index.stale_records([record]) == [
            {"record_id": record.id, "reason": "missing"}
        ]
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
            ext={VIRTUAL_REFS_EXTENSION: ["a"]},
            attrs={"subject": "a", "predicate": "is", "object": "x"},
        )
        r2 = MIRLRecord(
            id="clm:ns-beta",
            kind=RecordKind.CLM,
            ns="beta",
            scope="thread",
            ext={VIRTUAL_REFS_EXTENSION: ["b"]},
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
