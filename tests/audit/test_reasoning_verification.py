"""R3 contract: append-only verification loops over public reasoning artifacts."""

from __future__ import annotations

import hashlib
import inspect
import itertools
import sqlite3
from pathlib import Path

import pytest

from seam_runtime.mirl import RecordKind
from seam_runtime.runtime import SeamRuntime
from seam_runtime.sdk import ReasoningSession, SeamSDK


@pytest.fixture
def runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    instance = SeamRuntime(tmp_path / "verification.db", allow_pgvector_env=False)
    try:
        yield instance
    finally:
        instance.close()


def _subject(session: ReasoningSession) -> str:
    return str(
        session.add_node("hypothesis", "The migration is reversible.")["node_id"]
    )


def _seed_evidence(
    runtime: SeamRuntime, *, ns: str = "work", scope: str = "thread"
) -> tuple[str, str]:
    batch = runtime.compile_nl(
        "Ada verified the rollback path.",
        source_ref="local://verification-test",
        ns=ns,
        scope=scope,
        allow_env_extractor=False,
    )
    runtime.persist_ir(batch)
    raw_id = next(record.id for record in batch.records if record.kind == RecordKind.RAW)
    graph = runtime.store.knowledge_graph(
        query="Ada", namespace=ns, scope=scope, limit=100
    )
    knowledge_id = next(
        str(node["id"])
        for node in graph["nodes"]
        if node["kind"] in {"entity", "claim"}
    )
    return knowledge_id, raw_id


def test_failed_retry_then_verified_outcome_preserves_both_attempts(
    runtime: SeamRuntime,
) -> None:
    session = SeamSDK(runtime=runtime).start_reasoning(
        "Choose a safe migration.", ns="work", scope="thread", agent_id="codex"
    )
    subject_id = _subject(session)
    failed = session.verify(
        subject_id,
        check_kind="test",
        check_ref="tests/test_migration.py::test_rollback",
        verdict="failed",
        summary="Rollback fixture exposed a missing inverse.",
        result="FAILED: expected restored rows",
        exit_code=1,
        duration_ms=12.5,
    )
    passed = session.verify(
        subject_id,
        check_kind="test",
        check_ref="tests/test_migration.py::test_rollback",
        verdict="passed",
        summary="Rollback restored the original rows.",
        result="1 passed in 0.02s",
        exit_code=0,
        duration_ms=18.0,
        retry_of=str(failed["verification_id"]),
    )
    outcome = session.finalize_verified(
        "Use the reversible migration.",
        verification_ids=[str(passed["verification_id"])],
    )

    attempts = session.verifications()
    assert [item["verdict"] for item in attempts] == ["failed", "passed"]
    assert attempts[0]["superseded_by"] == passed["verification_id"]
    assert attempts[1]["retry_of"] == failed["verification_id"]
    assert attempts[1]["superseded_by"] is None
    assert outcome["status"] == "accepted"
    assert outcome["verification_ids"] == [passed["verification_id"]]
    assert session.graph()["verifications"] == [
        {
            "verification_id": item["verification_id"],
            "seq": item["seq"],
            "subject_node_id": item["subject_node_id"],
            "check_kind": item["check_kind"],
            "check_ref": item["check_ref"],
            "verdict": item["verdict"],
            "summary": item["summary"],
            "retry_of": item["retry_of"],
            "superseded_by": item["superseded_by"],
            "created_at": item["created_at"],
            "schema_version": item["schema_version"],
        }
        for item in attempts
    ]


def test_verification_stores_only_result_fingerprint(runtime: SeamRuntime) -> None:
    session = SeamSDK(runtime=runtime).start_reasoning("Keep tool output bounded.")
    subject_id = _subject(session)
    raw_result = "private tool output that must not enter the reasoning graph"
    verification = session.verify(
        subject_id,
        check_kind="tool",
        check_ref="schema-lint",
        verdict="passed",
        summary="The schema lint completed successfully.",
        result=raw_result,
    )

    assert verification["result_sha256"] == hashlib.sha256(
        raw_result.encode("utf-8")
    ).hexdigest()
    assert verification["result_length"] == len(raw_result.encode("utf-8"))
    assert raw_result not in repr(verification)
    assert raw_result not in repr(session.graph())
    with runtime.store._pool.checkout() as connection:
        columns = {
            str(row[1])
            for row in connection.execute(
                "pragma table_info(reasoning_verification)"
            ).fetchall()
        }
        assert "result" not in columns
        assert {"result_sha256", "result_length"} <= columns


