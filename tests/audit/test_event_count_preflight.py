"""No-provider tests for the stored-record count-context preflight."""

from __future__ import annotations

from benchmarks.external.mem0_harness.preflight_event_count_context import (
    summarize_record,
)


def _evaluation(*, question: str, score: float, category: int = 1) -> dict:
    return {
        "category": category,
        "question": question,
        "cutoff_results": {"top_200": {"score": score}},
        "retrieval": {
            "search_results": [
                {
                    "id": "raw:plan",
                    "memory": "[Nate 2023-03-03] I will enter next week's tournament.",
                    "score": 0.9,
                },
                {
                    "id": "raw:win",
                    "memory": "[Nate 2023-03-01] I won a tournament.",
                    "score": 0.7,
                },
            ]
        },
    }


def test_preflight_selects_only_failed_cat1_count_cases():
    report = summarize_record(
        {
            "evaluations": [
                _evaluation(
                    question="How many tournaments did Nate win?", score=0.0
                ),
                _evaluation(
                    question="Which tournament did Nate win?", score=0.0
                ),
                _evaluation(
                    question="How many tournaments did Nate win?", score=1.0
                ),
                _evaluation(
                    question="How many tournaments did Nate win?",
                    score=0.0,
                    category=3,
                ),
            ]
        }
    )

    assert report["dry_run"] is True
    assert report["provider_calls"] == 0
    assert report["selected_failed_cat1_count_cases"] == 1
    assert report["projected_cases"] == 1
    assert report["raw_candidates_preserved_in_projection"] == 2


def test_preflight_reports_projection_states_without_memory_text():
    report = summarize_record(
        {
            "evaluations": [
                _evaluation(
                    question="How many tournaments did Nate win?", score=0.0
                )
            ]
        }
    )

    assert report["state_counts"] == {"observed": 1, "planned": 1}
    serialized = str(report)
    assert "I won a tournament" not in serialized
    assert "next week's tournament" not in serialized


def test_preflight_distinguishes_selected_case_from_projected_case():
    evaluation = _evaluation(
        question="How many tournaments did Nate win?", score=0.0
    )
    evaluation["retrieval"]["search_results"] = []

    report = summarize_record({"evaluations": [evaluation]})

    assert report["selected_failed_cat1_count_cases"] == 1
    assert report["projected_cases"] == 0
