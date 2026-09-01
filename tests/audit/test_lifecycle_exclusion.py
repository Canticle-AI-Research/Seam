from __future__ import annotations

from pathlib import Path

import pytest

from seam_runtime.knowledge_graph import node_vector_source_hash, render_node_text
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind, Status
from seam_runtime.runtime import SeamRuntime


class _FailingDeleteVectorAdapter:
    name = "d3-failing-delete"

    def __init__(self) -> None:
        self.fail_delete = True

    def index_records(self, records) -> None:
        del records

    def delete_records(self, record_ids: list[str]) -> None:
        del record_ids
        if self.fail_delete:
            raise RuntimeError("injected vector cleanup failure")

    def search(self, query, limit=10, namespace=None, scope=None):
        del query, limit, namespace, scope
        return {}


def _claim_id(stored_ids: list[str]) -> str:
    return next(record_id for record_id in stored_ids if record_id.startswith("clm:"))


def _raw_id(stored_ids: list[str]) -> str:
    return next(record_id for record_id in stored_ids if record_id.startswith("raw:"))


def _soft_delete(
    runtime: SeamRuntime,
    *,
    record_ids: list[str],
    idempotency_key: str,
) -> dict[str, object]:
    planned = runtime.plan_scoped_delete(
        tenant_id="tenant-a",
        namespace="tenant-a",
        scope="thread",
        record_ids=record_ids,
        idempotency_key=idempotency_key,
        actor="operator",
    )
    return runtime.apply_scoped_delete(
        tenant_id="tenant-a",
        operation_id=str(planned["operation_id"]),
        actor="operator",
    )


def test_trace_rejects_deleted_root_and_does_not_cross_deleted_neighbor(
    tmp_path: Path,
) -> None:
    with SeamRuntime(
        tmp_path / "trace-exclusion.db", allow_pgvector_env=False
    ) as runtime:
        outcome = runtime.ingest_text(
            "Ada uses SQLite.",
            source_ref="local://lifecycle-exclusion/trace",
            ns="tenant-a",
            scope="thread",
        )
        claim_id = _claim_id(outcome.stored_ids)
        raw_id = _raw_id(outcome.stored_ids)

        assert raw_id in {node.id for node in runtime.trace(claim_id).nodes}

        applied = _soft_delete(
            runtime,
            record_ids=[raw_id],
            idempotency_key="delete-trace-raw",
        )

        assert applied["state"] == "applied"
        assert runtime.store.load_ir(ids=[raw_id]).records[0].status is Status.DELETED_SOFT
        with pytest.raises(KeyError):
            runtime.trace(raw_id)
        with pytest.raises(KeyError):
            runtime.trace(claim_id)
        assert claim_id not in runtime.pack_ir([claim_id], mode="exact").refs
        assert "SQLite" not in runtime.decompile_ir([claim_id])
        assert "SQLite" not in repr(runtime.memory_get([claim_id]))
        for policy in ("legacy-weighted/1", "reciprocal-rank-fusion/2"):
            result = runtime.retrieve(
                "SQLite",
                ns="tenant-a",
                scope="thread",
                budget=20,
                include_trace=True,
                ranking_policy=policy,
            )
            assert claim_id not in {candidate.record.id for candidate in result.candidates}
            assert claim_id not in repr(result.trace)


