from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable, Mapping

from .mirl import MIRLRecord, RecordKind, Status, utc_now

PROJECTION_VERSION = "knowledge-graph/4"
CURRENT_EXCLUDED_STATUSES = {
    Status.CONTRADICTED.value,
    Status.SUPERSEDED.value,
    Status.DEPRECATED.value,
    Status.DELETED_SOFT.value,
}

ASSERTION_KINDS = frozenset({"claim", "relation", "event", "state"})
ASSERTABLE_TRUST_STATES = frozenset({"verified", "supported"})
TRUST_STATES = (
    "verified",
    "supported",
    "contested",
    "unverified",
    "refuted",
    "stale",
    "superseded",
)

EPISTEMIC_PREDICATES = frozenset({
    "supports",
    "contradicts",
    "refutes",
    "corroborates",
    "derived_from",
    "unverified_by",
})
CAUSAL_PREDICATES = frozenset({
    "caused_by",
    "causes",
    "motivated_by",
    "because",
    "reason",
    "resulted_in",
    "leads_to",
})
TEMPORAL_PREDICATES = frozenset({
    "precedes",
    "follows",
    "before",
    "after",
    "then",
    "occurred_at",
    "valid_during",
    "supersedes",
})
PROVENANCE_PREDICATES = frozenset({
    "provenance",
    "evidence",
    "excerpt_of",
    "contributed",
    "produced",
})

_FACET_PREDICATES = {
    "who": "performed_by",
    "what": "about",
    "when": "occurred_at",
    "where": "located_in",
    "why": "caused_by",
    "how": "via",
    "then": "resulted_in",
}


def predicate_family(predicate: object, default: str = "semantic") -> str:
    """Classify a predicate without rewriting the open MIRL vocabulary."""

    value = str(predicate or "").strip().lower()
    if value in EPISTEMIC_PREDICATES:
        return "epistemic"
    if value in CAUSAL_PREDICATES:
        return "causal"
    if value in TEMPORAL_PREDICATES:
        return "temporal"
    if value in PROVENANCE_PREDICATES:
        return "provenance"
    if value in {"who", "what", "when", "where", "why", "how", "then"}:
        return "facet"
    return default

_KIND_NAMES = {
    RecordKind.RAW: "source",
    RecordKind.SPAN: "evidence",
    RecordKind.ENT: "entity",
    RecordKind.CLM: "claim",
    RecordKind.EVT: "event",
    RecordKind.REL: "relation",
    RecordKind.STA: "state",
    RecordKind.SYM: "symbol",
    RecordKind.PACK: "pack",
    RecordKind.FLOW: "flow",
    RecordKind.PROV: "provenance",
    RecordKind.META: "metadata",
}

_PREFIX_KINDS = {
    "raw": "source",
    "span": "evidence",
    "ent": "entity",
    "clm": "claim",
    "evt": "event",
    "rel": "relation",
    "sta": "state",
    "sym": "symbol",
    "pack": "pack",
    "flow": "flow",
    "prov": "provenance",
    "meta": "metadata",
    "agent": "agent",
    "value": "value",
}


def init_knowledge_graph(connection: sqlite3.Connection) -> None:
    """Create and, once per schema version, backfill the live graph projection."""
    connection.executescript(
        """
        create table if not exists knowledge_nodes (
            id text primary key,
            kind text not null,
            label text not null,
            ns text not null,
            scope text not null,
            status text not null,
            confidence real not null,
            valid_from text,
            valid_to text,
            created_at text not null,
            updated_at text not null,
            agent_id text,
            source_record_id text,
            synthetic integer not null default 0,
            properties_json text not null
        );
        create table if not exists knowledge_edges (
            id text primary key,
            src_id text not null,
            dst_id text not null,
            predicate text not null,
            edge_kind text not null,
            ns text not null,
            scope text not null,
            status text not null,
            confidence real not null,
            valid_from text,
            valid_to text,
            created_at text not null,
            updated_at text not null,
            expired_at text,
            agent_id text,
            source_record_id text not null,
            properties_json text not null
        );
        create table if not exists knowledge_episodes (
            id text primary key,
            source_record_id text not null unique,
            source_ref text,
            content_hash text,
            agent_id text,
            ns text not null,
            scope text not null,
            status text not null,
            valid_at text,
            recorded_at text not null,
            expired_at text,
            metadata_json text not null
        );
        create table if not exists knowledge_node_episodes (
            node_id text not null,
            episode_id text not null,
            source_record_id text not null,
            primary key (node_id, episode_id, source_record_id)
        );
        create table if not exists knowledge_edge_episodes (
            edge_id text not null,
            episode_id text not null,
            primary key (edge_id, episode_id)
        );
        create table if not exists knowledge_graph_meta (
            key text primary key,
            value text not null
        );
        create index if not exists idx_knowledge_nodes_kind on knowledge_nodes (kind);
        create index if not exists idx_knowledge_nodes_ns_scope on knowledge_nodes (ns, scope);
        create index if not exists idx_knowledge_nodes_agent on knowledge_nodes (agent_id);
        create index if not exists idx_knowledge_nodes_updated on knowledge_nodes (updated_at);
        create index if not exists idx_knowledge_edges_src on knowledge_edges (src_id);
        create index if not exists idx_knowledge_edges_dst on knowledge_edges (dst_id);
        create index if not exists idx_knowledge_edges_predicate on knowledge_edges (predicate);
        create index if not exists idx_knowledge_edges_ns_scope on knowledge_edges (ns, scope);
        create index if not exists idx_knowledge_edges_source on knowledge_edges (source_record_id);
        create index if not exists idx_knowledge_episodes_source_ref on knowledge_episodes (source_ref);
        create index if not exists idx_knowledge_episodes_agent on knowledge_episodes (agent_id);
        create index if not exists idx_knowledge_node_episodes_episode on knowledge_node_episodes (episode_id);
        create index if not exists idx_knowledge_edge_episodes_episode on knowledge_edge_episodes (episode_id);
        """
    )
    episode_columns = {row[1] for row in connection.execute("pragma table_info(knowledge_episodes)").fetchall()}
    if "expired_at" not in episode_columns:
        connection.execute("alter table knowledge_episodes add column expired_at text")
    row = connection.execute(
        "select value from knowledge_graph_meta where key = 'projection_version'"
    ).fetchone()
    if row is not None and row[0] == PROJECTION_VERSION:
        return

    connection.execute("delete from knowledge_edge_episodes")
    connection.execute("delete from knowledge_node_episodes")
    connection.execute("delete from knowledge_edges")
    connection.execute("delete from knowledge_episodes")
    connection.execute("delete from knowledge_nodes")
    cursor = connection.execute(
        "select id, kind, ns, scope, status, conf, t0, t1, created_at, updated_at, payload_json "
        "from ir_records order by id"
    )
    while True:
        rows = cursor.fetchmany(500)
        if not rows:
            break
        records = []
        for row in rows:
            try:
                data = json.loads(row["payload_json"])
                data.setdefault("id", row["id"])
                data.setdefault("kind", row["kind"])
                data.setdefault("ns", row["ns"])
                data.setdefault("scope", row["scope"])
                data.setdefault("conf", row["conf"])
                data.setdefault("t0", row["t0"])
                data.setdefault("t1", row["t1"])
                data.setdefault("created_at", row["created_at"])
                data.setdefault("updated_at", row["updated_at"])
                status = str(data.get("status") or row["status"])
                if status not in {item.value for item in Status}:
                    status = Status.ASSERTED.value
                data["status"] = status
                records.append(MIRLRecord.from_dict(data))
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                # A malformed legacy payload must not prevent the canonical
                # store from opening. It remains in ir_records for audit and
                # can be repaired independently of this derived projection.
                continue
        project_records(connection, records)
    connection.execute(
        "insert or replace into knowledge_graph_meta (key, value) values ('projection_version', ?)",
        (PROJECTION_VERSION,),
    )


def project_records(connection: sqlite3.Connection, records: Iterable[MIRLRecord]) -> None:
    """Project MIRL records into the self-maintaining semantic graph.

    Projection is deterministic and idempotent. Re-persisting a record first
    removes graph edges sourced by its previous version, so stale topology does
    not survive an update.
    """
    records = list(records)
    if not records:
        return
    batch_by_id = {record.id: record for record in records}
    for record in records:
        old_edges = connection.execute(
            "select id from knowledge_edges where source_record_id = ?", (record.id,)
        ).fetchall()
        if old_edges:
            placeholders = ",".join("?" for _ in old_edges)
            connection.execute(
                f"delete from knowledge_edge_episodes where edge_id in ({placeholders})",
                [row[0] for row in old_edges],
            )
        connection.execute("delete from knowledge_edges where source_record_id = ?", (record.id,))
        connection.execute("delete from knowledge_node_episodes where source_record_id = ?", (record.id,))

    for record in records:
        _project_record(connection, record, batch_by_id)

    # Synthetic values/references are disposable projections. Remove any that
    # became disconnected after a source record was updated.
    connection.execute(
        "delete from knowledge_nodes where synthetic = 1 "
        "and id not in (select src_id from knowledge_edges) "
        "and id not in (select dst_id from knowledge_edges) "
        "and id not in (select node_id from knowledge_node_episodes)"
    )


