from __future__ import annotations

from benchmarks.external.mem0_harness.preflight_graph_memory import (
    MATCHED_CONTEXT_BUDGET,
    MATCHED_SEARCH_TOP_K,
    compose_graph_rows,
    compose_reserved_graph_rows,
    measure_case,
    summarize_cases,
)


def test_graph_preflight_pins_the_frozen_broad_gpt4o_profile() -> None:
    assert MATCHED_SEARCH_TOP_K == 300
    assert MATCHED_CONTEXT_BUDGET == 60000


def _row(memory: str) -> dict[str, str]:
    return {"memory": memory, "id": memory}


def test_reserved_graph_composition_displaces_only_rows_actually_added() -> None:
    baseline = [_row(value) for value in ("a", "b", "c", "d", "e")]
    candidate, unique = compose_reserved_graph_rows(
        baseline,
        [_row("a"), _row("z")],
        limit=5,
        graph_slots=2,
    )
    assert [row["memory"] for row in unique] == ["z"]
    assert [row["memory"] for row in candidate] == ["a", "b", "c", "d", "z"]


def test_fill_only_graph_composition_never_displaces_baseline_rows() -> None:
    baseline = [_row(value) for value in ("a", "b", "c")]
    candidate, unique = compose_graph_rows(
        baseline,
        [_row("z"), _row("y")],
        limit=4,
        graph_slots=2,
        composition="fill-only",
    )
    assert [row["memory"] for row in unique] == ["z"]
    assert [row["memory"] for row in candidate] == ["a", "b", "c", "z"]


def test_graph_preflight_counts_exact_gains_and_displacement_without_text() -> None:
    gained = measure_case(
        question_id="conv0_q1",
        category=1,
        envelopes=["gold-a", "gold-b"],
        baseline=[_row("gold-a"), _row("noise")],
        graph_rows=[_row("gold-b")],
        top_k=2,
        graph_slots=1,
    )
    lost = measure_case(
        question_id="conv0_q2",
        category=3,
        envelopes=["gold-c"],
        baseline=[_row("noise"), _row("gold-c")],
        graph_rows=[_row("new-noise")],
        top_k=2,
        graph_slots=1,
    )
    summary = summarize_cases([gained, lost], unresolved_refs=0)

    assert gained["gained_refs"] == 1
    assert gained["gained_all"] is True
    assert lost["lost_refs"] == 1
    assert lost["lost_any"] is True
    assert summary["gained_refs"] == 1
    assert summary["lost_refs"] == 1
    assert summary["gate"]["passed"] is False
    assert "gold-a" not in repr(gained)
    assert "gold-c" not in repr(lost)
