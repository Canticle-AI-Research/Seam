from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field
from typing import Protocol

from .mirl import MIRLRecord
from .models import EmbeddingModel, cosine
from .vector import (
    INDEXABLE_KINDS,
    LEGACY_VECTOR_TEXT_VERSION,
    VECTOR_TEXT_VERSION,
    SQLiteVectorIndex,
    stored_vector_issue,
)


class VectorAdapter(Protocol):
    name: str

    def index_records(self, records: list[MIRLRecord]) -> None:
        ...

    def delete_records(self, record_ids: list[str]) -> None:
        ...

    def search(
        self,
        query: str,
        limit: int = 10,
        namespace: str | None = None,
        scope: str | None = None,
    ) -> dict[str, float]:
        ...


def search_vector_adapter(
    adapter: VectorAdapter,
    query: str,
    *,
    limit: int,
    namespace: str | None,
    scope: str | None,
) -> dict[str, float]:
    """Use scope-aware search without breaking pre-scope custom adapters."""

    try:
        parameters = inspect.signature(adapter.search).parameters.values()
    except (TypeError, ValueError):
        parameters = ()
    accepts_scope = any(
        parameter.name == "scope" or parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in parameters
    )
    if accepts_scope:
        return adapter.search(
            query,
            limit=limit,
            namespace=namespace,
            scope=scope,
        )
    return adapter.search(query, limit=limit, namespace=namespace)


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

    def delete_records(self, record_ids: list[str]) -> None:
        self.index.delete_records(record_ids)

    def search(
        self,
        query: str,
        limit: int = 10,
        namespace: str | None = None,
        scope: str | None = None,
    ) -> dict[str, float]:
        return self.index.search(
            query, limit=limit, namespace=namespace, scope=scope
        )

    def stale_records(self, records: list[MIRLRecord]) -> list[dict[str, object]]:
        return self.index.stale_records(records)

    def orphan_records(
        self,
        valid_record_ids: set[str] | None = None,
        *,
        model_name: str | None = None,
        namespace: str | None = None,
        scope: str | None = None,
    ) -> list[dict[str, object]]:
        return self.index.orphan_records(
            valid_record_ids,
            model_name=model_name,
            namespace=namespace,
            scope=scope,
        )