def remove_records(connection: sqlite3.Connection, record_ids: Iterable[str]) -> None:
    ids = list(dict.fromkeys(record_ids))
    if not ids:
        return
    placeholders = ",".join("?" for _ in ids)
    edge_rows = connection.execute(
        f"select id from knowledge_edges where source_record_id in ({placeholders})", ids
    ).fetchall()
    if edge_rows:
        edge_ids = [row[0] for row in edge_rows]
        edge_placeholders = ",".join("?" for _ in edge_ids)
        connection.execute(
            f"delete from knowledge_edge_episodes where edge_id in ({edge_placeholders})", edge_ids
        )
    connection.execute(
        f"delete from knowledge_edges where source_record_id in ({placeholders})", ids
    )
    connection.execute(
        f"delete from knowledge_node_episodes where source_record_id in ({placeholders})", ids
    )
    connection.execute(
        f"delete from knowledge_episodes where source_record_id in ({placeholders})", ids
    )
    connection.execute(
        f"delete from knowledge_nodes where source_record_id in ({placeholders}) "
        "and id not in (select src_id from knowledge_edges) "
        "and id not in (select dst_id from knowledge_edges)",
        ids,
    )
    retained = connection.execute(
        f"select id from knowledge_nodes where source_record_id in ({placeholders})",
        ids,
    ).fetchall()
    for row in retained:
        node_id = str(row["id"])
        connection.execute(
            "update knowledge_nodes set kind = ?, label = ?, status = ?, confidence = 0, "
            "valid_from = null, valid_to = null, updated_at = ?, agent_id = null, "
            "source_record_id = null, synthetic = 1, properties_json = ? where id = ?",
            (
                _kind_from_id(node_id),
                _label_from_id(node_id),
                Status.ASSERTED.value,
                utc_now(),
                _json({"reference": node_id}),
                node_id,
            ),
        )


def supersede_source(
    connection: sqlite3.Connection,
    *,
    source_ref: str,
    except_document_id: str,
    superseded_at: str,
) -> None:
    suffix = except_document_id.split(":", 1)[-1]
    active_raw_prefix = f"raw:{suffix}:%"
    connection.execute(
        "update knowledge_episodes set status = 'superseded', expired_at = coalesce(expired_at, ?) "
        "where source_ref = ? and source_record_id not like ?",
        (superseded_at, source_ref, active_raw_prefix),
    )
    connection.execute(
        "update knowledge_edges set expired_at = coalesce(expired_at, ?), status = 'superseded', updated_at = ? "
        "where id in ("
        "  select ke.edge_id from knowledge_edge_episodes ke "
        "  join knowledge_episodes ep on ep.id = ke.episode_id "
        "  where ep.source_ref = ? and ep.status = 'superseded'"
        ") and not exists ("
        "  select 1 from knowledge_edge_episodes active_ke "
        "  join knowledge_episodes active_ep on active_ep.id = active_ke.episode_id "
        "  where active_ke.edge_id = knowledge_edges.id and active_ep.status = 'active'"
        ")",
        (superseded_at, superseded_at, source_ref),
    )


def query_graph(
    connection: sqlite3.Connection,
    *,
    query: str | None = None,
    root_id: str | None = None,
    namespace: str | None = None,
    scope: str | None = None,
    agent_id: str | None = None,
    kinds: Iterable[str] | None = None,
    at: str | None = None,
    include_history: bool = False,
    limit: int = 300,
    hops: int = 2,
) -> dict[str, object]:
    limit = max(1, min(int(limit), 1000))
    hops = max(0, min(int(hops), 5))
    query = (query or "").strip()
    kind_values = [kind.strip().lower() for kind in (kinds or []) if kind.strip()]
    canonical_kind_values = [kind for kind in kind_values if kind != "episode"]
    canonical_seeds_enabled = not kind_values or bool(canonical_kind_values)
    episode_seeds_enabled = not kind_values or "episode" in kind_values

    where = ["1=1"]
    params: list[object] = []
    if root_id and not root_id.startswith("episode:"):
        where.append("n.id = ?")
        params.append(root_id)
    if namespace:
        where.append("n.ns = ?")
        params.append(namespace)
    if scope:
        where.append("n.scope = ?")
        params.append(scope)
    if canonical_kind_values:
        where.append(f"lower(n.kind) in ({','.join('?' for _ in canonical_kind_values)})")
        params.extend(canonical_kind_values)
    if query:
        where.append("lower(n.id || ' ' || n.label || ' ' || n.properties_json) like ?")
        params.append(f"%{query.lower()}%")
    if agent_id:
        where.append(
            "(n.id = ? or n.agent_id = ? or exists ("
            " select 1 from knowledge_node_episodes ne"
            " join knowledge_episodes ep on ep.id = ne.episode_id"
            " where ne.node_id = n.id and ep.agent_id = ?))"
        )
        params.extend([_agent_node_id(agent_id), agent_id, agent_id])
    where.extend(_node_time_clauses(params, at=at, include_history=include_history))

    seed_limit = min(limit, 1 if root_id else (60 if query else 90))
    seed_rows = []
    if canonical_seeds_enabled and not (root_id and root_id.startswith("episode:")):
        seed_rows = connection.execute(
            "select n.id, ("
            " select count(*) from knowledge_edges e where e.src_id = n.id or e.dst_id = n.id"
            ") as degree from knowledge_nodes n "
            f"where {' and '.join(where)} "
            "order by degree desc, n.updated_at desc, n.id limit ?",
            [*params, seed_limit],
        ).fetchall()
    selected = {str(row["id"]) for row in seed_rows}

    episode_seed_rows: list[sqlite3.Row] = []
    if episode_seeds_enabled and (query or (root_id and root_id.startswith("episode:"))):
        episode_where, episode_params = _episode_filter_clauses(
            namespace=namespace,
            scope=scope,
            agent_id=agent_id,
            at=at,
            include_history=include_history,
        )
        if root_id:
            episode_where.append("ep.id = ?")
            episode_params.append(root_id)
        if query:
            episode_where.append(
                "lower(ep.id || ' ' || coalesce(ep.source_ref, '') || ' ' || "
                "ep.source_record_id || ' ' || ep.metadata_json) like ?"
            )
            episode_params.append(f"%{query.lower()}%")
        episode_seed_rows = connection.execute(
            "select ep.* from knowledge_episodes ep "
            f"where {' and '.join(episode_where)} order by ep.recorded_at desc, ep.id limit ?",
            [*episode_params, seed_limit],
        ).fetchall()
        episode_seed_ids = [str(row["id"]) for row in episode_seed_rows]
        if episode_seed_ids:
            placeholders = ",".join("?" for _ in episode_seed_ids)
            linked_rows = connection.execute(
                "select distinct ne.node_id from knowledge_node_episodes ne "
                f"where ne.episode_id in ({placeholders}) order by ne.node_id",
                episode_seed_ids,
            ).fetchall()
            for row in linked_rows:
                if len(selected) >= limit:
                    break
                selected.add(str(row["node_id"]))
    frontier = set(selected)
    edge_by_id: dict[str, sqlite3.Row] = {}

    for _ in range(hops):
        if not frontier or len(selected) >= limit:
            break
        placeholders = ",".join("?" for _ in frontier)
        edge_where = [f"(e.src_id in ({placeholders}) or e.dst_id in ({placeholders}))"]
        edge_params: list[object] = [*frontier, *frontier]
        if namespace:
            edge_where.append("e.ns = ?")
            edge_params.append(namespace)
        if scope:
            edge_where.append("e.scope = ?")
            edge_params.append(scope)
        edge_where.extend(_edge_time_clauses(edge_params, at=at, include_history=include_history))
        rows = connection.execute(
            "select e.* from knowledge_edges e "
            f"where {' and '.join(edge_where)} "
            "order by e.confidence desc, e.updated_at desc limit ?",
            [*edge_params, max(limit * 8, 200)],
        ).fetchall()
        next_frontier: set[str] = set()
        for row in rows:
            edge_by_id[str(row["id"])] = row
            for node_id in (str(row["src_id"]), str(row["dst_id"])):
                if node_id not in selected and len(selected) < limit:
                    selected.add(node_id)
                    next_frontier.add(node_id)
        frontier = next_frontier

    if not selected and not episode_seed_rows:
        return {
            "nodes": [],
            "edges": [],
            "stats": _graph_stats(connection, include_history=include_history),
            "facets": {"kinds": {}, "agents": {}, "sources": {}, "trust_states": {}},
            "query": _query_payload(query, root_id, namespace, scope, agent_id, kind_values, at, include_history, limit, hops),
            "generated_at": utc_now(),
        }

    node_rows: list[sqlite3.Row] = []
    if selected:
        placeholders = ",".join("?" for _ in selected)
        node_params: list[object] = [*selected]
        node_where = [f"n.id in ({placeholders})"]
        if namespace:
            node_where.append("n.ns = ?")
            node_params.append(namespace)
        if scope:
            node_where.append("n.scope = ?")
            node_params.append(scope)
        node_where.extend(_node_time_clauses(node_params, at=at, include_history=include_history))
        node_rows = connection.execute(
            f"select n.* from knowledge_nodes n where {' and '.join(node_where)}",
            node_params,
        ).fetchall()
    selected = {str(row["id"]) for row in node_rows}
    # Include all edges internal to the selected subgraph, not only the edges
    # that happened to discover the nodes during traversal.
    if selected:
        placeholders = ",".join("?" for _ in selected)
        edge_params = [*selected, *selected]
        edge_where = [
            f"e.src_id in ({placeholders})",
            f"e.dst_id in ({placeholders})",
        ]
        if namespace:
            edge_where.append("e.ns = ?")
            edge_params.append(namespace)
        if scope:
            edge_where.append("e.scope = ?")
            edge_params.append(scope)
        edge_where.extend(_edge_time_clauses(edge_params, at=at, include_history=include_history))
        for row in connection.execute(
            "select e.* from knowledge_edges e "
            f"where {' and '.join(edge_where)} order by e.confidence desc, e.id",
            edge_params,
        ).fetchall():
            edge_by_id[str(row["id"])] = row

    agents_by_node, sources_by_node = _node_episode_facets(
        connection,
        selected,
        namespace=namespace,
        scope=scope,
        agent_id=agent_id,
        at=at,
        include_history=include_history,
    )
    trust_by_node = _trust_profiles(
        connection,
        node_rows,
        at=at,
        include_history=include_history,
        namespace=namespace,
        scope=scope,
    )
    nodes: list[dict[str, object]] = [
        _node_payload(
            row,
            agents_by_node.get(str(row["id"]), []),
            sources_by_node.get(str(row["id"]), []),
            trust_by_node.get(str(row["id"])),
        )
        for row in node_rows
    ]
    episode_rows = _graph_episode_rows(
        connection,
        selected,
        set(edge_by_id),
        {str(row["id"]) for row in episode_seed_rows},
        namespace=namespace,
        scope=scope,
        agent_id=agent_id,
        at=at,
        include_history=include_history,
        limit=limit,
    )
    nodes.extend(_episode_node_payload(row) for row in episode_rows)
    provenance_edges = _episode_provenance_edges(connection, episode_rows, selected)
    degree = Counter()
    for row in edge_by_id.values():
        degree[str(row["src_id"])] += 1
        degree[str(row["dst_id"])] += 1
    for edge in provenance_edges:
        degree[str(edge["source"])] += 1
        degree[str(edge["target"])] += 1
    for node in nodes:
        node["degree"] = degree[node["id"]]
    nodes.sort(key=lambda node: (-int(node["degree"]), str(node["label"]).lower(), str(node["id"])))
    edges = [*(_edge_payload(row) for row in edge_by_id.values()), *provenance_edges]
    edges.sort(key=lambda edge: (-float(edge["confidence"]), str(edge["predicate"]), str(edge["id"])))
    return {
        "nodes": nodes,
        "edges": edges,
        "stats": _graph_stats(connection, include_history=include_history),
        "facets": {
            "kinds": dict(sorted(Counter(str(node["kind"]) for node in nodes).items())),
            "agents": dict(sorted(Counter(agent for node in nodes for agent in node["agents"]).items())),
            "sources": dict(sorted(Counter(source for node in nodes for source in node["sources"]).items())),
            "trust_states": dict(sorted(Counter(
                str(node["trust_state"])
                for node in nodes
                if node.get("trust_state") not in {None, "not_applicable", "evidence"}
            ).items())),
        },
        "query": _query_payload(query, root_id, namespace, scope, agent_id, kind_values, at, include_history, limit, hops),
        "generated_at": utc_now(),
    }


