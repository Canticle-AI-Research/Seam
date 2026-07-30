from __future__ import annotations

import hashlib
import json
import re
from contextlib import closing
from dataclasses import dataclass
from typing import Protocol

from seam_runtime.knowledge_graph import (
    CURRENT_EXCLUDED_STATUSES,
    _edge_time_clauses,
    _episode_filter_clauses,
    _node_time_clauses,
)
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind, iter_textual_fields
from seam_runtime.models import EmbeddingModel
from seam_runtime.storage import SQLiteStore
from seam_runtime.temporal import parse_iso, temporal_distance_score
from seam_runtime.vector import INDEXABLE_KINDS, VECTOR_TEXT_VERSION, SQLiteVectorIndex
from seam_runtime.vector_adapters import VectorAdapter, search_vector_adapter
from seam_runtime.bm25 import BM25Index
from seam_runtime.retrieval import search_batch

from .types import GraphPathHop, LegHit, RetrievalPlan

GRAPH_RETURN_KINDS = {RecordKind.ENT, *INDEXABLE_KINDS}


def _visible_graph_node_ids(
    store: SQLiteStore,
    record_ids: set[str] | list[str] | tuple[str, ...],
    plan: RetrievalPlan,
) -> set[str]:
    """Return bounded candidate ids visible in the plan's graph-time view.

    G3 uses the same node-validity clauses as the knowledge-graph surface
    rather than reinterpreting expiry or supersession for retrieval. Inputs are
    always candidates produced from a bounded seed or edge query; chunks only
    avoid SQLite's parameter limit.
    """

    ordered_ids = sorted(set(record_ids))
    if not ordered_ids:
        return set()
    visible: set[str] = set()
    with closing(store._connect()) as connection:
        for start in range(0, len(ordered_ids), 500):
            chunk = ordered_ids[start : start + 500]
            placeholders = ",".join("?" for _ in chunk)
            where = [f"n.id in ({placeholders})"]
            params: list[object] = [*chunk]
            if plan.filters.scope:
                where.append("n.scope = ?")
                params.append(plan.filters.scope)
            if plan.filters.namespace:
                where.append("n.ns = ?")
                params.append(plan.filters.namespace)
            time_params: list[object] = []
            where.extend(
                _node_time_clauses(
                    time_params,
                    at=plan.graph_at,
                    include_history=plan.graph_include_history,
                )
            )
            rows = connection.execute(
                "select n.id from knowledge_nodes n "
                f"where {' and '.join(where)} order by n.id",
                [*params, *time_params],
            ).fetchall()
            visible.update(str(row["id"]) for row in rows)
    return visible


class SQLAdapter(Protocol):
    def search(self, plan: RetrievalPlan, limit: int) -> list[LegHit]:
        ...


class SemanticAdapter(Protocol):
    def search(self, plan: RetrievalPlan, limit: int) -> list[LegHit]:
        ...