@dataclass
class MemoryVectorAdapter:
    """Process-local vector projection for ephemeral canonical retrieval.

    HS/1 surface queries must use the normal retrieval engine without importing
    their payload into a durable database. This adapter keeps the derived vector
    leg in memory while ``SQLiteStore(':memory:')`` holds canonical MIRL.
    """

    model: EmbeddingModel
    name: str = "memory-vector"
    _rows: dict[str, tuple[MIRLRecord, list[float]]] = field(
        default_factory=dict, init=False, repr=False
    )

    def index_records(self, records: list[MIRLRecord]) -> None:
        for record in records:
            if record.kind not in INDEXABLE_KINDS:
                continue
            text = SQLiteVectorIndex.render_record_text(record)
            self._rows[record.id] = (record, self.model.embed(text))

    def delete_records(self, record_ids: list[str]) -> None:
        for record_id in record_ids:
            self._rows.pop(record_id, None)

    def search(
        self,
        query: str,
        limit: int = 10,
        namespace: str | None = None,
        scope: str | None = None,
    ) -> dict[str, float]:
        query_vector = self.model.embed(query)
        ranked = [
            (record_id, cosine(query_vector, vector))
            for record_id, (record, vector) in self._rows.items()
            if (namespace is None or record.ns == namespace)
            and (scope is None or record.scope == scope)
        ]
        ranked.sort(key=lambda item: (-item[1], item[0]))
        return dict(ranked[: max(0, limit)])


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

    def check_ready(self) -> None:
        """Raise unless the vector extension, schema, and required access work."""
        self.ensure_schema()

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
                        render_version text not null default '{VECTOR_TEXT_VERSION}',
                        namespace text not null default '',
                        scope text not null default '',
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
                    where table_schema = current_schema()
                      and table_name = %s and column_name = 'source_hash'
                    """,
                    (self.table_name,),
                )
                if cursor.fetchone() is None:
                    cursor.execute(f"alter table {self.table_name} add column source_hash text not null default ''")
                cursor.execute(
                    """
                    select column_name
                    from information_schema.columns
                    where table_schema = current_schema()
                      and table_name = %s and column_name = 'render_version'
                    """,
                    (self.table_name,),
                )
                if cursor.fetchone() is None:
                    # Adding the column is metadata-only and deliberately
                    # stamps all pre-contract embeddings as legacy. Merely
                    # opening the adapter must never invoke an embedding
                    # model or silently bless those vectors as current.
                    cursor.execute(
                        f"alter table {self.table_name} "
                        "add column render_version text not null "
                        f"default '{LEGACY_VECTOR_TEXT_VERSION}'"
                    )
                    cursor.execute(
                        f"alter table {self.table_name} alter column "
                        "render_version "
                        f"set default '{VECTOR_TEXT_VERSION}'"
                    )
                cursor.execute(
                    """
                    select column_name
                    from information_schema.columns
                    where table_schema = current_schema()
                      and table_name = %s and column_name = 'namespace'
                    """,
                    (self.table_name,),
                )
                if cursor.fetchone() is None:
                    cursor.execute(f"alter table {self.table_name} add column namespace text not null default ''")
                cursor.execute(
                    """
                    select column_name
                    from information_schema.columns
                    where table_schema = current_schema()
                      and table_name = %s and column_name = 'scope'
                    """,
                    (self.table_name,),
                )
                if cursor.fetchone() is None:
                    cursor.execute(
                        f"alter table {self.table_name} "
                        "add column scope text not null default ''"
                    )
                cursor.execute(f"create index if not exists {self.table_name}_model_name_idx on {self.table_name} (model_name)")
                cursor.execute(
                    f"create index if not exists {self.table_name}_boundary_idx "
                    f"on {self.table_name} (namespace, scope, model_name)"
                )
                self._migrate_composite_pk(cursor)
                if self.ann_index_status != "ok":
                    self._ensure_hnsw_index(cursor)
            connection.commit()

    def _ensure_hnsw_index(self, cursor) -> None:
        """Ensure an HNSW index covers this adapter's own embedding dimension,
        so pgvector search stops being an exact brute-force scan at scale.

        pgvector's hnsw access method requires a fixed-dimension vector type,
        but the ``embedding`` column itself stays dimensionless: this table's
        schema (composite PK on (record_id, model_name), a per-row
        ``dimension`` column, model_name+dimension filtering on every query)
        is built to let more than one embedding model/dimension share a table.
        ALTERing the column to one fixed dimension would permanently break
        every other dimension's ability to insert into this table again - a
        real regression when the default table is shared across runs with
        different embedding configs (e.g. a dev fallback to a small hash
        embedding vs. a real sentence-transformer model, both against the
        same DSN/table).

        Instead, build a partial expression index scoped to this dimension:
        the cast to ``vector(N)`` only runs for rows where ``dimension = N``
        (partial-index predicates short-circuit expression evaluation for
        non-matching rows), so it's always safe regardless of what other
        dimensions already live in the table. Each distinct dimension that
        calls ensure_schema() gets its own index; none of them touch the
        underlying column type.
        """
        target_dimension = int(self.model.dimension)
        index_name = f"{self.table_name}_hnsw_{target_dimension}_idx"
        cursor.execute(
            f"""
            create index if not exists {index_name}
            on {self.table_name}
            using hnsw ((embedding::vector({target_dimension})) vector_cosine_ops)
            where dimension = {target_dimension}
            """
        )
        self.ann_index_status = "ok"

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
                        f"select source_hash, dimension, render_version, "
                        f"namespace, scope from {self.table_name} "
                        "where record_id = %s and model_name = %s",
                        (record.id, self.model.name),
                    )
                    current = cursor.fetchone()
                    if (
                        current
                        and current[2] == VECTOR_TEXT_VERSION
                        and current[0] == source_hash
                        and int(current[1]) == int(self.model.dimension)
                    ):
                        if (
                            current[3] != (record.ns or "")
                            or current[4] != (record.scope or "")
                        ):
                            cursor.execute(
                                f"update {self.table_name} "
                                "set namespace = %s, scope = %s, updated_at = %s "
                                "where record_id = %s and model_name = %s",
                                (
                                    record.ns or "",
                                    record.scope or "",
                                    record.updated_at,
                                    record.id,
                                    self.model.name,
                                ),
                            )
                        continue
                    vector = self.model.embed(source_text)
                    cursor.execute(
                        f"""
                        insert into {self.table_name}
                            (record_id, model_name, dimension, source_text,
                             source_hash, render_version, namespace, scope,
                             embedding, updated_at)
                        values (%s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s)
                        on conflict (record_id, model_name) do update
                        set model_name = excluded.model_name,
                            dimension = excluded.dimension,
                            source_text = excluded.source_text,
                            source_hash = excluded.source_hash,
                            render_version = excluded.render_version,
                            namespace = excluded.namespace,
                            scope = excluded.scope,
                            embedding = excluded.embedding,
                            updated_at = excluded.updated_at
                        """,
                        (
                            record.id,
                            self.model.name,
                            len(vector),
                            source_text,
                            source_hash,
                            VECTOR_TEXT_VERSION,
                            record.ns or "",
                            record.scope or "",
                            _vector_literal(vector),
                            record.updated_at,
                        ),
                    )
            connection.commit()

    def delete_records(self, record_ids: list[str]) -> None:
        """Remove every embedding copy for the deleted canonical records."""

        _validate_table_name(self.table_name)
        ids = tuple(sorted({str(record_id).strip() for record_id in record_ids}))
        if not ids or any(not record_id for record_id in ids):
            raise ValueError("record_ids must contain non-empty references")
        self.ensure_schema()
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"delete from {self.table_name} where record_id = any(%s)",
                    (list(ids),),
                )
            connection.commit()

    def search(
        self,
        query: str,
        limit: int = 10,
        namespace: str | None = None,
        scope: str | None = None,
    ) -> dict[str, float]:
        _validate_table_name(self.table_name)
        self.ensure_schema()
        query_vector = self.model.embed(query)
        ns_clause = "and namespace = %s " if namespace is not None else ""
        scope_clause = "and scope = %s " if scope is not None else ""
        params: list[object] = [
            _vector_literal(query_vector),
            self.model.name,
            len(query_vector),
            VECTOR_TEXT_VERSION,
        ]
        if namespace is not None:
            params.append(namespace)
        if scope is not None:
            params.append(scope)
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
                    where model_name = %s and dimension = %s
                      and render_version = %s {ns_clause}{scope_clause}
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
                        f"select source_hash, dimension, render_version, "
                        f"namespace, scope, embedding::text from {self.table_name} "
                        "where record_id = %s and model_name = %s",
                        (record.id, self.model.name),
                    )
                    row = cursor.fetchone()
                    if row is None:
                        stale.append({"record_id": record.id, "reason": "missing"})
                    elif row[2] != VECTOR_TEXT_VERSION:
                        stale.append(
                            {
                                "record_id": record.id,
                                "reason": "render_version_changed",
                            }
                        )
                    elif row[0] != source_hash:
                        stale.append({"record_id": record.id, "reason": "source_changed"})
                    elif int(row[1]) != int(self.model.dimension):
                        stale.append({"record_id": record.id, "reason": "dimension_changed"})
                    elif row[3] != (record.ns or ""):
                        stale.append({"record_id": record.id, "reason": "namespace_changed"})
                    elif row[4] != (record.scope or ""):
                        stale.append({"record_id": record.id, "reason": "scope_changed"})
                    else:
                        vector_issue = stored_vector_issue(
                            row[5],
                            expected_dimension=int(self.model.dimension),
                        )
                        if vector_issue is not None:
                            stale.append(
                                {"record_id": record.id, "reason": vector_issue}
                            )
        return stale

    def sync_boundaries(self, records: list[MIRLRecord]) -> dict[str, object]:
        """Update namespace/scope metadata without re-embedding.

        For each record, if a matching vector row exists (same record_id and
        model_name) whose namespace or scope differs from the canonical MIRL
        record, update the metadata columns only.  Rows that are missing or
        whose render contract, source_hash, or dimension changed are reported
        but NOT re-embedded; use ``index_records`` for a full resync.

        Returns a summary dict with counts and per-record details.
        """
        _validate_table_name(self.table_name)
        self.ensure_schema()
        updated: list[str] = []
        skipped_missing: list[str] = []
        skipped_render_version: list[str] = []
        skipped_content: list[str] = []
        already_ok: list[str] = []
        with self._connect() as connection:
            with connection.cursor() as cursor:
                for record in records:
                    if record.kind not in INDEXABLE_KINDS:
                        continue
                    source_text = SQLiteVectorIndex.render_record_text(record)
                    source_hash = _hash_text(source_text)
                    cursor.execute(
                        f"select source_hash, dimension, render_version, "
                        f"namespace, scope from {self.table_name} "
                        "where record_id = %s and model_name = %s",
                        (record.id, self.model.name),
                    )
                    current = cursor.fetchone()
                    if current is None:
                        skipped_missing.append(record.id)
                        continue
                    if current[2] != VECTOR_TEXT_VERSION:
                        skipped_render_version.append(record.id)
                        continue
                    if current[0] != source_hash or int(current[1]) != int(self.model.dimension):
                        skipped_content.append(record.id)
                        continue
                    expected_ns = record.ns or ""
                    expected_scope = record.scope or ""
                    if current[3] == expected_ns and current[4] == expected_scope:
                        already_ok.append(record.id)
                        continue
                    cursor.execute(
                        f"update {self.table_name} "
                        "set namespace = %s, scope = %s, updated_at = %s "
                        "where record_id = %s and model_name = %s",
                        (
                            expected_ns,
                            expected_scope,
                            record.updated_at,
                            record.id,
                            self.model.name,
                        ),
                    )
                    updated.append(record.id)
            connection.commit()
        return {
            "updated": updated,
            "already_ok": len(already_ok),
            "skipped_missing": skipped_missing,
            "skipped_render_version": skipped_render_version,
            "skipped_content_changed": skipped_content,
        }

    def orphan_records(
        self,
        valid_record_ids: set[str] | None = None,
        *,
        model_name: str | None = None,
        namespace: str | None = None,
        scope: str | None = None,
    ) -> list[dict[str, object]]:
        """Return vector rows whose record_id is not in valid_record_ids.

        When valid_record_ids is None, returns all vector rows as potentially orphaned
        (caller must supply canonical IDs from SQLite). Optional filters keep a
        shared pgvector table bounded to one model and benchmark boundary.
        """
        _validate_table_name(self.table_name)
        self.ensure_schema()
        where: list[str] = []
        params: list[object] = []
        if model_name is not None:
            where.append("model_name = %s")
            params.append(model_name)
        if namespace is not None:
            where.append("namespace = %s")
            params.append(namespace)
        if scope is not None:
            where.append("scope = %s")
            params.append(scope)
        sql = f"select record_id, model_name from {self.table_name}"
        if where:
            sql += " where " + " and ".join(where)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
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
