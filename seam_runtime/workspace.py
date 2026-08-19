from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import deque
from dataclasses import dataclass
from typing import Iterable
from uuid import uuid4

from .migrations import execute_script
from .mirl import utc_now

WORKSPACE_SCHEMA_VERSION = 1
WORKSPACE_EVENT_TYPES = frozenset(
    {
        "run",
        "retrieval",
        "graph_activation",
        "reasoning_summary",
        "jlens_concept",
        "tool",
        "hypothesis",
        "decision",
        "verification",
        "answer_delta",
        "completion",
        "failure",
    }
)

# Workspace telemetry is deliberately not a chain-of-thought or arbitrary JSON
# store. Each event has a small public schema, and credential-shaped keys are
# rejected before schema validation. This is intentionally fail-closed: adding a
# new telemetry field requires adding it to the relevant event schema below.
_CREDENTIAL_KEYS = frozenset(
    {
        "apikey",
        "accesstoken",
        "refreshtoken",
        "idtoken",
        "authorization",
        "authorizationheader",
        "bearer",
        "bearertoken",
        "clientsecret",
        "clientpassword",
        "credential",
        "credentials",
        "cookie",
        "setcookie",
        "password",
        "passwd",
        "secret",
        "secretkey",
        "privatekey",
        "sessiontoken",
    }
)
_FORBIDDEN_TELEMETRY_KEYS = frozenset(
    {
        "chainofthought",
        "cot",
        "hiddenthoughts",
        "internalreasoning",
        "rawreasoning",
        "rawactivation",
        "rawactivations",
        "activationtensor",
        "activationtensors",
        "hiddenstate",
        "hiddenstates",
        "logits",
        "attentionweights",
    }
)
_MAX_STRING_CHARS = 4_096
_MAX_LIST_ITEMS = 256


def _list(item_schema: object, limit: int = _MAX_LIST_ITEMS) -> tuple[str, object, int]:
    return ("list", item_schema, limit)


_JLENS_CAPABILITY_SCHEMA: dict[str, object] = {
    "available": "bool",
    "backend": "str",
    "mode": "str",
    "reason": "nullable_str",
    "model": "nullable_str",
    "revision": "nullable_str",
    "model_ref_hash": "nullable_str",
    "model_artifact_hash": "nullable_str",
    "lens_artifact_hash": "nullable_str",
    "genuine_jacobian_lens": "bool",
    "identity_verified": "bool",
    "downloads_enabled": "bool",
    "authenticated": "bool",
}
_JLENS_CONCEPT_SCHEMA: dict[str, object] = {
    "id": "str",
    "label": "str",
    "description": "str",
    "score": "float",
    "layer": "scalar",
    "module": "str",
    "rank": "int",
    "source": "str",
}
_CANDIDATE_SCHEMA: dict[str, object] = {
    "record_id": "str",
    "kind": "str",
    "score": "float",
    "reasons": _list("str", 32),
}
_ACTIVATION_NODE_SCHEMA: dict[str, object] = {
    "node_id": "str",
    "activation": "float",
    "hop": "int",
    "from_node_id": "nullable_str",
    "via_edge_id": "nullable_str",
}
_RUN_METADATA_SCHEMA: dict[str, object] = {
    "message_sha256": "str",
    "message_chars": "int",
    "use_memory": "bool",
    "persist_chat": "bool",
    "jspace_requested": "bool",
}
_EVENT_PAYLOAD_SCHEMAS: dict[str, dict[str, object]] = {
    "run": {
        "status": "str",
        "model": "str",
        "provider": "str",
        "memory_enabled": "bool",
        "jspace_requested": "bool",
        "jlens_capability": _JLENS_CAPABILITY_SCHEMA,
    },
    "retrieval": {
        "status": "str",
        "query_sha256": "str",
        "candidates": _list(_CANDIDATE_SCHEMA, 128),
        "asserted_context_ids": _list("str", 128),
        "error": "nullable_str",
    },
    "graph_activation": {
        "status": "str",
        "seed_ids": _list("str", 128),
        "nodes": _list(_ACTIVATION_NODE_SCHEMA, 128),
        "decay": "float",
        "max_hops": "int",
        "error": "nullable_str",
    },
    "reasoning_summary": {
        "summary": "str",
        "source": "str",
        "hidden_chain_of_thought": ("const", False),
    },
    "jlens_concept": {
        "concept": _JLENS_CONCEPT_SCHEMA,
        "backend": "str",
        "model": "str",
        "revision": "str",
        "model_artifact_hash": "str",
        "lens_artifact_hash": "str",
        "identity_verified": ("const", True),
        "raw_activations_persisted": ("const", False),
    },
    "tool": {"tool": "str", "status": "str", "provider": "str", "model": "str"},
    "hypothesis": {
        "hypothesis": "str",
        "status": "str",
        "confidence": "float",
        "evidence_ids": _list("str", 128),
    },
    "decision": {
        "decision": "str",
        "memory_records": "int",
        "memory_context_chars": "int",
    },
    "verification": {
        "check": "str",
        "status": "str",
        "reason": "nullable_str",
        "answer_sha256": "str",
        "answer_chars": "int",
        "memory_records": "int",
        "chat_persisted": "bool",
        "error": "nullable_str",
    },
    "answer_delta": {"text": "str", "offset": "int", "final": "bool"},
    "completion": {
        "status": "str",
        "model": "str",
        "memory_used": "int",
        "answer_chars": "int",
        "memory_error": "nullable_str",
        "persist_error": "nullable_str",
    },
    "failure": {"status": "str", "stage": "str", "error_type": "str", "message": "str"},
}


