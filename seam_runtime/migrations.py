"""Central, fail-closed SQLite schema and projection migration spine.

The migration contract is intentionally smaller than the store implementation:
it owns version discovery, ordered step execution, integrity gates, backup and
restore.  Individual durable components still own their DDL, but they may only
be invoked from a registered migration step when an existing database needs to
change.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import tempfile
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final
from uuid import uuid4

CURRENT_SCHEMA_VERSION: Final = 2
MIGRATION_TABLE: Final = "seam_schema_migrations"
PROJECTION_TABLE: Final = "seam_projection_versions"

_KNOWN_LEGACY_TABLES: Final = frozenset(
    {
        "raw_docs",
        "raw_spans",
        "document_status",
        "ir_records",
        "ir_edges",
        "symbol_table",
        "pack_store",
        "prov_log",
        "vector_index",
        "machine_artifacts",
        "surface_artifacts",
        "benchmark_runs",
        "benchmark_cases",
        "projection_index",
        "retrieval_event",
        "improvement_proposal",
        "proposal_decision",
        "retrieval_flag_state",
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
        "graph_product_build",
        "graph_product",
        "graph_product_sentence",
        "lifecycle_operation",
        "lifecycle_event",
        "lifecycle_batch_payload",
        "workspace_run",
        "workspace_event",
        "reasoning_node",
        "reasoning_edge",
        "reasoning_state",
        "reasoning_retrieval",
        "reasoning_retrieval_candidate",
        "reasoning_verification",
        "reasoning_outcome_verification",
        "reasoning_pattern",
        "reasoning_pattern_use",
        "reasoning_pattern_result",
        "reasoning_promotion_proposal",
        "reasoning_promotion_review",
        "reasoning_promotion_application",
        "reasoning_promotion_reversal",
    }
)

_REQUIRED_PROJECTION_TABLES: Final = {
    "canonical_mirl": frozenset({"ir_records"}),
    "core_storage": frozenset(
        {
            "raw_docs",
            "raw_spans",
            "document_status",
            "ir_edges",
            "symbol_table",
            "pack_store",
            "prov_log",
            "projection_index",
            "retrieval_event",
        }
    ),
    "graph_products": frozenset({"graph_product_build", "graph_product", "graph_product_sentence"}),
    "knowledge_graph": frozenset(
        {
            "knowledge_graph_meta",
            "knowledge_nodes",
            "knowledge_edges",
            "knowledge_episodes",
            "knowledge_node_episodes",
            "knowledge_edge_episodes",
            "knowledge_node_terms",
            "identity_merges",
            "identity_merge_evidence",
        }
    ),
    "knowledge_graph_vectors": frozenset({"knowledge_node_vectors"}),
    "lifecycle": frozenset({"lifecycle_operation", "lifecycle_event", "lifecycle_batch_payload"}),
    "reasoning_graph": frozenset({"reasoning_node", "reasoning_edge", "reasoning_state"}),
    "reasoning_patterns": frozenset({"reasoning_pattern", "reasoning_pattern_use", "reasoning_pattern_result"}),
    "reasoning_promotion": frozenset(
        {
            "reasoning_promotion_proposal",
            "reasoning_promotion_review",
            "reasoning_promotion_application",
            "reasoning_promotion_reversal",
        }
    ),
    "reasoning_retrieval": frozenset({"reasoning_retrieval", "reasoning_retrieval_candidate"}),
    "reasoning_verification": frozenset({"reasoning_verification", "reasoning_outcome_verification"}),
    "sqlite_vector": frozenset({"vector_index"}),
    "workspace": frozenset({"workspace_run", "workspace_event"}),
}


class MigrationError(RuntimeError):
    """Base error for a refused or failed migration."""

    def __init__(self, message: str, *, backup_path: Path | None = None) -> None:
        super().__init__(message)
        self.backup_path = backup_path


class UnsupportedDatabaseVersionError(MigrationError):
    """Raised before mutation when the database is newer or unknown."""


class KnowledgeGraphProjectionVersionError(UnsupportedDatabaseVersionError):
    """Raised before mutation for an unsupported graph projection marker."""


class DatabaseIntegrityError(MigrationError):
    """Raised when SQLite integrity or foreign-key checks fail."""


SchemaInitializer = Callable[[sqlite3.Connection], None]
MigrationAction = Callable[
    [sqlite3.Connection, SchemaInitializer, Mapping[str, str]],
    None,
]
SQLParameters = Sequence[object] | Mapping[str, object]
SQLParameterRows = Iterable[Sequence[object] | Mapping[str, object]]


class ProjectionMigrationCursor:
    """Read/result-only cursor facade for projection migrations."""

    __slots__ = ("__cursor",)

    def __init__(self, cursor: sqlite3.Cursor) -> None:
        self.__cursor = cursor

    @property
    def rowcount(self) -> int:
        return self.__cursor.rowcount

    @property
    def lastrowid(self) -> int | None:
        return self.__cursor.lastrowid

    def fetchone(self) -> object | None:
        return self.__cursor.fetchone()

    def fetchmany(self, size: int | None = None) -> list[object]:
        if size is None:
            return self.__cursor.fetchmany()
        return self.__cursor.fetchmany(size)

    def fetchall(self) -> list[object]:
        return self.__cursor.fetchall()

    def __iter__(self) -> Iterator[object]:
        return iter(self.__cursor)


class ProjectionMigrationConnection:
    """Narrow SQL facade that cannot control or expose the owned transaction."""

    __slots__ = ("__connection",)

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.__connection = connection

    @property
    def in_transaction(self) -> bool:
        return self.__connection.in_transaction

    @property
    def total_changes(self) -> int:
        return self.__connection.total_changes

    def execute(
        self,
        statement: str,
        parameters: SQLParameters = (),
    ) -> ProjectionMigrationCursor:
        return ProjectionMigrationCursor(self.__connection.execute(statement, parameters))

    def executemany(
        self,
        statement: str,
        parameters: SQLParameterRows,
    ) -> ProjectionMigrationCursor:
        return ProjectionMigrationCursor(self.__connection.executemany(statement, parameters))

    def execute_script(self, script: str) -> None:
        """Run complete SQL statements without sqlite3.executescript's commit."""

        execute_script(self.__connection, script)


