"""Hermetic tests for the tokenizer-true cost report (no provider calls)."""

from __future__ import annotations

import pytest

from benchmarks.external.common.cost_report import (
    encoding_for_model,
    report_for_artifact,
)


class _StubPrompts:
    JUDGE_SYSTEM_PROMPT = "judge system"

    @staticmethod
    def get_answer_generation_prompt(question, formatted, reference_date=None, user_profile=None):
        return f"Q:{question} CTX:{len(formatted)} items " + " ".join(
            m["memory"] for m in formatted
        )

    @staticmethod
    def preprocess_answer(category, answer):
        return answer

    @staticmethod
    def get_judge_prompt(category, question, gold, generated):
        return f"judge {question} gold={gold} gen={generated}"


def _artifact():
    return {
        "metadata": {"answerer_model": "gpt-4o", "judge_model": "gpt-4o"},
        "evaluations": [
            {
                "question_id": "q1",
                "category": 1,
                "question": "When did it happen?",
                "ground_truth_answer": "May 2023",
                "retrieval": {"search_results": [
                    {"memory": "[A 2023-05-08] something happened", "score": 0.9, "id": "r1"},
                    {"memory": "[B 2023-06-01] other thing", "score": 0.5, "id": "r2"},
                ]},
                "cutoff_results": {"top_200": {
                    "generated_answer": "It happened in May 2023.",
                    "judgment": "CORRECT", "score": 1.0, "reason": "matches gold",
                }},
            },
            {   # empty answer: must be excluded from the count
                "question_id": "q2",
                "category": 1,
                "question": "x",
                "ground_truth_answer": "y",
                "retrieval": {"search_results": []},
                "cutoff_results": {"top_200": {"generated_answer": "", "judgment": "WRONG"}},
            },
        ],
    }


def test_encoding_map_prefers_o200k_for_4o_family() -> None:
    assert encoding_for_model("gpt-4o") == "o200k_base"
    assert encoding_for_model("gpt-4o-mini-2026-01") == "o200k_base"
    assert encoding_for_model("gpt-4-turbo") == "cl100k_base"
    assert encoding_for_model("gpt-5.4") == "o200k_base"


def test_report_counts_only_clean_cases_and_prices_them() -> None:
    report = report_for_artifact(
        _artifact(), _StubPrompts, answerer_model="gpt-4o", judge_model="gpt-4o"
    )
    assert report["cases_counted"] == 1
    ans = report["roles"]["answerer"]
    judge = report["roles"]["judge"]
    assert ans["prompt_tokens"] > 0 and ans["completion_tokens"] > 0
    assert judge["prompt_tokens"] > 0 and judge["completion_tokens"] > 0
    assert ans["cost_usd"] is not None and ans["cost_usd"] > 0
    assert report["single_pass_cost_usd"] > 0
    assert "LOWER BOUND" in report["caveat"]


def test_unpriced_model_yields_none_not_fabrication() -> None:
    report = report_for_artifact(
        _artifact(), _StubPrompts, answerer_model="totally-unknown-model", judge_model="gpt-4o"
    )
    assert report["roles"]["answerer"]["cost_usd"] is None
    assert report["single_pass_cost_usd"] is None
    assert report["unpriced_roles"] == ["answerer"]


@pytest.mark.parametrize("evaluations", [None, {}, "invalid"])
def test_report_rejects_missing_or_non_list_evaluations(evaluations) -> None:
    with pytest.raises(ValueError, match="evaluations.*list"):
        report_for_artifact(
            {"evaluations": evaluations},
            _StubPrompts,
            answerer_model="gpt-4o",
            judge_model="gpt-4o",
        )
