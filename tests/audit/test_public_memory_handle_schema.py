"""Fail-closed schema and row contracts for the public handle projection."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

import pytest

from seam_runtime.migrations import DatabaseIntegrityError
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.storage import SQLiteStore

TENANT_ID = "principal:" + ("a" * 64)
NAMESPACE = f"{TENANT_ID}.sdk.default"
SCOPE = "thread"
HANDLE_ID = "mem_" + ("b" * 24)
RECORD_ID = "meta:public-handle-contract"
GENERATION = "c" * 64


def _create_handle_store(path: Path) -> None:
    store = SQLiteStore(path)
    try:
        store.persist_ir(
            IRBatch(
                [
                    MIRLRecord(
                        id=RECORD_ID,
                        kind=RecordKind.META,
                        ns=NAMESPACE,
                        scope=SCOPE,
                        attrs={"key": "public-handle", "value": "contract"},
                        ext={"public_memory_generation": GENERATION},
                    )
                ]
            )
        )
        store.register_public_memory_handles(
            tenant_id=TENANT_ID,
            namespace=NAMESPACE,
            scope=SCOPE,
            handles={HANDLE_ID: (RECORD_ID, GENERATION)},
        )
    finally:
        store.close()


def _replacement_table(
    *,
    tenant_column: str = "tenant_id text not null",
    handle_column: str = "handle_id text primary key",
    extra_column: str = "",
    on_delete: str = "cascade",
    schema_version_default: str = "1",
) -> str:
    return f"""
        drop table public_memory_handle;
        create table public_memory_handle (
            {handle_column},
            {tenant_column},
            ns text not null,
            scope text not null,
            record_id text not null,
            generation text not null,
            created_at text not null,
            contract_version text not null,
            schema_version integer not null default {schema_version_default}
            {extra_column},
            foreign key (record_id) references ir_records(id)
                on delete {on_delete}
        );
        create index idx_public_memory_handle_boundary
            on public_memory_handle (tenant_id, ns, scope, handle_id);
    """


def _extra_column(connection: sqlite3.Connection) -> None:
    connection.executescript(_replacement_table(extra_column=", unexpected text"))


def _nullable_tenant(connection: sqlite3.Connection) -> None:
    connection.executescript(_replacement_table(tenant_column="tenant_id text"))


def _missing_primary_key(connection: sqlite3.Connection) -> None:
    connection.executescript(
        _replacement_table(handle_column="handle_id text not null")
    )


def _restricting_foreign_key(connection: sqlite3.Connection) -> None:
    connection.executescript(_replacement_table(on_delete="restrict"))


def _wrong_boundary_index(connection: sqlite3.Connection) -> None:
    connection.execute("drop index idx_public_memory_handle_boundary")
    connection.execute(
        "create index idx_public_memory_handle_boundary "
        "on public_memory_handle (tenant_id, ns, handle_id, scope)"
    )


def _wrong_schema_version_default(connection: sqlite3.Connection) -> None:
    connection.executescript(_replacement_table(schema_version_default="999"))


def _unexpected_unique_record_index(connection: sqlite3.Connection) -> None:
    connection.execute(
        "create unique index unexpected_public_handle_record "
        "on public_memory_handle (record_id)"
    )


def _unexpected_trigger(connection: sqlite3.Connection) -> None:
    connection.execute(
        "create trigger unexpected_public_handle_trigger "
        "before insert on public_memory_handle begin select raise(ignore); end"
    )


@pytest.mark.parametrize(
    "corrupt",
    [
        pytest.param(_extra_column, id="exact-columns"),
        pytest.param(_nullable_tenant, id="nullability"),
        pytest.param(_missing_primary_key, id="primary-key"),
        pytest.param(_restricting_foreign_key, id="foreign-key-cascade"),
        pytest.param(_wrong_boundary_index, id="boundary-index"),
        pytest.param(_wrong_schema_version_default, id="schema-version-default"),
        pytest.param(_unexpected_unique_record_index, id="unexpected-unique-index"),
        pytest.param(_unexpected_trigger, id="unexpected-trigger"),
    ],
)
def test_core_storage_four_rejects_corrupt_public_handle_schema_without_writes(
    tmp_path: Path,
    corrupt: Callable[[sqlite3.Connection], None],
) -> None:
    path = tmp_path / "corrupt-handle-schema.db"
    _create_handle_store(path)
    with sqlite3.connect(path) as connection:
        corrupt(connection)
        assert connection.execute(
            "select projection_version from seam_projection_versions "
            "where projection_name = 'core_storage'"
        ).fetchone() == ("core-storage/4",)

    before_bytes = path.read_bytes()
    backup_dir = tmp_path / "unexpected-backups"
    with pytest.raises(
        DatabaseIntegrityError,
        match="core-storage/4 public-memory-handle schema is invalid",
    ):
        SQLiteStore(path, _migration_backup_dir=backup_dir)

    assert path.read_bytes() == before_bytes
    assert not backup_dir.exists()


@pytest.mark.parametrize(
    ("column", "value"),
    [
        pytest.param("contract_version", "public-memory-handle/999", id="contract-version"),
        pytest.param("schema_version", 999, id="schema-version"),
        pytest.param("tenant_id", "principal:foreign", id="tenant-namespace"),
        pytest.param("ns", f"{TENANT_ID}.sdk.other", id="record-namespace"),
        pytest.param("scope", "project", id="record-scope"),
        pytest.param("handle_id", "not-an-opaque-handle", id="handle-format"),
        pytest.param("record_id", "meta:missing-record", id="missing-record"),
        pytest.param("generation", "not-a-generation", id="generation-format"),
    ],
)
def test_core_storage_four_rejects_invalid_public_handle_rows_without_writes(
    tmp_path: Path,
    column: str,
    value: object,
) -> None:
    path = tmp_path / "corrupt-handle-row.db"
    _create_handle_store(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            f"update public_memory_handle set {column} = ?",  # noqa: S608 - fixed test parameters
            (value,),
        )
        assert connection.execute(
            "select projection_version from seam_projection_versions "
            "where projection_name = 'core_storage'"
        ).fetchone() == ("core-storage/4",)

    before_bytes = path.read_bytes()
    backup_dir = tmp_path / "unexpected-backups"
    with pytest.raises(
        DatabaseIntegrityError,
        match="core-storage/4 public-memory-handle schema is invalid",
    ) as raised:
        SQLiteStore(path, _migration_backup_dir=backup_dir)

    assert RECORD_ID not in str(raised.value)
    assert HANDLE_ID not in str(raised.value)
    assert path.read_bytes() == before_bytes
    assert not backup_dir.exists()


def test_core_storage_four_accepts_exact_public_handle_contract(tmp_path: Path) -> None:
    path = tmp_path / "valid-handle-schema.db"
    _create_handle_store(path)

    reopened = SQLiteStore(path)
    try:
        assert reopened.migration_result.applied_steps == ()
    finally:
        reopened.close()


def test_core_storage_three_rejects_preexisting_handle_table_before_backup(
    tmp_path: Path,
) -> None:
    path = tmp_path / "preexisting-handle-target.db"
    store = SQLiteStore(path)
    store.close()
    with sqlite3.connect(path) as connection:
        connection.execute(
            "update seam_projection_versions set projection_version = "
            "'core-storage/3' where projection_name = 'core_storage'"
        )

    before_bytes = path.read_bytes()
    backup_dir = tmp_path / "unexpected-preflight-backups"
    with pytest.raises(
        DatabaseIntegrityError,
        match="target tables are unexpectedly present",
    ):
        SQLiteStore(path, _migration_backup_dir=backup_dir)

    assert path.read_bytes() == before_bytes
    assert not backup_dir.exists()


def test_handle_projection_preserves_nonblank_canonical_record_id_bytes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "opaque-record-id.db"
    record_id = "  meta:opaque-record-id  "
    store = SQLiteStore(path)
    try:
        store.persist_ir(
            IRBatch(
                [
                    MIRLRecord(
                        id=record_id,
                        kind=RecordKind.META,
                        ns=NAMESPACE,
                        scope=SCOPE,
                        attrs={"key": "opaque-record-id", "value": "preserved"},
                        ext={"public_memory_generation": GENERATION},
                    )
                ]
            )
        )
        store.register_public_memory_handles(
            tenant_id=TENANT_ID,
            namespace=NAMESPACE,
            scope=SCOPE,
            handles={HANDLE_ID: (record_id, GENERATION)},
        )
        assert store.resolve_public_memory_handles(
            tenant_id=TENANT_ID,
            namespace=NAMESPACE,
            scope=SCOPE,
            handle_ids=[HANDLE_ID],
        ) == {HANDLE_ID: (record_id, GENERATION)}
    finally:
        store.close()

    reopened = SQLiteStore(path)
    reopened.close()


def test_registration_does_not_silently_ignore_unexpected_unique_conflicts(
    tmp_path: Path,
) -> None:
    path = tmp_path / "live-unique-handle-conflict.db"
    _create_handle_store(path)
    store = SQLiteStore(path)
    rotated_handle = "mem_" + ("c" * 24)
    try:
        with sqlite3.connect(path) as connection:
            _unexpected_unique_record_index(connection)

        with pytest.raises(sqlite3.IntegrityError):
            store.register_public_memory_handles(
                tenant_id=TENANT_ID,
                namespace=NAMESPACE,
                scope=SCOPE,
                handles={rotated_handle: (RECORD_ID, GENERATION)},
            )
        assert store.resolve_public_memory_handles(
            tenant_id=TENANT_ID,
            namespace=NAMESPACE,
            scope=SCOPE,
            handle_ids=[rotated_handle],
        ) == {}
    finally:
        store.close()


def test_registration_verifies_postcondition_against_live_ignore_trigger(
    tmp_path: Path,
) -> None:
    path = tmp_path / "live-ignore-trigger.db"
    _create_handle_store(path)
    store = SQLiteStore(path)
    rotated_handle = "mem_" + ("d" * 24)
    try:
        with sqlite3.connect(path) as connection:
            _unexpected_trigger(connection)

        with pytest.raises(RuntimeError, match="registration failed"):
            store.register_public_memory_handles(
                tenant_id=TENANT_ID,
                namespace=NAMESPACE,
                scope=SCOPE,
                handles={rotated_handle: (RECORD_ID, GENERATION)},
            )
        assert store.resolve_public_memory_handles(
            tenant_id=TENANT_ID,
            namespace=NAMESPACE,
            scope=SCOPE,
            handle_ids=[rotated_handle],
        ) == {}
    finally:
        store.close()
