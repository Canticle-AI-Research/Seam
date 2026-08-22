from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from seam_runtime import BatchIngestItem, SeamSDK
from seam_runtime.lifecycle import (
    apply_scoped_delete,
    init_lifecycle,
    plan_batch_ingest,
    plan_scoped_delete,
)
from seam_runtime.mirl import Status
from seam_runtime.runtime import SeamRuntime


class _TrackingVectorAdapter:
    name = "tracking-vector"

    def __init__(self) -> None:
        self.record_ids: set[str] = set()
        self.deleted: list[tuple[str, ...]] = []

    def index_records(self, records) -> None:
        self.record_ids.update(record.id for record in records)

    def delete_records(self, record_ids: list[str]) -> None:
        ids = tuple(sorted(record_ids))
        self.deleted.append(ids)
        self.record_ids.difference_update(ids)

    def search(self, query, limit=10, namespace=None, scope=None):
        return {}


def _claim_id(report) -> str:
    return next(
        record_id
        for record_id in report.stored_ids
        if record_id.startswith("clm:")
    )


@pytest.mark.parametrize(
    "generation",
    [
        "",
        "a" * 63,
        "a" * 65,
        "A" * 64,
        "g" * 64,
    ],
)
def test_scoped_delete_refuses_malformed_generation_precondition(
    generation: str,
) -> None:
    connection = sqlite3.connect(":memory:")
    try:
        with pytest.raises(
            ValueError,
            match="record generation must be 64 lowercase hexadecimal characters",
        ):
            plan_scoped_delete(
                connection,
                tenant_id="tenant-a",
                namespace="tenant-a",
                scope="thread",
                record_ids=["clm:generation-contract"],
                idempotency_key="generation-contract",
                actor="operator",
                record_generations={"clm:generation-contract": generation},
            )
    finally:
        connection.close()


def test_scoped_delete_is_audited_soft_and_tenant_isolated(
    tmp_path: Path,
) -> None:
    database = tmp_path / "lifecycle.db"
    with SeamSDK(database, allow_pgvector_env=False) as sdk:
        tenant_a = sdk.ingest(
            "Alice owns Orbit.",
            source_ref="local://tenant-a/1",
            ns="tenant-a",
            scope="thread",
        )
        tenant_b = sdk.ingest(
            "Mallory owns Secret.",
            source_ref="local://tenant-b/1",
            ns="tenant-b",
            scope="thread",
        )
        a_claim = _claim_id(tenant_a)
        b_claim = _claim_id(tenant_b)

        refused = sdk.plan_delete(
            tenant_id="tenant-a",
            namespace="tenant-a",
            scope="thread",
            record_ids=[a_claim, b_claim],
            idempotency_key="delete-cross-boundary",
            actor="operator",
        )
        refused = sdk.apply_delete(
            tenant_id="tenant-a",
            operation_id=str(refused["operation_id"]),
            actor="operator",
        )
        assert refused["state"] == "refused"
        assert refused["events"][-1]["detail"]["cross_boundary_record_ids"] == [
            b_claim
        ]
        assert sdk.runtime.store.load_ir(ids=[a_claim]).records[0].status != (
            Status.DELETED_SOFT
        )

        planned = sdk.plan_delete(
            tenant_id="tenant-a",
            namespace="tenant-a",
            scope="thread",
            record_ids=[a_claim],
            idempotency_key="delete-a-claim",
            actor="operator",
        )
        applied = sdk.apply_delete(
            tenant_id="tenant-a",
            operation_id=str(planned["operation_id"]),
            actor="operator",
        )
        repeated = sdk.apply_delete(
            tenant_id="tenant-a",
            operation_id=str(planned["operation_id"]),
            actor="operator",
        )

        assert applied == repeated
        assert applied["state"] == "applied"
        assert [event["state"] for event in applied["events"]] == [
            "planned",
            "applying",
            "cleanup_pending",
            "applied",
        ]
        stored = sdk.runtime.store.load_ir(ids=[a_claim]).records[0]
        assert stored.status == Status.DELETED_SOFT
        assert stored.ext["lifecycle_delete_operation"] == planned["operation_id"]
        assert all(
            candidate.record.id != a_claim
            for candidate in sdk.runtime.search_ir(
                "Alice owns Orbit",
                ns="tenant-a",
                scope="thread",
                budget=20,
            ).candidates
        )
        assert sdk.runtime.store.load_ir(ids=[b_claim]).records[0].status != (
            Status.DELETED_SOFT
        )

        with sdk.runtime.store._pool.checkout() as connection:
            vector_count = connection.execute(
                "select count(*) from vector_index where record_id = ?",
                (a_claim,),
            ).fetchone()[0]
            graph_count = connection.execute(
                "select count(*) from knowledge_edges where source_record_id = ?",
                (a_claim,),
            ).fetchone()[0]
            assert vector_count == 0
            assert graph_count == 0
            with connection:
                try:
                    connection.execute(
                        "update lifecycle_operation set kind = kind "
                        "where operation_id = ?",
                        (planned["operation_id"],),
                    )
                except sqlite3.IntegrityError as exc:
                    assert "append-only" in str(exc)
                else:  # pragma: no cover - a failed invariant is clearer here.
                    raise AssertionError("lifecycle ledger allowed mutation")


