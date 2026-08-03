"""R5 contract: explicit reviewed and reversible reasoning promotion."""

from __future__ import annotations

import inspect
import sqlite3
import threading
from pathlib import Path

import pytest

from seam_runtime import IRBatch, MIRLRecord, RecordKind, SeamSDK
from seam_runtime.models import HashEmbeddingModel
from seam_runtime.reasoning_promotion import (
    get_reasoning_promotion,
    init_reasoning_promotion,
    list_reasoning_promotions,
    propose_reasoning_promotion,
    reasoning_promotion_eligibility,
    record_reasoning_promotion_application,
    reverse_reasoning_promotion,
    review_reasoning_promotion,
)
from seam_runtime.runtime import SeamRuntime
from seam_runtime.vector_adapters import MemoryVectorAdapter


class _BlockingPromotionAdapter(MemoryVectorAdapter):
    def __init__(self, model: HashEmbeddingModel) -> None:
        super().__init__(model)
        self.entered = threading.Event()
        self.release = threading.Event()
        self.blocked_once = False

    def index_records(self, records: list[MIRLRecord]) -> None:
        should_block = any(
            record.id == "clm:reviewed-migration"
            and record.attrs.get("object") == "reversible"
            for record in records
        )
        if should_block and not self.blocked_once:
            self.blocked_once = True
            self.entered.set()
            if not self.release.wait(timeout=5):
                raise RuntimeError("timed out waiting to release promotion index")
        super().index_records(records)


def _verified_outcome(seam: SeamSDK):
    evidence = MIRLRecord(
        id="raw:promotion-evidence",
        kind=RecordKind.RAW,
        ns="acme",
        scope="thread",
        attrs={"content": "The migration rollback was verified."},
    )
    migration_project = MIRLRecord(
        id="project:migration",
        kind=RecordKind.ENT,
        ns="acme",
        scope="thread",
        attrs={"label": "Migration project", "entity_type": "project"},
    )
    seam.runtime.persist_ir(IRBatch([evidence, migration_project]))
    run = seam.start_reasoning(
        "Choose the migration path.",
        ns="acme",
        scope="thread",
        agent_id="planner",
    )
    subject = run.add_node("hypothesis", "Use the reversible migration.")
    check = run.verify(
        str(subject["node_id"]),
        check_kind="test",
        check_ref="tests/test_migration.py::test_rollback",
        verdict="passed",
        summary="The rollback test passed.",
        evidence_refs=[evidence.id],
    )
    outcome = run.finalize_verified(
        "Use the reversible migration.",
        verification_ids=[str(check["verification_id"])],
        supporting_node_ids=[str(subject["node_id"])],
    )
    return run, subject, check, outcome, evidence


@pytest.fixture
def promotion_db(tmp_path):
    with SeamSDK(tmp_path / "promotion.db", allow_pgvector_env=False) as seam:
        with seam.runtime.store._pool.checkout() as connection:
            init_reasoning_promotion(connection)
            connection.commit()
        yield seam


def _propose(seam: SeamSDK):
    run, subject, check, outcome, evidence = _verified_outcome(seam)
    with seam.runtime.store._pool.checkout() as connection:
        proposal = propose_reasoning_promotion(
            connection,
            run_id=run.run_id,
            outcome_node_id=str(outcome["node_id"]),
            assertion_record_id="clm:reviewed-migration",
            assertion_subject="project:migration",
            assertion_predicate="recommended_path",
            assertion_object="reversible",
            assertion_status="inferred",
            assertion_confidence=0.92,
            proposed_by="planner",
        )
        connection.commit()
    return run, subject, check, outcome, evidence, proposal


