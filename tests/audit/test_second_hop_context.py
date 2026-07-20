"""Hermetic tests for the entity-bridge second-hop lever (HISTORY#429 autopsy).

Separate file from test_seam_mem0_server.py on purpose: that module has
in-flight concurrent edits by another agent.
"""

from __future__ import annotations

import os
from unittest import mock

from seam_runtime.second_hop_context import (
    POLICY_V1,
    build_bridge_plan,
    extract_bridge_terms,
    splice_results,
)

PRIMARY_TEXTS = [
    "[Tim 2023-05-08] I love playing Star Wars tunes on the piano after work.",
    '[Tim 2023-05-20] Just finished reading "The Alchemist" and loved it.',
    "[John 2023-06-01] my ankle is feeling better after physio.",
    "[Tim 2023-06-11] I keep humming those Star Wars melodies while collecting props.",
]


def test_extract_prefers_recurrent_entities_and_quoted_titles() -> None:
    terms = extract_bridge_terms(
        "Which popular music composer's tunes does Tim enjoy playing?",
        PRIMARY_TEXTS,
    )
    assert terms, "expected bridge terms"
    assert terms[0] == "Star Wars"  # appears in two distinct results
    assert "The Alchemist" in terms


def test_extract_skips_terms_already_in_query_and_speaker_prefixes() -> None:
    terms = extract_bridge_terms(
        "What does Tim think of Star Wars?", PRIMARY_TEXTS
    )
    assert "Star Wars" not in terms
    assert all("Tim" != t for t in terms)  # bracket speakers are not evidence


def test_plan_off_policy_and_empty_inputs_return_none() -> None:
    assert build_bridge_plan("q", PRIMARY_TEXTS) is None
    assert build_bridge_plan("q", PRIMARY_TEXTS, policy="weird/2") is None
    assert build_bridge_plan("q", [], policy=POLICY_V1) is None
    assert build_bridge_plan("what is on", ["all lowercase text only"], policy=POLICY_V1) is None


def test_splice_keeps_primary_head_and_fills_tail_with_novel() -> None:
    primary = [
        {"id": f"p{i}", "memory": f"m{i}", "score": 1.0 - i * 0.01} for i in range(10)
    ]
    secondary = [
        {"id": "p3", "memory": "dup", "score": 0.5},   # duplicate: dropped
        {"id": "s1", "memory": "bridge hit", "score": 0.9},
        {"id": "s2", "memory": "bridge hit 2", "score": 0.8},
    ]
    merged = splice_results(primary, secondary, limit=10, reserve_slots=2)
    assert len(merged) == 10
    assert [m["id"] for m in merged[:8]] == [f"p{i}" for i in range(8)]
    assert {m["id"] for m in merged[8:]} == {"s1", "s2"}
    # Novel scores sit below the primary floor so harness re-sort keeps order.
    floor = min(float(p["score"]) for p in primary)
    assert all(float(m["score"]) < floor for m in merged[8:])


def test_splice_backfills_tail_when_few_novel_results() -> None:
    primary = [
        {"id": f"p{i}", "memory": f"m{i}", "score": 1.0 - i * 0.01} for i in range(10)
    ]
    merged = splice_results(
        primary, [{"id": "s1", "memory": "x", "score": 0.9}], limit=10, reserve_slots=4
    )
    assert len(merged) == 10
    assert [m["id"] for m in merged[:9]] == [f"p{i}" for i in range(9)]
    assert merged[9]["id"] == "s1"


def test_splice_empty_secondary_is_identity() -> None:
    primary = [{"id": "p0", "memory": "m", "score": 1.0}]
    assert splice_results(primary, [], limit=200, reserve_slots=40) is primary


def test_facade_off_path_is_byte_identical() -> None:
    from benchmarks.external.mem0_harness.seam_mem0_server import SeamMem0Server

    class _Stub(SeamMem0Server):
        def __init__(self):  # no adapter construction
            pass

        def _search_raw(self, user_id, query, limit):
            raise AssertionError("no secondary search may run when policy is off")

    stub = _Stub()
    primary = [{"id": "p0", "memory": "[A 2023-01-01] Star Wars night", "score": 1.0}]
    with mock.patch.dict(os.environ, {}, clear=False):
        os.environ.pop("SEAM_SECOND_HOP_POLICY", None)
        assert stub._apply_second_hop_policy("u", "when?", primary, 200) is primary


def test_facade_on_path_runs_bridge_queries_and_splices() -> None:
    from benchmarks.external.mem0_harness.seam_mem0_server import SeamMem0Server

    calls: list[str] = []

    class _Stub(SeamMem0Server):
        def __init__(self):
            pass

        def _search_raw(self, user_id, query, limit):
            calls.append(query)
            return [{"id": f"s-{query}", "memory": f"hit for {query}", "score": 0.9}]

    stub = _Stub()
    primary = [
        {"id": f"p{i}", "memory": t, "score": 1.0 - i * 0.1}
        for i, t in enumerate(PRIMARY_TEXTS)
    ]
    with mock.patch.dict(os.environ, {"SEAM_SECOND_HOP_POLICY": POLICY_V1}):
        merged = stub._apply_second_hop_policy(
            "u", "Which composer's tunes does Tim enjoy?", primary, 6
        )
    assert calls, "expected secondary searches"
    assert any(q == "Star Wars" for q in calls)
    assert len(merged) <= 6
    assert any(str(m["id"]).startswith("s-") for m in merged)
