from __future__ import annotations

from seam_runtime.mirl import MIRLRecord, RecordKind
from seam_runtime.vector_adapters import MemoryVectorAdapter


class _SignedEmbeddingModel:
    name = "signed-test/1"
    dimension = 1

    def embed(self, text: str) -> list[float]:
        if text == "query" or "positive" in text:
            return [1.0]
        if "negative" in text:
            return [-1.0]
        return [0.0]


def _claim(record_id: str, value: str) -> MIRLRecord:
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.CLM,
        ns="work",
        scope="thread",
        attrs={"subject": "entity", "predicate": "content", "object": value},
    )


def test_memory_vector_filters_nonpositive_similarity_like_persistent_backends():
    adapter = MemoryVectorAdapter(_SignedEmbeddingModel())
    adapter.index_records(
        [
            _claim("clm:positive", "positive"),
            _claim("clm:zero", "zero"),
            _claim("clm:negative", "negative"),
        ]
    )

    assert adapter.search("query", limit=10, namespace="work", scope="thread") == {
        "clm:positive": 1.0
    }