def test_batch_ingest_recovers_after_interruption_and_is_idempotent(
    tmp_path: Path,
) -> None:
    database = tmp_path / "batch.db"
    items = [
        BatchIngestItem("Alice owns Orbit.", "local://batch/1"),
        BatchIngestItem("Orbit contains Quartz.", "local://batch/2"),
    ]
    with SeamSDK(database, allow_pgvector_env=False) as sdk:
        interrupted = sdk.batch_ingest(
            tenant_id="tenant-a",
            namespace="tenant-a",
            scope="thread",
            items=items,
            idempotency_key="batch-1",
            actor="agent-a",
            interrupt_after_items=1,
        )
        assert interrupted["state"] == "item_applied"
        serialized = json.dumps(interrupted, sort_keys=True)
        assert "Alice owns Orbit." not in serialized
        assert "Orbit contains Quartz." not in serialized
        assert all(
            "text_sha256" in item and "text" not in item
            for item in interrupted["payload"]["items"]
        )
        assert sdk.recoverable_operations(tenant_id="tenant-a")[0][
            "operation_id"
        ] == interrupted["operation_id"]
        with sdk.runtime.store._pool.checkout() as connection:
            transient_count = connection.execute(
                "select count(*) from lifecycle_batch_payload "
                "where operation_id = ?",
                (interrupted["operation_id"],),
            ).fetchone()[0]
        assert transient_count == 2

    with SeamSDK(database, allow_pgvector_env=False) as reopened:
        completed = reopened.resume_operation(
            str(interrupted["operation_id"]),
            tenant_id="tenant-a",
            actor="recovery-agent",
        )
        repeated = reopened.batch_ingest(
            tenant_id="tenant-a",
            namespace="tenant-a",
            scope="thread",
            items=items,
            idempotency_key="batch-1",
            actor="agent-a",
        )
        raw_records = [
            record
            for record in reopened.runtime.store.load_ir(
                ns="tenant-a", scope="thread"
            ).records
            if record.id.startswith("raw:")
        ]
        with reopened.runtime.store._pool.checkout() as connection:
            transient_count = connection.execute(
                "select count(*) from lifecycle_batch_payload "
                "where operation_id = ?",
                (completed["operation_id"],),
            ).fetchone()[0]

    assert completed["state"] == "applied"
    assert repeated["operation_id"] == completed["operation_id"]
    assert repeated["state"] == "applied"
    assert {
        event["detail"]["item_index"]
        for event in completed["events"]
        if event["state"] == "item_applied"
    } == {0, 1}
    assert len(raw_records) == 2
    assert transient_count == 0


