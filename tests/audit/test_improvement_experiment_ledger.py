from __future__ import annotations

import sqlite3
from contextlib import closing

import pytest

from seam_runtime.improvement_experiments import json_sha256
from seam_runtime.migrations import DatabaseIntegrityError, MigrationError
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.retrieval import RetrievalFlags, load_retrieval_flags
from seam_runtime.self_improve import RatchetGateEvidence, ScoreReport
from seam_runtime.storage import SQLiteStore
from tools.h2.improvement_loop import run_improvement_cycle


def _definition() -> dict[str, object]:
    return {
        "baseline_flags_sha256": json_sha256({}),
        "budget": {"max_candidates": 4},
        "candidate_space": [],
        "evaluator": {"version": "test/1"},
        "method": "bounded-autoresearch/1",
    }


def _create_experiment(store: SQLiteStore, experiment_id: str = "improve:test") -> str:
    return store.create_improvement_experiment(
        lane="retrieval-policy",
        evaluator_sha256=json_sha256({"evaluator": "test/1"}),
        dataset_sha256=json_sha256(["case:1"]),
        baseline_sha256=json_sha256({}),
        definition=_definition(),
        experiment_id=experiment_id,
    )


def _passing_non_evaluation_gates() -> list[RatchetGateEvidence]:
    return [
        RatchetGateEvidence(
            name=f"{family}:verified",
            family=family,
            passed=True,
            refs=(f"case:{family}",),
        )
        for family in ("integrity", "trust", "temporal", "provenance", "holdout")
    ]


def test_experiment_ledger_is_hash_chained_append_only_and_terminal(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "experiment.db")
    experiment_id = _create_experiment(store)
    store.append_improvement_experiment_event(
        experiment_id=experiment_id,
        event_kind="baseline_evaluated",
        payload={"reports": {"self_probe": {"aggregate": 0.5, "n": 1}}},
    )
    store.append_improvement_experiment_event(
        experiment_id=experiment_id,
        event_kind="candidate_evaluated",
        payload={
            "candidate": {"flags_sha256": json_sha256({"w_graph": 1.1})},
            "evaluation": {"is_improvement": False},
        },
    )
    store.append_improvement_experiment_event(
        experiment_id=experiment_id,
        event_kind="completed",
        payload={"outcome": "no_change", "proposal_id": None},
    )

    experiment = store.read_improvement_experiment(experiment_id)
    assert experiment is not None
    assert experiment["status"] == "completed"
    assert [event["sequence"] for event in experiment["events"]] == [1, 2, 3, 4]
    assert store.verify_improvement_experiment(experiment_id) == {
        "experiment_id": experiment_id,
        "valid": True,
        "event_count": 4,
        "status": "completed",
        "errors": [],
    }
    assert store.verify_improvement_experiment("improve:missing") == {
        "experiment_id": "improve:missing",
        "valid": False,
        "event_count": 0,
        "status": "invalid",
        "errors": ["experiment does not exist"],
    }
    with pytest.raises(ValueError, match="terminal event"):
        store.append_improvement_experiment_event(
            experiment_id=experiment_id,
            event_kind="failed",
            payload={"error_type": "LateFailure", "phase": "after_completion"},
        )
    with pytest.raises(ValueError, match="forbidden raw-content field"):
        store.create_improvement_experiment(
            lane="retrieval-policy",
            evaluator_sha256=json_sha256({}),
            dataset_sha256=json_sha256({}),
            baseline_sha256=json_sha256({}),
            definition={"query": "do not persist raw evaluator input"},
        )
    with sqlite3.connect(tmp_path / "experiment.db") as connection:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "update improvement_experiment set lane = 'substituted' "
                "where experiment_id = ?",
                (experiment_id,),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute(
                "delete from improvement_experiment_event where experiment_id = ?",
                (experiment_id,),
            )