def node_detail(
    connection: sqlite3.Connection,
    node_id: str,
    *,
    include_history: bool = True,
    at: str | None = None,
) -> dict[str, object]:
    row = connection.execute("select * from knowledge_nodes where id = ?", (node_id,)).fetchone()
    if row is None:
        episode_where, episode_params = _episode_filter_clauses(
            namespace=None,
            scope=None,
            agent_id=None,
            at=at,
            include_history=include_history,
        )
        episode_where.append("ep.id = ?")
        episode_params.append(node_id)
        episode = connection.execute(
            "select ep.* from knowledge_episodes ep "
            f"where {' and '.join(episode_where)}",
            episode_params,
        ).fetchone()
        if episode is None:
            raise KeyError(node_id)
        graph = query_graph(
            connection,
            root_id=node_id,
            include_history=include_history,
            at=at,
            limit=120,
            hops=1,
        )
        node = next((item for item in graph["nodes"] if item["id"] == node_id), None)
        if node is None:
            raise KeyError(node_id)
        outgoing = [edge for edge in graph["edges"] if edge["source"] == node_id]
        incoming = [edge for edge in graph["edges"] if edge["target"] == node_id]
        record_row = connection.execute(
            "select payload_json from ir_records where id = ?",
            (episode["source_record_id"],),
        ).fetchone()
        record = None
        if record_row is not None:
            try:
                record = json.loads(record_row[0])
            except (json.JSONDecodeError, TypeError):
                record = None
        source_ref = str(episode["source_ref"] or "").strip()
        agent = str(episode["agent_id"]) if episode["agent_id"] else None
        return {
            "node": node,
            "record": record,
            "episodes": [_episode_payload(episode)],
            "outgoing": outgoing,
            "incoming": incoming,
            "neighbors": [item for item in graph["nodes"] if item["id"] != node_id],
            "page": {
                "title": str(node["label"]),
                "summary": (
                    f"{node['label']} was recorded at {episode['recorded_at']} and "
                    f"supports {len(outgoing)} knowledge nodes."
                ),
                "facts": outgoing,
                "backlinks": incoming,
                "sources": [source_ref] if source_ref else [],
                "agents": [agent] if agent else [],
            },
        }
    graph = query_graph(
        connection,
        root_id=node_id,
        include_history=include_history,
        at=at,
        limit=120,
        hops=1,
    )
    record_row = connection.execute(
        "select payload_json from ir_records where id = ?", (node_id,)
    ).fetchone()
    episode_where = ["ne.node_id = ?"]
    episode_params: list[object] = [node_id]
    if at:
        episode_where.extend([
            "ep.recorded_at <= ?",
            "(ep.expired_at is null or ep.expired_at > ?)",
        ])
        episode_params.extend([at, at])
    elif not include_history:
        episode_where.append("ep.status = 'active'")
    episodes = connection.execute(
        "select distinct ep.* from knowledge_episodes ep "
        "join knowledge_node_episodes ne on ne.episode_id = ep.id "
        f"where {' and '.join(episode_where)} order by ep.recorded_at desc",
        episode_params,
    ).fetchall()
    outgoing = [edge for edge in graph["edges"] if edge["source"] == node_id]
    incoming = [edge for edge in graph["edges"] if edge["target"] == node_id]
    node = next((item for item in graph["nodes"] if item["id"] == node_id), None)
    if node is None:
        raise KeyError(node_id)
    record = None
    if record_row is not None:
        try:
            record = json.loads(record_row[0])
        except (json.JSONDecodeError, TypeError):
            record = None
    return {
        "node": node,
        "record": record,
        "episodes": [_episode_payload(episode) for episode in episodes],
        "outgoing": outgoing,
        "incoming": incoming,
        "neighbors": [node for node in graph["nodes"] if node["id"] != node_id],
        "page": {
            "title": str(row["label"]),
            "summary": _page_summary(row, outgoing, incoming),
            "facts": [
                edge
                for edge in outgoing
                if edge["edge_kind"] == "semantic" or edge["predicate"] == "contributed"
            ],
            "backlinks": incoming,
            "sources": sorted({str(episode["source_ref"]) for episode in episodes if episode["source_ref"]}),
            "agents": sorted({str(episode["agent_id"]) for episode in episodes if episode["agent_id"]}),
        },
    }


def assertable_record_ids(
    connection: sqlite3.Connection,
    record_ids: Iterable[str],
    *,
    at: str | None = None,
    namespace: str | None = None,
    scope: str | None = None,
) -> set[str]:
    """Return records safe to place in an asserted answer context.

    The gate is fail-closed for unknown ids. Claim-like MIRL records (CLM,
    REL, EVT, STA) pass only when their derived trust state is ``supported`` or
    ``verified``. Evidence and descriptive records may pass when current unless
    their only provenance is model/agent output; they never independently
    upgrade a model-produced claim. ``at`` evaluates
    the same rule at a historical knowledge horizon.

    This function does not delete or hide rejected records from graph
    exploration; callers use the returned id set only at an asserted-context
    boundary. Optional namespace/scope constraints are fail-closed: ids outside
    either boundary are absent from the result.
    """

    ids = sorted({str(record_id) for record_id in record_ids if str(record_id).strip()})
    if not ids:
        return set()
    placeholders = ",".join("?" for _ in ids)
    where = [f"id in ({placeholders})"]
    params: list[object] = list(ids)
    if namespace:
        where.append("ns = ?")
        params.append(namespace)
    if scope:
        where.append("scope = ?")
        params.append(scope)
    rows = connection.execute(
        f"select * from knowledge_nodes where {' and '.join(where)}",
        params,
    ).fetchall()
    profiles = _trust_profiles(
        connection,
        rows,
        at=at,
        include_history=bool(at),
        namespace=namespace,
        scope=scope,
    )
    allowed: set[str] = set()
    for row in rows:
        record_id = str(row["id"])
        if not _node_visible_at(row, at=at):
            continue
        kind = str(row["kind"])
        if kind not in ASSERTION_KINDS:
            profile = profiles[record_id]
            if not (
                profile["model_output_evidence_count"]
                and not profile["independent_evidence_count"]
            ):
                allowed.add(record_id)
            continue
        if profiles[record_id]["trust_state"] in ASSERTABLE_TRUST_STATES:
            allowed.add(record_id)
    return allowed


def graph_stats(connection: sqlite3.Connection, *, include_history: bool = False) -> dict[str, object]:
    return _graph_stats(connection, include_history=include_history)


