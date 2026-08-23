"""Indexed opaque-handle projection for the public memory API.

Canonical MIRL remains the source of truth. This table is a rebuildable adapter
index that lets the public deletion contract resolve only handles previously
returned to a caller, without scanning or exposing canonical record IDs.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from typing import Final

from .mirl import utc_now
from .tenancy import tenant_owns_namespace

PUBLIC_MEMORY_HANDLE_SCHEMA_VERSION: Final = 1
PUBLIC_MEMORY_HANDLE_CONTRACT_VERSION: Final = "public-memory-handle/1"
PUBLIC_MEMORY_GENERATION_EXTENSION: Final = "public_memory_generation"

_PUBLIC_MEMORY_HANDLE_COLUMNS: Final = (
    ("handle_id", "TEXT", 0, None, 1),
    ("tenant_id", "TEXT", 1, None, 0),
    ("ns", "TEXT", 1, None, 0),
    ("scope", "TEXT", 1, None, 0),
    ("record_id", "TEXT", 1, None, 0),
    ("generation", "TEXT", 1, None, 0),
    ("created_at", "TEXT", 1, None, 0),
    ("contract_version", "TEXT", 1, None, 0),
    ("schema_version", "INTEGER", 1, "1", 0),
)
_BOUNDARY_INDEX_NAME: Final = "idx_public_memory_handle_boundary"
_BOUNDARY_INDEX_COLUMNS: Final = ("tenant_id", "ns", "scope", "handle_id")
_ROW_COLUMNS: Final = tuple(column[0] for column in _PUBLIC_MEMORY_HANDLE_COLUMNS)


class PublicMemoryHandleStaleError(RuntimeError):
    """Raised when a recall snapshot no longer names the live generation."""


def init_public_memory_handles(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        create table if not exists public_memory_handle (
            handle_id text primary key,
            tenant_id text not null,
            ns text not null,
            scope text not null,
            record_id text not null,
            generation text not null,
            created_at text not null,
            contract_version text not null,
            schema_version integer not null default 1,
            foreign key (record_id) references ir_records(id) on delete cascade
        )
        """
    )
    connection.execute(
        """
        create index if not exists idx_public_memory_handle_boundary
            on public_memory_handle (tenant_id, ns, scope, handle_id)
        """
    )


def public_memory_handle_schema_errors(
    connection: sqlite3.Connection,
) -> tuple[str, ...]:
    """Return content-free structural and row-contract errors for core-storage/4."""

    errors: list[str] = []
    columns = tuple(
        (
            str(row[1]),
            str(row[2]).upper(),
            int(row[3]),
            str(row[4]) if row[4] is not None else None,
            int(row[5]),
        )
        for row in connection.execute(
            "pragma table_info(public_memory_handle)"
        ).fetchall()
    )
    if columns != _PUBLIC_MEMORY_HANDLE_COLUMNS:
        errors.append("columns")

    foreign_keys = {
        (str(row[2]), str(row[3]), str(row[4]), str(row[6]).upper())
        for row in connection.execute(
            "pragma foreign_key_list(public_memory_handle)"
        ).fetchall()
    }
    if foreign_keys != {("ir_records", "record_id", "id", "CASCADE")}:
        errors.append("record foreign key")

    index_rows = connection.execute(
        "pragma index_list(public_memory_handle)"
    ).fetchall()
    boundary_index = next(
        (
            row
            for row in index_rows
            if str(row[1]) == _BOUNDARY_INDEX_NAME
        ),
        None,
    )
    boundary_columns = tuple(
        str(row[2])
        for row in connection.execute(
            "select * from pragma_index_info(?) order by seqno",
            (_BOUNDARY_INDEX_NAME,),
        ).fetchall()
    )
    if (
        boundary_index is None
        or (int(boundary_index[2]), str(boundary_index[3]), int(boundary_index[4]))
        != (0, "c", 0)
        or boundary_columns != _BOUNDARY_INDEX_COLUMNS
    ):
        errors.append("boundary index")
    unique_indexes = {
        (
            str(row[3]),
            int(row[4]),
            tuple(
                str(info[2])
                for info in connection.execute(
                    "select * from pragma_index_info(?) order by seqno",
                    (str(row[1]),),
                ).fetchall()
            ),
        )
        for row in index_rows
        if int(row[2]) == 1
    }
    if unique_indexes != {("pk", 0, ("handle_id",))}:
        errors.append("unique indexes")
    if connection.execute(
        "select 1 from sqlite_master where type = 'trigger' "
        "and tbl_name = 'public_memory_handle' limit 1"
    ).fetchone() is not None:
        errors.append("triggers")

    # Do not issue row queries against a same-named but structurally incompatible
    # table.  This keeps corruption diagnostics content-free and deterministic.
    if errors:
        return tuple(errors)

    invalid_row = connection.execute(
        "select 1 from public_memory_handle handles "
        "left join ir_records records on records.id = handles.record_id where "
        "typeof(handles.contract_version) != 'text' "
        "or handles.contract_version != ? "
        "or typeof(handles.schema_version) != 'integer' "
        "or handles.schema_version != ? "
        "or typeof(handles.handle_id) != 'text' "
        "or trim(handles.handle_id) != handles.handle_id "
        "or length(handles.handle_id) != 28 "
        "or substr(handles.handle_id, 1, 4) != 'mem_' "
        "or substr(handles.handle_id, 5) glob '*[^0-9a-f]*' "
        "or typeof(handles.tenant_id) != 'text' "
        "or trim(handles.tenant_id) = '' "
        "or trim(handles.tenant_id) != handles.tenant_id "
        "or typeof(handles.ns) != 'text' or trim(handles.ns) = '' "
        "or trim(handles.ns) != handles.ns "
        "or typeof(handles.scope) != 'text' or trim(handles.scope) = '' "
        "or trim(handles.scope) != handles.scope "
        "or typeof(handles.record_id) != 'text' "
        "or trim(handles.record_id) = '' "
        "or typeof(handles.generation) != 'text' "
        "or length(handles.generation) != 64 "
        "or handles.generation glob '*[^0-9a-f]*' "
        "or typeof(handles.created_at) != 'text' "
        "or trim(handles.created_at) = '' "
        "or trim(handles.created_at) != handles.created_at "
        "or not (handles.ns = handles.tenant_id "
        "or substr(handles.ns, 1, length(handles.tenant_id) + 1) "
        "= handles.tenant_id || '.' "
        "or substr(handles.ns, 1, length(handles.tenant_id) + 1) "
        "= handles.tenant_id || ':') "
        "or records.id is null or records.ns != handles.ns "
        "or records.scope != handles.scope "
        "or coalesce(json_extract(records.payload_json, "
        "'$.ext.public_memory_generation'), '') != handles.generation limit 1",
        (
            PUBLIC_MEMORY_HANDLE_CONTRACT_VERSION,
            PUBLIC_MEMORY_HANDLE_SCHEMA_VERSION,
        ),
    ).fetchone()
    if invalid_row is not None:
        errors.append("rows")
    return tuple(errors)


