"""Hermetic contracts for the paired canonical-graph microgate."""

from __future__ import annotations

import json

import pytest

from benchmarks.external.mem0_harness.microgate_graph_memory import (
    _parse_question_id,
    _validate_sentinel_record,
    run_case_arm,
    summarize_results,
)


def test_question_id_parser_is_strict():
    assert _parse_question_id("conv3_q83") == (3, 83)
    with pytest.raises(ValueError, match="invalid LoCoMo"):
        _parse_question_id("3:83")


def test_sentinel_record_requires_frozen_gpt4o_contract():
    payload = {
        "metadata": {
            "benchmark": "locomo",
            "answerer_model": "gpt-4o",
            "judge_model": "gpt-4o",
            "top_k": 200,
            "categories": [1, 3],
        },
        "evaluations": [
            {
                "question_id": "conv1_q2",
                "cutoff_results": {"top_200": {"score": 1.0}},
            }
        ],
    }
    assert _validate_sentinel_record(payload) == {"conv1_q2"}
    payload["metadata"]["answerer_model"] = "gpt-4o-mini"
    with pytest.raises(ValueError, match="contract mismatch"):
        _validate_sentinel_record(payload)


def test_summary_requires_net_two_and_zero_sentinel_losses():
    cases = [
        {
            "role": "gain",
            "baseline_result": {"correct": False},
            "candidate_result": {"correct": True},
        },
        {
            "role": "gain",
            "baseline_result": {"correct": False},
            "candidate_result": {"correct": True},
        },
        {
            "role": "sentinel",
            "baseline_result": {"correct": True},
            "candidate_result": {"correct": True},
        },
    ]
    assert summarize_results(cases)["promotion_gate"]["passed"] is True
    cases[-1]["candidate_result"]["correct"] = False
    summary = summarize_results(cases)
    assert summary["sentinel_losses"] == 1
    assert summary["promotion_gate"]["passed"] is False


def test_run_case_arm_uses_evidence_aware_upstream_judge():
    class Prompts:
        JUDGE_SYSTEM_PROMPT = "judge-system"

        @staticmethod
        def get_answer_generation_prompt(*args, **kwargs):
            return "answer-prompt"

        @staticmethod
        def preprocess_answer(category, answer):
            return answer

        @staticmethod
        def get_judge_prompt_with_evidence(category, question, gold, response, evidence):
            assert evidence == "evidence-sentinel"
            return "judge-with-evidence"

    calls = []

    def call(model, system, user, *, json_mode):
        calls.append((system, user, json_mode))
        if json_mode:
            return json.dumps({"label": "CORRECT", "reasoning": "supported"})
        return "ANSWER: result"

    case = {
        "evaluation": {
            "category": 1,
            "question": "question",
            "ground_truth_answer": "gold",
            "reference_date": "date",
        },
        "evidence_context": "evidence-sentinel",
    }
    result = run_case_arm(Prompts, case, [], call)
    assert result["correct"] is True
    assert calls == [
        ("", "answer-prompt", False),
        ("judge-system", "judge-with-evidence", True),
    ]