def test_proposal_review_returns_explicit_payload_without_inserting_mirl(
    promotion_db: SeamSDK,
) -> None:
    seam = promotion_db
    run, _subject, check, outcome, evidence, proposal = _propose(seam)

    assert proposal["run_id"] == run.run_id
    assert proposal["outcome_node_id"] == outcome["node_id"]
    assert proposal["verification_ids"] == [check["verification_id"]]
    assert list(proposal["evidence_fingerprints"]) == [evidence.id]
    assert proposal["eligible"] is False
    assert proposal["approved_assertion"] is None

    with seam.runtime.store._pool.checkout() as connection:
        assert (
            connection.execute(
                "select 1 from ir_records where id = 'clm:reviewed-migration'"
            ).fetchone()
            is None
        )
        review = review_reasoning_promotion(
            connection,
            proposal_id=str(proposal["proposal_id"]),
            review_kind="human",
            decision="approved",
            reviewer_id="operator",
            rationale="The exact evidence supports this scoped assertion.",
        )
        approved = reasoning_promotion_eligibility(
            connection, str(proposal["proposal_id"])
        )
        connection.commit()

    assert review["decision"] == "approved"
    assert approved["eligible"] is True
    payload = approved["approved_assertion"]
    assert payload == {
        "id": "clm:reviewed-migration",
        "kind": "CLM",
        "ns": "acme",
        "scope": "thread",
        "ver": "mirl/0.1",
        "conf": 0.92,
        "status": "inferred",
        "t0": None,
        "t1": None,
        "prov": [],
        "evidence": [evidence.id],
        "ext": {
            "reasoning_promotion_proposal_id": proposal["proposal_id"],
            "reasoning_promotion_sha256": proposal["proposal_sha256"],
            "reasoning_outcome_node_id": outcome["node_id"],
            "reasoning_knowledge_refs": [],
        },
        "attrs": {
            "subject": "project:migration",
            "predicate": "recommended_path",
            "object": "reversible",
        },
    }
    with seam.runtime.store._pool.checkout() as connection:
        assert (
            connection.execute(
                "select 1 from ir_records where id = ?", (payload["id"],)
            ).fetchone()
            is None
        )
    seam.runtime.persist_ir(
        IRBatch([evidence, MIRLRecord.from_dict(payload)])
    )
    with seam.runtime.store._pool.checkout() as connection:
        application = record_reasoning_promotion_application(
            connection,
            proposal_id=str(proposal["proposal_id"]),
            assertion_record_id=str(payload["id"]),
            applied_by="store",
        )
        connection.commit()
        current = get_reasoning_promotion(connection, str(proposal["proposal_id"]))
    assert application["assertion_record_id"] == payload["id"]
    assert len(str(application["assertion_sha256"])) == 64
    assert current["application"]["application_id"] == application["application_id"]
    assert current["eligible"] is False
    assert current["eligibility_reason"] == "promotion proposal was already applied"


def test_approval_and_eligibility_fail_closed_on_stale_provenance(
    promotion_db: SeamSDK,
) -> None:
    seam = promotion_db
    run, subject, check, _outcome, evidence, proposal = _propose(seam)
    run.verify(
        str(subject["node_id"]),
        check_kind="test",
        check_ref="tests/test_migration.py::test_rollback",
        verdict="passed",
        summary="A newer run of the rollback test passed.",
        evidence_refs=[evidence.id],
        retry_of=str(check["verification_id"]),
    )
    with seam.runtime.store._pool.checkout() as connection:
        with pytest.raises(ValueError, match="stale or non-current"):
            review_reasoning_promotion(
                connection,
                proposal_id=str(proposal["proposal_id"]),
                review_kind="policy",
                decision="approved",
                reviewer_id="promotion-policy/1",
                rationale="Policy attempted approval.",
            )
        connection.rollback()

    # A fresh proposal approved before evidence drift becomes ineligible later.
    seam2 = SeamSDK(
        Path(seam.runtime.store.path).parent / "promotion-drift.db",
        allow_pgvector_env=False,
    )
    try:
        with seam2.runtime.store._pool.checkout() as connection:
            init_reasoning_promotion(connection)
            connection.commit()
        *_parts, drift_proposal = _propose(seam2)
        with seam2.runtime.store._pool.checkout() as connection:
            review_reasoning_promotion(
                connection,
                proposal_id=str(drift_proposal["proposal_id"]),
                review_kind="policy",
                decision="approved",
                reviewer_id="promotion-policy/1",
                rationale="Current evidence passed policy review.",
            )
            connection.execute(
                "update ir_records set payload_json = ? where id = ?",
                ('{"changed":true}', "raw:promotion-evidence"),
            )
            eligibility = reasoning_promotion_eligibility(
                connection, str(drift_proposal["proposal_id"])
            )
            connection.rollback()
        assert eligibility["eligible"] is False
        assert "evidence drift" in str(eligibility["reason"])
        assert eligibility["approved_assertion"] is None
    finally:
        seam2.close()


def test_runtime_promotion_cannot_publish_stale_vector_after_later_write(
    promotion_db: SeamSDK,
) -> None:
    seam = promotion_db
    model = HashEmbeddingModel()
    adapter = _BlockingPromotionAdapter(model)
    seam.runtime.embedding_model = model
    seam.runtime.vector_adapter = adapter
    *_parts, proposal = _propose(seam)
    proposal_id = str(proposal["proposal_id"])
    with seam.runtime.store._pool.checkout() as connection:
        review_reasoning_promotion(
            connection,
            proposal_id=proposal_id,
            review_kind="human",
            decision="approved",
            reviewer_id="operator",
            rationale="Approved after exact evidence review.",
        )
        approved = reasoning_promotion_eligibility(connection, proposal_id)
        connection.commit()

    replacement = MIRLRecord.from_dict(approved["approved_assertion"])
    replacement.attrs["object"] = "writer-b"
    runtime_b = SeamRuntime(
        seam.runtime.store.path,
        embedding_model=model,
        vector_adapter=adapter,
        allow_pgvector_env=False,
    )
    outcomes: dict[str, object] = {}
    writer_done = threading.Event()

    def run_promotion() -> None:
        try:
            outcomes["promotion_report"] = seam.runtime.apply_reasoning_promotion(
                proposal_id=proposal_id,
                applied_by="operator",
            )
        except Exception as exc:  # noqa: BLE001 - capture the thread outcome
            outcomes["promotion_error"] = exc

    def run_writer() -> None:
        try:
            outcomes["writer_report"] = runtime_b.persist_ir(
                IRBatch([replacement])
            )
        except Exception as exc:  # noqa: BLE001 - capture the thread outcome
            outcomes["writer_error"] = exc
        finally:
            writer_done.set()

    try:
        promoter = threading.Thread(target=run_promotion)
        promoter.start()
        assert adapter.entered.wait(timeout=5)

        writer = threading.Thread(target=run_writer)
        writer.start()
        assert not writer_done.wait(timeout=0.1)

        adapter.release.set()
        promoter.join(timeout=5)
        writer.join(timeout=5)
        assert not promoter.is_alive()
        assert not writer.is_alive()
        assert "promotion_error" not in outcomes
        assert "writer_error" not in outcomes

        canonical = seam.runtime.store.load_ir(
            ids=[replacement.id]
        ).records[0]
        projected = adapter._rows[replacement.id][0]
        assert canonical.attrs["object"] == "writer-b"
        assert projected.attrs["object"] == "writer-b"
    finally:
        adapter.release.set()
        runtime_b.close()


