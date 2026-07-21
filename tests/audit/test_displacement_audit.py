"""Unit tests for the free sentence-grounded displacement audit.

These exercise the pure comparator with synthetic artifacts: no Ollama, no
pgvector, no provider calls. They pin the five metrics the #439 handoff asks
for -- gold-evidence presence, fact placement, source-before-fact ordering,
pack displacement, and the sentinel non-regression guard.
"""

from __future__ import annotations

import json

from benchmarks.external.mem0_harness.preflight_displacement_audit import (
    displacement_for_question,
    fact_source_raw_id,
    gold_texts_for,
    is_fact_row,
    row_id,
    run_audit,
)


def raw_row(rid: str, text: str, score: float = 0.9) -> dict:
    return {"id": rid, "memory": text, "score": score}


def fact_row(claim_id: str, source_raw_id: str, source_text: str, score: float = 0.95) -> dict:
    fact = {
        "claim_id": claim_id,
        "object": "surfing",
        "predicate": "likes",
        "source_raw_id": source_raw_id,
        "subject": "John",
    }
    source = {"id": source_raw_id, "raw": source_text}
    memory = (
        "SEAM-FACT/1|"
        + json.dumps(fact, sort_keys=True, separators=(",", ":"))
        + "\nSEAM-SOURCE/1|"
        + json.dumps(source, sort_keys=True, separators=(",", ":"))
    )
    return {"id": claim_id, "memory": memory, "score": score}


def test_row_classification_and_source_parse() -> None:
    raw = raw_row("r1", "[John 2023-01-01] plain turn")
    fact = fact_row("c1", "r9", "I love surfing")
    assert is_fact_row(raw) is False
    assert is_fact_row(fact) is True
    assert row_id(fact) == "c1"
    assert fact_source_raw_id(fact) == "r9"
    assert fact_source_raw_id(raw) is None


def test_clean_gain_passes_gate() -> None:
    # Baseline misses gold; candidate retrieves the fact, which pulls its source
    # gold RAW into context (source-before-fact). >=4 RAW precede the fact so the
    # 20% ceiling holds. No sentinel regression.
    baseline = {
        "question_id": "q1",
        "category": 1,
        "conversation_idx": 0,
        "evidence": ["d1"],
        "cutoff_results": {"top_200": {"score": 0.0}},  # a miss
        "retrieval": {
            "search_results": [raw_row(f"r{i}", f"unrelated turn {i}") for i in range(5)]
        },
    }
    candidate = {
        "question_id": "q1",
        "conversation_idx": 0,
        "retrieval": {
            "search_results": [
                *[raw_row(f"r{i}", f"unrelated turn {i}") for i in range(4)],
                raw_row("rg", "[John 2023-01-01] I love surfing so much"),
                fact_row("c1", "rg", "I love surfing so much"),
            ]
        },
    }
    turn_index = [{"d1": {"text": "I love surfing so much", "speaker": "John", "envelope": ""}}]
    report = run_audit(
        {"evaluations": [baseline]},
        {"evaluations": [candidate]},
        turn_index,
        expected_conversations=frozenset({0}),
    )
    assert report["gate_passed"] is True
    assert report["totals"]["miss_gold_gained"] == 1
    assert report["totals"]["sentinel_gold_lost"] == 0
    assert report["miss_net_gold_gain"] == 1


def test_sentinel_gold_loss_blocks_gate() -> None:
    # A previously CORRECT case whose gold RAW is displaced out of the cutoff.
    baseline = {
        "question_id": "q2",
        "category": 1,
        "conversation_idx": 0,
        "evidence": ["d1"],
        "cutoff_results": {"top_200": {"score": 1.0}},  # sentinel
        "retrieval": {"search_results": [raw_row("rg", "critical gold sentence")]},
    }
    candidate = {
        "question_id": "q2",
        "conversation_idx": 0,
        "retrieval": {"search_results": [raw_row("rx", "some other row")]},
    }
    turn_index = [{"d1": {"text": "critical gold sentence", "speaker": "A", "envelope": ""}}]
    report = run_audit(
        {"evaluations": [baseline]},
        {"evaluations": [candidate]},
        turn_index,
        cutoff=1,
        expected_conversations=frozenset({0}),
    )
    assert report["gates"]["no_sentinel_gold_loss"] is False
    assert report["gate_passed"] is False
    assert report["totals"]["sentinel_gold_lost"] == 1


def test_ordering_violation_flagged() -> None:
    # Fact appears BEFORE its source RAW -> contract breach.
    rows = [
        fact_row("c1", "rg", "I love surfing"),
        raw_row("rg", "[John] I love surfing"),
    ]
    result = displacement_for_question(
        baseline_rows=[raw_row("rg", "[John] I love surfing")],
        candidate_rows=rows,
        gold_texts=[],
        was_correct=False,
        cutoff=10,
    )
    assert result["ordering_violations"] == 1


