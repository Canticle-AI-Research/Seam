"""No-provider tests for the sentence-grounded derived-facts preflight."""

from __future__ import annotations

from dataclasses import dataclass, field

from benchmarks.external.mem0_harness.preflight_sentence_grounded_facts import (
    SentenceGroundedFact,
    first_person_declarative_sentences,
    summarize_record,
    validate_sentence_grounded_fact,
)


def test_candidate_sentences_are_exact_first_person_declaratives():
    text = "I really love surfing. Do I need a new board? Mary likes skiing."

    assert first_person_declarative_sentences(text) == ("I really love surfing.",)


def test_fact_requires_exact_sentence_and_canonical_speaker():
    source = "I really love surfing when it is warm."
    valid = validate_sentence_grounded_fact(
        {
            "fact": "John enjoys surfing in warm weather.",
            "evidence_sentence_index": 0,
        },
        speaker="John",
        source_text=source,
    )
    assert valid == SentenceGroundedFact(
        fact="John enjoys surfing in warm weather.",
        evidence_sentence=source,
        evidence_start=0,
        evidence_end=len(source),
    )
    assert validate_sentence_grounded_fact(
        {"fact": "I enjoy surfing.", "evidence_sentence_index": 0},
        speaker="John",
        source_text=source,
    ) is None
    assert validate_sentence_grounded_fact(
        {"fact": "Mary enjoys surfing.", "evidence_sentence_index": 0},
        speaker="John",
        source_text=source,
    ) is None
    assert validate_sentence_grounded_fact(
        {"fact": "John enjoys surfing.", "evidence_sentence_index": 1},
        speaker="John",
        source_text=source,
    ) is None


def test_fact_preserves_numbers_and_negation():
    source = "I have not visited Paris in 3 years."

    assert validate_sentence_grounded_fact(
        {
            "fact": "John has not visited Paris in 3 years.",
            "evidence_sentence_index": 0,
        },
        speaker="John",
        source_text=source,
    ) == SentenceGroundedFact(
        fact="John has not visited Paris in 3 years.",
        evidence_sentence=source,
        evidence_start=0,
        evidence_end=len(source),
    )
    assert validate_sentence_grounded_fact(
        {
            "fact": "John visited Paris 3 years ago.",
            "evidence_sentence_index": 0,
        },
        speaker="John",
        source_text=source,
    ) is None
    assert validate_sentence_grounded_fact(
        {
            "fact": "John has not visited Paris recently.",
            "evidence_sentence_index": 0,
        },
        speaker="John",
        source_text=source,
    ) is None


@dataclass
class _Extractor:
    calls: int = 0
    cache_hits: int = 0
    model_fact_items: int = 0
    bound_fact_items: int = 0
    validated_fact_items: int = 0
    rejection_counts: dict[str, int] = field(default_factory=dict)
    seen: list[tuple[str, str]] = field(default_factory=list)

    def extract(self, *, speaker: str, source_text: str):
        self.calls += 1
        self.model_fact_items += 2
        self.bound_fact_items += 2
        self.validated_fact_items += 1
        self.seen.append((speaker, source_text))
        return (
            SentenceGroundedFact(
                fact=f"{speaker} enjoys surfing.",
                evidence_sentence=source_text,
            ),
        )


class _Embedder:
    def cos(self, a: str, b: str) -> float:
        if "enjoys surfing" in b:
            return 0.9
        if "enjoys surfing" in a:
            return 0.8
        return 0.4


def _evaluation(question_id: str) -> dict:
    return {
        "question_id": question_id,
        "conversation_idx": 0,
        "category": 1,
        "evidence": ["d1"],
        "cutoff_results": {"top_200": {"score": 0.0}},
        "retrieval": {"search_query": "What sport does John enjoy?"},
    }


def test_summary_dedupes_turn_extraction_and_emits_numeric_only():
    extractor = _Extractor()
    report = summarize_record(
        {"evaluations": [_evaluation("q1"), _evaluation("q2")]},
        [{
            "d1": {
                "speaker": "John",
                "text": "I really love surfing.",
                "timestamp": "2024-01-01",
                "envelope": "[John 2024-01-01] I really love surfing.",
            }
        }],
        extractor=extractor,
        embedder=_Embedder(),
    )

    assert extractor.calls == 1
    assert report["paid_provider_calls"] == 0
    assert report["policy_plumbing_changed"] is False
    assert report["totals"]["misses_with_bound_fact"] == 2
    assert report["totals"]["unique_candidate_turns"] == 1
    assert report["totals"]["misses_fact_beats_raw_gold"] == 2
    assert report["totals"]["model_fact_items"] == 4
    assert report["totals"]["bound_fact_items"] == 4
    assert report["totals"]["validated_fact_items"] == 2
    assert report["totals"]["provenance_bound_facts"] == 2
    assert report["provenance_binding_precision"] == 1.0
    assert report["safety_acceptance_rate"] == 0.5
    serialized = str(report)
    assert "I really love surfing" not in serialized
    assert "John enjoys surfing" not in serialized