ProjectionUpgrade = Callable[[ProjectionMigrationConnection], None]


@dataclass(frozen=True, slots=True)
class MigrationStep:
    from_version: int
    to_version: int
    name: str
    apply: MigrationAction

    @property
    def checksum(self) -> str:
        material = f"{self.from_version}:{self.to_version}:{self.name}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ProjectionMigration:
    """One exact, auditable transition for a durable projection."""

    projection_name: str
    from_version: str
    to_version: str
    name: str
    source_required_tables: frozenset[str]
    target_required_tables: frozenset[str]
    upgrade: ProjectionUpgrade

    def __post_init__(self) -> None:
        if not self.projection_name.strip():
            raise ValueError("projection migration requires a projection name")
        if not self.from_version.strip() or not self.to_version.strip():
            raise ValueError("projection migration versions must be non-empty")
        if self.from_version == self.to_version:
            raise ValueError("projection migration must change the version")
        if not self.name.strip():
            raise ValueError("projection migration requires a stable name")
        source_required_tables = frozenset(
            str(table) for table in self.source_required_tables
        )
        target_required_tables = frozenset(
            str(table) for table in self.target_required_tables
        )
        object.__setattr__(self, "source_required_tables", source_required_tables)
        object.__setattr__(self, "target_required_tables", target_required_tables)
        if not source_required_tables or not target_required_tables:
            raise ValueError(
                "projection migration requires non-empty source and target table contracts"
            )
        if any(not table.strip() for table in source_required_tables):
            raise ValueError("projection migration source table names must be non-empty")
        if any(not table.strip() for table in target_required_tables):
            raise ValueError("projection migration target table names must be non-empty")
        if not callable(self.upgrade):
            raise TypeError("projection migration upgrade must be callable")


@dataclass(frozen=True, slots=True)
class MigrationResult:
    initial_version: int
    final_version: int
    applied_steps: tuple[str, ...]
    backup_path: Path | None


def _initialize_versioned_core(
    connection: sqlite3.Connection,
    initialize_schema: SchemaInitializer,
    expected_projection_versions: Mapping[str, str],
) -> None:
    del expected_projection_versions
    initialize_schema(connection)
    connection.execute(
        f"create table {MIGRATION_TABLE} ("
        "version integer primary key check (version >= 1), "
        "name text not null unique, "
        "checksum text not null, "
        "applied_at text not null)"
    )


def _register_durable_projections(
    connection: sqlite3.Connection,
    initialize_schema: SchemaInitializer,
    expected_projection_versions: Mapping[str, str],
) -> None:
    del initialize_schema
    connection.execute(
        f"create table {PROJECTION_TABLE} (projection_name text primary key, projection_version text not null)"
    )
    connection.executemany(
        f"insert into {PROJECTION_TABLE} (projection_name, projection_version) values (?, ?)",
        sorted(expected_projection_versions.items()),
    )


_STEPS: Final = (
    MigrationStep(0, 1, "initialize-versioned-core", _initialize_versioned_core),
    MigrationStep(1, 2, "register-durable-projections", _register_durable_projections),
)
_STEP_BY_TARGET: Final = {step.to_version: step for step in _STEPS}

_KNOWLEDGE_GRAPH_V4_TABLES: Final = frozenset(
    {
        "knowledge_graph_meta",
        "knowledge_nodes",
        "knowledge_edges",
        "knowledge_episodes",
        "knowledge_node_episodes",
        "knowledge_edge_episodes",
        "identity_merges",
        "identity_merge_evidence",
    }
)


def _rebuild_knowledge_graph_4_to_5(
    connection: ProjectionMigrationConnection,
) -> None:
    # Lazy import avoids a module cycle: knowledge_graph imports the migration
    # exception and transactional script helper during ordinary initialization.
    from .knowledge_graph import rebuild_knowledge_graph_from_canonical

    rebuild_knowledge_graph_from_canonical(connection)