def test_ceiling_violation_flagged() -> None:
    # Two facts in the first two positions -> 100% > 20% ceiling.
    rows = [
        fact_row("c1", "r1", "a"),
        fact_row("c2", "r2", "b"),
        raw_row("r1", "raw one"),
        raw_row("r2", "raw two"),
    ]
    result = displacement_for_question(
        baseline_rows=[raw_row("r1", "raw one")],
        candidate_rows=rows,
        gold_texts=[],
        was_correct=False,
        cutoff=10,
    )
    assert result["ceiling_violations"] > 0


def test_raw_displacement_counted() -> None:
    baseline = [raw_row("r1", "one"), raw_row("r2", "two"), raw_row("r3", "three")]
    # Candidate drops r3 within the cutoff.
    candidate = [raw_row("r1", "one"), raw_row("r2", "two")]
    result = displacement_for_question(
        baseline_rows=baseline,
        candidate_rows=candidate,
        gold_texts=[],
        was_correct=False,
        cutoff=2,
    )
    # Within cutoff=2 baseline has {r1,r2}; candidate has {r1,r2} -> 0 displaced.
    assert result["raw_displaced"] == 0
    # At full cutoff, r3 is displaced.
    result_full = displacement_for_question(
        baseline_rows=baseline,
        candidate_rows=candidate,
        gold_texts=[],
        was_correct=False,
        cutoff=10,
    )
    assert result_full["raw_displaced"] == 1


def test_gold_texts_for_and_missing_candidate_blocks_coverage() -> None:
    turn_index = [{"d1": {"text": "Hello World", "speaker": "A", "envelope": ""}}]
    evaluation = {"conversation_idx": 0, "evidence": ["d1", "d_missing"]}
    assert gold_texts_for(evaluation, turn_index) == ["hello world"]

    # A baseline question absent from the declared candidate scope hard-fails.
    baseline = {
        "question_id": "only_in_baseline",
        "category": 1,
        "conversation_idx": 0,
        "evidence": ["d1"],
        "cutoff_results": {"top_200": {"score": 0.0}},
        "retrieval": {"search_results": [raw_row("r1", "x")]},
    }
    report = run_audit(
        {"evaluations": [baseline]},
        {"evaluations": []},
        turn_index,
        expected_conversations=frozenset({0}),
    )
    assert report["totals"]["questions"] == 0
    assert report["coverage"]["missing_questions"] == 1
    assert report["gates"]["coverage_complete"] is False
    assert report["gate_passed"] is False


def test_category_filter() -> None:
    turn_index = [{"d1": {"text": "t", "speaker": "A", "envelope": ""}}]
    make = lambda qid, cat: {  # noqa: E731
        "question_id": qid,
        "category": cat,
        "conversation_idx": 0,
        "evidence": ["d1"],
        "cutoff_results": {"top_200": {"score": 0.0}},
        "retrieval": {"search_results": [raw_row("r1", "t")]},
    }
    baseline = {"evaluations": [make("q1", 1), make("q2", 2)]}
    candidate = {
        "evaluations": [
            {"question_id": "q1", "retrieval": {"search_results": [raw_row("r1", "t")]}},
            {"question_id": "q2", "retrieval": {"search_results": [raw_row("r1", "t")]}},
        ]
    }
    report = run_audit(
        baseline,
        candidate,
        turn_index,
        categories=frozenset({1}),
        expected_conversations=frozenset({0}),
    )
    assert report["totals"]["questions"] == 1
    assert report["cases"][0]["category"] == 1


def test_duplicate_candidate_question_blocks_coverage() -> None:
    turn_index = [{"d1": {"text": "t", "speaker": "A", "envelope": ""}}]
    baseline = {
        "question_id": "q1",
        "category": 1,
        "conversation_idx": 0,
        "evidence": ["d1"],
        "cutoff_results": {"top_200": {"score": 0.0}},
        "retrieval": {"search_results": [raw_row("r1", "t")]},
    }
    candidate = {
        "question_id": "q1",
        "conversation_idx": 0,
        "retrieval": {"search_results": [raw_row("r1", "t")]},
    }
    report = run_audit(
        {"evaluations": [baseline]},
        {"evaluations": [candidate, candidate]},
        turn_index,
        expected_conversations=frozenset({0}),
    )
    assert report["coverage"]["duplicate_candidate_qids"] == 1
    assert report["gates"]["coverage_complete"] is False