def test_delete_invalidates_current_graph_products_and_excludes_pack_content(
    tmp_path: Path,
) -> None:
    raw = MIRLRecord(
        id="raw:d3:graph-product",
        kind=RecordKind.RAW,
        ns="tenant-a",
        scope="thread",
        attrs={
            "content": "Ada uses SQLite.",
            "source_ref": "local://lifecycle-exclusion/graph-product",
        },
    )
    entity = MIRLRecord(
        id="ent:d3:ada",
        kind=RecordKind.ENT,
        ns="tenant-a",
        scope="thread",
        evidence=[raw.id],
        attrs={"label": "Ada", "entity_type": "person"},
    )
    claim = MIRLRecord(
        id="clm:d3:sqlite",
        kind=RecordKind.CLM,
        ns="tenant-a",
        scope="thread",
        evidence=[raw.id],
        attrs={
            "subject": entity.id,
            "predicate": "uses",
            "object": "SQLite",
        },
    )

    with SeamRuntime(
        tmp_path / "projection-exclusion.db", allow_pgvector_env=False
    ) as runtime:
        runtime.persist_ir(IRBatch([raw, entity, claim]))
        built = runtime.rebuild_graph_products(
            namespace="tenant-a", scope="thread"
        )
        before = runtime.graph_products(namespace="tenant-a", scope="thread")
        assert built["accepted_fact_count"] == 1
        assert "SQLite" in repr(before)
        assert "SQLite" in repr(runtime.pack_ir([claim.id], mode="exact").payload)
        persisted_pack = runtime.pack_ir(
            [claim.id], mode="exact", persist=True
        )
        assert "SQLite" in repr(
            runtime.store.read_pack(persisted_pack.pack_id).payload
        )

        _soft_delete(
            runtime,
            record_ids=[claim.id],
            idempotency_key="delete-graph-product-claim",
        )

        retained = runtime.store.load_ir(ids=[claim.id]).records[0]
        assert retained.status is Status.DELETED_SOFT
        assert retained.attrs["object"] == "SQLite"
        assert "SQLite" not in repr(
            runtime.graph_products(namespace="tenant-a", scope="thread")
        )
        packed = runtime.pack_ir([claim.id], mode="exact")
        assert claim.id not in packed.refs
        assert "SQLite" not in repr(packed.payload)
        with pytest.raises(KeyError):
            runtime.store.read_pack(persisted_pack.pack_id)

        rebuilt = runtime.rebuild_graph_products(
            namespace="tenant-a", scope="thread"
        )
        repeated = runtime.rebuild_graph_products(
            namespace="tenant-a", scope="thread"
        )
        assert rebuilt["accepted_fact_count"] == 0
        assert repeated["reused"] is True
        assert repeated["build_id"] == rebuilt["build_id"]


def test_identity_audit_keeps_merge_metadata_but_hides_deleted_evidence(
    tmp_path: Path,
) -> None:
    canonical = MIRLRecord(
        id="ent:ibm",
        kind=RecordKind.ENT,
        ns="tenant-a",
        scope="thread",
        attrs={"label": "IBM", "entity_type": "org"},
    )
    alias = MIRLRecord(
        id="ent:ibm-corp",
        kind=RecordKind.ENT,
        ns="tenant-a",
        scope="thread",
        attrs={
            "label": "International Business Machines",
            "entity_type": "org",
            "aliases": ["IBM"],
        },
    )
    with SeamRuntime(
        tmp_path / "identity-exclusion.db", allow_pgvector_env=False
    ) as runtime:
        runtime.persist_ir(IRBatch([canonical, alias]))
        generated = runtime.store.generate_identity_merge_candidates(
            ns="tenant-a", scope="thread"
        )
        merge_id = str(generated["proposed"][0])
        before = runtime.store.identity_merge_audit(alias.id)
        assert before[0]["id"] == merge_id
        assert before[0]["evidence"]

        _soft_delete(
            runtime,
            record_ids=[canonical.id],
            idempotency_key="delete-identity-evidence",
        )

        listed = runtime.store.identity_merges(ns="tenant-a", scope="thread")
        audited = runtime.store.identity_merge_audit(alias.id)
        assert listed == []
        assert audited == []
        with runtime.store._pool.checkout() as connection:
            assert connection.execute(
                "select count(*) from identity_merges where id = ?", (merge_id,)
            ).fetchone()[0] == 1
            assert connection.execute(
                "select count(*) from identity_merge_evidence where merge_id = ?",
                (merge_id,),
            ).fetchone()[0] > 0


def test_identity_conflict_hides_present_noncurrent_endpoint(tmp_path: Path) -> None:
    canonical = MIRLRecord(
        id="ent:d3:excluded-canonical",
        kind=RecordKind.ENT,
        ns="tenant-a",
        scope="thread",
        attrs={"label": "Current Name", "entity_type": "org"},
    )
    alias = MIRLRecord(
        id="ent:d3:excluded-alias",
        kind=RecordKind.ENT,
        ns="tenant-a",
        scope="thread",
        attrs={
            "label": "Former Name",
            "entity_type": "org",
            "aliases": ["Current Name"],
        },
    )
    with SeamRuntime(tmp_path / "excluded-identity.db", allow_pgvector_env=False) as runtime:
        runtime.persist_ir(IRBatch([canonical, alias]))
        generated = runtime.store.generate_identity_merge_candidates(
            ns="tenant-a", scope="thread"
        )
        merge_id = str(generated["proposed"][0])
        retained = runtime.store.load_ir(ids=[canonical.id]).records[0]
        retained.status = Status.SUPERSEDED
        runtime.persist_ir(IRBatch([retained]))
        with runtime.store._pool.checkout() as connection:
            connection.execute(
                "update identity_merges set status = 'conflict' where id = ?",
                (merge_id,),
            )
            connection.commit()

        assert runtime.store.load_ir(ids=[canonical.id]).records[0].status is Status.SUPERSEDED
        assert runtime.store.identity_merges(ns="tenant-a", scope="thread") == []
        assert runtime.store.identity_merge_audit(alias.id) == []


