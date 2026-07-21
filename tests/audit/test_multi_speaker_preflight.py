"""Unit tests for the multi-speaker coverage preflight aggregation.

A fake extractor + fake embedder exercise ``summarize_record`` with no Ollama and
no provider calls. They pin the one metric the variant exists to prove: reach on
gold turns that have NO first-person sentence (the third-person-only upside).
"""

from __future__ import annotations

from types import SimpleNamespace

from benchmarks.external.mem0_harness.preflight_multi_speaker_facts import (
    OpenAIMultiSpeakerFactExtractor,
    summarize_record,
)
from seam_runtime.multi_speaker_facts import SentenceGroundedFact


class FakeExtractor:
    """Returns one fact for any turn whose text starts with 'FACT:'."""

    def __init__(self) -> None:
        self.calls = 0
        self.cache_hits = 0
        self.model_fact_items = 0
        self.validated_fact_items = 0
        self.rejection_counts: dict[str, int] = {}

    def extract(self, *, speaker: str, source_text: str):
        self.model_fact_items += 1
        if source_text.startswith("FACT:"):
            self.validated_fact_items += 1
            return (SentenceGroundedFact("fact text", source_text, 0, len(source_text)),)
        self.rejection_counts["rejected"] = self.rejection_counts.get("rejected", 0) + 1
        return ()


class FakeEmbedder:
    def cos(self, a: str, b: str) -> float:
        # A distilled fact ("fact text") scores higher than a raw envelope.
        return 0.9 if "fact" in b else 0.3


def _miss(qid: str, conv_idx: int, evidence: list[str], cat: int = 1) -> dict:
    return {
        "question_id": qid,
        "category": cat,
        "conversation_idx": conv_idx,
        "evidence": evidence,
        "cutoff_results": {"top_200": {"score": 0.0}},
        "retrieval": {"search_query": "some query"},
    }


def test_third_person_only_reach_counted() -> None:
    # d_tp: third-person gold turn (no first-person) that yields a fact.
    # d_fp: first-person gold turn that yields a fact.
    turn_index = [
        {
            "d_tp": {"text": "FACT: Sara loves painting.", "speaker": "John", "envelope": "raw tp"},
            "d_fp": {"text": "FACT: I love surfing.", "speaker": "John", "envelope": "raw fp"},
        }
    ]
    payload = {
        "evaluations": [
            _miss("q_tp", 0, ["d_tp"]),  # reached only via third-person
            _miss("q_fp", 0, ["d_fp"]),  # reached via first-person
        ]
    }
    report = summarize_record(
        payload, turn_index, extractor=FakeExtractor(), embedder=FakeEmbedder()
    )
    t = report["totals"]
    assert t["misses"] == 2
    assert t["misses_with_fact"] == 2
    assert t["misses_reached_third_person_only"] == 1  # only q_tp
    # Fact ("fact text") beats the raw envelope for both reached misses.
    assert t["misses_fact_beats_raw_gold"] == 2
    assert report["reach_delta_vs_sentence_grounded"] == 2 - 51


def test_unreached_miss_not_counted() -> None:
    turn_index = [
        {"d0": {"text": "no extractable fact here.", "speaker": "A", "envelope": "raw"}}
    ]
    payload = {"evaluations": [_miss("q0", 0, ["d0"])]}
    report = summarize_record(
        payload, turn_index, extractor=FakeExtractor(), embedder=FakeEmbedder()
    )
    assert report["totals"]["misses_with_fact"] == 0
    assert report["totals"]["misses_reached_third_person_only"] == 0
    assert report["gates"]["reached_misses"] is False


def test_category_filter_and_correct_excluded() -> None:
    turn_index = [{"d0": {"text": "FACT: Sara paints.", "speaker": "A", "envelope": "r"}}]
    correct = _miss("q_correct", 0, ["d0"])
    correct["cutoff_results"]["top_200"]["score"] = 1.0  # not a miss
    payload = {
        "evaluations": [
            _miss("q_cat1", 0, ["d0"], cat=1),
            _miss("q_cat2", 0, ["d0"], cat=2),  # filtered out
            correct,  # excluded (score 1.0)
        ]
    }
    report = summarize_record(
        payload, turn_index, extractor=FakeExtractor(), embedder=FakeEmbedder(),
        categories=frozenset({1, 3}),
    )
    assert report["totals"]["misses"] == 1
    assert report["cases"][0]["question_id"] == "q_cat1"


def test_openai_extractor_holds_contract_fixed_and_counts_usage() -> None:
    class FakeCompletions:
        def __init__(self) -> None:
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content=(
                                '{"facts":[{"fact":"Sara enjoys painting.",'
                                '"evidence_sentence_index":0}]}'
                            )
                        )
                    )
                ],
                usage=SimpleNamespace(prompt_tokens=120, completion_tokens=18),
            )

    completions = FakeCompletions()
    client = SimpleNamespace(
        chat=SimpleNamespace(completions=completions),
    )
    extractor = OpenAIMultiSpeakerFactExtractor(
        model="gpt-4o",
        client=client,
        ground_scope="turn",
    )

    facts = extractor.extract(
        speaker="John",
        source_text="Sara likes painting.",
    )

    assert [fact.fact for fact in facts] == ["Sara enjoys painting."]
    assert completions.kwargs["model"] == "gpt-4o"
    assert completions.kwargs["response_format"] == {"type": "json_object"}
    assert (
        "The source sentence must explicitly state it"
        in completions.kwargs["messages"][0]["content"]
    )
    assert extractor.config_metadata()["prompt_version"] == (
        "multi-speaker-grounded/1"
    )
    assert extractor.calls == 1
    assert extractor.input_tokens == 120
    assert extractor.output_tokens == 18
