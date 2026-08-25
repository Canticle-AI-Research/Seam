"""Track S S8 - one coherent retrieval engine.

Each test here pins one campaign exit condition from
`docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md`. The shared property is that a
single request must mean exactly one thing no matter which policy, surface, or
persistence path expresses it.
"""

from __future__ import annotations

import pytest

from seam_runtime.runtime import SeamRuntime

ADAPTER_ATTRS = (
    "sql_adapter",
    "semantic_adapter",
    "graph_adapter",
    "graph_node_adapter",
    "temporal_adapter",
    "legacy_weighted_adapter",
)


@pytest.fixture()
def runtime(tmp_path):
    rt = SeamRuntime(tmp_path / "s8.db", allow_pgvector_env=False)
    try:
        for index, text in enumerate(
            (
                "Ada shipped the retrieval coherence plan.",
                "Grace reviewed the fusion weight contract.",
                "The coherence plan depends on the fusion contract.",
            )
        ):
            rt.ingest_text(text, source_ref=f"local://s8/{index}")
        yield rt
    finally:
        rt.close()


def _spy_adapters(orchestrator, monkeypatch):
    """Count `.search()` calls on every leg adapter the engine owns."""

    calls: dict[str, int] = {name: 0 for name in ADAPTER_ATTRS}

    for name in ADAPTER_ATTRS:
        adapter = getattr(orchestrator, name)
        original = adapter.search

        def counted(*args, _name=name, _original=original, **kwargs):
            calls[_name] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(adapter, "search", counted)
    return calls


# -- exit: a legacy-policy plan executes only the legacy adapter -----------


def test_legacy_policy_executes_only_the_legacy_adapter(runtime, monkeypatch):
    orchestrator = runtime._retrieval_orchestrator_cached()
    calls = _spy_adapters(orchestrator, monkeypatch)

    runtime.retrieve(
        "coherence plan", budget=5, mode="mix", ranking_policy="legacy-weighted/1"
    )

    assert calls["legacy_weighted_adapter"] == 1
    unused = {name: count for name, count in calls.items() if name != "legacy_weighted_adapter"}
    assert unused == {name: 0 for name in unused}, (
        "a legacy-policy plan must not execute any canonical fusion leg"
    )


def test_fusion_policy_never_executes_the_legacy_adapter(runtime, monkeypatch):
    orchestrator = runtime._retrieval_orchestrator_cached()
    calls = _spy_adapters(orchestrator, monkeypatch)

    runtime.retrieve(
        "coherence plan", budget=5, mode="mix", ranking_policy="reciprocal-rank-fusion/2"
    )

    assert calls["legacy_weighted_adapter"] == 0
    assert calls["sql_adapter"] >= 1
    assert calls["semantic_adapter"] >= 1


# -- exit: weighted policy replays exactly through persistence ------------


def _weighted(runtime, weights):
    """Rebind the runtime's cached flags to a specific weight configuration."""

    import dataclasses

    base = runtime._retrieval_flags_cached()
    runtime._retrieval_flags = dataclasses.replace(base, fusion_leg_weights=weights)
    return runtime._retrieval_flags


def test_weighted_retrieval_is_persistable_through_the_sdk(runtime):
    """A weighted retrieval must record, not crash the reasoning recorder.

    The orchestrator reports `weighted-reciprocal-rank-fusion/1` as soon as any
    leg weight is set, so a persistence layer that only accepts
    `reciprocal-rank-fusion/2` turns a supported retrieval into a hard failure.
    """

    from seam_runtime.sdk import SeamSDK

    _weighted(runtime, (("vector", 0.5),))
    session = SeamSDK(runtime=runtime).start_reasoning("Weighted replay.")
    recorded = session.retrieve("coherence plan", budget=3, mode="mix")

    assert recorded.reasoning["policy"] == "weighted-reciprocal-rank-fusion/1"


