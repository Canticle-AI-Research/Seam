"""Batched embedding for bulk ingest.

Bulk document ingest embeds thousands of records per document. Running a
GPU-backed model one string at a time is almost entirely call overhead --
measured 120 rec/s per-record versus 2679 rec/s at batch 64 for bge-small on a
consumer GPU. These tests pin the two properties that make batching safe:
identical vectors, and no requirement that a model implement `embed_many`.
"""

from __future__ import annotations

import pytest

from seam_runtime.models import HashEmbeddingModel, embed_texts


class _EmbedOnlyModel:
    """A legitimate model that predates `embed_many` (and every test double)."""

    name = "embed-only/1"
    dimension = 4

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, text: str) -> list[float]:
        self.calls += 1
        return [float(len(text)), 1.0, 0.0, 0.0]


class _BatchingModel(_EmbedOnlyModel):
    name = "batching/1"

    def __init__(self) -> None:
        super().__init__()
        self.batches: list[int] = []

    def embed_many(self, texts) -> list[list[float]]:
        self.batches.append(len(texts))
        return [self.embed(text) for text in texts]


def test_embed_texts_falls_back_when_a_model_cannot_batch():
    """`EmbeddingModel` is structural, so `embed_many` must stay optional."""

    model = _EmbedOnlyModel()
    vectors = embed_texts(model, ["alpha", "beta", "gamma"])

    assert model.calls == 3, "the fallback must embed each text exactly once"
    assert [v[0] for v in vectors] == [5.0, 4.0, 5.0]


def test_embed_texts_uses_the_batch_path_when_offered():
    model = _BatchingModel()
    vectors = embed_texts(model, ["alpha", "beta", "gamma"])

    assert model.batches == [3], "one call must cover the whole batch"
    assert [v[0] for v in vectors] == [5.0, 4.0, 5.0]


def test_empty_batch_never_calls_the_model():
    model = _BatchingModel()
    assert embed_texts(model, []) == []
    assert model.batches == []
    assert model.calls == 0


def test_batched_vectors_are_identical_to_per_record_vectors():
    """Batching is an optimisation; it must not move a single score."""

    model = HashEmbeddingModel()
    texts = ["the mind concentrates force", "a habit loop has a cue", "phi and integration"]

    assert embed_texts(model, texts) == [model.embed(t) for t in texts]


def test_a_short_batch_from_the_model_is_rejected():
    """A silent length mismatch would misalign every vector with its record."""

    class _Truncating(_EmbedOnlyModel):
        def embed_many(self, texts):
            return [self.embed(t) for t in list(texts)[:-1]]

    with pytest.raises(RuntimeError, match="embed_many returned"):
        embed_texts(_Truncating(), ["a", "b", "c"])


def test_indexing_a_batch_matches_indexing_one_at_a_time(tmp_path):
    """End-to-end: the stored vectors must not depend on batch shape."""

    from seam_runtime.mirl import IRBatch
    from seam_runtime.runtime import SeamRuntime

    texts = [
        "William James described the stream of consciousness.",
        "Tononi proposed integrated information theory.",
        "Baars framed a global workspace.",
    ]

    one = SeamRuntime(tmp_path / "one.db", allow_pgvector_env=False)
    bulk = SeamRuntime(tmp_path / "bulk.db", allow_pgvector_env=False)
    try:
        records = []
        for index, text in enumerate(texts):
            batch = one.compile_nl(text, source_ref=f"local://b/{index}",
                                   ns="library.rare-books", scope="project")
            one.persist_ir(batch)
            records.extend(
                bulk.compile_nl(text, source_ref=f"local://b/{index}",
                                ns="library.rare-books", scope="project").records
            )
        bulk.persist_ir(IRBatch(records))

        def vectors(rt):
            with rt.store._pool.checkout() as connection:
                return {
                    row[0]: row[1]
                    for row in connection.execute(
                        "select record_id, vector_json from vector_index order by record_id"
                    ).fetchall()
                }

        per_record, batched = vectors(one), vectors(bulk)
        assert per_record, "the comparison needs indexed vectors"
        assert set(per_record) == set(batched)
        assert per_record == batched
    finally:
        one.close()
        bulk.close()


# -- review repairs (PR #230) -------------------------------------------


def test_explicit_protocol_subclass_without_embed_many_still_works():
    """A model may subclass the Protocol and implement only `embed`.

    `getattr` then finds the protocol's own `...` stub, which returns None.
    Treating that as a real batch implementation crashed bulk persistence for
    otherwise valid custom models.
    """

    from seam_runtime.models import EmbeddingModel

    class CustomModel(EmbeddingModel):
        name = "custom/1"
        dimension = 3

        def embed(self, text: str) -> list[float]:
            return [float(len(text)), 0.0, 0.0]

    assert embed_texts(CustomModel(), ["ab", "cde"]) == [
        [2.0, 0.0, 0.0],
        [3.0, 0.0, 0.0],
    ]


def test_index_records_flushes_in_bounded_slices(tmp_path, monkeypatch):
    """A large batch must not hold every rendered string and vector at once."""

    from seam_runtime import models as models_module
    from seam_runtime.mirl import MIRLRecord, RecordKind
    from seam_runtime.vector import SQLiteVectorIndex

    monkeypatch.setattr(models_module, "EMBED_FLUSH_SIZE", 4)
    import seam_runtime.vector as vector_module

    monkeypatch.setattr(vector_module, "EMBED_FLUSH_SIZE", 4)

    seen: list[int] = []

    class _Counting(HashEmbeddingModel):
        def embed_many(self, texts):
            seen.append(len(texts))
            return [self.embed(t) for t in texts]

    records = [
        MIRLRecord(
            id=f"clm:bounded:{i}",
            kind=RecordKind.CLM,
            ns="library.rare-books",
            scope="project",
            attrs={"subject": f"s{i}", "predicate": "p", "object": f"o{i}"},
        )
        for i in range(10)
    ]
    index = SQLiteVectorIndex(str(tmp_path / "bounded.db"), _Counting())
    index.index_records(records)

    assert seen, "the batch path must have been used"
    assert max(seen) <= 4, f"a flush exceeded the bound: {seen}"
    assert sum(seen) == len(records)


def test_cloud_batches_split_on_aggregate_size_not_just_count():
    """Providers cap total tokens per request, not item count."""

    from seam_runtime.models import OpenAICompatibleEmbeddingModel

    model = OpenAICompatibleEmbeddingModel(model="test", dimension=3)
    model.batch_size = 100          # count would never split these
    model.char_budget = 50          # ...but size must

    requests: list[list[str]] = []

    def _fake_request(inputs: list[str]) -> list[list[float]]:
        requests.append(list(inputs))
        return [[1.0, 0.0, 0.0] for _ in inputs]

    model._request = _fake_request  # type: ignore[method-assign]
    vectors = model.embed_many(["x" * 30, "y" * 30, "z" * 30])

    assert len(vectors) == 3
    assert len(requests) == 3, f"expected a split per oversized item, got {requests}"
    assert all(len(r) == 1 for r in requests)


def test_a_single_oversized_input_still_ships_alone():
    """One huge record must not be dropped or silently merged."""

    from seam_runtime.models import OpenAICompatibleEmbeddingModel

    model = OpenAICompatibleEmbeddingModel(model="test", dimension=3)
    model.char_budget = 10
    requests: list[list[str]] = []
    model._request = lambda inputs: (  # type: ignore[method-assign]
        requests.append(list(inputs)) or [[1.0, 0.0, 0.0] for _ in inputs]
    )

    assert len(model.embed_many(["z" * 500])) == 1
    assert requests == [["z" * 500]]
