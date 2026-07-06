"""Pool hardening tests (audit F3/F4): off-lock validation, blocking-path
validation, exhaustion, idle eviction, and thread-safety of the rewritten
_acquire/_release split.
"""
from __future__ import annotations

import sqlite3
import threading
import time

import pytest

from seam_runtime.pool import ConnectionPool


def _bootstrap(db_path: str) -> None:
    c = sqlite3.connect(db_path)
    # Establish WAL mode on the file so concurrent writers serialize on a write
    # lock with a busy wait instead of failing; mirrors SQLiteStore's production
    # connection config. Without this, Windows rollback-journal locking makes
    # concurrent writes flaky ("database is locked").
    c.execute("pragma journal_mode=WAL")
    c.execute("create table t (id integer primary key autoincrement, v text not null)")
    c.commit()
    c.close()


def _wal_connect(db_path: str) -> sqlite3.Connection:
    """Connection factory mirroring SQLiteStore: WAL + a real busy timeout."""
    conn = sqlite3.connect(db_path, timeout=5)
    conn.execute("pragma journal_mode=WAL")
    conn.execute("pragma busy_timeout=5000")
    return conn


def test_concurrent_writes_all_commit(tmp_path):
    db = str(tmp_path / "c.db")
    _bootstrap(db)
    pool = ConnectionPool(lambda: _wal_connect(db), pool_size=3)

    n_threads, per_thread = 8, 25
    errors: list[Exception] = []

    def worker(tid: int):
        try:
            for i in range(per_thread):
                with pool.checkout() as conn:
                    conn.execute("insert into t (v) values (?)", (f"{tid}-{i}",))
                    conn.commit()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, f"concurrent writers raised: {errors}"
    verify = sqlite3.connect(db)
    count = verify.execute("select count(*) from t").fetchone()[0]
    verify.close()
    assert count == n_threads * per_thread
    # all checked-out connections returned; active count never exceeds pool_size
    stats = pool.stats()
    assert stats["active_connections"] <= 3
    pool.close()


def test_exhaustion_raises_timeout(tmp_path):
    db = str(tmp_path / "e.db")
    _bootstrap(db)
    pool = ConnectionPool(lambda: sqlite3.connect(db), pool_size=1, checkout_timeout=1)
    with pool.checkout():
        # pool is now empty and at capacity; a second concurrent acquire must time out
        with pytest.raises(TimeoutError):
            with pool.checkout():
                pass
    pool.close()


def test_stale_pooled_connection_is_replaced(tmp_path):
    """A dead connection sitting in the pool is validated off-lock, discarded,
    and a fresh one returned — checkout never hands back a broken connection."""
    db = str(tmp_path / "s.db")
    _bootstrap(db)
    pool = ConnectionPool(lambda: sqlite3.connect(db), pool_size=2)

    # Put a connection into the pool, then kill it underneath the pool.
    with pool.checkout() as conn:
        conn.execute("select 1")
    # the returned connection is now idle in the pool; corrupt it
    dead, _ = pool._pool.get_nowait()
    dead.close()  # validation (select 1) will now raise
    pool._pool.put_nowait((dead, time.time()))

    # Next checkout must detect the dead connection and return a working one.
    with pool.checkout() as conn:
        assert conn.execute("select 1").fetchone() == (1,)
        conn.execute("insert into t (v) values ('ok')")
        conn.commit()
    pool.close()


def test_write_methods_are_retry_wrapped():
    """Audit F2: the dead retry_db_operation is now wired into the write paths."""
    from seam_runtime.storage import SQLiteStore

    for name in (
        "persist_ir",
        "delete_ir",
        "upsert_document_status",
        "write_retrieval_event",
        "write_improvement_proposal",
        "record_proposal_decision",
    ):
        method = getattr(SQLiteStore, name)
        assert hasattr(method, "__wrapped__"), f"{name} is not retry-wrapped"


def test_transient_lock_retries_then_succeeds(tmp_path):
    """End-to-end: a 'database is locked' error is retried rather than raised."""
    from unittest.mock import patch

    from seam_runtime import retry as retry_mod

    calls = {"n": 0}
    real_sleep = time.sleep

    @retry_mod.retry_db_operation(max_attempts=3, base_delay=0.001)
    def flaky_write():
        calls["n"] += 1
        if calls["n"] < 2:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    with patch.object(retry_mod.time, "sleep", lambda s: real_sleep(0)):
        assert flaky_write() == "ok"
    assert calls["n"] == 2  # retried once, then succeeded


def test_non_transient_error_not_retried():
    from seam_runtime import retry as retry_mod

    calls = {"n": 0}

    @retry_mod.retry_db_operation(max_attempts=5, base_delay=0.001)
    def bad_write():
        calls["n"] += 1
        raise sqlite3.IntegrityError("UNIQUE constraint failed")

    with pytest.raises(sqlite3.IntegrityError):
        bad_write()
    assert calls["n"] == 1  # IntegrityError propagates immediately, no retry


def test_idle_connection_evicted(tmp_path):
    db = str(tmp_path / "i.db")
    _bootstrap(db)
    pool = ConnectionPool(lambda: sqlite3.connect(db), pool_size=2, idle_timeout=0)
    with pool.checkout() as conn:
        conn.execute("select 1")
    # idle_timeout=0 means the pooled connection is always considered stale
    with pool.checkout() as conn:
        assert conn.execute("select 1").fetchone() == (1,)
    pool.close()
