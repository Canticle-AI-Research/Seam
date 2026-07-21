from __future__ import annotations

from types import SimpleNamespace

import pytest

from benchmarks.external.mem0_harness.preflight_multi_scope_pack import (
    direct_evidence_state,
    is_multi_scope_pack,
    measure_case,
)
from benchmarks.external.mem0_harness.seam_mem0_server import SeamMem0Server
from seam_runtime.multi_scope_pack import (
    POLICY_V1,
    ScopeQuotas,
    compose_reserved_multi_scope,
    pack_scope_counts,
    select_date_diverse_rows,
)


def _row(record_id: str, memory: str, score: float = 0.5) -> dict:
    return {
        "id": record_id,
        "memory": memory,
        "score": score,
        "created_at": "",
    }


def test_off_policy_is_exact_object_identity():
    baseline = [_row("raw:1", "[A 2024-01-01] one")]
    assert compose_reserved_multi_scope(
        baseline,
        {"raw_episode": [_row("raw:2", "[A 2024-01-02] two")]},
        limit=10,
    ) is baseline


def test_pack_preserves_displaced_raw_verbatim_and_enforces_scope_quotas():
    baseline = [
        _row("raw:1", "[A 2024-01-01] first", 0.9),
        _row("raw:2", "[A 2024-01-02] protected tail", 0.8),
    ]
    lanes = {
        "grounded_fact": [
            _row("clm:1", "SEAM-FACT/1|fact one"),
            _row("clm:2", "SEAM-FACT/1|fact two"),
        ],
        "entity_relation": [_row("raw:3", "[B 2024-01-03] graph evidence")],
        "temporal": [_row("raw:4", "[C 2024-01-04] temporal evidence")],
        "raw_episode": [_row("raw:5", "[D 2024-01-05] deep episode")],
    }

    composed = compose_reserved_multi_scope(
        baseline,
        lanes,
        limit=2,
        policy=POLICY_V1,
        quotas=ScopeQuotas(
            grounded_fact=1,
            entity_relation=1,
            temporal=1,
            raw_episode=1,
        ),
    )

    assert len(composed) == 2
    assert composed[0] is baseline[0]
    pack = composed[-1]
    assert str(pack["id"]).startswith("seam-multiscope-1-")
    assert str(pack["memory"]).startswith("SEAM-MULTISCOPE/1|")
    for exact_memory in (
        baseline[-1]["memory"],
        lanes["grounded_fact"][0]["memory"],
        lanes["entity_relation"][0]["memory"],
        lanes["temporal"][0]["memory"],
        lanes["raw_episode"][0]["memory"],
    ):
        assert exact_memory in pack["memory"]
    assert lanes["grounded_fact"][1]["memory"] not in pack["memory"]
    assert pack_scope_counts(pack) == {
        "raw_protected": 1,
        "grounded_fact": 1,
        "entity_relation": 1,
        "temporal": 1,
        "raw_episode": 1,
    }


def test_pack_deduplicates_content_and_respects_character_cap():
    baseline = [_row("raw:1", "[A 2024-01-01] existing")]
    duplicate = _row("raw:duplicate", baseline[0]["memory"])
    novel = _row("raw:2", "[A 2024-01-02] novel")

    assert compose_reserved_multi_scope(
        baseline,
        {"raw_episode": [duplicate]},
        limit=1,
        policy=POLICY_V1,
    ) is baseline
    assert compose_reserved_multi_scope(
        baseline,
        {"raw_episode": [novel]},
        limit=1,
        policy=POLICY_V1,
        max_pack_chars=10,
    ) == baseline


