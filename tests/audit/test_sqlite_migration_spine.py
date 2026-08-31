from __future__ import annotations

import hashlib
import multiprocessing
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

import pytest

import seam_runtime.migrations as migration_module
from seam_runtime.knowledge_graph import init_knowledge_graph
from seam_runtime.migrations import (
    CURRENT_SCHEMA_VERSION,
    MIGRATION_TABLE,
    PROJECTION_TABLE,
    MigrationError,
    ProjectionMigration,
    ProjectionMigrationConnection,
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


def _hold_supported_store(path: str, started, release) -> None:
    store = SQLiteStore(path)
    try:
        started.set()
        assert release.wait(timeout=10)
    finally:
        store.close()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in connection.execute("select name from sqlite_master where type = 'table'").fetchall()}


def _assert_sqlite_checks(
    connection: sqlite3.Connection | ProjectionMigrationConnection,
) -> None:
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


def test_projection_migration_plan_is_deterministic_across_chains() -> None:
    def no_op(connection: ProjectionMigrationConnection) -> None:
        del connection

    workspace_one_to_two = ProjectionMigration(
        projection_name="workspace",
        from_version="workspace-schema/1",
        to_version="workspace-schema/2",
        name="workspace-1-to-2",
        source_required_tables=frozenset({"workspace_run"}),
        target_required_tables=frozenset({"workspace_run", "workspace_event"}),
        upgrade=no_op,
    )
    workspace_two_to_three = ProjectionMigration(
        projection_name="workspace",
        from_version="workspace-schema/2",
        to_version="workspace-schema/3",
        name="workspace-2-to-3",
        source_required_tables=frozenset({"workspace_run", "workspace_event"}),
        target_required_tables=frozenset(
            {"workspace_run", "workspace_event", "workspace_projection_state"}
        ),
        upgrade=no_op,
    )
    core_one_to_two = ProjectionMigration(
        projection_name="core_storage",
        from_version="core-storage/1",
        to_version="core-storage/2",
        name="core-storage-1-to-2",
        source_required_tables=frozenset({"raw_docs"}),
        target_required_tables=frozenset({"raw_docs", "raw_spans"}),
        upgrade=no_op,
    )

    planned = migration_module._plan_projection_migrations(
        {
            "workspace": "workspace-schema/1",
            "core_storage": "core-storage/1",
        },
        {
            "workspace": "workspace-schema/3",
            "core_storage": "core-storage/2",
        },
        (
            workspace_two_to_three,
            workspace_one_to_two,
            core_one_to_two,
        ),
    )

    assert [migration.name for migration in planned] == [
        "core-storage-1-to-2",
        "workspace-1-to-2",
        "workspace-2-to-3",
    ]


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


@pytest.mark.parametrize("escape", ["attribute", "sql"])
def test_failure_injector_cannot_commit_owned_transaction(
    tmp_path: Path,
    escape: str,
) -> None:
    database_path = tmp_path / f"injector-{escape}-commit.db"
    _build_fixture(database_path, "v2_4_0.sql")

    def commit_inside_injector(step, connection) -> None:
        if step.name != "initialize-versioned-core":
            return
        if escape == "attribute":
            getattr(connection, "commit")()
        else:
            connection.execute("commit")
        raise RuntimeError("must not run after commit escape")

    with pytest.raises(MigrationError, match="rolled back"):
        SQLiteStore(
            database_path,
            _migration_failure_injector=commit_inside_injector,
        )

    with sqlite3.connect(database_path) as connection:
        assert MIGRATION_TABLE not in _tables(connection)
        assert connection.execute(
            "select count(*) from ir_records where id = 'ent:released-memory'"
        ).fetchone()[0] == 1


def test_post_commit_validation_failure_does_not_claim_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "post-commit-validation.db"

    def fail_final_validation(connection: sqlite3.Connection) -> int:
        del connection
        raise sqlite3.OperationalError("injected final validation failure")

    monkeypatch.setattr(
        migration_module,
        "_validate_migration_rows",
        fail_final_validation,
    )

    with pytest.raises(MigrationError) as exc_info:
        SQLiteStore(database_path)

    message = str(exc_info.value)
    assert "outside an active transaction" in message
    assert "no rollback was performed" in message
    assert "failed and was rolled back" not in message
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            f"select max(version) from {MIGRATION_TABLE}"
        ).fetchone()[0] == CURRENT_SCHEMA_VERSION


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


