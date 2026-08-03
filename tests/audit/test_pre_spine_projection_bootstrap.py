"""Regression coverage for guarded projection work during the v0 bootstrap."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path

import pytest

import seam_runtime.migrations as migration_module
from seam_runtime.migrations import (
    MIGRATION_TABLE,
    PROJECTION_TABLE,
    KnowledgeGraphProjectionVersionError,
    MigrationError,
    ProjectionMigration,
    UnsupportedDatabaseVersionError,
)
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind, Status
from seam_runtime.storage import STORE_PROJECTION_VERSIONS, SQLiteStore

SUBJECT_ID = "ent:pre-spine-subject"
OBJECT_ID = "ent:pre-spine-object"
DELETED_ID = "ent:pre-spine-deleted"
RELATION_ID = "rel:pre-spine-link"
PHANTOM_ID = "ent:pre-spine-phantom"


def _table_hashes(path: Path) -> dict[str, str]:
    with closing(sqlite3.connect(path)) as connection:
        tables = [
            str(row[0])
            for row in connection.execute(
                "select name from sqlite_master where type = 'table' "
                "and name not like 'sqlite_%' order by name"
            )
        ]
        hashes: dict[str, str] = {}
        for table in tables:
            schema = connection.execute(
                "select sql from sqlite_master where type = 'table' and name = ?",
                (table,),
            ).fetchone()
            rows = connection.execute(
                f'select * from "{table}" order by rowid'
            ).fetchall()
            payload = json.dumps(
                {"schema": schema[0], "rows": rows},
                sort_keys=True,
                separators=(",", ":"),
            )
            hashes[table] = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return hashes


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "select name from sqlite_master where type = 'table' "
            "and name not like 'sqlite_%'"
        )
    }


def _build_pre_spine_kg4_fixture(path: Path) -> None:
    store = SQLiteStore(path)
    try:
        store.persist_ir(
            IRBatch(
                [
                    MIRLRecord(
                        id=SUBJECT_ID,
                        kind=RecordKind.ENT,
                        attrs={"label": "Pre-spine subject", "entity_type": "thing"},
                    ),
                    MIRLRecord(
                        id=OBJECT_ID,
                        kind=RecordKind.ENT,
                        attrs={"label": "Pre-spine object", "entity_type": "thing"},
                    ),
                    MIRLRecord(
                        id=DELETED_ID,
                        kind=RecordKind.ENT,
                        attrs={"label": "Pre-spine deleted", "entity_type": "thing"},
                    ),
                    MIRLRecord(
                        id=RELATION_ID,
                        kind=RecordKind.REL,
                        attrs={
                            "src": SUBJECT_ID,
                            "predicate": "linked_to",
                            "dst": OBJECT_ID,
                        },
                    ),
                ]
            )
        )
    finally:
        store.close()

    with closing(sqlite3.connect(path)) as connection:
        connection.execute("pragma journal_mode=delete")
        connection.execute("pragma foreign_keys=off")

        deleted_payload = json.loads(
            str(
                connection.execute(
                    "select payload_json from ir_records where id = ?",
                    (DELETED_ID,),
                ).fetchone()[0]
            )
        )
        deleted_payload["status"] = Status.DELETED_SOFT.value
        connection.execute(
            "update ir_records set status = ?, payload_json = ? where id = ?",
            (
                Status.DELETED_SOFT.value,
                json.dumps(deleted_payload, sort_keys=True, separators=(",", ":")),
                DELETED_ID,
            ),
        )

        connection.execute(
            "insert into knowledge_nodes "
            "(id, kind, label, ns, scope, status, confidence, valid_from, "
            "valid_to, created_at, updated_at, agent_id, source_record_id, "
            "synthetic, properties_json) "
            "select ?, kind, 'pre-spine phantom', ns, scope, status, confidence, "
            "valid_from, valid_to, created_at, updated_at, agent_id, ?, synthetic, "
            "properties_json from knowledge_nodes where id = ?",
            (PHANTOM_ID, PHANTOM_ID, SUBJECT_ID),
        )
        connection.execute(
            "update knowledge_graph_meta set value = 'knowledge-graph/4' "
            "where key = 'projection_version'"
        )

        connection.execute("drop table ir_edge_sources")
        connection.execute("drop index if exists idx_ir_edges_src")
        connection.execute("drop index if exists idx_ir_edges_dst")
        connection.execute("drop index if exists idx_ir_edges_unique")
        connection.execute("alter table ir_edges rename to ir_edges_typed")
        connection.execute(
            "create table ir_edges ("
            "id integer primary key autoincrement, "
            "src_id text not null, "
            "edge_type text not null, "
            "dst_id text not null)"
        )
        connection.execute(
            "insert into ir_edges (id, src_id, edge_type, dst_id) "
            "select id, src_id, edge_type, dst_id from ir_edges_typed"
        )
        connection.execute("drop table ir_edges_typed")
        connection.execute(f"drop table {PROJECTION_TABLE}")
        connection.execute(f"drop table {MIGRATION_TABLE}")
        connection.commit()

        assert "ir_edge_sources" not in _tables(connection)
        assert {
            str(row[1]) for row in connection.execute("pragma table_info(ir_edges)")
        } == {"id", "src_id", "edge_type", "dst_id"}
        assert connection.execute("pragma foreign_key_check").fetchall() == []


def _instrument_graph_chain(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_after: tuple[str, str] | None = None,
) -> tuple[
    tuple[ProjectionMigration, ...],
    list[tuple[str, str]],
]:
    original = tuple(migration_module.PROJECTION_MIGRATIONS)
    observed: list[tuple[str, str]] = []
    instrumented: list[ProjectionMigration] = []
    for migration in original:
        if migration.projection_name != "knowledge_graph":
            instrumented.append(migration)
            continue

        def observed_upgrade(
            connection,
            *,
            registered: ProjectionMigration = migration,
        ) -> None:
            transition = (registered.from_version, registered.to_version)
            observed.append(transition)
            registered.upgrade(connection)
            if transition == fail_after:
                raise RuntimeError("injected pre-spine projection failure")

        instrumented.append(replace(migration, upgrade=observed_upgrade))
    monkeypatch.setattr(
        migration_module,
        "PROJECTION_MIGRATIONS",
        tuple(instrumented),
    )
    return original, observed


def test_pre_spine_kg4_bootstrap_runs_both_registered_graph_transitions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "pre-spine-kg4.sqlite3"
    _build_pre_spine_kg4_fixture(path)
    _, observed = _instrument_graph_chain(monkeypatch)

    store = SQLiteStore(path)
    try:
        assert observed == [
            ("knowledge-graph/4", "knowledge-graph/5"),
            ("knowledge-graph/5", "knowledge-graph/6"),
        ]
        assert store.migration_result.initial_version == 0
        assert store.migration_result.applied_steps == (
            "initialize-versioned-core",
            "register-durable-projections",
        )
        assert store.migration_result.backup_path is not None
        with store._pool.checkout() as connection:
            projection_versions = {
                str(row[0]): str(row[1])
                for row in connection.execute(
                    f"select projection_name, projection_version from {PROJECTION_TABLE}"
                )
            }
            assert projection_versions == STORE_PROJECTION_VERSIONS
            assert connection.execute(
                "select value from knowledge_graph_meta "
                "where key = 'projection_version'"
            ).fetchone()[0] == "knowledge-graph/6"
            assert connection.execute(
                "select count(*) from knowledge_nodes where id = ?",
                (PHANTOM_ID,),
            ).fetchone()[0] == 0
            assert connection.execute(
                "select count(*) from knowledge_nodes where id = ?",
                (DELETED_ID,),
            ).fetchone()[0] == 0
            assert connection.execute(
                "select count(*) from knowledge_nodes where id in (?, ?)",
                (SUBJECT_ID, OBJECT_ID),
            ).fetchone()[0] == 2
            edge = connection.execute(
                "select src_ref_type, dst_ref_type from ir_edges "
                "where src_id = ? and edge_type = 'linked_to' and dst_id = ?",
                (SUBJECT_ID, OBJECT_ID),
            ).fetchone()
            assert tuple(edge) == ("ENT", "ENT")
            assert connection.execute(
                "select count(*) from ir_edge_sources "
                "where source_record_id = ? and src_id = ? "
                "and edge_type = 'linked_to' and dst_id = ?",
                (RELATION_ID, SUBJECT_ID, OBJECT_ID),
            ).fetchone()[0] == 1
            assert connection.execute("pragma foreign_key_check").fetchall() == []
    finally:
        store.close()


def test_pre_spine_projection_failure_rolls_back_whole_bootstrap_and_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "pre-spine-rollback.sqlite3"
    backup_dir = tmp_path / "backups"
    _build_pre_spine_kg4_fixture(path)
    before = _table_hashes(path)
    original, observed = _instrument_graph_chain(
        monkeypatch,
        fail_after=("knowledge-graph/5", "knowledge-graph/6"),
    )

    with pytest.raises(MigrationError, match="rolled back") as exc_info:
        SQLiteStore(
            path,
            _migration_backup_dir=backup_dir,
        )
    assert observed == [
        ("knowledge-graph/4", "knowledge-graph/5"),
        ("knowledge-graph/5", "knowledge-graph/6"),
    ]
    assert exc_info.value.backup_path is not None
    assert exc_info.value.backup_path.is_file()
    assert _table_hashes(path) == before
    with closing(sqlite3.connect(path)) as connection:
        assert MIGRATION_TABLE not in _tables(connection)
        assert PROJECTION_TABLE not in _tables(connection)
        assert "ir_edge_sources" not in _tables(connection)
        assert connection.execute(
            "select value from knowledge_graph_meta where key = 'projection_version'"
        ).fetchone()[0] == "knowledge-graph/4"
        assert connection.execute(
            "select count(*) from knowledge_nodes where id = ?",
            (PHANTOM_ID,),
        ).fetchone()[0] == 1

    monkeypatch.setattr(migration_module, "PROJECTION_MIGRATIONS", original)
    resumed = SQLiteStore(path, _migration_backup_dir=backup_dir)
    try:
        assert resumed.migration_result.initial_version == 0
        assert resumed.migration_result.applied_steps == (
            "initialize-versioned-core",
            "register-durable-projections",
        )
        with resumed._pool.checkout() as connection:
            assert connection.execute(
                "select value from knowledge_graph_meta "
                "where key = 'projection_version'"
            ).fetchone()[0] == "knowledge-graph/6"
            assert connection.execute(
                "select count(*) from knowledge_nodes where id = ?",
                (PHANTOM_ID,),
            ).fetchone()[0] == 0
    finally:
        resumed.close()


def test_pre_spine_hybrid_projection_registry_refuses_before_backup_or_mutation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pre-spine-hybrid-projection-registry.sqlite3"
    backup_dir = tmp_path / "backups"
    _build_pre_spine_kg4_fixture(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            f"create table {PROJECTION_TABLE} ("
            "projection_name text primary key, projection_version text not null)"
        )
        hybrid_versions = dict(STORE_PROJECTION_VERSIONS)
        hybrid_versions["core_storage"] = "core-storage/1"
        hybrid_versions["knowledge_graph"] = "knowledge-graph/4"
        connection.executemany(
            f"insert into {PROJECTION_TABLE} "
            "(projection_name, projection_version) values (?, ?)",
            sorted(hybrid_versions.items()),
        )
        connection.commit()

    before_bytes = path.read_bytes()
    before_hashes = _table_hashes(path)
    with pytest.raises(
        UnsupportedDatabaseVersionError,
        match="projection-version registry without its central migration registry",
    ):
        SQLiteStore(path, _migration_backup_dir=backup_dir)

    assert path.read_bytes() == before_bytes
    assert _table_hashes(path) == before_hashes
    assert not backup_dir.exists()
    with closing(sqlite3.connect(path)) as connection:
        assert MIGRATION_TABLE not in _tables(connection)
        assert PROJECTION_TABLE in _tables(connection)
        assert connection.execute(
            "select value from knowledge_graph_meta "
            "where key = 'projection_version'"
        ).fetchone()[0] == "knowledge-graph/4"


@pytest.mark.parametrize(
    "marker",
    ["knowledge-graph/3", "knowledge-graph/999", "ordinary-marker"],
)
def test_pre_spine_unsupported_graph_marker_refuses_before_backup(
    tmp_path: Path,
    marker: str,
) -> None:
    path = tmp_path / f"unsupported-{marker.replace('/', '-')}.sqlite3"
    backup_dir = tmp_path / "backups"
    _build_pre_spine_kg4_fixture(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "update knowledge_graph_meta set value = ? "
            "where key = 'projection_version'",
            (marker,),
        )
        connection.commit()
    before_bytes = path.read_bytes()
    before_hashes = _table_hashes(path)

    with pytest.raises(
        KnowledgeGraphProjectionVersionError,
        match="Unsupported knowledge graph projection version",
    ):
        SQLiteStore(path, _migration_backup_dir=backup_dir)

    assert path.read_bytes() == before_bytes
    assert _table_hashes(path) == before_hashes
    assert not backup_dir.exists()
