from __future__ import annotations

import json
import re
from contextlib import closing
from dataclasses import dataclass
from typing import Protocol

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind, iter_textual_fields
from seam_runtime.models import EmbeddingModel
from seam_runtime.storage import SQLiteStore
from seam_runtime.vector import INDEXABLE_KINDS, SQLiteVectorIndex
from seam_runtime.vector_adapters import VectorAdapter

from .types import LegHit, RetrievalPlan

GRAPH_RETURN_KINDS = {RecordKind.ENT, *INDEXABLE_KINDS}


class SQLAdapter(Protocol):
    def search(self, plan: RetrievalPlan, limit: int) -> list[LegHit]:
        ...


class SemanticAdapter(Protocol):
    def search(self, plan: RetrievalPlan, limit: int) -> list[LegHit]:
        ...


class SQLiteIRAdapter:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def search(self, plan: RetrievalPlan, limit: int) -> list[LegHit]:
        query_text = plan.normalized_query or plan.query
        query_tokens = _unique_tokens(_tokens(query_text))
        query_sql, params = _build_structured_sql(plan, query_tokens, limit)
        with closing(self.store._connect()) as connection:
            rows = connection.execute(query_sql, params).fetchall()
        hits: list[LegHit] = []
        for row in rows:
            record = MIRLRecord.from_dict(json.loads(row["payload_json"]))
            filter_bonus, reasons = _structured_reasons(record, plan)
            lexical = float(row["lexical_score"])
            reasons.append(f"structured={float(row['structured_score']):.2f}")
            if query_tokens:
                reasons.append(f"lexical={lexical:.2f}")
                reasons.append(f"token_hits={int(row['lexical_hits'])}")
            hits.append(LegHit(leg="sql", record=record, score=float(row["sql_score"]), reasons=reasons))
        return hits


class SeamVectorSearchAdapter:
    def __init__(self, store: SQLiteStore, vector_adapter: VectorAdapter) -> None:
        self.store = store
        self.vector_adapter = vector_adapter

    def search(self, plan: RetrievalPlan, limit: int) -> list[LegHit]:
        query_text = plan.normalized_query or plan.query
        if not query_text.strip():
            return []
        raw_scores = self.vector_adapter.search(query_text, limit=max(limit * 3, 10))
        if not raw_scores:
            return []
        batch = self.store.load_ir(ids=list(raw_scores))
        by_id = batch.by_id()
        hits: list[LegHit] = []
        for record_id, raw_score in raw_scores.items():
            record = by_id.get(record_id)
            if record is None or not plan.filters.matches(record):
                continue
            if plan.filters.active():
                raw_score += 0.05 * _matched_filter_count(record, plan)
            hits.append(LegHit(leg="vector", record=record, score=raw_score, reasons=[f"semantic={raw_score:.2f}"]))
        return sorted(hits, key=lambda item: item.score, reverse=True)[:limit]