def test_registered_projection_upgrade_preserves_populated_store_and_recovers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "projection-upgrade.db"
    backup_dir = tmp_path / "backups"
    _build_fixture(database_path, "v2_4_0.sql")

    current = SQLiteStore(database_path, _migration_backup_dir=backup_dir)
    try:
        with current._pool.checkout() as connection:
            connection.execute(
                "insert into workspace_run "
                "(run_id, created_at, ns, scope, agent_id, model, provider, metadata_json, schema_version) "
                "values ('ws:migration-proof', '2026-08-02T00:00:00Z', 'audit', 'projection', "
                "null, null, null, '{}', 1)"
            )
            connection.commit()
    finally:
        current.close()

    calls: list[bool] = []

    workspace_v1_tables = frozenset({"workspace_run", "workspace_event"})
    workspace_v2_tables = workspace_v1_tables | {"workspace_projection_state"}

    def upgrade_workspace(connection: ProjectionMigrationConnection) -> None:
        calls.append(connection.in_transaction)
        connection.execute(
            "create table workspace_projection_state ("
            "run_id text primary key references workspace_run(run_id), "
            "state text not null)"
        )
        connection.execute(
            "insert into workspace_projection_state (run_id, state) "
            "select run_id, 'upgraded' from workspace_run"
        )

    migration = ProjectionMigration(
        projection_name="workspace",
        from_version="workspace-schema/1",
        to_version="workspace-schema/2",
        name="upgrade-workspace-schema-1-to-2",
        source_required_tables=workspace_v1_tables,
        target_required_tables=workspace_v2_tables,
        upgrade=upgrade_workspace,
    )
    monkeypatch.setattr(migration_module, "PROJECTION_MIGRATIONS", (migration,))
    monkeypatch.setitem(
        migration_module._REQUIRED_PROJECTION_TABLES,
        "workspace",
        workspace_v2_tables,
    )
    monkeypatch.setitem(STORE_PROJECTION_VERSIONS, "workspace", "workspace-schema/2")

    upgraded = SQLiteStore(database_path, _migration_backup_dir=backup_dir)
    projection_backup = upgraded.migration_result.backup_path
    assert projection_backup is not None
    try:
        assert upgraded.migration_result.initial_version == CURRENT_SCHEMA_VERSION
        assert upgraded.migration_result.final_version == CURRENT_SCHEMA_VERSION
        assert upgraded.migration_result.applied_steps == (
            "upgrade-workspace-schema-1-to-2",
        )
        with upgraded._pool.checkout() as connection:
            assert connection.execute(
                "select count(*) from ir_records where id = 'ent:released-memory'"
            ).fetchone()[0] == 1
            workspace = connection.execute(
                "select state from workspace_projection_state "
                "where run_id = 'ws:migration-proof'"
            ).fetchone()
            assert tuple(workspace) == ("upgraded",)
            assert connection.execute(
                f"select projection_version from {PROJECTION_TABLE} "
                "where projection_name = 'workspace'"
            ).fetchone()[0] == "workspace-schema/2"
            _assert_sqlite_checks(connection)
    finally:
        upgraded.close()

    restore_database_backup(database_path, projection_backup)
    with closing(sqlite3.connect(database_path)) as recovered:
        assert "workspace_projection_state" not in _tables(recovered)
        assert recovered.execute(
            "select count(*) from ir_records where id = 'ent:released-memory'"
        ).fetchone()[0] == 1
        assert recovered.execute(
            "select count(*) from workspace_run where run_id = 'ws:migration-proof'"
        ).fetchone()[0] == 1
        assert recovered.execute(
            f"select projection_version from {PROJECTION_TABLE} "
            "where projection_name = 'workspace'"
        ).fetchone()[0] == "workspace-schema/1"
        _assert_sqlite_checks(recovered)

    reupgraded = SQLiteStore(database_path, _migration_backup_dir=backup_dir)
    try:
        assert reupgraded.migration_result.applied_steps == (
            "upgrade-workspace-schema-1-to-2",
        )
        with reupgraded._pool.checkout() as connection:
            assert connection.execute(
                "select state from workspace_projection_state "
                "where run_id = 'ws:migration-proof'"
            ).fetchone()[0] == "upgraded"
            assert connection.execute(
                "select count(*) from ir_records where id = 'ent:released-memory'"
            ).fetchone()[0] == 1
    finally:
        reupgraded.close()
    assert calls == [True, True]


