from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from benchmarks.external.mem0_harness.preflight_multi_scope_pack import (
    direct_evidence_state,
    is_multi_scope_pack,
    measure_case,
)
from benchmarks.external.mem0_harness.seam_mem0_server import SeamMem0Server
from seam_runtime.multi_scope_pack import (
    NON_DISPLACING_FACT_PACK_PREFIX,
    NON_DISPLACING_FACT_POLICY_V1,
    POLICIES,
    POLICY_V1,
    ScopeQuotas,
    compose_non_displacing_fact_pack,
    compose_reserved_multi_scope,
    expand_logical_raw_rows,
    pack_scope_counts,
    parse_pack_items,
    select_date_diverse_rows,
)


def _row(record_id: str, memory: str, score: float = 0.5) -> dict:
    return {
        "id": record_id,
        "memory": memory,
        "score": score,
        "created_at": "",
    }


def _fact_row(
    claim_id: str = "clm:fact:1",
    source_raw_id: str = "raw:source:1",
    source_text: str = "[A 2024-01-03] exact source evidence",
) -> dict:
    fact = {
        "claim_id": claim_id,
        "object": "surfing",
        "predicate": "likes",
        "source_raw_id": source_raw_id,
        "subject": "A",
    }
    source = {"id": source_raw_id, "raw": source_text}
    memory = (
        "SEAM-FACT/1|"
        + json.dumps(fact, sort_keys=True, separators=(",", ":"))
        + "\nSEAM-SOURCE/1|"
        + json.dumps(source, sort_keys=True, separators=(",", ":"))
    )
    return _row(claim_id, memory, 0.7)


def _fact_source_row(
    source_raw_id: str = "raw:source:1",
    source_text: str = "[A 2024-01-03] exact source evidence",
) -> dict:
    return _row(source_raw_id, source_text, 0.65)