def _project_record(
    connection: sqlite3.Connection,
    record: MIRLRecord,
    batch_by_id: dict[str, MIRLRecord],
) -> None:
    agent_id = _record_agent(connection, record, batch_by_id)
    label = _record_label(record, batch_by_id)
    facets = _record_facets(record)
    epistemic_basis = _epistemic_basis(record)
    properties = {
        "record_kind": record.kind.value,
        "attrs": {key: value for key, value in record.attrs.items() if key != "content"},
        "ext": record.ext,
        "facets": facets,
        "epistemic_basis": epistemic_basis,
    }
    if record.kind == RecordKind.RAW:
        content = str(record.attrs.get("content") or "")
        properties["content_preview"] = _truncate(content, 240)
    _upsert_node(
        connection,
        node_id=record.id,
        kind=_KIND_NAMES[record.kind],
        label=label,
        record=record,
        agent_id=agent_id,
        properties=properties,
        synthetic=False,
    )

    episode_ids = _episode_ids(connection, record, batch_by_id, agent_id)
    for episode_id in episode_ids:
        connection.execute(
            "insert or ignore into knowledge_node_episodes (node_id, episode_id, source_record_id) values (?, ?, ?)",
            (record.id, episode_id, record.id),
        )

    def reference(value: object, *, literal: bool = False) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if literal or ":" not in text:
            node_id = _value_node_id(record.ns, record.scope, text)
            kind = "value"
            node_label = text
        else:
            node_id = text
            target = batch_by_id.get(text) or _load_record(connection, text)
            kind = _KIND_NAMES[target.kind] if target is not None else _kind_from_id(text)
            node_label = _record_label(target, batch_by_id) if target is not None else _label_from_id(text)
        _upsert_node(
            connection,
            node_id=node_id,
            kind=kind,
            label=node_label,
            record=record,
            agent_id=agent_id,
            properties={"reference": text},
            synthetic=node_id != record.id,
        )
        for episode_id in episode_ids:
            connection.execute(
                "insert or ignore into knowledge_node_episodes (node_id, episode_id, source_record_id) values (?, ?, ?)",
                (node_id, episode_id, record.id),
            )
        return node_id

    def edge(src: str | None, predicate: str, dst: str | None, edge_kind: str, **extra: object) -> None:
        if not src or not dst or src == dst:
            return
        family = predicate_family(predicate, edge_kind)
        projected_kind = family if edge_kind == "semantic" and family != "semantic" else edge_kind
        edge_id = _edge_id(record.id, src, predicate, dst, projected_kind)
        edge_properties = {
            "semantic_family": family,
            "epistemic_basis": epistemic_basis,
            **extra,
        }
        connection.execute(
            "insert or replace into knowledge_edges "
            "(id, src_id, dst_id, predicate, edge_kind, ns, scope, status, confidence, valid_from, valid_to, "
            " created_at, updated_at, expired_at, agent_id, source_record_id, properties_json) "
            "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                edge_id,
                src,
                dst,
                predicate or "related_to",
                projected_kind,
                record.ns,
                record.scope,
                record.status.value,
                float(record.conf),
                record.t0,
                record.t1,
                record.created_at,
                record.updated_at,
                record.updated_at if record.status.value in CURRENT_EXCLUDED_STATUSES else None,
                agent_id,
                record.id,
                _json(edge_properties),
            ),
        )
        for episode_id in episode_ids:
            connection.execute(
                "insert or ignore into knowledge_edge_episodes (edge_id, episode_id) values (?, ?)",
                (edge_id, episode_id),
            )

    if agent_id:
        agent_node = _agent_node_id(agent_id)
        _upsert_node(
            connection,
            node_id=agent_node,
            kind="agent",
            label=agent_id,
            record=record,
            agent_id=agent_id,
            properties={"agent_id": agent_id},
            synthetic=True,
        )
        # Agent identities are stable graph concepts, not canonical MIRL
        # records owned by whichever contribution happened to be projected
        # most recently. Their contribution edges and episodes carry the
        # source lifecycle; the identity node remains while any edge uses it.
        connection.execute(
            "update knowledge_nodes set kind = 'agent', label = ?, status = ?, confidence = 1, "
            "valid_from = null, valid_to = null, agent_id = ?, source_record_id = null, "
            "synthetic = 1, properties_json = ? where id = ?",
            (
                agent_id,
                Status.ASSERTED.value,
                agent_id,
                _json({"agent_id": agent_id}),
                agent_node,
            ),
        )
        for episode_id in episode_ids:
            connection.execute(
                "insert or ignore into knowledge_node_episodes (node_id, episode_id, source_record_id) values (?, ?, ?)",
                (agent_node, episode_id, record.id),
            )
        edge(agent_node, "contributed", record.id, "provenance")

    for provenance in record.prov:
        edge(record.id, "provenance", reference(provenance), "provenance")
    for evidence in record.evidence:
        edge(record.id, "evidence", reference(evidence), "provenance")

    attrs = record.attrs
    if record.kind == RecordKind.CLM:
        subject = reference(attrs.get("subject"))
        obj_value = attrs.get("object")
        obj = reference(obj_value, literal=not (isinstance(obj_value, str) and ":" in obj_value))
        predicate = str(attrs.get("predicate") or "asserts")
        edge(record.id, "about", subject, "grounding")
        edge(record.id, "object", obj, "grounding")
        edge(subject, predicate, obj, "semantic", claim_id=record.id, facets=facets)
    elif record.kind == RecordKind.REL:
        src = reference(attrs.get("src"))
        dst = reference(attrs.get("dst"))
        predicate = str(attrs.get("predicate") or "related_to")
        edge(record.id, "subject", src, "grounding")
        edge(record.id, "object", dst, "grounding")
        edge(src, predicate, dst, "semantic", relation_id=record.id, facets=facets)
    elif record.kind == RecordKind.EVT:
        actor = reference(attrs.get("actor") or attrs.get("subject"))
        obj = reference(attrs.get("object"), literal=not isinstance(attrs.get("object"), str))
        edge(actor, "participated_in", record.id, "semantic")
        edge(record.id, "object", obj, "semantic")
    elif record.kind == RecordKind.STA:
        target = reference(attrs.get("target") or attrs.get("subject"))
        edge(target, "has_state", record.id, "semantic")
    elif record.kind == RecordKind.SPAN:
        edge(record.id, "excerpt_of", reference(attrs.get("raw_id")), "provenance")
    elif record.kind == RecordKind.PROV:
        entity = reference(attrs.get("entity"))
        edge(_agent_node_id(agent_id) if agent_id else record.id, str(attrs.get("activity") or "produced"), entity, "provenance")
    elif record.kind == RecordKind.FLOW:
        edge(reference(attrs.get("src")), str(attrs.get("predicate") or "flows_to"), reference(attrs.get("dst")), "semantic")

    # 5W1H+Then is a derived, rebuildable lens over canonical MIRL. Keep the
    # original open predicate above and add only grounded facet links here.
    for facet, value in facets.items():
        if facet not in _FACET_PREDICATES:
            continue
        is_reference = isinstance(value, str) and (
            value in batch_by_id
            or value.split(":", 1)[0].lower() in _PREFIX_KINDS
        )
        edge(
            record.id,
            facet,
            reference(value, literal=not is_reference),
            "facet",
            canonical_predicate=_FACET_PREDICATES[facet],
        )

    # Explicit reconciliation pointers may be supplied as MIRL extension
    # fields. They become typed graph relations but never replace old records.
    for predicate in (*sorted(EPISTEMIC_PREDICATES), "supersedes"):
        for target in _reference_values(record.ext.get(predicate) or attrs.get(predicate)):
            edge(record.id, predicate, reference(target), predicate_family(predicate))


def _episode_ids(
    connection: sqlite3.Connection,
    record: MIRLRecord,
    batch_by_id: dict[str, MIRLRecord],
    agent_id: str | None,
) -> list[str]:
    raw_ids: set[str] = set()
    if record.kind == RecordKind.RAW:
        raw_ids.add(record.id)
    if record.kind == RecordKind.SPAN and record.attrs.get("raw_id"):
        raw_ids.add(str(record.attrs["raw_id"]))
    for ref in [*record.prov, *record.evidence]:
        target = batch_by_id.get(ref) or _load_record(connection, ref)
        if target is None:
            continue
        if target.kind == RecordKind.RAW:
            raw_ids.add(target.id)
        elif target.kind == RecordKind.SPAN and target.attrs.get("raw_id"):
            raw_ids.add(str(target.attrs["raw_id"]))
        elif target.kind == RecordKind.PROV and target.attrs.get("entity"):
            entity = str(target.attrs["entity"])
            if entity.startswith("raw:"):
                raw_ids.add(entity)

    episode_ids: list[str] = []
    for raw_id in sorted(raw_ids):
        raw = batch_by_id.get(raw_id) or _load_record(connection, raw_id)
        if raw is None:
            continue
        raw_agent = _record_agent(connection, raw, batch_by_id) or agent_id
        content = str(raw.attrs.get("content") or "")
        episode_id = f"episode:{hashlib.sha256(raw.id.encode('utf-8')).hexdigest()[:20]}"
        connection.execute(
            "insert into knowledge_episodes "
            "(id, source_record_id, source_ref, content_hash, agent_id, ns, scope, status, valid_at, recorded_at, expired_at, metadata_json) "
            "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "on conflict(id) do update set "
            "source_record_id = excluded.source_record_id, source_ref = excluded.source_ref, "
            "content_hash = excluded.content_hash, agent_id = excluded.agent_id, ns = excluded.ns, "
            "scope = excluded.scope, valid_at = excluded.valid_at, recorded_at = excluded.recorded_at, "
            "metadata_json = excluded.metadata_json",
            (
                episode_id,
                raw.id,
                str(raw.attrs.get("source_ref") or ""),
                hashlib.sha256(content.encode("utf-8")).hexdigest(),
                raw_agent,
                raw.ns,
                raw.scope,
                "active",
                raw.t0,
                raw.created_at,
                None,
                _json({
                    "media_type": raw.attrs.get("media_type"),
                    "byte_count": len(content.encode("utf-8")),
                    "source_type": raw.attrs.get("source_type") or raw.ext.get("source_type"),
                    "model_output": bool(raw.attrs.get("model_output") or raw.ext.get("model_output")),
                }),
            ),
        )
        episode_ids.append(episode_id)
    if not episode_ids and agent_id and record.kind in {
        RecordKind.CLM,
        RecordKind.EVT,
        RecordKind.REL,
        RecordKind.STA,
        RecordKind.FLOW,
        RecordKind.META,
    }:
        # Structured agent writes may arrive without a RAW wrapper. The MIRL
        # record is then itself the immutable source episode, so its agent and
        # provenance remain visible rather than becoming an unattributed edge.
        source_ref = str(record.ext.get("source_ref") or f"mirl://{record.id}")
        serialized = record.to_text_line()
        episode_id = f"episode:{hashlib.sha256(('direct:' + record.id).encode('utf-8')).hexdigest()[:20]}"
        connection.execute(
            "insert into knowledge_episodes "
            "(id, source_record_id, source_ref, content_hash, agent_id, ns, scope, status, valid_at, recorded_at, expired_at, metadata_json) "
            "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "on conflict(id) do update set "
            "source_record_id = excluded.source_record_id, source_ref = excluded.source_ref, "
            "content_hash = excluded.content_hash, agent_id = excluded.agent_id, ns = excluded.ns, "
            "scope = excluded.scope, valid_at = excluded.valid_at, recorded_at = excluded.recorded_at, "
            "metadata_json = excluded.metadata_json",
            (
                episode_id,
                record.id,
                source_ref,
                hashlib.sha256(serialized.encode("utf-8")).hexdigest(),
                agent_id,
                record.ns,
                record.scope,
                "active",
                record.t0,
                record.created_at,
                None,
                _json({"media_type": "application/x-seam-mirl", "direct_mirl": True}),
            ),
        )
        episode_ids.append(episode_id)
    return episode_ids


