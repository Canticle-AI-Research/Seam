from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seam_runtime.mcp import TOOL_METADATA, dispatch_tool
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind, Status
from seam_runtime.retrieval_orchestrator.adapters import SQLiteGraphAdapter
from seam_runtime.retrieval_orchestrator.types import QueryFilters, QueryIntent, RetrievalPlan
from seam_runtime.runtime import SeamRuntime
from seam_runtime.server import create_app


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    instance = SeamRuntime(tmp_path / "knowledge.db")
    try:
        yield instance
    finally:
        instance.close()


def test_every_persist_automatically_builds_agent_attributed_graph(runtime: SeamRuntime) -> None:
    batch = runtime.compile_nl(
        "Alice owns the billing service.",
        source_ref="agent://codex/session-1",
        agent_id="codex",
    )
    runtime.persist_ir(batch)

    graph = runtime.store.knowledge_graph(query="Alice", limit=100, hops=2)
    kinds = {node["kind"] for node in graph["nodes"]}
    assert {"agent", "entity", "claim", "source", "evidence", "value"} <= kinds
    assert graph["stats"]["agent_count"] == 1
    assert graph["stats"]["source_count"] == 1
    assert any(
        edge["edge_kind"] == "semantic" and edge["predicate"] == "content"
        for edge in graph["edges"]
    )
    assert any(
        edge["source"].startswith("agent:codex:") and edge["predicate"] == "contributed"
        for edge in graph["edges"]
    )
    agent_node = next(node for node in graph["nodes"] if node["kind"] == "agent")
    agent_detail = runtime.store.knowledge_node(agent_node["id"])
    assert agent_detail["page"]["sources"] == ["agent://codex/session-1"]
    assert any(edge["predicate"] == "contributed" for edge in agent_detail["page"]["facts"])

    alice = next(node for node in graph["nodes"] if node["kind"] == "entity" and node["label"] == "Alice")
    detail = runtime.store.knowledge_node(alice["id"])
    assert detail["page"]["agents"] == ["codex"]
    assert detail["page"]["sources"] == ["agent://codex/session-1"]
    assert detail["page"]["facts"][0]["source_record_id"].startswith("clm:")
    assert detail["record"]["kind"] == "ENT"


def test_query_graph_projects_episodes_as_connected_provenance_nodes(runtime: SeamRuntime) -> None:
    runtime.persist_ir(
        runtime.compile_nl(
            "Alice owns the billing service.",
            source_ref="agent://codex/session-episode",
            agent_id="codex",
        )
    )

    graph = runtime.store.knowledge_graph(query="Alice", limit=100, hops=2)
    episode = next(node for node in graph["nodes"] if node["kind"] == "episode")
    assert episode["label"] == "agent://codex/session-episode"
    assert episode["agents"] == ["codex"]
    assert episode["sources"] == ["agent://codex/session-episode"]
    assert episode["properties"]["source_record_id"].startswith("raw:")
    supports = [
        edge
        for edge in graph["edges"]
        if edge["source"] == episode["id"] and edge["predicate"] == "supports"
    ]
    assert supports
    assert all(edge["edge_kind"] == "provenance" for edge in supports)
    assert all(edge["properties"]["projection"] == "episode_provenance" for edge in supports)
    assert {edge["target"] for edge in supports} <= {node["id"] for node in graph["nodes"]}
    assert graph["stats"]["episode_count"] == 1
    assert graph["facets"]["kinds"]["episode"] == 1


def test_episode_search_and_detail_are_graph_backed(runtime: SeamRuntime) -> None:
    runtime.persist_ir(
        runtime.compile_nl(
            "Priya leads Orion.",
            source_ref="agent://claude/episode-detail",
            agent_id="claude",
        )
    )

    graph = runtime.store.knowledge_graph(
        query="episode-detail",
        kinds=["episode"],
        agent_id="claude",
        limit=100,
    )
    episode = next(node for node in graph["nodes"] if node["kind"] == "episode")
    detail = runtime.store.knowledge_node(episode["id"], include_history=False)
    assert detail["node"]["kind"] == "episode"
    assert detail["episodes"][0]["id"] == episode["id"]
    assert detail["page"]["sources"] == ["agent://claude/episode-detail"]
    assert detail["page"]["agents"] == ["claude"]
    assert detail["page"]["facts"]
    assert detail["record"]["kind"] == "RAW"
    assert any(node["kind"] == "entity" for node in detail["neighbors"])