def test_failed_projection_upgrade_rolls_back_callable_and_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "projection-rollback.db"
    backup_dir = tmp_path / "backups"
    current = SQLiteStore(database_path)
    current.close()

    workspace_v1_tables = frozenset({"workspace_run", "workspace_event"})
    workspace_v2_tables = workspace_v1_tables | {"workspace_projection_state"}

    def upgrade_workspace(connection: ProjectionMigrationConnection) -> None:
        connection.execute(
            "create table workspace_projection_state ("
            "run_id text primary key references workspace_run(run_id), "
            "state text not null)"
        )

    migration = ProjectionMigration(
        projection_name="workspace",
        from_version="workspace-schema/1",
        to_version="workspace-schema/2",
        name="upgrade-workspace-schema-1-to-2",
        source_required_tables=workspace_v1_tables,
        target_required_tables=workspace_v2_tables,
        upgrade=upgrade_workspace,
    )
    monkeypatch.setattr(migration_module, "PROJECTION_MIGRATIONS", (migration,))
    monkeypatch.setitem(
        migration_module._REQUIRED_PROJECTION_TABLES,
        "workspace",
        workspace_v2_tables,
    )
    monkeypatch.setitem(STORE_PROJECTION_VERSIONS, "workspace", "workspace-schema/2")

    def fail_after_checks(step, connection) -> None:
        if isinstance(step, ProjectionMigration):
            _assert_sqlite_checks(connection)
            raise RuntimeError("injected projection failure")

    with pytest.raises(MigrationError, match="rolled back") as exc_info:
        SQLiteStore(
            database_path,
            _migration_failure_injector=fail_after_checks,
            _migration_backup_dir=backup_dir,
        )
    assert exc_info.value.backup_path is not None
    assert exc_info.value.backup_path.is_file()

    with sqlite3.connect(database_path) as connection:
        assert "workspace_projection_state" not in _tables(connection)
        assert connection.execute(
            f"select projection_version from {PROJECTION_TABLE} "
            "where projection_name = 'workspace'"
        ).fetchone()[0] == "workspace-schema/1"
        _assert_sqlite_checks(connection)


@pytest.mark.parametrize(
    "transaction_escape",
    [
        "close",
        "commit",
        "cursor_connection",
        "executescript",
        "journal_mode",
        "locking_mode",
        "rollback",
        "set_authorizer",
        "sql_commit",
        "sql_savepoint",
    ],
)
def test_projection_upgrade_callable_cannot_end_owned_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    transaction_escape: str,
) -> None:
    database_path = tmp_path / f"projection-{transaction_escape}-refused.db"
    current = SQLiteStore(database_path)
    current.close()

    workspace_v1_tables = frozenset({"workspace_run", "workspace_event"})
    workspace_v2_tables = workspace_v1_tables | {"workspace_projection_state"}

    def end_transaction_inside_upgrade(
        connection: ProjectionMigrationConnection,
    ) -> None:
        connection.execute(
            "create table workspace_projection_state ("
            "run_id text primary key references workspace_run(run_id), "
            "state text not null)"
        )
        if transaction_escape == "cursor_connection":
            getattr(connection.execute("select 1"), "connection")
        elif transaction_escape == "sql_commit":
            connection.execute("commit")
        elif transaction_escape == "sql_savepoint":
            connection.execute("savepoint escaped")
        elif transaction_escape == "locking_mode":
            connection.execute("pragma main.locking_mode=NORMAL")
        elif transaction_escape == "journal_mode":
            connection.execute("pragma main.journal_mode=DELETE")
        elif transaction_escape == "executescript":
            getattr(connection, "executescript")("commit;")
        elif transaction_escape == "set_authorizer":
            getattr(connection, "set_authorizer")(None)
        else:
            getattr(connection, transaction_escape)()

    migration = ProjectionMigration(
        projection_name="workspace",
        from_version="workspace-schema/1",
        to_version="workspace-schema/2",
        name="upgrade-workspace-schema-1-to-2",
        source_required_tables=workspace_v1_tables,
        target_required_tables=workspace_v2_tables,
        upgrade=end_transaction_inside_upgrade,
    )
    monkeypatch.setattr(migration_module, "PROJECTION_MIGRATIONS", (migration,))
    monkeypatch.setitem(
        migration_module._REQUIRED_PROJECTION_TABLES,
        "workspace",
        workspace_v2_tables,
    )
    monkeypatch.setitem(STORE_PROJECTION_VERSIONS, "workspace", "workspace-schema/2")

    with pytest.raises(MigrationError, match="rolled back"):
        SQLiteStore(database_path)

    with sqlite3.connect(database_path) as connection:
        assert "workspace_projection_state" not in _tables(connection)
        assert connection.execute(
            f"select projection_version from {PROJECTION_TABLE} "
            "where projection_name = 'workspace'"
        ).fetchone()[0] == "workspace-schema/1"
        _assert_sqlite_checks(connection)


