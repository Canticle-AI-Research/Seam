"""Live pgvector coverage for vector-text render-contract migration."""

from __future__ import annotations

import hashlib
import os
import uuid

import pytest

from seam_runtime.mirl import MIRLRecord, RecordKind
from seam_runtime.vector import LEGACY_VECTOR_TEXT_VERSION, VECTOR_TEXT_VERSION

pytestmark = [
    pytest.mark.external,
    pytest.mark.skipif(
        not (os.environ.get("PGVECTOR_TEST_DSN") or os.environ.get("SEAM_PGVECTOR_DSN")),
        reason="pgvector test DSN not set",
    ),
]


class _CountingEmbeddingModel:
    name = "render-contract-counting"
    dimension = 8

    def __init__(self) -> None:
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [((digest[index] / 255.0) * 2.0) - 1.0 for index in range(8)]


def _make_record(
    *,
    namespace: str = "legacy-ns",
    scope: str = "legacy-scope",
) -> MIRLRecord:
    return MIRLRecord(
        id="clm:render-contract",
        kind=RecordKind.CLM,
        ns=namespace,
        scope=scope,
        attrs={
            "subject": "SEAM",
            "predicate": "supports",
            "object": "deterministic vectors",
        },
    )


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


def _make_legacy_adapter():
    import psycopg

    from seam_runtime.vector_adapters import PgVectorAdapter

    dsn = os.environ.get("PGVECTOR_TEST_DSN") or os.environ["SEAM_PGVECTOR_DSN"]
    table = f"seam_vector_render_test_{uuid.uuid4().hex[:12]}"
    model = _CountingEmbeddingModel()
    record = _make_record()
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute("create extension if not exists vector")
            cursor.execute(
                f"""
                create table {table} (
                    record_id text not null,
                    model_name text not null,
                    dimension integer not null,
                    source_text text not null,
                    source_hash text not null default '',
                    namespace text not null default '',
                    scope text not null default '',
                    embedding vector not null,
                    updated_at text not null,
                    primary key (record_id, model_name)
                )
                """
            )
            cursor.execute(
                f"""
                insert into {table}
                    (record_id, model_name, dimension, source_text, source_hash,
                     namespace, scope, embedding, updated_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s::vector, %s)
                """,
                (
                    record.id,
                    model.name,
                    model.dimension,
                    "legacy text",
                    "legacy-source-hash",
                    record.ns,
                    record.scope,
                    _vector_literal([0.25] * model.dimension),
                    record.updated_at,
                ),
            )
        connection.commit()
    return (
        PgVectorAdapter(dsn=dsn, model=model, table_name=table),
        table,
        model,
        record,
    )


def _drop_table(adapter, table: str) -> None:
    with adapter._connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(f'drop table if exists "{table}"')
        connection.commit()


def test_additive_migration_stamps_existing_rows_legacy_without_embedding():
    adapter, table, model, record = _make_legacy_adapter()
    try:
        adapter.ensure_schema()

        with adapter._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"select render_version from {table} "
                    "where record_id = %s and model_name = %s",
                    (record.id, model.name),
                )
                stored_version = cursor.fetchone()[0]
                cursor.execute(
                    """
                    select column_default
                    from information_schema.columns
                    where table_name = %s and column_name = 'render_version'
                    """,
                    (table,),
                )
                column_default = cursor.fetchone()[0]

        assert stored_version == LEGACY_VECTOR_TEXT_VERSION
        assert VECTOR_TEXT_VERSION in column_default
        assert model.calls == []
    finally:
        _drop_table(adapter, table)


def test_search_excludes_legacy_render_versions():
    adapter, table, model, _record = _make_legacy_adapter()
    try:
        adapter.ensure_schema()

        assert adapter.search("legacy text", limit=5) == {}
        assert model.calls == ["legacy text"]
    finally:
        _drop_table(adapter, table)


def test_stale_records_prioritizes_render_version_over_source_change():
    adapter, table, model, record = _make_legacy_adapter()
    try:
        adapter.ensure_schema()

        assert adapter.stale_records([record]) == [
            {
                "record_id": record.id,
                "reason": "render_version_changed",
            }
        ]
        assert model.calls == []
    finally:
        _drop_table(adapter, table)


def test_full_index_upgrades_legacy_once_then_reuses_current_vector():
    adapter, table, model, record = _make_legacy_adapter()
    try:
        adapter.index_records([record])
        assert len(model.calls) == 1

        with adapter._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"select render_version, source_text, source_hash "
                    f"from {table} where record_id = %s and model_name = %s",
                    (record.id, model.name),
                )
                render_version, source_text, source_hash = cursor.fetchone()

        assert render_version == VECTOR_TEXT_VERSION
        assert source_hash == hashlib.sha256(source_text.encode("utf-8")).hexdigest()
        assert adapter.stale_records([record]) == []

        adapter.index_records([record])
        assert len(model.calls) == 1
    finally:
        _drop_table(adapter, table)


def test_boundary_sync_skips_legacy_version_without_embedding_or_update():
    adapter, table, model, record = _make_legacy_adapter()
    try:
        adapter.ensure_schema()
        moved = _make_record(namespace="current-ns", scope="current-scope")

        result = adapter.sync_boundaries([moved])

        assert result == {
            "updated": [],
            "already_ok": 0,
            "skipped_missing": [],
            "skipped_render_version": [record.id],
            "skipped_content_changed": [],
        }
        assert model.calls == []
        with adapter._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"select namespace, scope from {table} "
                    "where record_id = %s and model_name = %s",
                    (record.id, model.name),
                )
                assert cursor.fetchone() == (record.ns, record.scope)
    finally:
        _drop_table(adapter, table)
