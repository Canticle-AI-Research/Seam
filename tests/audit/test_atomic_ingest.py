"""D2: one committed ingest outcome through the public runtime seam."""

from __future__ import annotations

import json
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest

from seam_runtime.knowledge_graph import restore_canonical_graph_state
from seam_runtime.models import HashEmbeddingModel
from seam_runtime.runtime import SeamRuntime
from seam_runtime.vector_adapters import SQLiteVectorAdapter


def _runtime(path: Path) -> SeamRuntime:
    model = HashEmbeddingModel()
    return SeamRuntime(
        path,
        embedding_model=model,
        vector_adapter=SQLiteVectorAdapter(str(path), model),
        allow_pgvector_env=False,
    )


def _active_document_ids(runtime: SeamRuntime, source_ref: str) -> set[str]:
    return {
        str(document["document_id"])
        for document in runtime.store.list_document_status(limit=200)
        if document["source_ref"] == source_ref and document["deleted_at"] is None
    }


def _assert_sqlite_integrity(runtime: SeamRuntime) -> None:
    with runtime.store._pool.checkout() as connection:
        assert connection.execute("pragma integrity_check").fetchone()[0] == "ok"
        assert connection.execute("pragma foreign_key_check").fetchall() == []


def _spawn_same_source_ingest(
    path: str,
    source_ref: str,
    text: str,
    start,
    outcomes,
) -> None:
    runtime = _runtime(Path(path))
    try:
        start.wait()
        outcome = runtime.ingest_text(text, source_ref=source_ref)
        outcomes.put(str(outcome.document["document_id"]))
    finally:
        runtime.close()


def test_failure_after_canonical_writes_preserves_exact_previous_ingest(
    tmp_path: Path,
) -> None:
    path = tmp_path / "atomic-ingest.db"
    source_ref = "test://atomic/reingest"
    runtime = _runtime(path)
    try:
        previous = runtime.ingest_text(
            "amberquartz previous durable content",
            source_ref=source_ref,
        )
        previous_ids = set(previous.stored_ids)

        def fail_after_canonical(transition: str) -> None:
            if transition == "after_canonical_records":
                raise RuntimeError("injected ingest failure")

        runtime._ingest_failure_injector = fail_after_canonical
        with pytest.raises(RuntimeError, match="injected ingest failure"):
            runtime.ingest_text(
                "cobaltzircon replacement content",
                source_ref=source_ref,
            )

        assert _active_document_ids(runtime, source_ref) == {
            str(previous.document["document_id"])
        }
        assert {
            record.id
            for record in runtime.store.load_ir().records
            if record.status.value != "superseded"
        } == previous_ids
        assert runtime.memory_search("amberquartz")["results"]
        assert "cobaltzircon" not in json.dumps(
            runtime.memory_search("cobaltzircon")["results"], sort_keys=True
        ).lower()
        _assert_sqlite_integrity(runtime)
    finally:
        runtime.close()


@pytest.mark.parametrize(
    "transition",
    [
        "after_canonical_records",
        "after_supersession",
        "after_document_status",
        "after_vector_intents",
    ],
)
def test_every_precommit_transition_rolls_back_to_previous_outcome(
    tmp_path: Path, transition: str
) -> None:
    path = tmp_path / f"precommit-{transition}.db"
    source_ref = "test://atomic/precommit"
    runtime = _runtime(path)
    try:
        previous = runtime.ingest_text(
            "amberquartz remains canonical", source_ref=source_ref
        )
        previous_records = sorted(
            (record.to_dict() for record in runtime.store.load_ir().records),
            key=lambda record: str(record["id"]),
        )
        previous_documents = runtime.store.list_document_status(limit=200)

        def fail_at(candidate: str) -> None:
            if candidate == transition:
                raise RuntimeError(f"failed at {transition}")

        runtime._ingest_failure_injector = fail_at
        with pytest.raises(RuntimeError, match=f"failed at {transition}"):
            runtime.ingest_text(
                "cobaltzircon must not survive", source_ref=source_ref
            )

        assert _active_document_ids(runtime, source_ref) == {
            str(previous.document["document_id"])
        }
        assert sorted(
            (record.to_dict() for record in runtime.store.load_ir().records),
            key=lambda record: str(record["id"]),
        ) == previous_records
        assert runtime.store.list_document_status(limit=200) == previous_documents
        assert "cobaltzircon" not in json.dumps(
            runtime.memory_search("cobaltzircon")["results"], sort_keys=True
        ).lower()
        assert runtime.store.pending_vector_outbox_count() == 0
        _assert_sqlite_integrity(runtime)
    finally:
        runtime.close()