def test_concurrent_idempotent_planning_has_one_operation(
    tmp_path: Path,
) -> None:
    with SeamSDK(
        tmp_path / "concurrent.db", allow_pgvector_env=False
    ) as sdk:
        report = sdk.ingest(
            "Alice owns Orbit.",
            source_ref="local://concurrent/1",
            ns="tenant-a",
            scope="thread",
        )
        claim_id = _claim_id(report)

        def plan(_: int) -> str:
            operation = sdk.runtime.store.plan_scoped_delete(
                tenant_id="tenant-a",
                namespace="tenant-a",
                scope="thread",
                record_ids=[claim_id],
                idempotency_key="same-key",
                actor="worker",
            )
            return str(operation["operation_id"])

        with ThreadPoolExecutor(max_workers=4) as executor:
            operation_ids = list(executor.map(plan, range(12)))

        assert len(set(operation_ids)) == 1
        with sdk.runtime.store._pool.checkout() as connection:
            count = connection.execute(
                "select count(*) from lifecycle_operation "
                "where tenant_id = ? and idempotency_key = ?",
                ("tenant-a", "same-key"),
            ).fetchone()[0]
        assert count == 1


def test_lifecycle_reads_and_transitions_require_exact_tenant(
    tmp_path: Path,
) -> None:
    with SeamSDK(
        tmp_path / "tenant-authorization.db", allow_pgvector_env=False
    ) as sdk:
        report = sdk.ingest(
            "Alice owns Orbit.",
            source_ref="local://tenant-authorization/1",
            ns="tenant-a",
            scope="thread",
        )
        claim_id = _claim_id(report)
        deletion = sdk.plan_delete(
            tenant_id="tenant-a",
            namespace="tenant-a",
            scope="thread",
            record_ids=[claim_id],
            idempotency_key="delete-owned-claim",
            actor="tenant-a-operator",
        )
        deletion_id = str(deletion["operation_id"])

        for read in (
            lambda: sdk.lifecycle_operation(
                deletion_id, tenant_id="tenant-b"
            ),
            lambda: sdk.apply_delete(
                tenant_id="tenant-b",
                operation_id=deletion_id,
                actor="tenant-b-operator",
            ),
        ):
            try:
                read()
            except KeyError as exc:
                assert exc.args == (deletion_id,)
            else:  # pragma: no cover - explicit security invariant.
                raise AssertionError("cross-tenant lifecycle access succeeded")

        assert sdk.recoverable_operations(tenant_id="tenant-b") == []
        assert sdk.lifecycle_operation(
            deletion_id, tenant_id="tenant-a"
        )["state"] == "planned"
        assert sdk.runtime.store.load_ir(ids=[claim_id]).records[0].status != (
            Status.DELETED_SOFT
        )

        interrupted = sdk.batch_ingest(
            tenant_id="tenant-a",
            namespace="tenant-a",
            scope="thread",
            items=[
                BatchIngestItem(
                    "Orbit contains Quartz.",
                    "local://tenant-authorization/batch",
                ),
                BatchIngestItem(
                    "Quartz has color blue.",
                    "local://tenant-authorization/batch-2",
                ),
            ],
            idempotency_key="tenant-a-batch",
            actor="tenant-a-agent",
            interrupt_after_items=1,
        )
        interrupted_id = str(interrupted["operation_id"])
        try:
            sdk.resume_operation(
                interrupted_id,
                tenant_id="tenant-b",
                actor="tenant-b-agent",
            )
        except KeyError as exc:
            assert exc.args == (interrupted_id,)
        else:  # pragma: no cover - explicit security invariant.
            raise AssertionError("cross-tenant lifecycle resume succeeded")
        try:
            sdk.runtime.store.lifecycle_batch_items(
                tenant_id="tenant-b", operation_id=interrupted_id
            )
        except KeyError as exc:
            assert exc.args == (interrupted_id,)
        else:  # pragma: no cover - explicit security invariant.
            raise AssertionError("cross-tenant batch payload read succeeded")
        assert sdk.lifecycle_operation(
            interrupted_id, tenant_id="tenant-a"
        )["state"] == "item_applied"


