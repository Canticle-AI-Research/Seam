"""B2 — Real-postgres pgvector adapter integration test.

Skipped unless SEAM_PGVECTOR_DSN is set (locally without docker, this is
a no-op). In CI, the pgvector-integration job sets the DSN to a service
container running pgvector/pgvector:0.8.2-pg18-trixie.
"""

import os
import uuid

import pytest

pytestmark = [
    pytest.mark.external,
    pytest.mark.skipif(
        not os.environ.get("SEAM_PGVECTOR_DSN"),
        reason="SEAM_PGVECTOR_DSN not set; skipping real-postgres pgvector integration",
    ),
]


def _make_adapter():
    from seam_runtime.models import HashEmbeddingModel
    from seam_runtime.vector_adapters import PgVectorAdapter
    # Unique table name per test run to avoid cross-CI-job collisions.
    table = f"seam_vector_index_test_{uuid.uuid4().hex[:12]}"
    dsn = os.environ["SEAM_PGVECTOR_DSN"]
    return PgVectorAdapter(dsn=dsn, model=HashEmbeddingModel(), table_name=table), table


def _make_records():
    from seam_runtime.dsl import compile_dsl
    batch = compile_dsl(
        """
entity project "SEAM" as proj
claim c1:
  subject proj
  predicate supports
  object "databases"
claim c2:
  subject proj
  predicate supports
  object "context windows"
""",
        scope="project",
    )
    return batch.records


def _mutate_first_indexable_record(records):
    from seam_runtime.mirl import MIRLRecord, RecordKind

    mutated = []
    changed = False
    for record in records:
        if not changed and record.kind in {RecordKind.CLM, RecordKind.STA, RecordKind.EVT, RecordKind.REL}:
            data = record.to_dict()
            data["attrs"]["object"] = "mutated source text"
            mutated.append(MIRLRecord.from_dict(data))
            changed = True
        else:
            mutated.append(record)
    assert changed, "fixture must include at least one indexable record to mutate"
    return mutated


def _drop_table(adapter, table_name):
    with adapter._connect() as connection:
        with connection.cursor() as cursor:
            cursor.execute(f'drop table if exists "{table_name}"')
        connection.commit()


def test_pgvector_real_adapter_index_and_search():
    """End-to-end: ensure_schema -> index_records -> search returns scored hits."""
    adapter, table = _make_adapter()
    try:
        records = _make_records()
        adapter.index_records(records)
        scores = adapter.search("databases context windows", limit=5)
        assert len(scores) > 0, "Expected at least one scored hit"
        for record_id, score in scores.items():
            assert isinstance(score, float)
            assert score > 0.0
    finally:
        _drop_table(adapter, table)


def test_pgvector_real_adapter_upsert_idempotent():
    """Indexing the same records twice should not duplicate rows."""
    adapter, table = _make_adapter()
    try:
        records = _make_records()
        adapter.index_records(records)
        with adapter._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f'select count(*) from "{table}"')
                count_first = cursor.fetchone()[0]
        adapter.index_records(records)
        with adapter._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f'select count(*) from "{table}"')
                count_second = cursor.fetchone()[0]
        assert count_first == count_second, (
            f"Expected idempotent upsert; first={count_first}, second={count_second}"
        )
    finally:
        _drop_table(adapter, table)


def test_pgvector_real_adapter_stale_records_detects_changes():
    """stale_records reports source_changed when the source text mutates."""
    adapter, table = _make_adapter()
    try:
        records = _make_records()
        adapter.index_records(records)
        stale_initial = adapter.stale_records(records)
        assert stale_initial == [], f"Expected no stale records right after index, got {stale_initial}"
        mutated_records = _mutate_first_indexable_record(records)
        stale_after_mutation = adapter.stale_records(mutated_records)
        assert len(stale_after_mutation) == 1, f"Expected 1 stale record after mutation, got {stale_after_mutation}"
        assert stale_after_mutation[0]["reason"] == "source_changed"
        # The stale record_id should be one of the indexable (CLM/STA/EVT/REL) records that was mutated.
        indexable_ids = {r.id for r in mutated_records if r.kind.value in {"CLM", "STA", "EVT", "REL"}}
        assert stale_after_mutation[0]["record_id"] in indexable_ids
    finally:
        _drop_table(adapter, table)


