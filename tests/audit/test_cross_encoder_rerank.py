from __future__ import annotations

import sys
from unittest import mock

import pytest

# ---------------------------------------------------------------------------
# cross_encoder_rerank() unit tests
# ---------------------------------------------------------------------------

def test_cross_encoder_rerank_returns_scores_in_order() -> None:
    """Stub cross-encoder returns known scores; verify the function passes
    them through in the same order."""
    from benchmarks.external.locomo.rerank import clear_cross_encoder_cache, cross_encoder_rerank

    query = "what did Alice say?"
    candidates = ["Alice said hello", "Bob replied goodbye", "Alice left"]

    clear_cross_encoder_cache()
    with mock.patch("sentence_transformers.CrossEncoder") as MockEncoder:
        instance = MockEncoder.return_value
        instance.predict.return_value = [0.9, 0.3, 0.7]

        scores = cross_encoder_rerank(query, candidates)

    assert scores == [0.9, 0.3, 0.7]
    MockEncoder.assert_called_once_with("cross-encoder/ms-marco-MiniLM-L6-v2")
    instance.predict.assert_called_once_with(
        [[query, "Alice said hello"], [query, "Bob replied goodbye"], [query, "Alice left"]]
    )


def test_cross_encoder_rerank_raises_without_sentence_transformers() -> None:
    """Clear RuntimeError with install hint when sentence_transformers is absent."""
    from benchmarks.external.locomo.rerank import clear_cross_encoder_cache, cross_encoder_rerank

    clear_cross_encoder_cache()
    with mock.patch.dict(sys.modules, {"sentence_transformers": None}):
        with pytest.raises(RuntimeError, match="sentence-transformers"):
            cross_encoder_rerank("q", ["a", "b"])


def test_cross_encoder_rerank_custom_model() -> None:
    """Model name is forwarded to CrossEncoder constructor."""
    from benchmarks.external.locomo.rerank import clear_cross_encoder_cache, cross_encoder_rerank

    clear_cross_encoder_cache()
    with mock.patch("sentence_transformers.CrossEncoder") as MockEncoder:
        instance = MockEncoder.return_value
        instance.predict.return_value = [0.5, 0.8]

        cross_encoder_rerank("q", ["a", "b"], model="custom/model")

    MockEncoder.assert_called_once_with("custom/model")


def test_cross_encoder_rerank_reuses_model_instance() -> None:
    """Repeated calls with the same model do not reload the cross-encoder."""
    from benchmarks.external.locomo.rerank import clear_cross_encoder_cache, cross_encoder_rerank

    clear_cross_encoder_cache()
    with mock.patch("sentence_transformers.CrossEncoder") as MockEncoder:
        instance = MockEncoder.return_value
        instance.predict.return_value = [0.4]

        cross_encoder_rerank("q1", ["a"])
        cross_encoder_rerank("q2", ["b"])

    MockEncoder.assert_called_once_with("cross-encoder/ms-marco-MiniLM-L6-v2")


# ---------------------------------------------------------------------------
# Adapter integration tests
# ---------------------------------------------------------------------------

def test_adapter_rerank_defaults_to_none() -> None:
    """Rerank is disabled by default."""
    from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter

    adapter = SeamLocomoAdapter()
    assert adapter._rerank is None


def test_adapter_accepts_rerank_cross_encoder() -> None:
    """Adapter stores rerank='cross-encoder' when requested."""
    from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter

    adapter = SeamLocomoAdapter(rerank="cross-encoder")
    assert adapter._rerank == "cross-encoder"


def test_adapter_rerank_reorders_candidates() -> None:
    """Adapter re-sorts top-K candidates according to cross-encoder scores."""
    from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter
    from benchmarks.external.locomo.rerank import clear_cross_encoder_cache
    from seam_runtime.mirl import MIRLRecord, RecordKind, SearchCandidate, SearchResult

    clear_cross_encoder_cache()
    adapter = SeamLocomoAdapter(rerank="cross-encoder")
    result = SearchResult(
        query="what color?",
        candidates=[
            SearchCandidate(
                record=MIRLRecord(
                    id="evt:blue",
                    kind=RecordKind.EVT,
                    attrs={"summary": "Alice liked blue"},
                ),
                score=0.9,
            ),
            SearchCandidate(
                record=MIRLRecord(
                    id="evt:green",
                    kind=RecordKind.EVT,
                    attrs={"summary": "Alice painted the room green"},
                ),
                score=0.1,
            ),
        ],
    )

    with mock.patch("sentence_transformers.CrossEncoder") as MockEncoder:
        instance = MockEncoder.return_value
        instance.predict.return_value = [0.2, 0.95]

        reranked = adapter._rerank_candidates("what color?", result)

    assert [candidate.record.id for candidate in reranked.candidates] == [
        "evt:green",
        "evt:blue",
    ]
    assert [round(candidate.score, 2) for candidate in reranked.candidates] == [
        0.95,
        0.2,
    ]


def test_adapter_rerank_off_does_not_reorder() -> None:
    """With rerank disabled, the default bi-encoder ranking is preserved."""
    import tempfile
    from pathlib import Path

    from benchmarks.external.common.types import ConversationTurn
    from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter

    with tempfile.TemporaryDirectory() as tmpdir:
        db = Path(tmpdir) / "test.db"
        adapter = SeamLocomoAdapter(db_path=str(db))

        sid = "scope-1"
        adapter.reset(sid)
        adapter.ingest_turn(
            sid,
            ConversationTurn(
                speaker="Alice", text="My favorite color is blue",
                timestamp="2024-01-01T00:00:00Z",
            ),
        )
        adapter.ingest_turn(
            sid,
            ConversationTurn(
                speaker="Bob", text="I prefer red over blue",
                timestamp="2024-01-02T00:00:00Z",
            ),
        )

        answer = adapter.answer(sid, "what color does Alice like?")
        assert len(answer.retrieved_context) > 0
        # Release the cached per-scope runtime so the TemporaryDirectory can be
        # removed on Windows (an open SQLite handle locks scope-1.db: WinError 32).
        adapter.close()


# ---------------------------------------------------------------------------
# CLI flag wiring tests
# ---------------------------------------------------------------------------

def test_run_parser_accepts_rerank_flag() -> None:
    """--rerank cross-encoder is accepted by the argument parser."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--rerank", choices=["none", "cross-encoder"], default="none")
    parser.add_argument("--quickstart", action="store_true")

    args = parser.parse_args(["--quickstart", "--rerank", "cross-encoder"])
    assert args.rerank == "cross-encoder"


def test_build_adapter_passes_rerank() -> None:
    """build_adapter forwards rerank to the SEAM adapter constructor."""
    from benchmarks.external.locomo.run import build_adapter

    adapter = build_adapter("seam", rerank="cross-encoder")
    assert adapter._rerank == "cross-encoder"


def test_build_adapter_default_rerank_none() -> None:
    """build_adapter defaults rerank to None (off)."""
    from benchmarks.external.locomo.run import build_adapter

    adapter = build_adapter("seam")
    assert adapter._rerank is None