def test_tampered_experiment_refuses_verification_and_future_events(tmp_path) -> None:
    path = tmp_path / "tampered.db"
    store = SQLiteStore(path)
    experiment_id = _create_experiment(store)
    store.append_improvement_experiment_event(
        experiment_id=experiment_id,
        event_kind="baseline_evaluated",
        payload={"reports": {"self_probe": {"aggregate": 0.5}}},
    )
    with sqlite3.connect(path) as connection:
        connection.execute("drop trigger improvement_experiment_event_no_update")
        connection.execute(
            "update improvement_experiment_event set payload_json = ? where experiment_id = ? and sequence = 2",
            ('{"reports":{"self_probe":{"aggregate":0.9}}}', experiment_id),
        )

    verification = store.verify_improvement_experiment(experiment_id)
    assert verification["valid"] is False
    assert "event 2 hash mismatch" in verification["errors"]
    with pytest.raises(ValueError, match="event chain is invalid"):
        store.append_improvement_experiment_event(
            experiment_id=experiment_id,
            event_kind="completed",
            payload={"outcome": "no_change"},
        )


def test_definition_hash_commits_all_immutable_metadata(tmp_path) -> None:
    path = tmp_path / "definition-tamper.db"
    store = SQLiteStore(path)
    experiment_id = _create_experiment(store)
    with sqlite3.connect(path) as connection:
        connection.execute("drop trigger improvement_experiment_no_update")
        connection.execute(
            "update improvement_experiment set evaluator_sha256 = ? "
            "where experiment_id = ?",
            (json_sha256({"evaluator": "substituted"}), experiment_id),
        )

    verification = store.verify_improvement_experiment(experiment_id)
    assert verification["valid"] is False
    assert "definition hash mismatch" in verification["errors"]
    with pytest.raises(ValueError, match="event chain is invalid"):
        store.append_improvement_experiment_event(
            experiment_id=experiment_id,
            event_kind="failed",
            payload={"error_type": "Tampered", "phase": "verification"},
        )


def test_status_filter_is_applied_before_result_limit(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "status-filter.db")
    failed_id = store.create_improvement_experiment(
        lane="retrieval-policy",
        evaluator_sha256=json_sha256({"evaluator": "test/1"}),
        dataset_sha256=json_sha256(["case:1"]),
        baseline_sha256=json_sha256({}),
        definition=_definition(),
        experiment_id="improve:failed",
        created_at="2026-01-01T00:00:00+00:00",
    )
    store.append_improvement_experiment_event(
        experiment_id=failed_id,
        event_kind="failed",
        payload={"error_type": "ExpectedFailure", "phase": "test"},
        ts="2026-01-01T00:00:01+00:00",
    )
    completed_id = store.create_improvement_experiment(
        lane="retrieval-policy",
        evaluator_sha256=json_sha256({"evaluator": "test/1"}),
        dataset_sha256=json_sha256(["case:2"]),
        baseline_sha256=json_sha256({}),
        definition=_definition(),
        experiment_id="improve:completed",
        created_at="2026-01-02T00:00:00+00:00",
    )
    store.append_improvement_experiment_event(
        experiment_id=completed_id,
        event_kind="baseline_evaluated",
        payload={"reports": {}},
        ts="2026-01-02T00:00:01+00:00",
    )
    store.append_improvement_experiment_event(
        experiment_id=completed_id,
        event_kind="completed",
        payload={"outcome": "no_change"},
        ts="2026-01-02T00:00:02+00:00",
    )

    failed = store.iter_improvement_experiments(status="failed", limit=1)
    assert [item["experiment_id"] for item in failed] == [failed_id]
    with pytest.raises(ValueError, match="experiment status"):
        store.iter_improvement_experiments(status="unknown")