@pytest.mark.parametrize("journal_mode", ["delete", "wal"])
def test_exclusive_migration_owner_blocks_writer_across_backup_and_step_commits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    journal_mode: str,
) -> None:
    database_path = tmp_path / f"exclusive-{journal_mode}.db"
    backup_dir = tmp_path / "backups"
    _build_fixture(database_path, "v2_4_0.sql")
    with sqlite3.connect(database_path) as connection:
        selected_mode = connection.execute(
            f"pragma journal_mode={journal_mode}"
        ).fetchone()[0]
    assert str(selected_mode).casefold() == journal_mode

    backup_complete = threading.Event()
    writer_blocked = threading.Event()
    writer_committed = threading.Event()
    real_backup = migration_module._backup_database
    observed_steps: list[str] = []
    migration_errors: list[BaseException] = []
    writer_errors: list[BaseException] = []

    def observed_backup(
        path: Path,
        version: int,
        destination: Path | None,
        *,
        source_connection: sqlite3.Connection | None = None,
    ) -> Path:
        result = real_backup(
            path,
            version,
            destination,
            source_connection=source_connection,
        )
        backup_complete.set()
        assert writer_blocked.wait(5)
        assert not writer_committed.wait(0.2)
        return result

    def observe_step(step, connection: ProjectionMigrationConnection) -> None:
        observed_steps.append(step.name)
        assert writer_blocked.is_set()
        assert not writer_committed.is_set()
        assert connection.execute("pragma main.locking_mode").fetchone()[0] == "exclusive"

    monkeypatch.setattr(migration_module, "_backup_database", observed_backup)

    def run_migration() -> None:
        try:
            store = SQLiteStore(
                database_path,
                _migration_backup_dir=backup_dir,
                _migration_failure_injector=observe_step,
            )
            store.close()
        except BaseException as exc:  # pragma: no cover - asserted in parent thread
            migration_errors.append(exc)

    def run_writer() -> None:
        try:
            with sqlite3.connect(database_path, timeout=10.0) as connection:
                connection.execute("pragma busy_timeout=0")
                with pytest.raises(sqlite3.OperationalError, match="locked"):
                    connection.execute("begin immediate")
                writer_blocked.set()
                connection.execute("pragma busy_timeout=10000")
                connection.execute("begin immediate")
                connection.execute(
                    "update ir_records set conf = 0.96 "
                    "where id = 'ent:released-memory'"
                )
                connection.commit()
            writer_committed.set()
        except BaseException as exc:  # pragma: no cover - asserted in parent thread
            writer_errors.append(exc)

    migration_thread = threading.Thread(target=run_migration)
    migration_thread.start()
    assert backup_complete.wait(5)

    writer_thread = threading.Thread(target=run_writer)
    writer_thread.start()
    migration_thread.join(15)
    writer_thread.join(15)

    assert not migration_thread.is_alive()
    assert not writer_thread.is_alive()
    assert migration_errors == []
    assert writer_errors == []
    assert writer_blocked.is_set()
    assert writer_committed.is_set()
    assert observed_steps == [
        "initialize-versioned-core",
        "register-durable-projections",
    ]
    with sqlite3.connect(database_path) as connection:
        assert connection.execute(
            "select conf from ir_records where id = 'ent:released-memory'"
        ).fetchone()[0] == 0.96
        assert connection.execute(
            f"select max(version) from {MIGRATION_TABLE}"
        ).fetchone()[0] == CURRENT_SCHEMA_VERSION


def test_failed_backup_is_never_published_as_recoverable(tmp_path: Path) -> None:
    database_path = tmp_path / "backup-source.db"
    backup_dir = tmp_path / "backups"

    class FailingBackupSource:
        in_transaction = False

        @staticmethod
        def backup(destination: sqlite3.Connection) -> None:
            destination.execute("create table incomplete (id integer primary key)")
            raise sqlite3.OperationalError("injected backup copy failure")

    with pytest.raises(MigrationError) as exc_info:
        migration_module._backup_database(
            database_path,
            CURRENT_SCHEMA_VERSION,
            backup_dir,
            source_connection=FailingBackupSource(),  # type: ignore[arg-type]
        )

    assert exc_info.value.backup_path is None
    assert "no recovery backup is available" in str(exc_info.value)
    assert list(backup_dir.iterdir()) == []