def _upsert_node(
    connection: sqlite3.Connection,
    *,
    node_id: str,
    kind: str,
    label: str,
    record: MIRLRecord,
    agent_id: str | None,
    properties: dict[str, object],
    synthetic: bool,
) -> None:
    connection.execute(
        "insert into knowledge_nodes "
        "(id, kind, label, ns, scope, status, confidence, valid_from, valid_to, created_at, updated_at, "
        " agent_id, source_record_id, synthetic, properties_json) "
        "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "on conflict(id) do update set "
        "kind = case when excluded.synthetic = 0 then excluded.kind else knowledge_nodes.kind end, "
        "label = case when excluded.synthetic = 0 then excluded.label else knowledge_nodes.label end, "
        "ns = case when excluded.synthetic = 0 then excluded.ns else knowledge_nodes.ns end, "
        "scope = case when excluded.synthetic = 0 then excluded.scope else knowledge_nodes.scope end, "
        "status = case when excluded.synthetic = 0 then excluded.status else knowledge_nodes.status end, "
        "confidence = case when excluded.synthetic = 0 then excluded.confidence else max(knowledge_nodes.confidence, excluded.confidence) end, "
        "valid_from = case when excluded.synthetic = 0 then excluded.valid_from else knowledge_nodes.valid_from end, "
        "valid_to = case when excluded.synthetic = 0 then excluded.valid_to else knowledge_nodes.valid_to end, "
        "created_at = case when excluded.synthetic = 0 then excluded.created_at else knowledge_nodes.created_at end, "
        "updated_at = case when excluded.synthetic = 0 then excluded.updated_at else max(knowledge_nodes.updated_at, excluded.updated_at) end, "
        "agent_id = case when excluded.synthetic = 0 then excluded.agent_id else knowledge_nodes.agent_id end, "
        "source_record_id = case when excluded.synthetic = 0 then excluded.source_record_id else knowledge_nodes.source_record_id end, "
        "synthetic = min(knowledge_nodes.synthetic, excluded.synthetic), "
        "properties_json = case when excluded.synthetic = 0 then excluded.properties_json else knowledge_nodes.properties_json end",
        (
            node_id,
            kind,
            _truncate(label or node_id, 180),
            record.ns,
            record.scope,
            record.status.value,
            float(record.conf),
            record.t0,
            record.t1,
            record.created_at,
            record.updated_at,
            agent_id,
            record.id,
            int(synthetic),
            _json(properties),
        ),
    )


def _record_agent(
    connection: sqlite3.Connection,
    record: MIRLRecord,
    batch_by_id: dict[str, MIRLRecord],
) -> str | None:
    for value in (
        record.ext.get("agent_id"),
        record.ext.get("agent"),
        record.attrs.get("agent") if record.kind == RecordKind.PROV else None,
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    if record.kind == RecordKind.RAW:
        source_ref = str(record.attrs.get("source_ref") or "")
        if source_ref.startswith("agent://"):
            candidate = source_ref.removeprefix("agent://").split("/", 1)[0].strip()
            if candidate and candidate != "input":
                return candidate
        for candidate_record in batch_by_id.values():
            if candidate_record.kind != RecordKind.PROV:
                continue
            if candidate_record.attrs.get("entity") != record.id:
                continue
            value = candidate_record.attrs.get("agent") or candidate_record.ext.get("agent_id")
            if isinstance(value, str) and value.strip():
                return value.strip()
        provenance_row = connection.execute(
            "select agent from prov_log where entity = ? and agent is not null order by id limit 1",
            (record.id,),
        ).fetchone()
        if provenance_row is not None and str(provenance_row[0]).strip():
            return str(provenance_row[0]).strip()
    for prov_id in record.prov:
        prov = batch_by_id.get(prov_id) or _load_record(connection, prov_id)
        if prov is not None:
            value = prov.attrs.get("agent") or prov.ext.get("agent_id")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _record_label(record: MIRLRecord, batch_by_id: dict[str, MIRLRecord]) -> str:
    attrs = record.attrs
    if record.kind == RecordKind.ENT:
        return str(attrs.get("label") or attrs.get("name") or record.id)
    if record.kind == RecordKind.CLM:
        return _join_label(attrs.get("subject"), attrs.get("predicate"), attrs.get("object"))
    if record.kind == RecordKind.REL:
        return _join_label(attrs.get("src"), attrs.get("predicate"), attrs.get("dst"))
    if record.kind == RecordKind.EVT:
        return _join_label(attrs.get("actor") or attrs.get("subject"), attrs.get("action") or attrs.get("predicate"), attrs.get("object"))
    if record.kind == RecordKind.STA:
        return _join_label(attrs.get("target") or attrs.get("subject"), "state", attrs.get("fields") or attrs.get("object"))
    if record.kind == RecordKind.RAW:
        return str(attrs.get("source_ref") or _truncate(str(attrs.get("content") or ""), 80) or record.id)
    if record.kind == RecordKind.SPAN:
        return f"Evidence span {attrs.get('start', 0)}:{attrs.get('end', 0)}"
    if record.kind == RecordKind.PROV:
        return _join_label(attrs.get("agent"), attrs.get("activity"), attrs.get("entity"))
    if record.kind == RecordKind.SYM:
        return str(attrs.get("symbol") or attrs.get("expansion") or record.id)
    return str(attrs.get("label") or attrs.get("name") or record.id)


def _epistemic_basis(record: MIRLRecord) -> str:
    declared = str(record.ext.get("epistemic_basis") or "").strip().lower()
    if declared in {"explicit", "inferred", "hypothetical"}:
        return declared
    if record.status == Status.HYPOTHETICAL:
        return "hypothetical"
    if record.status == Status.INFERRED:
        return "inferred"
    return "explicit"


def _record_facets(record: MIRLRecord) -> dict[str, object]:
    """Build a conservative 5W1H+Then projection from canonical MIRL.

    Explicit ``attrs.facets`` values win. Fallbacks use only already-present
    MIRL fields and known predicate families; this function never invents a
    missing why/how/where value.
    """

    attrs = record.attrs
    supplied = attrs.get("facets")
    facets: dict[str, object] = (
        {
            str(key): value
            for key, value in supplied.items()
            if str(key) in _FACET_PREDICATES and value not in (None, "", [], {})
        }
        if isinstance(supplied, Mapping)
        else {}
    )

    predicate = str(attrs.get("predicate") or attrs.get("action") or "").strip().lower()
    family = predicate_family(predicate)
    subject = attrs.get("subject") or attrs.get("actor") or attrs.get("src") or attrs.get("target")
    obj = attrs.get("object") or attrs.get("dst")
    if subject not in (None, ""):
        # Prefer the canonical entity/reference id to an extractor's surface
        # spelling so the facet connects to the real person/agent node.
        facets["who"] = subject
    if obj not in (None, ""):
        facets.setdefault("what", obj)
    when = attrs.get("when") or attrs.get("timestamp") or attrs.get("ts") or record.t0
    if when not in (None, ""):
        facets.setdefault("when", when)
    where = attrs.get("where") or attrs.get("location")
    if where not in (None, ""):
        facets.setdefault("where", where)
    why = attrs.get("why") or attrs.get("reason")
    if why not in (None, ""):
        facets.setdefault("why", why)
    how = attrs.get("how") or attrs.get("method") or attrs.get("via")
    if how not in (None, ""):
        facets.setdefault("how", how)
    then = attrs.get("then") or attrs.get("result") or attrs.get("outcome")
    if then not in (None, ""):
        facets.setdefault("then", then)

    if obj not in (None, ""):
        if predicate in {"location", "located_in", "at"}:
            facets.setdefault("where", obj)
        if family == "causal":
            if predicate in {"resulted_in", "leads_to", "causes"}:
                facets.setdefault("then", obj)
            else:
                facets.setdefault("why", obj)
        if family == "temporal":
            facets.setdefault("then", obj)
        if predicate in {"via", "used_tool", "used_method", "method"}:
            facets.setdefault("how", obj)
    return facets


def _reference_values(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set, frozenset)):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _node_time_clauses(params: list[object], *, at: str | None, include_history: bool) -> list[str]:
    clauses: list[str] = []
    if at:
        placeholders = ",".join("?" for _ in CURRENT_EXCLUDED_STATUSES)
        clauses.extend([
            "coalesce(n.valid_from, n.created_at) <= ?",
            "(n.valid_to is null or n.valid_to > ?)",
            f"(n.status not in ({placeholders}) or n.updated_at > ?)",
            "(not exists (select 1 from knowledge_node_episodes ne where ne.node_id = n.id) "
            "or exists (select 1 from knowledge_node_episodes ne join knowledge_episodes ep on ep.id = ne.episode_id "
            "where ne.node_id = n.id and ep.recorded_at <= ? and (ep.expired_at is null or ep.expired_at > ?)))",
        ])
        params.extend([at, at, *sorted(CURRENT_EXCLUDED_STATUSES), at, at, at])
    elif not include_history:
        placeholders = ",".join("?" for _ in CURRENT_EXCLUDED_STATUSES)
        clauses.append(f"n.status not in ({placeholders})")
        params.extend(sorted(CURRENT_EXCLUDED_STATUSES))
        clauses.append(
            "(not exists (select 1 from knowledge_node_episodes ne where ne.node_id = n.id) "
            "or exists (select 1 from knowledge_node_episodes ne join knowledge_episodes ep on ep.id = ne.episode_id "
            "where ne.node_id = n.id and ep.status = 'active'))"
        )
    return clauses