# Projection changes are registered statically alongside the code that knows
# how to perform them. Each transition is exact; arbitrary version ordering is
# intentionally unsupported.
PROJECTION_MIGRATIONS: Final[tuple[ProjectionMigration, ...]] = (
    ProjectionMigration(
        projection_name="knowledge_graph",
        from_version="knowledge-graph/4",
        to_version="knowledge-graph/5",
        name="rebuild-knowledge-graph-4-to-5-from-canonical",
        source_required_tables=_KNOWLEDGE_GRAPH_V4_TABLES,
        target_required_tables=_REQUIRED_PROJECTION_TABLES["knowledge_graph"],
        upgrade=_rebuild_knowledge_graph_4_to_5,
    ),
)

FailureInjector = Callable[
    [MigrationStep | ProjectionMigration, ProjectionMigrationConnection],
    None,
]


def execute_script(connection: sqlite3.Connection, script: str) -> None:
    """Execute a SQL script without sqlite3.executescript's implicit COMMIT.

    ``sqlite3.complete_statement`` keeps triggers and other multi-line
    statements intact while each completed statement stays inside the caller's
    transaction.
    """

    pending = ""
    for line in script.splitlines(keepends=True):
        pending += line
        if not sqlite3.complete_statement(pending):
            continue
        statement = pending.strip()
        pending = ""
        if statement:
            connection.execute(statement)
    without_block_comments = re.sub(r"/\*.*?\*/", "", pending, flags=re.DOTALL)
    without_comments = "\n".join(
        line.split("--", 1)[0] for line in without_block_comments.splitlines()
    )
    if without_comments.strip():
        raise sqlite3.OperationalError("incomplete SQL statement in schema script")


def _readonly_connection(path: Path) -> sqlite3.Connection:
    # Do not use immutable=1 here: it ignores WAL content and could classify a
    # crashed/newer database from a stale main file. Read-only mode observes the
    # complete committed SQLite state without opening the database for writes.
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _user_tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "select name from sqlite_master where type = 'table' and name not like 'sqlite_%'"
        ).fetchall()
    }


def _validate_migration_rows(connection: sqlite3.Connection) -> int:
    try:
        rows = connection.execute(f"select version, name, checksum from {MIGRATION_TABLE} order by version").fetchall()
    except sqlite3.Error as exc:
        raise UnsupportedDatabaseVersionError(
            "Unrecognized SEAM schema-version table; refusing to modify database"
        ) from exc
    if not rows:
        raise UnsupportedDatabaseVersionError("SEAM schema-version table is empty; refusing to modify database")
    versions = [int(row[0]) for row in rows]
    latest = versions[-1]
    if latest > CURRENT_SCHEMA_VERSION:
        raise UnsupportedDatabaseVersionError(
            f"Database schema version {latest} is newer than supported version "
            f"{CURRENT_SCHEMA_VERSION}; refusing to modify database"
        )
    if versions != list(range(1, latest + 1)):
        raise UnsupportedDatabaseVersionError("SEAM migration history is non-contiguous; refusing to modify database")
    for row in rows:
        version = int(row[0])
        step = _STEP_BY_TARGET.get(version)
        if step is None or str(row[1]) != step.name or str(row[2]) != step.checksum:
            raise UnsupportedDatabaseVersionError(
                f"Unknown migration identity at schema version {version}; refusing to modify database"
            )
    return latest


def _read_projection_rows(
    connection: sqlite3.Connection,
) -> dict[str, str]:
    tables = _user_tables(connection)
    if PROJECTION_TABLE not in tables:
        raise UnsupportedDatabaseVersionError(
            "Current SEAM database is missing its projection-version registry; refusing to modify database"
        )
    try:
        rows = connection.execute(
            f"select projection_name, projection_version from {PROJECTION_TABLE}"
        ).fetchall()
    except sqlite3.Error as exc:
        raise UnsupportedDatabaseVersionError(
            "Unrecognized projection-version registry; refusing to modify database"
        ) from exc
    actual: dict[str, str] = {}
    for row in rows:
        name = str(row[0])
        if name in actual:
            raise UnsupportedDatabaseVersionError(
                "Projection-version registry contains duplicate names; refusing to modify database"
            )
        actual[name] = str(row[1])
    return actual


def _projection_registry_detail(
    actual: Mapping[str, str],
    expected: Mapping[str, str],
) -> str:
    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    changed = sorted(name for name in set(actual) & set(expected) if actual[name] != expected[name])
    return f"missing={missing}, extra={extra}, changed={changed}"


def _unsupported_projection_registry(
    actual: Mapping[str, str],
    expected: Mapping[str, str],
    *,
    reason: str | None = None,
) -> UnsupportedDatabaseVersionError:
    detail = _projection_registry_detail(actual, expected)
    suffix = f"; {reason}" if reason else ""
    return UnsupportedDatabaseVersionError(
        f"Unsupported durable projection registry ({detail}{suffix}); refusing to modify database"
    )


def _projection_migration_index(
    migrations: tuple[ProjectionMigration, ...],
) -> dict[tuple[str, str], ProjectionMigration]:
    index: dict[tuple[str, str], ProjectionMigration] = {}
    names: set[str] = set()
    for migration in migrations:
        key = (migration.projection_name, migration.from_version)
        if key in index:
            raise MigrationError(
                "Projection migration registry has more than one transition from "
                f"{migration.projection_name!r} version {migration.from_version!r}"
            )
        if migration.name in names:
            raise MigrationError(
                f"Projection migration registry repeats stable name {migration.name!r}"
            )
        index[key] = migration
        names.add(migration.name)
    return index