def test_projection_failure_keeps_complete_new_outcome_and_pending_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "projection-pending.db"
    source_ref = "test://atomic/projection"
    runtime = _runtime(path)
    try:
        previous = runtime.ingest_text(
            "amberquartz obsolete unique content", source_ref=source_ref
        )

        def unavailable(_records) -> None:
            raise RuntimeError("projection unavailable")

        monkeypatch.setattr(runtime.vector_adapter, "index_records", unavailable)
        outcome = runtime.ingest_text(
            "cobaltzircon current unique content", source_ref=source_ref
        )

        assert outcome.projection_pending is True
        assert outcome.vector_intent_record_ids
        assert outcome.superseded_document_ids == [
            previous.document["document_id"]
        ]
        assert _active_document_ids(runtime, source_ref) == {
            str(outcome.document["document_id"])
        }
        assert runtime.store.pending_vector_outbox_count() == len(
            outcome.vector_intent_record_ids
        )
        assert "amberquartz" not in json.dumps(
            runtime.memory_search("amberquartz")["results"], sort_keys=True
        ).lower()
        _assert_sqlite_integrity(runtime)
    finally:
        runtime.close()


def test_failure_after_commit_exposes_complete_new_canonical_outcome(
    tmp_path: Path,
) -> None:
    path = tmp_path / "postcommit.db"
    source_ref = "test://atomic/postcommit"
    runtime = _runtime(path)
    try:
        previous = runtime.ingest_text(
            "amberquartz previous generation", source_ref=source_ref
        )

        def fail_after_commit(transition: str) -> None:
            if transition == "after_commit":
                raise RuntimeError("process stopped after commit")

        runtime._ingest_failure_injector = fail_after_commit
        with pytest.raises(RuntimeError, match="process stopped after commit"):
            runtime.ingest_text(
                "cobaltzircon committed generation", source_ref=source_ref
            )

        active = _active_document_ids(runtime, source_ref)
        assert len(active) == 1
        assert previous.document["document_id"] not in active
        assert runtime.store.pending_vector_outbox_count() > 0
        assert "amberquartz" not in json.dumps(
            runtime.memory_search("amberquartz")["results"], sort_keys=True
        ).lower()
        assert "cobaltzircon" in json.dumps(
            runtime.memory_search("cobaltzircon")["results"], sort_keys=True
        ).lower()
        _assert_sqlite_integrity(runtime)
    finally:
        runtime.close()


def test_node_vector_failure_stays_pending_and_reopen_repairs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "node-vector-pending.db"
    runtime = _runtime(path)
    try:
        monkeypatch.setattr(
            runtime,
            "project_node_vectors",
            lambda: {"embedded": 0, "failed": 0, "error": True},
        )
        outcome = runtime.ingest_text(
            "amberquartz node vector durability",
            source_ref="test://atomic/node-vector",
        )
        document_id = str(outcome.document["document_id"])

        assert outcome.projection_pending is True
        assert runtime.store.pending_vector_outbox_count() > 0
        assert runtime.store.read_document_status(document_id)["indexed_status"] == "pending"
        _assert_sqlite_integrity(runtime)
    finally:
        runtime.close()

    reopened = _runtime(path)
    try:
        assert reopened.store.pending_vector_outbox_count() == 0
        assert reopened.store.read_document_status(document_id)["indexed_status"] == "indexed"
        status = reopened.store.node_vector_status(reopened.embedding_model.name)
        assert status["pending_nodes"] == 0
    finally:
        reopened.close()


@pytest.mark.parametrize("failure_kind", ["after_vector_projection", "ack"])
def test_postprojection_or_ack_failure_leaves_durable_pending_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    runtime = _runtime(tmp_path / f"{failure_kind}.db")
    try:
        if failure_kind == "after_vector_projection":
            runtime._ingest_failure_injector = lambda transition: (
                (_ for _ in ()).throw(RuntimeError("injected postprojection failure"))
                if transition == "after_vector_projection"
                else None
            )
        else:
            monkeypatch.setattr(
                runtime.store,
                "complete_ingest_projection",
                lambda _document_id, _entry_ids: (_ for _ in ()).throw(
                    RuntimeError("injected acknowledgement failure")
                ),
            )

        outcome = runtime.ingest_text(
            f"amberquartz {failure_kind} durability",
            source_ref=f"test://atomic/{failure_kind}",
        )

        assert outcome.projection_pending is True
        assert runtime.store.pending_vector_outbox_count() > 0
        assert runtime.store.read_document_status(
            str(outcome.document["document_id"])
        )["indexed_status"] == "pending"
        _assert_sqlite_integrity(runtime)
    finally:
        runtime.close()


