"""Public PostgreSQL vector exactness and optional ANN qualification."""

from __future__ import annotations

import hashlib
import json
import os
import tracemalloc
import uuid
from pathlib import Path

import pytest

from seam_runtime.mirl import MIRLRecord, RecordKind
from seam_runtime.models import cosine
from seam_runtime.vector_adapters import PgVectorAdapter

pytestmark = pytest.mark.external


class PrecisionModel:
    name = "r2-precision"
    dimension = 2

    def __init__(self):
        self.calls = []

    def embed(self, text):
        self.calls.append(text)
        if "tiny" in text:
            return [1e-18, 1.0]
        if "negative" in text:
            return [-1.0, 0.0]
        if "zero" in text:
            return [0.0, 0.0]
        if "better" in text:
            return [1.00000001, 1.0]
        if text == "query":
            return [1.0, 0.0]
        return [1.0, 1.0]


def record(record_id, text, namespace="wanted", scope="thread"):
    return MIRLRecord(id=record_id, kind=RecordKind.RAW, ns=namespace,
                      scope=scope, attrs={"content": text})


@pytest.fixture
def pg_adapter():
    adapter = PgVectorAdapter(
        os.environ["PGVECTOR_TEST_DSN"], PrecisionModel(),
        table_name="seam_r2_parity_" + uuid.uuid4().hex[:12],
    )
    yield adapter
    with adapter._connect() as connection:
        connection.execute(f"drop table if exists {adapter.table_name}")


def test_default_search_preserves_original_near_tie_winner_and_score(pg_adapter):
    pg_adapter.index_records([record("raw:a", "ordinary"), record("raw:z", "better")])
    assert pg_adapter.search("query", limit=1) == {"raw:z": 0.7071067847220813}


def test_missing_original_is_reported_and_explicit_reindex_repairs_once(pg_adapter):
    item = record("raw:z", "better")
    pg_adapter.index_records([item])
    with pg_adapter._connect() as connection:
        connection.execute(f"update {pg_adapter.table_name} set original_vector_json = null, "
                           "original_vector_version = ''")
    calls = len(pg_adapter.model.calls)
    assert pg_adapter.stale_records([item]) == [
        {"record_id": item.id, "reason": "original_vector_missing"}
    ]
    assert len(pg_adapter.model.calls) == calls
    with pytest.raises(RuntimeError, match="reindex"):
        pg_adapter.search("query")
    pg_adapter.index_records([item])
    after_repair = len(pg_adapter.model.calls)
    pg_adapter.index_records([item])
    assert len(pg_adapter.model.calls) == after_repair
    assert pg_adapter.stale_records([item]) == []
    assert pg_adapter.search("query") == {"raw:z": 0.7071067847220813}


def test_old_schema_search_requires_explicit_metadata_migration_and_reindex(pg_adapter):
    item = record("raw:z", "better")
    pg_adapter.index_records([item])
    with pg_adapter._connect() as connection:
        connection.execute(f"alter table {pg_adapter.table_name} drop column original_vector_json, "
                           "drop column original_vector_version")
    reader = PgVectorAdapter(pg_adapter.dsn, pg_adapter.model, table_name=pg_adapter.table_name)
    with pytest.raises(RuntimeError, match="reindex"):
        reader.search("query")
    calls = len(reader.model.calls)
    reader.ensure_schema()
    assert len(reader.model.calls) == calls
    with pytest.raises(RuntimeError, match="reindex"):
        reader.search("query")
    reader.index_records([item])
    assert reader.search("query") == {"raw:z": 0.7071067847220813}


class DenseModel:
    name = "r2-dense"
    dimension = 16

    def embed(self, text):
        data = hashlib.sha256(text.encode()).digest()
        return [(value - 127.5) / 127.5 for value in data[:self.dimension]]


class ConnectionSpy:
    def __init__(self, connection, calls):
        self.connection, self.calls = connection, calls

    def __enter__(self):
        self.connection.__enter__()
        return self

    def __exit__(self, *args):
        return self.connection.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def cursor(self, *args, **kwargs):
        return CursorSpy(self.connection.cursor(*args, **kwargs), self.calls)


class CursorSpy:
    def __init__(self, cursor, calls):
        self.cursor, self.calls = cursor, calls

    def __enter__(self):
        self.cursor.__enter__()
        return self

    def __exit__(self, *args):
        return self.cursor.__exit__(*args)

    def __getattr__(self, name):
        return getattr(self.cursor, name)

    def execute(self, query, params=None):
        self.calls.append((query, params))
        return self.cursor.execute(query, params)


def plan_indexes(node):
    found = [node["Index Name"]] if "Index Name" in node else []
    return found + [name for child in node.get("Plans", []) for name in plan_indexes(child)]


def plan_nodes(node):
    yield node
    for child in node.get("Plans", []):
        yield from plan_nodes(child)