class LegacyWeightedAdapter:
    """Materialize the former runtime ranking as a named orchestrator policy.

    The old public ``search_ir`` scorer is retained as a component-level helper
    for representation tests, but live compatibility retrieval reaches it only
    through this adapter and the orchestrator plan.  Keeping the semantics
    intact gives the RRF/graph path an auditable, same-runtime control.
    """

    def __init__(self, store: SQLiteStore, vector_adapter: VectorAdapter) -> None:
        self.store = store
        self.vector_adapter = vector_adapter

    def search(self, plan: RetrievalPlan, limit: int, *, flags) -> list[LegHit]:
        batch = self.store.load_ir(
            ns=plan.filters.namespace,
            scope=plan.filters.scope,
        )
        vector_scores = search_vector_adapter(
            self.vector_adapter,
            plan.query,
            limit=max(limit * 3, 10),
            namespace=plan.filters.namespace,
            scope=plan.filters.scope,
        )
        bm25 = None
        if plan.include_raw or flags.bm25_all_kinds:
            bm25 = BM25Index()
            for record in batch.records:
                if record.kind == RecordKind.RAW:
                    content = record.attrs.get("content")
                    text = content if isinstance(content, str) and content else ""
                elif flags.bm25_all_kinds:
                    text = " ".join(iter_textual_fields(record))
                else:
                    text = ""
                if text:
                    bm25.add(record.id, text)
        namespace = batch.records[0].ns if batch.records else None
        result = search_batch(
            batch,
            query=plan.query,
            scope=plan.filters.scope,
            limit=limit,
            vector_scores=vector_scores,
            namespace=namespace,
            include_raw=plan.include_raw,
            bm25_index=bm25,
            temporal_window=plan.temporal_window,
            temporal_reference=plan.temporal_reference,
            flags=flags,
        )
        return [
            LegHit(
                leg="legacy_weighted",
                record=candidate.record,
                score=candidate.score,
                reasons=list(candidate.reasons),
            )
            for candidate in result.candidates
        ]


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
            if (
                record is None
                or (record.kind == RecordKind.RAW and not plan.include_raw)
                or not plan.filters.matches(record)
            ):
                continue
            if plan.filters.active():
                raw_score += 0.05 * _matched_filter_count(record, plan)
            hits.append(LegHit(leg="vector", record=record, score=raw_score, reasons=[f"semantic={raw_score:.2f}"]))
        return sorted(hits, key=lambda item: (-item.score, item.record.id))[:limit]


class SQLiteTemporalAdapter:
    """Rank canonical records against an explicit temporal query context."""

    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def search(self, plan: RetrievalPlan, limit: int) -> list[LegHit]:
        if plan.temporal_reference is None and plan.temporal_window is None:
            return []
        batch = self.store.load_ir(
            ids=plan.filters.ids or None,
            ns=plan.filters.namespace,
            scope=plan.filters.scope,
        )
        allowed_kinds = {RecordKind.CLM, RecordKind.STA, RecordKind.EVT, RecordKind.REL}
        if plan.include_raw:
            allowed_kinds.add(RecordKind.RAW)
        hits: list[LegHit] = []
        for record in batch.records:
            if (
                record.kind not in allowed_kinds
                or (
                    not plan.graph_include_history
                    and record.status.value in CURRENT_EXCLUDED_STATUSES
                )
                or not plan.filters.matches(record)
            ):
                continue
            timestamp = parse_iso(record.t0)
            if plan.temporal_reference is not None:
                score = temporal_distance_score(plan.temporal_reference, timestamp)
                reason = f"temporal_reference={score:.4f}"
            else:
                assert plan.temporal_window is not None
                score = (
                    1.0
                    if timestamp is not None
                    and plan.temporal_window[0] <= timestamp <= plan.temporal_window[1]
                    else 0.0
                )
                reason = f"temporal_window={score:.4f}"
            if score > 0:
                hits.append(
                    LegHit(
                        leg="temporal",
                        record=record,
                        score=score,
                        reasons=[reason],
                    )
                )
        return sorted(hits, key=lambda item: (-item.score, item.record.id))[:limit]