def test_read_pack_rejects_pack_record_deleted_soft(tmp_path: Path) -> None:
    with SeamRuntime(tmp_path / "deleted-pack.db", allow_pgvector_env=False) as runtime:
        outcome = runtime.ingest_text(
            "Ada uses SQLite.",
            source_ref="local://lifecycle-exclusion/deleted-pack",
            ns="tenant-a",
            scope="thread",
        )
        pack = runtime.pack_ir([_claim_id(outcome.stored_ids)], mode="exact", persist=True)
        _soft_delete(
            runtime,
            record_ids=[pack.pack_id],
            idempotency_key="delete-pack-itself",
        )
        assert runtime.store.load_ir(ids=[pack.pack_id]).records
        with pytest.raises(KeyError):
            runtime.store.read_pack(pack.pack_id)


def test_soft_delete_removes_affected_reusable_node_vector(
    tmp_path: Path,
) -> None:
    entity = MIRLRecord(
        id="ent:d3:ephemeral",
        kind=RecordKind.ENT,
        ns="tenant-a",
        scope="thread",
        attrs={"label": "Ephemeral", "entity_type": "concept"},
    )
    with SeamRuntime(
        tmp_path / "node-vector-exclusion.db", allow_pgvector_env=False
    ) as runtime:
        runtime.persist_ir(IRBatch([entity]))
        detail = runtime.store.knowledge_node(entity.id)
        node = detail["node"]
        model = runtime.embedding_model
        model_name = getattr(model, "name", "") or model.__class__.__name__
        source_text = render_node_text(
            str(node["kind"]), str(node["label"]), node["properties"]
        )
        source_hash = node_vector_source_hash(source_text, model_name)
        assert runtime.store.reusable_node_vectors(
            model_name, [source_hash]
        ).get(source_hash)

        _soft_delete(
            runtime,
            record_ids=[entity.id],
            idempotency_key="delete-node-vector-source",
        )

        assert runtime.store.reusable_node_vectors(model_name, [source_hash]) == {}


def test_delete_reprojects_still_live_shared_node_vector(tmp_path: Path) -> None:
    raw = MIRLRecord(
        id="raw:d3:shared",
        kind=RecordKind.RAW,
        ns="tenant-a",
        scope="thread",
        attrs={"content": "Ada uses SQLite and Postgres.", "source_ref": "local://d3/shared"},
    )
    entity = MIRLRecord(
        id="ent:d3:shared-ada",
        kind=RecordKind.ENT,
        ns="tenant-a",
        scope="thread",
        evidence=[raw.id],
        attrs={"label": "Ada", "entity_type": "person"},
    )
    claims = [
        MIRLRecord(
            id=f"clm:d3:shared:{name.lower()}",
            kind=RecordKind.CLM,
            ns="tenant-a",
            scope="thread",
            evidence=[raw.id],
            attrs={"subject": entity.id, "predicate": "uses", "object": name},
        )
        for name in ("SQLite", "Postgres")
    ]
    with SeamRuntime(tmp_path / "shared-node.db", allow_pgvector_env=False) as runtime:
        runtime.persist_ir(IRBatch([raw, entity, *claims]))
        node = runtime.store.knowledge_node(entity.id)["node"]
        model = runtime.embedding_model
        model_name = getattr(model, "name", "") or model.__class__.__name__
        source_hash = node_vector_source_hash(
            render_node_text(str(node["kind"]), str(node["label"]), node["properties"]),
            model_name,
        )
        _soft_delete(
            runtime,
            record_ids=[claims[0].id],
            idempotency_key="delete-one-shared-claim",
        )
        assert runtime.store.knowledge_node(entity.id)["node"] is not None
        assert runtime.store.reusable_node_vectors(model_name, [source_hash]).get(source_hash)


