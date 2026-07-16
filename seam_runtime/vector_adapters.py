from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from .mirl import MIRLRecord
from .models import EmbeddingModel
from .vector import INDEXABLE_KINDS, SQLiteVectorIndex


class VectorAdapter(Protocol):
    name: str

    def index_records(self, records: list[MIRLRecord]) -> None:
        ...

    def search(self, query: str, limit: int = 10, namespace: str | None = None) -> dict[str, float]:
        ...


@dataclass
class SQLiteVectorAdapter:
    path: str
    model: EmbeddingModel
    name: str = "sqlite-vector"

    def __post_init__(self) -> None:
        self.index = SQLiteVectorIndex(self.path, self.model)
        self.index.ensure_schema()

    def index_records(self, records: list[MIRLRecord]) -> None:
        self.index.index_records(records)

    def search(self, query: str, limit: int = 10, namespace: str | None = None) -> dict[str, float]:
        return self.index.search(query, limit=limit, namespace=namespace)

    def stale_records(self, records: list[MIRLRecord]) -> list[dict[str, object]]:
        return self.index.stale_records(records)


@dataclass
class PgVectorAdapter:
    dsn: str
    model: EmbeddingModel
    table_name: str = "seam_vector_index"
    name: str = "pgvector"
    ef_search: int = 40

    def __post_init__(self) -> None:
        _validate_table_name(self.table_name)
        self.ann_index_status: str | None = None

    def _connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("psycopg is required for PgVectorAdapter") from exc
        return psycopg.connect(self.dsn)

    def ensure_schema(self) -> None:
        _validate_table_name(self.table_name)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("create extension if not exists vector")
                cursor.execute(
                    f"""
                    create table if not exists {self.table_name} (
                        record_id text not null,
                        model_name text not null,
                        dimension integer not null,
                        source_text text not null,
                        source_hash text not null default '',
                        namespace text not null default '',
                        embedding vector not null,
                        updated_at text not null,
                        primary key (record_id, model_name)
                    )
                    """
                )
                cursor.execute(
                    """
                    select column_name
                    from information_schema.columns
                    where table_name = %s and column_name = 'source_hash'
                    """,
                    (self.table_name,),
                )
                if cursor.fetchone() is None:
                    cursor.execute(f"alter table {self.table_name} add column source_hash text not null default ''")
                cursor.execute(
                    """
                    select column_name
                    from information_schema.columns
                    where table_name = %s and column_name = 'namespace'
                    """,
                    (self.table_name,),
                )
                if cursor.fetchone() is None:
                    cursor.execute(f"alter table {self.table_name} add column namespace text not null default ''")
                cursor.execute(f"create index if not exists {self.table_name}_model_name_idx on {self.table_name} (model_name)")
                cursor.execute(f"create index if not exists {self.table_name}_namespace_idx on {self.table_name} (namespace, model_name)")
                self._migrate_composite_pk(cursor)
                if self.ann_index_status != "ok":
                    self._ensure_hnsw_index(cursor)
            connection.commit()

    def _ensure_hnsw_index(self, cursor) -> None:
        """Give the ``embedding`` column a fixed dimension and an HNSW index so
        pgvector search stops being an exact brute-force scan at scale.

        A dimensionless ``vector`` column cannot carry an HNSW index (pgvector
        requires a fixed dimension for that access method). This table already
        tracks each row's dimension separately (the ``dimension`` column) to
        support more than one embedding model/dimension sharing a table; fixing
        the column type is only safe when every existing row already agrees
        with the current model's dimension (or the table is empty/fresh).
        """
        cursor.execute(
            """
            select format_type(a.atttypid, a.atttypmod)
            from pg_attribute a
            join pg_class c on a.attrelid = c.oid
            where c.relname = %s and a.attname = 'embedding' and a.attnum > 0 and not a.attisdropped
            """,
            (self.table_name,),
        )
        row = cursor.fetchone()
        current_type = row[0] if row else None
        target_dimension = int(self.model.dimension)

        if current_type == "vector":
            cursor.execute(
                f"select 1 from {self.table_name} where dimension != %s limit 1",
                (target_dimension,),
            )
            if cursor.fetchone() is not None:
                self.ann_index_status = "skipped_mixed_dimension"
                return
            cursor.execute(f"alter table {self.table_name} alter column embedding type vector({target_dimension})")
            cursor.execute(
                f"create index if not exists {self.table_name}_hnsw_idx on {self.table_name} using hnsw (embedding vector_cosine_ops)"
            )
            self.ann_index_status = "ok"
            return

        if current_type == f"vector({target_dimension})":
            cursor.execute(
                f"create index if not exists {self.table_name}_hnsw_idx on {self.table_name} using hnsw (embedding vector_cosine_ops)"
            )
            self.ann_index_status = "ok"
            return

        # Fixed at some other dimension: a different embedding model owns this
        # table's column type. Surface it rather than silently searching without
        # an index (or worse, altering another model's column out from under it).
        self.ann_index_status = "skipped_dimension_mismatch"

    def _migrate_composite_pk(self, cursor) -> None:
        """Idempotent: upgrade single-column PK (record_id) to composite (record_id, model_name)."""
        cursor.execute(
            """
            select pg_get_constraintdef(c.oid)
            from pg_constraint c
            join pg_class t on c.conrelid = t.oid
            where t.relname = %s and c.contype = 'p'
            """,
            (self.table_name,),
        )
        pk_row = cursor.fetchone()
        if pk_row is None:
            return
        pk_def = pk_row[0]
        if "record_id" in pk_def and "model_name" not in pk_def:
            cursor.execute(f"alter table {self.table_name} drop constraint if exists {self.table_name}_pkey")
            cursor.execute(
                f"alter table {self.table_name} add primary key (record_id, model_name)"
            )

    def index_records(self, records: list[MIRLRecord]) -> None:
        _validate_table_name(self.table_name)
        self.ensure_schema()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for record in records:
                    if record.kind not in INDEXABLE_KINDS:
                        continue
                    source_text = SQLiteVectorIndex.render_record_text(record)
                    source_hash = _hash_text(source_text)
                    cursor.execute(
                        f"select source_hash, dimension from {self.table_name} where record_id = %s and model_name = %s",
                        (record.id, self.model.name),
                    )
                    current = cursor.fetchone()
                    if current and current[0] == source_hash and int(current[1]) == int(self.model.dimension):
                        continue
                    vector = self.model.embed(source_text)
                    cursor.execute(
                        f"""
                        insert into {self.table_name} (record_id, model_name, dimension, source_text, source_hash, namespace, embedding, updated_at)
                        values (%s, %s, %s, %s, %s, %s, %s::vector, %s)
                        on conflict (record_id, model_name) do update
                        set model_name = excluded.model_name,
                            dimension = excluded.dimension,
                            source_text = excluded.source_text,
                            source_hash = excluded.source_hash,
                            namespace = excluded.namespace,
                            embedding = excluded.embedding,
                            updated_at = excluded.updated_at
                        """,
                        (record.id, self.model.name, len(vector), source_text, source_hash, record.ns or "", _vector_literal(vector), record.updated_at),
                    )
            connection.commit()

    def search(self, query: str, limit: int = 10, namespace: str | None = None) -> dict[str, float]:
        _validate_table_name(self.table_name)
        self.ensure_schema()
        query_vector = self.model.embed(query)
        ns_clause = "and namespace = %s " if namespace is not None else ""
        params: list[object] = [_vector_literal(query_vector), self.model.name, len(query_vector)]
        if namespace is not None:
            params.append(namespace)
        params.extend([_vector_literal(query_vector), limit])
        with self._connect() as connection:
            with connection.cursor() as cursor:
                # hnsw.ef_search is a session GUC, not a bind-parameterizable
                # value under SET; set_config's 2nd arg IS a regular parameter.
                cursor.execute("select set_config('hnsw.ef_search', %s, false)", (str(int(self.ef_search)),))
                cursor.execute(
                    f"""
                    select record_id, 1 - (embedding <=> %s::vector) as score
                    from {self.table_name}
                    where model_name = %s and dimension = %s {ns_clause}
                    order by embedding <=> %s::vector
                    limit %s
                    """,
                    params,
                )
                rows = cursor.fetchall()
        return {record_id: float(score) for record_id, score in rows if score is not None and float(score) > 0}

    def stale_records(self, records: list[MIRLRecord]) -> list[dict[str, object]]:
        _validate_table_name(self.table_name)
        self.ensure_schema()
        stale: list[dict[str, object]] = []
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for record in records:
                    if record.kind not in INDEXABLE_KINDS:
                        continue
                    source_text = SQLiteVectorIndex.render_record_text(record)
                    source_hash = _hash_text(source_text)
                    cursor.execute(
                        f"select source_hash, dimension from {self.table_name} where record_id = %s and model_name = %s",
                        (record.id, self.model.name),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        stale.append({"record_id": record.id, "reason": "missing"})
                    elif row[0] != source_hash:
                        stale.append({"record_id": record.id, "reason": "source_changed"})
                    elif int(row[1]) != int(self.model.dimension):
                        stale.append({"record_id": record.id, "reason": "dimension_changed"})
        return stale

    def orphan_records(self, valid_record_ids: set[str] | None = None) -> list[dict[str, object]]:
        """Return vector rows whose record_id is not in valid_record_ids.

        When valid_record_ids is None, returns all vector rows as potentially orphaned
        (caller must supply canonical IDs from SQLite).
        """
        self.ensure_schema()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"select record_id, model_name from {self.table_name}")
                rows = cursor.fetchall()
        if valid_record_ids is None:
            return [{"record_id": r[0], "model_name": r[1], "reason": "orphan (no canonical set provided)"} for r in rows]
        return [{"record_id": r[0], "model_name": r[1], "reason": "orphan"} for r in rows if r[0] not in valid_record_ids]

    def vector_count(self) -> int:
        """Return total number of vector rows."""
        self.ensure_schema()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(f"select count(*) from {self.table_name}")
                row = cursor.fetchone()
        return row[0] if row else 0


# fullmatch (not match) anchors both ends, so a trailing newline can't slip
# an unmatched suffix past the pattern -- the guard against SQL injection via
# an interpolated table name.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_table_name(name: str) -> None:
    if not _IDENTIFIER_RE.fullmatch(name):
        raise ValueError(f"Unsafe SQL identifier: {name!r}")


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in vector) + "]"


def _hash_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()