def _edge_time_clauses(params: list[object], *, at: str | None, include_history: bool) -> list[str]:
    clauses: list[str] = []
    if at:
        clauses.extend([
            "coalesce(e.valid_from, e.created_at) <= ?",
            "(e.valid_to is null or e.valid_to > ?)",
            "(e.expired_at is null or e.expired_at > ?)",
        ])
        params.extend([at, at, at])
    elif not include_history:
        placeholders = ",".join("?" for _ in CURRENT_EXCLUDED_STATUSES)
        clauses.extend([f"e.status not in ({placeholders})", "e.expired_at is null"])
        params.extend(sorted(CURRENT_EXCLUDED_STATUSES))
        clauses.append(
            "(not exists (select 1 from knowledge_edge_episodes ee where ee.edge_id = e.id) "
            "or exists (select 1 from knowledge_edge_episodes ee join knowledge_episodes ep on ep.id = ee.episode_id "
            "where ee.edge_id = e.id and ep.status = 'active'))"
        )
    return clauses


def _episode_filter_clauses(
    *,
    namespace: str | None,
    scope: str | None,
    agent_id: str | None,
    at: str | None,
    include_history: bool,
) -> tuple[list[str], list[object]]:
    clauses = ["1=1"]
    params: list[object] = []
    if namespace:
        clauses.append("ep.ns = ?")
        params.append(namespace)
    if scope:
        clauses.append("ep.scope = ?")
        params.append(scope)
    if agent_id:
        clauses.append("ep.agent_id = ?")
        params.append(agent_id)
    if at:
        clauses.extend([
            "ep.recorded_at <= ?",
            "(ep.expired_at is null or ep.expired_at > ?)",
        ])
        params.extend([at, at])
    elif not include_history:
        clauses.append("ep.status = 'active'")
    return clauses, params


def _graph_episode_rows(
    connection: sqlite3.Connection,
    node_ids: set[str],
    edge_ids: set[str],
    seed_episode_ids: set[str],
    *,
    namespace: str | None,
    scope: str | None,
    agent_id: str | None,
    at: str | None,
    include_history: bool,
    limit: int,
) -> list[sqlite3.Row]:
    relationship_clauses: list[str] = []
    relationship_params: list[object] = []
    if seed_episode_ids:
        placeholders = ",".join("?" for _ in seed_episode_ids)
        relationship_clauses.append(f"ep.id in ({placeholders})")
        relationship_params.extend(sorted(seed_episode_ids))
    if node_ids:
        placeholders = ",".join("?" for _ in node_ids)
        relationship_clauses.append(
            "exists (select 1 from knowledge_node_episodes ne "
            f"where ne.episode_id = ep.id and ne.node_id in ({placeholders}))"
        )
        relationship_params.extend(sorted(node_ids))
    if edge_ids:
        placeholders = ",".join("?" for _ in edge_ids)
        relationship_clauses.append(
            "exists (select 1 from knowledge_edge_episodes ee "
            f"where ee.episode_id = ep.id and ee.edge_id in ({placeholders}))"
        )
        relationship_params.extend(sorted(edge_ids))
    if not relationship_clauses:
        return []
    filters, filter_params = _episode_filter_clauses(
        namespace=namespace,
        scope=scope,
        agent_id=agent_id,
        at=at,
        include_history=include_history,
    )
    order_params: list[object] = []
    if seed_episode_ids:
        placeholders = ",".join("?" for _ in seed_episode_ids)
        order = f"case when ep.id in ({placeholders}) then 0 else 1 end, "
        order_params.extend(sorted(seed_episode_ids))
    else:
        order = ""
    return connection.execute(
        "select ep.* from knowledge_episodes ep "
        f"where ({' or '.join(relationship_clauses)}) and {' and '.join(filters)} "
        f"order by {order}ep.recorded_at desc, ep.id limit ?",
        [*relationship_params, *filter_params, *order_params, limit],
    ).fetchall()


def _episode_provenance_edges(
    connection: sqlite3.Connection,
    episode_rows: list[sqlite3.Row],
    node_ids: set[str],
) -> list[dict[str, object]]:
    if not episode_rows or not node_ids:
        return []
    episode_by_id = {str(row["id"]): row for row in episode_rows}
    episode_placeholders = ",".join("?" for _ in episode_by_id)
    node_placeholders = ",".join("?" for _ in node_ids)
    links = connection.execute(
        "select distinct ne.episode_id, ne.node_id, ne.source_record_id "
        "from knowledge_node_episodes ne "
        f"where ne.episode_id in ({episode_placeholders}) "
        f"and ne.node_id in ({node_placeholders}) order by ne.episode_id, ne.node_id",
        [*sorted(episode_by_id), *sorted(node_ids)],
    ).fetchall()
    contributors_by_link: dict[tuple[str, str], set[str]] = {}
    for link in links:
        key = (str(link["episode_id"]), str(link["node_id"]))
        contributors_by_link.setdefault(key, set()).add(str(link["source_record_id"]))

    edges: list[dict[str, object]] = []
    for (episode_id, node_id), contributor_ids in sorted(contributors_by_link.items()):
        episode = episode_by_id[episode_id]
        independent = _episode_is_independent(episode)
        predicate = "supports" if independent else "unverified_by"
        material = "\x1f".join((episode_id, predicate, node_id))
        edges.append({
            "id": f"kgep:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}",
            "source": episode_id,
            "target": node_id,
            "predicate": predicate,
            "edge_kind": "provenance" if independent else "epistemic",
            "semantic_family": "provenance" if independent else "epistemic",
            "epistemic_basis": "explicit",
            "namespace": str(episode["ns"]),
            "scope": str(episode["scope"]),
            "status": str(episode["status"]),
            "confidence": 1.0,
            "valid_from": episode["valid_at"] or episode["recorded_at"],
            "valid_to": episode["expired_at"],
            "created_at": str(episode["recorded_at"]),
            "updated_at": str(episode["expired_at"] or episode["recorded_at"]),
            "expired_at": episode["expired_at"],
            "agent_id": episode["agent_id"],
            "source_record_id": str(episode["source_record_id"]),
            "properties": {
                "projection": "episode_provenance",
                "episode_source_record_id": str(episode["source_record_id"]),
                "contributing_record_ids": sorted(contributor_ids),
                "independent_evidence": independent,
            },
        })
    return edges


def _node_episode_facets(
    connection: sqlite3.Connection,
    node_ids: set[str],
    *,
    namespace: str | None,
    scope: str | None,
    agent_id: str | None,
    at: str | None,
    include_history: bool,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    if not node_ids:
        return {}, {}
    placeholders = ",".join("?" for _ in node_ids)
    where = [f"ne.node_id in ({placeholders})"]
    params: list[object] = list(node_ids)
    if namespace:
        where.append("ep.ns = ?")
        params.append(namespace)
    if scope:
        where.append("ep.scope = ?")
        params.append(scope)
    if agent_id:
        where.append("ep.agent_id = ?")
        params.append(agent_id)
    if at:
        where.extend([
            "ep.recorded_at <= ?",
            "(ep.expired_at is null or ep.expired_at > ?)",
        ])
        params.extend([at, at])
    elif not include_history:
        where.append("ep.status = 'active'")
    rows = connection.execute(
        "select distinct ne.node_id, ep.agent_id, ep.source_ref "
        "from knowledge_node_episodes ne join knowledge_episodes ep on ep.id = ne.episode_id "
        f"where {' and '.join(where)}",
        params,
    ).fetchall()
    agents: dict[str, set[str]] = {}
    sources: dict[str, set[str]] = {}
    for row in rows:
        node_id = str(row["node_id"])
        if row["agent_id"]:
            agents.setdefault(node_id, set()).add(str(row["agent_id"]))
        if row["source_ref"]:
            sources.setdefault(node_id, set()).add(str(row["source_ref"]))
    return (
        {key: sorted(values) for key, values in agents.items()},
        {key: sorted(values) for key, values in sources.items()},
    )


def _episode_is_independent(row: sqlite3.Row) -> bool:
    """Whether an episode is independent evidence rather than model output."""

    metadata = json.loads(row["metadata_json"] or "{}")
    source_type = str(metadata.get("source_type") or "").strip().lower()
    if metadata.get("model_output") or metadata.get("direct_mirl"):
        return False
    if source_type in {"model", "model_output", "llm", "reasoning_summary", "provider_trace"}:
        return False
    source_ref = str(row["source_ref"] or "").strip().lower()
    if source_ref.startswith("chat://") and source_ref.rstrip("/").endswith(("/assistant", "/model")):
        return False
    if source_ref.startswith("agent://") and row["agent_id"]:
        return False
    return True


def _evidence_key(row: sqlite3.Row) -> str:
    source_ref = str(row["source_ref"] or "").strip()
    if source_ref:
        return f"source:{source_ref}"
    content_hash = str(row["content_hash"] or "").strip()
    return f"content:{content_hash}" if content_hash else f"episode:{row['id']}"


def _node_visible_at(row: sqlite3.Row, *, at: str | None) -> bool:
    status = str(row["status"])
    if at is None:
        return status not in CURRENT_EXCLUDED_STATUSES and not _time_reached(row["valid_to"], utc_now())
    start = row["valid_from"] or row["created_at"]
    end = row["valid_to"]
    if start and str(start) > at:
        return False
    if end and str(end) <= at:
        return False
    return status not in CURRENT_EXCLUDED_STATUSES or str(row["updated_at"]) > at


def _time_reached(value: object, horizon: str) -> bool:
    if value in (None, ""):
        return False
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) <= datetime.fromisoformat(
            horizon.replace("Z", "+00:00")
        )
    except ValueError:
        return str(value) <= horizon