class GraphNodeSemanticAdapter:
    """Expose derived graph-node vectors as an explicit RRF leg and seed set."""

    def __init__(
        self, store: SQLiteStore, embedding_model: EmbeddingModel
    ) -> None:
        self.store = store
        self.embedding_model = embedding_model

    def search(
        self,
        plan: RetrievalPlan,
        limit: int,
        *,
        min_score: float = 0.0,
    ) -> tuple[list[str], list[LegHit]]:
        query_text = plan.normalized_query or plan.query
        if not query_text.strip() or limit <= 0:
            return [], []
        model_name = (
            getattr(self.embedding_model, "name", "")
            or self.embedding_model.__class__.__name__
        )
        ranked = self.store.search_node_vectors(
            self.embedding_model.embed(query_text),
            model_name,
            ns=plan.filters.namespace,
            scope=plan.filters.scope,
            limit=limit,
            min_score=min_score,
        )
        visible = _visible_graph_node_ids(
            self.store, [node_id for node_id, _score in ranked], plan
        )
        ranked = [
            (node_id, score)
            for node_id, score in ranked
            if node_id in visible
        ]
        if not ranked:
            return [], []
        with closing(self.store._connect()) as connection:
            placeholders = ",".join("?" for _ in ranked)
            rows = connection.execute(
                "select id, source_record_id from knowledge_nodes "
                f"where id in ({placeholders})",
                [node_id for node_id, _score in ranked],
            ).fetchall()
        source_by_node = {
            str(row["id"]): str(row["source_record_id"] or row["id"])
            for row in rows
        }
        batch = self.store.load_ir(
            ids=sorted(set(source_by_node.values())),
            ns=plan.filters.namespace,
            scope=plan.filters.scope,
        )
        records = batch.by_id()
        hits: list[LegHit] = []
        accepted_node_ids: list[str] = []
        for node_id, score in ranked:
            record = records.get(source_by_node.get(node_id, ""))
            if (
                record is None
                or (record.kind == RecordKind.RAW and not plan.include_raw)
                or not plan.filters.matches(record)
            ):
                continue
            accepted_node_ids.append(node_id)
            hits.append(
                LegHit(
                    leg="graph_node",
                    record=record,
                    score=score,
                    reasons=[f"graph_node_semantic={score:.4f}"],
                )
            )
        return accepted_node_ids, hits