def test_zero_scope_quota_admits_no_rows_and_none_score_defaults_to_zero():
    baseline = [_row("raw:1", "[A 2024-01-01] protected")]
    baseline[0]["score"] = None
    composed = compose_reserved_multi_scope(
        baseline,
        {
            "grounded_fact": [_row("fact:1", "SEAM-FACT/1|excluded")],
            "raw_episode": [_row("raw:2", "[A 2024-01-02] included")],
        },
        limit=1,
        policy=POLICY_V1,
        quotas=ScopeQuotas(
            grounded_fact=0,
            entity_relation=0,
            temporal=0,
            raw_episode=1,
        ),
    )

    assert composed[0]["score"] == 0.0
    assert "SEAM-FACT/1|excluded" not in composed[0]["memory"]
    assert "[A 2024-01-02] included" in composed[0]["memory"]


def test_date_diverse_rows_prefers_distinct_dates_then_backfills():
    rows = [
        _row("raw:1", "[A 2024-01-01] one"),
        _row("raw:2", "[A 2024-01-01] two"),
        _row("raw:3", "[A 2024-01-02] three"),
        _row("raw:4", "undated"),
    ]
    selected = select_date_diverse_rows(rows, limit=3)
    assert [row["id"] for row in selected] == ["raw:1", "raw:3", "raw:2"]


def test_facade_rejects_unknown_multi_scope_policy_before_opening_store(tmp_path):
    target = tmp_path / "unused"
    with pytest.raises(ValueError, match="unknown multi-scope pack policy"):
        SeamMem0Server(
            db_path=str(target),
            multi_scope_pack_policy="unknown",
        )
    assert not target.exists()


def test_facade_multi_scope_candidate_is_standalone_and_prefix_safe():
    primary = [_row("raw:1", "[A 2024-01-01] first")]
    deep = [*primary, _row("raw:2", "[A 2024-01-02] deeper")]
    server = SeamMem0Server.__new__(SeamMem0Server)
    server._multi_scope_pack_policy = POLICY_V1
    server._derived_facts_policy = "off"
    server._adapter = SimpleNamespace(_runtime=lambda user_id: object())
    server._search_raw = lambda user_id, query, limit: deep
    server._search_graph_raw = lambda user_id, query, limit: []
    server._apply_second_hop_policy = lambda *args: pytest.fail(
        "standalone multi-scope policy must not stack second-hop"
    )

    result = server._apply_multi_scope_pack_policy("user", "query", primary, 1)
    assert len(result) == 1
    assert primary[0]["memory"] in result[0]["memory"]
    assert deep[1]["memory"] in result[0]["memory"]

    server._search_raw = lambda user_id, query, limit: [deep[1], primary[0]]
    assert server._apply_multi_scope_pack_policy(
        "user", "query", primary, 1
    ) is primary


def test_preflight_counts_exact_evidence_inside_direct_read_pack():
    baseline = [_row("raw:1", "[A 2024-01-01] retained")]
    candidate = compose_reserved_multi_scope(
        baseline,
        {"raw_episode": [_row("raw:2", "[A 2024-01-02] gained")]},
        limit=1,
        policy=POLICY_V1,
    )
    state = direct_evidence_state(
        candidate,
        [baseline[0]["memory"], "[A 2024-01-02] gained"],
    )
    assert state["hits"] == 2
    measured = measure_case(
        question_id="q1",
        category=1,
        envelopes=[baseline[0]["memory"], "[A 2024-01-02] gained"],
        baseline=baseline,
        candidate=candidate,
    )
    assert measured["gained_refs"] == 1
    assert measured["lost_refs"] == 0
    assert measured["pack_rows"] == 1


def test_preflight_requires_pack_id_and_memory_prefix_for_all_metrics():
    id_only = _row("seam-multiscope-1-false", "ordinary RAW")
    memory_only = _row("raw:1", "SEAM-MULTISCOPE/1|not a validated pack")

    assert is_multi_scope_pack(id_only) is False
    assert is_multi_scope_pack(memory_only) is False
    measured = measure_case(
        question_id="q1",
        category=1,
        envelopes=["ordinary RAW"],
        baseline=[],
        candidate=[id_only, memory_only],
    )
    assert measured["candidate_hits"] == 1
    assert measured["pack_rows"] == 0
    assert measured["pack_chars"] == 0