def test_reversal_is_append_only_and_permanently_disables_proposal(
    promotion_db: SeamSDK,
) -> None:
    seam = promotion_db
    _run, _subject, _check, _outcome, evidence, proposal = _propose(seam)
    proposal_id = str(proposal["proposal_id"])
    with seam.runtime.store._pool.checkout() as connection:
        review_reasoning_promotion(
            connection,
            proposal_id=proposal_id,
            review_kind="human",
            decision="approved",
            reviewer_id="operator",
            rationale="Approved after evidence review.",
        )
        approved = reasoning_promotion_eligibility(connection, proposal_id)
        connection.commit()
    seam.runtime.persist_ir(
        IRBatch(
            [
                evidence,
                MIRLRecord.from_dict(approved["approved_assertion"]),
            ]
        )
    )
    with seam.runtime.store._pool.checkout() as connection:
        application = record_reasoning_promotion_application(
            connection,
            proposal_id=proposal_id,
            assertion_record_id="clm:reviewed-migration",
            applied_by="store",
        )
        reversal = reverse_reasoning_promotion(
            connection,
            proposal_id=proposal_id,
            reversed_by="operator",
            reason="New context requires a replacement assertion.",
        )
        connection.commit()
        assert reversal["application_id"] == application["application_id"]
        assert reversal["assertion_record_id"] == "clm:reviewed-migration"
        assert reasoning_promotion_eligibility(connection, proposal_id)["eligible"] is False
        with pytest.raises(ValueError, match="cannot be reviewed"):
            review_reasoning_promotion(
                connection,
                proposal_id=proposal_id,
                review_kind="human",
                decision="approved",
                reviewer_id="operator",
                rationale="Do not revive a reversed proposal.",
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "update reasoning_promotion_reversal set reason = 'rewrite' "
                "where reversal_id = ?",
                (reversal["reversal_id"],),
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "delete from reasoning_promotion_proposal where proposal_id = ?",
                (proposal_id,),
            )
        connection.rollback()
        current = get_reasoning_promotion(connection, proposal_id)
        assert current["reversal"]["reason"].startswith("New context")
        assert current["eligible"] is False


def test_promotion_surface_is_bounded_content_free_and_tenant_scoped(
    promotion_db: SeamSDK,
) -> None:
    seam = promotion_db
    *_parts, proposal = _propose(seam)
    parameters = set(inspect.signature(propose_reasoning_promotion).parameters)
    assert not parameters & {
        "content",
        "raw_log",
        "tool_payload",
        "provider_response",
        "chain_of_thought",
        "hidden_cot",
        "command",
        "payload",
        "attrs",
        "ext",
    }
    with seam.runtime.store._pool.checkout() as connection:
        columns = {
            str(row[1])
            for row in connection.execute(
                "pragma table_info(reasoning_promotion_proposal)"
            ).fetchall()
        }
        assert not columns & {
            "content",
            "raw_log",
            "tool_payload",
            "provider_response",
            "chain_of_thought",
            "command",
            "payload",
        }
        with pytest.raises(TypeError, match="free-form mappings"):
            propose_reasoning_promotion(
                connection,
                run_id=str(proposal["run_id"]),
                outcome_node_id=str(proposal["outcome_node_id"]),
                assertion_record_id="clm:unsafe",
                assertion_subject="project:migration",
                assertion_predicate="unsafe",
                assertion_object={"command": "private"},
                proposed_by="planner",
            )
        connection.rollback()
        assert list_reasoning_promotions(
            connection, ns="other", scope="thread"
        ) == []
        assert [
            item["proposal_id"]
            for item in list_reasoning_promotions(
                connection, ns="acme", scope="thread", limit=1
            )
        ] == [proposal["proposal_id"]]
        with pytest.raises(ValueError, match="between 1 and 100"):
            list_reasoning_promotions(
                connection, ns="acme", scope="thread", limit=101
            )