def test_episode_projection_respects_lifecycle_and_query_filters(runtime: SeamRuntime) -> None:
    runtime.ingest_text(
        "Alice owns alpha.",
        source_ref="agent://codex/evolving",
        agent_id="codex",
        ns="team.alpha",
        scope="project",
    )
    runtime.ingest_text(
        "Alice owns beta.",
        source_ref="agent://codex/evolving",
        agent_id="codex",
        ns="team.alpha",
        scope="project",
    )
    with runtime.store._pool.checkout() as connection:
        episodes = connection.execute(
            "select id, status from knowledge_episodes where source_ref = ? order by status",
            ("agent://codex/evolving",),
        ).fetchall()
        old_episode_id = next(row["id"] for row in episodes if row["status"] == "superseded")
        connection.execute(
            "update knowledge_episodes set recorded_at = ?, expired_at = ? where id = ?",
            ("2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00", old_episode_id),
        )
        connection.commit()

    current = runtime.store.knowledge_graph(
        query="evolving",
        kinds=["episode"],
        namespace="team.alpha",
        scope="project",
        agent_id="codex",
        include_history=False,
        limit=100,
    )
    historical = runtime.store.knowledge_graph(
        query="evolving",
        kinds=["episode"],
        namespace="team.alpha",
        scope="project",
        agent_id="codex",
        include_history=True,
        limit=100,
    )
    at_old_episode = runtime.store.knowledge_graph(
        root_id=old_episode_id,
        at="2026-01-15T00:00:00+00:00",
        include_history=True,
    )
    assert len([node for node in current["nodes"] if node["kind"] == "episode"]) == 1
    assert len([node for node in historical["nodes"] if node["kind"] == "episode"]) == 2
    assert [node["id"] for node in at_old_episode["nodes"]] == [old_episode_id]
    assert runtime.store.knowledge_node(
        old_episode_id,
        at="2026-01-15T00:00:00+00:00",
    )["node"]["id"] == old_episode_id
    with pytest.raises(KeyError):
        runtime.store.knowledge_node(old_episode_id, include_history=False)
    assert runtime.store.knowledge_graph(query="evolving", agent_id="gemini")["nodes"] == []
    assert runtime.store.knowledge_graph(query="evolving", namespace="team.beta")["nodes"] == []


def test_reprojecting_record_removes_stale_semantic_edges(runtime: SeamRuntime) -> None:
    original = MIRLRecord(
        id="rel:ownership",
        kind=RecordKind.REL,
        attrs={"src": "ent:alice", "predicate": "owns", "dst": "ent:alpha"},
        ext={"agent_id": "claude"},
    )
    runtime.persist_ir(IRBatch([original]))
    replacement = MIRLRecord.from_dict(original.to_dict())
    replacement.attrs["dst"] = "ent:beta"
    runtime.persist_ir(IRBatch([replacement]))

    with runtime.store._pool.checkout() as connection:
        semantic = connection.execute(
            "select src_id, predicate, dst_id from knowledge_edges "
            "where source_record_id = ? and edge_kind = 'semantic'",
            (original.id,),
        ).fetchall()
    assert [tuple(row) for row in semantic] == [("ent:alice", "owns", "ent:beta")]
    detail = runtime.store.knowledge_node("ent:alice")
    assert detail["page"]["agents"] == ["claude"]
    assert detail["page"]["sources"] == ["mirl://rel:ownership"]


def test_trace_preserves_persisted_direction_when_following_an_incoming_edge(runtime: SeamRuntime) -> None:
    runtime.persist_ir(
        IRBatch(
            [
                MIRLRecord(
                    id="ent:source",
                    kind=RecordKind.ENT,
                    attrs={"label": "Source", "entity_type": "service"},
                ),
                MIRLRecord(
                    id="ent:target",
                    kind=RecordKind.ENT,
                    attrs={"label": "Target", "entity_type": "service"},
                ),
                MIRLRecord(
                    id="rel:source-target",
                    kind=RecordKind.REL,
                    attrs={"src": "ent:source", "predicate": "references", "dst": "ent:target"},
                ),
            ]
        )
    )

    trace = runtime.store.trace("ent:target")

    assert {"src": "ent:source", "type": "references", "dst": "ent:target"} in trace.edges
    assert {"src": "ent:target", "type": "references", "dst": "ent:source"} not in trace.edges


