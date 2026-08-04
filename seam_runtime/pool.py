"""SQLite connection pool (connection reuse pattern).

Note: SQLite doesn't support true connection pooling like PostgreSQL.
This is a connection reuse pattern that maintains N reusable connections
in a queue. For high-concurrency workloads, migrate to PostgreSQL.
"""
from __future__ import annotations

import logging
import queue
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Callable

from .read_snapshot import active_connection

LOGGER = logging.getLogger(__name__)


class ConnectionPool:
    def __init__(
        self,
        connect_factory: Callable[[], sqlite3.Connection],
        pool_size: int = 5,
        idle_timeout: int = 300,
        checkout_timeout: int = 5,
    ) -> None:
        self._connect_factory = connect_factory
        self.pool_size = pool_size
        self.idle_timeout = idle_timeout
        self.checkout_timeout = checkout_timeout
        self._lock = threading.Lock()
        self._pool: queue.Queue[tuple[sqlite3.Connection, float]] = queue.Queue(maxsize=pool_size)
        self._active_count = 0
        self._closed = False

    def _validate_connection(self, connection: sqlite3.Connection) -> bool:
        try:
            connection.execute("select 1")
            return True
        except Exception:
            LOGGER.warning("Connection validation failed, will recreate")
            return False

    def _close_connection(self, connection: sqlite3.Connection) -> None:
        try:
            connection.close()
        except Exception:
            LOGGER.warning("Error closing connection", exc_info=True)

    def _drop(self, connection: sqlite3.Connection) -> None:
        """Close a connection and account for it leaving the pool."""
        self._close_connection(connection)
        with self._lock:
            self._active_count -= 1

    def _acquire(self) -> sqlite3.Connection:
        # Validation (a SQL round-trip) is done OUTSIDE the lock so one slow or
        # hung connection check cannot serialize every other checkout.
        deadline = time.time() + self.checkout_timeout
        while True:
            candidate: sqlite3.Connection | None = None
            created = False
            with self._lock:
                while not self._pool.empty():
                    try:
                        conn, last_used = self._pool.get_nowait()
                    except queue.Empty:
                        break
                    if time.time() - last_used > self.idle_timeout:
                        LOGGER.debug("Closing idle connection")
                        self._close_connection(conn)
                        self._active_count -= 1
                        continue
                    candidate = conn
                    break
                if candidate is None and self._active_count < self.pool_size:
                    candidate = self._connect_factory()
                    self._active_count += 1
                    created = True

            if candidate is not None:
                # Freshly created connections are valid by construction; pooled
                # ones are validated off-lock and discarded+retried if stale.
                if created or self._validate_connection(candidate):
                    return candidate
                self._drop(candidate)
                continue

            # Pool exhausted: block for a returned connection, then validate it
            # too (the fast path is not the only way to get a dead connection).
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError(
                    f"Could not acquire connection within {self.checkout_timeout}s "
                    f"(pool_size={self.pool_size}, active={self._active_count})"
                )
            try:
                conn, _ = self._pool.get(timeout=remaining)
            except queue.Empty:
                raise TimeoutError(
                    f"Could not acquire connection within {self.checkout_timeout}s "
                    f"(pool_size={self.pool_size}, active={self._active_count})"
                )
            if self._validate_connection(conn):
                return conn
            self._drop(conn)
            # loop: a slot is now free, so the next pass can create a fresh one

    def _release(self, connection: sqlite3.Connection) -> None:
        if self._closed:
            self._drop(connection)
            return
        # Reset on return: discard any uncommitted transaction before the
        # connection re-enters the pool. SQLite uses implicit transactions
        # (isolation_level=""), so a write that raised after the first statement
        # but before commit() would leave an open transaction; without this
        # rollback the next caller to reuse this connection would commit those
        # orphaned rows. Done OUTSIDE the lock (it is a SQL round-trip).
        try:
            connection.rollback()
        except sqlite3.Error:
            LOGGER.warning("Connection unusable on return, discarding", exc_info=True)
            self._drop(connection)
            return
        with self._lock:
            if self._closed:
                self._active_count -= 1
                should_close = True
            else:
                try:
                    self._pool.put_nowait((connection, time.time()))
                    should_close = False
                except queue.Full:
                    LOGGER.warning("Pool is full, closing excess connection")
                    self._active_count -= 1
                    should_close = True
        if should_close:
            self._close_connection(connection)

    @contextmanager
    def checkout(self):
        if self._closed:
            raise RuntimeError("ConnectionPool is closed")
        connection = self._acquire()
        try:
            yield connection
        finally:
            self._release(connection)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            while not self._pool.empty():
                try:
                    conn, _ = self._pool.get_nowait()
                    self._close_connection(conn)
                    self._active_count -= 1
                except queue.Empty:
                    break

    def stats(self) -> dict[str, object]:
        with self._lock:
            return {
                "pool_size": self.pool_size,
                "active_connections": self._active_count,
                "idle_connections": self._pool.qsize(),
                "closed": self._closed,
            }


class SnapshotAwarePool:
    """A pool that yields the context's read snapshot when one is held.

    Wrapping the pool rather than editing every call site is deliberate: a
    single retrieval request reaches the store through dozens of read helpers,
    and a snapshot that only some of them joined would still answer from
    mutually inconsistent states -- exactly the defect S5 exists to close.
    Routing the checkout itself makes joining the snapshot the default and
    opting out impossible by omission.

    Outside a snapshot every checkout behaves exactly as before.
    """

    def __init__(self, pool: ConnectionPool, snapshot_key: str) -> None:
        self._pool = pool
        self._snapshot_key = snapshot_key

    @property
    def snapshot_key(self) -> str:
        return self._snapshot_key

    @property
    def pool_size(self) -> int:
        return self._pool.pool_size

    @contextmanager
    def checkout(self):
        connection = active_connection(self._snapshot_key)
        if connection is not None:
            # Already inside this database's snapshot: reuse it and do not
            # release it here, because the snapshot owns its lifetime.
            yield connection
            return
        with self._pool.checkout() as connection:
            yield connection

    def checkout_physical(self):
        """Check out from the underlying pool, ignoring any bound snapshot.

        The snapshot itself needs this to acquire the connection it will bind.
        """

        return self._pool.checkout()

    def close(self) -> None:
        self._pool.close()

    def stats(self) -> dict[str, object]:
        return self._pool.stats()
