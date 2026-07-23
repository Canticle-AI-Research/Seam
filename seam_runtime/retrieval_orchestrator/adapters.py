from __future__ import annotations

import hashlib
import json
import re
from contextlib import closing
from dataclasses import dataclass
from typing import Protocol

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind, iter_textual_fields
from seam_runtime.models import EmbeddingModel
from seam_runtime.storage import SQLiteStore
from seam_runtime.vector import INDEXABLE_KINDS, VECTOR_TEXT_VERSION, SQLiteVectorIndex
from seam_runtime.vector_adapters import VectorAdapter, search_vector_adapter

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
        raw_scores = search_vector_adapter(
            self.vector_adapter,
            query_text,
            limit=max(limit * 3, 10),
            namespace=plan.filters.namespace,
            scope=plan.filters.scope,
        )
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
        return sorted(hits, key=lambda item: (-item.score, item.record.id))[:limit]


class SQLiteGraphAdapter:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def search(
        self,
        plan: RetrievalPlan,
        limit: int,
        *,
        seed_record_ids: list[str] | tuple[str, ...] = (),
    ) -> list[LegHit]:
        query_text = plan.normalized_query or plan.query
        tokens = _unique_tokens(_tokens(query_text))
        if not tokens and not plan.filters.active() and not seed_record_ids:
            return []
        seed_limit = max(50, min(250, limit * 20))
        seed_sql, seed_params = _build_structured_sql(
            plan,
            tokens,
            seed_limit,
            include_graph_kinds=True,
        )
        with closing(self.store._connect()) as connection:
            seed_rows = connection.execute(seed_sql, seed_params).fetchall()
        matching_records = [
            MIRLRecord.from_dict(json.loads(row["payload_json"])) for row in seed_rows
        ]
        bounded_semantic_ids = sorted(set(seed_record_ids))[:300]
        semantic_batch = (
            self.store.load_ir(
                ids=bounded_semantic_ids,
                ns=plan.filters.namespace,
                scope=plan.filters.scope,
            )
            if bounded_semantic_ids
            else IRBatch([])
        )
        semantic_seed_ids = {
            record.id
            for record in semantic_batch.records
            if plan.filters.matches(record)
        }
        if not matching_records and not semantic_seed_ids:
            return []
        if tokens:
            matching_records.sort(key=lambda record: (-_lexical_score(record, tokens), record.id))
        else:
            matching_records.sort(key=lambda record: record.id)
        lexical_seed_ids = {record.id for record in matching_records[:seed_limit]}
        semantic_seed_ids = set(
            sorted(semantic_seed_ids)[: max(0, 300 - len(lexical_seed_ids))]
        )
        initial_seed_ids = lexical_seed_ids | semantic_seed_ids

        graph: dict[str, set[str]] = {}
        # The graph leg reads the same self-building temporal graph exposed by
        # the dashboard. Unlike the retired ir_edges projection, these rows
        # carry semantic predicates, provenance, validity, and source records.
        edge_where = [
            "expired_at is null",
            "status not in ('contradicted','superseded','deprecated','deleted_soft')",
        ]
        edge_params: list[object] = []
        if plan.filters.scope:
            edge_where.append("scope = ?")
            edge_params.append(plan.filters.scope)
        if plan.filters.namespace:
            edge_where.append("ns = ?")
            edge_params.append(plan.filters.namespace)
        node_budget = max(
            len(initial_seed_ids), min(512, max(64, limit * 32))
        )
        edge_budget = min(4096, max(256, node_budget * 8))
        hop_by_id = {record_id: 0 for record_id in initial_seed_ids}
        reached_ids = set(initial_seed_ids)
        frontier = set(initial_seed_ids)
        for hop in range(1, plan.graph_hops + 1):
            if not frontier or len(reached_ids) >= node_budget:
                break
            ordered_frontier = sorted(frontier)
            placeholders = ",".join("?" for _ in ordered_frontier)
            hop_where = [*edge_where]
            hop_params = [*edge_params]
            hop_where.append(
                f"(src_id in ({placeholders}) or dst_id in ({placeholders}) "
                f"or source_record_id in ({placeholders}))"
            )
            hop_params.extend(
                [*ordered_frontier, *ordered_frontier, *ordered_frontier, edge_budget]
            )
            edge_sql = (
                "select id, src_id, predicate as edge_type, dst_id, source_record_id "
                "from knowledge_edges "
                f"where {' and '.join(hop_where)} order by id limit ?"
            )
            with closing(self.store._connect()) as connection:
                rows = connection.execute(edge_sql, hop_params).fetchall()
            discovered: set[str] = set()
            for row in rows:
                src = str(row["src_id"])
                dst = str(row["dst_id"])
                source = str(row["source_record_id"] or "")
                graph.setdefault(src, set()).add(dst)
                graph.setdefault(dst, set()).add(src)
                if source:
                    graph.setdefault(source, set()).update((src, dst))
                    graph.setdefault(src, set()).add(source)
                    graph.setdefault(dst, set()).add(source)
                if src in frontier:
                    discovered.add(dst)
                if dst in frontier:
                    discovered.add(src)
                if source in frontier:
                    discovered.update((src, dst))
            available = node_budget - len(reached_ids)
            next_frontier = set(sorted(discovered - reached_ids)[:available])
            for record_id in next_frontier:
                hop_by_id[record_id] = hop
            reached_ids.update(next_frontier)
            frontier = next_frontier

        reached_batch = self.store.load_ir(
            ids=sorted(reached_ids),
            ns=plan.filters.namespace,
            scope=plan.filters.scope,
        )
        by_id = reached_batch.by_id()
        hits: list[LegHit] = []
        # ``seed_ids`` is a set because the graph expansion deduplicates lexical
        # seeds and neighbors.  Iterating it directly made equal-score graph
        # hits depend on the process hash seed, which in turn made reserved-tail
        # benchmark composition non-reproducible.  Stabilize both construction
        # and the final score-tie order by canonical record id.
        for record_id in sorted(reached_ids):
            record = by_id.get(record_id)
            if record is None or record.kind not in GRAPH_RETURN_KINDS or not plan.filters.matches(record):
                continue
            if (
                record_id in semantic_seed_ids
                and record_id not in lexical_seed_ids
                and not graph.get(record_id)
            ):
                # A semantic result is not graph evidence by itself. It gains a
                # graph source only after an actual in-boundary edge connects it.
                continue
            lexical = _lexical_score(record, tokens)
            neighbor_bonus = min(0.6, len(graph.get(record_id, set())) * 0.1)
            seed_bonus = 0.5 if record_id in lexical_seed_ids else 0.0
            semantic_seed_bonus = 0.25 if record_id in semantic_seed_ids else 0.0
            score = lexical + neighbor_bonus + seed_bonus + semantic_seed_bonus
            if score <= 0:
                score = neighbor_bonus
            hits.append(
                LegHit(
                    leg="graph",
                    record=record,
                    score=score,
                    reasons=[
                        f"graph_neighbors={len(graph.get(record_id, set()))}",
                        f"graph_hop={hop_by_id.get(record_id, 0)}",
                        f"lexical={lexical:.2f}",
                        *( ["semantic_seed=true"] if record_id in semantic_seed_ids else [] ),
                    ],
                )
            )
        return sorted(hits, key=lambda item: (-item.score, item.record.id))[:limit]


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
            metadatas=[
                _chroma_metadata(record, source_text)
                for record, source_text in zip(records, rendered, strict=True)
            ],
        )
        return len(records)

    def search(self, plan: RetrievalPlan, limit: int) -> list[LegHit]:
        query_text = plan.normalized_query or plan.query
        if not query_text.strip():
            return []
        if self.sync_on_search:
            self.sync_records(plan)
        collection = self._collection()
        query_options: dict[str, object] = {
            "query_embeddings": [self.embedding_model.embed(query_text)],
            "n_results": max(limit * 3, 10),
            "include": ["metadatas", "distances", "documents"],
        }
        boundary_filters = [
            {"vector_text_version": {"$eq": VECTOR_TEXT_VERSION}}
        ]
        if plan.filters.namespace:
            boundary_filters.append({"ns": {"$eq": plan.filters.namespace}})
        if plan.filters.scope:
            boundary_filters.append({"scope": {"$eq": plan.filters.scope}})
        if len(boundary_filters) == 1:
            query_options["where"] = boundary_filters[0]
        elif boundary_filters:
            query_options["where"] = {"$and": boundary_filters}
        response = collection.query(**query_options)
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
        return sorted(hits, key=lambda item: (-item.score, item.record.id))[:limit]


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


