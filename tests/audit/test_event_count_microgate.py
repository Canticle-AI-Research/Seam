"""Hermetic tests for the event-count microgate (no provider calls)."""

from __future__ import annotations

import json

import pytest

from benchmarks.external.mem0_harness.microgate_event_count_context import (
    candidate_results,
    format_search_results,
    load_harness_prompts,
    run_microgate,
    select_cases,
)
from seam_runtime.event_count_context import EVENT_COUNT_DISTINCT_V2

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
    def evaluation(question_id, category, question, score, memories):
        return {
            "question_id": question_id,
            "category": category,
            "question": question,
            "ground_truth_answer": "4",
            "reference_date": "May 20, 2023",
            "retrieval": {
                "search_results": [
                    {"id": f"m{i}", "memory": text, "score": 1.0 - i * 0.1}
                    for i, text in enumerate(memories)
                ]
            },
            "cutoff_results": {"top_200": {"score": score}},
        }

    return {
        "evaluations": [
            evaluation(
                "q-count-miss", 1, "How many times did Melanie go camping?", 0.0,
                ["Melanie went camping in May.", "Melanie plans to go camping."],
            ),
            # excluded: correct already
            evaluation(
                "q-count-hit", 1, "How many pets does Sam have?", 1.0,
                ["Sam has two pets."],
            ),
            # excluded: not a count question
            evaluation(
                "q-not-count", 1, "Where did Melanie go camping?", 0.0,
                ["Melanie went camping in May."],
            ),
            # excluded: wrong category
            evaluation(
                "q-cat3", 3, "How many moons does Mars have?", 0.0,
                ["Mars talk."],
            ),
        ]
    }


def test_select_cases_matches_preflight_predicate():
    ids = [e["question_id"] for e in select_cases(_payload())]
    assert ids == ["q-count-miss"]


def test_candidate_results_prepends_projection():
    stored = _payload()["evaluations"][0]["retrieval"]["search_results"]
    projected = candidate_results(stored, "How many times did Melanie go camping?")
    assert projected[0]["id"].startswith("seam-count:")
    assert "SEAM-COUNT/1" in projected[0]["memory"]
    # retained rows keep provenance ids from the stored results
    retained_ids = {row["id"] for row in projected[1:]}
    assert retained_ids <= {row["id"] for row in stored}


def test_candidate_results_default_policy_is_v1():
    stored = _payload()["evaluations"][0]["retrieval"]["search_results"]
    projected = candidate_results(stored, "How many times did Melanie go camping?")
    assert "SEAM-COUNT/1" in projected[0]["memory"]


def test_candidate_results_accepts_v2_policy():
    stored = _payload()["evaluations"][0]["retrieval"]["search_results"]
    projected = candidate_results(
        stored, "How many times did Melanie go camping?", policy=EVENT_COUNT_DISTINCT_V2
    )
    assert projected[0]["id"].startswith("seam-count:")
    assert "SEAM-COUNT/2" in projected[0]["memory"]


def test_run_microgate_threads_selected_policy_into_candidate_arm(tmp_path):
    prompts_dir = tmp_path / "benchmarks" / "locomo"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "prompts.py").write_text(_FAKE_PROMPTS, encoding="utf-8")
    prompts = load_harness_prompts(tmp_path)

    def fake_call(model, system, user, *, json_mode):
        if json_mode:
            label = "CORRECT" if "SEAM-COUNT/2" in user else "WRONG"
            return json.dumps({"label": label, "reasoning": "test"})
        return f"ANSWER: {'SEAM-COUNT/2' if 'SEAM-COUNT/2' in user else 'plain'}"

    report = run_microgate(
        _payload(), prompts, fake_call, policy=EVENT_COUNT_DISTINCT_V2
    )
    assert report["policy"] == EVENT_COUNT_DISTINCT_V2
    assert report["candidate_correct"] == 1
    assert "SEAM-COUNT/1" not in report["cases"][0]["candidate"]["generated_answer"]


def test_format_search_results_sorts_score_desc_and_keeps_keys():
    rows = format_search_results(
        [
            {"id": "a", "memory": "low", "score": 0.1},
            {"id": "b", "memory": "high", "score": 0.9, "created_at": "2023-05-01"},
        ]
    )
    assert [row["id"] for row in rows] == ["b", "a"]
    assert rows[0]["created_at"] == "2023-05-01"
    assert "created_at" not in rows[1]


def test_run_microgate_flip_accounting(tmp_path):
    prompts_dir = tmp_path / "benchmarks" / "locomo"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "prompts.py").write_text(_FAKE_PROMPTS, encoding="utf-8")
    prompts = load_harness_prompts(tmp_path)

    calls = []

    def fake_call(model, system, user, *, json_mode):
        calls.append({"json_mode": json_mode, "user": user})
        if json_mode:
            # judge: candidate arm sees the projection header in its answer echo
            label = "CORRECT" if "SEAM-COUNT/1" in user else "WRONG"
            return json.dumps({"label": label, "reasoning": "test"})
        # answerer: echo whether the projection was present in context
        return f"ANSWER: {'SEAM-COUNT/1' if 'SEAM-COUNT/1' in user else 'plain'}"

    report = run_microgate(_payload(), prompts, fake_call)
    assert report["selected_cases"] == 1
    assert report["baseline_rerun_correct"] == 0
    assert report["candidate_correct"] == 1
    assert report["net_candidate_minus_baseline"] == 1
    case = report["cases"][0]
    assert case["projection_applied"] is True
    assert case["baseline"]["label"] == "WRONG"
    assert case["candidate"]["label"] == "CORRECT"
    # two arms x (answer + judge)
    assert len(calls) == 4


def test_load_harness_prompts_missing_path(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_harness_prompts(tmp_path / "nope")