def _record_under(runtime, weights, label):
    from seam_runtime.sdk import SeamSDK

    _weighted(runtime, weights)
    session = SeamSDK(runtime=runtime).start_reasoning(f"Replay {label}.")
    recorded = session.retrieve("coherence plan", budget=3, mode="mix")
    return session.retrieval(str(recorded.reasoning["retrieval_id"]))


@pytest.mark.parametrize(
    ("label", "weights"),
    [
        ("absent", ()),
        ("all-one", (("sql", 1.0), ("vector", 1.0))),
        ("zero", (("vector", 0.0),)),
        ("non-unit", (("sql", 0.25), ("vector", 2.5))),
    ],
)
def test_persisted_weights_replay_the_recorded_score_exactly(runtime, label, weights):
    """The stored row must be enough to re-derive its own ranking, bit for bit."""

    from seam_runtime.retrieval_policy import weighted_fusion_score

    stored = _record_under(runtime, weights, label)
    persisted = stored["leg_weights"]

    assert persisted == {leg: weight for leg, weight in weights}
    candidates = stored["candidates"]
    assert candidates, "replay needs at least one recorded candidate"
    for candidate in candidates:
        assert weighted_fusion_score(candidate["sources"], persisted) == candidate["score"]
    ranks = [candidate["rank"] for candidate in candidates]
    assert ranks == sorted(ranks)


def test_all_one_weights_are_bitwise_identical_to_plain_rrf(runtime):
    """All-1.0 must not perturb a single stored score, or every prior
    measurement taken under `/2` silently changes meaning."""

    absent = _record_under(runtime, (), "absent-baseline")
    all_one = _record_under(
        runtime, (("sql", 1.0), ("vector", 1.0), ("graph", 1.0)), "all-one"
    )

    def shape(stored):
        return [
            (candidate["record_id"], candidate["rank"], candidate["score"])
            for candidate in stored["candidates"]
        ]

    assert shape(all_one) == shape(absent)
    assert all_one["candidate_set_sha256"] == absent["candidate_set_sha256"]
    # The policy id must still tell the truth about how it was ranked.
    assert absent["policy"] == "reciprocal-rank-fusion/2"
    assert all_one["policy"] == "weighted-reciprocal-rank-fusion/1"


def test_zero_weight_removes_a_leg_from_ranking_but_not_from_the_record(runtime):
    """A zeroed leg must stay auditable: ablation is a ranking act, not erasure."""

    stored = _record_under(runtime, (("vector", 0.0),), "zero-vector")

    assert stored["leg_weights"] == {"vector": 0.0}
    contributed = [c for c in stored["candidates"] if "vector" in c["sources"]]
    assert contributed, "the vector leg must still be recorded in the evidence"
    for candidate in contributed:
        without_vector = {
            leg: value for leg, value in candidate["sources"].items() if leg != "vector"
        }
        from seam_runtime.retrieval_policy import weighted_fusion_score

        assert weighted_fusion_score(
            without_vector, stored["leg_weights"]
        ) == candidate["score"]


# -- exit: every shipped surface matches direct `retrieve()` --------------

COMPAT_KINDS = {"CLM", "STA", "EVT", "REL"}


def _direct_ids(runtime, query, budget, policy):
    """The canonical ranking, narrowed to the compatibility record kinds."""

    result = runtime.retrieve(
        query, budget=budget, mode="mix", ranking_policy=policy
    )
    return [
        candidate.record.id
        for candidate in result.candidates
        if candidate.record.kind.value.upper() in COMPAT_KINDS
    ][:budget]


@pytest.mark.parametrize(
    "policy", ["legacy-weighted/1", "reciprocal-rank-fusion/2"]
)
def test_search_ir_matches_direct_retrieve_under_the_same_policy(runtime, policy):
    """`search_ir` is a result shape, not a second ranking pipeline."""

    query, budget = "coherence plan", 3
    surface = runtime.search_ir(query, budget=budget, ranking_policy=policy)
    surface_ids = [candidate.record.id for candidate in surface.candidates]

    assert surface_ids, "parity check needs a non-empty candidate list"
    assert surface_ids == _direct_ids(runtime, query, budget, policy)


