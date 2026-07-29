from __future__ import annotations

from pathlib import Path

from seam_runtime import SeamSDK
from seam_runtime.mirl import utc_now


def test_sdk_context_assembles_current_canonical_and_g4_products(
    tmp_path: Path,
) -> None:
    database = tmp_path / "g5.db"
    with SeamSDK(database, allow_pgvector_env=False) as sdk:
        sdk.ingest(
            "Alice owns Orbit.",
            source_ref="local://tenant-a/episode-1",
            ns="tenant-a",
            scope="thread",
        )
        sdk.ingest(
            "Alice owns Orbit.",
            source_ref="local://tenant-a/episode-2",
            ns="tenant-a",
            scope="thread",
        )
        sdk.ingest(
            "Mallory owns Secret.",
            source_ref="local://tenant-b/episode-1",
            ns="tenant-b",
            scope="thread",
        )
        sdk.rebuild_graph_products(namespace="tenant-a", scope="thread")
        as_of = utc_now()
        first = sdk.context(
            task="Who owns Orbit?",
            namespace="tenant-a",
            scope="thread",
            as_of=as_of,
            token_budget=8_000,
            fact_reserve_tokens=1_000,
        )

    with SeamSDK(database, allow_pgvector_env=False) as reopened:
        second = reopened.context(
            task="Who owns Orbit?",
            namespace="tenant-a",
            scope="thread",
            as_of=as_of,
            token_budget=8_000,
            fact_reserve_tokens=1_000,
        )

    assert first.rendered == second.rendered
    assert first.backtraces == second.backtraces
    assert first.token_cost <= first.token_budget
    assert {"fact", "entity", "episode", "entity_summary", "observation"} <= {
        item.kind for item in first.items
    }
    assert all(item.record_ids and item.episode_ids for item in first.items)
    assert "Mallory" not in first.rendered
    assert "Secret" not in first.rendered


def test_context_revalidates_graph_product_support_after_delete(
    tmp_path: Path,
) -> None:
    with SeamSDK(
        tmp_path / "g5-delete.db", allow_pgvector_env=False
    ) as sdk:
        report = sdk.ingest(
            "Alice owns Orbit.",
            source_ref="local://tenant-a/delete-support",
            ns="tenant-a",
            scope="thread",
        )
        claim_id = next(
            record_id
            for record_id in report.stored_ids
            if record_id.startswith("clm:")
        )
        sdk.rebuild_graph_products(namespace="tenant-a", scope="thread")
        before = sdk.runtime.store.context_candidates(
            namespace="tenant-a", scope="thread"
        )
        stale_candidate_ids = {
            candidate.candidate_id
            for candidate in before
            if claim_id in candidate.record_ids
        }
        assert stale_candidate_ids

        deletion = sdk.plan_delete(
            tenant_id="tenant-a",
            namespace="tenant-a",
            scope="thread",
            record_ids=[claim_id],
            idempotency_key="delete-product-support",
            actor="operator",
        )
        sdk.apply_delete(
            tenant_id="tenant-a",
            operation_id=str(deletion["operation_id"]),
            actor="operator",
        )
        after = sdk.runtime.store.context_candidates(
            namespace="tenant-a", scope="thread"
        )

    assert not stale_candidate_ids & {
        candidate.candidate_id for candidate in after
    }
    assert all(claim_id not in candidate.record_ids for candidate in after)