def register_public_memory_handles(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    namespace: str,
    scope: str,
    handles: Mapping[str, tuple[str, str]],
) -> None:
    """Register generation-bound handles inside one exact boundary."""

    if not handles:
        return
    tenant = _required(tenant_id, "tenant_id")
    ns = _required(namespace, "namespace")
    selected_scope = _required(scope, "scope")
    if not tenant_owns_namespace(tenant, ns):
        raise ValueError("tenant_id does not own namespace")
    normalized = {
        _required_handle_id(handle_id): (
            _required_preserving(record_and_generation[0], "record_id"),
            _required_generation(record_and_generation[1]),
        )
        for handle_id, record_and_generation in handles.items()
    }
    expected_generations: dict[str, str] = {}
    for record_id, generation in normalized.values():
        prior = expected_generations.setdefault(record_id, generation)
        if prior != generation:
            raise ValueError("one record cannot register multiple generations")
    record_ids = sorted(expected_generations)
    placeholders = ",".join("?" for _ in record_ids)
    rows = connection.execute(
        "select id, payload_json from ir_records "
        f"where id in ({placeholders}) and ns = ? and scope = ? "
        "and status != ?",
        [*record_ids, ns, selected_scope, "deleted_soft"],
    ).fetchall()
    current_generations = {
        str(row[0]): _payload_generation(str(row[1])) for row in rows
    }
    if current_generations != expected_generations:
        raise PublicMemoryHandleStaleError(
            "public memory handles require the current record generation"
        )

    handle_ids = sorted(normalized)
    handle_placeholders = ",".join("?" for _ in handle_ids)
    existing = connection.execute(
        "select handle_id, tenant_id, ns, scope, record_id, generation "
        "from public_memory_handle "
        f"where handle_id in ({handle_placeholders})",
        handle_ids,
    ).fetchall()
    for row in existing:
        handle_id = str(row[0])
        if (
            str(row[1]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            str(row[5]),
        ) != (tenant, ns, selected_scope, *normalized[handle_id]):
            raise ValueError("opaque public memory handle collision")

    timestamp = utc_now()
    connection.executemany(
        "insert into public_memory_handle "
        "(handle_id, tenant_id, ns, scope, record_id, generation, created_at, "
        "contract_version, schema_version) values (?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "on conflict(handle_id) do nothing",
        [
            (
                handle_id,
                tenant,
                ns,
                selected_scope,
                normalized[handle_id][0],
                normalized[handle_id][1],
                timestamp,
                PUBLIC_MEMORY_HANDLE_CONTRACT_VERSION,
                PUBLIC_MEMORY_HANDLE_SCHEMA_VERSION,
            )
            for handle_id in handle_ids
        ],
    )
    registered = connection.execute(
        "select handle_id, tenant_id, ns, scope, record_id, generation "
        "from public_memory_handle "
        f"where handle_id in ({handle_placeholders})",
        handle_ids,
    ).fetchall()
    actual = {
        str(row[0]): (
            str(row[1]),
            str(row[2]),
            str(row[3]),
            str(row[4]),
            str(row[5]),
        )
        for row in registered
    }
    expected = {
        handle_id: (tenant, ns, selected_scope, *normalized[handle_id])
        for handle_id in handle_ids
    }
    if actual != expected:
        raise RuntimeError("public memory handle registration failed")


def resolve_public_memory_handles(
    connection: sqlite3.Connection,
    *,
    tenant_id: str,
    namespace: str,
    scope: str,
    handle_ids: Sequence[str],
) -> dict[str, tuple[str, str]]:
    """Resolve registered handles inside one boundary without membership leaks."""

    if not handle_ids:
        return {}
    tenant = _required(tenant_id, "tenant_id")
    ns = _required(namespace, "namespace")
    selected_scope = _required(scope, "scope")
    normalized = tuple(_required(handle_id, "handle_id") for handle_id in handle_ids)
    placeholders = ",".join("?" for _ in normalized)
    rows = connection.execute(
        "select handles.handle_id, handles.record_id, handles.generation, "
        "records.payload_json from public_memory_handle handles "
        "join ir_records records on records.id = handles.record_id "
        f"where handles.handle_id in ({placeholders}) "
        "and handles.tenant_id = ? and handles.ns = ? and handles.scope = ? "
        "and records.status != ?",
        [*normalized, tenant, ns, selected_scope, "deleted_soft"],
    ).fetchall()
    return {
        str(row[0]): (str(row[1]), str(row[2]))
        for row in rows
        if _payload_generation(str(row[3])) == str(row[2])
    }


def snapshot_public_memory_handle_rows(
    connection: sqlite3.Connection,
    record_ids: Iterable[str],
) -> tuple[tuple[object, ...], ...]:
    """Capture the exact disposable handle rows owned by canonical records."""

    ordered_ids = sorted(
        {_required_preserving(record_id, "record_id") for record_id in record_ids}
    )
    if not ordered_ids:
        return ()
    rows: list[tuple[object, ...]] = []
    columns = ", ".join(_ROW_COLUMNS)
    for start in range(0, len(ordered_ids), 500):
        chunk = ordered_ids[start : start + 500]
        placeholders = ",".join("?" for _ in chunk)
        rows.extend(
            tuple(row)
            for row in connection.execute(
                f"select {columns} from public_memory_handle "
                f"where record_id in ({placeholders}) order by handle_id",
                chunk,
            ).fetchall()
        )
    return tuple(sorted(rows, key=lambda row: str(row[0])))


def restore_public_memory_handle_rows(
    connection: sqlite3.Connection,
    record_ids: Iterable[str],
    previous_rows: Sequence[tuple[object, ...]],
) -> None:
    """Restore one exact handle slice inside the caller's write transaction."""

    ordered_ids = sorted(
        {_required_preserving(record_id, "record_id") for record_id in record_ids}
    )
    touched = set(ordered_ids)
    expected: dict[str, tuple[object, ...]] = {}
    for raw_row in previous_rows:
        row = tuple(raw_row)
        if len(row) != len(_ROW_COLUMNS) or str(row[4]) not in touched:
            raise ValueError("invalid public memory handle rollback snapshot")
        handle_id = _required_handle_id(row[0])
        _required_generation(row[5])
        if handle_id in expected:
            raise ValueError("invalid public memory handle rollback snapshot")
        expected[handle_id] = row
    for start in range(0, len(ordered_ids), 500):
        chunk = ordered_ids[start : start + 500]
        placeholders = ",".join("?" for _ in chunk)
        connection.execute(
            f"delete from public_memory_handle where record_id in ({placeholders})",
            chunk,
        )
    if expected:
        columns = ", ".join(_ROW_COLUMNS)
        placeholders = ", ".join("?" for _ in _ROW_COLUMNS)
        connection.executemany(
            f"insert into public_memory_handle ({columns}) values ({placeholders})",
            [expected[handle_id] for handle_id in sorted(expected)],
        )
    actual = snapshot_public_memory_handle_rows(connection, ordered_ids)
    if actual != tuple(expected[handle_id] for handle_id in sorted(expected)):
        raise RuntimeError("public memory handle rollback failed")


def _payload_generation(payload_json: str) -> str | None:
    import json

    try:
        payload = json.loads(payload_json)
    except (TypeError, ValueError):
        return None
    ext = payload.get("ext")
    generation = (
        ext.get(PUBLIC_MEMORY_GENERATION_EXTENSION)
        if isinstance(ext, dict)
        else None
    )
    return generation if isinstance(generation, str) else None


def _required_generation(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("generation must be 64 lowercase hexadecimal characters")
    return value


def _required(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _required_handle_id(value: object) -> str:
    handle_id = _required(value, "handle_id")
    suffix = handle_id[4:]
    if (
        len(handle_id) != 28
        or not handle_id.startswith("mem_")
        or any(character not in "0123456789abcdef" for character in suffix)
    ):
        raise ValueError("handle_id must be an opaque mem_ id")
    return handle_id


def _required_preserving(value: object, field: str) -> str:
    """Validate an opaque canonical value without rewriting its identity bytes."""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value
