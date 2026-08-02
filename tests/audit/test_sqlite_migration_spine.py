from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest

import seam_runtime.migrations as migration_module
from seam_runtime.knowledge_graph import init_knowledge_graph
from seam_runtime.migrations import (
    CURRENT_SCHEMA_VERSION,
    MIGRATION_TABLE,
    PROJECTION_TABLE,
    MigrationError,
    UnsupportedDatabaseVersionError,
    execute_script,
    migrate_database,
    restore_database_backup,
)
from seam_runtime.storage import STORE_PROJECTION_VERSIONS, SQLiteStore

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "sqlite_history"
HISTORICAL_FIXTURES = {
    "v1_2_0.sql": "ent:legacy-memory",
    "v2_4_0.sql": "ent:released-memory",
}


def _build_fixture(path: Path, fixture_name: str) -> None:
    script = (FIXTURE_DIR / fixture_name).read_text(encoding="utf-8")
    with sqlite3.connect(path) as connection:
        connection.executescript(script)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in connection.execute("select name from sqlite_master where type = 'table'").fetchall()}


def _assert_sqlite_checks(connection: sqlite3.Connection) -> None:
    assert [str(row[0]) for row in connection.execute("pragma integrity_check")] == ["ok"]
    assert connection.execute("pragma foreign_key_check").fetchall() == []


def test_every_maintained_historical_fixture_is_registered() -> None:
    actual = {path.name for path in FIXTURE_DIR.glob("*.sql")}
    assert actual == set(HISTORICAL_FIXTURES)


def test_pregraph_backfill_accepts_default_tuple_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "tuple-rows.db"
    _build_fixture(database_path, "v1_2_0.sql")

    with sqlite3.connect(database_path) as connection:
        assert connection.row_factory is None
        init_knowledge_graph(connection, allow_migration=True)
        assert connection.execute(
            "select count(*) from knowledge_nodes where id = 'ent:legacy-memory'"
        ).fetchone()[0] == 1


def test_transactional_script_preserves_trigger_body_and_ignores_trailing_comment() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute("begin immediate")
        execute_script(
            connection,
            """
            create table guarded (id integer primary key);
            create trigger guarded_no_insert
            before insert on guarded begin
                select raise(abort, 'guarded');
            end;
            -- trailing schema note without another statement
            """,
        )
        assert connection.execute(
            "select count(*) from sqlite_master "
            "where type = 'trigger' and name = 'guarded_no_insert'"
        ).fetchone()[0] == 1
        with pytest.raises(sqlite3.IntegrityError, match="guarded"):
            connection.execute("insert into guarded values (1)")
        connection.rollback()
        assert "guarded" not in _tables(connection)
    finally:
        connection.close()


def test_required_projection_validation_rolls_back_step_one(tmp_path: Path) -> None:
    database_path = tmp_path / "missing-required-table.db"

    with pytest.raises(MigrationError, match="missing tables"):
        migrate_database(
            database_path,
            initialize_schema=lambda connection: None,
            expected_projection_versions={"canonical_mirl": "mirl/0.1"},
        )

    with sqlite3.connect(database_path) as connection:
        assert MIGRATION_TABLE not in _tables(connection)


@pytest.mark.parametrize("fixture_name", sorted(HISTORICAL_FIXTURES))
def test_historical_database_upgrades_preserve_truth_and_pass_checks(
    tmp_path: Path,
    fixture_name: str,
) -> None:
    database_path = tmp_path / f"{fixture_name}.db"
    record_id = HISTORICAL_FIXTURES[fixture_name]
    _build_fixture(database_path, fixture_name)

    store = SQLiteStore(database_path)
    try:
        assert store.migration_result.initial_version == 0
        assert store.migration_result.final_version == CURRENT_SCHEMA_VERSION
        assert store.migration_result.applied_steps == (
            "initialize-versioned-core",
            "register-durable-projections",
        )
        assert store.migration_result.backup_path is not None
        assert store.migration_result.backup_path.is_file()
        with store._pool.checkout() as connection:
            assert connection.execute("select count(*) from ir_records where id = ?", (record_id,)).fetchone()[0] == 1
            versions = connection.execute(f"select version from {MIGRATION_TABLE} order by version").fetchall()
            assert [int(row[0]) for row in versions] == [1, 2]
            projections = {
                str(row[0]): str(row[1])
                for row in connection.execute(
                    f"select projection_name, projection_version from {PROJECTION_TABLE}"
                ).fetchall()
            }
            assert projections == STORE_PROJECTION_VERSIONS
            _assert_sqlite_checks(connection)
            if fixture_name == "v1_2_0.sql":
                vector_columns = {str(row[1]) for row in connection.execute("pragma table_info(vector_index)")}
                assert {"source_hash", "render_version", "namespace", "scope"} <= vector_columns
                assert (
                    connection.execute("select count(*) from knowledge_nodes where id = ?", (record_id,)).fetchone()[0]
                    == 1
                )
    finally:
        store.close()