def test_lifecycle_initialization_preserves_caller_transaction() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    try:
        connection.execute(
            "create table caller_marker (marker_id text primary key)"
        )
        init_lifecycle(connection)
        connection.commit()

        connection.execute(
            "insert into caller_marker (marker_id) values ('uncommitted')"
        )
        operation = plan_batch_ingest(
            connection,
            tenant_id="tenant-a",
            namespace="tenant-a",
            scope="thread",
            items=(
                BatchIngestItem(
                    "Alice owns Orbit.", "local://transaction/1"
                ),
            ),
            idempotency_key="caller-transaction",
            actor="agent-a",
        )
        assert connection.in_transaction
        connection.rollback()

        assert connection.execute(
            "select count(*) from caller_marker"
        ).fetchone()[0] == 0
        assert connection.execute(
            "select count(*) from lifecycle_operation where operation_id = ?",
            (operation["operation_id"],),
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_identical_payloads_with_distinct_keys_create_distinct_operations(
    tmp_path: Path,
) -> None:
    items = [
        BatchIngestItem("Alice owns Orbit.", "local://distinct-keys/1")
    ]
    with SeamSDK(
        tmp_path / "distinct-keys.db", allow_pgvector_env=False
    ) as sdk:
        first = sdk.runtime.store.plan_batch_ingest(
            tenant_id="tenant-a",
            namespace="tenant-a",
            scope="thread",
            items=items,
            idempotency_key="distinct-key-1",
            actor="agent-a",
        )
        second = sdk.runtime.store.plan_batch_ingest(
            tenant_id="tenant-a",
            namespace="tenant-a",
            scope="thread",
            items=items,
            idempotency_key="distinct-key-2",
            actor="agent-a",
        )
        repeated = sdk.runtime.store.plan_batch_ingest(
            tenant_id="tenant-a",
            namespace="tenant-a",
            scope="thread",
            items=items,
            idempotency_key="distinct-key-1",
            actor="agent-a",
        )

    assert first["operation_id"] != second["operation_id"]
    assert repeated["operation_id"] == first["operation_id"]


def test_scoped_delete_clears_configured_external_vector_adapter(
    tmp_path: Path,
) -> None:
    vectors = _TrackingVectorAdapter()
    runtime = SeamRuntime(
        tmp_path / "external-vector.db",
        vector_adapter=vectors,
        allow_pgvector_env=False,
    )
    with SeamSDK(runtime=runtime) as sdk:
        report = sdk.ingest(
            "Alice owns Orbit.",
            source_ref="local://external-vector/1",
            ns="tenant-a",
            scope="thread",
        )
        claim_id = _claim_id(report)
        assert claim_id in vectors.record_ids
        deletion = sdk.plan_delete(
            tenant_id="tenant-a",
            namespace="tenant-a",
            scope="thread",
            record_ids=[claim_id],
            idempotency_key="delete-external-vector",
            actor="operator",
        )
        applied = sdk.apply_delete(
            tenant_id="tenant-a",
            operation_id=str(deletion["operation_id"]),
            actor="operator",
        )

    runtime.close()
    assert applied["state"] == "applied"
    assert vectors.deleted == [(claim_id,)]
    assert claim_id not in vectors.record_ids


def test_scoped_delete_clears_registered_chroma_projection(
    tmp_path: Path,
) -> None:
    from seam_runtime.retrieval_orchestrator import RetrievalOrchestrator
    from seam_runtime.retrieval_orchestrator.adapters import (
        ChromaSemanticAdapter,
    )

    class _Collection:
        def __init__(self) -> None:
            self.deleted: list[tuple[str, ...]] = []

        def delete(self, *, ids: list[str]) -> None:
            self.deleted.append(tuple(sorted(ids)))

    class _Client:
        def __init__(self, collection: _Collection) -> None:
            self.collection = collection

        def get_or_create_collection(self, **_options):
            return self.collection

    collection = _Collection()
    with SeamRuntime(
        tmp_path / "chroma-delete.db", allow_pgvector_env=False
    ) as runtime:
        chroma = ChromaSemanticAdapter(
            runtime.store,
            runtime.embedding_model,
            client=_Client(collection),
        )
        RetrievalOrchestrator(runtime, semantic_adapter=chroma)
        RetrievalOrchestrator(runtime, semantic_adapter=chroma)
        with SeamSDK(runtime=runtime) as sdk:
            report = sdk.ingest(
                "Alice owns Orbit.",
                source_ref="local://chroma-delete/1",
                ns="tenant-a",
                scope="thread",
            )
            claim_id = _claim_id(report)
            deletion = sdk.plan_delete(
                tenant_id="tenant-a",
                namespace="tenant-a",
                scope="thread",
                record_ids=[claim_id],
                idempotency_key="delete-chroma-vector",
                actor="operator",
            )
            sdk.apply_delete(
                tenant_id="tenant-a",
                operation_id=str(deletion["operation_id"]),
                actor="operator",
            )

    assert collection.deleted == [(claim_id,)]


def test_external_vector_delete_failure_leaves_recoverable_outbox(
    tmp_path: Path,
) -> None:
    class _FailingVectorAdapter(_TrackingVectorAdapter):
        fail = True

        def delete_records(self, record_ids: list[str]) -> None:
            if self.fail:
                raise RuntimeError("external vector delete failed")
            super().delete_records(record_ids)

    vectors = _FailingVectorAdapter()
    runtime = SeamRuntime(
        tmp_path / "external-vector-failure.db",
        vector_adapter=vectors,
        allow_pgvector_env=False,
    )
    with SeamSDK(runtime=runtime) as sdk:
        report = sdk.ingest(
            "Alice owns Orbit.",
            source_ref="local://external-vector/failure",
            ns="tenant-a",
            scope="thread",
        )
        claim_id = _claim_id(report)
        deletion = sdk.plan_delete(
            tenant_id="tenant-a",
            namespace="tenant-a",
            scope="thread",
            record_ids=[claim_id],
            idempotency_key="delete-external-vector-failure",
            actor="operator",
        )
        try:
            sdk.apply_delete(
                tenant_id="tenant-a",
                operation_id=str(deletion["operation_id"]),
                actor="operator",
            )
        except RuntimeError as exc:
            assert str(exc) == "external vector delete failed"
        else:  # pragma: no cover - explicit fail-closed invariant.
            raise AssertionError("external vector deletion failure was ignored")
        record = sdk.runtime.store.load_ir(ids=[claim_id]).records[0]
        operation = sdk.lifecycle_operation(
            str(deletion["operation_id"]), tenant_id="tenant-a"
        )
        assert sdk.recoverable_operations(tenant_id="tenant-a")[0][
            "operation_id"
        ] == deletion["operation_id"]
        vectors.fail = False
        recovered = sdk.resume_operation(
            str(deletion["operation_id"]),
            tenant_id="tenant-a",
            actor="recovery-agent",
        )

    runtime.close()
    assert record.status == Status.DELETED_SOFT
    assert operation["state"] == "cleanup_pending"
    assert recovered["state"] == "applied"
    assert vectors.deleted == [(claim_id,)]


def test_external_cleanup_refuses_caller_owned_transaction(
    tmp_path: Path,
) -> None:
    vectors = _TrackingVectorAdapter()
    runtime = SeamRuntime(
        tmp_path / "external-caller-transaction.db",
        vector_adapter=vectors,
        allow_pgvector_env=False,
    )
    with SeamSDK(runtime=runtime) as sdk:
        report = sdk.ingest(
            "Alice owns Orbit.",
            source_ref="local://external-vector/caller-transaction",
            ns="tenant-a",
            scope="thread",
        )
        claim_id = _claim_id(report)
        deletion = sdk.plan_delete(
            tenant_id="tenant-a",
            namespace="tenant-a",
            scope="thread",
            record_ids=[claim_id],
            idempotency_key="delete-caller-transaction",
            actor="operator",
        )
        with sdk.runtime.store._pool.checkout() as connection:
            connection.execute("begin immediate")
            try:
                apply_scoped_delete(
                    connection,
                    tenant_id="tenant-a",
                    operation_id=str(deletion["operation_id"]),
                    actor="operator",
                    delete_derived_records=runtime._delete_derived_records,
                )
            except RuntimeError as exc:
                assert str(exc) == (
                    "external lifecycle cleanup requires an owned transaction"
                )
            else:  # pragma: no cover - explicit cross-store invariant.
                raise AssertionError("external cleanup ran in caller transaction")
            connection.rollback()
        record = sdk.runtime.store.load_ir(ids=[claim_id]).records[0]
        operation = sdk.lifecycle_operation(
            str(deletion["operation_id"]), tenant_id="tenant-a"
        )

    runtime.close()
    assert vectors.deleted == []
    assert record.status != Status.DELETED_SOFT
    assert operation["state"] == "planned"