@pytest.mark.parametrize("count", [2048, 8192])
def test_approximate_public_search_uses_unforced_hnsw_with_filtered_prepared_queries(count):
    from psycopg import sql

    model = DenseModel()
    adapter = PgVectorAdapter(os.environ["PGVECTOR_TEST_DSN"], model,
                              table_name="seam_r2_ann_" + uuid.uuid4().hex[:12],
                              search_mode="approximate", ef_search=100)
    records = [record(f"raw:{i:06}", f"document {i}",
                      "wanted" if i % 2 else "other") for i in range(count)]
    calls = []
    connect = adapter._connect
    try:
        adapter.index_records(records)
        with connect() as connection:
            connection.execute(f"analyze {adapter.table_name}")
        adapter._connect = lambda: ConnectionSpy(connect(), calls)
        scores = adapter.search("query", limit=4, namespace="wanted", scope="thread")
        assert len(scores) == 4
        originals = {r.id: model.embed(adapter_text(r)) for r in records}
        assert scores == {rid: cosine(model.embed("query"), originals[rid]) for rid in scores}
        assert list(scores) == sorted(scores, key=lambda rid: (-scores[rid], rid))
        statement, params = next((statement, params) for statement, params in calls
                                 if "select record_id" in str(statement).lower())
        plans = []
        with connect() as connection:
            for setting, values in calls:
                if "set_config" in str(setting).lower():
                    connection.execute(setting, values)
            for mode in ("auto", "force_generic_plan"):
                connection.execute("select set_config('plan_cache_mode', %s, true)", (mode,))
                for _ in range(7):
                    connection.execute(statement, params, prepare=True).fetchall()
                name = connection.execute(
                    "select name from pg_prepared_statements where statement like %s",
                    ("%select record_id%",),
                ).fetchone()[0]
                explain = sql.SQL("explain (analyze, buffers, format json) execute {} ({})").format(
                    sql.Identifier(name), sql.SQL(", ").join(map(sql.Literal, params)))
                plan = connection.execute(explain).fetchone()[0][0]
                assert f"{adapter.table_name}_hnsw_16_idx" in plan_indexes(plan["Plan"])
                plans.append({"plan_cache_mode": mode, "ef_search": adapter.ef_search,
                              "iterative_scan": "strict_order", "plan": plan})
        sink = Path("test_seam/r2-backend/pg")
        sink.mkdir(parents=True, exist_ok=True)
        (sink / f"plans-{count}.json").write_text(json.dumps(plans, indent=2) + "\n")
    finally:
        adapter._connect = connect
        with connect() as connection:
            connection.execute(f"drop table if exists {adapter.table_name}")


def adapter_text(item):
    from seam_runtime.vector import SQLiteVectorIndex
    return SQLiteVectorIndex.render_record_text(item)


@pytest.mark.parametrize("numpy_enabled", [False, True])
def test_exact_public_parity_across_cutoffs_boundaries_and_numeric_edges(
    pg_adapter, tmp_path, monkeypatch, numpy_enabled
):
    import seam_runtime.models as models_module
    import seam_runtime.vector as vector_module
    from seam_runtime.vector_adapters import SQLiteVectorAdapter

    if not numpy_enabled:
        monkeypatch.setattr(models_module, "_numpy", None)
        monkeypatch.setattr(vector_module, "_numpy", None)
    sqlite = SQLiteVectorAdapter(str(tmp_path / "parity.db"), pg_adapter.model)
    records = [record(f"raw:{i:04}", "ordinary",
                      "wanted" if i % 2 else "other", "thread" if i % 3 else "project")
               for i in reversed(range(320))]
    records.extend([record("raw:z", "better"), record("raw:tiny", "tiny"),
                    record("raw:negative", "negative"), record("raw:zero", "zero")])
    pg_adapter.index_records(records)
    sqlite.index_records(list(reversed(records)))
    for query in ("query", "better", "tiny", "zero"):
        for namespace, scope in ((None, None), ("wanted", None), (None, "thread"),
                                 ("wanted", "thread"), ("missing", "thread"), ("", "")):
            for limit in (0, 1, 3, 10, 50, 500):
                options = dict(limit=limit, namespace=namespace, scope=scope)
                actual = pg_adapter.search(query, **options)
                expected = sqlite.search(query, **options)
                assert list(actual.items()) == list(expected.items()), (query, options)
    assert list(pg_adapter.search("query", limit=4)) == ["raw:z", "raw:0000", "raw:0001", "raw:0002"]
    assert pg_adapter.search("query", limit=1000)["raw:tiny"] == 1e-18
    pg_adapter.delete_records(["raw:z"])
    sqlite.delete_records(["raw:z"])
    assert list(pg_adapter.search("query", limit=2)) == list(sqlite.search("query", limit=2))