def test_reopened_store_verifies_full_chain_once_then_appends_incrementally(
    tmp_path, monkeypatch
) -> None:
    import seam_runtime.storage as storage_module

    path = tmp_path / "incremental.db"
    initial = SQLiteStore(path)
    experiment_id = _create_experiment(initial)
    initial.close()

    calls = 0
    original = storage_module._improvement_experiment_chain_errors

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(
        storage_module,
        "_improvement_experiment_chain_errors",
        counted,
    )
    reopened = SQLiteStore(path)
    reopened.append_improvement_experiment_event(
        experiment_id=experiment_id,
        event_kind="baseline_evaluated",
        payload={"reports": {}},
    )
    reopened.append_improvement_experiment_event(
        experiment_id=experiment_id,
        event_kind="candidate_evaluated",
        payload={"candidate": {"flags_sha256": json_sha256({})}},
    )
    assert calls == 1


class _ImprovingScorer:
    name = "synthetic"

    def score(self, runtime, flags=None):  # noqa: ARG002
        improved = bool(flags and flags.bm25_all_kinds)
        value = 0.9 if improved else 0.5
        return ScoreReport(
            scorer=self.name,
            aggregate=value,
            n=1,
            per_category={"one": value},
            per_case={"case:dev:1": value},
        )


def test_cycle_rejects_duplicate_scorer_names_before_creating_experiment(
    tmp_path,
) -> None:
    store = SQLiteStore(tmp_path / "duplicate-scorers.db")
    with pytest.raises(ValueError, match="scorer names must be unique"):
        run_improvement_cycle(
            None,
            store,
            [_ImprovingScorer(), _ImprovingScorer()],
        )
    assert store.iter_improvement_experiments() == []


class _ReservedWordIdentifierScorer:
    name = "query"

    def score(self, runtime, flags=None):  # noqa: ARG002
        return ScoreReport(
            scorer=self.name,
            aggregate=0.5,
            n=1,
            per_category={"content": 0.5},
            per_case={"answer": 0.5},
        )


def test_scorer_defined_identifiers_are_values_not_payload_keys(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "identifier-shape.db")
    report = run_improvement_cycle(
        None,
        store,
        [_ReservedWordIdentifierScorer()],
    )

    experiment = store.read_improvement_experiment(report["experiment_id"])
    assert experiment is not None
    baseline = next(
        event
        for event in experiment["events"]
        if event["event_kind"] == "baseline_evaluated"
    )
    [stored_report] = baseline["payload"]["reports"]
    assert stored_report["scorer"] == "query"
    assert stored_report["per_category"] == [
        {"category": "content", "score": 0.5}
    ]
    assert stored_report["per_case"] == [{"case_id": "answer", "score": 0.5}]
    assert store.verify_improvement_experiment(report["experiment_id"])["valid"]


def test_cycle_records_every_candidate_and_links_the_h2_proposal(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "cycle.db")
    report = run_improvement_cycle(
        None,
        store,
        [_ImprovingScorer()],
        ratchet_gates=_passing_non_evaluation_gates(),
        experiment_label="first production-shaped slice",
    )

    experiment = store.read_improvement_experiment(report["experiment_id"])
    assert experiment is not None
    candidate_events = [event for event in experiment["events"] if event["event_kind"] == "candidate_evaluated"]
    assert len(candidate_events) == report["n_candidates"]
    assert any(event["payload"]["candidate"]["change"] == {"bm25_all_kinds": True} for event in candidate_events)
    assert experiment["events"][-2]["event_kind"] == "proposal_created"
    assert experiment["events"][-1]["payload"]["outcome"] == "pending_approval"
    assert store.verify_improvement_experiment(report["experiment_id"])["valid"]

    [proposal] = store.iter_improvement_proposals()
    assert proposal["extra"]["experiment_id"] == report["experiment_id"]
    assert proposal["evidence_case_ids"] == ["case:dev:1"]
    assert load_retrieval_flags(store, env={}) == RetrievalFlags()
    assert report["candidate_space_truncated"] is False


def test_cycle_reports_explicit_candidate_truncation(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "truncated.db")
    report = run_improvement_cycle(
        None,
        store,
        [_ImprovingScorer()],
        max_candidates=1,
    )

    assert report["n_candidates"] == 1
    assert report["candidate_space_count"] > 1
    assert report["candidate_space_truncated"] is True
    experiment = store.read_improvement_experiment(report["experiment_id"])
    assert experiment is not None
    assert experiment["definition"]["budget"]["truncated"] is True