class SQLiteGraphAdapter:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def search(self, plan: RetrievalPlan, limit: int) -> list[LegHit]:
        query_text = plan.normalized_query or plan.query
        tokens = _unique_tokens(_tokens(query_text))
        if not tokens and not plan.filters.active():
            return []
        batch = self.store.load_ir(scope=plan.filters.scope, ns=plan.filters.namespace)
        by_id = batch.by_id()
        graph: dict[str, set[str]] = {}
        # Restrict the edge load to edges that TOUCH an in-scope/in-namespace
        # record instead of scanning the entire ir_edges table on every graph
        # search. We keep every edge incident to a loaded record (src OR dst in
        # the record set), so neighbor counts/bonuses are byte-identical to the
        # prior full scan; only edges between two out-of-scope records — which
        # were already unreachable downstream (filtered by by_id + matches) —
        # are dropped. With no scope/ns filter this is the full scan as before.
        record_where: list[str] = []
        record_params: list[object] = []
        if plan.filters.scope:
            record_where.append("scope = ?")
            record_params.append(plan.filters.scope)
        if plan.filters.namespace:
            record_where.append("ns = ?")
            record_params.append(plan.filters.namespace)
        if record_where:
            subquery = f"select id from ir_records where {' and '.join(record_where)}"
            edge_sql = (
                "select src_id, edge_type, dst_id from ir_edges "
                f"where src_id in ({subquery}) or dst_id in ({subquery})"
            )
            edge_params = record_params + record_params  # subquery is referenced twice
        else:
            edge_sql = "select src_id, edge_type, dst_id from ir_edges"
            edge_params = []
        with closing(self.store._connect()) as connection:
            rows = connection.execute(edge_sql, edge_params).fetchall()
        for row in rows:
            src = str(row["src_id"])
            dst = str(row["dst_id"])
            edge_type = str(row["edge_type"])
            graph.setdefault(src, set()).add(dst)
            graph.setdefault(dst, set()).add(src)
            graph.setdefault(edge_type, set()).update([src, dst])

        seed_ids: set[str] = set()
        for record in batch.records:
            if not plan.filters.matches(record):
                continue
            haystack = " ".join([record.id, record.kind.value, *iter_textual_fields(record)]).lower()
            if not tokens or any(token in haystack for token in tokens):
                seed_ids.add(record.id)
                seed_ids.update(graph.get(record.id, set()))
        hits: list[LegHit] = []
        for record_id in seed_ids:
            record = by_id.get(record_id)
            if record is None or record.kind not in GRAPH_RETURN_KINDS or not plan.filters.matches(record):
                continue
            lexical = _lexical_score(record, tokens)
            neighbor_bonus = min(0.6, len(graph.get(record_id, set())) * 0.1)
            seed_bonus = 0.5 if record_id in seed_ids else 0.0
            score = lexical + neighbor_bonus + seed_bonus
            if score <= 0:
                score = neighbor_bonus
            hits.append(
                LegHit(
                    leg="graph",
                    record=record,
                    score=score,
                    reasons=[f"graph_neighbors={len(graph.get(record_id, set()))}", f"lexical={lexical:.2f}"],
                )
            )
        return sorted(hits, key=lambda item: item.score, reverse=True)[:limit]


@dataclass
class ChromaSemanticAdapter:
    store: SQLiteStore
    embedding_model: EmbeddingModel
    persist_directory: str = ".seam_chroma"
    collection_name: str = "seam_hybrid"
    client: object | None = None
    sync_on_search: bool = False  # default flipped; callers that need sync call sync_persistent_indexes explicitly

    def _client(self):
        if self.client is not None:
            return self.client
        try:
            import chromadb
        except ImportError as exc:
            raise RuntimeError("chromadb is not installed. Install it to use --semantic-backend chroma.") from exc
        self.client = chromadb.PersistentClient(path=self.persist_directory)
        return self.client

    def _collection(self):
        return self._client().get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def sync_records(self, plan: RetrievalPlan | None = None) -> int:
        ids = plan.filters.ids or None if plan is not None else None
        namespace = plan.filters.namespace if plan is not None else None
        scope = plan.filters.scope if plan is not None else None
        batch = self.store.load_ir(ids=ids, ns=namespace, scope=scope)
        return self.sync_batch(batch)

    def sync_batch(self, batch: IRBatch) -> int:
        records = [record for record in batch.records if record.kind in INDEXABLE_KINDS]
        if not records:
            return 0
        collection = self._collection()
        rendered = [SQLiteVectorIndex.render_record_text(record) for record in records]
        collection.upsert(
            ids=[record.id for record in records],
            embeddings=[self.embedding_model.embed(text) for text in rendered],
            documents=rendered,
            metadatas=[_chroma_metadata(record) for record in records],
        )
        return len(records)

    def search(self, plan: RetrievalPlan, limit: int) -> list[LegHit]:
        query_text = plan.normalized_query or plan.query
        if not query_text.strip():
            return []
        if self.sync_on_search:
            self.sync_records(plan)
        collection = self._collection()
        response = collection.query(
            query_embeddings=[self.embedding_model.embed(query_text)],
            n_results=max(limit * 3, 10),
            include=["metadatas", "distances", "documents"],
        )
        ids = response.get("ids", [[]])[0]
        distances = response.get("distances", [[]])[0]
        if not ids:
            return []
        batch = self.store.load_ir(ids=list(ids))
        by_id = batch.by_id()
        hits: list[LegHit] = []
        for index, record_id in enumerate(ids):
            record = by_id.get(record_id)
            if record is None or not plan.filters.matches(record):
                continue
            distance = float(distances[index]) if index < len(distances) else 1.0
            score = max(0.0, 1.0 - distance)
            if plan.filters.active():
                score += 0.05 * _matched_filter_count(record, plan)
            hits.append(LegHit(leg="chroma", record=record, score=score, reasons=[f"chroma={score:.2f}"]))
        return sorted(hits, key=lambda item: item.score, reverse=True)[:limit]


