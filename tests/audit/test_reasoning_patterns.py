from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from seam_runtime import IRBatch, MIRLRecord, RecordKind, SeamSDK


def _verified_run(seam: SeamSDK, objective: str, *, scope: str = "thread"):
    run = seam.start_reasoning(
        objective,
        ns="acme",
        scope=scope,
        agent_id="planner",
    )
    hypothesis = run.add_node(
        "hypothesis",
        "Use the reversible path.",
        operation="compare-reversible-options",
    )
    check = run.verify(
        str(hypothesis["node_id"]),
        check_kind="test",
        check_ref="tests/test_plan.py::test_reversible",
        verdict="passed",
        summary="The reversible path passed.",
        result="1 passed",
    )
    outcome = run.finalize_verified(
        "Choose the reversible path.",
        verification_ids=[str(check["verification_id"])],
        supporting_node_ids=[str(hypothesis["node_id"])],
    )
    return run, outcome


def test_verified_runs_learn_content_free_patterns_and_reuse_improves_rank(tmp_path):
    with SeamSDK(tmp_path / "patterns.db", allow_pgvector_env=False) as seam:
        source, outcome = _verified_run(
            seam, "Decide which database migration path is safest."
        )
        pattern_id = str(outcome["learned_pattern_id"])

        matches = source.patterns(
            "Choose the safest reversible database migration.",
            operation="compare-reversible-options",
        )
        assert [item["pattern_id"] for item in matches] == [pattern_id]
        pattern_text = json.dumps(matches[0]["template"], sort_keys=True)
        assert "Use the reversible path" not in pattern_text
        assert "Choose the reversible path" not in pattern_text
        assert "1 passed" not in pattern_text
        assert {step["kind"] for step in matches[0]["template"]["steps"]} >= {
            "objective",
            "hypothesis",
            "outcome",
        }
        assert matches[0]["template"]["checks"] == [
            {"kind": "test", "subject": "step:2"}
        ]

        reused = seam.start_reasoning(
            "Choose the safest reversible database migration.",
            ns="acme",
            scope="thread",
            agent_id="planner-2",
        )
        assert reused.recommended_patterns[0]["pattern_id"] == pattern_id
        use = reused.use_pattern(pattern_id)
        hypothesis = reused.add_node(
            "hypothesis",
            "Evaluate the prior verified structure on the new migration.",
            operation="compare-reversible-options",
        )
        check = reused.verify(
            str(hypothesis["node_id"]),
            check_kind="test",
            check_ref="tests/test_new_plan.py::test_reversible",
            verdict="passed",
            summary="The new rollback path passed.",
        )
        second = reused.finalize_verified(
            "Choose the new reversible path.",
            verification_ids=[str(check["verification_id"])],
            supporting_node_ids=[str(hypothesis["node_id"])],
        )
        assert second["pattern_feedback_count"] == 1
        updated = seam.runtime.store.reasoning_pattern(pattern_id)
        assert updated["uses"] == 1
        assert updated["successes"] == 2
        assert updated["failures"] == 0
        assert updated["trust_score"] == 1.0
        assert use["use_id"].startswith("ruse:")


def test_pattern_reuse_fails_closed_on_boundary_freshness_and_evidence_drift(
    tmp_path,
):
    with SeamSDK(tmp_path / "pattern-gates.db", allow_pgvector_env=False) as seam:
        evidence = MIRLRecord(
            id="raw:plan",
            kind=RecordKind.RAW,
            ns="acme",
            scope="thread",
            attrs={"content": "The rollback test passed."},
        )
        seam.runtime.persist_ir(IRBatch([evidence]))
        run = seam.start_reasoning(
            "Validate the rollback plan.",
            ns="acme",
            scope="thread",
        )
        hypothesis = run.add_node(
            "hypothesis",
            "The rollback plan is viable.",
            operation="validate-rollback",
        )
        check = run.verify(
            str(hypothesis["node_id"]),
            check_kind="test",
            check_ref="rollback",
            verdict="passed",
            summary="Rollback passed.",
            evidence_refs=[evidence.id],
        )
        outcome = run.finalize_verified(
            "Use the rollback plan.",
            verification_ids=[str(check["verification_id"])],
            supporting_node_ids=[str(hypothesis["node_id"])],
        )
        pattern_id = str(outcome["learned_pattern_id"])

        assert seam.runtime.store.reasoning_patterns(
            objective="Validate a rollback plan.",
            ns="acme",
            scope="other",
        ) == []
        created = datetime.fromisoformat(
            str(seam.runtime.store.reasoning_pattern(pattern_id)["created_at"])
        )
        stale_now = (created + timedelta(days=91)).astimezone(
            timezone.utc
        ).isoformat()
        assert seam.runtime.store.reasoning_patterns(
            objective="Validate a rollback plan.",
            ns="acme",
            scope="thread",
            max_age_days=90,
            now=stale_now,
        ) == []

        eligible = seam.runtime.store.reasoning_patterns(
            objective="Validate a rollback plan.",
            ns="acme",
            scope="thread",
        )
        assert [item["pattern_id"] for item in eligible] == [pattern_id]
        with seam.runtime.store._pool.checkout() as connection:
            connection.execute(
                "update ir_records set payload_json = ? where id = ?",
                ('{"changed":true}', evidence.id),
            )
            connection.commit()
        assert seam.runtime.store.reasoning_patterns(
            objective="Validate a rollback plan.",
            ns="acme",
            scope="thread",
        ) == []
        current = seam.runtime.store.reasoning_pattern(pattern_id)
        assert current["provenance_current"] is False
        assert "evidence drift" in current["provenance_status"]


