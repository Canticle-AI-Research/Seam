"""Tests for PgVector composite primary key (record_id, model_name)."""
import os
import uuid

import pytest

# external: hits the real pgvector service; deselected with -m "not external" in
# jobs without it, RUN with PGVECTOR_TEST_DSN set in the pgvector CI job.
pytestmark = [
    pytest.mark.external,
    pytest.mark.skipif(
        not os.environ.get("PGVECTOR_TEST_DSN"),
        reason="PGVECTOR_TEST_DSN not set",
    ),
]


def _vector_literal_64(vector):
    return "[" + ",".join(f"{float(value):.8f}" for value in vector) + "]"


def _create_old_schema(connection, table):
    """Create the pre-#218 schema with single-column PK (record_id)."""
    with connection.cursor() as cursor:
        cursor.execute("create extension if not exists vector")
        cursor.execute(
            f"""
            create table if not exists {table} (
                record_id text primary key,
                model_name text not null,
                dimension integer not null,
                source_text text not null,
                source_hash text not null default '',
                embedding vector(3) not null,
                updated_at text not null
            )
            """
        )
    connection.commit()


def _insert_row_old_schema(connection, table, record_id, model_name, vector_vals):
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            insert into {table} (record_id, model_name, dimension, source_text, source_hash, embedding, updated_at)
            values (%s, %s, %s, %s, %s, %s::vector, %s)
            on conflict (record_id) do nothing
            """,
            (record_id, model_name, 3, "test text", "abc", _vector_literal_64(vector_vals), "2025-01-01T00:00:00Z"),
        )
    connection.commit()


class TestPgVectorCompositePK:
    def test_composite_pk_allows_two_models_same_record(self):
        from seam_runtime.models import HashEmbeddingModel
        from seam_runtime.vector_adapters import PgVectorAdapter

        dsn = os.environ["PGVECTOR_TEST_DSN"]
        table = f"seam_vector_pk_test_{uuid.uuid4().hex[:12]}"

        model_a = HashEmbeddingModel(name="model-a", dimension=64)
        adapter_a = PgVectorAdapter(dsn=dsn, model=model_a, table_name=table)

        try:
            adapter_a.ensure_schema()

            with adapter_a._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"""
                        insert into {table} (record_id, model_name, dimension, source_text, source_hash, embedding, updated_at)
                        values (%s, %s, %s, %s, %s, %s::vector, %s)
                        on conflict (record_id, model_name) do nothing
                        """,
                        ("test-record-1", "model-a", 64, "source text", "hash123", _vector_literal_64([0.1] * 64), "2025-01-01T00:00:00Z"),
                    )
                    cursor.execute(
                        f"""
                        insert into {table} (record_id, model_name, dimension, source_text, source_hash, embedding, updated_at)
                        values (%s, %s, %s, %s, %s, %s::vector, %s)
                        on conflict (record_id, model_name) do nothing
                        """,
                        ("test-record-1", "model-b", 64, "source text", "hash123", _vector_literal_64([0.2] * 64), "2025-01-01T00:00:00Z"),
                    )
                connection.commit()

            count = adapter_a.vector_count()
            assert count == 2, f"Expected 2 rows (one per model_name), got {count}"

            with adapter_a._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"select model_name from {table} where record_id = %s order by model_name",
                        ("test-record-1",),
                    )
                    model_names = [r[0] for r in cursor.fetchall()]
            assert model_names == ["model-a", "model-b"], f"Expected both model names, got {model_names}"

        finally:
            with adapter_a._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(f'drop table if exists "{table}"')
                connection.commit()

    def test_migration_old_single_pk_upgrades_to_composite(self):
        """ensure_schema() migrates old PRIMARY KEY (record_id) → (record_id, model_name)."""
        from seam_runtime.models import HashEmbeddingModel
        from seam_runtime.vector_adapters import PgVectorAdapter

        dsn = os.environ["PGVECTOR_TEST_DSN"]
        table = f"seam_vector_migrate_{uuid.uuid4().hex[:12]}"

        try:
            import psycopg
            conn = psycopg.connect(dsn)
            _create_old_schema(conn, table)
            _insert_row_old_schema(conn, table, "rec-1", "model-x", [0.1, 0.2, 0.3])
            _insert_row_old_schema(conn, table, "rec-2", "model-x", [0.4, 0.5, 0.6])
            conn.close()

            adapter = PgVectorAdapter(dsn=dsn, model=HashEmbeddingModel(name="model-x", dimension=3), table_name=table)
            adapter.ensure_schema()

            count = adapter.vector_count()
            assert count == 2, f"Rows should survive migration, got {count}"

            with adapter._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        select pg_get_constraintdef(c.oid)
                        from pg_constraint c
                        join pg_class t on c.conrelid = t.oid
                        where t.relname = %s and c.contype = 'p'
                        """,
                        (table,),
                    )
                    pk_def = cursor.fetchone()[0]
            assert "record_id" in pk_def and "model_name" in pk_def, (
                f"PK should be composite after migration, got {pk_def}"
            )

        finally:
            import psycopg
            conn = psycopg.connect(dsn)
            with conn.cursor() as cursor:
                cursor.execute(f'drop table if exists "{table}"')
            conn.commit()
            conn.close()

    def test_ensure_schema_idempotent_on_composite_pk(self):
        """Running ensure_schema() twice with composite PK is safe."""
        from seam_runtime.models import HashEmbeddingModel
        from seam_runtime.vector_adapters import PgVectorAdapter

        dsn = os.environ["PGVECTOR_TEST_DSN"]
        table = f"seam_vector_idem_{uuid.uuid4().hex[:12]}"

        try:
            adapter = PgVectorAdapter(dsn=dsn, model=HashEmbeddingModel(name="model-x", dimension=3), table_name=table)
            adapter.ensure_schema()
            adapter.ensure_schema()

            with adapter._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"select count(*) from {table}"
                    )
                    row_count = cursor.fetchone()[0]
            assert row_count == 0

        finally:
            import psycopg
            conn = psycopg.connect(dsn)
            with conn.cursor() as cursor:
                cursor.execute(f'drop table if exists "{table}"')
            conn.commit()
            conn.close()
