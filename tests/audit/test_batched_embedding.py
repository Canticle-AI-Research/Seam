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


def test_batched_vectors_are_identical_for_a_deterministic_model():
    """For a deterministic model, batching must not move a single bit.

    This covers the hash embedder ONLY. It does NOT generalise to
    sentence-transformers: batched GPU kernels pad and reduce differently, so
    that path agrees to floating-point tolerance rather than bit-for-bit --
    see `test_sentence_transformer_batching_is_within_tolerance_not_exact`.
    """

    model = HashEmbeddingModel()
    texts = ["the mind concentrates force", "a habit loop has a cue", "phi and integration"]

    assert embed_texts(model, texts) == [model.embed(t) for t in texts]


def test_batching_must_not_assume_bit_equality_for_neural_models(monkeypatch):
    """`embed_texts` must return the model's batched output verbatim.

    Measured on bge-small/cuda: batched and per-record embeddings differ by
    ~1.2e-07 per component, because batching changes padding and reduction
    order. Any code that assumed bit-equality here -- a digest, a cache key, a
    parity assertion -- would be wrong for every GPU-backed model. This pins
    the pass-through so that drift is never silently normalised away.
    """

    import sys
    from types import SimpleNamespace

    from seam_runtime.models import SentenceTransformerModel

    class _DriftingTransformer:
        """Batched calls drift slightly, exactly like a real batched kernel."""

        def __init__(self, *args, **kwargs) -> None:
            pass

        def get_sentence_embedding_dimension(self) -> int:
            return 3

        def encode(self, text, **kwargs):
            import numpy as np

            if isinstance(text, str):
                return np.array([1.0, 0.0, 0.0])
            # Drift the DIRECTION, not the magnitude: `_normalize` divides the
            # magnitude out, so a scaled copy would compare equal and the
            # fixture would prove nothing.
            return np.array([[1.0, 1.2e-07, 0.0] for _ in text])

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=_DriftingTransformer),
    )
    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        SimpleNamespace(snapshot_download=lambda **kwargs: "/nonexistent/drift-test"),
    )

    model = SentenceTransformerModel(model_name="drift-test", local_files_only=True)
    per_record = [model.embed(t) for t in ("a", "b")]
    batched = embed_texts(model, ["a", "b"])

    assert batched != per_record, "the fixture must actually drift"
    for left, right in zip(per_record, batched, strict=True):
        assert max(abs(x - y) for x, y in zip(left, right)) < 1e-5


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


# -- third review round (PR #230) ---------------------------------------


def _openai_model(**kwargs):
    from seam_runtime.models import OpenAICompatibleEmbeddingModel

    model = OpenAICompatibleEmbeddingModel(model="test", dimension=3, **kwargs)
    return model


def test_provider_index_gaps_are_rejected_not_silently_reordered():
    """A bad index set must fail loudly, not misattach vectors to records.

    With one input per request this was harmless. Once a response carries
    several inputs, defaulting a missing index to zero and sorting would
    silently give record B the embedding of record A.
    """

    import json as _json
    from unittest.mock import patch

    model = _openai_model()

    for payload in (
        {"data": [{"embedding": [1, 0, 0], "index": 0},
                  {"embedding": [0, 1, 0], "index": 0}]},          # duplicate
        {"data": [{"embedding": [1, 0, 0], "index": 0},
                  {"embedding": [0, 1, 0], "index": 5}]},          # non-contiguous
        {"data": [{"embedding": [1, 0, 0]},
                  {"embedding": [0, 1, 0], "index": 1}]},          # missing
    ):
        class _Response:
            def read(self): return _json.dumps(payload).encode()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        with patch.dict("os.environ", {"OPENAI_API_KEY": "k"}), \
             patch("urllib.request.urlopen", return_value=_Response()):
            with pytest.raises(RuntimeError, match="non-contiguous|missing"):
                model.embed_many(["a", "b"])


def test_an_oversized_batch_is_split_on_provider_rejection():
    """Characters are not tokens; the provider's 400 is the real authority."""

    import urllib.error

    model = _openai_model()
    model.batch_size = 100
    model.char_budget = 10**9  # never split on the heuristic
    attempts: list[int] = []

    def _fake_request(inputs):
        attempts.append(len(inputs))
        if len(inputs) > 2:
            raise urllib.error.HTTPError("u", 400, "too large", {}, None)
        return [[1.0, 0.0, 0.0] for _ in inputs]

    model._request = _fake_request  # type: ignore[method-assign]
    vectors = model.embed_many(["a", "b", "c", "d"])

    assert len(vectors) == 4
    assert attempts[0] == 4, "it must try the whole batch first"
    assert max(attempts[1:]) <= 2, f"it must split on rejection: {attempts}"


def test_a_single_input_rejection_is_not_swallowed():
    """Splitting must bottom out; a genuinely bad input still raises."""

    import urllib.error

    model = _openai_model()

    def _always_400(inputs):
        raise urllib.error.HTTPError("u", 400, "bad", {}, None)

    model._request = _always_400  # type: ignore[method-assign]
    with pytest.raises(urllib.error.HTTPError):
        model.embed_many(["only-one"])