class SQLiteGraphAdapter:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def search(
        self,
        plan: RetrievalPlan,
        limit: int,
        *,
        seed_record_ids: list[str] | tuple[str, ...] = (),
        seed_node_ids: list[str] | tuple[str, ...] = (),
    ) -> list[LegHit]:
        query_text = plan.normalized_query or plan.query
        tokens = _unique_tokens(_tokens(query_text))
        if (
            not tokens
            and not plan.filters.active()
            and not seed_record_ids
            and not seed_node_ids
        ):
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
        semantic_seed_ids.update(
            _visible_graph_node_ids(
                self.store,
                sorted(set(seed_node_ids))[:300],
                plan,
            )
        )
        visible_seed_ids = _visible_graph_node_ids(
            self.store,
            {record.id for record in matching_records} | semantic_seed_ids,
            plan,
        )
        matching_records = [
            record for record in matching_records if record.id in visible_seed_ids
        ]
        semantic_seed_ids &= visible_seed_ids
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
        edge_where: list[str] = []
        edge_params: list[object] = []
        if plan.filters.scope:
            edge_where.append("e.scope = ?")
            edge_params.append(plan.filters.scope)
        if plan.filters.namespace:
            edge_where.append("e.ns = ?")
            edge_params.append(plan.filters.namespace)
        edge_time_params: list[object] = []
        edge_where.extend(
            _edge_time_clauses(
                edge_time_params,
                at=plan.graph_at,
                include_history=plan.graph_include_history,
            )
        )
        edge_params.extend(edge_time_params)
        node_budget = max(
            len(initial_seed_ids), min(512, max(64, limit * 32))
        )
        edge_budget = min(4096, max(256, node_budget * 8))
        hop_by_id = {record_id: 0 for record_id in initial_seed_ids}
        # The parent edge that first discovered a node keeps returned paths
        # exact and deterministic. Hop-0 seeds intentionally remain path-free.
        parent_edge: dict[str, tuple[str, str, str, str, str, str]] = {}
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
                f"(e.src_id in ({placeholders}) or e.dst_id in ({placeholders}) "
                f"or e.source_record_id in ({placeholders}))"
            )
            hop_params.extend(
                [*ordered_frontier, *ordered_frontier, *ordered_frontier, edge_budget]
            )
            edge_sql = (
                "select e.id, e.src_id, e.predicate as edge_type, e.dst_id, e.source_record_id "
                "from knowledge_edges e "
                f"where {' and '.join(hop_where)} order by e.id limit ?"
            )
            with closing(self.store._connect()) as connection:
                rows = connection.execute(edge_sql, hop_params).fetchall()
            edge_node_ids = {
                node_id
                for row in rows
                for node_id in (
                    str(row["src_id"]),
                    str(row["dst_id"]),
                    str(row["source_record_id"] or ""),
                )
                if node_id
            }
            visible_edge_node_ids = _visible_graph_node_ids(
                self.store, edge_node_ids, plan
            )
            discovered: set[str] = set()
            discovery_candidates: dict[
                str, list[tuple[str, str, str, str, str, str]]
            ] = {}

            def propose(
                child: str,
                parent: str,
                edge_id: str,
                predicate: str,
                src: str,
                dst: str,
                source: str,
            ) -> None:
                discovery_candidates.setdefault(child, []).append(
                    (parent, edge_id, predicate, src, dst, source)
                )

            for row in rows:
                edge_id = str(row["id"])
                src = str(row["src_id"])
                dst = str(row["dst_id"])
                predicate = str(row["edge_type"] or "")
                source = str(row["source_record_id"] or "")
                if src in visible_edge_node_ids and dst in visible_edge_node_ids:
                    graph.setdefault(src, set()).add(dst)
                    graph.setdefault(dst, set()).add(src)
                if source in visible_edge_node_ids:
                    if src in visible_edge_node_ids:
                        graph.setdefault(source, set()).add(src)
                        graph.setdefault(src, set()).add(source)
                    if dst in visible_edge_node_ids:
                        graph.setdefault(source, set()).add(dst)
                        graph.setdefault(dst, set()).add(source)
                if src in frontier and dst in visible_edge_node_ids:
                    discovered.add(dst)
                    propose(dst, src, edge_id, predicate, src, dst, source)
                if dst in frontier and src in visible_edge_node_ids:
                    discovered.add(src)
                    propose(src, dst, edge_id, predicate, src, dst, source)
                if source in frontier:
                    if src in visible_edge_node_ids:
                        discovered.add(src)
                        propose(src, source, edge_id, predicate, src, dst, source)
                    if dst in visible_edge_node_ids:
                        discovered.add(dst)
                        propose(dst, source, edge_id, predicate, src, dst, source)
            available = node_budget - len(reached_ids)
            next_frontier = set(sorted(discovered - reached_ids)[:available])
            for record_id in next_frontier:
                hop_by_id[record_id] = hop
                candidates = discovery_candidates.get(record_id)
                if candidates:
                    parent_edge[record_id] = min(candidates)
            reached_ids.update(next_frontier)
            frontier = next_frontier

        reached_batch = self.store.load_ir(
            ids=sorted(reached_ids),
            ns=plan.filters.namespace,
            scope=plan.filters.scope,
        )
        by_id = reached_batch.by_id()

        def reconstruct_path(
            record_id: str,
        ) -> tuple[tuple[str, str, str, str, str], ...]:
            steps: list[tuple[str, str, str, str, str]] = []
            current = record_id
            for _ in range(plan.graph_hops):
                edge = parent_edge.get(current)
                if edge is None:
                    break
                parent_id, edge_id, predicate, src_id, dst_id, source_record_id = edge
                steps.append((edge_id, predicate, src_id, dst_id, source_record_id))
                current = parent_id
            steps.reverse()
            return tuple(steps)

        paths_by_record = {
            record_id: reconstruct_path(record_id)
            for record_id in reached_ids
            if hop_by_id.get(record_id, 0) > 0
        }
        edge_ids = sorted(
            {edge_id for path in paths_by_record.values() for edge_id, *_ in path}
        )
        episodes_by_edge: dict[str, tuple[str, ...]] = {}
        if edge_ids:
            placeholders = ",".join("?" for _ in edge_ids)
            episode_where, episode_params = _episode_filter_clauses(
                namespace=plan.filters.namespace,
                scope=plan.filters.scope,
                agent_id=None,
                at=plan.graph_at,
                include_history=plan.graph_include_history,
            )
            with closing(self.store._connect()) as connection:
                episode_rows = connection.execute(
                    "select kee.edge_id as edge_id, ep.id as episode_id "
                    "from knowledge_edge_episodes kee "
                    "join knowledge_episodes ep on ep.id = kee.episode_id "
                    f"where kee.edge_id in ({placeholders}) and {' and '.join(episode_where)} "
                    "order by kee.edge_id, ep.id",
                    [*edge_ids, *episode_params],
                ).fetchall()
            grouped: dict[str, list[str]] = {}
            for row in episode_rows:
                grouped.setdefault(str(row["edge_id"]), []).append(str(row["episode_id"]))
            episodes_by_edge = {
                edge_id: tuple(episode_ids)
                for edge_id, episode_ids in grouped.items()
            }
        hits: list[LegHit] = []
        # ``seed_ids`` is a set because the graph expansion deduplicates lexical
        # seeds and neighbors.  Iterating it directly made equal-score graph
        # hits depend on the process hash seed, which in turn made reserved-tail
        # benchmark composition non-reproducible.  Stabilize both construction
        # and the final score-tie order by canonical record id.
        for record_id in sorted(reached_ids):
            record = by_id.get(record_id)
            if (
                record is None
                or record.kind not in GRAPH_RETURN_KINDS
                or (record.kind == RecordKind.RAW and not plan.include_raw)
                or not plan.filters.matches(record)
            ):
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
            path = tuple(
                GraphPathHop(
                    edge_id=edge_id,
                    predicate=predicate,
                    src_id=src_id,
                    dst_id=dst_id,
                    source_record_id=source_record_id or None,
                    episode_ids=episodes_by_edge.get(edge_id, ()),
                )
                for edge_id, predicate, src_id, dst_id, source_record_id in paths_by_record.get(
                    record_id, ()
                )
            )
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
                    path=path,
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
        records = [
            record
            for record in batch.records
            if record.kind in INDEXABLE_KINDS
            and record.status.value not in CURRENT_EXCLUDED_STATUSES
        ]
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

    def delete_records(self, record_ids: list[str]) -> None:
        ids = sorted({str(record_id).strip() for record_id in record_ids})
        if not ids or any(not record_id for record_id in ids):
            raise ValueError("record_ids must contain non-empty references")
        self._collection().delete(ids=ids)

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
            if (
                record is None
                or (record.kind == RecordKind.RAW and not plan.include_raw)
                or not plan.filters.matches(record)
            ):
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
    if plan.include_raw:
        allowed_kinds.append("RAW")
    if include_graph_kinds:
        allowed_kinds.append("ENT")
        if "RAW" not in allowed_kinds:
            allowed_kinds.append("RAW")
    kind_placeholders = ",".join("?" for _ in allowed_kinds)
    where_clauses = [f"r.kind in ({kind_placeholders})"]
    where_params: list[object] = list(allowed_kinds)
    if not plan.graph_include_history:
        excluded = sorted(CURRENT_EXCLUDED_STATUSES)
        status_placeholders = ",".join("?" for _ in excluded)
        where_clauses.append(f"r.status not in ({status_placeholders})")
        where_params.extend(excluded)

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
        # Two explicit boundary filters (normally namespace + scope) are
        # sufficient to retain non-lexical tail records.  The historical
        # ``search_ir`` contract ranked that bounded tail through its temporal
        # channel; keeping it here preserves closure/fact composition without
        # admitting unrelated namespaces or scopes. Graph seed selection stays
        # lexical so zero-hop/hop bounds cannot be bypassed by boundary-only
        # matches.
        structured_gate = (
            0.8 if plan.include_raw and not include_graph_kinds else 1.0
        )
        gating_clause = (
            f"and (lexical_hits > 0 or structured_score >= {structured_gate})"
        )

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