def test_pattern_feedback_cannot_cross_reasoning_runs(tmp_path):
    with SeamSDK(tmp_path / "pattern-feedback.db", allow_pgvector_env=False) as seam:
        source, outcome = _verified_run(
            seam, "Choose a safe database migration."
        )
        pattern_id = str(outcome["learned_pattern_id"])
        use = source.use_pattern(pattern_id)
        other = seam.start_reasoning(
            "Choose a safe database migration.",
            ns="acme",
            scope="thread",
        )

        try:
            other.reject_pattern(str(use["use_id"]), reason="not this run")
        except ValueError as exc:
            assert "does not belong" in str(exc)
        else:
            raise AssertionError("cross-run pattern feedback was accepted")
        assert seam.runtime.store.reasoning_pattern(pattern_id)["failures"] == 0

        source.reject_pattern(str(use["use_id"]), reason="did not transfer")
        assert seam.runtime.store.reasoning_pattern(pattern_id)["failures"] == 1


def test_later_verified_pattern_outcome_is_retained_as_disagreement(tmp_path):
    with SeamSDK(tmp_path / "pattern-disagreement.db", allow_pgvector_env=False) as seam:
        _, outcome = _verified_run(
            seam, "Choose a safe database migration."
        )
        pattern_id = str(outcome["learned_pattern_id"])
        reused = seam.start_reasoning(
            "Choose a safe database migration.",
            ns="acme",
            scope="thread",
        )
        use = reused.use_pattern(pattern_id)
        reused.reject_pattern(
            str(use["use_id"]),
            reason="the first attempted application failed",
        )
        hypothesis = reused.add_node(
            "hypothesis",
            "Retry with the reversible migration path.",
            operation="compare-reversible-options",
        )
        check = reused.verify(
            str(hypothesis["node_id"]),
            check_kind="test",
            check_ref="tests/test_retry.py::test_reversible",
            verdict="passed",
            summary="The corrected application passed.",
        )
        verified = reused.finalize_verified(
            "Use the corrected reversible path.",
            verification_ids=[str(check["verification_id"])],
            supporting_node_ids=[str(hypothesis["node_id"])],
        )

        pattern = seam.runtime.store.reasoning_pattern(pattern_id)
        assert verified["pattern_feedback_count"] == 1
        assert pattern["successes"] == 2
        assert pattern["failures"] == 1
        assert pattern["disagreement_count"] == 1
        disagreement = pattern["disagreements"][0]
        assert disagreement["disagreement_id"].startswith("rdis:")
        assert disagreement["use_id"] == str(use["use_id"])
        assert disagreement["prior_succeeded"] is False
        assert disagreement["later_succeeded"] is True
        assert disagreement["outcome_node_id"] == verified["node_id"]
        assert disagreement["reason"] == (
            "pattern reuse supported a verified accepted outcome"
        )

        repeated = seam.runtime.store.record_reasoning_pattern_feedback(
            use_id=str(use["use_id"]),
            expected_run_id=reused.run_id,
            succeeded=True,
            outcome_node_id=str(verified["node_id"]),
            reason="same successful outcome, described differently",
        )
        assert repeated["result_id"] == disagreement["disagreement_id"]
        assert repeated["reason"] == disagreement["reason"]
        replayed_pattern = seam.runtime.store.reasoning_pattern(pattern_id)
        assert replayed_pattern["successes"] == 2
        assert replayed_pattern["failures"] == 1
        assert replayed_pattern["disagreement_count"] == 1


def test_reworded_same_pattern_outcome_is_idempotent(tmp_path):
    with SeamSDK(tmp_path / "pattern-reworded-result.db", allow_pgvector_env=False) as seam:
        source, outcome = _verified_run(
            seam, "Choose a safe database migration."
        )
        pattern_id = str(outcome["learned_pattern_id"])
        use = source.use_pattern(pattern_id)

        first = source.reject_pattern(
            str(use["use_id"]),
            reason="the attempted application failed",
        )
        repeated = source.reject_pattern(
            str(use["use_id"]),
            reason="same outcome, described with different words",
        )

        pattern = seam.runtime.store.reasoning_pattern(pattern_id)
        assert repeated["result_id"] == first["result_id"]
        assert pattern["failures"] == 1
        assert pattern["disagreement_count"] == 0
        assert pattern["disagreements"] == []