def _trust_profiles(
    connection: sqlite3.Connection,
    node_rows: Iterable[sqlite3.Row],
    *,
    at: str | None,
    include_history: bool,
    namespace: str | None = None,
    scope: str | None = None,
) -> dict[str, dict[str, object]]:
    """Derive tenant-isolated trust from episodes and epistemic edges.

    An incoming epistemic edge is usable only when the edge, its source node,
    and every evidence episode used from that path share the target claim's
    namespace and scope. ``namespace``/``scope`` add an explicit fail-closed
    caller boundary. Support and corroboration edges must also carry their own
    independent episode; an evidenced source cannot validate an unevidenced
    model-produced relation.
    """

    rows = list(node_rows)
    if not rows:
        return {}
    ids = {str(row["id"]) for row in rows}
    placeholders = ",".join("?" for _ in ids)

    edge_params: list[object] = [*sorted(ids)]
    edge_where = [
        f"e.dst_id in ({placeholders})",
        f"lower(e.predicate) in ({','.join('?' for _ in EPISTEMIC_PREDICATES | {'supersedes'})})",
    ]
    edge_params.extend(sorted(EPISTEMIC_PREDICATES | {"supersedes"}))
    edge_where.extend(_edge_time_clauses(edge_params, at=at, include_history=include_history))
    candidate_edges = connection.execute(
        "select e.* from knowledge_edges e "
        f"where {' and '.join(edge_where)} order by e.id",
        edge_params,
    ).fetchall()

    source_ids = {str(edge["src_id"]) for edge in candidate_edges}
    source_rows: list[sqlite3.Row] = []
    if source_ids:
        source_placeholders = ",".join("?" for _ in source_ids)
        source_rows = connection.execute(
            f"select * from knowledge_nodes where id in ({source_placeholders})",
            sorted(source_ids),
        ).fetchall()
    node_by_id = {str(row["id"]): row for row in [*rows, *source_rows]}
    target_by_id = {str(row["id"]): row for row in rows}

    def same_tenant(candidate: sqlite3.Row, target: sqlite3.Row) -> bool:
        if str(candidate["ns"]) != str(target["ns"]) or str(candidate["scope"]) != str(target["scope"]):
            return False
        if namespace is not None and str(candidate["ns"]) != namespace:
            return False
        if scope is not None and str(candidate["scope"]) != scope:
            return False
        return True

    epistemic_edges: list[sqlite3.Row] = []
    for edge in candidate_edges:
        target = target_by_id.get(str(edge["dst_id"]))
        source = node_by_id.get(str(edge["src_id"]))
        if target is None or source is None:
            continue
        if not same_tenant(edge, target) or not same_tenant(source, target):
            continue
        epistemic_edges.append(edge)

    evidence_node_ids = ids | {str(edge["src_id"]) for edge in epistemic_edges}
    evidence_placeholders = ",".join("?" for _ in evidence_node_ids)
    episode_where = [f"ne.node_id in ({evidence_placeholders})"]
    episode_params: list[object] = [*sorted(evidence_node_ids)]
    if at:
        episode_where.extend(["ep.recorded_at <= ?", "(ep.expired_at is null or ep.expired_at > ?)"])
        episode_params.extend([at, at])
    elif not include_history:
        episode_where.append("ep.status = 'active'")
    episode_rows = connection.execute(
        "select distinct ne.node_id, ep.* from knowledge_node_episodes ne "
        "join knowledge_episodes ep on ep.id = ne.episode_id "
        f"where {' and '.join(episode_where)} order by ne.node_id, ep.id",
        episode_params,
    ).fetchall()
    independent: dict[str, set[str]] = {}
    model_only: dict[str, set[str]] = {}
    for episode in episode_rows:
        node_id = str(episode["node_id"])
        linked_node = node_by_id.get(node_id)
        if linked_node is None or not same_tenant(episode, linked_node):
            continue
        target = independent if _episode_is_independent(episode) else model_only
        target.setdefault(node_id, set()).add(_evidence_key(episode))

    independent_edge_evidence: dict[str, set[str]] = {}
    edge_ids = {str(edge["id"]) for edge in epistemic_edges}
    if edge_ids:
        edge_placeholders = ",".join("?" for _ in edge_ids)
        edge_episode_rows = connection.execute(
            "select distinct ee.edge_id, ep.* from knowledge_edge_episodes ee "
            "join knowledge_episodes ep on ep.id = ee.episode_id "
            f"where ee.edge_id in ({edge_placeholders}) order by ee.edge_id, ep.id",
            sorted(edge_ids),
        ).fetchall()
        edge_by_id = {str(edge["id"]): edge for edge in epistemic_edges}
        for episode in edge_episode_rows:
            edge = edge_by_id[str(episode["edge_id"])]
            target = target_by_id[str(edge["dst_id"])]
            if not same_tenant(episode, target) or not _episode_is_independent(episode):
                continue
            independent_edge_evidence.setdefault(str(edge["id"]), set()).add(_evidence_key(episode))

    incoming: dict[str, list[sqlite3.Row]] = {}
    for edge in epistemic_edges:
        incoming.setdefault(str(edge["dst_id"]), []).append(edge)

    horizon = at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    profiles: dict[str, dict[str, object]] = {}
    for row in rows:
        node_id = str(row["id"])
        kind = str(row["kind"])
        if kind not in ASSERTION_KINDS:
            profiles[node_id] = {
                "trust_state": "not_applicable",
                "assertable": True,
                "epistemic_basis": _row_epistemic_basis(row),
                "independent_evidence_count": len(independent.get(node_id, ())),
                "model_output_evidence_count": len(model_only.get(node_id, ())),
                "reasons": [],
            }
            continue

        status = str(row["status"])
        if at and status in CURRENT_EXCLUDED_STATUSES and str(row["updated_at"]) > at:
            # The row stores current status, while point-in-time visibility
            # admits it before that transition. Treat the later status as not
            # yet effective at the requested horizon.
            status = Status.ASSERTED.value
        basis = _row_epistemic_basis(row)
        node_edges = incoming.get(node_id, [])
        supported_by = [
            edge for edge in node_edges
            if str(edge["predicate"]).lower() in {"supports", "corroborates"}
            and independent.get(str(edge["src_id"]))
            and independent_edge_evidence.get(str(edge["id"]))
        ]
        verified_refutations = [
            edge for edge in node_edges
            if str(edge["predicate"]).lower() == "refutes"
            and independent.get(str(edge["src_id"]))
            and independent_edge_evidence.get(str(edge["id"]))
        ]
        disputes = [
            edge for edge in node_edges
            if str(edge["predicate"]).lower() in {"contradicts", "refutes"}
        ]
        verified_supersessions = [
            edge for edge in node_edges
            if str(edge["predicate"]).lower() == "supersedes"
            and independent.get(str(edge["src_id"]))
            and independent_edge_evidence.get(str(edge["id"]))
        ]
        independent_evidence = set(independent.get(node_id, ()))
        for edge in supported_by:
            independent_evidence.update(independent.get(str(edge["src_id"]), ()))
            independent_evidence.update(independent_edge_evidence.get(str(edge["id"]), ()))
        independent_count = len(independent_evidence)
        reasons: list[str] = []
        if status == Status.SUPERSEDED.value or verified_supersessions:
            trust_state = "superseded"
            reasons.append("superseded by canonical lifecycle or independently evidenced relation")
        elif status == Status.CONTRADICTED.value or verified_refutations:
            trust_state = "refuted"
            reasons.append("refuted by independently evidenced knowledge")
        elif disputes:
            trust_state = "contested"
            reasons.append("a contradiction or refutation edge requires resolution")
        elif _time_reached(row["valid_to"], horizon):
            trust_state = "stale"
            reasons.append("validity interval ended before the knowledge horizon")
        elif basis == "hypothetical" or status == Status.HYPOTHETICAL.value:
            trust_state = "unverified"
            reasons.append("hypothetical claims are never asserted as established knowledge")
        elif independent_count >= 2:
            trust_state = "verified"
            reasons.append("corroborated by multiple independent evidence paths")
        elif independent_count >= 1 or supported_by:
            trust_state = "supported"
            reasons.append("grounded in at least one independent evidence episode")
        else:
            trust_state = "unverified"
            reasons.append("no independent non-model evidence path")
        profiles[node_id] = {
            "trust_state": trust_state,
            "assertable": trust_state in ASSERTABLE_TRUST_STATES,
            "epistemic_basis": basis,
            "independent_evidence_count": independent_count,
            "model_output_evidence_count": len(model_only.get(node_id, ())),
            "support_edge_count": len(supported_by),
            "dispute_edge_count": len(disputes),
            "reasons": reasons,
        }
    return profiles