def _normalized_key(value: object) -> str:
    return "".join(character for character in str(value).lower() if character.isalnum())


def _forbidden_key(value: object) -> bool:
    normalized = _normalized_key(value)
    return normalized in _CREDENTIAL_KEYS or normalized in _FORBIDDEN_TELEMETRY_KEYS


def _sanitize_schema_value(value: object, schema: object, path: str, redacted: list[str]) -> object:
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            redacted.append(path)
            return {}
        output: dict[str, object] = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            child_path = f"{path}.{key}" if path else key
            child_schema = schema.get(key)
            if _forbidden_key(key) or child_schema is None:
                redacted.append(child_path)
                continue
            output[key] = _sanitize_schema_value(child, child_schema, child_path, redacted)
        return output
    if isinstance(schema, tuple) and schema and schema[0] == "list":
        if not isinstance(value, (list, tuple)):
            redacted.append(path)
            return []
        _, item_schema, limit = schema
        items = list(value)
        if len(items) > int(limit):
            redacted.append(path)
            items = items[: int(limit)]
        return [
            _sanitize_schema_value(item, item_schema, f"{path}[{index}]", redacted)
            for index, item in enumerate(items)
        ]
    if isinstance(schema, tuple) and schema and schema[0] == "const":
        if value != schema[1]:
            redacted.append(path)
        return schema[1]
    if schema == "nullable_str" and value is None:
        return None
    if schema == "str" or schema == "nullable_str":
        if not isinstance(value, str):
            redacted.append(path)
            return ""
        if len(value) > _MAX_STRING_CHARS:
            redacted.append(path)
            return value[:_MAX_STRING_CHARS]
        return value
    if schema == "bool":
        if type(value) is not bool:
            redacted.append(path)
            return False
        return value
    if schema == "int":
        if type(value) is not int:
            redacted.append(path)
            return 0
        return value
    if schema == "float":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            redacted.append(path)
            return 0.0
        return float(value)
    if schema == "scalar":
        if value is None or isinstance(value, (str, bool, int, float)):
            return _sanitize_schema_value(value, "str", path, redacted) if isinstance(value, str) else value
        redacted.append(path)
        return None
    redacted.append(path)
    return None


def sanitize_workspace_payload(payload: dict[str, object], *, event_type: str) -> dict[str, object]:
    """Apply the event's allowlisted telemetry schema and reject secrets.

    ``redacted_fields`` records field paths only. Unknown fields, nested arrays
    where a scalar is required, credentials, hidden reasoning, and tensor-like
    data never reach SQLite.
    """

    redacted: list[str] = []
    schema = _EVENT_PAYLOAD_SCHEMAS.get(event_type)
    if schema is None:
        raise ValueError(f"workspace event schema is not defined: {event_type}")
    cleaned = _sanitize_schema_value(payload, schema, "", redacted)
    assert isinstance(cleaned, dict)
    if redacted:
        cleaned["redacted_fields"] = sorted(set(redacted))
    return cleaned


def sanitize_workspace_metadata(payload: dict[str, object]) -> dict[str, object]:
    redacted: list[str] = []
    cleaned = _sanitize_schema_value(payload, _RUN_METADATA_SCHEMA, "", redacted)
    assert isinstance(cleaned, dict)
    if redacted:
        cleaned["redacted_fields"] = sorted(set(redacted))
    return cleaned