def _structured_reasons(record: MIRLRecord, plan: RetrievalPlan) -> tuple[float, list[str]]:
    bonus = 0.0
    reasons: list[str] = []
    if plan.filters.ids and record.id in plan.filters.ids:
        bonus += 1.2
        reasons.append("matched=id")
    if plan.filters.kinds and record.kind.value in plan.filters.kinds:
        bonus += 0.8
        reasons.append("matched=kind")
    if plan.filters.namespace and record.ns == plan.filters.namespace:
        bonus += 0.4
        reasons.append("matched=ns")
    if plan.filters.scope and record.scope == plan.filters.scope:
        bonus += 0.4
        reasons.append("matched=scope")
    if plan.filters.predicate and str(record.attrs.get("predicate", "")).lower() == plan.filters.predicate.lower():
        bonus += 0.6
        reasons.append("matched=predicate")
    if plan.filters.subject and str(record.attrs.get("subject", "")).lower() == plan.filters.subject.lower():
        bonus += 0.6
        reasons.append("matched=subject")
    if plan.filters.object_text and plan.filters.object_text.lower() in str(record.attrs.get("object", "")).lower():
        bonus += 0.6
        reasons.append("matched=object")
    return bonus, reasons


def _matched_filter_count(record: MIRLRecord, plan: RetrievalPlan) -> int:
    matched = 0
    if plan.filters.ids and record.id in plan.filters.ids:
        matched += 1
    if plan.filters.kinds and record.kind.value in plan.filters.kinds:
        matched += 1
    if plan.filters.namespace and record.ns == plan.filters.namespace:
        matched += 1
    if plan.filters.scope and record.scope == plan.filters.scope:
        matched += 1
    if plan.filters.predicate and str(record.attrs.get("predicate", "")).lower() == plan.filters.predicate.lower():
        matched += 1
    if plan.filters.subject and str(record.attrs.get("subject", "")).lower() == plan.filters.subject.lower():
        matched += 1
    if plan.filters.object_text and plan.filters.object_text.lower() in str(record.attrs.get("object", "")).lower():
        matched += 1
    return matched


def _lexical_score(record: MIRLRecord, query_tokens: list[str]) -> float:
    if not query_tokens:
        return 0.0
    record_tokens = set(_tokens(" ".join(iter_textual_fields(record))))
    if not record_tokens:
        return 0.0
    return len(set(query_tokens) & record_tokens) / max(len(set(query_tokens)), 1)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_:-]+", text.lower())


def _unique_tokens(tokens: list[str]) -> list[str]:
    return list(dict.fromkeys(tokens))