def test_backup_publication_syncs_new_directory_and_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "backup-source.db"
    backup_dir = tmp_path / "new-backups"
    with sqlite3.connect(database_path) as connection:
        connection.execute("create table durable (id integer primary key)")

    synced: list[Path] = []
    monkeypatch.setattr(
        migration_module,
        "_fsync_directory",
        lambda path: synced.append(path),
    )

    backup_path = migration_module._backup_database(
        database_path,
        CURRENT_SCHEMA_VERSION,
        backup_dir,
    )

    assert backup_path.is_file()
    assert synced == [backup_dir, tmp_path]


def test_backup_directory_sync_failure_reports_published_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "backup-source.db"
    backup_dir = tmp_path / "backups"
    with sqlite3.connect(database_path) as connection:
        connection.execute("create table durable (id integer primary key)")

    monkeypatch.setattr(
        migration_module,
        "_fsync_directory",
        lambda path: (_ for _ in ()).throw(OSError(f"cannot sync {path.name}")),
    )

    with pytest.raises(MigrationError) as exc_info:
        migration_module._backup_database(
            database_path,
            CURRENT_SCHEMA_VERSION,
            backup_dir,
        )

    assert exc_info.value.backup_path is not None
    assert exc_info.value.backup_path.is_file()
    assert "published" in str(exc_info.value)
    assert not list(backup_dir.glob("*.partial-*"))


@pytest.mark.parametrize("drift", ["central-history", "projection-registry"])
def test_locked_preflight_refuses_toctou_drift_before_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: str,
) -> None:
    database_path = tmp_path / f"toctou-{drift}.db"
    backup_dir = tmp_path / "backups"
    current = SQLiteStore(database_path)
    current.close()
    with sqlite3.connect(database_path) as connection:
        assert connection.execute("pragma journal_mode=delete").fetchone()[0] == "delete"

    workspace_v1_tables = frozenset({"workspace_run", "workspace_event"})
    workspace_v2_tables = workspace_v1_tables | {"workspace_projection_state"}

    def upgrade_workspace(connection: ProjectionMigrationConnection) -> None:
        connection.execute(
            "create table workspace_projection_state ("
            "run_id text primary key references workspace_run(run_id), "
            "state text not null)"
        )

    migration = ProjectionMigration(
        projection_name="workspace",
        from_version="workspace-schema/1",
        to_version="workspace-schema/2",
        name="upgrade-workspace-schema-1-to-2",
        source_required_tables=workspace_v1_tables,
        target_required_tables=workspace_v2_tables,
        upgrade=upgrade_workspace,
    )
    monkeypatch.setattr(migration_module, "PROJECTION_MIGRATIONS", (migration,))
    monkeypatch.setitem(
        migration_module._REQUIRED_PROJECTION_TABLES,
        "workspace",
        workspace_v2_tables,
    )
    monkeypatch.setitem(STORE_PROJECTION_VERSIONS, "workspace", "workspace-schema/2")

    real_inspect = migration_module._inspect_database
    state_after_drift: list[bytes] = []

    def inspect_then_drift(
        path: str | Path,
        *,
        expected_projection_versions,
        projection_migrations,
    ):
        result = real_inspect(
            path,
            expected_projection_versions=expected_projection_versions,
            projection_migrations=projection_migrations,
        )
        with sqlite3.connect(path) as connection:
            if drift == "central-history":
                connection.execute(
                    f"update {MIGRATION_TABLE} set checksum = 'raced' where version = 2"
                )
            else:
                connection.execute(
                    f"update {PROJECTION_TABLE} set projection_version = 'core-storage/raced' "
                    "where projection_name = 'core_storage'"
                )
            connection.commit()
        state_after_drift.append(Path(path).read_bytes())
        return result

    monkeypatch.setattr(migration_module, "_inspect_database", inspect_then_drift)

    with pytest.raises(UnsupportedDatabaseVersionError, match="(?i)refusing"):
        SQLiteStore(database_path, _migration_backup_dir=backup_dir)

    assert state_after_drift
    assert database_path.read_bytes() == state_after_drift[-1]
    assert not backup_dir.exists()


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