def test_failed_stale_cross_run_and_forked_checks_cannot_finalize(
    runtime: SeamRuntime,
) -> None:
    sdk = SeamSDK(runtime=runtime)
    first = sdk.start_reasoning("First run.")
    second = sdk.start_reasoning("Second run.")
    subject_id = _subject(first)
    failed = first.verify(
        subject_id,
        check_kind="review",
        check_ref="operator-review",
        verdict="failed",
        summary="The first review failed.",
    )
    with pytest.raises(ValueError, match="current passed"):
        first.finalize_verified(
            "Invalid failed outcome.",
            verification_ids=[str(failed["verification_id"])],
        )
    passed = first.verify(
        subject_id,
        check_kind="review",
        check_ref="operator-review",
        verdict="passed",
        summary="The retry passed.",
        retry_of=str(failed["verification_id"]),
    )
    with pytest.raises(ValueError, match="current passed"):
        first.finalize_verified(
            "Invalid stale outcome.",
            verification_ids=[str(failed["verification_id"])],
        )
    with pytest.raises(ValueError, match="does not belong"):
        second.finalize_verified(
            "Invalid cross-run outcome.",
            verification_ids=[str(passed["verification_id"])],
        )
    with pytest.raises(ValueError, match="already has a retry"):
        first.verify(
            subject_id,
            check_kind="review",
            check_ref="operator-review",
            verdict="error",
            summary="A retry fork must be rejected.",
            retry_of=str(failed["verification_id"]),
        )


def test_verified_finalization_is_atomic_on_error(runtime: SeamRuntime) -> None:
    session = SeamSDK(runtime=runtime).start_reasoning("Finalize atomically.")
    subject_id = _subject(session)
    passed = session.verify(
        subject_id,
        check_kind="test",
        check_ref="atomic-check",
        verdict="passed",
        summary="The atomic check passed.",
    )
    before = session.graph()

    with pytest.raises(KeyError, match="verification not found"):
        session.finalize_verified(
            "This outcome must roll back.",
            verification_ids=[str(passed["verification_id"]), "verify:missing"],
        )

    after = session.graph()
    assert after["nodes"] == before["nodes"]
    assert after["edges"] == before["edges"]


def test_verification_isolation_evidence_and_append_only_guards(
    runtime: SeamRuntime,
) -> None:
    knowledge_id, raw_id = _seed_evidence(runtime, ns="alpha")
    session = SeamSDK(runtime=runtime).start_reasoning(
        "Respect evidence boundaries.", ns="beta", scope="thread"
    )
    subject_id = _subject(session)

    with pytest.raises(ValueError, match="crosses namespace or scope"):
        session.verify(
            subject_id,
            check_kind="challenge",
            check_ref="knowledge-boundary",
            verdict="contradicted",
            summary="This evidence belongs to another namespace.",
            knowledge_refs=[knowledge_id],
        )
    with pytest.raises(ValueError, match="crosses namespace or scope"):
        session.verify(
            subject_id,
            check_kind="challenge",
            check_ref="evidence-boundary",
            verdict="contradicted",
            summary="This source belongs to another namespace.",
            evidence_refs=[raw_id],
        )

    verification = session.verify(
        subject_id,
        check_kind="test",
        check_ref="append-only-check",
        verdict="passed",
        summary="The local check passed.",
    )
    with runtime.store._pool.checkout() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "update reasoning_verification set verdict = 'failed' "
                "where verification_id = ?",
                (verification["verification_id"],),
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "delete from reasoning_verification where verification_id = ?",
                (verification["verification_id"],),
            )
        connection.rollback()


def test_verification_inputs_and_reads_are_bounded(runtime: SeamRuntime) -> None:
    session = SeamSDK(runtime=runtime).start_reasoning("Bound verification input.")
    subject_id = _subject(session)

    with pytest.raises(ValueError, match="at most 256 references"):
        session.verify(
            subject_id,
            check_kind="test",
            check_ref="bounded-evidence",
            verdict="error",
            summary="Reject an unbounded reference iterator.",
            evidence_refs=itertools.repeat("raw:missing"),
        )
    parameters = set(inspect.signature(ReasoningSession.verify).parameters)
    assert not parameters & {
        "command",
        "raw_log",
        "tool_payload",
        "provider_response",
        "chain_of_thought",
    }
    with pytest.raises(ValueError, match="between 1 and 100"):
        session.verifications(limit=101)


def test_retry_requires_same_subject_and_check_identity(runtime: SeamRuntime) -> None:
    session = SeamSDK(runtime=runtime).start_reasoning("Keep retry identity stable.")
    first_subject = _subject(session)
    second_subject = _subject(session)
    failed = session.verify(
        first_subject,
        check_kind="test",
        check_ref="stable-check",
        verdict="failed",
        summary="The first attempt failed.",
    )

    with pytest.raises(ValueError, match="same subject and check identity"):
        session.verify(
            second_subject,
            check_kind="test",
            check_ref="stable-check",
            verdict="passed",
            summary="A different subject is not a retry.",
            retry_of=str(failed["verification_id"]),
        )
    with pytest.raises(ValueError, match="same subject and check identity"):
        session.verify(
            first_subject,
            check_kind="tool",
            check_ref="stable-check",
            verdict="passed",
            summary="A different check kind is not a retry.",
            retry_of=str(failed["verification_id"]),
        )
