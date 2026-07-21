"""Hermetic tests for the answerer-parity probe (no provider calls)."""

from __future__ import annotations

import json
from unittest import mock

import pytest

from benchmarks.external.mem0_harness.parity_probe_answerer import (
    BASELINE_ANSWERER,
    JUDGE_MODEL,
    PARITY_ANSWERER,
    load_harness_prompts,
    run_probe,
    select_misses,
)

_FAKE_PROMPTS = '''
JUDGE_SYSTEM_PROMPT = "judge"


def get_answer_generation_prompt(question, search_results, reference_date=None, user_profile=None):
    memories = "\\n".join(r["memory"] for r in search_results)
    return f"{memories}\\nQ: {question}"


def preprocess_answer(category, answer):
    return answer


def get_judge_prompt(category, question, answer, response):
    return f"gold={answer} got={response}"
'''


def _payload() -> dict:
    def evaluation(question_id, category, score):
        return {
            "question_id": question_id,
            "category": category,
            "question": f"What about {question_id}?",
            "ground_truth_answer": "gold-item",
            "reference_date": "May 20, 2023",
            "retrieval": {
                "search_results": [
                    {"id": "m1", "memory": "some evidence", "score": 0.9}
                ]
            },
            "cutoff_results": {"top_200": {"score": score}},
        }

    return {
        "evaluations": [
            evaluation("q-cat1-miss", 1, 0.0),
            evaluation("q-cat1-hit", 1, 1.0),
            evaluation("q-cat3-miss", 3, 0.0),
            evaluation("q-cat2-miss", 2, 0.0),
        ]
    }


def test_select_misses_filters_score_and_category():
    ids = [e["question_id"] for e in select_misses(_payload(), {1})]
    assert ids == ["q-cat1-miss"]
    ids13 = [e["question_id"] for e in select_misses(_payload(), {1, 3})]
    assert ids13 == ["q-cat1-miss", "q-cat3-miss"]


def test_select_misses_skips_missing_or_non_numeric_scores():
    payload = _payload()
    payload["evaluations"].extend(
        [
            {"question_id": "missing", "category": 1, "cutoff_results": {"top_200": {}}},
            {
                "question_id": "string",
                "category": 1,
                "cutoff_results": {"top_200": {"score": "0"}},
            },
        ]
    )
    ids = [e["question_id"] for e in select_misses(payload, {1})]
    assert ids == ["q-cat1-miss"]


def test_select_misses_rejects_malformed_evaluations():
    with pytest.raises(ValueError, match="evaluations.*list"):
        select_misses({}, {1})


def test_run_probe_isolates_answerer_variable(tmp_path):
    prompts_dir = tmp_path / "benchmarks" / "locomo"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "prompts.py").write_text(_FAKE_PROMPTS, encoding="utf-8")
    with mock.patch(
        "benchmarks.external.mem0_harness.parity_probe_answerer._resolve_git_revision",
        side_effect=["full-audited-sha", "full-audited-sha"],
    ):
        prompts = load_harness_prompts(tmp_path)

    calls = []

    def fake_call(model, system, user, *, json_mode):
        calls.append((model, json_mode))
        if json_mode:
            assert model == JUDGE_MODEL
            label = "CORRECT" if "strong" in user else "WRONG"
            return json.dumps({"label": label, "reasoning": "test"})
        return "ANSWER: strong" if model == PARITY_ANSWERER else "ANSWER: weak"

    report = run_probe(_payload(), prompts, fake_call, {1})
    assert report["selected_miss_cases"] == 1
    assert report["baseline_rerun_correct"] == 0
    assert report["parity_correct"] == 1
    assert report["net_parity_minus_baseline"] == 1
    assert report["harness_revision"] == "full-audited-sha"
    assert report["per_category"] == {"1": {"cases": 1, "baseline": 0, "parity": 1}}
    # both arms answered, both judged by the same judge model
    # (PARITY_ANSWERER and JUDGE_MODEL may be the same model id, so
    # distinguish answer calls from judge calls by json_mode)
    assert calls.count((BASELINE_ANSWERER, False)) == 1
    assert calls.count((PARITY_ANSWERER, False)) == 1
    assert calls.count((JUDGE_MODEL, True)) == 2


def test_load_harness_prompts_missing_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_harness_prompts(tmp_path / "nope")


def test_load_harness_prompts_rejects_wrong_revision(tmp_path):
    prompts_dir = tmp_path / "benchmarks" / "locomo"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "prompts.py").write_text(_FAKE_PROMPTS, encoding="utf-8")
    with mock.patch(
        "benchmarks.external.mem0_harness.parity_probe_answerer._resolve_git_revision",
        side_effect=["actual-sha", "audited-sha"],
    ), pytest.raises(RuntimeError, match="revision mismatch"):
        load_harness_prompts(tmp_path)
