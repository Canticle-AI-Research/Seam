from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing

import pytest

from seam_runtime.mirl import MIRLRecord, RecordKind
from seam_runtime.vector import SQLiteVectorIndex
from seam_runtime.vector_adapters import PgVectorAdapter, SQLiteVectorAdapter


class _Embedding:
    name = "integrity-model"
    dimension = 3

    def embed(self, _text: str) -> list[float]:
        return [1.0, 0.0, 0.0]


def _record() -> MIRLRecord:
    return MIRLRecord(
        id="clm:integrity",
        kind=RecordKind.CLM,
        ns="bench",
        scope="thread",
        attrs={
            "subject": "ent:ada",
            "predicate": "uses",
            "object": "pinned embeddings",
        },
    )


_INVALID_STORED_VECTORS = (
    ("not-json", "vector_malformed"),
    (json.dumps({"value": [1.0, 0.0, 0.0]}), "vector_not_list"),
    (json.dumps([1.0, "not-a-number", 0.0]), "vector_non_numeric"),
    (json.dumps(["1.0", 0.0, 0.0]), "vector_non_numeric"),
    (json.dumps([10**400, 0.0, 0.0]), "vector_nonfinite"),
    (json.dumps([1.0, 0.0]), "vector_length_changed"),
    (json.dumps([1.0, float("nan"), 0.0]), "vector_nonfinite"),
    (json.dumps([0.0, 0.0, 0.0]), "vector_all_zero"),
)


@pytest.mark.parametrize(("payload", "reason"), _INVALID_STORED_VECTORS)
def test_sqlite_stale_records_rejects_unusable_current_model_vector(
    tmp_path, payload: str, reason: str
) -> None:
    path = str(tmp_path / "vectors.db")
    model = _Embedding()
    record = _record()
    index = SQLiteVectorIndex(path, model)
    index.index_records([record])
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            "update vector_index set vector_json = ? "
            "where record_id = ? and model_name = ?",
            (payload, record.id, model.name),
        )
        connection.commit()

    assert index.stale_records([record]) == [
        {"record_id": record.id, "reason": reason}
    ]


def test_sqlite_orphan_records_can_filter_exact_model_and_boundary(
    tmp_path,
) -> None:
    path = str(tmp_path / "orphans.db")
    model = _Embedding()
    adapter = SQLiteVectorAdapter(path, model)
    with closing(sqlite3.connect(path)) as connection:
        rows = [
            ("clm:current", model.name, "bench", "thread"),
            ("clm:other-model", "other-model", "bench", "thread"),
            ("clm:other-scope", model.name, "bench", "other"),
        ]
        connection.executemany(
            """
            insert into vector_index (
                record_id, model_name, dimension, source_text, source_hash,
                render_version, namespace, scope, vector_json, updated_at
            ) values (?, ?, 3, 'text', 'hash', 'mirl-vector-text/2',
                      ?, ?, '[1.0,0.0,0.0]', '2026-07-31T00:00:00Z')
            """,
            rows,
        )
        connection.commit()

    assert adapter.orphan_records(
        set(),
        model_name=model.name,
        namespace="bench",
        scope="thread",
    ) == [
        {
            "record_id": "clm:current",
            "model_name": model.name,
            "reason": "orphan",
        }
    ]


class _FakeCursor:
    def __init__(
        self,
        *,
        one: tuple[object, ...] | None = None,
        many: list[tuple[object, ...]] | None = None,
    ) -> None:
        self.one = one
        self.many = many or []
        self.statements: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        return None

    def execute(self, sql: str, params=()) -> None:
        self.statements.append((sql, tuple(params)))

    def fetchone(self):
        return self.one

    def fetchall(self):
        return list(self.many)


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self._cursor


@pytest.mark.parametrize(("payload", "reason"), _INVALID_STORED_VECTORS)
def test_pgvector_stale_records_rejects_unusable_current_model_vector(
    monkeypatch, payload: str, reason: str
) -> None:
    model = _Embedding()
    record = _record()
    source_text = SQLiteVectorIndex.render_record_text(record)
    cursor = _FakeCursor(
        one=(
            hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
            model.dimension,
            "mirl-vector-text/2",
            record.ns,
            record.scope,
            payload,
        )
    )
    adapter = PgVectorAdapter("postgresql://unused", model)
    monkeypatch.setattr(adapter, "ensure_schema", lambda: None)
    monkeypatch.setattr(
        adapter,
        "_connect",
        lambda: _FakeConnection(cursor),
    )

    assert adapter.stale_records([record]) == [
        {"record_id": record.id, "reason": reason}
    ]
    assert "embedding::text" in cursor.statements[0][0]


def test_pgvector_orphans_can_filter_exact_model_and_boundary(
    monkeypatch,
) -> None:
    model = _Embedding()
    cursor = _FakeCursor(
        many=[
            ("clm:valid", model.name),
            ("clm:orphan", model.name),
        ]
    )
    adapter = PgVectorAdapter("postgresql://unused", model)
    monkeypatch.setattr(adapter, "ensure_schema", lambda: None)
    monkeypatch.setattr(
        adapter,
        "_connect",
        lambda: _FakeConnection(cursor),
    )

    assert adapter.orphan_records(
        {"clm:valid"},
        model_name=model.name,
        namespace="bench",
        scope="thread",
    ) == [
        {
            "record_id": "clm:orphan",
            "model_name": model.name,
            "reason": "orphan",
        }
    ]
    sql, params = cursor.statements[0]
    assert "model_name = %s" in sql
    assert "namespace = %s" in sql
    assert "scope = %s" in sql
    assert params == (model.name, "bench", "thread")