def test_reingest_keeps_history_but_hides_superseded_source_from_current_graph(runtime: SeamRuntime) -> None:
    first = runtime.ingest_text(
        "Alice owns alpha.",
        source_ref="agent://codex/fact",
        agent_id="codex",
    )
    runtime.ingest_text(
        "Alice owns beta.",
        source_ref="agent://codex/fact",
        agent_id="codex",
    )

    current = runtime.store.knowledge_graph(query="alpha", include_history=False, limit=100)
    historical = runtime.store.knowledge_graph(query="alpha", include_history=True, limit=100)
    assert current["nodes"] == []
    assert any(node["label"] == "Alice owns alpha." for node in historical["nodes"])

    with runtime.store._pool.checkout() as connection:
        statuses = connection.execute(
            "select status from knowledge_episodes where source_ref = ? order by status",
            ("agent://codex/fact",),
        ).fetchall()
    assert [row[0] for row in statuses] == ["active", "superseded"]

    old_raw_id = next(record_id for record_id in first.stored_ids if record_id.startswith("raw:"))
    old_raw = runtime.store.load_ir(ids=[old_raw_id]).records[0]
    runtime.persist_ir(IRBatch([old_raw]))
    with runtime.store._pool.checkout() as connection:
        episode = connection.execute(
            "select status, expired_at from knowledge_episodes where source_record_id = ?",
            (old_raw_id,),
        ).fetchone()
    assert tuple(episode) == ("superseded", episode["expired_at"])
    assert episode["expired_at"] is not None
    assert runtime.store.knowledge_graph(query="alpha", include_history=False)["nodes"] == []


def test_canonical_reprojection_refreshes_node_values(runtime: SeamRuntime) -> None:
    original = MIRLRecord(
        id="ent:service",
        kind=RecordKind.ENT,
        conf=0.9,
        attrs={"label": "Old service", "entity_type": "service", "category": "legacy"},
    )
    runtime.persist_ir(IRBatch([original]))
    replacement = MIRLRecord.from_dict(original.to_dict())
    replacement.conf = 0.4
    replacement.attrs = {"label": "Current service", "entity_type": "service", "category": "canonical"}
    runtime.persist_ir(IRBatch([replacement]))

    detail = runtime.store.knowledge_node(original.id)
    assert detail["node"]["label"] == "Current service"
    assert detail["node"]["confidence"] == pytest.approx(0.4)
    assert detail["node"]["properties"]["attrs"]["category"] == "canonical"


def test_deleted_canonical_node_is_scrubbed_when_other_facts_still_reference_it(runtime: SeamRuntime) -> None:
    relation = MIRLRecord(
        id="rel:uses-target",
        kind=RecordKind.REL,
        attrs={"src": "ent:consumer", "predicate": "uses", "dst": "ent:target"},
    )
    target = MIRLRecord(
        id="ent:target",
        kind=RecordKind.ENT,
        attrs={"label": "Sensitive canonical label", "entity_type": "service", "private": "remove me"},
    )
    runtime.persist_ir(IRBatch([relation, target]))
    runtime.store.delete_ir([target.id])

    with runtime.store._pool.checkout() as connection:
        row = connection.execute(
            "select label, source_record_id, synthetic, properties_json from knowledge_nodes where id = ?",
            (target.id,),
        ).fetchone()
    assert row["label"] == "target"
    assert row["source_record_id"] is None
    assert row["synthetic"] == 1
    assert json.loads(row["properties_json"]) == {"reference": target.id}


def test_synthetic_identities_are_scope_and_agent_collision_safe(runtime: SeamRuntime) -> None:
    records = [
        MIRLRecord(
            id="clm:thread-value",
            kind=RecordKind.CLM,
            ns="shared",
            scope="thread",
            ext={"agent_id": "agent/a"},
            attrs={"subject": "ent:one", "predicate": "uses", "object": "same literal"},
        ),
        MIRLRecord(
            id="clm:project-value",
            kind=RecordKind.CLM,
            ns="shared",
            scope="project",
            ext={"agent_id": "agent-a"},
            attrs={"subject": "ent:two", "predicate": "uses", "object": "same literal"},
        ),
    ]
    runtime.persist_ir(IRBatch(records))
    with runtime.store._pool.checkout() as connection:
        value_ids = connection.execute(
            "select id from knowledge_nodes where kind = 'value' and label = 'same literal'"
        ).fetchall()
        agent_ids = connection.execute(
            "select id from knowledge_nodes where kind = 'agent' order by id"
        ).fetchall()
    assert len({row[0] for row in value_ids}) == 2
    assert len({row[0] for row in agent_ids}) == 2