def _row_epistemic_basis(row: sqlite3.Row) -> str:
    properties = json.loads(row["properties_json"] or "{}")
    value = str(properties.get("epistemic_basis") or "").strip().lower()
    if value in {"explicit", "inferred", "hypothetical"}:
        return value
    status = str(row["status"])
    if status == Status.HYPOTHETICAL.value:
        return "hypothetical"
    if status == Status.INFERRED.value:
        return "inferred"
    return "explicit"


def _graph_stats(connection: sqlite3.Connection, *, include_history: bool) -> dict[str, object]:
    if include_history:
        node_where = "1=1"
        edge_where = "1=1"
        params: list[object] = []
    else:
        excluded = sorted(CURRENT_EXCLUDED_STATUSES)
        placeholders = ",".join("?" for _ in excluded)
        node_where = (
            f"status not in ({placeholders}) and "
            "(not exists (select 1 from knowledge_node_episodes ne where ne.node_id = knowledge_nodes.id) "
            "or exists (select 1 from knowledge_node_episodes ne "
            "join knowledge_episodes ep on ep.id = ne.episode_id "
            "where ne.node_id = knowledge_nodes.id and ep.status = 'active'))"
        )
        edge_where = f"status not in ({placeholders}) and expired_at is null"
        params = excluded
    node_count = connection.execute(
        f"select count(*) from knowledge_nodes where {node_where}", params
    ).fetchone()[0]
    edge_count = connection.execute(
        f"select count(*) from knowledge_edges where {edge_where}", params
    ).fetchone()[0]
    episode_status = "" if include_history else " and status = 'active'"
    agent_count = connection.execute(
        "select count(distinct agent_id) from knowledge_episodes where agent_id is not null" + episode_status
    ).fetchone()[0]
    source_count = connection.execute(
        "select count(distinct source_ref) from knowledge_episodes "
        "where source_ref is not null and source_ref != ''" + episode_status
    ).fetchone()[0]
    episode_count = connection.execute(
        "select count(*) from knowledge_episodes where 1=1" + episode_status
    ).fetchone()[0]
    kinds = {
        str(row[0]): int(row[1])
        for row in connection.execute(
            f"select kind, count(*) from knowledge_nodes where {node_where} group by kind", params
        ).fetchall()
    }
    edge_kinds = {
        str(row[0]): int(row[1])
        for row in connection.execute(
            f"select predicate, count(*) from knowledge_edges where {edge_where} group by predicate", params
        ).fetchall()
    }
    return {
        "node_count": int(node_count),
        "edge_count": int(edge_count),
        "episode_count": int(episode_count),
        "agent_count": int(agent_count),
        "source_count": int(source_count),
        "node_kinds": kinds,
        "edge_kinds": edge_kinds,
        "projection_version": PROJECTION_VERSION,
    }


def _node_payload(
    row: sqlite3.Row,
    agents: list[str],
    sources: list[str],
    trust: dict[str, object] | None = None,
) -> dict[str, object]:
    properties = json.loads(row["properties_json"])
    profile = trust or {
        "trust_state": "not_applicable",
        "assertable": True,
        "epistemic_basis": properties.get("epistemic_basis", "explicit"),
        "independent_evidence_count": 0,
        "model_output_evidence_count": 0,
        "reasons": [],
    }
    return {
        "id": str(row["id"]),
        "kind": str(row["kind"]),
        "label": str(row["label"]),
        "namespace": str(row["ns"]),
        "scope": str(row["scope"]),
        "status": str(row["status"]),
        "confidence": float(row["confidence"]),
        "valid_from": row["valid_from"],
        "valid_to": row["valid_to"],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "agents": agents or ([str(row["agent_id"])] if row["agent_id"] else []),
        "sources": sources,
        "synthetic": bool(row["synthetic"]),
        "facets": properties.get("facets", {}),
        "epistemic_basis": profile["epistemic_basis"],
        "trust_state": profile["trust_state"],
        "assertable": bool(profile["assertable"]),
        "trust": profile,
        "properties": properties,
    }


def _episode_node_payload(row: sqlite3.Row) -> dict[str, object]:
    source_ref = str(row["source_ref"] or "").strip()
    source_record_id = str(row["source_record_id"])
    recorded_at = str(row["recorded_at"])
    independent = _episode_is_independent(row)
    return {
        "id": str(row["id"]),
        "kind": "episode",
        "label": source_ref or f"Episode {source_record_id}",
        "namespace": str(row["ns"]),
        "scope": str(row["scope"]),
        "status": str(row["status"]),
        "confidence": 1.0,
        "valid_from": row["valid_at"] or recorded_at,
        "valid_to": row["expired_at"],
        "created_at": recorded_at,
        "updated_at": str(row["expired_at"] or recorded_at),
        "agents": [str(row["agent_id"])] if row["agent_id"] else [],
        "sources": [source_ref] if source_ref else [],
        "synthetic": True,
        "facets": {"when": row["valid_at"] or recorded_at},
        "epistemic_basis": "explicit",
        "trust_state": "evidence",
        "assertable": independent,
        "trust": {
            "trust_state": "evidence",
            "assertable": independent,
            "independent_evidence_count": int(independent),
            "model_output_evidence_count": int(not independent),
            "reasons": [
                "independent source episode" if independent
                else "model or agent output is provenance, not independent evidence"
            ],
        },
        "properties": {
            "source_record_id": source_record_id,
            "source_ref": source_ref or None,
            "content_hash": row["content_hash"],
            "recorded_at": recorded_at,
            "expired_at": row["expired_at"],
            "metadata": json.loads(row["metadata_json"]),
        },
    }


def _edge_payload(row: sqlite3.Row) -> dict[str, object]:
    properties = json.loads(row["properties_json"])
    return {
        "id": str(row["id"]),
        "source": str(row["src_id"]),
        "target": str(row["dst_id"]),
        "predicate": str(row["predicate"]),
        "edge_kind": str(row["edge_kind"]),
        "namespace": str(row["ns"]),
        "scope": str(row["scope"]),
        "status": str(row["status"]),
        "confidence": float(row["confidence"]),
        "valid_from": row["valid_from"],
        "valid_to": row["valid_to"],
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "expired_at": row["expired_at"],
        "agent_id": row["agent_id"],
        "source_record_id": str(row["source_record_id"]),
        "semantic_family": properties.get(
            "semantic_family",
            predicate_family(row["predicate"], str(row["edge_kind"])),
        ),
        "epistemic_basis": properties.get("epistemic_basis", "explicit"),
        "properties": properties,
    }


def _episode_payload(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": str(row["id"]),
        "source_record_id": str(row["source_record_id"]),
        "source_ref": row["source_ref"],
        "content_hash": row["content_hash"],
        "agent_id": row["agent_id"],
        "namespace": str(row["ns"]),
        "scope": str(row["scope"]),
        "status": str(row["status"]),
        "valid_at": row["valid_at"],
        "recorded_at": str(row["recorded_at"]),
        "expired_at": row["expired_at"],
        "metadata": json.loads(row["metadata_json"]),
    }


def _page_summary(row: sqlite3.Row, outgoing: list[dict[str, object]], incoming: list[dict[str, object]]) -> str:
    facts = [edge for edge in outgoing if edge["edge_kind"] == "semantic"]
    if facts:
        predicates = ", ".join(dict.fromkeys(str(edge["predicate"]) for edge in facts[:5]))
        return f"{row['label']} has {len(facts)} current outgoing facts ({predicates}) and {len(incoming)} backlinks."
    return f"{row['label']} has {len(outgoing)} outgoing links and {len(incoming)} backlinks in the SEAM knowledge graph."


def _query_payload(
    query: str,
    root_id: str | None,
    namespace: str | None,
    scope: str | None,
    agent_id: str | None,
    kinds: list[str],
    at: str | None,
    include_history: bool,
    limit: int,
    hops: int,
) -> dict[str, object]:
    return {
        "text": query,
        "root_id": root_id,
        "namespace": namespace,
        "scope": scope,
        "agent_id": agent_id,
        "kinds": kinds,
        "at": at,
        "include_history": include_history,
        "limit": limit,
        "hops": hops,
    }


def _load_record(connection: sqlite3.Connection, record_id: str) -> MIRLRecord | None:
    row = connection.execute("select payload_json from ir_records where id = ?", (record_id,)).fetchone()
    if row is None:
        return None
    try:
        return MIRLRecord.from_dict(json.loads(row[0]))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def _edge_id(source_record_id: str, src: str, predicate: str, dst: str, edge_kind: str) -> str:
    material = "\x1f".join((source_record_id, src, predicate, dst, edge_kind))
    return f"kge:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:24]}"


def _value_node_id(namespace: str, scope: str, value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.strip().lower())
    material = f"{namespace}\x1f{scope}\x1f{normalized}"
    return f"value:{hashlib.sha256(material.encode('utf-8')).hexdigest()[:20]}"


def _agent_node_id(agent_id: str | None) -> str:
    value = (agent_id or "unknown").strip()
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-").lower() or "unknown"
    identity_hash = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
    return f"agent:{slug}:{identity_hash}"


def _kind_from_id(node_id: str) -> str:
    return _PREFIX_KINDS.get(node_id.partition(":")[0].lower(), "concept")


def _label_from_id(node_id: str) -> str:
    tail = node_id.partition(":")[2] or node_id
    return tail.replace("_", " ").replace("-", " ")


def _join_label(*parts: object) -> str:
    return _truncate(" ".join(str(part) for part in parts if part not in (None, "")), 180)


def _truncate(value: str, length: int) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    return value if len(value) <= length else value[: length - 1].rstrip() + "…"


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
