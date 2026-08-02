from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from seam_runtime.knowledge_graph import rebuild_knowledge_graph_from_canonical
from seam_runtime.migrations import (
    DatabaseIntegrityError,
    KnowledgeGraphProjectionVersionError,
    MigrationError,
    UnsupportedDatabaseVersionError,
)
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.runtime import SeamRuntime
from seam_runtime.storage import SQLiteStore

REBUILD_STEP = "rebuild-knowledge-graph-4-to-5-from-canonical"
RELEVANT_TABLES = (
    "document_status",
    "ir_records",
    "seam_projection_versions",
    "knowledge_graph_meta",
    "knowledge_nodes",
    "knowledge_edges",
    "knowledge_episodes",
    "knowledge_node_episodes",
    "knowledge_edge_episodes",
    "knowledge_node_terms",
    "knowledge_node_vectors",
    "identity_merges",
    "identity_merge_evidence",
)


def _table_hashes(path: Path) -> dict[str, str]:
    with closing(sqlite3.connect(path)) as connection:
        hashes: dict[str, str] = {}
        for table in RELEVANT_TABLES:
            schema = connection.execute(
                "select sql from sqlite_master where type = 'table' and name = ?",
                (table,),
            ).fetchone()
            rows = (
                connection.execute(f'select * from "{table}" order by rowid').fetchall()
                if schema is not None
                else []
            )
            payload = json.dumps(
                {"schema": schema[0] if schema is not None else None, "rows": rows},
                sort_keys=True,
                separators=(",", ":"),
            )
            hashes[table] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return hashes


def _downgrade_graph_marker(path: Path, version: str = "knowledge-graph/4") -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "update seam_projection_versions set projection_version = ? "
            "where projection_name = 'knowledge_graph'",
            (version,),
        )
        connection.execute(
            "update knowledge_graph_meta set value = ? "
            "where key = 'projection_version'",
            (version,),
        )
        connection.commit()


def _stable_graph_view(payload: dict[str, object]) -> dict[str, object]:
    """Exclude only the response-generation clock from view equivalence."""

    return {key: value for key, value in payload.items() if key != "generated_at"}