def _plan_projection_migrations(
    actual_projection_versions: Mapping[str, str],
    expected_projection_versions: Mapping[str, str],
    migrations: tuple[ProjectionMigration, ...],
) -> tuple[ProjectionMigration, ...]:
    actual = {str(name): str(version) for name, version in actual_projection_versions.items()}
    expected = {str(name): str(version) for name, version in expected_projection_versions.items()}
    if set(actual) != set(expected):
        raise _unsupported_projection_registry(actual, expected)

    index = _projection_migration_index(migrations)
    planned: list[ProjectionMigration] = []
    for projection_name in sorted(expected):
        current_version = actual[projection_name]
        target_version = expected[projection_name]
        visited = {current_version}
        while current_version != target_version:
            migration = index.get((projection_name, current_version))
            if migration is None:
                raise _unsupported_projection_registry(
                    actual,
                    expected,
                    reason=(
                        f"no registered transition for {projection_name!r} "
                        f"from {current_version!r} toward {target_version!r}"
                    ),
                )
            if migration.to_version in visited:
                raise _unsupported_projection_registry(
                    actual,
                    expected,
                    reason=f"registered transitions for {projection_name!r} contain a cycle",
                )
            planned.append(migration)
            current_version = migration.to_version
            visited.add(current_version)
    return tuple(planned)


def _projection_table_contracts_for_plan(
    actual_projection_versions: Mapping[str, str],
    expected_projection_versions: Mapping[str, str],
    planned: tuple[ProjectionMigration, ...],
) -> dict[str, frozenset[str]]:
    contracts = {
        name: required
        for name, required in _REQUIRED_PROJECTION_TABLES.items()
        if name in actual_projection_versions
    }
    by_projection: dict[str, list[ProjectionMigration]] = {}
    for migration in planned:
        by_projection.setdefault(migration.projection_name, []).append(migration)

    for projection_name, migrations in by_projection.items():
        for previous, following in zip(migrations, migrations[1:], strict=False):
            if previous.target_required_tables != following.source_required_tables:
                raise MigrationError(
                    f"Projection migration table contract is discontinuous for {projection_name!r} "
                    f"between {previous.name!r} and {following.name!r}"
                )
        target_contract = _REQUIRED_PROJECTION_TABLES.get(projection_name)
        if target_contract is None:
            raise MigrationError(
                f"Projection migration {projection_name!r} has no current required-table contract"
            )
        if migrations[-1].target_required_tables != target_contract:
            raise MigrationError(
                f"Projection migration {migrations[-1].name!r} target tables do not match "
                f"the current {projection_name!r} contract"
            )
        if migrations[0].from_version != actual_projection_versions[projection_name]:
            raise MigrationError(
                f"Projection migration {migrations[0].name!r} source version does not match preflight"
            )
        if migrations[-1].to_version != expected_projection_versions[projection_name]:
            raise MigrationError(
                f"Projection migration {migrations[-1].name!r} target version does not match expected state"
            )
        contracts[projection_name] = migrations[0].source_required_tables
    return contracts


def _validate_projection_rows(
    connection: sqlite3.Connection,
    expected_projection_versions: Mapping[str, str],
) -> None:
    actual = _read_projection_rows(connection)
    expected = {str(name): str(version) for name, version in expected_projection_versions.items()}
    if actual != expected:
        raise _unsupported_projection_registry(actual, expected)
    _validate_required_projection_tables(connection, expected)


def _validate_required_projection_tables(
    connection: sqlite3.Connection,
    expected_projection_versions: Mapping[str, str],
) -> None:
    required_tables = {
        name: required
        for name, required in _REQUIRED_PROJECTION_TABLES.items()
        if name in expected_projection_versions
    }
    _validate_required_table_contracts(connection, required_tables)


def _validate_required_table_contracts(
    connection: sqlite3.Connection,
    required_tables: Mapping[str, frozenset[str]],
) -> None:
    tables = _user_tables(connection)
    missing_tables = {
        name: sorted(required - tables)
        for name, required in required_tables.items()
        if required - tables
    }
    if missing_tables:
        raise DatabaseIntegrityError(
            f"Durable projection registry references missing tables {missing_tables}"
        )


def _validate_knowledge_graph_marker(
    connection: sqlite3.Connection,
    tables: set[str],
    expected_projection_versions: Mapping[str, str],
    *,
    require_present: bool,
) -> None:
    expected = expected_projection_versions.get("knowledge_graph")
    if expected is None:
        return
    if "knowledge_graph_meta" not in tables:
        if require_present:
            raise KnowledgeGraphProjectionVersionError(
                "Knowledge graph projection marker is missing. "
                "Refusing automatic reprojection and leaving database unchanged"
            )
        return
    row = connection.execute("select value from knowledge_graph_meta where key = 'projection_version'").fetchone()
    stored = str(row[0]) if row is not None else "missing"
    if stored != expected:
        raise KnowledgeGraphProjectionVersionError(
            "Unsupported knowledge graph projection version "
            f"{stored!r}; expected {expected!r}. "
            "Refusing automatic reprojection and leaving database unchanged"
        )