def test_empty_store_runs_every_step_and_reopens_without_writes(tmp_path: Path) -> None:
    database_path = tmp_path / "empty.db"
    database_path.touch()

    first = SQLiteStore(database_path)
    try:
        assert first.migration_result.initial_version == 0
        assert first.migration_result.final_version == CURRENT_SCHEMA_VERSION
        assert len(first.migration_result.applied_steps) == 2
        with first._pool.checkout() as connection:
            _assert_sqlite_checks(connection)
    finally:
        first.close()

    before = _sha256(database_path)
    second = SQLiteStore(database_path)
    try:
        assert second.migration_result.applied_steps == ()
    finally:
        second.close()
    assert _sha256(database_path) == before


@pytest.mark.parametrize(
    ("failed_step", "expected_version"),
    [
        ("initialize-versioned-core", 0),
        ("register-durable-projections", 1),
    ],
)
def test_failure_after_each_step_rolls_back_that_whole_step(
    tmp_path: Path,
    failed_step: str,
    expected_version: int,
) -> None:
    database_path = tmp_path / f"rollback-{expected_version}.db"
    backup_dir = tmp_path / "backups"
    _build_fixture(database_path, "v2_4_0.sql")

    def fail_after_step(step, connection) -> None:
        if step.name == failed_step:
            raise RuntimeError(f"injected after {step.name}")

    with pytest.raises(MigrationError, match="rolled back") as exc_info:
        SQLiteStore(
            database_path,
            _migration_failure_injector=fail_after_step,
            _migration_backup_dir=backup_dir,
        )
    assert exc_info.value.backup_path is not None
    assert exc_info.value.backup_path.is_file()

    with sqlite3.connect(database_path) as connection:
        tables = _tables(connection)
        if expected_version == 0:
            assert MIGRATION_TABLE not in tables
        else:
            assert connection.execute(f"select max(version) from {MIGRATION_TABLE}").fetchone()[0] == expected_version
        assert PROJECTION_TABLE not in tables
        assert connection.execute("select count(*) from ir_records where id = 'ent:released-memory'").fetchone()[0] == 1
        _assert_sqlite_checks(connection)


def test_integrity_and_foreign_keys_are_checked_after_every_step(tmp_path: Path) -> None:
    database_path = tmp_path / "observed-checks.db"
    observed: list[str] = []

    def observe_step(step, connection) -> None:
        _assert_sqlite_checks(connection)
        observed.append(step.name)

    store = SQLiteStore(database_path, _migration_failure_injector=observe_step)
    try:
        assert observed == [
            "initialize-versioned-core",
            "register-durable-projections",
        ]
    finally:
        store.close()


def test_supported_intermediate_version_resumes_at_the_next_step(tmp_path: Path) -> None:
    database_path = tmp_path / "schema-v1.db"
    _build_fixture(database_path, "v2_4_0.sql")

    def stop_at_v1(step, connection) -> None:
        if step.name == "register-durable-projections":
            raise RuntimeError("leave the committed v1 step in place")

    with pytest.raises(MigrationError):
        SQLiteStore(database_path, _migration_failure_injector=stop_at_v1)

    resumed = SQLiteStore(database_path)
    try:
        assert resumed.migration_result.initial_version == 1
        assert resumed.migration_result.applied_steps == ("register-durable-projections",)
        with resumed._pool.checkout() as connection:
            _assert_sqlite_checks(connection)
    finally:
        resumed.close()