def _build_structured_sql(
    plan: RetrievalPlan,
    query_tokens: list[str],
    limit: int,
    *,
    include_graph_kinds: bool = False,
) -> tuple[str, list[object]]:
    allowed_kinds = ["CLM", "EVT", "REL", "STA"]
    if include_graph_kinds:
        allowed_kinds.extend(("ENT", "RAW"))
    kind_placeholders = ",".join("?" for _ in allowed_kinds)
    where_clauses = [f"r.kind in ({kind_placeholders})"]
    where_params: list[object] = list(allowed_kinds)

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
        id,
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
    id,
    payload_json,
    structured_score,
    lexical_hits,
    lexical_score,
    (structured_score + lexical_score + temporal_score + (case when conf < 1.0 then conf else 1.0 end * 0.15)) as sql_score
from scored_rows
where (structured_score + lexical_score) > 0
{gating_clause}
order by sql_score desc, lexical_hits desc, updated_at desc, id asc
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


def _chroma_metadata(record: MIRLRecord, source_text: str) -> dict[str, str]:
    attrs = record.attrs
    metadata = {
        "kind": record.kind.value,
        "ns": record.ns,
        "scope": record.scope,
        "vector_text_version": VECTOR_TEXT_VERSION,
        "source_hash": hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
    }
    if "predicate" in attrs:
        metadata["predicate"] = str(attrs.get("predicate"))
    if "subject" in attrs:
        metadata["subject"] = str(attrs.get("subject"))
    if "object" in attrs:
        metadata["object"] = str(attrs.get("object"))
    return metadata
