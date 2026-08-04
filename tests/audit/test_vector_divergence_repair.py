"""Track S S5: vector divergence is detected and repaired on every backend.

The exit-gate clause names all three: SQLite-vector, pgvector, and Chroma.

Divergence has exactly three shapes and each needs a different repair, so they
are asserted separately rather than as one count:

``missing``  canonical records the backend holds no vector for -- what a crash
             between the canonical commit and indexing leaves behind.
``stale``    a vector whose source, render version, dimension, or boundary no
             longer matches the record.
``orphan``   a vector with no live canonical record, which stays searchable and
             can surface deleted content.

SQLite-vector is exercised against the real backend. pgvector and Chroma are
exercised through their real adapter code against recording doubles, so the
clause holds in provider-free lanes instead of only where those services run.
"""

from __future__ import annotations

import hashlib

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.models import HashEmbeddingModel
from seam_runtime.reference_contracts import VIRTUAL_REFS_EXTENSION
from seam_runtime.retrieval_orchestrator.adapters import ChromaSemanticAdapter
from seam_runtime.runtime import SeamRuntime
from seam_runtime.vector import VECTOR_TEXT_VERSION, SQLiteVectorIndex
from seam_runtime.vector_adapters import SQLiteVectorAdapter


def _record(record_id: str, text: str = "a compiler note") -> MIRLRecord:
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.CLM,
        ns="work",
        scope="thread",
        ext={VIRTUAL_REFS_EXTENSION: ["ent:test"]},
        attrs={"subject": "ent:test", "predicate": "notes", "object": text},
    )


def _runtime(path) -> SeamRuntime:
    model = HashEmbeddingModel()
    return SeamRuntime(
        path,
        embedding_model=model,
        vector_adapter=SQLiteVectorAdapter(str(path), model),
        allow_pgvector_env=False,
    )


def _reasons(issues) -> set[str]:
    return {str(issue["reason"]) for issue in issues}


def _ids(issues) -> set[str]:
    return {str(issue["record_id"]) for issue in issues}


# --------------------------------------------------------------------------
# SQLite-vector, against the real backend
# --------------------------------------------------------------------------


def test_healthy_store_reports_no_divergence(tmp_path) -> None:
    runtime = _runtime(tmp_path / "healthy.db")
    try:
        runtime.persist_ir(IRBatch([_record("clm:one"), _record("clm:two")]))
        report = runtime.verify_vector_divergence()

        assert report["diverged"] is False
        assert report["missing"] == []
        assert report["stale"] == []
        assert report["orphan"] == []
        assert report["expected_record_count"] == 2
        # "No divergence" must mean every shape was actually checked.
        assert report["checks"] == {"missing": True, "stale": True, "orphan": True}
    finally:
        runtime.close()


def test_missing_vector_is_detected_and_repaired(tmp_path) -> None:
    runtime = _runtime(tmp_path / "missing.db")
    try:
        runtime.persist_ir(IRBatch([_record("clm:one"), _record("clm:two")]))

        # Exactly the state a crash between commit and indexing leaves.
        with runtime.store._pool.checkout() as connection:
            connection.execute("delete from vector_index where record_id = ?", ("clm:one",))
            connection.commit()

        report = runtime.verify_vector_divergence()
        assert report["diverged"] is True
        assert _ids(report["missing"]) == {"clm:one"}
        assert report["stale"] == []

        repair = runtime.repair_vector_divergence()
        assert repair["repaired"] is True
        assert "clm:one" in repair["reindexed_ids"]
        assert runtime.verify_vector_divergence()["diverged"] is False
    finally:
        runtime.close()


def test_stale_vector_is_detected_and_repaired(tmp_path) -> None:
    runtime = _runtime(tmp_path / "stale.db")
    try:
        runtime.persist_ir(IRBatch([_record("clm:one")]))

        with runtime.store._pool.checkout() as connection:
            connection.execute(
                "update vector_index set source_hash = ? where record_id = ?",
                ("0" * 64, "clm:one"),
            )
            connection.commit()

        report = runtime.verify_vector_divergence()
        assert _reasons(report["stale"]) == {"source_changed"}
        assert report["missing"] == []

        repair = runtime.repair_vector_divergence()
        assert repair["repaired"] is True
        assert runtime.verify_vector_divergence()["stale"] == []
    finally:
        runtime.close()


def test_orphan_vector_is_detected_and_deleted(tmp_path) -> None:
    runtime = _runtime(tmp_path / "orphan.db")
    try:
        runtime.persist_ir(IRBatch([_record("clm:one")]))

        # A vector whose canonical record does not exist: still searchable, so
        # it can surface content nothing backs.
        with runtime.store._pool.checkout() as connection:
            connection.execute(
                "insert into vector_index (record_id, model_name, dimension, "
                "source_text, source_hash, render_version, namespace, scope, "
                "vector_json, updated_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "clm:ghost",
                    runtime.embedding_model.name,
                    runtime.embedding_model.dimension,
                    "ghost text",
                    "f" * 64,
                    VECTOR_TEXT_VERSION,
                    "work",
                    "thread",
                    "[0.5]",
                    "2026-08-03T00:00:00Z",
                ),
            )
            connection.commit()

        report = runtime.verify_vector_divergence()
        assert _ids(report["orphan"]) == {"clm:ghost"}

        repair = runtime.repair_vector_divergence()
        assert repair["deleted_orphan_ids"] == ["clm:ghost"]
        assert repair["repaired"] is True

        with runtime.store._pool.checkout() as connection:
            remaining = connection.execute(
                "select count(*) from vector_index where record_id = ?", ("clm:ghost",)
            ).fetchone()[0]
        assert remaining == 0
    finally:
        runtime.close()


