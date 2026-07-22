"""Hermetic tests for the zero-provider non-displacing PACK replay."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from benchmarks.external.mem0_harness.preflight_non_displacing_pack import (
    audit_prompt_headroom,
    build_candidate_payload,
    run_replay,
    validate_candidate_output_path,
    validate_gpt4o_source_contract,
)


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
    return {
        "id": record_id,
        "memory": memory,
        "score": score,
    }


def _fact_row(
    *,
    claim_id: str = "clm:fact:1",
    source_raw_id: str = "raw:source:1",
    source_text: str = "critical gold sentence",
) -> dict[str, Any]:
    fact = {
        "claim_id": claim_id,
        "object": "critical gold sentence",
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


def _auxiliary_payload(
    *,
    fact: dict[str, Any] | None = None,
    include_source: bool = True,
) -> dict[str, Any]:
    source = _raw_row("raw:source:1", "critical gold sentence", 0.9)
    rows = [source] if include_source else []
    rows.extend(
        [
            _raw_row("raw:episode:1", "novel episode one", 0.7),
            _raw_row("raw:episode:2", "novel episode two", 0.6),
            fact or _fact_row(),
        ]
    )
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


def test_clean_replay_gains_one_miss_without_loss_and_preserves_source_order() -> None:
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
    assert report["totals"]["total_source_raw_items"] == 1
    assert report["totals"]["total_fact_items"] == 1
    assert report["totals"]["source_order_failures"] == 0
    assert report["totals"]["logical_preservation_failures"] == 0
    assert report["totals"]["physical_row_count_failures"] == 0
    assert candidate["metadata"]["provider_calls"] == 0


@pytest.mark.parametrize("failure", ["missing", "duplicate"])
def test_candidate_builder_rejects_inexact_or_duplicate_auxiliary_coverage(
    failure: str,
) -> None:
    auxiliary = _auxiliary_payload()
    if failure == "missing":
        auxiliary["evaluations"] = []
        match = "coverage mismatch"
    else:
        auxiliary["evaluations"].append(
            copy.deepcopy(auxiliary["evaluations"][0])
        )
        match = "duplicate question_id"

    with pytest.raises(ValueError, match=match):
        build_candidate_payload(
            _baseline_payload(),
            auxiliary,
            categories=frozenset({1}),
            conversations=frozenset({0}),
            expected_questions=1,
        )


def test_gpt4o_source_contract_accepts_cloud_and_rejects_local_extraction() -> None:
    source_config = {
        "config": {
            "policy": "multi-speaker-grounded/1",
            "extractor": {
                "type": "openai-multi-speaker-grounded-probe",
                "provider": "openai",
                "model": "gpt-4o",
            },
        }
    }
    extraction_stats = {
        "provider_calls": 7,
        "validated_fact_items": 3,
        "derived_facts_policy": "multi-speaker-grounded/1",
    }

    contract = validate_gpt4o_source_contract(
        _baseline_payload(), source_config, extraction_stats
    )
    assert contract["fact_extractor_model"] == "gpt-4o"
    assert contract["replay_provider_calls"] == 0

    local_config = copy.deepcopy(source_config)
    local_config["config"]["extractor"].update(
        {
            "type": "ollama-multi-speaker-grounded",
            "provider": "ollama",
            "model": "qwen2.5:7b",
        }
    )
    with pytest.raises(ValueError, match="GPT-4o source contract mismatch"):
        validate_gpt4o_source_contract(
            _baseline_payload(), local_config, extraction_stats
        )


def test_prompt_headroom_failure_blocks_the_replay_gate() -> None:
    _, report = _run(context_window=1, output_reserve=0)

    assert report["prompt"]["fits_context"] is False
    assert report["prompt"]["headroom_tokens"] < 0
    assert report["gates"]["prompt_fits_gpt4o_context"] is False
    assert report["gate_passed"] is False


@pytest.mark.parametrize("failure", ["missing-source", "malformed-fact"])
def test_missing_or_malformed_fact_source_fails_closed(failure: str) -> None:
    if failure == "missing-source":
        auxiliary = _auxiliary_payload(include_source=False)
    else:
        malformed = _raw_row("clm:fact:1", "SEAM-FACT/1|not-json", 0.8)
        auxiliary = _auxiliary_payload(fact=malformed)

    _, report = _run(auxiliary)

    assert report["gate_passed"] is False
    assert report["gates"]["one_pack_per_question"] is False
    assert report["gates"]["one_source_raw_per_question"] is False
    assert report["gates"]["source_before_fact"] is False


def test_replay_contract_is_zero_provider_and_cases_are_numeric_only() -> None:
    candidate, report = _run()

    assert candidate["metadata"]["provider_calls"] == 0
    assert report["dry_run"] is True
    assert report["paid_provider_calls"] == 0
    assert report["contract"]["replay_provider_calls"] == 0
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
            "source_raw_items",
            "auxiliary_raw_items",
            "source_before_fact",
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


def test_prompt_audit_reports_exact_budget_boundary() -> None:
    baseline = _baseline_payload()["evaluations"]
    candidate = build_candidate_payload(
        _baseline_payload(),
        _auxiliary_payload(),
        categories=frozenset({1}),
        conversations=frozenset({0}),
        expected_questions=1,
    )["evaluations"]

    prompt = audit_prompt_headroom(
        baseline,
        candidate,
        _FakePrompts(),
        context_window=100,
        output_reserve=20,
        token_counter=lambda _value: 80,
    )

    assert prompt["max_candidate_prompt_tokens"] == 80
    assert prompt["headroom_tokens"] == 0
    assert prompt["fits_context"] is True


def test_licensed_candidate_output_must_stay_outside_repository(
    tmp_path: Path,
) -> None:
    repo_candidate = Path(__file__).resolve().parents[2] / "licensed-candidate.json"
    with pytest.raises(ValueError, match="outside the repository"):
        validate_candidate_output_path(repo_candidate)

    external_candidate = tmp_path / "licensed-candidate.json"
    assert validate_candidate_output_path(external_candidate) == external_candidate