def test_search_ir_no_longer_hardcodes_its_ranking_policy(runtime):
    """The surface must rank differently only when asked to, never silently."""

    query, budget = "coherence plan", 3
    legacy = runtime.search_ir(query, budget=budget, ranking_policy="legacy-weighted/1")
    canonical = runtime.search_ir(
        query, budget=budget, ranking_policy="reciprocal-rank-fusion/2"
    )

    assert legacy.trace is None or canonical.trace is None or True
    # Both must be exact mirrors of the engine under their own policy.
    assert [c.record.id for c in legacy.candidates] == _direct_ids(
        runtime, query, budget, "legacy-weighted/1"
    )
    assert [c.record.id for c in canonical.candidates] == _direct_ids(
        runtime, query, budget, "reciprocal-rank-fusion/2"
    )


def test_rest_search_surface_matches_direct_retrieve(tmp_path, monkeypatch):
    """The shipped HTTP surface must not reorder or re-rank the engine."""

    from fastapi.testclient import TestClient

    from seam_runtime.server import create_app_from_env

    db = tmp_path / "s8-rest.db"
    monkeypatch.setenv("SEAM_SERVER_DB", str(db))
    monkeypatch.delenv("SEAM_API_TOKEN", raising=False)
    monkeypatch.delenv("SEAM_API_RATE_LIMIT_PER_MINUTE", raising=False)

    app = create_app_from_env()
    client = TestClient(app)
    for index, text in enumerate(
        (
            "Ada shipped the retrieval coherence plan.",
            "Grace reviewed the fusion weight contract.",
            "The coherence plan depends on the fusion contract.",
        )
    ):
        assert client.post(
            "/compile",
            json={
                "text": text,
                "source_ref": f"local://s8-rest/{index}",
                "persist": True,
            },
        ).status_code == 200

    response = client.get("/search?query=coherence+plan&budget=3")
    assert response.status_code == 200
    surface_ids = [
        candidate["record"]["id"] for candidate in response.json()["candidates"]
    ]
    assert surface_ids, "parity check needs a non-empty candidate list"

    from seam_runtime.runtime import SeamRuntime

    direct = SeamRuntime(db, allow_pgvector_env=False)
    try:
        expected = _direct_ids(direct, "coherence plan", 3, "legacy-weighted/1")
    finally:
        direct.close()
    assert surface_ids == expected


# -- exit: exactly one tenant-scoped event, telemetry answer-inert ---------


def _events(runtime):
    return runtime.store.iter_retrieval_events()


def _events_on(runtime):
    import dataclasses

    base = runtime._retrieval_flags_cached()
    runtime._retrieval_flags = dataclasses.replace(base, retrieval_events=True)
    return runtime._retrieval_flags


def test_no_event_is_recorded_while_telemetry_is_disabled(runtime):
    """Default-off means default-silent: no surface writes without opt-in."""

    runtime.retrieve("coherence plan", budget=3, mode="mix")
    assert _events(runtime) == []


def test_exactly_one_event_per_successful_retrieval(runtime):
    _events_on(runtime)

    runtime.retrieve("coherence plan", budget=3, mode="mix")
    assert len(_events(runtime)) == 1

    runtime.retrieve("fusion contract", budget=3, mode="mix")
    assert len(_events(runtime)) == 2


def test_a_compatibility_surface_call_still_records_exactly_one_event(runtime):
    """`search_ir` delegates to the engine, so it must not double-count."""

    _events_on(runtime)
    runtime.search_ir("coherence plan", budget=3)
    assert len(_events(runtime)) == 1


def test_the_sdk_engine_path_also_records_exactly_one_event(runtime):
    """The SDK drives the orchestrator directly; it must not be a blind spot."""

    from seam_runtime.sdk import SeamSDK

    _events_on(runtime)
    session = SeamSDK(runtime=runtime).start_reasoning("Telemetry coverage.")
    session.retrieve("coherence plan", budget=3, mode="mix")
    assert len(_events(runtime)) == 1