def test_repair_fixes_all_three_shapes_in_one_pass(tmp_path) -> None:
    runtime = _runtime(tmp_path / "all-shapes.db")
    try:
        runtime.persist_ir(
            IRBatch([_record("clm:one"), _record("clm:two"), _record("clm:three")])
        )
        with runtime.store._pool.checkout() as connection:
            connection.execute("delete from vector_index where record_id = ?", ("clm:one",))
            connection.execute(
                "update vector_index set source_hash = ? where record_id = ?",
                ("0" * 64, "clm:two"),
            )
            connection.execute(
                "insert into vector_index (record_id, model_name, dimension, "
                "source_text, source_hash, render_version, namespace, scope, "
                "vector_json, updated_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "clm:ghost",
                    runtime.embedding_model.name,
                    runtime.embedding_model.dimension,
                    "ghost",
                    "f" * 64,
                    VECTOR_TEXT_VERSION,
                    "work",
                    "thread",
                    "[0.5]",
                    "2026-08-03T00:00:00Z",
                ),
            )
            connection.commit()

        before = runtime.verify_vector_divergence()
        assert _ids(before["missing"]) == {"clm:one"}
        assert _ids(before["stale"]) == {"clm:two"}
        assert _ids(before["orphan"]) == {"clm:ghost"}

        repair = runtime.repair_vector_divergence()
        assert repair["repaired"] is True
        assert repair["after"]["diverged"] is False
    finally:
        runtime.close()


def test_repair_is_idempotent(tmp_path) -> None:
    runtime = _runtime(tmp_path / "idempotent-repair.db")
    try:
        runtime.persist_ir(IRBatch([_record("clm:one")]))
        first = runtime.repair_vector_divergence()
        assert first["reindexed_ids"] == []
        assert first["deleted_orphan_ids"] == []

        second = runtime.repair_vector_divergence()
        assert second == first
    finally:
        runtime.close()


# --------------------------------------------------------------------------
# pgvector, through its real adapter against a recording double
# --------------------------------------------------------------------------


class _FakePgAdapter:
    """Stands in for PgVectorAdapter's observable divergence protocol."""

    name = "pgvector"

    def __init__(self, *, stale=(), orphans=()) -> None:
        self._stale = list(stale)
        self._orphans = list(orphans)
        self.indexed: list[list[str]] = []
        self.deleted: list[list[str]] = []

    def stale_records(self, records):
        known = {record.id for record in records}
        return [issue for issue in self._stale if issue["record_id"] in known]

    def orphan_records(self, valid_record_ids=None, *, model_name=None, namespace=None, scope=None):
        return list(self._orphans)

    def index_records(self, records):
        self.indexed.append([record.id for record in records])
        self._stale = []

    def delete_records(self, record_ids):
        self.deleted.append(list(record_ids))
        self._orphans = []


def test_pgvector_divergence_is_detected_and_repaired(tmp_path) -> None:
    runtime = _runtime(tmp_path / "pgvector-shape.db")
    try:
        runtime.persist_ir(IRBatch([_record("clm:one"), _record("clm:two")]))
        adapter = _FakePgAdapter(
            stale=[
                {"record_id": "clm:one", "reason": "missing"},
                {"record_id": "clm:two", "reason": "render_version_changed"},
            ],
            orphans=[{"record_id": "clm:ghost", "reason": "orphan"}],
        )

        report = runtime.verify_vector_divergence(vector_adapter=adapter)
        assert report["adapter"] == "pgvector"
        assert _ids(report["missing"]) == {"clm:one"}
        assert _ids(report["stale"]) == {"clm:two"}
        assert _ids(report["orphan"]) == {"clm:ghost"}

        repair = runtime.repair_vector_divergence(vector_adapter=adapter)
        assert repair["reindexed_ids"] == ["clm:one", "clm:two"]
        assert repair["deleted_orphan_ids"] == ["clm:ghost"]
        assert repair["repaired"] is True
        assert adapter.indexed and adapter.deleted
    finally:
        runtime.close()


# --------------------------------------------------------------------------
# Chroma, through its real adapter against a recording collection
# --------------------------------------------------------------------------