class _FailingCandidateScorer:
    name = "failing"

    def score(self, runtime, flags=None):  # noqa: ARG002
        if flags != RetrievalFlags():
            raise RuntimeError("private evaluator detail must not enter the ledger")
        return ScoreReport(self.name, 0.5, 1, per_case={"case:1": 0.5})


def test_baseline_evidence_write_failure_is_terminal(tmp_path, monkeypatch) -> None:
    store = SQLiteStore(tmp_path / "failed-baseline-evidence.db")
    experiment_id = "improve:baseline-evidence-failure"
    original_append = store.append_improvement_experiment_event

    def fail_baseline_evidence(*, event_kind, **kwargs):
        if event_kind == "baseline_evaluated":
            raise RuntimeError("simulated evidence write failure")
        return original_append(event_kind=event_kind, **kwargs)

    monkeypatch.setattr(
        store,
        "append_improvement_experiment_event",
        fail_baseline_evidence,
    )
    with pytest.raises(RuntimeError, match="simulated evidence write failure"):
        run_improvement_cycle(
            None,
            store,
            [_ImprovingScorer()],
            experiment_id=experiment_id,
        )

    experiment = store.read_improvement_experiment(experiment_id)
    assert experiment is not None
    assert experiment["status"] == "failed"
    assert experiment["events"][-1]["payload"] == {
        "error_type": "RuntimeError",
        "phase": "baseline_evidence",
    }


def test_cycle_failure_is_durable_without_persisting_exception_text(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "failed.db")
    experiment_id = "improve:known-failure"
    with pytest.raises(RuntimeError, match="private evaluator detail"):
        run_improvement_cycle(
            None,
            store,
            [_FailingCandidateScorer()],
            experiment_id=experiment_id,
        )

    experiment = store.read_improvement_experiment(experiment_id)
    assert experiment is not None
    assert experiment["status"] == "failed"
    failed = experiment["events"][-1]
    assert failed["payload"] == {
        "error_type": "RuntimeError",
        "phase": "candidate_evaluation",
    }
    assert "private evaluator detail" not in str(experiment)
    assert store.verify_improvement_experiment(experiment_id)["valid"]


class _FailingRatchetScorer(_ImprovingScorer):
    def ratchet_gates(self, runtime, baseline, candidate, *, regress_tol):  # noqa: ARG002
        raise RuntimeError("private gate detail must not enter the ledger")


def test_cycle_ratchet_failure_is_terminal_and_content_free(tmp_path) -> None:
    store = SQLiteStore(tmp_path / "failed-ratchet.db")
    experiment_id = "improve:ratchet-failure"
    with pytest.raises(RuntimeError, match="private gate detail"):
        run_improvement_cycle(
            None,
            store,
            [_FailingRatchetScorer()],
            experiment_id=experiment_id,
        )

    experiment = store.read_improvement_experiment(experiment_id)
    assert experiment is not None
    assert experiment["status"] == "failed"
    assert experiment["events"][-1]["payload"] == {
        "error_type": "RuntimeError",
        "phase": "ratchet_evaluation",
    }
    assert "private gate detail" not in str(experiment)
    assert store.verify_improvement_experiment(experiment_id)["valid"]


def test_core_storage_two_migrates_to_experiment_ledger(tmp_path) -> None:
    path = tmp_path / "core-two.db"
    store = SQLiteStore(path)
    store.close()
    with sqlite3.connect(path) as connection:
        connection.execute("drop table public_memory_handle")
        connection.execute("drop table improvement_experiment_event")
        connection.execute("drop table improvement_experiment")
        connection.execute(
            "update seam_projection_versions set projection_version = 'core-storage/2' "
            "where projection_name = 'core_storage'"
        )

    migrated = SQLiteStore(path)
    assert migrated.migration_result.applied_steps == (
        "append-only-improvement-experiment-ledger",
        "indexed-public-memory-handles",
    )
    assert migrated.iter_improvement_experiments() == []
    with sqlite3.connect(path) as connection:
        version = connection.execute(
            "select projection_version from seam_projection_versions where projection_name = 'core_storage'"
        ).fetchone()[0]
    assert version == "core-storage/4"


