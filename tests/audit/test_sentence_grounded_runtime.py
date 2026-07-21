"""Runtime invariants for the default-off sentence-grounded fact policy."""

from __future__ import annotations

from copy import deepcopy

from seam_runtime.derived_fact_context import (
    SENTENCE_GROUNDED_CLM_V1,
    configure_derived_facts,
    grounded_spans_match_source,
    is_eligible_derived_claim,
    resolve_derived_facts_policy,
)
from seam_runtime.mirl import RecordKind
from seam_runtime.nl import compile_nl
from seam_runtime.sentence_grounded_facts import SentenceGroundedFact
from seam_runtime.vector import SQLiteVectorIndex


class _SentenceExtractor:
    def __init__(self) -> None:
        self.calls = 0

    def config_metadata(self) -> dict[str, object]:
        return {
            "type": "test-sentence-grounded",
            "prompt_fingerprint": "frozen-test",
        }

    def extract_sentence_facts(
        self,
        text: str,
        *,
        speaker: str,
    ) -> tuple[SentenceGroundedFact, ...]:
        self.calls += 1
        assert text == "I really love surfing."
        assert speaker == "John"
        return (
            SentenceGroundedFact(
                fact="John enjoys surfing.",
                evidence_sentence=text,
                evidence_start=0,
                evidence_end=len(text),
            ),
        )


def _compiled_sentence_fact():
    source = "[John 2024-01-01] I really love surfing."
    batch = compile_nl(
        source,
        ns="locomo:user-1",
        scope="thread",
        extractor=_SentenceExtractor(),
        speaker="John",
        source_timestamp="2024-01-01",
        derived_fact_policy=SENTENCE_GROUNDED_CLM_V1,
    )
    fact = next(
        record
        for record in batch.records
        if record.ext.get("derived_fact_policy") == SENTENCE_GROUNDED_CLM_V1
    )
    raw = batch.kind(RecordKind.RAW)[0]
    span = next(record for record in batch.kind(RecordKind.SPAN) if record.id in fact.evidence)
    return source, batch, fact, raw, span


def test_sentence_grounded_policy_compiles_index_fact_with_exact_source():
    source, _, fact, raw, span = _compiled_sentence_fact()
    metadata = raw.ext["source_metadata"]

    assert resolve_derived_facts_policy(SENTENCE_GROUNDED_CLM_V1) == SENTENCE_GROUNDED_CLM_V1
    assert is_eligible_derived_claim(fact, policy=SENTENCE_GROUNDED_CLM_V1)
    assert fact.attrs["subject_label"] == "John"
    assert fact.attrs["predicate"] == "sentence_fact"
    assert fact.attrs["object"] == "John enjoys surfing."
    assert SQLiteVectorIndex.render_record_text(fact) == "John enjoys surfing."
    assert grounded_spans_match_source(
        fact,
        source,
        evidence_start=span.attrs["start"],
        evidence_end=span.attrs["end"],
        source_speaker=metadata["speaker"],
        source_timestamp=metadata["timestamp"],
        source_prefix_end=metadata["prefix_end"],
        require_evidence_bounds=True,
        require_source_metadata=True,
    )


def test_sentence_grounded_source_validation_rejects_tampering():
    source, _, fact, raw, span = _compiled_sentence_fact()
    metadata = raw.ext["source_metadata"]
    tampered = deepcopy(fact)
    tampered.attrs["object"] = "John dislikes surfing."

    assert not grounded_spans_match_source(
        tampered,
        source,
        evidence_start=span.attrs["start"],
        evidence_end=span.attrs["end"],
        source_speaker=metadata["speaker"],
        source_timestamp=metadata["timestamp"],
        source_prefix_end=metadata["prefix_end"],
        require_evidence_bounds=True,
        require_source_metadata=True,
    )


def test_sentence_grounded_cache_is_speaker_scoped(tmp_path, monkeypatch):
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    monkeypatch.delenv("SEAM_EMBEDDING_PROVIDER", raising=False)
    extractor = _SentenceExtractor()
    runtime = configure_derived_facts(
        tmp_path,
        policy=SENTENCE_GROUNDED_CLM_V1,
        extractor=extractor,
    )
    scoped = runtime.extractor.bind("locomo:user-1")

    first = scoped.extract_sentence_facts(
        "I really love surfing.",
        speaker="John",
    )
    second = scoped.extract_sentence_facts(
        "I really love surfing.",
        speaker="John",
    )

    assert first == second
    assert extractor.calls == 1
    assert scoped._cache.stats()["hits"] == 1
    assert runtime.config.enabled
