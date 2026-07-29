from __future__ import annotations

import random
from dataclasses import replace

import pytest

from seam_runtime.context_assembly import (
    CONTEXT_ASSEMBLY_CONTRACT_VERSION,
    ContextCandidate,
    assemble_context,
)

AS_OF = "2026-07-29T12:00:00Z"


def _candidate(
    candidate_id: str,
    *,
    kind: str = "fact",
    text: str = "Compiler rollback succeeded",
    trust_state: str = "supported",
    namespace: str = "tenant-a",
    scope: str = "thread-1",
    occurred_at: str = "2026-07-28T12:00:00Z",
    record_ids: tuple[str, ...] | None = None,
    episode_ids: tuple[str, ...] | None = None,
    entity_ids: tuple[str, ...] = ("ent:compiler",),
    product_id: str | None = None,
    task_tags: tuple[str, ...] = (),
    valid_until: str | None = None,
    current: bool = True,
) -> ContextCandidate:
    if kind in {"entity_summary", "community_summary", "observation"}:
        product_id = product_id or f"gp:{candidate_id}"
    return ContextCandidate(
        candidate_id=candidate_id,
        kind=kind,
        text=text,
        namespace=namespace,
        scope=scope,
        trust_state=trust_state,
        record_ids=record_ids or (f"clm:{candidate_id}",),
        episode_ids=episode_ids or (f"episode:{candidate_id}",),
        entity_ids=entity_ids,
        product_id=product_id,
        task_tags=task_tags,
        occurred_at=occurred_at,
        valid_until=valid_until,
        current=current,
    )


def _assemble(
    candidates: list[ContextCandidate],
    **overrides: object,
):
    params = {
        "task": "compiler rollback",
        "namespace": "tenant-a",
        "scope": "thread-1",
        "as_of": AS_OF,
        "token_budget": 4_000,
        "fact_reserve_tokens": 800,
    }
    params.update(overrides)
    return assemble_context(candidates, **params)


def test_assembles_all_g5_kinds_with_exact_backtraces_and_version() -> None:
    candidates = [
        _candidate("fact"),
        _candidate("entity", kind="entity", text="Compiler is a service"),
        _candidate("episode", kind="episode", text="Rollback deployment episode"),
        _candidate(
            "entity-summary",
            kind="entity_summary",
            text="Compiler rollback is normally reversible",
            record_ids=("clm:1", "clm:2"),
            episode_ids=("episode:1", "episode:2"),
        ),
        _candidate(
            "community",
            kind="community_summary",
            text="Compiler and deployer form one rollback community",
        ),
        _candidate(
            "observation",
            kind="observation",
            text="Compiler rollback succeeded across two episodes",
        ),
    ]

    pack = _assemble(candidates)

    assert pack.contract_version == CONTEXT_ASSEMBLY_CONTRACT_VERSION
    assert {item.kind for item in pack.items} == {
        "fact",
        "entity",
        "episode",
        "entity_summary",
        "community_summary",
        "observation",
    }
    assert pack.rendered.startswith("SEAM-CONTEXT/1|")
    assert pack.token_cost <= pack.token_budget
    assert pack.refs == tuple(
        sorted({ref for item in pack.items for ref in item.record_ids})
    )
    assert all(trace["record_ids"] for trace in pack.backtraces)
    assert all(trace["episode_ids"] for trace in pack.backtraces)
    for item in pack.items:
        assert item.record_ids[0] in pack.rendered
        assert item.episode_ids[0] in pack.rendered
        if item.kind in {"entity_summary", "community_summary", "observation"}:
            assert item.product_id in pack.rendered


def test_trust_boundary_time_and_provenance_fail_closed() -> None:
    candidates = [
        _candidate("accepted", trust_state="verified"),
        _candidate("untrusted", trust_state="inferred"),
        _candidate("wrong-namespace", namespace="tenant-b"),
        _candidate("wrong-scope", scope="thread-2"),
        _candidate("future", occurred_at="2026-07-30T12:00:00Z"),
        _candidate("expired", valid_until="2026-07-29T11:59:59Z"),
        _candidate("stale", current=False),
        _candidate(
            "missing-product",
            kind="observation",
            product_id=None,
        ),
        _candidate("missing-record", record_ids=()),
        _candidate("missing-episode", episode_ids=()),
    ]
    # The helper supplies defaults for false-y refs and derived product IDs;
    # replace those three candidates explicitly to exercise malformed inputs.
    candidates[-3] = replace(candidates[-3], product_id=None)
    candidates[-2] = replace(candidates[-2], record_ids=())
    candidates[-1] = replace(candidates[-1], episode_ids=())

    pack = _assemble(candidates)

    assert [item.candidate_id for item in pack.items] == ["accepted"]
    assert dict(pack.rejected_counts) == {
        "boundary": 2,
        "derived_without_product": 1,
        "malformed": 2,
        "not_current": 1,
        "time": 2,
        "trust": 1,
    }
    assert "untrusted" not in pack.rendered
    assert "wrong-namespace" not in pack.rendered