def test_graph_filters_internal_edges_by_namespace(runtime: SeamRuntime) -> None:
    runtime.persist_ir(IRBatch([
        MIRLRecord(
            id="rel:namespace-a",
            kind=RecordKind.REL,
            ns="namespace.a",
            attrs={"src": "ent:shared-src", "predicate": "allowed", "dst": "ent:shared-dst"},
        ),
        MIRLRecord(
            id="rel:namespace-b",
            kind=RecordKind.REL,
            ns="namespace.b",
            attrs={"src": "ent:shared-src", "predicate": "must_not_leak", "dst": "ent:shared-dst"},
        ),
    ]))
    graph = runtime.store.knowledge_graph(
        root_id="ent:shared-src",
        namespace="namespace.a",
        include_history=True,
    )
    assert graph["edges"]
    assert {edge["namespace"] for edge in graph["edges"]} == {"namespace.a"}
    assert "must_not_leak" not in {edge["predicate"] for edge in graph["edges"]}


def test_point_in_time_node_visibility_and_current_detail_not_found(runtime: SeamRuntime) -> None:
    record = MIRLRecord(
        id="ent:retired",
        kind=RecordKind.ENT,
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-02-01T00:00:00+00:00",
        status=Status.SUPERSEDED,
        attrs={"label": "Retired knowledge", "entity_type": "concept"},
    )
    runtime.persist_ir(IRBatch([record]))

    before = runtime.store.knowledge_graph(
        root_id=record.id,
        at="2026-01-15T00:00:00+00:00",
        include_history=True,
    )
    after = runtime.store.knowledge_graph(
        root_id=record.id,
        at="2026-03-01T00:00:00+00:00",
        include_history=True,
    )
    assert [node["id"] for node in before["nodes"]] == [record.id]
    assert after["nodes"] == []
    assert runtime.store.knowledge_node(
        record.id,
        at="2026-01-15T00:00:00+00:00",
    )["node"]["id"] == record.id
    with pytest.raises(KeyError):
        runtime.store.knowledge_node(record.id, include_history=False)


def test_malformed_legacy_reference_does_not_break_projection(runtime: SeamRuntime) -> None:
    target = MIRLRecord(
        id="ent:legacy",
        kind=RecordKind.ENT,
        attrs={"label": "Legacy", "entity_type": "concept"},
    )
    runtime.persist_ir(IRBatch([target]))
    with runtime.store._pool.checkout() as connection:
        connection.execute("update ir_records set payload_json = '{' where id = ?", (target.id,))
        connection.commit()

    relation = MIRLRecord(
        id="rel:legacy-reference",
        kind=RecordKind.REL,
        attrs={"src": "ent:source", "predicate": "references", "dst": target.id},
    )
    runtime.persist_ir(IRBatch([relation]))
    assert runtime.store.knowledge_graph(query="legacy", include_history=True)["nodes"]


def test_graph_retrieval_reads_canonical_knowledge_edges_not_legacy_ir_edges(runtime: SeamRuntime) -> None:
    runtime.persist_ir(
        runtime.compile_nl(
            "Priya leads the Orion program.",
            source_ref="agent://gemini/session-2",
            agent_id="gemini",
        )
    )
    with runtime.store._pool.checkout() as connection:
        connection.execute("delete from ir_edges")
        connection.commit()

    plan = RetrievalPlan(
        query="Priya",
        normalized_query="Priya",
        intent=QueryIntent.GRAPH,
        filters=QueryFilters(),
        legs=[],
        mode="graph",
    )
    hits = SQLiteGraphAdapter(runtime.store).search(plan, limit=10)
    assert hits
    assert any("graph_neighbors=" in reason and not reason.endswith("=0") for hit in hits for reason in hit.reasons)


