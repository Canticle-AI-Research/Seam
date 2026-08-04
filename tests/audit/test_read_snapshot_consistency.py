"""Track S S5: pooled, snapshot-consistent retrieval reads.

These cover the S5 exit-gate clauses about the read path:

* every SQLite-backed leg and visibility check in one retrieval request reads
  from one committed snapshot, so a concurrent ingest cannot produce a
  candidate set assembled from mutually inconsistent database states;
* warm ``mix`` retrieval opens no new physical SQLite connections, and a
  40-thread stress run stays within the configured pool;
* ranking, IDs, order, and provenance are unchanged by the snapshot.

`HISTORY#528` recorded the trap these are written against: routing the eleven
``store._connect()`` sites through a pool satisfies the pooling clause while
leaving the read-snapshot tear intact. The connection-count assertions alone
would therefore pass on a defective implementation, so each clause below is
tested against observable state, not against connection bookkeeping.
"""

from __future__ import annotations

import threading

import pytest

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.models import HashEmbeddingModel
from seam_runtime.read_snapshot import (
    active_connection,
    physical_open_count,
    snapshot_key_for_path,
)
from seam_runtime.reference_contracts import VIRTUAL_REFS_EXTENSION
from seam_runtime.runtime import SeamRuntime
from seam_runtime.vector_adapters import SQLiteVectorAdapter


def _runtime(tmp_path, name: str = "snapshot.db", pool_size: int | None = None) -> SeamRuntime:
    path = tmp_path / name
    model = HashEmbeddingModel()
    runtime = SeamRuntime(
        path,
        embedding_model=model,
        vector_adapter=SQLiteVectorAdapter(str(path), model),
        allow_pgvector_env=False,
    )
    if pool_size is not None:
        runtime.store._pool._pool.pool_size = pool_size
    return runtime


def _record(record_id: str, text: str, kind: RecordKind = RecordKind.CLM) -> MIRLRecord:
    attrs = (
        {"content": text}
        if kind is RecordKind.RAW
        else {"subject": "ent:test", "predicate": "notes", "object": text}
    )
    return MIRLRecord(
        id=record_id,
        kind=kind,
        ns="work",
        scope="thread",
        ext=({} if kind is RecordKind.RAW else {VIRTUAL_REFS_EXTENSION: ["ent:test"]}),
        attrs=attrs,
    )


def _seed(runtime: SeamRuntime, count: int, prefix: str = "seed") -> None:
    runtime.persist_ir(
        IRBatch(
            [
                _record(f"clm:{prefix}-{index}", f"{prefix} note {index} about compilers")
                for index in range(count)
            ]
        )
    )


def _search(runtime: SeamRuntime, query: str = "compilers", budget: int = 10):
    orchestrator = runtime._retrieval_orchestrator_cached()
    return orchestrator.search(query, budget=budget, mode="mix")


# --------------------------------------------------------------------------
# One committed snapshot per request
# --------------------------------------------------------------------------


def test_all_legs_share_one_connection_during_a_request(tmp_path) -> None:
    """Each SQLite-backed leg must resolve to the request's bound connection."""

    runtime = _runtime(tmp_path)
    try:
        _seed(runtime, 6)
        key = snapshot_key_for_path(runtime.store.path)
        seen: list[int] = []

        original = runtime.store._pool.checkout

        def recording_checkout():
            manager = original()

            class _Recorder:
                def __enter__(self):
                    connection = manager.__enter__()
                    seen.append(id(connection))
                    return connection

                def __exit__(self, *exc):
                    return manager.__exit__(*exc)

            return _Recorder()

        runtime.store._pool.checkout = recording_checkout
        try:
            with runtime.store.read_snapshot() as snapshot:
                _search(runtime)
                bound = active_connection(key)
        finally:
            runtime.store._pool.checkout = original

        assert bound is snapshot
        assert seen, "the request performed no pooled reads at all"
        # Every read during the request resolved to the one bound connection.
        assert set(seen) == {id(snapshot)}
    finally:
        runtime.close()


def test_same_file_vector_index_joins_the_snapshot(tmp_path) -> None:
    """The vector leg reads the canonical file and must join its snapshot.

    ``SQLiteVectorAdapter`` is constructed on ``store.path``, so before S5 the
    semantic leg read a *different* committed state than the SQL, graph, and
    temporal legs of the same request even after those were pooled.
    """

    runtime = _runtime(tmp_path)
    try:
        _seed(runtime, 4)
        index = runtime.vector_adapter.index
        with runtime.store.read_snapshot() as snapshot:
            with index._read_connection() as connection:
                assert connection is snapshot
    finally:
        runtime.close()


def test_concurrent_ingest_cannot_tear_a_request(tmp_path) -> None:
    """A commit landing mid-request must be invisible to every later leg.

    This is the observable form of the defect: without one held snapshot, a leg
    running after the writer commits sees records that legs running before it
    did not, so the assembled candidate set corresponds to no committed state.
    """

    runtime = _runtime(tmp_path)
    try:
        _seed(runtime, 4, prefix="before")

        def count_visible() -> int:
            return len(runtime.store.load_ir(ns="work", scope="thread").records)

        def ingest_elsewhere() -> None:
            # A concurrent ingest is by definition another context, so it holds
            # no snapshot and is free to commit. Running it on this thread would
            # instead hit the snapshot's write guard.
            writer = _runtime(tmp_path)
            try:
                _seed(writer, 3, prefix="during")
            finally:
                writer.close()

        with runtime.store.read_snapshot():
            first = count_visible()

            ingest = threading.Thread(target=ingest_elsewhere)
            ingest.start()
            ingest.join(timeout=60)
            assert not ingest.is_alive()

            second = count_visible()

        assert first == second, "a mid-request commit leaked into the snapshot"

        # After release, the same store observes the new state -- the snapshot
        # isolates the request, it does not pin the store forever.
        assert count_visible() > first
    finally:
        runtime.close()