def test_grounded_fact_reservation_prevents_derived_displacement() -> None:
    fact = _candidate(
        "fact",
        text="Compiler rollback raw grounded fact",
        trust_state="supported",
    )
    summary = _candidate(
        "summary",
        kind="entity_summary",
        text=("compiler rollback " * 40).strip(),
        trust_state="verified",
    )
    count_chars = len
    header_only = _assemble(
        [],
        token_budget=10_000,
        fact_reserve_tokens=0,
        token_counter=count_chars,
    )
    fact_only = _assemble(
        [fact],
        token_budget=10_000,
        fact_reserve_tokens=10_000,
        token_counter=count_chars,
    )
    fact_increment = fact_only.token_cost - header_only.token_cost
    budget = fact_only.token_cost + 8

    pack = _assemble(
        [summary, fact],
        token_budget=budget,
        fact_reserve_tokens=fact_increment,
        token_counter=count_chars,
    )

    assert [item.candidate_id for item in pack.items] == ["fact"]
    assert pack.omitted_candidate_ids == ("summary",)
    assert pack.token_cost <= budget


def test_order_and_truncation_are_input_order_independent() -> None:
    candidates = [
        _candidate(
            "older-verified",
            trust_state="verified",
            occurred_at="2026-07-20T00:00:00Z",
        ),
        _candidate(
            "newer-verified",
            trust_state="verified",
            occurred_at="2026-07-28T00:00:00Z",
        ),
        _candidate(
            "task-supported",
            trust_state="supported",
            text="compiler rollback exact task match",
        ),
        _candidate(
            "unrelated-supported",
            trust_state="supported",
            text="lunch order",
        ),
    ]
    first = _assemble(candidates, token_budget=720, fact_reserve_tokens=0)
    random.Random(42).shuffle(candidates)
    second = _assemble(candidates, token_budget=720, fact_reserve_tokens=0)

    assert first.rendered == second.rendered
    assert first.items == second.items
    assert first.omitted_candidate_ids == second.omitted_candidate_ids
    selected = [item.candidate_id for item in first.items]
    assert selected[:2] == ["newer-verified", "older-verified"]
    if "task-supported" in selected and "unrelated-supported" in selected:
        assert selected.index("task-supported") < selected.index(
            "unrelated-supported"
        )


def test_conflicting_ids_fail_closed_and_exact_duplicates_dedupe() -> None:
    same = _candidate("same")
    conflict = _candidate("same", text="Conflicting text")

    pack = _assemble([same, same, conflict])

    assert pack.items == ()
    assert dict(pack.rejected_counts) == {"conflicting_candidate_id": 3}

    deduped = _assemble([same, same])
    assert [item.candidate_id for item in deduped.items] == ["same"]
    assert dict(deduped.rejected_counts) == {"duplicate_candidate": 1}


def test_budget_is_exact_and_never_partially_truncates_items() -> None:
    candidate = _candidate("one", text="compiler rollback " * 20)
    count_chars = len
    empty = _assemble(
        [],
        token_budget=10_000,
        fact_reserve_tokens=0,
        token_counter=count_chars,
    )
    full = _assemble(
        [candidate],
        token_budget=10_000,
        fact_reserve_tokens=10_000,
        token_counter=count_chars,
    )

    exact = _assemble(
        [candidate],
        token_budget=full.token_cost,
        fact_reserve_tokens=full.token_cost,
        token_counter=count_chars,
    )
    short = _assemble(
        [candidate],
        token_budget=full.token_cost - 1,
        fact_reserve_tokens=full.token_cost,
        token_counter=count_chars,
    )

    assert exact.token_cost == full.token_cost
    assert [item.candidate_id for item in exact.items] == ["one"]
    assert short.token_cost == empty.token_cost
    assert short.items == ()
    assert short.omitted_candidate_ids == ("one",)


def test_invalid_budget_and_naive_time_are_rejected() -> None:
    with pytest.raises(ValueError, match="positive"):
        _assemble([], token_budget=0)
    with pytest.raises(ValueError, match="non-negative"):
        _assemble([], fact_reserve_tokens=-1)
    with pytest.raises(ValueError, match="timezone"):
        _assemble([], as_of="2026-07-29T12:00:00")
    with pytest.raises(ValueError, match="too small"):
        _assemble([], token_budget=1)


def test_token_counting_calls_scale_linearly_with_candidates() -> None:
    candidates = [
        _candidate(
            f"candidate-{index}",
            text=f"compiler rollback evidence {index}",
        )
        for index in range(200)
    ]
    calls = 0

    def counting_chars(value: str) -> int:
        nonlocal calls
        calls += 1
        return len(value)

    pack = _assemble(
        candidates,
        token_budget=100_000,
        fact_reserve_tokens=100_000,
        token_counter=counting_chars,
    )

    assert len(pack.items) == len(candidates)
    assert calls <= len(candidates) * 2 + 3
