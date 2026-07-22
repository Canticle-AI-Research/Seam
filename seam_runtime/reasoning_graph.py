from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from uuid import uuid4

from .mirl import utc_now

REASONING_SCHEMA_VERSION = 1
REASONING_NODE_KINDS = frozenset(
    {
        "objective",
        "question",
        "premise",
        "hypothesis",
        "inference",
        "decision",
        "outcome",
    }
)
REASONING_RELATIONS = frozenset(
    {
        "decomposes",
        "uses",
        "supports",
        "opposes",
        "derives",
        "tests",
        "selects",
        "answers",
        "supersedes",
        "produces",
    }
)
REASONING_STATUSES = frozenset(
    {"open", "supported", "challenged", "accepted", "rejected", "superseded"}
)
_STATUS_TRANSITIONS = {
    "open": frozenset({"supported", "challenged", "accepted", "rejected", "superseded"}),
    "supported": frozenset({"challenged", "accepted", "rejected", "superseded"}),
    "challenged": frozenset({"supported", "accepted", "rejected", "superseded"}),
    "accepted": frozenset({"superseded"}),
    "rejected": frozenset({"superseded"}),
    "superseded": frozenset(),
}
_SUPPORTING_RELATIONS = frozenset({"uses", "supports", "derives", "tests", "answers"})


def init_reasoning_graph(connection: sqlite3.Connection) -> None:
    """Create the append-only public reasoning plane.

    The graph records concise, inspectable reasoning artifacts. It deliberately
    has no field for hidden chain-of-thought, activations, logits, or raw model
    traces, and it never promotes a conclusion into canonical MIRL by itself.
    """

    connection.executescript(
        """
        create table if not exists reasoning_node (
            node_id text primary key,
            run_id text not null,
            seq integer not null,
            kind text not null check (kind in
                ('objective', 'question', 'premise', 'hypothesis', 'inference', 'decision', 'outcome')),
            summary text not null,
            confidence real check (confidence is null or (confidence >= 0 and confidence <= 1)),
            ns text not null,
            scope text not null,
            agent_id text,
            operation text,
            knowledge_refs_json text not null,
            evidence_record_ids_json text not null,
            created_at text not null,
            schema_version integer not null default 1,
            foreign key (run_id) references workspace_run(run_id),
            unique (run_id, seq)
        );
        create table if not exists reasoning_edge (
            edge_id text primary key,
            run_id text not null,
            seq integer not null,
            src_node_id text not null,
            relation text not null check (relation in
                ('decomposes', 'uses', 'supports', 'opposes', 'derives', 'tests',
                 'selects', 'answers', 'supersedes', 'produces')),
            dst_node_id text not null,
            agent_id text,
            created_at text not null,
            schema_version integer not null default 1,
            foreign key (run_id) references workspace_run(run_id),
            foreign key (src_node_id) references reasoning_node(node_id),
            foreign key (dst_node_id) references reasoning_node(node_id),
            unique (run_id, seq),
            unique (src_node_id, relation, dst_node_id)
        );
        create table if not exists reasoning_state (
            state_id text primary key,
            node_id text not null,
            seq integer not null,
            status text not null check (status in
                ('open', 'supported', 'challenged', 'accepted', 'rejected', 'superseded')),
            reason text,
            actor text,
            created_at text not null,
            schema_version integer not null default 1,
            foreign key (node_id) references reasoning_node(node_id),
            unique (node_id, seq)
        );
        create index if not exists idx_reasoning_node_run on reasoning_node (run_id, seq);
        create index if not exists idx_reasoning_node_ns_scope on reasoning_node (ns, scope);
        create index if not exists idx_reasoning_edge_run on reasoning_edge (run_id, seq);
        create index if not exists idx_reasoning_edge_src on reasoning_edge (src_node_id);
        create index if not exists idx_reasoning_edge_dst on reasoning_edge (dst_node_id);
        create index if not exists idx_reasoning_state_node on reasoning_state (node_id, seq);
        create trigger if not exists reasoning_node_no_update
        before update on reasoning_node begin
            select raise(abort, 'reasoning_node is append-only');
        end;
        create trigger if not exists reasoning_node_no_delete
        before delete on reasoning_node begin
            select raise(abort, 'reasoning_node is append-only');
        end;
        create trigger if not exists reasoning_edge_no_update
        before update on reasoning_edge begin
            select raise(abort, 'reasoning_edge is append-only');
        end;
        create trigger if not exists reasoning_edge_no_delete
        before delete on reasoning_edge begin
            select raise(abort, 'reasoning_edge is append-only');
        end;
        create trigger if not exists reasoning_state_no_update
        before update on reasoning_state begin
            select raise(abort, 'reasoning_state is append-only');
        end;
        create trigger if not exists reasoning_state_no_delete
        before delete on reasoning_state begin
            select raise(abort, 'reasoning_state is append-only');
        end;
        """
    )


