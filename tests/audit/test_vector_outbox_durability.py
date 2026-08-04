"""Track S S5: the vector outbox makes derived indexing process-durable.

Audit finding F7. The canonical commit precedes derived vector indexing, and
before this the compensation for a failed index lived only in the writing
process: a crash between the two left canonical records that no vector backend
knew about, with nothing in the database recording that the work was owed.

The S5 exit gate names two clauses covered here:

* crashes before and after canonical commit, vector indexing, and outbox
  acknowledgement converge to the same state after reopen; and
* duplicate replay is harmless.

Process loss is simulated by driving the write path's stages directly rather
than by killing an interpreter: what a crash actually does is stop the sequence
between two durable points, and stopping it there is both faithful and
deterministic. Each case then reopens the store and asserts convergence.
"""

from __future__ import annotations

import pytest

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.models import HashEmbeddingModel
from seam_runtime.reference_contracts import VIRTUAL_REFS_EXTENSION
from seam_runtime.runtime import SeamRuntime
from seam_runtime.vector_adapters import SQLiteVectorAdapter
from seam_runtime.vector_outbox import (
    acknowledge,
    enqueue_index_intents,
    init_vector_outbox,
    pending_count,
    pending_entries,
)


class _CountingAdapter:
    """A vector adapter that records what it was asked to index."""

    name = "counting"
    index_records_atomic = True

    def __init__(self) -> None:
        self.indexed: list[list[str]] = []
        self.fail = False

    def index_records(self, records) -> None:
        if self.fail:
            raise RuntimeError("vector backend unavailable")
        self.indexed.append([record.id for record in records])

    def delete_records(self, record_ids) -> None:
        return None

    def search(self, query, limit=10, namespace=None, scope=None):
        return {}


def _record(record_id: str, text: str = "a compiler note") -> MIRLRecord:
    return MIRLRecord(
        id=record_id,
        kind=RecordKind.CLM,
        ns="work",
        scope="thread",
        ext={VIRTUAL_REFS_EXTENSION: ["ent:test"]},
        attrs={"subject": "ent:test", "predicate": "notes", "object": text},
    )


def _runtime(path, adapter=None) -> SeamRuntime:
    model = HashEmbeddingModel()
    return SeamRuntime(
        path,
        embedding_model=model,
        vector_adapter=adapter if adapter is not None else SQLiteVectorAdapter(str(path), model),
        allow_pgvector_env=False,
    )


# --------------------------------------------------------------------------
# Table-level behaviour
# --------------------------------------------------------------------------


def test_enqueue_and_acknowledge_round_trip(tmp_path) -> None:
    import sqlite3

    connection = sqlite3.connect(str(tmp_path / "outbox.db"))
    try:
        init_vector_outbox(connection)
        assert pending_count(connection) == 0

        entry_ids = enqueue_index_intents(connection, ["clm:a", "clm:b"])
        assert len(entry_ids) == 2
        assert pending_count(connection) == 2

        entries = pending_entries(connection)
        assert [entry["record_id"] for entry in entries] == ["clm:a", "clm:b"]
        assert all(entry["operation"] == "index" for entry in entries)

        assert acknowledge(connection, entry_ids) == 2
        assert pending_count(connection) == 0
        # Acknowledging twice is not an error.
        assert acknowledge(connection, entry_ids) == 0
    finally:
        connection.close()


def test_outbox_helpers_tolerate_a_missing_table(tmp_path) -> None:
    import sqlite3

    connection = sqlite3.connect(str(tmp_path / "empty.db"))
    try:
        assert pending_entries(connection) == []
        assert pending_count(connection) == 0
        assert acknowledge(connection, [1, 2]) == 0
    finally:
        connection.close()


# --------------------------------------------------------------------------
# The steady state owes nothing
# --------------------------------------------------------------------------


def test_a_successful_write_leaves_nothing_pending(tmp_path) -> None:
    path = tmp_path / "clean.db"
    runtime = _runtime(path)
    try:
        runtime.persist_ir(IRBatch([_record("clm:one")]))
        assert runtime.store.pending_vector_outbox_count() == 0
    finally:
        runtime.close()


def test_intent_and_record_commit_together(tmp_path) -> None:
    """The intent must be written by the canonical transaction itself."""

    path = tmp_path / "atomic.db"
    runtime = _runtime(path)
    try:
        report = runtime.store.persist_ir(
            IRBatch([_record("clm:one")]),
            _enqueue_vector_outbox=True,
        )
        # persist_ir committed; the intent is durable and unacknowledged
        # because nothing has indexed anything yet.
        assert report.outbox_entry_ids
        assert runtime.store.pending_vector_outbox_count() == len(report.stored_ids)
    finally:
        runtime.close()


# --------------------------------------------------------------------------
# Crash convergence
# --------------------------------------------------------------------------