def _inspect_connection(
    connection: sqlite3.Connection,
    *,
    expected_projection_versions: Mapping[str, str],
    projection_migrations: tuple[ProjectionMigration, ...],
) -> tuple[int, dict[str, str] | None, tuple[ProjectionMigration, ...]]:
    tables = _user_tables(connection)
    if not tables:
        return 0, None, ()
    if MIGRATION_TABLE not in tables:
        if not tables.intersection(_KNOWN_LEGACY_TABLES):
            raise UnsupportedDatabaseVersionError(
                "Database has no recognized SEAM schema; refusing to modify database"
            )
        _validate_knowledge_graph_marker(
            connection,
            tables,
            expected_projection_versions,
            require_present=False,
        )
        return 0, None, ()
    version = _validate_migration_rows(connection)
    if version == CURRENT_SCHEMA_VERSION:
        actual_projection_versions = _read_projection_rows(connection)
        planned = _plan_projection_migrations(
            actual_projection_versions,
            expected_projection_versions,
            projection_migrations,
        )
        source_table_contracts = _projection_table_contracts_for_plan(
            actual_projection_versions,
            expected_projection_versions,
            planned,
        )
        _validate_required_table_contracts(
            connection,
            source_table_contracts,
        )
        _validate_knowledge_graph_marker(
            connection,
            tables,
            actual_projection_versions,
            require_present=True,
        )
        return version, actual_projection_versions, planned
    return version, None, ()


def _inspect_database(
    path: str | Path,
    *,
    expected_projection_versions: Mapping[str, str],
    projection_migrations: tuple[ProjectionMigration, ...],
) -> tuple[int, dict[str, str] | None, tuple[ProjectionMigration, ...]]:
    """Return the supported schema version and projection plan read-only."""

    _projection_migration_index(projection_migrations)
    database_path = Path(path)
    if not database_path.exists() or database_path.stat().st_size == 0:
        return 0, None, ()
    try:
        with closing(_readonly_connection(database_path)) as connection:
            return _inspect_connection(
                connection,
                expected_projection_versions=expected_projection_versions,
                projection_migrations=projection_migrations,
            )
    except sqlite3.DatabaseError as exc:
        raise UnsupportedDatabaseVersionError(
            "Database is not a readable supported SEAM SQLite store; refusing to modify database"
        ) from exc


def inspect_database(
    path: str | Path,
    *,
    expected_projection_versions: Mapping[str, str],
) -> int:
    """Return the supported schema version without changing database bytes."""

    version, _, _ = _inspect_database(
        path,
        expected_projection_versions=expected_projection_versions,
        projection_migrations=tuple(PROJECTION_MIGRATIONS),
    )
    return version


def _revalidate_locked_preflight(
    connection: sqlite3.Connection,
    *,
    initial_version: int,
    preflight_projection_versions: Mapping[str, str] | None,
    preflight_projection_plan: tuple[ProjectionMigration, ...],
    expected_projection_versions: Mapping[str, str],
    projection_migrations: tuple[ProjectionMigration, ...],
) -> dict[str, frozenset[str]]:
    locked_version, locked_projection_versions, locked_projection_plan = (
        _inspect_connection(
            connection,
            expected_projection_versions=expected_projection_versions,
            projection_migrations=projection_migrations,
        )
    )
    expected_preflight_versions = (
        dict(preflight_projection_versions)
        if preflight_projection_versions is not None
        else None
    )
    if (
        locked_version != initial_version
        or locked_projection_versions != expected_preflight_versions
        or locked_projection_plan != preflight_projection_plan
    ):
        raise UnsupportedDatabaseVersionError(
            "Database migration state changed after read-only preflight; "
            "refusing before backup or mutation"
        )
    if locked_projection_versions is None:
        return {}
    return _projection_table_contracts_for_plan(
        locked_projection_versions,
        expected_projection_versions,
        locked_projection_plan,
    )


def _check_integrity(connection: sqlite3.Connection) -> None:
    integrity_rows = connection.execute("pragma integrity_check").fetchall()
    integrity = [str(row[0]) for row in integrity_rows]
    if integrity != ["ok"]:
        raise DatabaseIntegrityError("SQLite integrity_check failed: " + "; ".join(integrity))
    foreign_rows = connection.execute("pragma foreign_key_check").fetchall()
    if foreign_rows:
        detail = "; ".join(str(tuple(row)) for row in foreign_rows[:20])
        raise DatabaseIntegrityError(f"SQLite foreign_key_check failed: {detail}")