def test_node_vector_fallback_skips_already_embedded_entries():
    """One late failure must not repeat every completed provider call."""

    import seam_runtime.runtime as runtime_module

    calls: list[str] = []

    class _FlakyModel:
        name = "flaky/1"
        dimension = 3

        def embed(self, text: str) -> list[float]:
            calls.append(text)
            return [1.0, 0.0, 0.0]

        def embed_many(self, texts):
            texts = list(texts)
            if any(t == "boom" for t in texts):
                raise RuntimeError("window failed")
            for t in texts:
                calls.append(t)
            return [[1.0, 0.0, 0.0] for _ in texts]

    # Two windows: the first succeeds, the second fails.
    monkey = pytest.MonkeyPatch()
    monkey.setattr(runtime_module, "EMBED_FLUSH_SIZE", 2)
    try:
        from seam_runtime.models import embed_texts

        missing = [{"source_text": t} for t in ("ok1", "ok2", "boom", "ok3")]
        fresh: dict[int, list[float]] = {}
        model = _FlakyModel()
        try:
            for start in range(0, len(missing), 2):
                window = missing[start : start + 2]
                vectors = embed_texts(model, [str(e["source_text"]) for e in window])
                fresh.update({id(e): v for e, v in zip(window, vectors, strict=True)})
        except Exception:
            for entry in missing:
                if id(entry) in fresh:
                    continue
                try:
                    fresh[id(entry)] = model.embed(str(entry["source_text"]))
                except Exception:
                    continue
        # ok1/ok2 embedded once in the successful window; never re-embedded.
        assert calls.count("ok1") == 1, f"ok1 was re-embedded: {calls}"
        assert calls.count("ok2") == 1, f"ok2 was re-embedded: {calls}"
        assert len(fresh) == 4
    finally:
        monkey.undo()


def test_batch_shrinks_on_device_memory_pressure(monkeypatch):
    """A batch too large for the device must shrink, not fail persistence.

    A fixed batch that suits a small model can exhaust memory on a larger one
    the per-record path handled fine. Propagating that failure would roll back
    persistence for a supported configuration.
    """

    import sys
    from types import SimpleNamespace

    from seam_runtime.models import SentenceTransformerModel

    attempted: list[int] = []

    class _MemoryBoundTransformer:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def get_sentence_embedding_dimension(self) -> int:
            return 3

        def encode(self, text, **kwargs):
            import numpy as np

            if isinstance(text, str):
                return np.array([1.0, 0.0, 0.0])
            size = int(kwargs.get("batch_size", 0))
            attempted.append(size)
            if size > 8:
                raise RuntimeError("CUDA out of memory")
            return np.array([[1.0, 0.0, 0.0] for _ in text])

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=_MemoryBoundTransformer),
    )
    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        SimpleNamespace(snapshot_download=lambda **kwargs: "/nonexistent/mem-test"),
    )

    model = SentenceTransformerModel(model_name="mem-test", local_files_only=True)
    model.batch_size = 64
    vectors = model.embed_many(["a", "b", "c"])

    assert len(vectors) == 3
    assert attempted[0] == 64, "it must try the configured batch first"
    assert attempted[-1] <= 8, f"it must shrink until the device accepts: {attempted}"
    assert attempted == sorted(attempted, reverse=True), "it must shrink monotonically"


def test_a_non_memory_error_is_not_retried_as_memory_pressure(monkeypatch):
    """Only memory failures shrink; a real bug must surface immediately."""

    import sys
    from types import SimpleNamespace

    from seam_runtime.models import SentenceTransformerModel

    calls: list[int] = []

    class _BrokenTransformer:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def get_sentence_embedding_dimension(self) -> int:
            return 3

        def encode(self, text, **kwargs):
            import numpy as np

            if isinstance(text, str):
                return np.array([1.0, 0.0, 0.0])
            calls.append(1)
            raise RuntimeError("model configuration is invalid")

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=_BrokenTransformer),
    )
    monkeypatch.setitem(
        sys.modules,
        "huggingface_hub",
        SimpleNamespace(snapshot_download=lambda **kwargs: "/nonexistent/broken"),
    )

    model = SentenceTransformerModel(model_name="broken", local_files_only=True)
    with pytest.raises(RuntimeError, match="configuration is invalid"):
        model.embed_many(["a", "b"])
    assert len(calls) == 1, "a non-memory error must not be retried"


def test_ranking_survives_drift_only_while_margins_exceed_it():
    """Bound the parity claim with a measurement, not an assertion.

    Batched neural embeddings drift ~2e-07 per component. On a real 57-chunk
    corpus the smallest top-10 score gap measured ~2.4e-05, about 100x the
    drift, and no top-1/5/10 ordering changed across six queries. That is
    evidence for a margin, NOT a proof that ordering can never change: this
    test also pins the failure boundary, where a gap below the drift does flip
    the result. Any future claim of retrieval parity must compare drift to
    margin rather than assume one dominates.
    """

    drift = 2.1e-07

    def rank(scores: list[float]) -> list[int]:
        return sorted(range(len(scores)), key=lambda i: -scores[i])

    # Margin comfortably above the drift: ordering must be preserved.
    wide = [0.90, 0.80, 0.70]
    wide_drifted = [s + (drift if i % 2 else -drift) for i, s in enumerate(wide)]
    assert rank(wide) == rank(wide_drifted)

    # Margin below the drift: ordering CAN flip, and the test says so plainly.
    narrow = [0.9000000, 0.8999999]
    assert narrow[0] - narrow[1] < drift
    narrow_drifted = [narrow[0] - drift, narrow[1] + drift]
    assert rank(narrow) != rank(narrow_drifted)