def test_real_pre_migration_backup_restores_then_reupgrades(tmp_path: Path) -> None:
    database_path = tmp_path / "recovery.db"
    backup_dir = tmp_path / "backups"
    _build_fixture(database_path, "v1_2_0.sql")

    migrated = SQLiteStore(database_path, _migration_backup_dir=backup_dir)
    backup_path = migrated.migration_result.backup_path
    assert backup_path is not None
    try:
        with migrated._pool.checkout() as connection:
            connection.execute("delete from ir_records where id = 'ent:legacy-memory'")
            connection.commit()
    finally:
        migrated.close()

    restore_database_backup(database_path, backup_path)
    with sqlite3.connect(database_path) as recovered:
        assert MIGRATION_TABLE not in _tables(recovered)
        assert recovered.execute("select count(*) from ir_records where id = 'ent:legacy-memory'").fetchone()[0] == 1
        _assert_sqlite_checks(recovered)

    reopened = SQLiteStore(database_path, _migration_backup_dir=backup_dir)
    try:
        with reopened._pool.checkout() as connection:
            assert (
                connection.execute("select count(*) from ir_records where id = 'ent:legacy-memory'").fetchone()[0] == 1
            )
            assert (
                connection.execute("select count(*) from knowledge_nodes where id = 'ent:legacy-memory'").fetchone()[0]
                == 1
            )
            _assert_sqlite_checks(connection)
    finally:
        reopened.close()


def test_failed_atomic_restore_leaves_original_and_sidecars_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "restore-target.db"
    backup_path = tmp_path / "valid-backup.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("create table original (id integer primary key)")
    with sqlite3.connect(backup_path) as connection:
        connection.execute("create table recovered (id integer primary key)")
    original_bytes = database_path.read_bytes()
    sidecars = [Path(f"{database_path}{suffix}") for suffix in ("-wal", "-shm", "-journal")]
    for index, sidecar in enumerate(sidecars):
        sidecar.write_bytes(f"sidecar-{index}".encode())

    def fail_replace(source, destination) -> None:
        raise OSError("injected atomic replacement failure")

    monkeypatch.setattr(migration_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="injected atomic replacement failure"):
        restore_database_backup(database_path, backup_path)

    assert database_path.read_bytes() == original_bytes
    assert [sidecar.read_bytes() for sidecar in sidecars] == [
        b"sidecar-0",
        b"sidecar-1",
        b"sidecar-2",
    ]


@pytest.mark.parametrize(
    "case",
    ["unknown", "newer-schema", "newer-projection", "newer-component-marker"],
)
def test_unknown_or_newer_database_refusal_is_byte_unchanged(
    tmp_path: Path,
    case: str,
) -> None:
    database_path = tmp_path / f"{case}.db"
    if case == "unknown":
        with sqlite3.connect(database_path) as connection:
            connection.execute("create table unrelated_product (id integer primary key)")
    elif case == "newer-schema":
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                f"create table {MIGRATION_TABLE} ("
                "version integer primary key, name text not null, "
                "checksum text not null, applied_at text not null)"
            )
            connection.execute(f"insert into {MIGRATION_TABLE} values (999, 'future', 'future', 'future')")
    else:
        current = SQLiteStore(database_path)
        try:
            with current._pool.checkout() as connection:
                if case == "newer-projection":
                    connection.execute(
                        f"update {PROJECTION_TABLE} set projection_version = ? "
                        "where projection_name = 'knowledge_graph'",
                        ("knowledge-graph/999",),
                    )
                else:
                    connection.execute(
                        "update knowledge_graph_meta set value = ? where key = 'projection_version'",
                        ("knowledge-graph/999",),
                    )
                connection.commit()
        finally:
            current.close()

    before = database_path.read_bytes()
    with pytest.raises(UnsupportedDatabaseVersionError, match="(?i)refusing"):
        SQLiteStore(database_path)
    assert database_path.read_bytes() == before
