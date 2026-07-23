from __future__ import annotations

import hashlib
import heapq
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from typing import Iterable

from .mirl import MIRLRecord, RecordKind
from .models import EmbeddingModel, cosine

try:
    # Optional fast path. numpy is not a core dep (core = rich + tiktoken); it
    # arrives with the sbert/rerank extras. Without it, search() falls back to
    # the pure-Python per-row scan below.
    import numpy as _numpy
except ImportError:  # pragma: no cover - exercised via the pure-Python branch
    _numpy = None

INDEXABLE_KINDS = {RecordKind.CLM, RecordKind.STA, RecordKind.EVT, RecordKind.REL, RecordKind.RAW}
LEGACY_VECTOR_TEXT_VERSION = "mirl-vector-text/1"
VECTOR_TEXT_VERSION = "mirl-vector-text/2"

_SEMANTIC_ATTR_ORDER: dict[RecordKind, tuple[str, ...]] = {
    RecordKind.CLM: ("subject", "predicate", "object"),
    RecordKind.STA: ("target", "fields"),
    RecordKind.EVT: ("actor", "action", "object"),
    RecordKind.REL: ("src", "predicate", "dst"),
}
_GROUNDED_CLM_POLICIES = {
    "grounded-clm/1",
    "grounded-clm/2",
    "sentence-grounded-clm/1",
    "multi-speaker-grounded/1",
}
_OBJECT_ONLY_GROUNDED_CLM_POLICIES = {
    "sentence-grounded-clm/1",
    "multi-speaker-grounded/1",
}


@dataclass
class _VectorCache:
    """Deserialized vectors for one (model, dimension, namespace), reused across
    queries. ``fingerprint`` = (row count, max updated_at) for the slice; a
    mismatch on the next search rebuilds, so writes from THIS process or any
    other (the MCP server and CLI share the DB) invalidate correctly."""

    fingerprint: tuple[int, str]
    ids: list[str]
    matrix: "object"  # numpy.ndarray (n, dim), float64
    norms: "object"  # numpy.ndarray (n,), float64 row norms