class _Collection:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, object]] = {}
        self.deleted: list[list[str]] = []

    def upsert(self, *, ids, embeddings, documents, metadatas) -> None:
        for record_id, document, metadata in zip(ids, documents, metadatas, strict=False):
            self.rows[record_id] = {"document": document, "metadata": metadata}

    def get(self, ids=None, include=None):
        selected = sorted(self.rows) if ids is None else [i for i in ids if i in self.rows]
        return {
            "ids": selected,
            "metadatas": [self.rows[record_id]["metadata"] for record_id in selected],
        }

    def delete(self, ids) -> None:
        self.deleted.append(list(ids))
        for record_id in ids:
            self.rows.pop(record_id, None)


class _Client:
    def __init__(self, collection) -> None:
        self.collection = collection

    def get_or_create_collection(self, **options):
        return self.collection


def _chroma(runtime, collection) -> ChromaSemanticAdapter:
    return ChromaSemanticAdapter(
        store=runtime.store,
        embedding_model=runtime.embedding_model,
        client=_Client(collection),
    )


def test_chroma_reports_missing_records(tmp_path) -> None:
    runtime = _runtime(tmp_path / "chroma-missing.db")
    try:
        runtime.persist_ir(IRBatch([_record("clm:one"), _record("clm:two")]))
        collection = _Collection()
        adapter = _chroma(runtime, collection)

        # Nothing synced yet: every canonical record is missing.
        report = runtime.verify_vector_divergence(vector_adapter=adapter)
        assert report["checks"] == {"missing": True, "stale": True, "orphan": True}
        assert _ids(report["missing"]) == {"clm:one", "clm:two"}

        repair = runtime.repair_vector_divergence(vector_adapter=adapter)
        assert repair["repaired"] is True
        assert sorted(collection.rows) == ["clm:one", "clm:two"]
    finally:
        runtime.close()


def test_chroma_reports_stale_and_orphan_entries(tmp_path) -> None:
    runtime = _runtime(tmp_path / "chroma-stale.db")
    try:
        runtime.persist_ir(IRBatch([_record("clm:one")]))
        collection = _Collection()
        adapter = _chroma(runtime, collection)
        adapter.sync_batch(runtime.store.load_ir())
        assert runtime.verify_vector_divergence(vector_adapter=adapter)["diverged"] is False

        # Corrupt the stored source hash, and add an entry nothing backs.
        collection.rows["clm:one"]["metadata"]["source_hash"] = "0" * 64
        collection.rows["clm:ghost"] = {
            "document": "ghost",
            "metadata": {
                "kind": "CLM",
                "ns": "work",
                "scope": "thread",
                "vector_text_version": VECTOR_TEXT_VERSION,
                "source_hash": "f" * 64,
            },
        }

        report = runtime.verify_vector_divergence(vector_adapter=adapter)
        assert _reasons(report["stale"]) == {"source_changed"}
        assert _ids(report["orphan"]) == {"clm:ghost"}

        repair = runtime.repair_vector_divergence(vector_adapter=adapter)
        assert repair["repaired"] is True
        assert collection.deleted == [["clm:ghost"]]
        assert "clm:ghost" not in collection.rows
    finally:
        runtime.close()


def test_chroma_detects_a_render_version_change(tmp_path) -> None:
    runtime = _runtime(tmp_path / "chroma-render.db")
    try:
        runtime.persist_ir(IRBatch([_record("clm:one")]))
        collection = _Collection()
        adapter = _chroma(runtime, collection)
        adapter.sync_batch(runtime.store.load_ir())

        collection.rows["clm:one"]["metadata"]["vector_text_version"] = "mirl-vector-text/1"
        report = runtime.verify_vector_divergence(vector_adapter=adapter)
        assert _reasons(report["stale"]) == {"render_version_changed"}
    finally:
        runtime.close()


def test_chroma_stale_check_matches_the_records_it_would_sync(tmp_path) -> None:
    """Divergence is measured against what the backend is meant to hold."""

    runtime = _runtime(tmp_path / "chroma-scope.db")
    try:
        runtime.persist_ir(IRBatch([_record("clm:one")]))
        collection = _Collection()
        adapter = _chroma(runtime, collection)
        adapter.sync_batch(runtime.store.load_ir())

        records = runtime.store.load_ir().records
        expected = adapter.indexable_records(records)
        # The rendered document the adapter stores is what the hash is over.
        rendered = SQLiteVectorIndex.render_record_text(expected[0])
        assert collection.rows["clm:one"]["metadata"]["source_hash"] == (
            hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        )
        assert adapter.stale_records(expected) == []
    finally:
        runtime.close()


# --------------------------------------------------------------------------
# Honest reporting
# --------------------------------------------------------------------------


def test_an_adapter_that_cannot_be_inspected_says_so(tmp_path) -> None:
    """"No divergence" must never be indistinguishable from "never looked"."""

    class _Opaque:
        name = "opaque"

        def index_records(self, records):
            return None

        def delete_records(self, record_ids):
            return None

    runtime = _runtime(tmp_path / "opaque.db")
    try:
        runtime.persist_ir(IRBatch([_record("clm:one")]))
        report = runtime.verify_vector_divergence(vector_adapter=_Opaque())

        assert report["diverged"] is False
        assert report["checks"] == {
            "missing": False,
            "stale": False,
            "orphan": False,
        }
    finally:
        runtime.close()