def _build_reprojection_fixture(path: Path) -> dict[str, object]:
    runtime = SeamRuntime(path)
    try:
        first = runtime.ingest_text(
            "Alice owns alpha.",
            source_ref="test://s3/evolving",
            ns="tenant-a",
            scope="thread",
            agent_id="codex",
        )
        second = runtime.ingest_text(
            "Alice owns beta.",
            source_ref="test://s3/evolving",
            ns="tenant-a",
            scope="thread",
            agent_id="codex",
        )
        old_raw_id = next(
            record_id for record_id in first.stored_ids if record_id.startswith("raw:")
        )
        active_raw_id = next(
            record_id for record_id in second.stored_ids if record_id.startswith("raw:")
        )

        # One semantic edge has two independent episode supports. Superseding
        # the old document must not expire it while the second episode is live.
        shared = MIRLRecord(
            id="rel:s3-shared-support",
            kind=RecordKind.REL,
            ns="tenant-a",
            scope="thread",
            evidence=[old_raw_id, active_raw_id],
            attrs={
                "src": "ent:s3-alice",
                "predicate": "owns",
                "dst": "ent:s3-shared",
            },
            ext={"agent_id": "codex"},
        )
        runtime.store.persist_ir(IRBatch([shared]))

        lifecycle_record = MIRLRecord(
            id="clm:s3-lifecycle-excluded",
            kind=RecordKind.CLM,
            ns="tenant-a",
            scope="thread",
            attrs={
                "subject": "ent:s3-deleted-only",
                "predicate": "owns",
                "object": "deleted-only-value",
            },
        )
        runtime.store.persist_ir(IRBatch([lifecycle_record]))
        operation = runtime.plan_scoped_delete(
            tenant_id="tenant-a",
            namespace="tenant-a",
            scope="thread",
            record_ids=[lifecycle_record.id],
            idempotency_key="s3-reprojection-lifecycle",
            actor="test",
        )
        applied = runtime.apply_scoped_delete(
            tenant_id="tenant-a",
            operation_id=str(operation["operation_id"]),
            actor="test",
        )
        assert applied["state"] == "applied"

        with runtime.store._pool.checkout() as connection:
            old_episode = connection.execute(
                "select id, recorded_at, expired_at from knowledge_episodes "
                "where source_record_id = ?",
                (old_raw_id,),
            ).fetchone()
            shared_edge = connection.execute(
                "select id, status, expired_at from knowledge_edges "
                "where source_record_id = ? and edge_kind = 'semantic'",
                (shared.id,),
            ).fetchone()
            shared_episode_statuses = connection.execute(
                "select ep.status from knowledge_edge_episodes ee "
                "join knowledge_episodes ep on ep.id = ee.episode_id "
                "where ee.edge_id = ? order by ep.status",
                (shared_edge["id"],),
            ).fetchall()

        at = str(old_episode["recorded_at"])
        views = {
            "current": _stable_graph_view(
                runtime.store.knowledge_graph(
                    namespace="tenant-a", scope="thread", limit=1000
                )
            ),
            "history": _stable_graph_view(
                runtime.store.knowledge_graph(
                    namespace="tenant-a",
                    scope="thread",
                    include_history=True,
                    limit=1000,
                )
            ),
            "at": _stable_graph_view(
                runtime.store.knowledge_graph(
                    root_id=str(old_episode["id"]), at=at, limit=1000
                )
            ),
        }
        return {
            "old_raw_id": old_raw_id,
            "old_episode_id": str(old_episode["id"]),
            "old_expired_at": str(old_episode["expired_at"]),
            "shared_edge_id": str(shared_edge["id"]),
            "shared_edge_state": (str(shared_edge["status"]), shared_edge["expired_at"]),
            "shared_episode_statuses": [str(row[0]) for row in shared_episode_statuses],
            "lifecycle_record_id": lifecycle_record.id,
            "views": views,
        }
    finally:
        runtime.close()


def test_guarded_reprojection_is_history_equivalent_and_has_zero_resurrections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / "s3-equivalence.sqlite3"
    fixture = _build_reprojection_fixture(path)
    _downgrade_graph_marker(path)

    runtime = SeamRuntime(path)
    try:
        assert runtime.store.migration_result.applied_steps == (REBUILD_STEP,)
        after_views = {
            "current": _stable_graph_view(
                runtime.store.knowledge_graph(
                    namespace="tenant-a", scope="thread", limit=1000
                )
            ),
            "history": _stable_graph_view(
                runtime.store.knowledge_graph(
                    namespace="tenant-a",
                    scope="thread",
                    include_history=True,
                    limit=1000,
                )
            ),
            "at": _stable_graph_view(
                runtime.store.knowledge_graph(
                    root_id=str(fixture["old_episode_id"]),
                    at=str(fixture["views"]["at"]["query"]["at"]),
                    limit=1000,
                )
            ),
        }
        assert after_views == fixture["views"]

        with runtime.store._pool.checkout() as connection:
            episodes = connection.execute(
                "select source_record_id, status, expired_at from knowledge_episodes"
            ).fetchall()
            shared_edge = connection.execute(
                "select status, expired_at from knowledge_edges where id = ?",
                (fixture["shared_edge_id"],),
            ).fetchone()
            shared_episode_statuses = connection.execute(
                "select ep.status from knowledge_edge_episodes ee "
                "join knowledge_episodes ep on ep.id = ee.episode_id "
                "where ee.edge_id = ? order by ep.status",
                (fixture["shared_edge_id"],),
            ).fetchall()
            lifecycle_rows = connection.execute(
                "select id from knowledge_nodes where id = ? union all "
                "select source_record_id from knowledge_edges where source_record_id = ?",
                (fixture["lifecycle_record_id"], fixture["lifecycle_record_id"]),
            ).fetchall()

        assert not {
            str(row["source_record_id"])
            for row in episodes
            if row["status"] == "active"
        } & {str(fixture["old_raw_id"])}
        assert tuple(shared_edge) == fixture["shared_edge_state"] == ("asserted", None)
        assert [str(row[0]) for row in shared_episode_statuses] == (
            fixture["shared_episode_statuses"]
        ) == ["active", "superseded"]
        assert lifecycle_rows == []
    finally:
        runtime.close()