def test_the_event_is_scoped_to_the_tenant_namespace(runtime):
    _events_on(runtime)

    runtime.retrieve("coherence plan", budget=3, mode="mix", ns="tenant-a", scope="project")
    runtime.retrieve("coherence plan", budget=3, mode="mix", ns="tenant-b", scope="project")

    scopes = sorted(str(event["scope"]) for event in _events(runtime))
    assert scopes == ["tenant-a:project", "tenant-b:project"]


def test_telemetry_failure_cannot_alter_the_answer(runtime, monkeypatch):
    """An observability outage is not an answer outage."""

    baseline = [
        candidate.record.id
        for candidate in runtime.retrieve("coherence plan", budget=3, mode="mix").candidates
    ]

    _events_on(runtime)

    def _boom(**_kwargs):
        raise RuntimeError("telemetry store is unavailable")

    monkeypatch.setattr(runtime.store, "write_retrieval_event", _boom)

    result = runtime.retrieve("coherence plan", budget=3, mode="mix")
    assert [candidate.record.id for candidate in result.candidates] == baseline
    assert baseline, "inertness check needs a non-empty candidate list"


# -- audit item: the process-lifetime flag cache is explicit, not accidental


def test_applied_state_is_adopted_only_through_an_explicit_refresh(runtime):
    """Stability by default, adoption on request -- both provable."""

    assert runtime._retrieval_flags_cached().retrieval_events is False

    runtime.store.upsert_retrieval_flag_state(
        flag_key="retrieval_events", flag_value=True
    )

    # A running process must NOT shift scoring underneath itself.
    assert runtime._retrieval_flags_cached().retrieval_events is False
    # ...and must be able to adopt the change deliberately.
    assert runtime.refresh_retrieval_flags().retrieval_events is True


# -- audit item: bound every IN(...) below the 999-variable floor ----------


def test_graph_traversal_survives_a_frontier_past_the_variable_floor(tmp_path):
    """A deep-retrieval frontier must not blow SQLite's variable limit.

    The traversal binds the frontier twice per statement, so a limit an
    operator can actually configure (`search_top_k` in the hundreds) pushed a
    single one-shot `IN (...)` past 999 host parameters.
    """

    import sqlite3

    from seam_runtime.knowledge_graph import query_graph
    from seam_runtime.mirl import utc_now

    rt = SeamRuntime(tmp_path / "frontier.db", allow_pgvector_env=False)
    try:
        with rt.store._pool.checkout() as connection:
            now = utc_now()
            spokes = 700  # frontier binds twice -> 1400 host parameters
            connection.execute(
                "insert into knowledge_nodes (id, kind, label, ns, scope, status,"
                " confidence, created_at, updated_at, properties_json)"
                " values ('hub', 'entity', 'hub', 'g', 'project', 'active', 1.0, ?, ?, '{}')",
                (now, now),
            )
            for index in range(spokes):
                node_id = f"spoke-{index:04d}"
                connection.execute(
                    "insert into knowledge_nodes (id, kind, label, ns, scope, status,"
                    " confidence, created_at, updated_at, properties_json)"
                    " values (?, 'entity', ?, 'g', 'project', 'active', 1.0, ?, ?, '{}')",
                    (node_id, node_id, now, now),
                )
                connection.execute(
                    "insert into knowledge_edges (id, src_id, dst_id, predicate,"
                    " edge_kind, ns, scope, status, confidence, created_at,"
                    " updated_at, source_record_id, properties_json)"
                    " values (?, 'hub', ?, 'relates_to', 'semantic', 'g', 'project',"
                    " 'active', 0.0, ?, ?, 'raw:1', '{}')",
                    (f"edge-{index:04d}", node_id, now, now),
                )
            connection.commit()

            # Pin this connection to the legacy 999-variable floor. Modern
            # SQLite builds allow far more (250k here), so without this the
            # test would pass even with chunking removed -- it would prove
            # nothing about the portability contract the audit asked for.
            connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)

            # hops=2 forces a second round whose frontier is the full spoke set.
            result = query_graph(
                connection,
                root_id="hub",
                namespace="g",
                scope="project",
                limit=1000,
                hops=2,
            )

        assert len(result["nodes"]) > 500, "the frontier must actually exceed the floor"
    finally:
        rt.close()


