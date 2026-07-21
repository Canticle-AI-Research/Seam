"""Runtime invariants for the default-off multi-speaker research policy."""

from __future__ import annotations

from copy import deepcopy

from benchmarks.external.mem0_harness.seam_mem0_server import SeamMem0Server
from seam_runtime.derived_fact_context import (
    MULTI_SPEAKER_GROUNDED_V1,
    configure_derived_facts,
    grounded_spans_match_source,
    is_eligible_derived_claim,
)
from seam_runtime.mirl import RecordKind
from seam_runtime.nl import compile_nl
from seam_runtime.sentence_grounded_facts import SentenceGroundedFact
from seam_runtime.vector import SQLiteVectorIndex


class _MultiSpeakerExtractor:
    def __init__(self) -> None:
        self.calls = 0

    def config_metadata(self) -> dict[str, object]:
        return {
            "type": "test-multi-speaker-grounded",
            "ground_scope": "turn",
            "prompt_fingerprint": "frozen-test",
        }

    def extract_sentence_facts(
        self,
        text: str,
        *,
        speaker: str,
    ) -> tuple[SentenceGroundedFact, ...]:
        self.calls += 1
        if "Sara likes painting" not in text:
            return ()
        start = text.index("Sara likes painting")
        evidence = "Sara likes painting."
        return (
            SentenceGroundedFact(
                fact="Sara enjoys painting.",
                evidence_sentence=evidence,
                evidence_start=start,
                evidence_end=start + len(evidence),
            ),
        )


class _CrossSentenceExtractor(_MultiSpeakerExtractor):
    def extract_sentence_facts(
        self,
        text: str,
        *,
        speaker: str,
    ) -> tuple[SentenceGroundedFact, ...]:
        self.calls += 1
        assert text == "This is my daughter Sara. She likes painting."
        evidence = "She likes painting."
        start = text.index(evidence)
        return (
            SentenceGroundedFact(
                fact="Sara likes painting.",
                evidence_sentence=evidence,
                evidence_start=start,
                evidence_end=start + len(evidence),
            ),
        )


def _compiled_multi_speaker_fact():
    source = "[John 2024-01-01] Sara likes painting."
    batch = compile_nl(
        source,
        ns="locomo:user-1",
        scope="thread",
        extractor=_MultiSpeakerExtractor(),
        speaker="John",
        source_timestamp="2024-01-01",
        derived_fact_policy=MULTI_SPEAKER_GROUNDED_V1,
    )
    fact = next(
        record for record in batch.records if record.ext.get("derived_fact_policy") == MULTI_SPEAKER_GROUNDED_V1
    )
    raw = batch.kind(RecordKind.RAW)[0]
    span = next(record for record in batch.kind(RecordKind.SPAN) if record.id in fact.evidence)
    return source, fact, raw, span


def test_multi_speaker_policy_compiles_grounded_third_party_fact() -> None:
    source, fact, raw, span = _compiled_multi_speaker_fact()
    metadata = raw.ext["source_metadata"]

    assert is_eligible_derived_claim(
        fact,
        policy=MULTI_SPEAKER_GROUNDED_V1,
    )
    assert fact.attrs["subject_label"] == "John"
    assert fact.attrs["predicate"] == "sentence_fact"
    assert fact.attrs["object"] == "Sara enjoys painting."
    assert SQLiteVectorIndex.render_record_text(fact) == "Sara enjoys painting."
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


def test_multi_speaker_policy_rejects_tampered_fact() -> None:
    source, fact, raw, span = _compiled_multi_speaker_fact()
    metadata = raw.ext["source_metadata"]
    tampered = deepcopy(fact)
    tampered.attrs["object"] = "Bailey enjoys painting."

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

    speaker_tampered = deepcopy(fact)
    speaker_tampered.attrs["subject_label"] = "Maria"
    speaker_tampered.ext["subject_resolution"]["speaker"] = "Maria"
    assert not grounded_spans_match_source(
        speaker_tampered,
        source,
        evidence_start=span.attrs["start"],
        evidence_end=span.attrs["end"],
        source_speaker=metadata["speaker"],
        source_timestamp=metadata["timestamp"],
        source_prefix_end=metadata["prefix_end"],
        require_evidence_bounds=True,
        require_source_metadata=True,
    )


