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
