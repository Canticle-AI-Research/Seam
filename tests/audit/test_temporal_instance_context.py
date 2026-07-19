"""Hermetic tests for the SEAM-TEMPORAL/1 projection (HISTORY#426 cat2 lever).

Separate file from test_seam_mem0_server.py on purpose: that module has
in-flight concurrent edits by another agent.
"""

from __future__ import annotations

import os
from unittest import mock

from seam_runtime.temporal_instance_context import (
    POLICY_V1,
    TemporalEvidence,
    build_temporal_context_projection,
    is_temporal_question,
)


def _ev(rank: int, text: str) -> TemporalEvidence:
    return TemporalEvidence(record_id=f"r{rank}", text=text, score=1.0 / rank, original_rank=rank)


TURNS = [
    _ev(1, "[Caroline 2023-05-08] I went to a LGBTQ support group yesterday and it was so powerful."),
    _ev(2, "[Melanie 2023-10-21] Just got back from a charity race for mental health!"),
    _ev(3, "[Caroline 2023-07-06] We had a picnic last week and the kids loved it."),
    _ev(4, "[Melanie 2023-10-21] Thinking about running another race next year."),
]


def test_off_policy_returns_none() -> None:
    assert build_temporal_context_projection("When did Caroline go?", TURNS) is None
    assert build_temporal_context_projection("When did Caroline go?", TURNS, policy="unknown/9") is None


def test_non_temporal_question_returns_none() -> None:
    assert build_temporal_context_projection("What sports does John like?", TURNS, policy=POLICY_V1) is None


def test_single_date_returns_none() -> None:
    single = [TURNS[1], TURNS[3]]  # both 2023-10-21
    assert build_temporal_context_projection("When did Melanie run the race?", single, policy=POLICY_V1) is None


def test_projection_groups_by_session_date_and_flags_relative_wording() -> None:
    projection = build_temporal_context_projection(
        "When did Caroline go to the LGBTQ support group?", TURNS, policy=POLICY_V1
    )
    assert projection is not None
    rendered = projection.render()
    assert "2023-05-08:" in rendered and "2023-10-21:" in rendered and "2023-07-06:" in rendered
    assert "[relative: yesterday]" in rendered
    assert "[relative: last week]" in rendered
    assert "SEAM-TEMPORAL/1" in rendered
    assert projection.projection_id.startswith("seam-temporal-1-")


def test_undated_memories_do_not_crash_and_are_excluded_from_rows() -> None:
    mixed = TURNS + [_ev(9, "no bracket prefix at all")]
    projection = build_temporal_context_projection("When was the picnic?", mixed, policy=POLICY_V1)
    assert projection is not None
    assert len(projection.undated) == 1
    assert "no bracket prefix" not in projection.render()


def test_temporal_intent_detection() -> None:
    assert is_temporal_question("When did Melanie paint the sunrise?")
    assert is_temporal_question("How long ago did John adopt the dog?")
    assert is_temporal_question("What year did Joanna sell a screenplay?")
    assert not is_temporal_question("How many times did Dave attend car shows?")
    assert not is_temporal_question("What did Maria donate?")


def test_facade_off_path_is_byte_identical() -> None:
    from benchmarks.external.mem0_harness.seam_mem0_server import (
        _apply_temporal_context_policy,
    )

    results = [
        {"memory": t.text, "score": t.score, "id": t.record_id, "created_at": ""}
        for t in TURNS
    ]
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SEAM_TEMPORAL_CONTEXT_POLICY", None)
        assert _apply_temporal_context_policy("When did Caroline go?", results, 200) is results


def test_facade_on_path_prepends_projection_within_limit() -> None:
    from benchmarks.external.mem0_harness.seam_mem0_server import (
        _apply_temporal_context_policy,
    )

    results = [
        {"memory": t.text, "score": t.score, "id": t.record_id, "created_at": ""}
        for t in TURNS
    ]
    with mock.patch.dict(os.environ, {"SEAM_TEMPORAL_CONTEXT_POLICY": POLICY_V1}):
        out = _apply_temporal_context_policy(
            "When did Caroline go to the LGBTQ support group?", results, 4
        )
    assert out is not results
    assert len(out) == 4  # projection + limit-1 retained
    assert out[0]["memory"].startswith("SEAM-TEMPORAL/1")
    assert out[0]["id"].startswith("seam-temporal-1-")
    assert out[1] == results[0]