def _resign_pack(row: dict, memory: str) -> dict:
    digest = hashlib.sha256(memory.encode()).hexdigest()[:16]
    return {
        **row,
        "id": f"seam-nondisplacing-fact-1-{digest}",
        "memory": memory,
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


def test_non_displacing_pack_preserves_logical_raw_sequence_and_timestamp():
    assert NON_DISPLACING_FACT_POLICY_V1 not in POLICIES
    baseline = [
        _row("raw:1", "[A 2024-01-01] first", 0.9),
        _row("raw:2", "[B 2024-01-02] protected tail", 0.8),
    ]
    baseline[-1]["created_at"] = "2024-01-02T12:00:00Z"
    delimiter_memory = (
        "[C 2024-01-03] body contains\nEND-ITEM\nITEM|not real metadata"
    )
    auxiliary = [
        _fact_source_row(),
        _row("raw:duplicate-text", "  [a 2024-01-01]   FIRST  "),
        _row("raw:3", delimiter_memory),
        _row("raw:4", "[D 2024-01-04] fourth"),
        _row("raw:5", "[E 2024-01-05] fifth"),
        _row("raw:6", "[F 2024-01-06] sixth"),
        _row("raw:7", "[G 2024-01-07] capped out"),
    ]

    composed = compose_non_displacing_fact_pack(
        baseline,
        auxiliary,
        [_fact_row(), _fact_row()],
        limit=2,
        policy=NON_DISPLACING_FACT_POLICY_V1,
        novel_raw_limit=4,
    )

    assert len(composed) == len(baseline)
    assert composed[0] is baseline[0]
    pack = composed[-1]
    assert pack["created_at"] == baseline[-1]["created_at"]
    assert str(pack["memory"]).startswith(f"{NON_DISPLACING_FACT_PACK_PREFIX}|")
    items = parse_pack_items(pack)
    assert items is not None
    assert [item.scope for item in items] == [
        "raw_protected",
        "raw_source",
        "raw_episode",
        "raw_episode",
        "raw_episode",
        "raw_episode",
        "grounded_fact",
    ]
    assert sum(item.scope == "grounded_fact" for item in items) == 1
    assert items[2].memory == delimiter_memory
    assert [row["id"] for row in expand_logical_raw_rows(composed)] == [
        "raw:1",
        "raw:2",
        "raw:source:1",
        "raw:3",
        "raw:4",
        "raw:5",
        "raw:6",
    ]
    assert [row["memory"] for row in expand_logical_raw_rows(composed)][:2] == [
        row["memory"] for row in baseline
    ]


def test_non_displacing_pack_caps_dedupes_and_fails_closed_on_char_cap():
    baseline = [_row("raw:1", "[A 2024-01-01] protected")]
    fact = _fact_row()
    auxiliary = [
        _fact_source_row(),
        _row("raw:2", "[B 2024-01-02] novel"),
        _row("raw:2", "[B 2024-01-02] duplicate id"),
        _row("raw:3", "[B 2024-01-02] novel"),
        _row("raw:4", "[C 2024-01-03] second novel"),
    ]

    composed = compose_non_displacing_fact_pack(
        baseline,
        auxiliary,
        [fact],
        limit=1,
        policy=NON_DISPLACING_FACT_POLICY_V1,
        novel_raw_limit=1,
    )
    items = parse_pack_items(composed[-1])
    assert items is not None
    assert [item.record_id for item in items if item.scope == "raw_episode"] == [
        "raw:2"
    ]

    assert (
        compose_non_displacing_fact_pack(
            baseline,
            auxiliary,
            [fact],
            limit=1,
            policy=NON_DISPLACING_FACT_POLICY_V1,
            fact_limit=0,
        )
        is baseline
    )
    assert (
        compose_non_displacing_fact_pack(
            baseline,
            auxiliary,
            [fact],
            limit=1,
            policy=NON_DISPLACING_FACT_POLICY_V1,
            max_pack_chars=1,
        )
        is baseline
    )
    with pytest.raises(ValueError, match="fact_limit"):
        compose_non_displacing_fact_pack(
            baseline,
            auxiliary,
            [fact],
            limit=1,
            policy=NON_DISPLACING_FACT_POLICY_V1,
            fact_limit=2,
        )
    with pytest.raises(ValueError, match="novel_raw_limit"):
        compose_non_displacing_fact_pack(
            baseline,
            auxiliary,
            [fact],
            limit=1,
            policy=NON_DISPLACING_FACT_POLICY_V1,
            novel_raw_limit=5,
        )


def test_non_displacing_pack_off_and_malformed_inputs_are_exact_fallbacks():
    baseline = [_row("raw:1", "[A 2024-01-01] protected")]
    valid_fact = _fact_row()
    assert (
        compose_non_displacing_fact_pack(
            baseline,
            [_row("raw:2", "[B 2024-01-02] novel")],
            [valid_fact],
            limit=1,
        )
        is baseline
    )

    malformed_fact = _row("clm:bad", "SEAM-FACT/1|not-json")
    malformed_raw = _row("not-raw", "ordinary text")
    for auxiliary, facts in (
        ([_row("raw:2", "[B 2024-01-02] novel")], [malformed_fact]),
        ([malformed_raw], [valid_fact]),
    ):
        assert (
            compose_non_displacing_fact_pack(
                baseline,
                auxiliary,
                facts,
                limit=1,
                policy=NON_DISPLACING_FACT_POLICY_V1,
            )
            is baseline
        )

    missing_tail = [_row("raw:1", "")]
    assert (
        compose_non_displacing_fact_pack(
            missing_tail,
            [],
            [valid_fact],
            limit=1,
            policy=NON_DISPLACING_FACT_POLICY_V1,
        )
        is missing_tail
    )

    for auxiliary in (
        [_row("raw:2", "[B 2024-01-02] novel")],
        [_fact_source_row(source_text="[A 2024-01-03] mismatched source")],
    ):
        assert (
            compose_non_displacing_fact_pack(
                baseline,
                auxiliary,
                [valid_fact],
                limit=1,
                policy=NON_DISPLACING_FACT_POLICY_V1,
            )
            is baseline
        )


def test_non_displacing_pack_parser_rejects_structural_corruption():
    baseline = [_row("raw:1", "[A 2024-01-01] protected")]
    valid = compose_non_displacing_fact_pack(
        baseline,
        [
            _fact_source_row(),
            _row("raw:2", "[B 2024-01-02] novel"),
        ],
        [_fact_row()],
        limit=1,
        policy=NON_DISPLACING_FACT_POLICY_V1,
    )[-1]
    memory = str(valid["memory"])

    truncated = _resign_pack(valid, memory.rsplit("\nEND-ITEM", 1)[0])
    unknown_scope = _resign_pack(
        valid,
        memory.replace('"scope":"raw_episode"', '"scope":"unknown"', 1),
    )
    duplicate_id = _resign_pack(
        valid,
        memory.replace(
            '"id":"raw:2","scope":"raw_episode"',
            '"id":"raw:1","scope":"raw_episode"',
            1,
        ),
    )
    missing_protected = _resign_pack(
        valid,
        memory.replace('"scope":"raw_protected"', '"scope":"raw_episode"', 1),
    )
    blocks = memory.split("\nITEM|")
    assert len(blocks) == 5
    source_after_fact = _resign_pack(
        valid,
        "\nITEM|".join([blocks[0], blocks[1], blocks[3], blocks[4], blocks[2]]),
    )
    fact_start = memory.rindex("SEAM-FACT/1|")
    mismatched_source = _resign_pack(
        valid,
        memory[:fact_start]
        + memory[fact_start:].replace("raw:source:1", "raw:source:2"),
    )

    for corrupt in (
        truncated,
        unknown_scope,
        duplicate_id,
        missing_protected,
        source_after_fact,
        mismatched_source,
    ):
        assert parse_pack_items(corrupt) is None
        assert expand_logical_raw_rows([corrupt]) is None
    assert expand_logical_raw_rows([valid, _row("raw:3", "after pack")]) is None
