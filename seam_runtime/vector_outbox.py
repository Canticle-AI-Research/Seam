"""Durable intent queue for derived vector indexing.

Audit finding F7: the canonical database commit precedes derived vector
indexing, and the compensation for a failed index is not process-durable. A
crash between the two leaves canonical records that no vector backend knows
about, and nothing in the database records that the work is owed. The gap is
invisible -- retrieval simply stops returning those records.

The outbox closes it with the standard transactional-outbox shape:

1. The canonical write and an ``index`` intent for each touched record commit
   in **one** SQLite transaction, so the intent cannot be lost while the record
   survives.
2. The vector backend is updated.
3. The intents are acknowledged (deleted).

Every crash point converges on reopen:

===========================  ==============================================
crash before step 1 commits  nothing happened; nothing is owed
between steps 1 and 2        intents survive and replay indexes the records
between steps 2 and 3        intents survive and replay re-indexes them
after step 3                 nothing pending
===========================  ==============================================

The middle two rows are why replay must be idempotent rather than merely
correct-once: after a crash we cannot tell whether the backend was updated, so
replay always assumes it was not. Re-indexing an already-indexed record is a
content-hash no-op in every adapter, which makes duplicate replay harmless by
construction instead of by bookkeeping.

Deletes are not queued here. Scoped deletion already carries its own durable
``cleanup_pending`` lifecycle state and recovers through
``recoverable_operations``; adding a second mechanism over the same transition
would create two sources of truth for one operation.
"""

from __future__ import annotations

import sqlite3
from typing import Iterable, Sequence

from .mirl import utc_now

VECTOR_OUTBOX_TABLE = "vector_outbox"
OPERATION_INDEX = "index"

# Keep every one-shot ``IN (...)`` below SQLite's legacy 999-variable floor.
_ID_CHUNK = 400


def init_vector_outbox(connection: sqlite3.Connection) -> None:
    """Create the outbox table if it is absent.

    Created lazily on use, the same way ``init_lifecycle`` establishes the
    lifecycle tables, so existing databases gain it without a spine migration.
    The migration spine validates that required projection tables are present
    and never refuses additional ones.
    """

    connection.execute(
        f"""
        create table if not exists {VECTOR_OUTBOX_TABLE} (
            entry_id integer primary key autoincrement,
            record_id text not null,
            operation text not null check (operation in ('{OPERATION_INDEX}')),
            enqueued_at text not null,
            attempts integer not null default 0,
            last_error text,
            ingest_document_id text
        )
        """
    )
    columns = {
        str(row[1])
        for row in connection.execute(
            f"pragma table_info({VECTOR_OUTBOX_TABLE})"
        ).fetchall()
    }
    if "ingest_document_id" not in columns:
        connection.execute(
            f"alter table {VECTOR_OUTBOX_TABLE} add column ingest_document_id text"
        )
    connection.execute(
        f"create index if not exists {VECTOR_OUTBOX_TABLE}_record_idx "
        f"on {VECTOR_OUTBOX_TABLE} (record_id)"
    )
    connection.execute(
        f"create index if not exists {VECTOR_OUTBOX_TABLE}_ingest_document_idx "
        f"on {VECTOR_OUTBOX_TABLE} (ingest_document_id)"
    )


def enqueue_index_intents(
    connection: sqlite3.Connection,
    record_ids: Sequence[str],
    *,
    now: str | None = None,
    ingest_document_id: str | None = None,
) -> list[int]:
    """Record that ``record_ids`` owe a vector index update.

    Must be called on the connection that is writing the canonical records and
    before that transaction commits; that shared transaction is the entire
    guarantee.
    """

    ordered = [str(record_id) for record_id in record_ids if str(record_id)]
    if not ordered:
        return []
    init_vector_outbox(connection)
    enqueued_at = now or utc_now()
    entry_ids: list[int] = []
    for record_id in ordered:
        cursor = connection.execute(
            f"insert into {VECTOR_OUTBOX_TABLE} "
            "(record_id, operation, enqueued_at, ingest_document_id) "
            "values (?, ?, ?, ?)",
            (record_id, OPERATION_INDEX, enqueued_at, ingest_document_id),
        )
        entry_ids.append(int(cursor.lastrowid))
    return entry_ids


def pending_entries(
    connection: sqlite3.Connection,
    *,
    limit: int | None = None,
) -> list[dict[str, object]]:
    """Return unacknowledged intents in enqueue order."""

    if not _table_exists(connection):
        return []
    has_document_id = any(
        str(row[1]) == "ingest_document_id"
        for row in connection.execute(
            f"pragma table_info({VECTOR_OUTBOX_TABLE})"
        ).fetchall()
    )
    document_expression = (
        "ingest_document_id" if has_document_id else "null as ingest_document_id"
    )
    sql = (
        f"select entry_id, record_id, operation, enqueued_at, attempts, last_error, "
        f"{document_expression} "
        f"from {VECTOR_OUTBOX_TABLE} order by entry_id"
    )
    params: list[object] = []
    if limit is not None:
        sql += " limit ?"
        params.append(int(limit))
    return [
        {
            "entry_id": int(row[0]),
            "record_id": str(row[1]),
            "operation": str(row[2]),
            "enqueued_at": str(row[3]),
            "attempts": int(row[4]),
            "last_error": row[5],
            "ingest_document_id": row[6],
        }
        for row in connection.execute(sql, params).fetchall()
    ]


def pending_count(connection: sqlite3.Connection) -> int:
    if not _table_exists(connection):
        return 0
    row = connection.execute(
        f"select count(*) from {VECTOR_OUTBOX_TABLE}"
    ).fetchone()
    return int(row[0]) if row else 0


def acknowledge(connection: sqlite3.Connection, entry_ids: Iterable[int]) -> int:
    """Delete acknowledged intents; returns how many rows were removed."""

    ordered = sorted({int(entry_id) for entry_id in entry_ids})
    if not ordered or not _table_exists(connection):
        return 0
    removed = 0
    for start in range(0, len(ordered), _ID_CHUNK):
        chunk = ordered[start : start + _ID_CHUNK]
        placeholders = ",".join("?" for _ in chunk)
        cursor = connection.execute(
            f"delete from {VECTOR_OUTBOX_TABLE} where entry_id in ({placeholders})",
            chunk,
        )
        removed += int(cursor.rowcount or 0)
    return removed


def record_failure(
    connection: sqlite3.Connection,
    entry_ids: Iterable[int],
    *,
    error_type: str,
) -> None:
    """Count one failed attempt against each intent.

    ``error_type`` is an exception class name, never a message: outbox rows are
    operator-visible and a message can carry record content or a credential.
    """

    ordered = sorted({int(entry_id) for entry_id in entry_ids})
    if not ordered or not _table_exists(connection):
        return
    for start in range(0, len(ordered), _ID_CHUNK):
        chunk = ordered[start : start + _ID_CHUNK]
        placeholders = ",".join("?" for _ in chunk)
        connection.execute(
            f"update {VECTOR_OUTBOX_TABLE} "
            "set attempts = attempts + 1, last_error = ? "
            f"where entry_id in ({placeholders})",
            [str(error_type), *chunk],
        )


def _table_exists(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "select 1 from sqlite_master where type = 'table' and name = ?",
        (VECTOR_OUTBOX_TABLE,),
    ).fetchone()
    return row is not None