def test_crash_after_canonical_commit_before_indexing_converges(tmp_path) -> None:
    """The canonical record survives with no vector row; reopen must index it."""

    path = tmp_path / "crash-before-index.db"
    adapter = _CountingAdapter()
    runtime = _runtime(path, adapter)
    try:
        # Exactly what persist_ir does up to the canonical commit, then stop:
        # the process is gone before index_records runs.
        runtime.store.persist_ir(
            IRBatch([_record("clm:one")]),
            _preserve_node_vectors=True,
            _enqueue_vector_outbox=True,
        )
        assert runtime.store.pending_vector_outbox_count() == 1
        assert adapter.indexed == [], "the fixture indexed before the crash point"
    finally:
        runtime.close()

    reopened_adapter = _CountingAdapter()
    reopened = _runtime(path, reopened_adapter)
    try:
        # Reopen replayed the intent.
        assert reopened_adapter.indexed, "reopen did not index the owed record"
        assert "clm:one" in reopened_adapter.indexed[0]
        assert reopened.store.pending_vector_outbox_count() == 0
    finally:
        reopened.close()


def test_crash_after_indexing_before_acknowledgement_converges(tmp_path) -> None:
    """Indexing completed but the ack was lost; replay must be a safe no-op."""

    path = tmp_path / "crash-before-ack.db"
    adapter = _CountingAdapter()
    runtime = _runtime(path, adapter)
    try:
        report = runtime.store.persist_ir(
            IRBatch([_record("clm:one")]),
            _preserve_node_vectors=True,
            _enqueue_vector_outbox=True,
        )
        persisted = runtime.store.load_ir(ids=report.stored_ids)
        adapter.index_records(persisted.records)
        # The process dies here, before acknowledge_vector_outbox.
        assert runtime.store.pending_vector_outbox_count() == 1
    finally:
        runtime.close()

    reopened_adapter = _CountingAdapter()
    reopened = _runtime(path, reopened_adapter)
    try:
        assert reopened_adapter.indexed, "reopen did not replay the unacked intent"
        assert reopened.store.pending_vector_outbox_count() == 0
        # Converged to the same state as the crash-before-indexing case.
        assert "clm:one" in reopened_adapter.indexed[0]
    finally:
        reopened.close()


def test_crash_before_canonical_commit_owes_nothing(tmp_path) -> None:
    path = tmp_path / "crash-before-commit.db"
    runtime = _runtime(path)
    try:
        # Nothing was ever written, so nothing is pending and reopen is inert.
        assert runtime.store.pending_vector_outbox_count() == 0
    finally:
        runtime.close()

    reopened = _runtime(path)
    try:
        assert reopened.store.pending_vector_outbox_count() == 0
        assert reopened.store.load_ir(ns="work", scope="thread").records == []
    finally:
        reopened.close()


def test_all_crash_points_converge_to_the_same_state(tmp_path) -> None:
    """The gate's actual wording: every crash point converges identically."""

    def final_vector_ids(path, stage: str) -> set[str]:
        adapter = _CountingAdapter()
        runtime = _runtime(path, adapter)
        try:
            report = runtime.store.persist_ir(
                IRBatch([_record("clm:one"), _record("clm:two")]),
                _preserve_node_vectors=True,
                _enqueue_vector_outbox=True,
            )
            if stage in {"after_index", "after_ack"}:
                persisted = runtime.store.load_ir(ids=report.stored_ids)
                adapter.index_records(persisted.records)
            if stage == "after_ack":
                runtime.store.acknowledge_vector_outbox(report.outbox_entry_ids)
        finally:
            runtime.close()

        replay_adapter = _CountingAdapter()
        # Seed the replay adapter with whatever the crashed process managed to
        # index, so the comparison is over final state, not over replay work.
        replay_adapter.indexed = list(adapter.indexed)
        reopened = _runtime(path, replay_adapter)
        try:
            assert reopened.store.pending_vector_outbox_count() == 0
            return {
                record_id
                for batch in replay_adapter.indexed
                for record_id in batch
            }
        finally:
            reopened.close()

    outcomes = {
        stage: final_vector_ids(tmp_path / f"{stage}.db", stage)
        for stage in ("after_commit", "after_index", "after_ack")
    }

    assert outcomes["after_commit"] == {"clm:one", "clm:two"}
    assert len(set(map(frozenset, outcomes.values()))) == 1, outcomes


# --------------------------------------------------------------------------
# Duplicate replay
# --------------------------------------------------------------------------


def test_duplicate_replay_is_harmless(tmp_path) -> None:
    path = tmp_path / "duplicate.db"
    adapter = _CountingAdapter()
    runtime = _runtime(path, adapter)
    try:
        runtime.store.persist_ir(
            IRBatch([_record("clm:one")]),
            _preserve_node_vectors=True,
            _enqueue_vector_outbox=True,
        )
        first = runtime.replay_vector_outbox()
        assert first["acknowledged"] == 1
        assert first["reindexed"] == 1

        # Every subsequent replay finds nothing owed and changes nothing.
        for _ in range(3):
            repeat = runtime.replay_vector_outbox()
            assert repeat == {
                "pending": 0,
                "reindexed": 0,
                "acknowledged": 0,
                "failed": 0,
            }
        assert len(adapter.indexed) == 1
    finally:
        runtime.close()