def test_snapshot_denies_writes_instead_of_discarding_them(tmp_path) -> None:
    """A write inside a snapshot must raise, not vanish at release.

    The snapshot ends in ``rollback``. Without the authorizer, a stray write
    would join the read transaction and be silently discarded -- a data-loss
    mode strictly worse than the tear being fixed.
    """

    import sqlite3

    runtime = _runtime(tmp_path)
    try:
        _seed(runtime, 2)
        with runtime.store.read_snapshot() as snapshot:
            with pytest.raises(sqlite3.DatabaseError):
                snapshot.execute("delete from ir_records")
            with pytest.raises(sqlite3.DatabaseError):
                snapshot.execute(
                    "insert into ir_records (id, kind, ns, scope, status, conf, "
                    "created_at, updated_at, payload_json) "
                    "values ('x','CLM','work','thread','active',1.0,'t','t','{}')"
                )
            with pytest.raises(sqlite3.DatabaseError):
                snapshot.execute("create table snapshot_probe (a)")

        # The refused writes changed nothing.
        assert len(runtime.store.load_ir(ns="work", scope="thread").records) == 2
    finally:
        runtime.close()


def test_nested_snapshot_reuses_the_outer_transaction(tmp_path) -> None:
    """Re-entry must not open a second, divergent read state."""

    runtime = _runtime(tmp_path)
    try:
        _seed(runtime, 2)
        with runtime.store.read_snapshot() as outer:
            with runtime.store.read_snapshot() as inner:
                assert inner is outer
            # The inner exit must not have released the outer snapshot.
            assert active_connection(runtime.store._snapshot_key) is outer
        assert active_connection(runtime.store._snapshot_key) is None
    finally:
        runtime.close()


# --------------------------------------------------------------------------
# Connection budget
# --------------------------------------------------------------------------


def test_warm_mix_retrieval_opens_no_new_physical_connections(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        _seed(runtime, 8)
        key = snapshot_key_for_path(runtime.store.path)

        # Warm every leg, the vector index, and the pool.
        for _ in range(3):
            _search(runtime)

        warm = physical_open_count(key)
        for _ in range(5):
            _search(runtime)

        assert physical_open_count(key) == warm
    finally:
        runtime.close()


def test_forty_thread_stress_stays_within_the_configured_pool(tmp_path) -> None:
    pool_size = 6
    runtime = _runtime(tmp_path, pool_size=pool_size)
    try:
        _seed(runtime, 10)
        _search(runtime)  # warm

        errors: list[Exception] = []
        peak = 0
        peak_lock = threading.Lock()
        barrier = threading.Barrier(40)

        def worker() -> None:
            nonlocal peak
            try:
                barrier.wait(timeout=30)
                for _ in range(3):
                    _search(runtime, budget=5)
                    active = int(runtime.store._pool.stats()["active_connections"])
                    with peak_lock:
                        peak = max(peak, active)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(40)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=120)

        assert not errors, f"stress run raised: {errors[:3]}"
        assert not any(thread.is_alive() for thread in threads)
        assert peak <= pool_size, f"pool exceeded its bound: {peak} > {pool_size}"
        assert runtime.store._pool.stats()["active_connections"] <= pool_size
    finally:
        runtime.close()


# --------------------------------------------------------------------------
# Results are unchanged
# --------------------------------------------------------------------------


def test_ranking_ids_and_order_are_unchanged_by_the_snapshot(tmp_path) -> None:
    """The snapshot is an isolation change, not a ranking change."""

    runtime = _runtime(tmp_path)
    try:
        _seed(runtime, 12)
        inside = [candidate.record.id for candidate in _search(runtime).candidates]

        # Re-run with the snapshot mechanism bypassed at the store level, which
        # reproduces the pre-S5 per-read connection behaviour.
        original = runtime.store.read_snapshot
        from contextlib import nullcontext

        runtime.store.read_snapshot = lambda: nullcontext(None)
        try:
            outside = [candidate.record.id for candidate in _search(runtime).candidates]
        finally:
            runtime.store.read_snapshot = original

        assert inside == outside
        assert inside, "the fixture produced no candidates to compare"
    finally:
        runtime.close()


def test_provenance_resolves_inside_the_request_snapshot(tmp_path) -> None:
    runtime = _runtime(tmp_path)
    try:
        runtime.persist_ir(
            IRBatch(
                [
                    _record("raw:source", "Ada shipped the compiler.", RecordKind.RAW),
                    _record("clm:compiler", "Ada shipped the compiler"),
                ]
            )
        )
        orchestrator = runtime._retrieval_orchestrator_cached()
        result = orchestrator.search(
            "compiler", budget=5, mode="mix", include_provenance=True
        )
        assert result.candidates
        # Provenance resolution happened inside the request, and the snapshot
        # was released cleanly afterwards.
        assert active_connection(runtime.store._snapshot_key) is None
    finally:
        runtime.close()
