"""Context-local committed read snapshots for SQLite-backed retrieval.

One retrieval request must answer from a single committed database state.
Before this module every leg opened its own connection and every connection
read its own implicit transaction, so a `mix` search running concurrently with
an ingest could assemble a candidate set -- and a ``candidate_set_sha256``
attesting it -- from database states that never coexisted.

A snapshot binds one connection, inside one deferred read transaction, to the
calling context for the whole request. Every read that resolves the same
database key reuses that connection, so the canonical legs, the graph
visibility checks, and the same-file SQLite vector index all observe one state.

Two properties make the binding safe to apply this broadly:

* **Context-local.** Bindings live in a :class:`~contextvars.ContextVar`, so
  concurrent requests never share a snapshot. Threads start from a fresh
  context, which is what a per-request snapshot wants: a worker thread opens
  its own snapshot rather than silently joining its parent's.
* **Read-only.** While a snapshot is bound the connection carries a SQLite
  authorizer that denies every mutating action. Without it a stray write would
  join the read transaction and be silently discarded by the closing rollback;
  with it the write raises instead. The guard is what makes "reuse the request's
  connection everywhere" a safe default rather than a data-loss hazard.

Keys are database identities, not store identities, so a second reader of the
same file (the SQLite vector index is opened on ``store.path``) joins the same
snapshot. Private in-memory databases are keyed per owner and therefore never
join a snapshot belonging to a different database.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator

__all__ = [
    "SnapshotWriteDenied",
    "active_connection",
    "bind_connection",
    "memory_snapshot_key",
    "physical_open_count",
    "record_physical_open",
    "reset_physical_open_counts",
    "snapshot_key_for_path",
]


class SnapshotWriteDenied(RuntimeError):
    """Raised when a write is attempted on a bound read snapshot."""


# Every authorizer action that can modify durable state. Denying by explicit
# action rather than allowing by explicit action keeps ordinary reads working:
# a read issues SQLITE_READ/SELECT/FUNCTION/PRAGMA and several undocumented
# internal actions, and an allowlist would have to enumerate all of them.
_DENIED_ACTIONS = frozenset(
    {
        sqlite3.SQLITE_INSERT,
        sqlite3.SQLITE_UPDATE,
        sqlite3.SQLITE_DELETE,
        sqlite3.SQLITE_CREATE_TABLE,
        sqlite3.SQLITE_CREATE_INDEX,
        sqlite3.SQLITE_CREATE_VIEW,
        sqlite3.SQLITE_CREATE_TRIGGER,
        sqlite3.SQLITE_DROP_TABLE,
        sqlite3.SQLITE_DROP_INDEX,
        sqlite3.SQLITE_DROP_VIEW,
        sqlite3.SQLITE_DROP_TRIGGER,
        sqlite3.SQLITE_ALTER_TABLE,
        sqlite3.SQLITE_REINDEX,
    }
)

# One binding per database key. The value is an immutable tuple so that setting
# a binding in a child context can never mutate the parent's view.
_ACTIVE: ContextVar[tuple[tuple[str, sqlite3.Connection], ...]] = ContextVar(
    "seam_read_snapshot_bindings", default=()
)

_OPEN_COUNTS: dict[str, int] = {}
_OPEN_COUNTS_LOCK = threading.Lock()


def snapshot_key_for_path(path: str) -> str:
    """Return the snapshot key naming the database at ``path``.

    File databases key on the path itself, so every reader of one file shares a
    snapshot. ``:memory:`` names a *private* database per connection, so it can
    never be shared and is refused here; owners of an in-memory database use
    :func:`memory_snapshot_key` instead.
    """

    if path == ":memory:":
        raise ValueError(
            "':memory:' names a private database; use memory_snapshot_key(owner)"
        )
    return path


def memory_snapshot_key(owner: object) -> str:
    """Return the snapshot key for an in-memory database owned by ``owner``."""

    return f"memory:{id(owner):x}"


def active_connection(key: str) -> sqlite3.Connection | None:
    """Return the snapshot connection bound to ``key`` in this context."""

    for bound_key, connection in _ACTIVE.get():
        if bound_key == key:
            return connection
    return None


def record_physical_open(key: str) -> None:
    """Count one physical connection opened against ``key``.

    Instrumentation for the S5 clause that warm retrieval opens no new physical
    SQLite connections. Counting at the two real ``sqlite3.connect`` sites is
    what makes that clause measurable instead of asserted.
    """

    with _OPEN_COUNTS_LOCK:
        _OPEN_COUNTS[key] = _OPEN_COUNTS.get(key, 0) + 1


def physical_open_count(key: str) -> int:
    """Return how many physical connections have been opened against ``key``."""

    with _OPEN_COUNTS_LOCK:
        return _OPEN_COUNTS.get(key, 0)


def reset_physical_open_counts() -> None:
    """Clear the physical-open counters (test instrumentation)."""

    with _OPEN_COUNTS_LOCK:
        _OPEN_COUNTS.clear()


def _deny_writes(action: int, arg1, arg2, database, trigger) -> int:
    if action in _DENIED_ACTIONS:
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


@contextmanager
def bind_connection(
    key: str,
    checkout: Callable[[], object],
) -> Iterator[sqlite3.Connection]:
    """Hold one committed read snapshot of ``key`` for the calling context.

    ``checkout`` is a zero-argument callable returning a context manager that
    yields a connection -- normally a pool checkout, so a snapshot reuses a
    pooled connection instead of opening a new one.

    Re-entering with a key that is already bound yields the existing connection
    and leaves the transaction alone, so nesting a snapshot inside a snapshot
    is a no-op rather than a second, divergent read state.
    """

    existing = active_connection(key)
    if existing is not None:
        yield existing
        return

    with checkout() as connection:
        previous_isolation = connection.isolation_level
        # Drive the transaction explicitly: with the default isolation level
        # sqlite3 opens transactions implicitly for DML only, so plain SELECTs
        # would each read their own state and never hold a snapshot at all.
        connection.isolation_level = None
        connection.execute("begin deferred")
        try:
            # A deferred transaction does not acquire its read mark until it
            # first touches the database, so pin it here. Every leg then reads
            # the state as of snapshot entry rather than as of whichever leg
            # happened to run first.
            connection.execute("select count(*) from sqlite_master").fetchone()
            connection.set_authorizer(_deny_writes)
            try:
                token = _ACTIVE.set((*_ACTIVE.get(), (key, connection)))
                try:
                    yield connection
                finally:
                    _ACTIVE.reset(token)
            finally:
                connection.set_authorizer(None)
        finally:
            # Read-only by construction, so rollback is the correct release:
            # it ends the read transaction without publishing anything.
            connection.rollback()
            connection.isolation_level = previous_isolation