def test_store_delete_preserves_unchanged_shared_endpoint_vector(tmp_path: Path) -> None:
    raw = MIRLRecord(
        id="raw:d3:store-shared",
        kind=RecordKind.RAW,
        ns="tenant-a",
        scope="thread",
        attrs={"content": "Ada uses SQLite and Postgres.", "source_ref": "local://d3/store-shared"},
    )
    entity = MIRLRecord(
        id="ent:d3:store-shared-ada",
        kind=RecordKind.ENT,
        ns="tenant-a",
        scope="thread",
        evidence=[raw.id],
        attrs={"label": "Ada", "entity_type": "person"},
    )
    claims = [
        MIRLRecord(
            id=f"clm:d3:store-shared:{name.lower()}",
            kind=RecordKind.CLM,
            ns="tenant-a",
            scope="thread",
            evidence=[raw.id],
            attrs={"subject": entity.id, "predicate": "uses", "object": name},
        )
        for name in ("SQLite", "Postgres")
    ]
    with SeamRuntime(tmp_path / "store-shared-node.db", allow_pgvector_env=False) as runtime:
        runtime.persist_ir(IRBatch([raw, entity, *claims]))
        node = runtime.store.knowledge_node(entity.id)["node"]
        model = runtime.embedding_model
        model_name = getattr(model, "name", "") or model.__class__.__name__
        source_hash = node_vector_source_hash(
            render_node_text(str(node["kind"]), str(node["label"]), node["properties"]),
            model_name,
        )
        planned = runtime.store.plan_scoped_delete(
            tenant_id="tenant-a",
            namespace="tenant-a",
            scope="thread",
            record_ids=[claims[0].id],
            idempotency_key="store-delete-one-shared-claim",
            actor="operator",
        )
        runtime.store.apply_scoped_delete(
            tenant_id="tenant-a",
            operation_id=str(planned["operation_id"]),
            actor="operator",
        )
        assert runtime.store.reusable_node_vectors(model_name, [source_hash]).get(source_hash)
        assert runtime.store.pending_node_vectors(model_name) == []


def test_delete_rebuilds_surviving_graph_products_and_hides_old_history(
    tmp_path: Path,
) -> None:
    records: list[MIRLRecord] = []
    claims: list[MIRLRecord] = []
    for person, product in (("Ada", "SQLite"), ("Bob", "Postgres")):
        raw = MIRLRecord(
            id=f"raw:d3:{person.lower()}",
            kind=RecordKind.RAW,
            ns="tenant-a",
            scope="thread",
            attrs={"content": f"{person} uses {product}.", "source_ref": f"local://d3/{person}"},
        )
        entity = MIRLRecord(
            id=f"ent:d3:{person.lower()}",
            kind=RecordKind.ENT,
            ns="tenant-a",
            scope="thread",
            evidence=[raw.id],
            attrs={"label": person, "entity_type": "person"},
        )
        claim = MIRLRecord(
            id=f"clm:d3:{product.lower()}",
            kind=RecordKind.CLM,
            ns="tenant-a",
            scope="thread",
            evidence=[raw.id],
            attrs={"subject": entity.id, "predicate": "uses", "object": product},
        )
        records.extend((raw, entity, claim))
        claims.append(claim)
    with SeamRuntime(tmp_path / "surviving-products.db", allow_pgvector_env=False) as runtime:
        runtime.persist_ir(IRBatch(records))
        runtime.rebuild_graph_products(namespace="tenant-a", scope="thread")
        before = runtime.graph_products(namespace="tenant-a", scope="thread")
        sqlite_key = next(row["stable_key"] for row in before if "SQLite" in repr(row))
        _soft_delete(
            runtime,
            record_ids=[claims[0].id],
            idempotency_key="delete-one-product",
        )
        current = runtime.graph_products(namespace="tenant-a", scope="thread")
        assert "Postgres" in repr(current)
        assert "SQLite" not in repr(current)
        assert runtime.graph_product_history(
            namespace="tenant-a", scope="thread", stable_key=str(sqlite_key)
        ) == []
        with runtime.store._pool.checkout() as connection:
            assert connection.execute(
                "select count(*) from graph_product where stable_key = ?", (sqlite_key,)
            ).fetchone()[0] > 0