def test_restore_refuses_while_a_supported_store_is_live(tmp_path: Path) -> None:
    database_path = tmp_path / "live-store-restore-target.db"
    backup_path = tmp_path / "live-store-restore-backup.db"
    live_store = SQLiteStore(database_path)
    with sqlite3.connect(backup_path) as backup:
        backup.execute("create table recovered (id integer primary key)")
    before = database_path.read_bytes()

    try:
        with pytest.raises(RuntimeError, match="active SEAM store"):
            restore_database_backup(database_path, backup_path)

        assert database_path.read_bytes() == before
        live_store.check_ready()
    finally:
        live_store.close()


def test_restore_lease_crosses_processes_and_releases_on_store_close(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "cross-process-restore-target.db"
    backup_path = tmp_path / "cross-process-restore-backup.db"
    with sqlite3.connect(backup_path) as backup:
        backup.execute("create table recovered (id integer primary key)")
    process_context = multiprocessing.get_context("spawn")
    started = process_context.Event()
    release = process_context.Event()
    process = process_context.Process(
        target=_hold_supported_store,
        args=(str(database_path), started, release),
    )
    process.start()
    try:
        assert started.wait(timeout=10)
        with pytest.raises(RuntimeError, match="active SEAM store"):
            restore_database_backup(database_path, backup_path)
    finally:
        release.set()
        process.join(timeout=10)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
        assert process.exitcode == 0

    restore_database_backup(database_path, backup_path)
    with sqlite3.connect(database_path) as recovered:
        assert "recovered" in _tables(recovered)


def test_failed_store_initialization_releases_the_restore_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "failed-store-init-target.db"
    backup_path = tmp_path / "failed-store-init-backup.db"
    with sqlite3.connect(backup_path) as backup:
        backup.execute("create table recovered (id integer primary key)")
    monkeypatch.setenv("SEAM_DB_POOL_SIZE", "not-an-integer")

    with pytest.raises(ValueError, match="invalid literal"):
        SQLiteStore(database_path)

    monkeypatch.delenv("SEAM_DB_POOL_SIZE")
    restore_database_backup(database_path, backup_path)
    with sqlite3.connect(database_path) as recovered:
        assert "recovered" in _tables(recovered)


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


def test_failed_sidecar_cleanup_does_not_commit_the_restored_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sidecar-cleanup-target.db"
    backup_path = tmp_path / "sidecar-cleanup-backup.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("create table original (id integer primary key)")
    with sqlite3.connect(backup_path) as connection:
        connection.execute("create table recovered (id integer primary key)")
    original_bytes = database_path.read_bytes()
    stale_journal = Path(f"{database_path}-journal")
    stale_journal.write_bytes(b"stale-journal")
    real_replace = migration_module.os.replace

    def fail_stale_sidecar_quarantine(source, destination) -> None:
        if Path(source) == stale_journal:
            raise OSError("injected stale sidecar cleanup failure")
        real_replace(source, destination)

    monkeypatch.setattr(
        migration_module.os,
        "replace",
        fail_stale_sidecar_quarantine,
    )
    with pytest.raises(OSError, match="injected stale sidecar cleanup failure"):
        restore_database_backup(database_path, backup_path)

    assert database_path.read_bytes() == original_bytes
    assert stale_journal.read_bytes() == b"stale-journal"


@pytest.mark.parametrize(
    "case",
    [
        "unknown",
        "newer-schema",
        "newer-projection",
        "newer-component-marker",
        "missing-projection",
        "extra-projection",
        "changed-projection",
    ],
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
                elif case == "newer-component-marker":
                    connection.execute(
                        "update knowledge_graph_meta set value = ? where key = 'projection_version'",
                        ("knowledge-graph/999",),
                    )
                elif case == "missing-projection":
                    connection.execute(
                        f"delete from {PROJECTION_TABLE} where projection_name = 'workspace'"
                    )
                elif case == "extra-projection":
                    connection.execute(
                        f"insert into {PROJECTION_TABLE} values ('unregistered_projection', 'unknown/1')"
                    )
                else:
                    connection.execute(
                        f"update {PROJECTION_TABLE} set projection_version = 'workspace-schema/999' "
                        "where projection_name = 'workspace'"
                    )
                connection.commit()
        finally:
            current.close()

    before = database_path.read_bytes()
    with pytest.raises(UnsupportedDatabaseVersionError, match="(?i)refusing"):
        SQLiteStore(database_path)
    assert database_path.read_bytes() == before
    assert not database_path.with_name(f"{database_path.name}.seam-backups").exists()