def _build_structured_sql(plan: RetrievalPlan, query_tokens: list[str], limit: int) -> tuple[str, list[object]]:
    where_clauses = ["r.kind in ('CLM', 'STA', 'EVT', 'REL')"]
    where_params: list[object] = []

    if plan.filters.ids:
        placeholders = ",".join("?" for _ in plan.filters.ids)
        where_clauses.append(f"r.id in ({placeholders})")
        where_params.extend(plan.filters.ids)
    if plan.filters.namespace:
        where_clauses.append("r.ns = ?")
        where_params.append(plan.filters.namespace)
    if plan.filters.scope:
        where_clauses.append("r.scope = ?")
        where_params.append(plan.filters.scope)
    if plan.filters.kinds:
        placeholders = ",".join("?" for _ in plan.filters.kinds)
        where_clauses.append(f"r.kind in ({placeholders})")
        where_params.extend(plan.filters.kinds)
    if plan.filters.predicate:
        where_clauses.append("lower(coalesce(json_extract(r.payload_json, '$.attrs.predicate'), '')) = ?")
        where_params.append(plan.filters.predicate.lower())
    if plan.filters.subject:
        where_clauses.append("lower(coalesce(json_extract(r.payload_json, '$.attrs.subject'), '')) = ?")
        where_params.append(plan.filters.subject.lower())
    if plan.filters.object_text:
        escaped = plan.filters.object_text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where_clauses.append("lower(coalesce(json_extract(r.payload_json, '$.attrs.object'), '')) like ? escape '\\'")
        where_params.append(f"%{escaped}%")

    structured_parts: list[str] = []
    structured_params: list[object] = []
    if plan.filters.ids:
        placeholders = ",".join("?" for _ in plan.filters.ids)
        structured_parts.append(f"case when id in ({placeholders}) then 1.20 else 0 end")
        structured_params.extend(plan.filters.ids)
    if plan.filters.kinds:
        placeholders = ",".join("?" for _ in plan.filters.kinds)
        structured_parts.append(f"case when kind in ({placeholders}) then 0.80 else 0 end")
        structured_params.extend(plan.filters.kinds)
    if plan.filters.namespace:
        structured_parts.append("case when ns = ? then 0.40 else 0 end")
        structured_params.append(plan.filters.namespace)
    if plan.filters.scope:
        structured_parts.append("case when scope = ? then 0.40 else 0 end")
        structured_params.append(plan.filters.scope)
    if plan.filters.predicate:
        structured_parts.append("case when predicate_text = ? then 0.75 else 0 end")
        structured_params.append(plan.filters.predicate.lower())
    if plan.filters.subject:
        structured_parts.append("case when subject_text = ? then 0.70 else 0 end")
        structured_params.append(plan.filters.subject.lower())
    if plan.filters.object_text:
        escaped = plan.filters.object_text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        structured_parts.append("case when object_text like ? escape '\\' then 0.65 else 0 end")
        structured_params.append(f"%{escaped}%")
    structured_expr = " + ".join(structured_parts) if structured_parts else "0.0"

    lexical_count_parts: list[str] = []
    lexical_count_params: list[object] = []
    lexical_score_parts: list[str] = []
    lexical_score_params: list[object] = []
    normalized_query = (plan.normalized_query or plan.query).strip().lower()
    if normalized_query:
        lexical_score_parts.append("case when instr(search_text, ?) > 0 then 0.55 else 0 end")
        lexical_score_params.append(normalized_query)
    for token in query_tokens:
        lexical_count_parts.append("case when instr(search_text, ?) > 0 then 1 else 0 end")
        lexical_count_params.append(token)
        lexical_score_parts.append("case when instr(search_text, ?) > 0 then 0.22 else 0 end")
        lexical_score_params.append(token)
    lexical_hits_expr = " + ".join(lexical_count_parts) if lexical_count_parts else "0"
    lexical_score_expr = " + ".join(lexical_score_parts) if lexical_score_parts else "0.0"

    gating_clause = ""
    gating_params: list[object] = []
    if query_tokens:
        gating_clause = "and (lexical_hits > 0 or structured_score >= 1.0)"

    query = f"""
with record_rows as (
    select
        r.id,
        r.kind,
        r.ns,
        r.scope,
        r.conf,
        r.t0,
        r.updated_at,
        r.payload_json,
        lower(coalesce(v.source_text, r.payload_json)) as search_text,
        lower(coalesce(json_extract(r.payload_json, '$.attrs.predicate'), '')) as predicate_text,
        lower(coalesce(json_extract(r.payload_json, '$.attrs.subject'), '')) as subject_text,
        lower(coalesce(json_extract(r.payload_json, '$.attrs.object'), '')) as object_text
    from ir_records r
    left join (
        select record_id, max(source_text) as source_text
        from vector_index
        group by record_id
    ) v on v.record_id = r.id
    where {' and '.join(where_clauses)}
),
scored_rows as (
    select
        payload_json,
        conf,
        updated_at,
        {structured_expr} as structured_score,
        {lexical_hits_expr} as lexical_hits,
        {lexical_score_expr} as lexical_score,
        case when t0 is not null then 0.10 else 0.0 end as temporal_score
    from record_rows
)
select
    payload_json,
    structured_score,
    lexical_hits,
    lexical_score,
    (structured_score + lexical_score + temporal_score + (case when conf < 1.0 then conf else 1.0 end * 0.15)) as sql_score
from scored_rows
where (structured_score + lexical_score) > 0
{gating_clause}
order by sql_score desc, lexical_hits desc, updated_at desc
limit ?
"""
    params: list[object] = []
    params.extend(where_params)
    params.extend(structured_params)
    params.extend(lexical_count_params)
    params.extend(lexical_score_params)
    params.extend(gating_params)
    params.append(limit)
    return query, params


def _chroma_metadata(record: MIRLRecord) -> dict[str, str]:
    attrs = record.attrs
    metadata = {
        "kind": record.kind.value,
        "ns": record.ns,
        "scope": record.scope,
    }
    if "predicate" in attrs:
        metadata["predicate"] = str(attrs.get("predicate"))
    if "subject" in attrs:
        metadata["subject"] = str(attrs.get("subject"))
    if "object" in attrs:
        metadata["object"] = str(attrs.get("object"))
    return metadata
