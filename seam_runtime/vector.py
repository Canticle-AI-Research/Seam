from __future__ import annotations

import hashlib
import heapq
import json
import sqlite3
from contextlib import closing
from typing import Iterable

from .mirl import MIRLRecord, RecordKind, iter_textual_fields
from .models import EmbeddingModel, cosine

INDEXABLE_KINDS = {RecordKind.CLM, RecordKind.STA, RecordKind.EVT, RecordKind.REL, RecordKind.RAW}


class SQLiteVectorIndex:
    def __init__(self, path: str, model: EmbeddingModel) -> None:
        self.path = path
        self.model = model

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        if self.path != ":memory:":
            connection.execute("pragma journal_mode=WAL")
        connection.execute("pragma busy_timeout=5000")
        connection.execute("pragma foreign_keys=ON")
        connection.execute("pragma synchronous=NORMAL")
        return connection

    def ensure_schema(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                create table if not exists vector_index (
                    record_id text not null,
                    model_name text not null,
                    dimension integer not null,
                    source_text text not null,
                    source_hash text not null default '',
                    namespace text not null default '',
                    vector_json text not null,
                    updated_at text not null,
                    primary key (record_id, model_name)
                )
                """
            )
            columns = {row["name"] for row in connection.execute("pragma table_info(vector_index)").fetchall()}
            if "source_hash" not in columns:
                connection.execute("alter table vector_index add column source_hash text not null default ''")
            if "namespace" not in columns:
                connection.execute("alter table vector_index add column namespace text not null default ''")
            connection.commit()

    def index_records(self, records: Iterable[MIRLRecord]) -> None:
        self.ensure_schema()
        with closing(self._connect()) as connection:
            for record in records:
                if record.kind not in INDEXABLE_KINDS:
                    continue
                source_text = self.render_record_text(record)
                source_hash = _source_hash(source_text)
                current = connection.execute(
                    """
                    select source_hash, dimension
                    from vector_index
                    where record_id = ? and model_name = ?
                    """,
                    (record.id, self.model.name),
                ).fetchone()
                if current and current["source_hash"] == source_hash and int(current["dimension"]) == int(self.model.dimension):
                    continue
                vector = self.model.embed(source_text)
                connection.execute(
                    """
                    insert or replace into vector_index (record_id, model_name, dimension, source_text, source_hash, namespace, vector_json, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (record.id, self.model.name, len(vector), source_text, source_hash, record.ns or "", json.dumps(vector), record.updated_at),
                )
            connection.commit()

    def search(self, query: str, limit: int = 10, namespace: str | None = None) -> dict[str, float]:
        self.ensure_schema()
        if limit <= 0:
            return {}
        query_vector = self.model.embed(query)
        top: list[tuple[float, str]] = []
        sql = "select record_id, vector_json from vector_index where model_name = ? and dimension = ?"
        params: list[object] = [self.model.name, len(query_vector)]
        if namespace is not None:
            sql += " and namespace = ?"
            params.append(namespace)
        with closing(self._connect()) as connection:
            rows = connection.execute(sql, params)
            for row in rows:
                score = cosine(query_vector, json.loads(row["vector_json"]))
                if score <= 0:
                    continue
                item = (score, row["record_id"])
                if len(top) < limit:
                    heapq.heappush(top, item)
                elif item > top[0]:
                    heapq.heapreplace(top, item)
        ordered = sorted(((record_id, score) for score, record_id in top), key=lambda item: item[1], reverse=True)
        return dict(ordered)

    def stale_records(self, records: Iterable[MIRLRecord]) -> list[dict[str, object]]:
        self.ensure_schema()
        stale: list[dict[str, object]] = []
        with closing(self._connect()) as connection:
            for record in records:
                if record.kind not in INDEXABLE_KINDS:
                    continue
                source_text = self.render_record_text(record)
                source_hash = _source_hash(source_text)
                row = connection.execute(
                    """
                    select source_hash, dimension
                    from vector_index
                    where record_id = ? and model_name = ?
                    """,
                    (record.id, self.model.name),
                ).fetchone()
                if row is None:
                    stale.append({"record_id": record.id, "reason": "missing"})
                elif row["source_hash"] != source_hash:
                    stale.append({"record_id": record.id, "reason": "source_changed"})
                elif int(row["dimension"]) != int(self.model.dimension):
                    stale.append({"record_id": record.id, "reason": "dimension_changed"})
        return stale

    def orphan_records(self) -> list[dict[str, object]]:
        """Return vector rows whose record_id is missing from ir_records."""
        self.ensure_schema()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                select v.record_id, v.model_name
                from vector_index v
                where not exists (select 1 from ir_records r where r.id = v.record_id)
                """
            ).fetchall()
        return [{"record_id": row["record_id"], "model_name": row["model_name"], "reason": "orphan"} for row in rows]

    def vector_count(self) -> int:
        """Return total number of vector rows."""
        self.ensure_schema()
        with closing(self._connect()) as connection:
            row = connection.execute("select count(*) from vector_index").fetchone()
        return row[0] if row else 0

    @staticmethod
    def render_record_text(record: MIRLRecord) -> str:
        if record.kind == RecordKind.RAW:
            content = record.attrs.get("content")
            if isinstance(content, str) and content.strip():
                return content
        parts = [record.kind.value]
        parts.extend(iter_textual_fields(record))
        return " ".join(part for part in parts if part)


def _source_hash(source_text: str) -> str:
    return hashlib.sha256(source_text.encode("utf-8")).hexdigest()