def test_conversation_turn_failure_after_canonical_writes_is_atomic(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path / "conversation-atomic.db")
    source_ref = "test://atomic/conversation"
    try:
        previous = runtime.ingest_conversation_turn(
            "amberquartz prior conversation", source_ref=source_ref
        )
        previous_records = sorted(previous.stored_ids)

        def fail_after_canonical(transition: str) -> None:
            if transition == "after_canonical_records":
                raise RuntimeError("conversation ingest interrupted")

        runtime._ingest_failure_injector = fail_after_canonical
        with pytest.raises(RuntimeError, match="conversation ingest interrupted"):
            runtime.ingest_conversation_turn(
                "cobaltzircon replacement conversation", source_ref=source_ref
            )

        assert sorted(
            record.id
            for record in runtime.store.load_ir().records
            if record.status.value != "superseded"
        ) == previous_records
        assert _active_document_ids(runtime, source_ref) == {
            str(previous.document["document_id"])
        }
        _assert_sqlite_integrity(runtime)
    finally:
        runtime.close()


def test_same_content_replay_is_idempotent(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "same-content.db")
    source_ref = "test://atomic/idempotent"
    try:
        first = runtime.ingest_text("stable replay content", source_ref=source_ref)
        second = runtime.ingest_text("stable replay content", source_ref=source_ref)

        assert second.document["document_id"] == first.document["document_id"]
        assert second.stored_ids == first.stored_ids
        assert second.superseded_document_ids == []
        assert second.projection_pending is False
        assert _active_document_ids(runtime, source_ref) == {
            str(first.document["document_id"])
        }
        assert runtime.store.pending_vector_outbox_count() == 0
    finally:
        runtime.close()


def test_concurrent_same_source_ingests_leave_one_explicit_winner(
    tmp_path: Path,
) -> None:
    path = tmp_path / "concurrent-source.db"
    source_ref = "test://atomic/concurrent"
    runtime_a = _runtime(path)
    runtime_b = _runtime(path)
    start = Barrier(2, timeout=10)

    def ingest(runtime: SeamRuntime, text: str):
        start.wait()
        return runtime.ingest_text(text, source_ref=source_ref)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            future_a = executor.submit(
                ingest, runtime_a, "amberquartz concurrent generation"
            )
            future_b = executor.submit(
                ingest, runtime_b, "cobaltzircon concurrent generation"
            )
            outcomes = [future_a.result(timeout=20), future_b.result(timeout=20)]

        active = _active_document_ids(runtime_a, source_ref)
        assert len(active) == 1
        winner_id = next(iter(active))
        loser = next(
            outcome
            for outcome in outcomes
            if outcome.document["document_id"] != winner_id
        )
        assert runtime_a.store.read_document_status(
            str(loser.document["document_id"])
        )["deleted_at"] is not None
        winner_word = "amberquartz" if winner_id == outcomes[0].document["document_id"] else "cobaltzircon"
        loser_word = "cobaltzircon" if winner_word == "amberquartz" else "amberquartz"
        assert winner_word in json.dumps(
            runtime_a.memory_search(winner_word)["results"], sort_keys=True
        ).lower()
        assert loser_word not in json.dumps(
            runtime_a.memory_search(loser_word)["results"], sort_keys=True
        ).lower()
    finally:
        runtime_a.close()
        runtime_b.close()


def test_spawned_process_same_source_ingests_leave_one_active_document(
    tmp_path: Path,
) -> None:
    path = tmp_path / "spawned-source.db"
    source_ref = "test://atomic/spawned-concurrent"
    initialized = _runtime(path)
    initialized.close()
    context = multiprocessing.get_context("spawn")
    start = context.Barrier(2, timeout=20)
    outcomes = context.Queue()
    processes = [
        context.Process(
            target=_spawn_same_source_ingest,
            args=(str(path), source_ref, text, start, outcomes),
        )
        for text in (
            "amberquartz spawned generation",
            "cobaltzircon spawned generation",
        )
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=30)
        assert process.exitcode == 0
    document_ids = {outcomes.get(timeout=5) for _ in processes}

    runtime = _runtime(path)
    try:
        active = _active_document_ids(runtime, source_ref)
        assert len(active) == 1
        assert active <= document_ids
        loser_id = next(document_id for document_id in document_ids if document_id not in active)
        assert runtime.store.read_document_status(loser_id)["deleted_at"] is not None
        _assert_sqlite_integrity(runtime)
    finally:
        runtime.close()