def test_cleanup_reopen_resume_and_rebuild_are_idempotent_and_content_free(
    tmp_path: Path,
) -> None:
    database = tmp_path / "cleanup-resume.db"
    secret = "D3VioletLifecycleSecret"
    vectors = _FailingDeleteVectorAdapter()
    operation_id = ""
    claim_id = ""
    with SeamRuntime(
        database,
        vector_adapter=vectors,
        allow_pgvector_env=False,
    ) as runtime:
        outcome = runtime.ingest_text(
            f"Ada uses {secret}.",
            source_ref="local://lifecycle-exclusion/cleanup-resume",
            ns="tenant-a",
            scope="thread",
        )
        claim_id = _claim_id(outcome.stored_ids)
        runtime.rebuild_graph_products(namespace="tenant-a", scope="thread")
        planned = runtime.plan_scoped_delete(
            tenant_id="tenant-a",
            namespace="tenant-a",
            scope="thread",
            record_ids=[claim_id],
            idempotency_key="cleanup-reopen-resume",
            actor="operator",
        )
        operation_id = str(planned["operation_id"])
        with pytest.raises(RuntimeError, match="injected vector cleanup failure"):
            runtime.apply_scoped_delete(
                tenant_id="tenant-a",
                operation_id=operation_id,
                actor="operator",
            )
        pending = runtime.store.lifecycle_operation(
            tenant_id="tenant-a", operation_id=operation_id
        )
        assert pending["state"] == "cleanup_pending"
        assert secret not in repr(pending)
        assert secret not in repr(
            runtime.graph_products(namespace="tenant-a", scope="thread")
        )

    vectors.fail_delete = False
    with SeamRuntime(
        database,
        vector_adapter=vectors,
        allow_pgvector_env=False,
    ) as reopened:
        recovered = reopened.resume_lifecycle_operation(
            operation_id, tenant_id="tenant-a", actor="recovery"
        )
        repeated = reopened.resume_lifecycle_operation(
            operation_id, tenant_id="tenant-a", actor="recovery"
        )
        rebuilt = reopened.rebuild_graph_products(
            namespace="tenant-a", scope="thread"
        )
        rebuilt_again = reopened.rebuild_graph_products(
            namespace="tenant-a", scope="thread"
        )

        assert recovered["state"] == repeated["state"] == "applied"
        assert recovered["events"] == repeated["events"]
        assert secret not in repr(recovered)
        assert secret not in repr(
            reopened.graph_products(namespace="tenant-a", scope="thread")
        )
        assert rebuilt_again["reused"] is True
        assert rebuilt_again["build_id"] == rebuilt["build_id"]
        assert claim_id not in reopened.pack_ir([claim_id], mode="exact").refs
        with pytest.raises(KeyError):
            reopened.trace(claim_id)
        with reopened.store._pool.checkout() as connection:
            assert connection.execute("pragma integrity_check").fetchone()[0] == "ok"
            assert connection.execute("pragma foreign_key_check").fetchall() == []


@pytest.mark.parametrize(
    "ranking_policy",
    ["legacy-weighted/1", "reciprocal-rank-fusion/2"],
)
def test_retrieve_and_search_ir_exclude_soft_deleted_memory_under_supported_policies(
    tmp_path: Path,
    ranking_policy: str,
) -> None:
    secret = "D3QuartzRetrievalSecret"
    with SeamRuntime(
        tmp_path / f"retrieval-{ranking_policy.split('/')[0]}.db",
        allow_pgvector_env=False,
    ) as runtime:
        outcome = runtime.ingest_text(
            f"Ada owns {secret}.",
            source_ref=f"local://lifecycle-exclusion/{ranking_policy}",
            ns="tenant-a",
            scope="thread",
        )
        claim_id = _claim_id(outcome.stored_ids)
        _soft_delete(
            runtime,
            record_ids=[claim_id],
            idempotency_key=f"delete-{ranking_policy}",
        )

        retrieved = runtime.retrieve(
            secret,
            ns="tenant-a",
            scope="thread",
            budget=20,
            include_trace=True,
            ranking_policy=ranking_policy,
        )
        searched = runtime.search_ir(
            secret,
            ns="tenant-a",
            scope="thread",
            budget=20,
            include_trace=True,
            ranking_policy=ranking_policy,
        )
        assert claim_id not in {
            candidate.record.id for candidate in retrieved.candidates
        }
        assert claim_id not in {
            candidate.record.id for candidate in searched.candidates
        }
        retrieved_payload = retrieved.to_dict()
        searched_payload = searched.to_dict()
        assert secret not in repr(retrieved_payload["candidates"])
        assert secret not in repr(searched_payload["candidates"])
        assert secret not in repr(retrieved_payload["trace"]["legs"])
        assert secret not in repr(searched_payload["trace"]["legs"])