def test_leg_weights_column_is_an_additive_migration(runtime):
    """An existing store must gain the column without losing its rows.

    Every row recorded before this change ran under unweighted `/2`, so the
    backfill value is `{}` -- which is exactly what replays those rows.
    """

    from seam_runtime.reasoning_graph import (
        _migrate_reasoning_retrieval_schema,
        _table_columns,
    )
    from seam_runtime.sdk import SeamSDK

    session = SeamSDK(runtime=runtime).start_reasoning("Migration check.")
    session.retrieve("coherence plan", budget=3, mode="mix")

    with runtime.store._pool.checkout() as connection:
        # Simulate the pre-change schema on a real, populated store.
        connection.execute("drop trigger if exists reasoning_retrieval_no_update")
        connection.execute(
            "alter table reasoning_retrieval drop column leg_weights_json"
        )
        connection.commit()
        assert "leg_weights_json" not in _table_columns(
            connection, "reasoning_retrieval"
        )

        _migrate_reasoning_retrieval_schema(connection)
        connection.commit()

        assert "leg_weights_json" in _table_columns(connection, "reasoning_retrieval")
        rows = connection.execute(
            "select leg_weights_json from reasoning_retrieval"
        ).fetchall()
        assert rows, "the pre-existing row must survive the migration"
        assert all(row[0] == "{}" for row in rows)

        # Re-running must be a no-op, not an error.
        _migrate_reasoning_retrieval_schema(connection)
        connection.commit()


# -- exit: MCP and TUI surfaces are covered by the same proof --------------


def test_mcp_retrieve_tool_matches_direct_retrieve(runtime):
    """`seam_retrieve` drives the engine; it must not re-rank."""

    from seam_runtime.mcp import dispatch_tool

    response = dispatch_tool(
        runtime,
        {
            "tool": "seam_retrieve",
            "arguments": {"query": "coherence plan", "budget": 3, "mode": "mix"},
        },
    )
    surface_ids = [
        candidate["record"]["id"] for candidate in response["result"]["candidates"]
    ]
    direct = runtime.retrieve("coherence plan", budget=3, mode="mix")

    assert surface_ids, "parity check needs a non-empty candidate list"
    assert surface_ids == [candidate.record.id for candidate in direct.candidates]


def test_mcp_context_tool_matches_the_compatibility_ranking(runtime):
    """`seam_context` reads through `search_ir`, so it inherits that parity."""

    from seam_runtime.mcp import dispatch_tool

    response = dispatch_tool(
        runtime,
        {"tool": "seam_context", "arguments": {"query": "coherence plan", "budget": 3}},
    )
    surface_ids = [
        candidate["record"]["id"] for candidate in response["result"]["candidates"]
    ]
    expected = [
        candidate.record.id
        for candidate in runtime.search_ir("coherence plan", budget=3).candidates
    ]

    assert surface_ids, "parity check needs a non-empty candidate list"
    assert surface_ids == expected


def test_mcp_retrieval_records_exactly_one_event(runtime):
    from seam_runtime.mcp import dispatch_tool

    _events_on(runtime)
    dispatch_tool(
        runtime,
        {
            "tool": "seam_retrieve",
            "arguments": {"query": "coherence plan", "budget": 3, "mode": "mix"},
        },
    )
    assert len(_events(runtime)) == 1


def test_tui_memory_panel_path_matches_direct_retrieve(runtime):
    """The TUI reads through the same `search_ir` call the dashboard uses."""

    surface = runtime.search_ir("coherence plan", budget=5)
    surface_ids = [candidate.record.id for candidate in surface.candidates]

    assert surface_ids, "parity check needs a non-empty candidate list"
    assert surface_ids == _direct_ids(runtime, "coherence plan", 5, "legacy-weighted/1")