def test_turn_scope_extracts_once_and_binds_adjacent_sentence_name() -> None:
    extractor = _CrossSentenceExtractor()
    source = "[John 2024-01-01] This is my daughter Sara. She likes painting."
    batch = compile_nl(
        source,
        ns="locomo:user-1",
        scope="thread",
        extractor=extractor,
        speaker="John",
        source_timestamp="2024-01-01",
        derived_fact_policy=MULTI_SPEAKER_GROUNDED_V1,
    )
    fact = next(
        record for record in batch.records if record.ext.get("derived_fact_policy") == MULTI_SPEAKER_GROUNDED_V1
    )
    raw = batch.kind(RecordKind.RAW)[0]
    span = next(record for record in batch.kind(RecordKind.SPAN) if record.id in fact.evidence)
    metadata = raw.ext["source_metadata"]

    assert extractor.calls == 1
    assert fact.attrs["object"] == "Sara likes painting."
    assert span.attrs["start"] == source.index("She likes painting.")
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


def test_multi_speaker_cache_is_speaker_scoped(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    monkeypatch.delenv("SEAM_EMBEDDING_PROVIDER", raising=False)
    extractor = _MultiSpeakerExtractor()
    runtime = configure_derived_facts(
        tmp_path,
        policy=MULTI_SPEAKER_GROUNDED_V1,
        extractor=extractor,
    )
    scoped = runtime.extractor.bind("locomo:user-1")

    first = scoped.extract_sentence_facts(
        "Sara likes painting.",
        speaker="John",
    )
    second = scoped.extract_sentence_facts(
        "Sara likes painting.",
        speaker="John",
    )

    assert first == second
    assert extractor.calls == 1
    assert scoped._cache.stats()["hits"] == 1


def test_facade_serves_multi_speaker_fact_after_exact_source(
    tmp_path,
    monkeypatch,
) -> None:
    from benchmarks.external.locomo.adapters import seam as seam_adapter
    from seam_runtime.derived_fact_context import DERIVED_FACTS_EMBEDDING_CONFIG
    from seam_runtime.models import HashEmbeddingModel

    embedding = HashEmbeddingModel(
        name=str(DERIVED_FACTS_EMBEDDING_CONFIG["name"]),
        dimension=int(DERIVED_FACTS_EMBEDDING_CONFIG["dimension"]),
    )
    embedding.local_files_only = True
    monkeypatch.setattr(
        seam_adapter,
        "_DERIVED_FACTS_SENTENCE_TRANSFORMER_MODEL",
        embedding,
    )
    server = SeamMem0Server(
        db_path=str(tmp_path / "multi-speaker-scopes"),
        derived_facts_policy=MULTI_SPEAKER_GROUNDED_V1,
        nl_extractor=_MultiSpeakerExtractor(),
    )
    try:
        server.add(
            {
                "user_id": "multi-speaker-user",
                "timestamp": 1687000000,
                "messages": [
                    {"content": "John: Sara likes painting."},
                    {"content": "John: The weather was sunny."},
                    {"content": "John: The studio was nearby."},
                    {"content": "John: The brushes were clean."},
                    {"content": "John: The canvas was large."},
                ],
            }
        )
        results = server.search(
            {
                "user_id": "multi-speaker-user",
                "query": "What does Sara enjoy?",
                "limit": 10,
            }
        )["results"]

        harness_resorted = sorted(
            results,
            key=lambda item: item.get("score", 0),
            reverse=True,
        )
        assert [item["id"] for item in harness_resorted] == [item["id"] for item in results]

        fact = next(item for item in results if str(item["id"]).startswith("clm:"))
        fact_index = results.index(fact)
        assert '"object":"Sara enjoys painting."' in fact["memory"]
        assert any("Sara likes painting" in str(item["memory"]) for item in results[:fact_index])
        assert sum(str(item["id"]).startswith("clm:") for item in results) * 5 <= len(results)
        stats = server.probe_stats()
        assert stats["derived_facts_policy"] == MULTI_SPEAKER_GROUNDED_V1
        assert stats["enabled"] is True
        assert stats["cache"]["misses"] == 5
    finally:
        server.close()