@pytest.mark.parametrize("noise_count", [512, 8192])
def test_exact_filtered_plan_work_stays_scoped_under_unrelated_growth(noise_count):
    model = DenseModel()
    adapter = PgVectorAdapter(os.environ["PGVECTOR_TEST_DSN"], model,
                              table_name="seam_r2_exact_" + uuid.uuid4().hex[:12])
    connect, calls = adapter._connect, []
    target = [record(f"raw:target:{i}", f"target {i}") for i in range(64)]
    try:
        adapter.index_records(target)
        adapter.index_records([record(f"raw:noise:{i}", f"noise {i}", "other")
                               for i in range(noise_count)])
        other_model = DenseModel()
        other_model.name = "r2-unrelated-model"
        other = PgVectorAdapter(adapter.dsn, other_model, table_name=adapter.table_name)
        other.index_records([record(f"raw:model:{i}", f"model {i}")
                             for i in range(noise_count)])
        with connect() as connection:
            connection.execute(f"analyze {adapter.table_name}")
        adapter._connect = lambda: ConnectionSpy(connect(), calls)
        scores = adapter.search("query", 5, namespace="wanted", scope="thread")
        expected = sorted(((r.id, cosine(model.embed("query"), model.embed(adapter_text(r))))
                           for r in target), key=lambda item: (-item[1], item[0]))[:5]
        assert list(scores.items()) == expected
        statement, params = next((query, params) for query, params in calls
                                 if "select record_id" in str(query).lower())
        with connect() as connection:
            plan = connection.execute("explain (analyze, buffers, format json) "
                                      "declare seam_plan cursor for " + statement,
                                      params).fetchone()[0][0]
        Path(f"test_seam/r2-backend/pg/exact-plan-{noise_count}.json").write_text(
            json.dumps(plan, indent=2) + "\n")
        assert set(plan_indexes(plan["Plan"])) & {
            f"{adapter.table_name}_boundary_idx", f"{adapter.table_name}_exact_namespace_idx"
        }
        assert plan["Plan"]["Actual Rows"] == 64
        assert sum(node.get("Rows Removed by Filter", 0)
                   for node in plan_nodes(plan["Plan"])) == 0
    finally:
        adapter._connect = connect
        with connect() as connection:
            connection.execute(f"drop table if exists {adapter.table_name}")


@pytest.mark.parametrize("count", [256, 4096])
def test_exact_search_pages_one_snapshot_with_bounded_client_memory(pg_adapter, count):
    items = [record(f"raw:{i:06}", "ordinary") for i in range(count)]
    items.append(record("raw:zzzz", "ordinary"))
    pg_adapter.index_records(items)
    connect = pg_adapter._connect
    batches, names, injected = [], [], []

    class SnapshotCursor(CursorSpy):
        def fetchmany(self, size):
            result = self.cursor.fetchmany(size)
            names.append(self.cursor.name)
            batches.append(len(result))
            if result and not injected:
                injected.append(True)
                pg_adapter.index_records([record("raw:zzzz", "better")])
            return result

    class SnapshotConnection(ConnectionSpy):
        def cursor(self, *args, **kwargs):
            return SnapshotCursor(self.connection.cursor(*args, **kwargs), [])

    pg_adapter._connect = lambda: SnapshotConnection(connect(), [])
    try:
        first = pg_adapter.search("query", limit=5)
        assert list(first) == [f"raw:{i:06}" for i in range(5)]
        tracemalloc.start()
        second = pg_adapter.search("query", limit=5)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert next(iter(second)) == "raw:zzzz"
        assert all(names)
        assert max(batches) <= 128
        assert peak < 512_000
        Path(f"test_seam/r2-backend/pg/exact-memory-{count}.json").write_text(
            json.dumps({"rows": count + 1, "limit": 5, "max_payload_page": max(batches),
                        "peak_tracemalloc_bytes": peak, "named_cursor": True,
                        "concurrent_update_snapshot_preserved": True}, indent=2) + "\n")
    finally:
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        pg_adapter._connect = connect


@pytest.mark.parametrize("payload", [None, "not-json", "[true, 1]", "[1]", "[1, NaN]"])
def test_invalid_original_cannot_silently_remove_an_eligible_candidate(pg_adapter, payload):
    pg_adapter.index_records([record("raw:a", "ordinary"), record("raw:z", "better")])
    with pg_adapter._connect() as connection:
        connection.execute(f"update {pg_adapter.table_name} set original_vector_json = %s "
                           "where record_id = 'raw:z'", (payload,))
    with pytest.raises(RuntimeError, match="reindex"):
        pg_adapter.search("query", limit=1)


def test_search_modes_are_explicit_and_invalid_values_fail(pg_adapter):
    assert pg_adapter.search_mode == "exact"
    assert PgVectorAdapter(pg_adapter.dsn, pg_adapter.model, search_mode="approximate").search_mode == "approximate"
    with pytest.raises(ValueError, match="search_mode"):
        PgVectorAdapter(pg_adapter.dsn, pg_adapter.model, search_mode="silently-auto")
