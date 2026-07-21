"""No-provider tests for the stored-record count-context preflight."""

from __future__ import annotations

from benchmarks.external.mem0_harness.preflight_event_count_context import (
    summarize_record,
)
from seam_runtime.event_count_context import EVENT_COUNT_DISTINCT_V2


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


def test_preflight_v2_reports_grouping_without_exposing_memory_text():
    evaluation = _evaluation(
        question="How many tournaments did Nate win?", score=0.0
    )
    evaluation["retrieval"]["search_results"] = [
        {
            "id": "raw:win",
            "memory": "[Nate 2023-03-01] I won a tournament.",
            "score": 0.9,
        },
        {
            "id": "raw:followup",
            "memory": "[Nate 2023-03-01] Winning that tournament felt great.",
            "score": 0.8,
        },
    ]

    report = summarize_record(
        {"evaluations": [evaluation]},
        policy=EVENT_COUNT_DISTINCT_V2,
    )

    assert report["policy"] == EVENT_COUNT_DISTINCT_V2
    assert report["event_groups"] == 1
    assert report["direct_match_groups"] == 1
    assert report["multi_member_groups"] == 1
    assert report["grouped_member_savings"] == 1
    assert "Winning that tournament" not in str(report)