def test_knowledge_graph_api_exposes_filters_and_graph_backed_pages(runtime: SeamRuntime) -> None:
    with TestClient(create_app(runtime)) as client:
        response = client.post(
            "/compile",
            json={
                "text": "Priya leads Orion.",
                "source_ref": "agent://claude/session-3",
                "agent_id": "claude",
                "persist": True,
            },
        )
        assert response.status_code == 200
        graph_response = client.get(
            "/knowledge-graph",
            params={
                "query": "Priya",
                "agent_id": "claude",
                "kinds": " entity, , episode ",
                "limit": 100,
                "hops": 2,
            },
        )
        assert graph_response.status_code == 200
        graph = graph_response.json()
        assert graph["query"]["agent_id"] == "claude"
        assert graph["query"]["kinds"] == ["entity", "episode"]
        entity = next(node for node in graph["nodes"] if node["kind"] == "entity" and node["label"] == "Priya")
        episode = next(node for node in graph["nodes"] if node["kind"] == "episode")

        detail_response = client.get("/knowledge-node", params={"node_id": entity["id"]})
        assert detail_response.status_code == 200
        detail = detail_response.json()
        assert detail["page"]["agents"] == ["claude"]
        assert detail["page"]["backlinks"]
        horizon_response = client.get(
            "/knowledge-node",
            params={"node_id": entity["id"], "include_history": True, "at": "2999-01-01T00:00:00+00:00"},
        )
        assert horizon_response.status_code == 200
        episode_response = client.get("/knowledge-node", params={"node_id": episode["id"]})
        assert episode_response.status_code == 200
        assert episode_response.json()["node"]["kind"] == "episode"


def test_agents_can_write_and_query_the_graph_through_mcp(runtime: SeamRuntime) -> None:
    assert "agent_id" in TOOL_METADATA["seam_ingest"]["input_schema"]
    assert TOOL_METADATA["seam_knowledge_graph"]["annotations"]["readOnlyHint"] is True
    assert "at" in TOOL_METADATA["seam_knowledge_node"]["input_schema"]
    dispatch_tool(
        runtime,
        {
            "tool": "seam_ingest",
            "arguments": {
                "text": "Mina maintains the release ledger.",
                "source_ref": "agent://gemini/release",
                "agent_id": "gemini",
            },
        },
    )
    graph_response = dispatch_tool(
        runtime,
        {
            "tool": "seam_knowledge_graph",
            "arguments": {"query": "Mina", "agent_id": "gemini", "limit": 100},
        },
    )
    graph = graph_response["result"]
    assert any(node["label"] == "Mina" for node in graph["nodes"])
    mina_id = next(node["id"] for node in graph["nodes"] if node["label"] == "Mina")
    page = dispatch_tool(
        runtime,
        {"tool": "seam_knowledge_node", "arguments": {"node_id": mina_id}},
    )["result"]
    assert page["page"]["agents"] == ["gemini"]


def test_dashboard_graph_is_live_only_and_has_no_synthetic_edge_builder() -> None:
    dashboard = Path("seam_runtime/webui/dashboard.html").read_text(encoding="utf-8")
    canvas = dashboard.split("function KnowledgeGraphCanvas", 1)[1].split("function KnowledgeGraphWorkspace", 1)[0]
    workspace = dashboard.split("function KnowledgeGraphWorkspace", 1)[1].split("function MemoryFullView", 1)[0]
    api = Path("seam_runtime/webui/seam-api.js").read_text(encoding="utf-8")

    assert "graphEdges || []" in canvas
    assert "records.forEach" not in canvas
    assert "sources[Math.floor" not in canvas
    assert "provenanceNodes" not in dashboard
    assert "provenanceEdges" not in dashboard
    assert "CompactKnowledgeGraph" in dashboard
    assert "window.SeamAPI.knowledgeGraph({ limit: 80, hops: 1 })" in dashboard
    assert "if (!enabled) setAt('')" in dashboard
    assert "detailLoading" in dashboard
    assert "knowledgeNode(selectedNode, graphHistory, horizon)" in dashboard
    assert "Object.keys(graph.facets?.kinds || {})" in dashboard
    assert "self-building · live from SQLite" in workspace
    assert "Knowledge horizon" in workspace
    assert "Canonical MIRL record" in workspace
    assert "knowledgeGraph: async function" in api
    assert "knowledgeNode: async function" in api
    assert "if (at) params.set('at', at)" in api


def test_knowledge_properties_are_valid_json(runtime: SeamRuntime) -> None:
    runtime.persist_ir(runtime.compile_nl("SEAM connects claims to sources."))
    with runtime.store._pool.checkout() as connection:
        node_payloads = connection.execute("select properties_json from knowledge_nodes").fetchall()
        edge_payloads = connection.execute("select properties_json from knowledge_edges").fetchall()
    assert all(isinstance(json.loads(row[0]), dict) for row in [*node_payloads, *edge_payloads])
