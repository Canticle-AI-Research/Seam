"""Hermetic tests for the zero-provider fact-free non-displacing RAW PACK."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from benchmarks.external.mem0_harness.preflight_fact_free_raw_pack import (
    build_candidate_payload,
    run_replay,
)
from seam_runtime.multi_scope_pack import parse_raw_pack_items


class _FakePrompts:
    @staticmethod
    def get_answer_generation_prompt(
        question: str,
        search_results: list[dict[str, Any]],
        reference_date: str | None = None,
        user_profile: dict[str, Any] | None = None,
    ) -> str:
        del user_profile
        memories = "\n".join(str(row.get("memory") or "") for row in search_results)
        return f"date={reference_date}\n{memories}\nquestion={question}"


def _raw_row(record_id: str, memory: str, score: float = 0.5) -> dict[str, Any]:
    return {"id": record_id, "memory": memory, "score": score}


def _fact_row(
    *,
    claim_id: str = "clm:fact:1",
    source_raw_id: str = "raw:source:1",
    source_text: str = "unrelated source clause",
) -> dict[str, Any]:
    fact = {
        "claim_id": claim_id,
        "object": "unrelated source clause",
        "predicate": "said",
        "source_raw_id": source_raw_id,
        "subject": "A",
    }
    source = {"id": source_raw_id, "raw": source_text}
    return {
        "id": claim_id,
        "memory": (
            "SEAM-FACT/1|"
            + json.dumps(fact, sort_keys=True, separators=(",", ":"))
            + "\nSEAM-SOURCE/1|"
            + json.dumps(source, sort_keys=True, separators=(",", ":"))
        ),
        "score": 0.8,
    }


def _evaluation(
    question_id: str,
    rows: list[dict[str, Any]],
    *,
    score: float | None,
) -> dict[str, Any]:
    evaluation: dict[str, Any] = {
        "question_id": question_id,
        "conversation_idx": 0,
        "category": 1,
        "category_name": "single-hop",
        "question": "What did A say?",
        "ground_truth_answer": "critical gold sentence",
        "evidence": ["d1"],
        "user_id": "synthetic-user",
        "reference_date": "January 01, 2024",
        "retrieval": {
            "search_query": "What did A say?",
            "search_results": rows,
            "search_latency_ms": 1.0,
            "total_results": len(rows),
        },
    }
    if score is not None:
        evaluation["cutoff_results"] = {"top_200": {"score": score}}
    return evaluation


def _baseline_payload() -> dict[str, Any]:
    return {
        "metadata": {
            "benchmark": "locomo",
            "answerer_model": "gpt-4o",
            "judge_model": "gpt-4o",
            "provider": "openai",
            "top_k": 200,
        },
        "evaluations": [
            _evaluation(
                "q1",
                [_raw_row("raw:baseline:1", "unrelated baseline memory")],
                score=0.0,
            )
        ],
    }


def _auxiliary_payload(fact: dict[str, Any] | None = None) -> dict[str, Any]:
    # The gold turn text lives in an auxiliary RAW episode, NOT in the fact or
    # its source: the ablation must still surface it after the fact is removed.
    rows = [
        _raw_row("raw:source:1", "unrelated source clause", 0.9),
        _raw_row("raw:episode:1", "critical gold sentence appears here", 0.7),
        _raw_row("raw:episode:2", "novel episode two", 0.6),
        fact or _fact_row(),
    ]
    return {"evaluations": [_evaluation("q1", rows, score=None)]}


def _turn_index() -> list[dict[str, dict[str, str]]]:
    return [
        {
            "d1": {
                "speaker": "A",
                "text": "critical gold sentence",
                "timestamp": "2024-01-01",
                "envelope": "[A 2024-01-01] critical gold sentence",
            }
        }
    ]


def _source_contract() -> dict[str, Any]:
    return {
        "baseline_answerer_model": "gpt-4o",
        "baseline_judge_model": "gpt-4o",
        "fact_extractor_model": "gpt-4o",
        "provider": "openai",
        "historical_extraction_provider_calls": 7,
        "historical_validated_fact_items": 3,
        "replay_provider_calls": 0,
    }


def _run(
    auxiliary: dict[str, Any] | None = None,
    **kwargs: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    return run_replay(
        _baseline_payload(),
        auxiliary or _auxiliary_payload(),
        _turn_index(),
        _FakePrompts(),
        source_contract=_source_contract(),
        categories=frozenset({1}),
        conversations=frozenset({0}),
        expected_questions=1,
        cutoff=200,
        token_counter=lambda value: len(value.split()),
        **kwargs,
    )


def test_fact_free_pack_retains_the_miss_gain_without_serving_any_fact() -> None:
    candidate, report = _run()

    assert report["gate_passed"] is True
    assert report["evidence"] == {
        "misses": 1,
        "sentinels": 0,
        "miss_gold_gained": 1,
        "miss_gold_lost": 0,
        "sentinel_gold_gained": 0,
        "sentinel_gold_lost": 0,
    }
    assert report["totals"]["questions_with_pack"] == 1
    assert report["totals"]["total_fact_items"] == 0
    assert report["totals"]["logical_preservation_failures"] == 0
    assert report["totals"]["physical_row_count_failures"] == 0
    assert report["gates"]["no_fact_items"] is True
    assert report["gates"]["miss_gold_gain"] is True
    assert candidate["metadata"]["provider_calls"] == 0

    # The tail is a fact-free RAW pack that never carries the fact or its source.
    rows = candidate["evaluations"][0]["retrieval"]["search_results"]
    items = parse_raw_pack_items(rows[-1])
    assert items is not None
    scopes = [item.scope for item in items]
    assert scopes[0] == "raw_protected"
    assert set(scopes[1:]) == {"raw_episode"}
    assert all("SEAM-FACT/1" not in item.memory for item in items)
    # The episode ids match exactly what the fact-bearing selection chose.
    episode_ids = [item.record_id for item in items if item.scope == "raw_episode"]
    assert episode_ids == ["raw:episode:1", "raw:episode:2"]


def test_pack_is_absent_when_the_fact_selection_had_no_episode() -> None:
    # A fact PACK with only a source (no novel episode) leaves the fact-free
    # candidate at baseline RAW, so no episode gain is possible.
    auxiliary = {
        "evaluations": [
            _evaluation(
                "q1",
                [_raw_row("raw:source:1", "unrelated source clause", 0.9), _fact_row()],
                score=None,
            )
        ]
    }
    _, report = _run(auxiliary)

    assert report["totals"]["questions_with_pack"] == 0
    assert report["totals"]["total_auxiliary_raw_items"] == 0
    assert report["gates"]["no_fact_items"] is True
    # No episode reached the context, so the miss gain gate fails: the fact-free
    # pack cannot invent evidence.
    assert report["gates"]["miss_gold_gain"] is False
    assert report["gate_passed"] is False


def test_prompt_headroom_failure_blocks_the_replay_gate() -> None:
    _, report = _run(context_window=1, output_reserve=0)

    assert report["prompt"]["fits_context"] is False
    assert report["gates"]["prompt_fits_gpt4o_context"] is False
    assert report["gate_passed"] is False


@pytest.mark.parametrize("failure", ["missing", "duplicate"])
def test_candidate_builder_rejects_inexact_or_duplicate_auxiliary_coverage(
    failure: str,
) -> None:
    auxiliary = _auxiliary_payload()
    if failure == "missing":
        auxiliary["evaluations"] = []
        match = "coverage mismatch"
    else:
        auxiliary["evaluations"].append(copy.deepcopy(auxiliary["evaluations"][0]))
        match = "duplicate question_id"

    with pytest.raises(ValueError, match=match):
        build_candidate_payload(
            _baseline_payload(),
            auxiliary,
            categories=frozenset({1}),
            conversations=frozenset({0}),
            expected_questions=1,
        )


def test_replay_contract_is_zero_provider_and_cases_are_numeric_only() -> None:
    candidate, report = _run()

    assert candidate["metadata"]["provider_calls"] == 0
    assert report["dry_run"] is True
    assert report["paid_provider_calls"] == 0
    assert report["gates"]["zero_replay_provider_calls"] is True

    forbidden_fragments = {"memory", "question", "answer", "evidence", "text"}
    for case in report["cases"]:
        assert set(case) == {
            "question_id",
            "category",
            "was_correct",
            "gold_present_baseline",
            "gold_present_candidate",
            "gold_delta",
            "baseline_physical_rows",
            "candidate_physical_rows",
            "physical_row_count_stable",
            "logical_raw_rows",
            "logical_raw_prefix_exact",
            "pack_rows",
            "fact_items",
            "auxiliary_raw_items",
            "pack_chars",
        }
        assert not any(
            fragment in key
            for key in case
            if key != "question_id"
            for fragment in forbidden_fragments
        )
        assert isinstance(case["question_id"], str)
        assert all(
            isinstance(value, (bool, int))
            for key, value in case.items()
            if key != "question_id"
        )