@dataclass(frozen=True)
class WorkspaceRun:
    run_id: str
    created_at: str
    ns: str
    scope: str
    agent_id: str | None
    model: str | None
    provider: str | None
    metadata: dict[str, object]

    def to_dict(self, *, status: str = "running") -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "created_at": self.created_at,
            "ns": self.ns,
            "scope": self.scope,
            "agent_id": self.agent_id,
            "model": self.model,
            "provider": self.provider,
            "status": status,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class WorkspaceEvent:
    event_id: int
    run_id: str
    seq: int
    event_type: str
    created_at: str
    ns: str
    scope: str
    agent_id: str | None
    payload: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "seq": self.seq,
            "event_type": self.event_type,
            "created_at": self.created_at,
            "ns": self.ns,
            "scope": self.scope,
            "agent_id": self.agent_id,
            "payload": dict(self.payload),
        }


def init_workspace_schema(connection: sqlite3.Connection) -> None:
    execute_script(
        connection,
        """
        create table if not exists workspace_run (
            run_id text primary key,
            created_at text not null,
            ns text not null,
            scope text not null,
            agent_id text,
            model text,
            provider text,
            metadata_json text not null,
            schema_version integer not null default 1
        );
        create table if not exists workspace_event (
            event_id integer primary key autoincrement,
            run_id text not null,
            seq integer not null,
            event_type text not null,
            created_at text not null,
            ns text not null,
            scope text not null,
            agent_id text,
            payload_json text not null,
            schema_version integer not null default 1,
            foreign key (run_id) references workspace_run(run_id),
            unique (run_id, seq)
        );
        create index if not exists idx_workspace_event_run on workspace_event (run_id, seq);
        create index if not exists idx_workspace_event_created on workspace_event (created_at);
        create index if not exists idx_workspace_event_ns_scope on workspace_event (ns, scope);
        create trigger if not exists workspace_run_no_update
        before update on workspace_run begin
            select raise(abort, 'workspace_run is append-only');
        end;
        create trigger if not exists workspace_run_no_delete
        before delete on workspace_run begin
            select raise(abort, 'workspace_run is append-only');
        end;
        create trigger if not exists workspace_event_no_update
        before update on workspace_event begin
            select raise(abort, 'workspace_event is append-only');
        end;
        create trigger if not exists workspace_event_no_delete
        before delete on workspace_event begin
            select raise(abort, 'workspace_event is append-only');
        end;
        """
    )


def create_workspace_run(
    connection: sqlite3.Connection,
    *,
    run_id: str | None = None,
    ns: str = "local.chat",
    scope: str = "thread",
    agent_id: str | None = None,
    model: str | None = None,
    provider: str | None = None,
    metadata: dict[str, object] | None = None,
    created_at: str | None = None,
) -> WorkspaceRun:
    if not ns.strip():
        raise ValueError("workspace namespace is required")
    if not scope.strip():
        raise ValueError("workspace scope is required")
    resolved_run_id = run_id or f"ws:{uuid4().hex}"
    resolved_created_at = created_at or utc_now()
    safe_metadata = sanitize_workspace_metadata(metadata or {})
    connection.execute(
        """
        insert into workspace_run
            (run_id, created_at, ns, scope, agent_id, model, provider, metadata_json, schema_version)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            resolved_run_id,
            resolved_created_at,
            ns,
            scope,
            agent_id,
            model,
            provider,
            json.dumps(safe_metadata, sort_keys=True, separators=(",", ":")),
            WORKSPACE_SCHEMA_VERSION,
        ),
    )
    return WorkspaceRun(
        run_id=resolved_run_id,
        created_at=resolved_created_at,
        ns=ns,
        scope=scope,
        agent_id=agent_id,
        model=model,
        provider=provider,
        metadata=safe_metadata,
    )


def append_workspace_event(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    event_type: str,
    payload: dict[str, object] | None = None,
    created_at: str | None = None,
    agent_id: str | None = None,
) -> WorkspaceEvent:
    if event_type not in WORKSPACE_EVENT_TYPES:
        allowed = ", ".join(sorted(WORKSPACE_EVENT_TYPES))
        raise ValueError(f"unsupported workspace event type {event_type!r}; expected one of: {allowed}")
    # Sequence allocation and insertion must share a write lock. Without an
    # IMMEDIATE transaction, two pooled connections can both observe the same
    # max(seq) and race on the unique(run_id, seq) constraint.
    if not connection.in_transaction:
        connection.execute("begin immediate")
    run_row = connection.execute(
        "select ns, scope, agent_id from workspace_run where run_id = ?",
        (run_id,),
    ).fetchone()
    if run_row is None:
        raise KeyError(f"workspace run not found: {run_id}")
    seq = int(
        connection.execute(
            "select coalesce(max(seq), 0) + 1 from workspace_event where run_id = ?",
            (run_id,),
        ).fetchone()[0]
    )
    resolved_created_at = created_at or utc_now()
    safe_payload = sanitize_workspace_payload(payload or {}, event_type=event_type)
    resolved_agent = agent_id if agent_id is not None else run_row["agent_id"]
    cursor = connection.execute(
        """
        insert into workspace_event
            (run_id, seq, event_type, created_at, ns, scope, agent_id, payload_json, schema_version)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            seq,
            event_type,
            resolved_created_at,
            run_row["ns"],
            run_row["scope"],
            resolved_agent,
            json.dumps(safe_payload, sort_keys=True, separators=(",", ":")),
            WORKSPACE_SCHEMA_VERSION,
        ),
    )
    return WorkspaceEvent(
        event_id=int(cursor.lastrowid),
        run_id=run_id,
        seq=seq,
        event_type=event_type,
        created_at=resolved_created_at,
        ns=str(run_row["ns"]),
        scope=str(run_row["scope"]),
        agent_id=resolved_agent,
        payload=safe_payload,
    )