def _fsync_directory(path: Path) -> None:
    """Persist directory-entry changes where the platform exposes directory fsync."""

    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _backup_database(
    path: Path,
    version: int,
    backup_dir: Path | None,
    *,
    source_connection: sqlite3.Connection | None = None,
) -> Path:
    if source_connection is not None and source_connection.in_transaction:
        raise MigrationError(
            "Cannot back up a database from inside an active migration transaction"
        )
    source = source_connection or sqlite3.connect(str(path), timeout=5.0)
    owns_source = source_connection is None
    target_dir = backup_dir or path.with_name(f"{path.name}.seam-backups")
    backup_path = target_dir / (
        f"{path.stem}.pre-migration-v{version}-{uuid4().hex}.sqlite3"
    )
    temporary_path = target_dir / f".{backup_path.name}.partial-{uuid4().hex}"
    target_dir_existed = target_dir.exists()
    published = False
    destination: sqlite3.Connection | None = None
    try:
        target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != "nt":
            target_dir.chmod(0o700)
        descriptor = os.open(
            temporary_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        os.close(descriptor)
        destination = sqlite3.connect(str(temporary_path))
        source.backup(destination)
        _check_integrity(destination)
        destination.close()
        destination = None
        if os.name != "nt":
            temporary_path.chmod(0o600)
        with temporary_path.open("rb+") as backup_file:
            os.fsync(backup_file.fileno())
        os.replace(temporary_path, backup_path)
        published = True
        _fsync_directory(target_dir)
        if not target_dir_existed:
            _fsync_directory(target_dir.parent)
        return backup_path
    except Exception as exc:
        if destination is not None:
            destination.close()
        temporary_path.unlink(missing_ok=True)
        if published:
            raise MigrationError(
                "A validated pre-migration backup was published, but its "
                "directory durability sync failed; migration did not start",
                backup_path=backup_path,
            ) from exc
        raise MigrationError(
            "Could not create a validated pre-migration backup; "
            "the database remains unmodified and no recovery backup is available"
        ) from exc
    finally:
        if owns_source:
            source.close()


def _record_step(connection: sqlite3.Connection, step: MigrationStep) -> None:
    connection.execute(
        f"insert into {MIGRATION_TABLE} (version, name, checksum, applied_at) values (?, ?, ?, ?)",
        (
            step.to_version,
            step.name,
            step.checksum,
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        ),
    )


def _apply_step(
    connection: sqlite3.Connection,
    step: MigrationStep,
    *,
    initialize_schema: SchemaInitializer,
    expected_projection_versions: Mapping[str, str],
) -> None:
    step.apply(connection, initialize_schema, expected_projection_versions)
    _record_step(connection, step)


def _projection_step_authorizer(
    action_code: int,
    argument_one: str | None,
    argument_two: str | None,
    _database_name: str | None,
    _trigger_name: str | None,
) -> int:
    if action_code in {sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT}:
        return sqlite3.SQLITE_DENY
    if (
        action_code == sqlite3.SQLITE_PRAGMA
        and argument_two is not None
        and (argument_one or "").casefold() in {"journal_mode", "locking_mode"}
    ):
        return sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_OK


def _apply_projection_migration(
    connection: sqlite3.Connection,
    migration: ProjectionMigration,
    current_projection_versions: Mapping[str, str],
    current_required_tables: Mapping[str, frozenset[str]],
) -> tuple[dict[str, str], dict[str, frozenset[str]]]:
    expected_before = {
        str(name): str(version) for name, version in current_projection_versions.items()
    }
    actual_before = _read_projection_rows(connection)
    if actual_before != expected_before:
        raise _unsupported_projection_registry(
            actual_before,
            expected_before,
            reason="projection registry changed after read-only preflight",
        )
    if actual_before.get(migration.projection_name) != migration.from_version:
        raise _unsupported_projection_registry(
            actual_before,
            expected_before,
            reason=(
                f"registered step {migration.name!r} expected "
                f"{migration.projection_name!r} at {migration.from_version!r}"
            ),
        )

    connection.set_authorizer(_projection_step_authorizer)
    try:
        migration.upgrade(ProjectionMigrationConnection(connection))
    finally:
        connection.set_authorizer(None)
    if not connection.in_transaction:
        raise MigrationError(
            f"Projection migration {migration.name!r} ended its transaction"
        )
    updated = connection.execute(
        f"update {PROJECTION_TABLE} set projection_version = ? "
        "where projection_name = ? and projection_version = ?",
        (
            migration.to_version,
            migration.projection_name,
            migration.from_version,
        ),
    )
    if updated.rowcount != 1:
        raise MigrationError(
            f"Projection migration {migration.name!r} could not advance its registry marker"
        )

    expected_after = dict(expected_before)
    expected_after[migration.projection_name] = migration.to_version
    actual_after = _read_projection_rows(connection)
    if actual_after != expected_after:
        raise MigrationError(
            f"Projection migration {migration.name!r} changed projection markers outside its registered transition"
        )
    expected_required_tables = dict(current_required_tables)
    expected_required_tables[migration.projection_name] = (
        migration.target_required_tables
    )
    _validate_required_table_contracts(connection, expected_required_tables)
    _validate_knowledge_graph_marker(
        connection,
        _user_tables(connection),
        actual_after,
        require_present=True,
    )
    return expected_after, expected_required_tables


def _set_exclusive_locking_mode(connection: sqlite3.Connection) -> None:
    row = connection.execute("pragma main.locking_mode=EXCLUSIVE").fetchone()
    if row is None or str(row[0]).casefold() != "exclusive":
        raise MigrationError(
            "SQLite refused the exclusive migration locking mode"
        )


def _assert_exclusive_locking_mode(connection: sqlite3.Connection) -> None:
    row = connection.execute("pragma main.locking_mode").fetchone()
    if row is None or str(row[0]).casefold() != "exclusive":
        raise MigrationError(
            "SQLite lost the exclusive migration locking mode"
        )


def _invoke_failure_injector(
    connection: sqlite3.Connection,
    failure_injector: FailureInjector,
    step: MigrationStep | ProjectionMigration,
) -> None:
    """Run the test hook without surrendering transaction or locking control."""

    connection.set_authorizer(_projection_step_authorizer)
    try:
        failure_injector(step, ProjectionMigrationConnection(connection))
    finally:
        connection.set_authorizer(None)


def _rollback_or_report_unknown(connection: sqlite3.Connection) -> bool:
    """Roll back an active step, failing honestly if SQLite cannot confirm it."""

    if not connection.in_transaction:
        return False
    try:
        connection.rollback()
    except Exception as exc:
        raise MigrationError(
            "SQLite could not confirm rollback of the active migration step; "
            "its commit state is unknown"
        ) from exc
    return True


def _run_migration_transaction(
    connection: sqlite3.Connection,
    operation: Callable[[], None],
) -> None:
    _assert_exclusive_locking_mode(connection)
    try:
        connection.execute("begin immediate")
    except Exception as exc:
        _rollback_or_report_unknown(connection)
        raise MigrationError(
            "SQLite could not begin the migration step; no step mutation was applied"
        ) from exc
    try:
        operation()
        if not connection.in_transaction:
            raise MigrationError(
                "The active migration transaction ended before the spine-owned "
                "commit; its commit state is unknown"
            )
        _assert_exclusive_locking_mode(connection)
    except MigrationError:
        _rollback_or_report_unknown(connection)
        raise
    except Exception as exc:
        if not _rollback_or_report_unknown(connection):
            raise MigrationError(
                "The active migration transaction ended outside spine control; "
                "its commit state is unknown"
            ) from None
        raise MigrationError(
            "The active migration step failed and was rolled back"
        ) from exc

    try:
        connection.commit()
    except Exception as exc:
        if not _rollback_or_report_unknown(connection):
            raise MigrationError(
                "SQLite commit failed after the active migration transaction "
                "ended; its commit state is unknown"
            ) from exc
        raise MigrationError(
            "SQLite commit failed and the active migration step was rolled back"
        ) from exc
    _assert_exclusive_locking_mode(connection)


def migrate_database(
    path: str | Path,
    *,
    initialize_schema: SchemaInitializer,
    expected_projection_versions: Mapping[str, str],
    failure_injector: FailureInjector | None = None,
    backup_dir: str | Path | None = None,
) -> MigrationResult:
    """Upgrade one file-backed store through every supported migration step."""

    database_path = Path(path).expanduser().resolve()
    projection_migrations = tuple(PROJECTION_MIGRATIONS)
    initial_version, current_projection_versions, projection_plan = _inspect_database(
        database_path,
        expected_projection_versions=expected_projection_versions,
        projection_migrations=projection_migrations,
    )
    if initial_version == CURRENT_SCHEMA_VERSION and not projection_plan:
        return MigrationResult(initial_version, initial_version, (), None)

    had_database_bytes = database_path.exists() and bool(database_path.stat().st_size)
    backup_path = None
    connection = sqlite3.connect(str(database_path), timeout=5.0)
    connection.row_factory = sqlite3.Row
    applied: list[str] = []
    active_step: MigrationStep | ProjectionMigration | None = None
    try:
        # This must be the migration connection's first SQL statement. In
        # exclusive locking mode SQLite retains the database lock across the
        # per-step commits below, preserving both writer exclusion and the
        # durable resume point after every completed step.
        _set_exclusive_locking_mode(connection)
        connection.execute("pragma busy_timeout=5000")
        connection.execute("pragma foreign_keys=ON")
        try:
            connection.execute("begin exclusive")
        except Exception as exc:
            _rollback_or_report_unknown(connection)
            raise MigrationError(
                "SQLite could not acquire the exclusive migration lock; "
                "migration did not start"
            ) from exc
        try:
            current_required_tables = _revalidate_locked_preflight(
                connection,
                initial_version=initial_version,
                preflight_projection_versions=current_projection_versions,
                preflight_projection_plan=projection_plan,
                expected_projection_versions=expected_projection_versions,
                projection_migrations=projection_migrations,
            )
            _check_integrity(connection)
        except MigrationError:
            _rollback_or_report_unknown(connection)
            raise
        except Exception as exc:
            try:
                _rollback_or_report_unknown(connection)
            except MigrationError as rollback_error:
                raise rollback_error from exc
            raise MigrationError(
                "Locked migration preflight failed and was rolled back; "
                "migration did not start"
            ) from exc
        try:
            connection.commit()
        except Exception as exc:
            _rollback_or_report_unknown(connection)
            raise MigrationError(
                "SQLite could not complete locked migration preflight; "
                "migration did not start"
            ) from exc
        _assert_exclusive_locking_mode(connection)
        if had_database_bytes:
            backup_path = _backup_database(
                database_path,
                initial_version,
                Path(backup_dir).resolve() if backup_dir is not None else None,
                source_connection=connection,
            )

        for step in _STEPS:
            if step.from_version < initial_version:
                continue
            if step.from_version != initial_version + len(applied):
                raise MigrationError(
                    f"No contiguous migration from schema version {initial_version + len(applied)}",
                    backup_path=backup_path,
                )
            active_step = step

            def apply_central_step(step: MigrationStep = step) -> None:
                _apply_step(
                    connection,
                    step,
                    initialize_schema=initialize_schema,
                    expected_projection_versions=expected_projection_versions,
                )
                _validate_required_projection_tables(
                    connection,
                    expected_projection_versions,
                )
                if step.to_version == CURRENT_SCHEMA_VERSION:
                    _validate_projection_rows(
                        connection,
                        expected_projection_versions,
                    )
                    _validate_knowledge_graph_marker(
                        connection,
                        _user_tables(connection),
                        expected_projection_versions,
                        require_present=True,
                    )
                _check_integrity(connection)
                if failure_injector is not None:
                    _invoke_failure_injector(connection, failure_injector, step)

            _run_migration_transaction(
                connection,
                apply_central_step,
            )
            applied.append(step.name)

        if projection_plan:
            if current_projection_versions is None:  # pragma: no cover - internal invariant
                raise MigrationError("Projection migration plan has no preflight registry state")
            for projection_migration in projection_plan:
                active_step = projection_migration

                def apply_projection_step(
                    projection_migration: ProjectionMigration = projection_migration,
                ) -> None:
                    nonlocal current_projection_versions, current_required_tables
                    (
                        current_projection_versions,
                        current_required_tables,
                    ) = _apply_projection_migration(
                        connection,
                        projection_migration,
                        current_projection_versions,
                        current_required_tables,
                    )
                    _check_integrity(connection)
                    if failure_injector is not None:
                        _invoke_failure_injector(
                            connection,
                            failure_injector,
                            projection_migration,
                        )

                _run_migration_transaction(
                    connection,
                    apply_projection_step,
                )
                applied.append(projection_migration.name)

        final_version = _validate_migration_rows(connection)
        _validate_projection_rows(connection, expected_projection_versions)
        _validate_knowledge_graph_marker(
            connection,
            _user_tables(connection),
            expected_projection_versions,
            require_present=True,
        )
        _check_integrity(connection)
    except Exception as exc:
        if isinstance(exc, MigrationError):
            if exc.backup_path is None:
                exc.backup_path = backup_path
            raise
        try:
            rolled_back = _rollback_or_report_unknown(connection)
        except MigrationError as rollback_error:
            if rollback_error.backup_path is None:
                rollback_error.backup_path = backup_path
            raise rollback_error from exc
        failed_name = active_step.name if active_step is not None else "preflight"
        earlier_steps = (
            "earlier completed steps remain applied"
            if applied
            else "no migration step was committed"
        )
        recovery_guidance = (
            "Restore the retained pre-migration backup for full recovery"
            if backup_path is not None
            else "No pre-migration backup was created"
        )
        if not rolled_back:
            raise MigrationError(
                f"Migration validation after {failed_name!r} failed outside an "
                f"active transaction; no rollback was performed and {earlier_steps}. "
                f"{recovery_guidance}: {exc}",
                backup_path=backup_path,
            ) from exc
        raise MigrationError(
            f"Migration step {failed_name!r} failed and was rolled back; "
            f"{earlier_steps}. {recovery_guidance}: {exc}",
            backup_path=backup_path,
        ) from exc
    finally:
        connection.close()

    return MigrationResult(
        initial_version,
        final_version,
        tuple(applied),
        backup_path,
    )


def migrate_memory_database(
    connection: sqlite3.Connection,
    *,
    initialize_schema: SchemaInitializer,
    expected_projection_versions: Mapping[str, str],
) -> MigrationResult:
    """Initialize an isolated in-memory store through the same registered steps."""

    applied: list[str] = []
    connection.execute("pragma foreign_keys=ON")
    for step in _STEPS:
        connection.execute("begin immediate")
        try:
            _apply_step(
                connection,
                step,
                initialize_schema=initialize_schema,
                expected_projection_versions=expected_projection_versions,
            )
            _check_integrity(connection)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        applied.append(step.name)
    return MigrationResult(0, CURRENT_SCHEMA_VERSION, tuple(applied), None)


def restore_database_backup(path: str | Path, backup_path: str | Path) -> None:
    """Validate and atomically restore one pre-migration SQLite backup.

    The caller must close every runtime using ``path`` before restore. SQLite
    sidecars are removed only at this explicit recovery boundary so a WAL from
    the replaced database cannot be replayed over the recovered bytes.
    """

    database_path = Path(path).expanduser().resolve()
    source_path = Path(backup_path).expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"migration backup not found: {source_path}")
    with sqlite3.connect(str(source_path)) as source:
        _check_integrity(source)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{database_path.name}.restore-",
        suffix=".sqlite3",
        dir=database_path.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        shutil.copyfile(source_path, temporary_path)
        if os.name != "nt":
            temporary_path.chmod(0o600)
        with temporary_path.open("rb") as temporary_file:
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, database_path)
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(f"{database_path}{suffix}")
            if sidecar.exists():
                sidecar.unlink()
        if os.name != "nt":
            directory_fd = os.open(database_path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