def test_reprojection_derives_supersession_from_document_status_not_stale_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / "s3-canonical-source.sqlite3"
    fixture = _build_reprojection_fixture(path)
    with closing(sqlite3.connect(path)) as connection:
        deleted_at = connection.execute(
            "select deleted_at from document_status where document_id = ?",
            ("doc:" + str(fixture["old_raw_id"]).split(":", 2)[1],),
        ).fetchone()[0]
        # Deliberately corrupt only the disposable graph. The rebuild must not
        # carry this active row forward because document_status is authoritative.
        connection.execute(
            "update knowledge_episodes set status = 'active', expired_at = null "
            "where source_record_id = ?",
            (fixture["old_raw_id"],),
        )
        connection.commit()
    _downgrade_graph_marker(path)

    runtime = SeamRuntime(path)
    try:
        with runtime.store._pool.checkout() as connection:
            rebuilt = connection.execute(
                "select status, expired_at from knowledge_episodes "
                "where source_record_id = ?",
                (fixture["old_raw_id"],),
            ).fetchone()
        assert tuple(rebuilt) == ("superseded", deleted_at)
    finally:
        runtime.close()


def test_failed_reprojection_rolls_back_every_relevant_table_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / "s3-failed.sqlite3"
    _build_reprojection_fixture(path)
    _downgrade_graph_marker(path)
    before = _table_hashes(path)

    def fail_after_rebuild(step, _connection) -> None:
        if step.name == REBUILD_STEP:
            raise RuntimeError("injected S3 rebuild failure")

    with pytest.raises(MigrationError, match="rolled back"):
        SQLiteStore(
            path,
            _migration_failure_injector=fail_after_rebuild,
            _migration_backup_dir=tmp_path / "backups",
        )

    assert _table_hashes(path) == before


def test_newer_reprojection_request_refuses_before_any_table_hash_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / "s3-newer.sqlite3"
    _build_reprojection_fixture(path)
    _downgrade_graph_marker(path, "knowledge-graph/999")
    before = _table_hashes(path)

    with pytest.raises(UnsupportedDatabaseVersionError, match="no registered transition"):
        SQLiteStore(path)

    assert _table_hashes(path) == before


@pytest.mark.parametrize("missing_table", ["identity_merges", "identity_merge_evidence"])
def test_reprojection_refuses_missing_identity_ledger_before_any_table_hash_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_table: str,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / f"s3-missing-{missing_table}.sqlite3"
    _build_reprojection_fixture(path)
    _downgrade_graph_marker(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(f'drop table "{missing_table}"')
        connection.commit()
    before = _table_hashes(path)

    with pytest.raises(DatabaseIntegrityError, match=missing_table):
        SQLiteStore(path)

    assert _table_hashes(path) == before


def test_direct_reprojection_refuses_missing_marker_table_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)
    path = tmp_path / "s3-missing-marker.sqlite3"
    _build_reprojection_fixture(path)
    _downgrade_graph_marker(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("drop table knowledge_graph_meta")
        connection.commit()
    before = _table_hashes(path)

    with closing(sqlite3.connect(path)) as connection:
        with pytest.raises(KnowledgeGraphProjectionVersionError, match="found 'missing'"):
            rebuild_knowledge_graph_from_canonical(connection)

    assert _table_hashes(path) == before
