from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from seam_runtime.lifecycle import (
    BatchIngestItem,
    begin_batch_ingest,
    complete_batch_ingest,
    init_lifecycle,
    plan_batch_ingest,
    plan_scoped_delete,
    record_batch_item,
    recoverable_operations,
)
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind, Status
from seam_runtime.retrieval import search_batch
from seam_runtime.retrieval_orchestrator import RetrievalOrchestrator
from seam_runtime.retrieval_orchestrator.types import LegHit
from seam_runtime.runtime import SeamRuntime


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_lifecycle(connection)
    return connection


def _plan_batch(
    connection: sqlite3.Connection,
    *,
    tenant: str,
    suffix: str,
) -> dict[str, object]:
    return plan_batch_ingest(
        connection,
        tenant_id=tenant,
        namespace=tenant,
        scope="thread",
        items=(
            BatchIngestItem(
                text=f"batch item {suffix}",
                source_ref=f"local://batch/{suffix}",
            ),
        ),
        idempotency_key=f"batch-{suffix}",
        actor="test",
        created_at=f"2026-07-29T00:00:0{len(suffix)}Z",
    )


def test_terminal_batch_refuses_late_item_after_applied() -> None:
    connection = _connection()
    try:
        operation = _plan_batch(connection, tenant="tenant-a", suffix="one")
        operation_id = str(operation["operation_id"])
        begin_batch_ingest(
            connection,
            tenant_id="tenant-a",
            operation_id=operation_id,
            actor="worker",
        )
        record_batch_item(
            connection,
            tenant_id="tenant-a",
            operation_id=operation_id,
            item_index=0,
            stored_ids=("clm:one",),
            actor="worker",
        )
        applied = complete_batch_ingest(
            connection,
            tenant_id="tenant-a",
            operation_id=operation_id,
            actor="worker",
        )

        with pytest.raises(
            ValueError, match="cannot record batch item in state applied"
        ):
            record_batch_item(
                connection,
                tenant_id="tenant-a",
                operation_id=operation_id,
                item_index=0,
                stored_ids=("clm:late",),
                actor="late-worker",
            )

        states = [event["state"] for event in applied["events"]]
        assert states == ["planned", "applying", "item_applied", "applied"]
        assert recoverable_operations(connection, tenant_id="tenant-a") == []
    finally:
        connection.close()


def test_terminal_failed_batch_cannot_be_overwritten_as_applied() -> None:
    connection = _connection()
    try:
        operation = _plan_batch(
            connection, tenant="tenant-a", suffix="failed"
        )
        operation_id = str(operation["operation_id"])
        connection.execute(
            "insert into lifecycle_event "
            "(event_id, operation_id, state, actor, detail_json, created_at, "
            "schema_version) values (?, ?, ?, ?, ?, ?, ?)",
            (
                "life-event:synthetic-failed",
                operation_id,
                "failed",
                "test",
                "{}",
                "2026-07-29T00:00:00Z",
                1,
            ),
        )
        connection.commit()

        with pytest.raises(
            ValueError, match="cannot complete batch ingest in state failed"
        ):
            complete_batch_ingest(
                connection,
                tenant_id="tenant-a",
                operation_id=operation_id,
                actor="worker",
            )

        latest = connection.execute(
            "select state from lifecycle_event where operation_id = ? "
            "order by event_seq desc limit 1",
            (operation_id,),
        ).fetchone()[0]
        assert latest == "failed"
    finally:
        connection.close()


def test_lifecycle_planning_rejects_unowned_namespace_prefixes() -> None:
    connection = _connection()
    try:
        with pytest.raises(ValueError, match="does not own namespace"):
            plan_scoped_delete(
                connection,
                tenant_id="tenant-a",
                namespace="tenant-ab",
                scope="thread",
                record_ids=("clm:foreign",),
                idempotency_key="delete-foreign",
                actor="operator",
            )
        with pytest.raises(ValueError, match="does not own namespace"):
            plan_batch_ingest(
                connection,
                tenant_id="tenant-a",
                namespace="tenant-b",
                scope="thread",
                items=(BatchIngestItem("foreign", "local://foreign"),),
                idempotency_key="batch-foreign",
                actor="operator",
            )

        exact = _plan_batch(connection, tenant="tenant-a", suffix="exact")
        dotted = plan_batch_ingest(
            connection,
            tenant_id="tenant-a",
            namespace="tenant-a.project",
            scope="thread",
            items=(BatchIngestItem("dotted", "local://dotted"),),
            idempotency_key="batch-dotted",
            actor="operator",
        )
        colon = plan_batch_ingest(
            connection,
            tenant_id="tenant-a",
            namespace="tenant-a:project",
            scope="thread",
            items=(BatchIngestItem("colon", "local://colon"),),
            idempotency_key="batch-colon",
            actor="operator",
        )
        assert {
            exact["namespace"],
            dotted["namespace"],
            colon["namespace"],
        } == {"tenant-a", "tenant-a.project", "tenant-a:project"}
    finally:
        connection.close()