def _required_text(value: str, field: str, *, limit: int) -> str:
    resolved = str(value).strip()
    if not resolved:
        raise ValueError(f"{field} is required")
    if len(resolved) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return resolved


def _reference_ids(values: Iterable[str], field: str) -> tuple[str, ...]:
    resolved = tuple(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    if len(resolved) > 256:
        raise ValueError(f"{field} supports at most 256 references")
    return resolved


def _run_row(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    row = connection.execute(
        "select run_id, ns, scope, agent_id from workspace_run where run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"workspace run not found: {run_id}")
    return row


def _validate_references(
    connection: sqlite3.Connection,
    *,
    ns: str,
    scope: str,
    knowledge_refs: tuple[str, ...],
    evidence_record_ids: tuple[str, ...],
) -> None:
    for node_id in knowledge_refs:
        row = connection.execute(
            "select ns, scope from knowledge_nodes where id = ?", (node_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"knowledge node not found: {node_id}")
        if row["ns"] != ns or row["scope"] != scope:
            raise ValueError(f"knowledge reference crosses namespace or scope: {node_id}")
    for record_id in evidence_record_ids:
        row = connection.execute(
            "select ns, scope from ir_records where id = ?", (record_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"evidence record not found: {record_id}")
        if row["ns"] != ns or row["scope"] != scope:
            raise ValueError(f"evidence reference crosses namespace or scope: {record_id}")


def add_reasoning_node(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    kind: str,
    summary: str,
    confidence: float | None = None,
    agent_id: str | None = None,
    operation: str | None = None,
    knowledge_refs: Iterable[str] = (),
    evidence_record_ids: Iterable[str] = (),
    node_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, object]:
    # Sequence allocation and insertion share a write lock, matching the
    # workspace event contract. Callers already inside a transaction retain
    # control of their own transaction boundary.
    if not connection.in_transaction:
        connection.execute("begin immediate")
    resolved_kind = str(kind).strip().lower()
    if resolved_kind not in REASONING_NODE_KINDS:
        raise ValueError(f"unsupported reasoning node kind: {kind}")
    resolved_summary = _required_text(summary, "reasoning summary", limit=4096)
    if confidence is not None and not 0 <= float(confidence) <= 1:
        raise ValueError("confidence must be between 0 and 1")
    resolved_operation = None
    if operation is not None:
        resolved_operation = _required_text(operation, "operation", limit=128)
    resolved_knowledge = _reference_ids(knowledge_refs, "knowledge_refs")
    resolved_evidence = _reference_ids(evidence_record_ids, "evidence_record_ids")
    if resolved_kind == "premise" and not (resolved_knowledge or resolved_evidence):
        raise ValueError("premise nodes require a knowledge or evidence reference")

    run = _run_row(connection, run_id)
    _validate_references(
        connection,
        ns=run["ns"],
        scope=run["scope"],
        knowledge_refs=resolved_knowledge,
        evidence_record_ids=resolved_evidence,
    )
    resolved_node_id = node_id or f"reason:{uuid4().hex}"
    resolved_created_at = created_at or utc_now()
    next_seq = connection.execute(
        "select coalesce(max(seq), 0) + 1 from reasoning_node where run_id = ?", (run_id,)
    ).fetchone()[0]
    connection.execute(
        """
        insert into reasoning_node
            (node_id, run_id, seq, kind, summary, confidence, ns, scope, agent_id,
             operation, knowledge_refs_json, evidence_record_ids_json, created_at, schema_version)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            resolved_node_id,
            run_id,
            next_seq,
            resolved_kind,
            resolved_summary,
            None if confidence is None else float(confidence),
            run["ns"],
            run["scope"],
            agent_id or run["agent_id"],
            resolved_operation,
            json.dumps(resolved_knowledge, separators=(",", ":")),
            json.dumps(resolved_evidence, separators=(",", ":")),
            resolved_created_at,
            REASONING_SCHEMA_VERSION,
        ),
    )
    connection.execute(
        """
        insert into reasoning_state
            (state_id, node_id, seq, status, reason, actor, created_at, schema_version)
        values (?, ?, 1, 'open', ?, ?, ?, ?)
        """,
        (
            f"reason-state:{uuid4().hex}",
            resolved_node_id,
            "node created",
            agent_id or run["agent_id"],
            resolved_created_at,
            REASONING_SCHEMA_VERSION,
        ),
    )
    return get_reasoning_node(connection, resolved_node_id)


def add_reasoning_edge(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    src_node_id: str,
    relation: str,
    dst_node_id: str,
    agent_id: str | None = None,
    edge_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, object]:
    if not connection.in_transaction:
        connection.execute("begin immediate")
    resolved_relation = str(relation).strip().lower()
    if resolved_relation not in REASONING_RELATIONS:
        raise ValueError(f"unsupported reasoning relation: {relation}")
    if src_node_id == dst_node_id:
        raise ValueError("reasoning edges cannot be self-referential")
    run = _run_row(connection, run_id)
    rows = connection.execute(
        "select node_id, run_id, ns, scope from reasoning_node where node_id in (?, ?)",
        (src_node_id, dst_node_id),
    ).fetchall()
    by_id = {row["node_id"]: row for row in rows}
    missing = [node_id for node_id in (src_node_id, dst_node_id) if node_id not in by_id]
    if missing:
        raise KeyError(f"reasoning node not found: {missing[0]}")
    for row in by_id.values():
        if row["run_id"] != run_id or row["ns"] != run["ns"] or row["scope"] != run["scope"]:
            raise ValueError("reasoning edges cannot cross runs, namespaces, or scopes")
    next_seq = connection.execute(
        "select coalesce(max(seq), 0) + 1 from reasoning_edge where run_id = ?", (run_id,)
    ).fetchone()[0]
    resolved_edge_id = edge_id or f"reason-edge:{uuid4().hex}"
    resolved_created_at = created_at or utc_now()
    connection.execute(
        """
        insert into reasoning_edge
            (edge_id, run_id, seq, src_node_id, relation, dst_node_id, agent_id,
             created_at, schema_version)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            resolved_edge_id,
            run_id,
            next_seq,
            src_node_id,
            resolved_relation,
            dst_node_id,
            agent_id or run["agent_id"],
            resolved_created_at,
            REASONING_SCHEMA_VERSION,
        ),
    )
    return {
        "edge_id": resolved_edge_id,
        "run_id": run_id,
        "seq": next_seq,
        "src_node_id": src_node_id,
        "relation": resolved_relation,
        "dst_node_id": dst_node_id,
        "agent_id": agent_id or run["agent_id"],
        "created_at": resolved_created_at,
        "schema_version": REASONING_SCHEMA_VERSION,
    }


def _current_status(connection: sqlite3.Connection, node_id: str) -> sqlite3.Row:
    row = connection.execute(
        "select * from reasoning_state where node_id = ? order by seq desc limit 1",
        (node_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"reasoning node not found: {node_id}")
    return row


def _has_support(connection: sqlite3.Connection, node: sqlite3.Row) -> bool:
    if json.loads(node["knowledge_refs_json"]) or json.loads(node["evidence_record_ids_json"]):
        return True
    placeholders = ",".join("?" for _ in _SUPPORTING_RELATIONS)
    row = connection.execute(
        f"select 1 from reasoning_edge where dst_node_id = ? "
        f"and relation in ({placeholders}) limit 1",
        (node["node_id"], *sorted(_SUPPORTING_RELATIONS)),
    ).fetchone()
    return row is not None


def transition_reasoning_node(
    connection: sqlite3.Connection,
    *,
    node_id: str,
    status: str,
    reason: str | None = None,
    actor: str | None = None,
    created_at: str | None = None,
) -> dict[str, object]:
    if not connection.in_transaction:
        connection.execute("begin immediate")
    resolved_status = str(status).strip().lower()
    if resolved_status not in REASONING_STATUSES:
        raise ValueError(f"unsupported reasoning status: {status}")
    node = connection.execute(
        "select * from reasoning_node where node_id = ?", (node_id,)
    ).fetchone()
    if node is None:
        raise KeyError(f"reasoning node not found: {node_id}")
    current = _current_status(connection, node_id)
    if resolved_status not in _STATUS_TRANSITIONS[current["status"]]:
        raise ValueError(
            f"invalid reasoning status transition: {current['status']} -> {resolved_status}"
        )
    if (
        resolved_status == "accepted"
        and node["kind"] in {"inference", "decision", "outcome"}
        and not _has_support(connection, node)
    ):
        raise ValueError(f"accepted {node['kind']} nodes require explicit support")
    resolved_reason = None
    if reason is not None:
        resolved_reason = _required_text(reason, "transition reason", limit=2048)
    next_seq = int(current["seq"]) + 1
    resolved_created_at = created_at or utc_now()
    state_id = f"reason-state:{uuid4().hex}"
    connection.execute(
        """
        insert into reasoning_state
            (state_id, node_id, seq, status, reason, actor, created_at, schema_version)
        values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            state_id,
            node_id,
            next_seq,
            resolved_status,
            resolved_reason,
            actor,
            resolved_created_at,
            REASONING_SCHEMA_VERSION,
        ),
    )
    return {
        "state_id": state_id,
        "node_id": node_id,
        "seq": next_seq,
        "status": resolved_status,
        "reason": resolved_reason,
        "actor": actor,
        "created_at": resolved_created_at,
        "schema_version": REASONING_SCHEMA_VERSION,
    }


def _state_from_row(row: sqlite3.Row) -> dict[str, object]:
    return {
        "state_id": row["state_id"],
        "node_id": row["node_id"],
        "seq": row["seq"],
        "status": row["status"],
        "reason": row["reason"],
        "actor": row["actor"],
        "created_at": row["created_at"],
        "schema_version": row["schema_version"],
    }


def _node_from_row(
    connection: sqlite3.Connection, row: sqlite3.Row, *, include_history: bool
) -> dict[str, object]:
    states = connection.execute(
        "select * from reasoning_state where node_id = ? order by seq", (row["node_id"],)
    ).fetchall()
    result: dict[str, object] = {
        "node_id": row["node_id"],
        "run_id": row["run_id"],
        "seq": row["seq"],
        "kind": row["kind"],
        "summary": row["summary"],
        "confidence": row["confidence"],
        "status": states[-1]["status"],
        "ns": row["ns"],
        "scope": row["scope"],
        "agent_id": row["agent_id"],
        "operation": row["operation"],
        "knowledge_refs": json.loads(row["knowledge_refs_json"]),
        "evidence_record_ids": json.loads(row["evidence_record_ids_json"]),
        "created_at": row["created_at"],
        "schema_version": row["schema_version"],
    }
    if include_history:
        result["state_history"] = [_state_from_row(state) for state in states]
    return result


def get_reasoning_node(
    connection: sqlite3.Connection, node_id: str, *, include_history: bool = True
) -> dict[str, object]:
    row = connection.execute(
        "select * from reasoning_node where node_id = ?", (node_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"reasoning node not found: {node_id}")
    return _node_from_row(connection, row, include_history=include_history)


def reasoning_graph(connection: sqlite3.Connection, run_id: str) -> dict[str, object]:
    run = _run_row(connection, run_id)
    node_rows = connection.execute(
        "select * from reasoning_node where run_id = ? order by seq", (run_id,)
    ).fetchall()
    edge_rows = connection.execute(
        "select * from reasoning_edge where run_id = ? order by seq", (run_id,)
    ).fetchall()
    return {
        "run_id": run_id,
        "ns": run["ns"],
        "scope": run["scope"],
        "canonical_truth": False,
        "automatic_promotion": False,
        "nodes": [
            _node_from_row(connection, row, include_history=True) for row in node_rows
        ],
        "edges": [
            {
                "edge_id": row["edge_id"],
                "run_id": row["run_id"],
                "seq": row["seq"],
                "src_node_id": row["src_node_id"],
                "relation": row["relation"],
                "dst_node_id": row["dst_node_id"],
                "agent_id": row["agent_id"],
                "created_at": row["created_at"],
                "schema_version": row["schema_version"],
            }
            for row in edge_rows
        ],
    }