def test_replay_of_the_same_intent_twice_produces_one_vector_row(tmp_path) -> None:
    """Idempotence measured on the real SQLite backend, not a double."""

    path = tmp_path / "idempotent.db"
    runtime = _runtime(path)
    try:
        runtime.persist_ir(IRBatch([_record("clm:one")]))

        def vector_rows() -> int:
            with runtime.store._pool.checkout() as connection:
                return int(
                    connection.execute(
                        "select count(*) from vector_index where record_id = ?",
                        ("clm:one",),
                    ).fetchone()[0]
                )

        before = vector_rows()
        assert before == 1

        # Re-enqueue the same intent and replay it repeatedly.
        with runtime.store._pool.checkout() as connection:
            enqueue_index_intents(connection, ["clm:one"])
            connection.commit()
        runtime.replay_vector_outbox()
        with runtime.store._pool.checkout() as connection:
            enqueue_index_intents(connection, ["clm:one"])
            connection.commit()
        runtime.replay_vector_outbox()

        assert vector_rows() == before
        assert runtime.store.pending_vector_outbox_count() == 0
    finally:
        runtime.close()


def test_replay_settles_intents_whose_record_is_gone(tmp_path) -> None:
    """A rolled-back or deleted record leaves no work to do, and no stuck row."""

    path = tmp_path / "orphan-intent.db"
    adapter = _CountingAdapter()
    runtime = _runtime(path, adapter)
    try:
        with runtime.store._pool.checkout() as connection:
            enqueue_index_intents(connection, ["clm:never-persisted"])
            connection.commit()
        assert runtime.store.pending_vector_outbox_count() == 1

        summary = runtime.replay_vector_outbox()
        assert summary["acknowledged"] == 1
        assert summary["reindexed"] == 0
        assert adapter.indexed == []
        assert runtime.store.pending_vector_outbox_count() == 0
    finally:
        runtime.close()


# --------------------------------------------------------------------------
# Failure handling
# --------------------------------------------------------------------------


def test_replay_keeps_intents_pending_when_the_backend_is_down(tmp_path) -> None:
    path = tmp_path / "backend-down.db"
    adapter = _CountingAdapter()
    runtime = _runtime(path, adapter)
    try:
        runtime.store.persist_ir(
            IRBatch([_record("clm:one")]),
            _preserve_node_vectors=True,
            _enqueue_vector_outbox=True,
        )
        adapter.fail = True
        summary = runtime.replay_vector_outbox()

        assert summary["failed"] == 1
        assert summary["acknowledged"] == 0
        assert runtime.store.pending_vector_outbox_count() == 1

        entry = runtime.store.pending_vector_outbox()[0]
        assert entry["attempts"] == 1
        # An exception class name, never a message: outbox rows are
        # operator-visible and a message can carry record content.
        assert entry["last_error"] == "RuntimeError"

        # Once the backend recovers, the owed work completes.
        adapter.fail = False
        recovered = runtime.replay_vector_outbox()
        assert recovered["acknowledged"] == 1
        assert runtime.store.pending_vector_outbox_count() == 0
    finally:
        runtime.close()


def test_reopen_never_fails_because_a_backend_is_unreachable(tmp_path) -> None:
    """A pending intent plus a dead backend must not make reopen impossible."""

    path = tmp_path / "reopen-safe.db"
    runtime = _runtime(path, _CountingAdapter())
    try:
        runtime.store.persist_ir(
            IRBatch([_record("clm:one")]),
            _preserve_node_vectors=True,
            _enqueue_vector_outbox=True,
        )
    finally:
        runtime.close()

    broken = _CountingAdapter()
    broken.fail = True
    reopened = _runtime(path, broken)  # must not raise
    try:
        assert reopened.store.pending_vector_outbox_count() == 1
    finally:
        reopened.close()


def test_failed_persist_that_restores_cleanly_leaves_no_pending_intent(tmp_path) -> None:
    """A restored write is an exact no-op, including in the outbox.

    S4 qualified that a failed vector index restores the canonical database to
    its prior state. Intents left behind by such a write would accumulate
    forever and make replay re-index records nothing is waiting on.
    """

    path = tmp_path / "restored.db"
    adapter = _CountingAdapter()
    runtime = _runtime(path, adapter)
    try:
        runtime.persist_ir(IRBatch([_record("clm:one")]))
        assert runtime.store.pending_vector_outbox_count() == 0

        adapter.fail = True
        with pytest.raises(RuntimeError, match="restored"):
            runtime.persist_ir(IRBatch([_record("clm:two")]))

        assert runtime.store.pending_vector_outbox_count() == 0
    finally:
        runtime.close()