def test_core_storage_three_migrates_to_indexed_public_handles(tmp_path) -> None:
    path = tmp_path / "core-three.db"
    store = SQLiteStore(path)
    store.close()
    with sqlite3.connect(path) as connection:
        connection.execute("drop table public_memory_handle")
        connection.execute(
            "update seam_projection_versions set projection_version = 'core-storage/3' "
            "where projection_name = 'core_storage'"
        )

    migrated = SQLiteStore(path)
    try:
        assert migrated.migration_result.applied_steps == (
            "indexed-public-memory-handles",
        )
        with sqlite3.connect(path) as connection:
            version = connection.execute(
                "select projection_version from seam_projection_versions "
                "where projection_name = 'core_storage'"
            ).fetchone()[0]
            assert version == "core-storage/4"
            assert connection.execute(
                "select 1 from sqlite_master where type = 'table' "
                "and name = 'public_memory_handle'"
            ).fetchone() == (1,)
    finally:
        migrated.close()


def test_populated_core_storage_three_migration_preserves_existing_rows(
    tmp_path,
) -> None:
    path = tmp_path / "populated-core-three.db"
    store = SQLiteStore(path)
    try:
        store.persist_ir(
            IRBatch(
                [
                    MIRLRecord(
                        id="raw:migration-witness",
                        kind=RecordKind.RAW,
                        ns="migration",
                        scope="preservation",
                        attrs={
                            "content": "Ada reviews the migration with Grace.",
                            "media_type": "text/plain",
                        },
                    ),
                    MIRLRecord(
                        id="span:migration-witness",
                        kind=RecordKind.SPAN,
                        ns="migration",
                        scope="preservation",
                        attrs={
                            "raw_id": "raw:migration-witness",
                            "start": 0,
                            "end": 3,
                        },
                    ),
                    MIRLRecord(
                        id="prov:migration-witness",
                        kind=RecordKind.PROV,
                        ns="migration",
                        scope="preservation",
                        attrs={
                            "entity": "raw:migration-witness",
                            "activity": "migration-regression-fixture",
                        },
                    ),
                    MIRLRecord(
                        id="ent:migration-ada",
                        kind=RecordKind.ENT,
                        ns="migration",
                        scope="preservation",
                        attrs={"label": "Ada", "entity_type": "person"},
                    ),
                    MIRLRecord(
                        id="ent:migration-grace",
                        kind=RecordKind.ENT,
                        ns="migration",
                        scope="preservation",
                        attrs={"label": "Grace", "entity_type": "person"},
                    ),
                    MIRLRecord(
                        id="rel:migration-review",
                        kind=RecordKind.REL,
                        ns="migration",
                        scope="preservation",
                        prov=["prov:migration-witness"],
                        evidence=["span:migration-witness"],
                        attrs={
                            "src": "ent:migration-ada",
                            "predicate": "reviews_with",
                            "dst": "ent:migration-grace",
                        },
                    ),
                ]
            )
        )
    finally:
        store.close()

    preserved_tables = (
        "raw_docs",
        "raw_spans",
        "ir_records",
        "ir_edges",
        "ir_edge_sources",
        "prov_log",
        "knowledge_nodes",
        "knowledge_edges",
        "knowledge_node_terms",
    )
    with closing(sqlite3.connect(path)) as connection:
        before = {
            table: connection.execute(
                f'select * from "{table}" order by rowid'
            ).fetchall()
            for table in preserved_tables
        }
        assert all(before.values())
        connection.execute("drop table public_memory_handle")
        connection.execute(
            "update seam_projection_versions set projection_version = 'core-storage/3' "
            "where projection_name = 'core_storage'"
        )
        connection.commit()

    migrated = SQLiteStore(path)
    try:
        assert migrated.migration_result.applied_steps == (
            "indexed-public-memory-handles",
        )
    finally:
        migrated.close()

    with closing(sqlite3.connect(path)) as connection:
        after = {
            table: connection.execute(
                f'select * from "{table}" order by rowid'
            ).fetchall()
            for table in preserved_tables
        }
        assert after == before
        assert connection.execute(
            "select count(*) from public_memory_handle"
        ).fetchone() == (0,)
        assert connection.execute(
            "select projection_version from seam_projection_versions "
            "where projection_name = 'core_storage'"
        ).fetchone() == ("core-storage/4",)


