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
from collections.abc import Callable, Mapping
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


@dataclass(frozen=True, slots=True)
class MigrationStep:
    from_version: int
    to_version: int
    name: str

    @property
    def checksum(self) -> str:
        material = f"{self.from_version}:{self.to_version}:{self.name}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class MigrationResult:
    initial_version: int
    final_version: int
    applied_steps: tuple[str, ...]
    backup_path: Path | None


_STEPS: Final = (
    MigrationStep(0, 1, "initialize-versioned-core"),
    MigrationStep(1, 2, "register-durable-projections"),
)
_STEP_BY_TARGET: Final = {step.to_version: step for step in _STEPS}

SchemaInitializer = Callable[[sqlite3.Connection], None]
FailureInjector = Callable[[MigrationStep, sqlite3.Connection], None]


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


def _validate_projection_rows(
    connection: sqlite3.Connection,
    expected_projection_versions: Mapping[str, str],
) -> None:
    tables = _user_tables(connection)
    if PROJECTION_TABLE not in tables:
        raise UnsupportedDatabaseVersionError(
            "Current SEAM database is missing its projection-version registry; refusing to modify database"
        )
    try:
        actual = {
            str(row[0]): str(row[1])
            for row in connection.execute(
                f"select projection_name, projection_version from {PROJECTION_TABLE}"
            ).fetchall()
        }
    except sqlite3.Error as exc:
        raise UnsupportedDatabaseVersionError(
            "Unrecognized projection-version registry; refusing to modify database"
        ) from exc
    expected = dict(expected_projection_versions)
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(name for name in set(actual) & set(expected) if actual[name] != expected[name])
        detail = f"missing={missing}, extra={extra}, changed={changed}"
        raise UnsupportedDatabaseVersionError(
            f"Unsupported durable projection registry ({detail}); refusing to modify database"
        )
    _validate_required_projection_tables(connection, expected)


def _validate_required_projection_tables(
    connection: sqlite3.Connection,
    expected_projection_versions: Mapping[str, str],
) -> None:
    tables = _user_tables(connection)
    missing_tables = {
        name: sorted(required - tables)
        for name, required in _REQUIRED_PROJECTION_TABLES.items()
        if name in expected_projection_versions and required - tables
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


def inspect_database(
    path: str | Path,
    *,
    expected_projection_versions: Mapping[str, str],
) -> int:
    """Return the supported schema version without changing database bytes."""

    database_path = Path(path)
    if not database_path.exists() or database_path.stat().st_size == 0:
        return 0
    try:
        with _readonly_connection(database_path) as connection:
            tables = _user_tables(connection)
            if not tables:
                return 0
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
                return 0
            version = _validate_migration_rows(connection)
            if version == CURRENT_SCHEMA_VERSION:
                _validate_projection_rows(connection, expected_projection_versions)
                _validate_knowledge_graph_marker(
                    connection,
                    tables,
                    expected_projection_versions,
                    require_present=True,
                )
            return version
    except sqlite3.DatabaseError as exc:
        raise UnsupportedDatabaseVersionError(
            "Database is not a readable supported SEAM SQLite store; refusing to modify database"
        ) from exc


def _check_integrity(connection: sqlite3.Connection) -> None:
    integrity_rows = connection.execute("pragma integrity_check").fetchall()
    integrity = [str(row[0]) for row in integrity_rows]
    if integrity != ["ok"]:
        raise DatabaseIntegrityError("SQLite integrity_check failed: " + "; ".join(integrity))
    foreign_rows = connection.execute("pragma foreign_key_check").fetchall()
    if foreign_rows:
        detail = "; ".join(str(tuple(row)) for row in foreign_rows[:20])
        raise DatabaseIntegrityError(f"SQLite foreign_key_check failed: {detail}")


def _backup_database(path: Path, version: int, backup_dir: Path | None) -> Path:
    target_dir = backup_dir or path.with_name(f"{path.name}.seam-backups")
    target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        target_dir.chmod(0o700)
    backup_path = target_dir / (f"{path.stem}.pre-migration-v{version}-{uuid4().hex}.sqlite3")
    descriptor = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    source = sqlite3.connect(str(path), timeout=5.0)
    destination = sqlite3.connect(str(backup_path))
    try:
        source.backup(destination)
        _check_integrity(destination)
    finally:
        destination.close()
        source.close()
    if os.name != "nt":
        backup_path.chmod(0o600)
    return backup_path


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
    if step.to_version == 1:
        initialize_schema(connection)
        connection.execute(
            f"create table {MIGRATION_TABLE} ("
            "version integer primary key check (version >= 1), "
            "name text not null unique, "
            "checksum text not null, "
            "applied_at text not null)"
        )
    elif step.to_version == 2:
        connection.execute(
            f"create table {PROJECTION_TABLE} (projection_name text primary key, projection_version text not null)"
        )
        connection.executemany(
            f"insert into {PROJECTION_TABLE} (projection_name, projection_version) values (?, ?)",
            sorted(expected_projection_versions.items()),
        )
    else:  # pragma: no cover - guarded by the static step registry
        raise MigrationError(f"No implementation for migration {step.name}")
    _record_step(connection, step)


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
    initial_version = inspect_database(
        database_path,
        expected_projection_versions=expected_projection_versions,
    )
    if initial_version == CURRENT_SCHEMA_VERSION:
        return MigrationResult(initial_version, initial_version, (), None)

    backup_path = None
    if database_path.exists() and database_path.stat().st_size:
        backup_path = _backup_database(
            database_path,
            initial_version,
            Path(backup_dir).resolve() if backup_dir is not None else None,
        )

    connection = sqlite3.connect(str(database_path), timeout=5.0)
    connection.row_factory = sqlite3.Row
    applied: list[str] = []
    active_step: MigrationStep | None = None
    try:
        connection.execute("pragma busy_timeout=5000")
        connection.execute("pragma foreign_keys=ON")
        for step in _STEPS:
            if step.from_version < initial_version:
                continue
            if step.from_version != initial_version + len(applied):
                raise MigrationError(
                    f"No contiguous migration from schema version {initial_version + len(applied)}",
                    backup_path=backup_path,
                )
            active_step = step
            connection.execute("begin immediate")
            try:
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
                    failure_injector(step, connection)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            applied.append(step.name)
        final_version = _validate_migration_rows(connection)
        _validate_projection_rows(connection, expected_projection_versions)
        _check_integrity(connection)
    except Exception as exc:
        if isinstance(exc, MigrationError):
            if exc.backup_path is None:
                exc.backup_path = backup_path
            raise
        failed_name = active_step.name if active_step is not None else "preflight"
        raise MigrationError(
            f"Migration step {failed_name!r} failed and was rolled back; "
            f"earlier committed steps remain applied. Restore the retained "
            f"pre-migration backup for full recovery: {exc}",
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