def workspace_event_from_row(row: sqlite3.Row) -> WorkspaceEvent:
    return WorkspaceEvent(
        event_id=int(row["event_id"]),
        run_id=str(row["run_id"]),
        seq=int(row["seq"]),
        event_type=str(row["event_type"]),
        created_at=str(row["created_at"]),
        ns=str(row["ns"]),
        scope=str(row["scope"]),
        agent_id=row["agent_id"],
        payload=json.loads(row["payload_json"]),
    )


def workspace_run_from_row(row: sqlite3.Row) -> WorkspaceRun:
    return WorkspaceRun(
        run_id=str(row["run_id"]),
        created_at=str(row["created_at"]),
        ns=str(row["ns"]),
        scope=str(row["scope"]),
        agent_id=row["agent_id"],
        model=row["model"],
        provider=row["provider"],
        metadata=json.loads(row["metadata_json"]),
    )


def run_status(events: Iterable[WorkspaceEvent]) -> str:
    status = "running"
    for event in events:
        if event.event_type == "completion":
            status = "completed"
        elif event.event_type == "failure":
            status = "failed"
    return status


def sse_frame(event: WorkspaceEvent | dict[str, object]) -> str:
    data = event.to_dict() if isinstance(event, WorkspaceEvent) else dict(event)
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return f"id: {int(data['event_id'])}\nevent: {data['event_type']}\ndata: {payload}\n\n"


def content_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def spread_graph_activation(
    graph: dict[str, object],
    seed_ids: Iterable[str],
    *,
    max_hops: int = 2,
    decay: float = 0.72,
    limit: int = 64,
) -> list[dict[str, object]]:
    """Compute a bounded, deterministic, provenance-preserving activation view."""

    if max_hops < 0:
        raise ValueError("max_hops must be non-negative")
    if not 0.0 < decay <= 1.0:
        raise ValueError("decay must be in (0, 1]")
    edges = [edge for edge in graph.get("edges", []) if isinstance(edge, dict)]
    adjacency: dict[str, list[tuple[str, dict[str, object]]]] = {}
    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if not source or not target:
            continue
        adjacency.setdefault(source, []).append((target, edge))
        adjacency.setdefault(target, []).append((source, edge))
    for neighbors in adjacency.values():
        neighbors.sort(key=lambda item: (str(item[1].get("id") or ""), item[0]))

    best: dict[str, float] = {}
    output: dict[str, dict[str, object]] = {}
    queue: deque[tuple[str, float, int, str | None, str | None]] = deque()
    for seed_id in sorted({str(value) for value in seed_ids if str(value)}):
        best[seed_id] = 1.0
        queue.append((seed_id, 1.0, 0, None, None))
    while queue:
        node_id, score, hop, from_node_id, via_edge_id = queue.popleft()
        output[node_id] = {
            "node_id": node_id,
            "activation": round(score, 6),
            "hop": hop,
            "from_node_id": from_node_id,
            "via_edge_id": via_edge_id,
        }
        if hop >= max_hops:
            continue
        for neighbor, edge in adjacency.get(node_id, []):
            raw_confidence = edge.get("confidence")
            confidence = float(1.0 if raw_confidence is None else raw_confidence)
            next_score = score * decay * max(0.0, min(confidence, 1.0))
            if next_score <= 0.0:
                continue
            if next_score <= best.get(neighbor, -1.0):
                continue
            best[neighbor] = next_score
            queue.append((neighbor, next_score, hop + 1, node_id, str(edge.get("id") or "") or None))
    ranked = sorted(output.values(), key=lambda item: (-float(item["activation"]), int(item["hop"]), str(item["node_id"])))
    return ranked[: max(1, int(limit))]