def test_public_handle_projection_migration_rolls_back_atomically(tmp_path) -> None:
    path = tmp_path / "core-three-rollback.db"
    store = SQLiteStore(path)
    store.close()
    with sqlite3.connect(path) as connection:
        connection.execute("drop table public_memory_handle")
        connection.execute(
            "update seam_projection_versions set projection_version = 'core-storage/3' "
            "where projection_name = 'core_storage'"
        )

    def fail_after_handle_step(step, _connection) -> None:
        if step.name == "indexed-public-memory-handles":
            raise RuntimeError("injected handle migration failure")

    with pytest.raises(MigrationError, match="rolled back"):
        SQLiteStore(path, _migration_failure_injector=fail_after_handle_step)

    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "select projection_version from seam_projection_versions "
            "where projection_name = 'core_storage'"
        ).fetchone()[0] == "core-storage/3"
        assert connection.execute(
            "select 1 from sqlite_master where type = 'table' "
            "and name = 'public_memory_handle'"
        ).fetchone() is None

    resumed = SQLiteStore(path)
    try:
        assert resumed.migration_result.applied_steps == (
            "indexed-public-memory-handles",
        )
    finally:
        resumed.close()


def test_core_storage_two_refuses_preexisting_experiment_table(tmp_path) -> None:
    path = tmp_path / "core-two-conflict.db"
    store = SQLiteStore(path)
    store.close()
    with sqlite3.connect(path) as connection:
        connection.execute("drop table public_memory_handle")
        connection.execute("drop table improvement_experiment_event")
        connection.execute("drop table improvement_experiment")
        connection.execute("create table improvement_experiment (unexpected text)")
        connection.execute(
            "update seam_projection_versions set projection_version = 'core-storage/2' "
            "where projection_name = 'core_storage'"
        )

    before_bytes = path.read_bytes()
    backup_dir = tmp_path / "unexpected-partial-backups"
    with pytest.raises(DatabaseIntegrityError, match="target tables"):
        SQLiteStore(path, _migration_backup_dir=backup_dir)
    assert path.read_bytes() == before_bytes
    assert not backup_dir.exists()
    with sqlite3.connect(path) as connection:
        version = connection.execute(
            "select projection_version from seam_projection_versions "
            "where projection_name = 'core_storage'"
        ).fetchone()[0]
    assert version == "core-storage/2"


def test_core_storage_two_refuses_incompatible_complete_table_pair(tmp_path) -> None:
    path = tmp_path / "core-two-incompatible.db"
    store = SQLiteStore(path)
    store.close()
    with sqlite3.connect(path) as connection:
        connection.execute("drop table public_memory_handle")
        connection.execute("drop table improvement_experiment_event")
        connection.execute("drop table improvement_experiment")
        connection.execute("create table improvement_experiment (unexpected text)")
        connection.execute(
            "create table improvement_experiment_event (unexpected text)"
        )
        connection.execute(
            "update seam_projection_versions set projection_version = 'core-storage/2' "
            "where projection_name = 'core_storage'"
        )

    before_bytes = path.read_bytes()
    backup_dir = tmp_path / "unexpected-incompatible-backups"
    with pytest.raises(DatabaseIntegrityError, match="target tables"):
        SQLiteStore(path, _migration_backup_dir=backup_dir)
    assert path.read_bytes() == before_bytes
    assert not backup_dir.exists()