def test_ensure_schema_creates_hnsw_partial_index_on_fresh_table():
    """ensure_schema() builds a dimension-scoped partial HNSW index and
    reports ann_index_status == "ok", without narrowing the shared
    dimensionless ``embedding`` column."""
    adapter, table = _make_adapter()
    try:
        adapter.ensure_schema()
        assert adapter.ann_index_status == "ok"
        with adapter._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("select indexdef from pg_indexes where tablename = %s", (table,))
                index_defs = [row[0] for row in cursor.fetchall()]
                cursor.execute(
                    """
                    select format_type(a.atttypid, a.atttypmod)
                    from pg_attribute a
                    join pg_class c on a.attrelid = c.oid
                    where c.relname = %s and a.attname = 'embedding' and a.attnum > 0 and not a.attisdropped
                    """,
                    (table,),
                )
                column_type = cursor.fetchone()[0]
        assert any("hnsw" in d.lower() for d in index_defs), f"Expected an hnsw index, got {index_defs}"
        assert column_type == "vector", (
            f"embedding column must stay dimensionless so other dimensions can still "
            f"share this table; got {column_type!r}"
        )
    finally:
        _drop_table(adapter, table)


def test_hnsw_index_coexists_across_dimensions_sharing_one_table():
    """Regression test: two embedding models at DIFFERENT dimensions sharing
    the same table_name must both be able to index and search their own rows.

    Prior to the partial-index fix, ensure_schema() ALTERed the shared
    ``embedding`` column to whichever dimension touched the table first,
    permanently breaking every other dimension's INSERTs against that table -
    a real regression for the common case of a shared default table_name
    used across runs with different embedding configs (e.g. a hash-embedding
    dev fallback vs. a real sentence-transformer model).
    """
    from seam_runtime.vector_adapters import PgVectorAdapter
    from seam_runtime.models import HashEmbeddingModel

    dsn = os.environ["SEAM_PGVECTOR_DSN"]
    table = f"seam_vector_index_test_{uuid.uuid4().hex[:12]}"
    model_a = HashEmbeddingModel(name="model-a", dimension=64)
    model_b = HashEmbeddingModel(name="model-b", dimension=32)
    adapter_a = PgVectorAdapter(dsn=dsn, model=model_a, table_name=table)
    adapter_b = PgVectorAdapter(dsn=dsn, model=model_b, table_name=table)
    try:
        records = _make_records()
        # model_a touches the table first (would have won the ALTER pre-fix).
        adapter_a.index_records(records)
        # model_b, a DIFFERENT dimension, must still be able to index into
        # the same shared table without a pgvector dimension-mismatch error.
        adapter_b.index_records(records)

        scores_a = adapter_a.search("databases context windows", limit=5)
        scores_b = adapter_b.search("databases context windows", limit=5)
        assert len(scores_a) > 0, "model_a search returned no hits"
        assert len(scores_b) > 0, "model_b search returned no hits"
        assert adapter_a.vector_count() == adapter_b.vector_count()
    finally:
        _drop_table(adapter_a, table)


def test_search_respects_ef_search_override():
    """A non-default ef_search is set via set_config before the ANN query
    runs, with the configured value (session GUCs can't be verified via a
    separate connection since they don't outlive the connection that set
    them, so this spies on the same connection search() uses)."""
    from seam_runtime.vector_adapters import PgVectorAdapter
    from seam_runtime.models import HashEmbeddingModel

    dsn = os.environ["SEAM_PGVECTOR_DSN"]
    table = f"seam_vector_index_test_{uuid.uuid4().hex[:12]}"
    adapter = PgVectorAdapter(dsn=dsn, model=HashEmbeddingModel(), table_name=table, ef_search=17)
    try:
        records = _make_records()
        adapter.index_records(records)

        calls: list[tuple[str, object]] = []
        original_connect = adapter._connect

        def _spying_connect():
            connection = original_connect()
            real_cursor_factory = connection.cursor

            def _spying_cursor(*args, **kwargs):
                cursor = real_cursor_factory(*args, **kwargs)
                real_execute = cursor.execute

                def _spying_execute(sql, params=None):
                    calls.append((sql, params))
                    return real_execute(sql, params) if params is not None else real_execute(sql)

                cursor.execute = _spying_execute
                return cursor

            connection.cursor = _spying_cursor
            return connection

        adapter._connect = _spying_connect
        scores = adapter.search("databases context windows", limit=5)

        set_config_calls = [(sql, params) for sql, params in calls if "set_config" in sql.lower()]
        assert set_config_calls, "expected search() to call set_config for hnsw.ef_search"
        assert set_config_calls[0][1] == ("17",)
        assert len(scores) > 0
    finally:
        adapter._connect = original_connect
        _drop_table(adapter, table)
