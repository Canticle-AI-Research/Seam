"""Auditable, recoverable G6 lifecycle operations for SQLite-backed SEAM."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator, Mapping, Sequence
from uuid import uuid4

from .knowledge_graph import remove_records as remove_knowledge_records
from .mirl import Status, utc_now
from .tenancy import tenant_owns_namespace as _tenant_owns_namespace

LIFECYCLE_SCHEMA_VERSION = 1
LIFECYCLE_CONTRACT_VERSION = "lifecycle/2"
OPERATION_KINDS = frozenset({"scoped_delete", "batch_ingest"})
TERMINAL_STATES = frozenset({"applied", "failed", "refused"})


class LifecycleIdempotencyConflictError(ValueError):
    """Raised when one idempotency key is reused for different work."""


class LifecycleOperationPendingError(RuntimeError):
    """Raised when a write overlaps unfinished lifecycle work."""


@dataclass(frozen=True, slots=True)
class BatchIngestItem:
    text: str
    source_ref: str

    def to_dict(self) -> dict[str, object]:
        text = _required(self.text, "text")
        return {
            "source_ref": _required(self.source_ref, "source_ref"),
            "text_bytes": len(text.encode("utf-8")),
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }

    def private_dict(self) -> dict[str, str]:
        return {
            "source_ref": _required(self.source_ref, "source_ref"),
            "text": _required(self.text, "text"),
        }


def init_lifecycle(connection: sqlite3.Connection) -> None:
    statements = (
        """
        create table if not exists lifecycle_operation (
            operation_seq integer primary key autoincrement,
            operation_id text not null unique,
            tenant_id text not null,
            ns text not null,
            scope text not null,
            kind text not null check (kind in ('scoped_delete', 'batch_ingest')),
            idempotency_key text not null,
            fingerprint text not null,
            payload_json text not null,
            created_by text not null,
            created_at text not null,
            contract_version text not null,
            schema_version integer not null default 1,
            unique (tenant_id, idempotency_key)
        )
        """,
        """
        create table if not exists lifecycle_event (
            event_seq integer primary key autoincrement,
            event_id text not null unique,
            operation_id text not null,
            state text not null,
            actor text not null,
            detail_json text not null,
            created_at text not null,
            schema_version integer not null default 1,
            foreign key (operation_id) references lifecycle_operation(operation_id)
        )
        """,
        """
        create table if not exists lifecycle_batch_payload (
            operation_id text not null,
            item_index integer not null,
            source_ref text not null,
            text_value text not null,
            text_sha256 text not null,
            primary key (operation_id, item_index),
            foreign key (operation_id) references lifecycle_operation(operation_id)
        )
        """,
        """
        create index if not exists idx_lifecycle_operation_boundary
            on lifecycle_operation (tenant_id, ns, scope, operation_seq)
        """,
        """
        create index if not exists idx_lifecycle_event_operation
            on lifecycle_event (operation_id, event_seq)
        """,
        """
        create trigger if not exists lifecycle_operation_no_update
        before update on lifecycle_operation begin
            select raise(abort, 'lifecycle_operation is append-only');
        end
        """,
        """
        create trigger if not exists lifecycle_operation_no_delete
        before delete on lifecycle_operation begin
            select raise(abort, 'lifecycle_operation is append-only');
        end
        """,
        """
        create trigger if not exists lifecycle_event_no_update
        before update on lifecycle_event begin
            select raise(abort, 'lifecycle_event is append-only');
        end
        """,
        """
        create trigger if not exists lifecycle_event_no_delete
        before delete on lifecycle_event begin
            select raise(abort, 'lifecycle_event is append-only');
        end
        """,
    )
    for statement in statements:
        connection.execute(statement)


def plan_scoped_delete(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    namespace: str,
    scope: str,
    record_ids: Iterable[str],
    idempotency_key: str,
    actor: str,
    idempotency_context: str | None = None,
    record_generations: Mapping[str, str] | None = None,
    created_at: str | None = None,
) -> dict[str, object]:
    targets = _refs(record_ids, "record_ids")
    payload: dict[str, object] = {"record_ids": targets}
    if idempotency_context is not None:
        payload["idempotency_context"] = _required(
            idempotency_context, "idempotency_context"
        )
    if record_generations is not None:
        normalized_generations = {
            _required(record_id, "record_generations key"): _required_generation(
                generation
            )
            for record_id, generation in record_generations.items()
        }
        if set(normalized_generations) != set(targets):
            raise ValueError("record generations must exactly match record_ids")
        payload["record_generations"] = normalized_generations
    return _plan_operation(
        connection,
        tenant_id=tenant_id,
        namespace=namespace,
        scope=scope,
        kind="scoped_delete",
        idempotency_key=idempotency_key,
        actor=actor,
        payload=payload,
        created_at=created_at,
    )


def plan_batch_ingest(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    namespace: str,
    scope: str,
    items: Sequence[BatchIngestItem],
    idempotency_key: str,
    actor: str,
    created_at: str | None = None,
) -> dict[str, object]:
    if not items:
        raise ValueError("batch ingest requires at least one item")
    if len(items) > 10_000:
        raise ValueError("batch ingest exceeds 10000 items")
    payload_items = [item.to_dict() for item in items]
    private_items = [item.private_dict() for item in items]
    return _plan_operation(
        connection,
        tenant_id=tenant_id,
        namespace=namespace,
        scope=scope,
        kind="batch_ingest",
        idempotency_key=idempotency_key,
        actor=actor,
        payload={"items": payload_items},
        batch_items=private_items,
        created_at=created_at,
    )


def apply_scoped_delete(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    operation_id: str,
    actor: str,
    interrupt_after_intent: bool = False,
    delete_derived_records: Callable[[tuple[str, ...]], None] | None = None,
) -> dict[str, object]:
    """Soft-delete exact boundary-owned MIRL with a recoverable cleanup outbox."""

    selected_actor = _required(actor, "actor")
    tenant = _required(tenant_id, "tenant_id")
    if delete_derived_records is not None and connection.in_transaction:
        raise RuntimeError(
            "external lifecycle cleanup requires an owned transaction"
        )
    init_lifecycle(connection)
    with _transaction(connection):
        operation = _operation_row(connection, tenant, operation_id)
        if operation["kind"] != "scoped_delete":
            raise ValueError("lifecycle operation is not a scoped delete")
        if not _tenant_owns_namespace(
            str(operation["tenant_id"]), str(operation["namespace"])
        ):
            raise ValueError("lifecycle tenant does not own operation namespace")
        latest = _latest_state(connection, operation_id)
        if latest == "applied":
            return _get_lifecycle_operation(connection, tenant, operation_id)
        if latest in {"failed", "refused"}:
            raise ValueError(f"cannot apply lifecycle operation in state {latest}")
        targets = tuple(operation["payload"]["record_ids"])
        if latest != "cleanup_pending":
            rows = _target_rows(connection, targets)
            found = {str(row["id"]) for row in rows}
            missing = sorted(set(targets) - found)
            cross_boundary = sorted(
                str(row["id"])
                for row in rows
                if str(row["ns"]) != operation["namespace"]
                or str(row["scope"]) != operation["scope"]
            )
            expected_generations = operation["payload"].get(
                "record_generations", {}
            )
            generation_mismatch = sorted(
                str(row["id"])
                for row in rows
                if str(row["id"]) in expected_generations
                and _record_generation(str(row["payload_json"]))
                != expected_generations[str(row["id"])]
            )
            if missing or cross_boundary or generation_mismatch:
                _append_event(
                    connection,
                    operation_id=operation_id,
                    state="refused",
                    actor=selected_actor,
                    detail={
                        "cross_boundary_record_ids": cross_boundary,
                        "generation_mismatch_record_ids": generation_mismatch,
                        "missing_record_ids": missing,
                    },
                )
                return _get_lifecycle_operation(
                    connection, tenant, operation_id
                )
            if latest != "applying":
                _append_event(
                    connection,
                    operation_id=operation_id,
                    state="applying",
                    actor=selected_actor,
                    detail={"record_ids": targets},
                )
            if interrupt_after_intent:
                return _get_lifecycle_operation(
                    connection, tenant, operation_id
                )

            now = utc_now()
            previous_statuses: dict[str, str] = {}
            for row in rows:
                payload = json.loads(str(row["payload_json"]))
                previous_statuses[str(row["id"])] = str(payload["status"])
                payload["status"] = Status.DELETED_SOFT.value
                payload["updated_at"] = now
                ext = dict(payload.get("ext") or {})
                ext["lifecycle_delete_operation"] = operation_id
                payload["ext"] = ext
                connection.execute(
                    "update ir_records set status = ?, updated_at = ?, "
                    "payload_json = ? where id = ?",
                    (
                        Status.DELETED_SOFT.value,
                        now,
                        _canonical_json(payload),
                        str(row["id"]),
                    ),
                )
            remove_knowledge_records(connection, targets)
            placeholders = ",".join("?" for _ in targets)
            connection.execute(
                f"delete from vector_index where record_id in ({placeholders})",
                targets,
            )
            connection.execute(
                f"delete from projection_index where record_id in ({placeholders})",
                targets,
            )
            _append_event(
                connection,
                operation_id=operation_id,
                state="cleanup_pending",
                actor=selected_actor,
                detail={
                    "affected_record_ids": targets,
                    "previous_statuses": previous_statuses,
                },
            )

    if delete_derived_records is not None:
        delete_derived_records(targets)

    with _transaction(connection):
        _operation_row(connection, tenant, operation_id)
        if _latest_state(connection, operation_id) == "cleanup_pending":
            _append_event(
                connection,
                operation_id=operation_id,
                state="applied",
                actor=selected_actor,
                detail={
                    "affected_record_ids": targets,
                    "derived_cleanup_complete": True,
                },
            )
        return _get_lifecycle_operation(connection, tenant, operation_id)


def begin_batch_ingest(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    operation_id: str,
    actor: str,
) -> dict[str, object]:
    selected_actor = _required(actor, "actor")
    tenant = _required(tenant_id, "tenant_id")
    init_lifecycle(connection)
    with _transaction(connection):
        operation = _operation_row(connection, tenant, operation_id)
        if operation["kind"] != "batch_ingest":
            raise ValueError("lifecycle operation is not a batch ingest")
        latest = _latest_state(connection, operation_id)
        if latest == "applied":
            return _get_lifecycle_operation(connection, tenant, operation_id)
        if latest in {"failed", "refused"}:
            raise ValueError(f"cannot resume batch ingest in state {latest}")
        if latest != "applying":
            _append_event(
                connection,
                operation_id=operation_id,
                state="applying",
                actor=selected_actor,
                detail={
                    "completed_indexes": _completed_batch_indexes(
                        connection, operation_id
                    )
                },
            )
        return _get_lifecycle_operation(connection, tenant, operation_id)


def record_batch_item(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    operation_id: str,
    item_index: int,
    stored_ids: Iterable[str],
    actor: str,
) -> dict[str, object]:
    if (
        not isinstance(item_index, int)
        or isinstance(item_index, bool)
        or item_index < 0
    ):
        raise ValueError("item_index must be a non-negative integer")
    ids = _refs(stored_ids, "stored_ids")
    tenant = _required(tenant_id, "tenant_id")
    init_lifecycle(connection)
    with _transaction(connection):
        operation = _operation_row(connection, tenant, operation_id)
        if operation["kind"] != "batch_ingest":
            raise ValueError("lifecycle operation is not a batch ingest")
        items = operation["payload"]["items"]
        if item_index >= len(items):
            raise ValueError("batch item index is out of range")
        latest = _latest_state(connection, operation_id)
        if latest in TERMINAL_STATES:
            raise ValueError(f"cannot record batch item in state {latest}")
        if item_index in _completed_batch_indexes(connection, operation_id):
            return _get_lifecycle_operation(connection, tenant, operation_id)
        _append_event(
            connection,
            operation_id=operation_id,
            state="item_applied",
            actor=_required(actor, "actor"),
            detail={"item_index": item_index, "stored_ids": ids},
        )
        return _get_lifecycle_operation(connection, tenant, operation_id)


def complete_batch_ingest(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    operation_id: str,
    actor: str,
) -> dict[str, object]:
    tenant = _required(tenant_id, "tenant_id")
    init_lifecycle(connection)
    with _transaction(connection):
        operation = _operation_row(connection, tenant, operation_id)
        if operation["kind"] != "batch_ingest":
            raise ValueError("lifecycle operation is not a batch ingest")
        expected = set(range(len(operation["payload"]["items"])))
        completed = set(_completed_batch_indexes(connection, operation_id))
        latest = _latest_state(connection, operation_id)
        if latest in TERMINAL_STATES and latest != "applied":
            raise ValueError(f"cannot complete batch ingest in state {latest}")
        if completed != expected:
            raise ValueError("batch ingest cannot complete with pending items")
        if latest != "applied":
            _append_event(
                connection,
                operation_id=operation_id,
                state="applied",
                actor=_required(actor, "actor"),
                detail={"completed_indexes": tuple(sorted(completed))},
            )
        connection.execute(
            "delete from lifecycle_batch_payload where operation_id = ?",
            (operation_id,),
        )
        return _get_lifecycle_operation(connection, tenant, operation_id)


def completed_batch_indexes(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    operation_id: str,
) -> tuple[int, ...]:
    tenant = _required(tenant_id, "tenant_id")
    init_lifecycle(connection)
    _operation_row(connection, tenant, operation_id)
    return _completed_batch_indexes(connection, operation_id)


def batch_ingest_items(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    operation_id: str,
) -> tuple[BatchIngestItem, ...]:
    """Read transient pending input after exact tenant authorization."""

    tenant = _required(tenant_id, "tenant_id")
    init_lifecycle(connection)
    operation = _operation_row(connection, tenant, operation_id)
    if operation["kind"] != "batch_ingest":
        raise ValueError("lifecycle operation is not a batch ingest")
    rows = connection.execute(
        "select item_index, source_ref, text_value, text_sha256 "
        "from lifecycle_batch_payload where operation_id = ? "
        "order by item_index",
        (operation_id,),
    ).fetchall()
    expected = operation["payload"]["items"]
    if len(rows) != len(expected):
        if _latest_state(connection, operation_id) == "applied" and not rows:
            return ()
        raise ValueError("batch ingest transient payload is incomplete")
    items: list[BatchIngestItem] = []
    for row, audit in zip(rows, expected, strict=True):
        index = int(row[0])
        source_ref = str(row[1])
        text = str(row[2])
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if (
            index != len(items)
            or source_ref != str(audit["source_ref"])
            or digest != str(row[3])
            or digest != str(audit["text_sha256"])
        ):
            raise ValueError("batch ingest transient payload failed audit")
        items.append(BatchIngestItem(text=text, source_ref=source_ref))
    return tuple(items)


def _completed_batch_indexes(
    connection: sqlite3.Connection, operation_id: str
) -> tuple[int, ...]:
    rows = connection.execute(
        "select detail_json from lifecycle_event "
        "where operation_id = ? and state = 'item_applied' order by event_seq",
        (_required(operation_id, "operation_id"),),
    ).fetchall()
    return tuple(
        sorted(
            {
                int(json.loads(str(row[0]))["item_index"])
                for row in rows
            }
        )
    )


def recoverable_operations(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    limit: int = 100,
) -> list[dict[str, object]]:
    if limit < 1 or limit > 1_000:
        raise ValueError("limit must be between 1 and 1000")
    tenant = _required(tenant_id, "tenant_id")
    init_lifecycle(connection)
    where = [
        "o.tenant_id = ?",
        "(select e.state from lifecycle_event e "
        "where e.operation_id = o.operation_id "
        "order by e.event_seq desc limit 1) "
        "in ('planned', 'applying', 'cleanup_pending', 'item_applied')",
    ]
    rows = connection.execute(
        "select o.operation_id from lifecycle_operation o "
        f"where {' and '.join(where)} "
        "order by o.operation_seq desc limit ?",
        (tenant, limit),
    ).fetchall()
    return [
        _get_lifecycle_operation(connection, tenant, str(row[0]))
        for row in rows
    ]


def get_lifecycle_operation(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    operation_id: str,
) -> dict[str, object]:
    tenant = _required(tenant_id, "tenant_id")
    init_lifecycle(connection)
    return _get_lifecycle_operation(connection, tenant, operation_id)


def _get_lifecycle_operation(
    connection: sqlite3.Connection, tenant_id: str, operation_id: str
) -> dict[str, object]:
    operation = _operation_row(connection, tenant_id, operation_id)
    event_rows = connection.execute(
        "select event_id, state, actor, detail_json, created_at, schema_version "
        "from lifecycle_event where operation_id = ? order by event_seq",
        (operation_id,),
    ).fetchall()
    events = [
        {
            "actor": str(row[2]),
            "created_at": str(row[4]),
            "detail": json.loads(str(row[3])),
            "event_id": str(row[0]),
            "schema_version": int(row[5]),
            "state": str(row[1]),
        }
        for row in event_rows
    ]
    return {
        **operation,
        "events": events,
        "state": events[-1]["state"] if events else "unknown",
    }


def _plan_operation(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    namespace: str,
    scope: str,
    kind: str,
    idempotency_key: str,
    actor: str,
    payload: Mapping[str, object],
    created_at: str | None,
    batch_items: Sequence[Mapping[str, str]] = (),
) -> dict[str, object]:
    tenant = _required(tenant_id, "tenant_id")
    ns = _required(namespace, "namespace")
    selected_scope = _required(scope, "scope")
    selected_kind = _required(kind, "kind")
    if selected_kind not in OPERATION_KINDS:
        raise ValueError("unknown lifecycle operation kind")
    key = _required(idempotency_key, "idempotency_key")
    selected_actor = _required(actor, "actor")
    if not _tenant_owns_namespace(tenant, ns):
        raise ValueError("tenant_id does not own namespace")
    material = {
        "contract_version": LIFECYCLE_CONTRACT_VERSION,
        "kind": selected_kind,
        "namespace": ns,
        "payload": payload,
        "scope": selected_scope,
        "tenant_id": tenant,
    }
    fingerprint = _digest(material)
    operation_identity = {
        "fingerprint": fingerprint,
        "idempotency_key": key,
        "tenant_id": tenant,
    }
    operation_id = f"life:{_digest(operation_identity)[:24]}"
    init_lifecycle(connection)
    with _transaction(connection):
        existing = connection.execute(
            "select operation_id, fingerprint from lifecycle_operation "
            "where tenant_id = ? and idempotency_key = ?",
            (tenant, key),
        ).fetchone()
        if existing is not None:
            if str(existing[1]) != fingerprint:
                raise LifecycleIdempotencyConflictError(
                    "idempotency key already names a different operation"
                )
            return _get_lifecycle_operation(
                connection, tenant, str(existing[0])
            )
        timestamp = str(created_at or utc_now())
        connection.execute(
            "insert into lifecycle_operation "
            "(operation_id, tenant_id, ns, scope, kind, idempotency_key, "
            "fingerprint, payload_json, created_by, created_at, "
            "contract_version, schema_version) "
            "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                operation_id,
                tenant,
                ns,
                selected_scope,
                selected_kind,
                key,
                fingerprint,
                _canonical_json(payload),
                selected_actor,
                timestamp,
                LIFECYCLE_CONTRACT_VERSION,
                LIFECYCLE_SCHEMA_VERSION,
            ),
        )
        for item_index, item in enumerate(batch_items):
            text = _required(item.get("text"), "batch item text")
            source_ref = _required(
                item.get("source_ref"), "batch item source_ref"
            )
            connection.execute(
                "insert into lifecycle_batch_payload "
                "(operation_id, item_index, source_ref, text_value, text_sha256) "
                "values (?, ?, ?, ?, ?)",
                (
                    operation_id,
                    item_index,
                    source_ref,
                    text,
                    hashlib.sha256(text.encode("utf-8")).hexdigest(),
                ),
            )
        _append_event(
            connection,
            operation_id=operation_id,
            state="planned",
            actor=selected_actor,
            detail={"fingerprint": fingerprint},
            created_at=timestamp,
        )
        return _get_lifecycle_operation(connection, tenant, operation_id)


def _operation_row(
    connection: sqlite3.Connection, tenant_id: str, operation_id: str
) -> dict[str, object]:
    tenant = _required(tenant_id, "tenant_id")
    selected = _required(operation_id, "operation_id")
    row = connection.execute(
        "select operation_id, tenant_id, ns, scope, kind, idempotency_key, "
        "fingerprint, payload_json, created_by, created_at, contract_version, "
        "schema_version from lifecycle_operation "
        "where operation_id = ? and tenant_id = ?",
        (selected, tenant),
    ).fetchone()
    if row is None:
        raise KeyError(selected)
    return {
        "contract_version": str(row[10]),
        "created_at": str(row[9]),
        "created_by": str(row[8]),
        "fingerprint": str(row[6]),
        "idempotency_key": str(row[5]),
        "kind": str(row[4]),
        "namespace": str(row[2]),
        "operation_id": str(row[0]),
        "payload": json.loads(str(row[7])),
        "schema_version": int(row[11]),
        "scope": str(row[3]),
        "tenant_id": str(row[1]),
    }


def _latest_state(connection: sqlite3.Connection, operation_id: str) -> str:
    row = connection.execute(
        "select state from lifecycle_event where operation_id = ? "
        "order by event_seq desc limit 1",
        (operation_id,),
    ).fetchone()
    return str(row[0]) if row is not None else "unknown"


def _append_event(
    connection: sqlite3.Connection,
    *,
    operation_id: str,
    state: str,
    actor: str,
    detail: Mapping[str, object],
    created_at: str | None = None,
) -> None:
    timestamp = str(created_at or utc_now())
    event_id = f"life-event:{uuid4().hex[:24]}"
    connection.execute(
        "insert into lifecycle_event "
        "(event_id, operation_id, state, actor, detail_json, created_at, "
        "schema_version) values (?, ?, ?, ?, ?, ?, ?)",
        (
            event_id,
            operation_id,
            _required(state, "state"),
            _required(actor, "actor"),
            _canonical_json(detail),
            timestamp,
            LIFECYCLE_SCHEMA_VERSION,
        ),
    )


def _target_rows(
    connection: sqlite3.Connection, record_ids: Sequence[str]
) -> list[sqlite3.Row]:
    placeholders = ",".join("?" for _ in record_ids)
    return connection.execute(
        "select id, ns, scope, payload_json from ir_records "
        f"where id in ({placeholders}) order by id",
        record_ids,
    ).fetchall()


def ensure_no_active_scoped_delete(
    connection: sqlite3.Connection,
    *,
    namespace: str,
    scope: str,
    record_ids: Iterable[str],
) -> None:
    """Refuse a new incarnation while delete cleanup can still resume."""

    targets = set(_refs(record_ids, "record_ids"))
    init_lifecycle(connection)
    rows = connection.execute(
        "select operation.payload_json from lifecycle_operation operation "
        "where operation.kind = 'scoped_delete' and operation.ns = ? "
        "and operation.scope = ? and (select event.state from lifecycle_event event "
        "where event.operation_id = operation.operation_id "
        "order by event.event_seq desc limit 1) "
        "in ('planned', 'applying', 'cleanup_pending')",
        (_required(namespace, "namespace"), _required(scope, "scope")),
    ).fetchall()
    if any(
        targets.intersection(json.loads(str(row[0])).get("record_ids", ()))
        for row in rows
    ):
        raise LifecycleOperationPendingError(
            "memory deletion is still pending"
        )


def _record_generation(payload_json: str) -> str | None:
    payload = json.loads(payload_json)
    ext = payload.get("ext")
    generation = (
        ext.get("public_memory_generation") if isinstance(ext, dict) else None
    )
    return generation if isinstance(generation, str) else None


@contextmanager
def _transaction(connection: sqlite3.Connection) -> Iterator[None]:
    owned = not connection.in_transaction
    if owned:
        connection.execute("begin immediate")
    try:
        yield
    except Exception:
        if owned:
            connection.rollback()
        raise
    else:
        if owned:
            connection.commit()


def _refs(values: Iterable[str], field: str) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError(f"{field} must be an iterable of references")
    refs = tuple(sorted({_required(value, field) for value in values}))
    if not refs:
        raise ValueError(f"{field} must contain at least one reference")
    if len(refs) > 10_000:
        raise ValueError(f"{field} exceeds 10000 references")
    return refs


def _required(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _required_generation(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(
            "record generation must be 64 lowercase hexadecimal characters"
        )
    return value


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()