def test_recoverable_limit_filters_terminal_then_orders_newest() -> None:
    connection = _connection()
    try:
        oldest = _plan_batch(connection, tenant="tenant-a", suffix="old")
        terminal = _plan_batch(
            connection, tenant="tenant-a", suffix="terminal"
        )
        terminal_id = str(terminal["operation_id"])
        begin_batch_ingest(
            connection,
            tenant_id="tenant-a",
            operation_id=terminal_id,
            actor="worker",
        )
        record_batch_item(
            connection,
            tenant_id="tenant-a",
            operation_id=terminal_id,
            item_index=0,
            stored_ids=("clm:terminal",),
            actor="worker",
        )
        complete_batch_ingest(
            connection,
            tenant_id="tenant-a",
            operation_id=terminal_id,
            actor="worker",
        )
        newest_a = _plan_batch(
            connection, tenant="tenant-a", suffix="new-a"
        )
        newest_b = _plan_batch(
            connection, tenant="tenant-b", suffix="new-b"
        )

        tenant_limited = recoverable_operations(
            connection, tenant_id="tenant-a", limit=1
        )
        tenant_b_limited = recoverable_operations(
            connection, tenant_id="tenant-b", limit=2
        )

        assert [item["operation_id"] for item in tenant_limited] == [
            newest_a["operation_id"]
        ]
        assert [item["operation_id"] for item in tenant_b_limited] == [
            newest_b["operation_id"]
        ]
        assert oldest["operation_id"] not in {
            item["operation_id"] for item in tenant_limited
        }
        assert terminal_id not in {
            item["operation_id"] for item in recoverable_operations(
                connection, tenant_id="tenant-a", limit=100
            )
        }
    finally:
        connection.close()


class _CapturingLeg:
    def __init__(self, leg: str, records: list[MIRLRecord]) -> None:
        self.leg = leg
        self.records = records
        self.limits: list[int] = []

    def search(self, plan, limit: int) -> list[LegHit]:
        self.limits.append(limit)
        return [
            LegHit(
                leg=self.leg,
                record=record,
                score=1.0,
                reasons=[f"{self.leg}=1.00"],
            )
            for record in self.records[:limit]
        ]


def test_current_retrieval_overfetches_before_status_filtering(
    tmp_path: Path,
) -> None:
    excluded = [
        MIRLRecord(
            id=f"clm:excluded-{index}",
            kind=RecordKind.CLM,
            ns="work",
            scope="thread",
            status=status,
            attrs={"subject": "old", "predicate": "mentions", "object": "needle"},
        )
        for index, status in enumerate(
            (
                Status.SUPERSEDED,
                Status.CONTRADICTED,
                Status.DEPRECATED,
                Status.DELETED_SOFT,
            )
            * 5
        )
    ]
    current = MIRLRecord(
        id="clm:current",
        kind=RecordKind.CLM,
        ns="work",
        scope="thread",
        status=Status.ASSERTED,
        attrs={"subject": "current", "predicate": "mentions", "object": "needle"},
    )
    sql = _CapturingLeg("sql", [*excluded, current])
    vector = _CapturingLeg("vector", [])
    with SeamRuntime(
        tmp_path / "retrieval.db", allow_pgvector_env=False
    ) as runtime:
        orchestrator = RetrievalOrchestrator(
            runtime, sql_adapter=sql, semantic_adapter=vector
        )
        result = orchestrator.search(
            "needle",
            namespace="work",
            scope="thread",
            budget=1,
            mode="hybrid",
            include_trace=True,
        )

    assert sql.limits == [5, 10, 20, 40]
    assert vector.limits == [5]
    assert [candidate.record.id for candidate in result.candidates] == [
        "clm:current"
    ]
    assert [
        item["record"]["id"] for item in result.trace["legs"]["sql"]
    ] == ["clm:current"]


def test_search_batch_excludes_noncurrent_records_before_ranking() -> None:
    stale = MIRLRecord(
        id="clm:stale",
        kind=RecordKind.CLM,
        status=Status.SUPERSEDED,
        attrs={"subject": "old", "predicate": "mentions", "object": "needle"},
    )
    current = MIRLRecord(
        id="clm:current",
        kind=RecordKind.CLM,
        status=Status.ASSERTED,
        attrs={"subject": "new", "predicate": "mentions", "object": "needle"},
    )

    result = search_batch(IRBatch([stale, current]), query="needle", limit=5)

    assert [candidate.record.id for candidate in result.candidates] == [
        "clm:current"
    ]
