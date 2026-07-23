from __future__ import annotations

import hashlib

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.retrieval_orchestrator.adapters import ChromaSemanticAdapter
from seam_runtime.retrieval_orchestrator.planner import build_plan
from seam_runtime.vector import VECTOR_TEXT_VERSION, SQLiteVectorIndex


class _Embedding:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.texts.append(text)
        return [1.0]


class _Store:
    def __init__(self, records: list[MIRLRecord]) -> None:
        self.records = {record.id: record for record in records}

    def load_ir(self, ids=None, ns=None, scope=None) -> IRBatch:
        records = list(self.records.values())
        if ids is not None:
            records = [record for record in records if record.id in ids]
        if ns is not None:
            records = [record for record in records if record.ns == ns]
        if scope is not None:
            records = [record for record in records if record.scope == scope]
        return IRBatch(records)


class _Collection:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, object]] = {}
        self.query_options: dict[str, object] | None = None

    def upsert(self, *, ids, embeddings, documents, metadatas) -> None:
        for record_id, embedding, document, metadata in zip(
            ids, embeddings, documents, metadatas, strict=True
        ):
            self.rows[record_id] = {
                "embedding": embedding,
                "document": document,
                "metadata": metadata,
                "distance": 0.0,
            }

    def query(self, **options):
        self.query_options = options
        where = options.get("where")
        matching = [
            (record_id, row)
            for record_id, row in self.rows.items()
            if _matches_where(row["metadata"], where)
        ]
        matching.sort(key=lambda item: (item[1]["distance"], item[0]))
        matching = matching[: options["n_results"]]
        return {
            "ids": [[record_id for record_id, _ in matching]],
            "distances": [[row["distance"] for _, row in matching]],
            "documents": [[row["document"] for _, row in matching]],
            "metadatas": [[row["metadata"] for _, row in matching]],
        }


class _Client:
    def __init__(self, collection: _Collection) -> None:
        self.collection = collection
        self.options: dict[str, object] | None = None

    def get_or_create_collection(self, **options):
        self.options = options
        return self.collection


def _matches_where(metadata: object, where: object) -> bool:
    if not isinstance(metadata, dict) or not isinstance(where, dict):
        return False
    conjunction = where.get("$and")
    if isinstance(conjunction, list):
        return all(_matches_where(metadata, clause) for clause in conjunction)
    if len(where) != 1:
        return False
    key, condition = next(iter(where.items()))
    return isinstance(condition, dict) and metadata.get(key) == condition.get("$eq")


def _record(record_id: str, attrs: dict[str, str]) -> MIRLRecord:
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.CLM,
        ns="alpha",
        scope="thread",
        attrs=attrs,
    )


def test_chroma_sync_stamps_v2_source_contract_and_stable_document() -> None:
    first = _record("clm:first", {"zeta": "last", "alpha": "first"})
    second = _record("clm:second", {"alpha": "first", "zeta": "last"})
    collection = _Collection()
    client = _Client(collection)
    embedding = _Embedding()
    adapter = ChromaSemanticAdapter(_Store([first, second]), embedding, client=client)

    assert adapter.sync_batch(IRBatch([first, second])) == 2

    assert client.options == {
        "name": "seam_hybrid",
        "metadata": {"hnsw:space": "cosine"},
    }
    first_row = collection.rows[first.id]
    second_row = collection.rows[second.id]
    assert first_row["document"] == SQLiteVectorIndex.render_record_text(first)
    assert first_row["document"] == second_row["document"]
    assert embedding.texts == [first_row["document"], second_row["document"]]
    for row in (first_row, second_row):
        metadata = row["metadata"]
        assert metadata["vector_text_version"] == VECTOR_TEXT_VERSION
        assert metadata["source_hash"] == hashlib.sha256(
            row["document"].encode("utf-8")
        ).hexdigest()
        assert metadata["ns"] == "alpha"
        assert metadata["scope"] == "thread"


def test_chroma_search_composes_v2_filter_with_namespace_and_scope() -> None:
    collection = _Collection()
    adapter = ChromaSemanticAdapter(_Store([]), _Embedding())
    adapter._collection = lambda: collection
    plan = build_plan(
        "compiler", namespace="alpha", scope="thread", mode="vector"
    )

    assert adapter.search(plan, limit=5) == []
    assert collection.query_options["where"] == {
        "$and": [
            {"vector_text_version": {"$eq": VECTOR_TEXT_VERSION}},
            {"ns": {"$eq": "alpha"}},
            {"scope": {"$eq": "thread"}},
        ]
    }


def test_chroma_search_fails_closed_on_legacy_rows_before_top_k() -> None:
    current = _record("clm:current", {"subject": "current evidence"})
    legacy = _record("clm:legacy", {"subject": "legacy evidence"})
    collection = _Collection()
    collection.rows = {
        legacy.id: {
            "embedding": [1.0],
            "document": "legacy evidence",
            "metadata": {"kind": "CLM", "ns": "alpha", "scope": "thread"},
            "distance": 0.0,
        },
        current.id: {
            "embedding": [1.0],
            "document": "current evidence",
            "metadata": {
                "kind": "CLM",
                "ns": "alpha",
                "scope": "thread",
                "vector_text_version": VECTOR_TEXT_VERSION,
            },
            "distance": 0.5,
        },
    }
    adapter = ChromaSemanticAdapter(_Store([current, legacy]), _Embedding())
    adapter._collection = lambda: collection
    plan = build_plan(
        "evidence", namespace="alpha", scope="thread", mode="vector"
    )

    hits = adapter.search(plan, limit=1)

    assert [hit.record.id for hit in hits] == [current.id]
    assert collection.query_options["where"] == {
        "$and": [
            {"vector_text_version": {"$eq": VECTOR_TEXT_VERSION}},
            {"ns": {"$eq": "alpha"}},
            {"scope": {"$eq": "thread"}},
        ]
    }


def test_chroma_search_always_filters_v2_without_boundary_filters() -> None:
    collection = _Collection()
    adapter = ChromaSemanticAdapter(_Store([]), _Embedding())
    adapter._collection = lambda: collection

    assert adapter.search(build_plan("compiler", mode="vector"), limit=5) == []
    assert collection.query_options["where"] == {
        "vector_text_version": {"$eq": VECTOR_TEXT_VERSION}
    }