class SQLiteVectorIndex:
    def __init__(self, path: str, model: EmbeddingModel) -> None:
        self.path = path
        self.model = model
        # Keyed by (model_name, dimension, namespace, scope). Only used on the numpy
        # fast path; harmless (unread) on the pure-Python fallback.
        self._cache: dict[
            tuple[str, int, str | None, str | None], _VectorCache
        ] = {}

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
                    render_version text not null default 'mirl-vector-text/2',
                    namespace text not null default '',
                    scope text not null default '',
                    vector_json text not null,
                    updated_at text not null,
                    primary key (record_id, model_name)
                )
                """
            )
            columns = {row["name"] for row in connection.execute("pragma table_info(vector_index)").fetchall()}
            has_ir_records = connection.execute(
                "select 1 from sqlite_master where type = 'table' and name = 'ir_records'"
            ).fetchone() is not None
            if "source_hash" not in columns:
                connection.execute("alter table vector_index add column source_hash text not null default ''")
            if "render_version" not in columns:
                connection.execute(
                    "alter table vector_index add column render_version text "
                    f"not null default '{LEGACY_VECTOR_TEXT_VERSION}'"
                )
            if "namespace" not in columns:
                connection.execute("alter table vector_index add column namespace text not null default ''")
                if has_ir_records:
                    connection.execute(
                        "update vector_index set namespace = coalesce(("
                        "select r.ns from ir_records r where r.id = vector_index.record_id"
                        "), '')"
                    )
            if "scope" not in columns:
                connection.execute(
                    "alter table vector_index add column scope text not null default ''"
                )
                if has_ir_records:
                    connection.execute(
                        "update vector_index set scope = coalesce(("
                        "select r.scope from ir_records r where r.id = vector_index.record_id"
                        "), '')"
                    )
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
                    select source_hash, render_version, dimension, namespace, scope
                    from vector_index
                    where record_id = ? and model_name = ?
                    """,
                    (record.id, self.model.name),
                ).fetchone()
                if (
                    current
                    and current["render_version"] == VECTOR_TEXT_VERSION
                    and current["source_hash"] == source_hash
                    and int(current["dimension"]) == int(self.model.dimension)
                ):
                    if (
                        current["namespace"] != (record.ns or "")
                        or current["scope"] != (record.scope or "")
                    ):
                        connection.execute(
                            "update vector_index set namespace = ?, scope = ?, "
                            "updated_at = ? where record_id = ? and model_name = ?",
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
                connection.execute(
                    """
                    insert or replace into vector_index
                        (record_id, model_name, dimension, source_text, source_hash,
                         render_version, namespace, scope, vector_json, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        json.dumps(vector),
                        record.updated_at,
                    ),
                )
            connection.commit()
        # A local write may invalidate any cached matrix; the per-search
        # fingerprint check would catch it anyway, but clearing here avoids one
        # stale-detection round-trip.
        self._cache.clear()

    def search(
        self,
        query: str,
        limit: int = 10,
        namespace: str | None = None,
        scope: str | None = None,
    ) -> dict[str, float]:
        self.ensure_schema()
        if limit <= 0:
            return {}
        query_vector = self.model.embed(query)
        if _numpy is None:
            return self._search_scan(query_vector, limit, namespace, scope)
        return self._search_cached(query_vector, limit, namespace, scope)

    def _fingerprint(
        self,
        connection,
        dimension: int,
        namespace: str | None,
        scope: str | None,
    ) -> tuple[int, str]:
        """Cheap invalidation key: (row count, max updated_at) for the slice.

        An ``insert or replace`` stamps the record's ``updated_at`` (monotonic
        at ingest), so both new rows (count) and content changes (max ts) move
        the fingerprint; a stale cache is rebuilt on the next search."""
        sql = (
            "select count(*), coalesce(max(updated_at), '') from vector_index "
            "where model_name = ? and dimension = ? and render_version = ?"
        )
        params: list[object] = [
            self.model.name,
            dimension,
            VECTOR_TEXT_VERSION,
        ]
        if namespace is not None:
            sql += " and namespace = ?"
            params.append(namespace)
        if scope is not None:
            sql += " and scope = ?"
            params.append(scope)
        row = connection.execute(sql, params).fetchone()
        return (int(row[0]), str(row[1]))

    def _load_cache(
        self,
        connection,
        dimension: int,
        namespace: str | None,
        scope: str | None,
    ) -> _VectorCache:
        key = (self.model.name, dimension, namespace, scope)
        fingerprint = self._fingerprint(connection, dimension, namespace, scope)
        cached = self._cache.get(key)
        if cached is not None and cached.fingerprint == fingerprint:
            return cached
        sql = (
            "select record_id, vector_json from vector_index "
            "where model_name = ? and dimension = ? and render_version = ?"
        )
        params: list[object] = [
            self.model.name,
            dimension,
            VECTOR_TEXT_VERSION,
        ]
        if namespace is not None:
            sql += " and namespace = ?"
            params.append(namespace)
        if scope is not None:
            sql += " and scope = ?"
            params.append(scope)
        ids: list[str] = []
        vectors: list[list[float]] = []
        for row in connection.execute(sql, params):
            ids.append(row["record_id"])
            vectors.append(json.loads(row["vector_json"]))
        if vectors:
            matrix = _numpy.asarray(vectors, dtype=_numpy.float64)
            # Per-row norm (NOT batched norm(matrix, axis=1)): the batched
            # reduction rounds differently than cosine()'s per-vector
            # np.linalg.norm, which would flip tied records. Matching it per row
            # keeps scores bit-identical to the pure-Python scan.
            norms = _numpy.array(
                [_numpy.linalg.norm(matrix[i]) for i in range(matrix.shape[0])],
                dtype=_numpy.float64,
            )
        else:
            matrix = _numpy.zeros((0, dimension), dtype=_numpy.float64)
            norms = _numpy.zeros(0, dtype=_numpy.float64)
        cached = _VectorCache(fingerprint=fingerprint, ids=ids, matrix=matrix, norms=norms)
        self._cache[key] = cached
        return cached

    def _search_cached(
        self,
        query_vector: list[float],
        limit: int,
        namespace: str | None,
        scope: str | None,
    ) -> dict[str, float]:
        with closing(self._connect()) as connection:
            cache = self._load_cache(
                connection, len(query_vector), namespace, scope
            )
        if not cache.ids:
            return {}
        query = _numpy.asarray(query_vector, dtype=_numpy.float64)
        query_norm = float(_numpy.linalg.norm(query))
        if not query_norm:
            return {}
        matrix = cache.matrix
        norms = cache.norms
        # Score PER ROW with ``matrix[i] @ query`` -- the identical operation
        # ``cosine()`` performs (same float64 operands, same np.dot reduction,
        # same norms), so scores are bit-identical to the pure-Python scan and
        # rankings never change. A single batched ``matrix @ query`` is faster
        # but its gemv reduction rounds differently, flipping tied records
        # (measured: reorders on hash-embedding ties). The win here is skipping
        # json.loads (was ~88% of the scan) and re-deserialization across
        # queries, not vectorizing the dot.
        top: list[tuple[float, str]] = []
        for i, record_id in enumerate(cache.ids):
            row_norm = float(norms[i])
            if not row_norm:
                continue
            score = float(query @ matrix[i]) / (row_norm * query_norm)
            if score <= 0:
                continue
            item = (score, record_id)
            if len(top) < limit:
                heapq.heappush(top, item)
            elif item > top[0]:
                heapq.heapreplace(top, item)
        ordered = sorted(((record_id, score) for score, record_id in top), key=lambda item: item[1], reverse=True)
        return dict(ordered)

    def _search_scan(
        self,
        query_vector: list[float],
        limit: int,
        namespace: str | None,
        scope: str | None,
    ) -> dict[str, float]:
        """Pure-Python fallback (numpy absent): brute-force per-row cosine."""
        top: list[tuple[float, str]] = []
        sql = (
            "select record_id, vector_json from vector_index "
            "where model_name = ? and dimension = ? and render_version = ?"
        )
        params: list[object] = [
            self.model.name,
            len(query_vector),
            VECTOR_TEXT_VERSION,
        ]
        if namespace is not None:
            sql += " and namespace = ?"
            params.append(namespace)
        if scope is not None:
            sql += " and scope = ?"
            params.append(scope)
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
                    select source_hash, render_version, dimension, namespace, scope
                    from vector_index
                    where record_id = ? and model_name = ?
                    """,
                    (record.id, self.model.name),
                ).fetchone()
                if row is None:
                    stale.append({"record_id": record.id, "reason": "missing"})
                elif row["render_version"] != VECTOR_TEXT_VERSION:
                    stale.append(
                        {
                            "record_id": record.id,
                            "reason": "render_version_changed",
                        }
                    )
                elif row["source_hash"] != source_hash:
                    stale.append({"record_id": record.id, "reason": "source_changed"})
                elif int(row["dimension"]) != int(self.model.dimension):
                    stale.append({"record_id": record.id, "reason": "dimension_changed"})
                elif row["namespace"] != (record.ns or ""):
                    stale.append({"record_id": record.id, "reason": "namespace_changed"})
                elif row["scope"] != (record.scope or ""):
                    stale.append({"record_id": record.id, "reason": "scope_changed"})
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
        policy = str(record.ext.get("derived_fact_policy") or "")
        if record.kind == RecordKind.CLM and policy in _GROUNDED_CLM_POLICIES:
            subject = record.attrs.get("subject_label")
            predicate = record.attrs.get("predicate")
            obj = record.attrs.get("object")
            if (
                policy in _OBJECT_ONLY_GROUNDED_CLM_POLICIES
                and isinstance(obj, str)
                and obj.strip()
            ):
                return obj
            if all(
                isinstance(value, str) and value.strip()
                for value in (subject, predicate, obj)
            ):
                return f"{subject} {predicate} {obj}"
        parts = [record.kind.value]
        parts.extend(_iter_deterministic_textual_fields(record))
        return " ".join(part for part in parts if part)


def _iter_deterministic_textual_fields(record: MIRLRecord) -> Iterable[str]:
    preferred = _SEMANTIC_ATTR_ORDER.get(record.kind, ())
    ordered_keys = [key for key in preferred if key in record.attrs]
    preferred_keys = set(preferred)
    ordered_keys.extend(sorted(key for key in record.attrs if key not in preferred_keys))
    for key in ordered_keys:
        yield from _iter_text_values(record.attrs[key])


def _iter_text_values(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _iter_text_values(item)
    elif isinstance(value, dict):
        for key in sorted(value):
            yield from _iter_text_values(value[key])


def _source_hash(source_text: str) -> str:
    return hashlib.sha256(source_text.encode("utf-8")).hexdigest()