def test_reingest_preserves_coreferent_entity_referenced_by_winner(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path / "coreferent.db")
    source_ref = "test://atomic/coreferent"
    try:
        first = runtime.ingest_text(
            "Melanie keeps the amberquartz notebook.", source_ref=source_ref
        )
        second = runtime.ingest_text(
            "Melanie keeps the cobaltzircon notebook.", source_ref=source_ref
        )
        winner = runtime.store.load_ir(ids=second.stored_ids)
        winner_claim = next(
            record for record in winner.records if record.kind.value == "CLM"
        )
        entity_id = str(winner_claim.attrs["subject"])
        entity = runtime.store.load_ir(ids=[entity_id]).records[0]
        graph = runtime.knowledge_graph(query="cobaltzircon")
        old_only_ids = set(first.stored_ids) - {entity_id}

        assert entity.status.value != "superseded"
        assert entity_id in first.stored_ids
        assert entity_id in second.stored_ids
        assert old_only_ids.isdisjoint(
            str(edge["source_record_id"]) for edge in graph["edges"]
        )
    finally:
        runtime.close()


def test_same_source_ref_isolated_across_namespace_and_scope(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "boundary-source.db")
    source_ref = "test://atomic/shared-source"
    try:
        tenant_a = runtime.ingest_text(
            "amberquartz shared boundary content",
            source_ref=source_ref,
            ns="tenant.a",
            scope="thread",
        )
        tenant_b = runtime.ingest_text(
            "amberquartz shared boundary content",
            source_ref=source_ref,
            ns="tenant.b",
            scope="thread",
        )

        assert tenant_a.document["document_id"] != tenant_b.document["document_id"]
        assert runtime.store.read_document_status(
            str(tenant_a.document["document_id"])
        )["deleted_at"] is None
        assert runtime.store.read_document_status(
            str(tenant_b.document["document_id"])
        )["deleted_at"] is None
        assert runtime.search_ir(
            "amberquartz", ns="tenant.a", scope="thread"
        ).candidates
        assert runtime.search_ir(
            "amberquartz", ns="tenant.b", scope="thread"
        ).candidates
    finally:
        runtime.close()


def test_graph_restore_preserves_shared_entity_referenced_by_winner(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path / "restore-shared-entity.db")
    source_ref = "test://atomic/restore-shared-entity"
    try:
        first = runtime.ingest_text(
            "Melanie keeps the amberquartz notebook.", source_ref=source_ref
        )
        second = runtime.ingest_text(
            "Melanie keeps the cobaltzircon notebook.", source_ref=source_ref
        )
        winner = runtime.store.load_ir(ids=second.stored_ids)
        winner_claim = next(
            record for record in winner.records if record.kind.value == "CLM"
        )
        shared_entity_id = str(winner_claim.attrs["subject"])
        assert shared_entity_id in first.stored_ids

        with runtime.store._pool.checkout() as connection:
            before = connection.execute(
                "select status from knowledge_nodes where id = ?",
                (shared_entity_id,),
            ).fetchone()[0]
            assert before == "asserted"
            restore_canonical_graph_state(connection)
            after = connection.execute(
                "select status from knowledge_nodes where id = ?",
                (shared_entity_id,),
            ).fetchone()[0]
            connection.commit()

        assert after == "asserted"
        assert runtime.store.load_ir(ids=[shared_entity_id]).records[0].status.value == "asserted"
        assert runtime.store.knowledge_graph(
            query="amberquartz", include_history=False
        )["nodes"] == []
        assert runtime.store.knowledge_graph(
            query="amberquartz", include_history=True
        )["nodes"]
        _assert_sqlite_integrity(runtime)
    finally:
        runtime.close()


def test_same_namespace_source_isolated_across_scopes(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path / "scope-source.db")
    source_ref = "test://atomic/shared-scope-source"
    try:
        thread = runtime.ingest_text(
            "amberquartz shared scoped content",
            source_ref=source_ref,
            ns="tenant.a",
            scope="thread",
        )
        project = runtime.ingest_text(
            "amberquartz shared scoped content",
            source_ref=source_ref,
            ns="tenant.a",
            scope="project",
        )

        assert thread.document["document_id"] != project.document["document_id"]
        assert runtime.store.read_document_status(
            str(thread.document["document_id"])
        )["deleted_at"] is None
        assert runtime.store.read_document_status(
            str(project.document["document_id"])
        )["deleted_at"] is None
        assert runtime.search_ir(
            "amberquartz", ns="tenant.a", scope="thread"
        ).candidates
        assert runtime.search_ir(
            "amberquartz", ns="tenant.a", scope="project"
        ).candidates
        _assert_sqlite_integrity(runtime)
    finally:
        runtime.close()
