from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from .identity_resolution import (
    accept_merge as accept_identity_merge_op,
)
from .identity_resolution import (
    generate_merge_candidates as generate_identity_merge_candidates_op,
)
from .identity_resolution import (
    list_merges as list_identity_merges,
)
from .identity_resolution import (
    merge_audit as identity_merge_audit_detail,
)
from .identity_resolution import (
    split_merge as split_identity_merge_op,
)
from .knowledge_graph import (
    graph_stats,
    init_knowledge_graph,
)
from .knowledge_graph import (
    node_detail as knowledge_node_detail,
)
from .knowledge_graph import (
    project_records as project_knowledge_records,
)
from .knowledge_graph import (
    query_graph as query_knowledge_graph,
)
from .knowledge_graph import (
    remove_records as remove_knowledge_records,
)
from .knowledge_graph import (
    supersede_source as supersede_knowledge_source,
)
from .mirl import SYMBOL_FOR_KIND, IRBatch, MIRLRecord, Pack, PersistReport, RecordKind, TraceGraph, utc_now
from .pool import ConnectionPool
from .reasoning_graph import (
    ReasoningRetrievalCandidate,
    finalize_verified_reasoning_outcome,
    get_reasoning_verification,
    init_reasoning_graph,
    list_reasoning_retrievals,
    list_reasoning_verifications,
    reasoning_graph,
    record_reasoning_retrieval,
    record_reasoning_verification,
    transition_reasoning_node,
)
from .reasoning_graph import (
    add_reasoning_edge as add_reasoning_edge_row,
)
from .reasoning_graph import (
    add_reasoning_node as add_reasoning_node_row,
)
from .reasoning_graph import (
    get_reasoning_node as get_reasoning_node_row,
)
from .reasoning_graph import get_reasoning_retrieval as get_reasoning_retrieval_row
from .retry import retry_db_operation
from .workspace import (
    append_workspace_event as append_workspace_event_row,
)
from .workspace import (
    create_workspace_run as create_workspace_run_row,
)
from .workspace import (
    init_workspace_schema,
    run_status,
    workspace_event_from_row,
    workspace_run_from_row,
)


class SQLiteStore:
    def __init__(self, path: str | Path = "seam.db", pool_size: int | None = None) -> None:
        self.path = str(path)
        self._mem_anchor: sqlite3.Connection | None = None
        if self.path != ":memory:":
            Path(self.path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        else:
            # Keep one anchor connection alive so that the shared in-memory
            # database persists across per-operation connections.
            self._mem_anchor = sqlite3.connect(
                f"file:mem_{id(self)}?mode=memory&cache=shared",
                uri=True,
                timeout=5.0,
                check_same_thread=False,
            )
        self._init_schema()
        resolved_pool_size = pool_size if pool_size is not None else int(os.environ.get("SEAM_DB_POOL_SIZE", "5"))
        self._pool = ConnectionPool(
            connect_factory=self._connect,
            pool_size=resolved_pool_size,
            idle_timeout=int(os.environ.get("SEAM_DB_POOL_TIMEOUT", "300")),
        )

    def _connect(self) -> sqlite3.Connection:
        if self.path == ":memory:":
            connection = sqlite3.connect(
                f"file:mem_{id(self)}?mode=memory&cache=shared",
                uri=True,
                timeout=5.0,
                check_same_thread=False,
            )
        else:
            connection = sqlite3.connect(
                self.path,
                timeout=5.0,
                check_same_thread=False,
            )
        connection.row_factory = sqlite3.Row
        if self.path != ":memory:":
            connection.execute("pragma journal_mode=WAL")
        connection.execute("pragma busy_timeout=5000")
        connection.execute("pragma foreign_keys=ON")
        return connection

    def close(self) -> None:
        pool = getattr(self, "_pool", None)
        if pool is not None:
            pool.close()
        if self._mem_anchor is not None:
            self._mem_anchor.close()
            self._mem_anchor = None

    def __enter__(self) -> "SQLiteStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _init_schema(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                create table if not exists raw_docs (
                    id text primary key,
                    ns text not null,
                    scope text not null,
                    source_ref text,
                    content text not null,
                    created_at text not null
                );
                create table if not exists raw_spans (
                    id text primary key,
                    raw_id text not null,
                    start integer not null,
                    end integer not null,
                    span_text text,
                    created_at text not null
                );
                create table if not exists document_status (
                    document_id text primary key,
                    ns text not null,
                    scope text not null,
                    source_ref text not null,
                    source_hash text not null,
                    byte_count integer not null,
                    chunk_count integer not null,
                    extraction_status text not null,
                    indexed_status text not null,
                    deleted_at text,
                    metadata_json text not null,
                    created_at text not null,
                    updated_at text not null
                );
                create table if not exists ir_records (
                    id text primary key,
                    kind text not null,
                    ns text not null,
                    scope text not null,
                    status text not null,
                    conf real not null,
                    t0 text,
                    t1 text,
                    created_at text not null,
                    updated_at text not null,
                    payload_json text not null
                );
                create table if not exists ir_edges (
                    id integer primary key autoincrement,
                    src_id text not null,
                    edge_type text not null,
                    dst_id text not null
                );
                create table if not exists symbol_table (
                    id text primary key,
                    ns text not null,
                    symbol text not null,
                    expansion text not null,
                    payload_json text not null
                );
                create table if not exists pack_store (
                    id text primary key,
                    mode text not null,
                    lens text not null,
                    refs_json text not null,
                    payload_json text not null,
                    created_at text not null
                );
                create table if not exists prov_log (
                    id text primary key,
                    entity text,
                    activity text,
                    agent text,
                    payload_json text not null
                );
                create table if not exists vector_index (
                    record_id text not null,
                    model_name text not null,
                    dimension integer not null,
                    source_text text not null,
                    source_hash text not null default '',
                    namespace text not null default '',
                    scope text not null default '',
                    vector_json text not null,
                    updated_at text not null,
                    primary key (record_id, model_name)
                );
                create table if not exists machine_artifacts (
                    artifact_id text primary key,
                    source_type text not null,
                    source_id text not null,
                    codec text,
                    transform_chain text,
                    tokenizer text,
                    sha256_raw text,
                    sha256_machine text,
                    bytes_raw integer,
                    bytes_machine integer,
                    tokens_raw integer,
                    tokens_machine integer,
                    token_savings_ratio real,
                    roundtrip_ok integer not null,
                    metadata_json text not null,
                    artifact_json text not null,
                    machine_text text,
                    created_at text not null
                );
                create table if not exists surface_artifacts (
                    surface_id text primary key,
                    artifact_path text not null unique,
                    mode text not null,
                    payload_format text not null,
                    source_ref text,
                    source_sha256 text,
                    payload_sha256 text not null,
                    surface_sha256 text not null,
                    payload_bytes integer not null,
                    surface_bytes integer not null,
                    width integer not null,
                    height integer not null,
                    capacity_bytes integer not null,
                    verification_status text not null,
                    query_status text not null,
                    import_status text not null,
                    metadata_json text not null,
                    created_at text not null,
                    updated_at text not null
                );
                create table if not exists benchmark_runs (
                    run_id text primary key,
                    requested_suite text,
                    executed_suites text not null,
                    status text not null,
                    bundle_hash text,
                    manifest_json text not null,
                    summary_json text not null,
                    report_json text not null,
                    created_at text not null
                );
                create table if not exists benchmark_cases (
                    run_id text not null,
                    case_id text not null,
                    family text not null,
                    status text not null,
                    case_hash text,
                    metrics_json text not null,
                    trace_json text not null,
                    case_json text not null,
                    primary key (run_id, case_id)
                );
                create table if not exists projection_index (
                    projection_id text primary key,
                    record_id text not null,
                    projection_kind text not null,
                    projection_text text not null,
                    tokenizer text,
                    token_count integer,
                    metadata_json text not null,
                    updated_at text not null
                );
                create table if not exists retrieval_event (
                    event_id integer primary key autoincrement,
                    ts text not null,
                    run_id text not null,
                    scope text,
                    query text not null,
                    candidate_ids_json text not null,
                    ranks_json text,
                    scores_json text,
                    reasons_json text,
                    context_hash text,
                    gold_answer text,
                    gold_hit_ids_json text,
                    context_recall real,
                    judge_score real,
                    answer text,
                    source_kind text not null,
                    source_ref text,
                    stale_source integer not null default 0,
                    schema_version integer not null default 1,
                    extra_json text
                );
                create table if not exists improvement_proposal (
                    proposal_id integer primary key autoincrement,
                    created_at text not null,
                    kind text not null,
                    summary text not null,
                    rationale text,
                    evidence_event_ids_json text,
                    evidence_case_ids_json text,
                    proposed_change_json text,
                    holdout_violation integer not null default 0,
                    schema_version integer not null default 1,
                    extra_json text
                );
                create table if not exists proposal_decision (
                    decision_id integer primary key autoincrement,
                    proposal_id integer not null,
                    ts text not null,
                    status text not null,
                    reason text,
                    actor text,
                    foreign key (proposal_id) references improvement_proposal(proposal_id)
                );
                create table if not exists retrieval_flag_state (
                    flag_key text primary key,
                    flag_value text not null,
                    source_proposal_id integer,
                    applied_at text not null
                );
                create index if not exists idx_ir_records_kind on ir_records (kind);
                create index if not exists idx_ir_records_ns_scope on ir_records (ns, scope);
                create index if not exists idx_document_status_source on document_status (source_ref);
                create index if not exists idx_document_status_hash on document_status (source_hash);
                create index if not exists idx_ir_edges_src on ir_edges (src_id);
                create index if not exists idx_ir_edges_dst on ir_edges (dst_id);
                create unique index if not exists idx_ir_edges_unique
                    on ir_edges (src_id, edge_type, dst_id);
                create index if not exists idx_machine_artifacts_source on machine_artifacts (source_type, source_id);
                create index if not exists idx_surface_artifacts_payload on surface_artifacts (payload_sha256);
                create index if not exists idx_surface_artifacts_source on surface_artifacts (source_ref);
                create index if not exists idx_benchmark_cases_family on benchmark_cases (family);
                create unique index if not exists idx_projection_record_kind on projection_index (record_id, projection_kind);
                create index if not exists idx_retrieval_event_run on retrieval_event (run_id);
                create index if not exists idx_retrieval_event_ts on retrieval_event (ts);
                create index if not exists idx_retrieval_event_stale on retrieval_event (stale_source);
                create index if not exists idx_improvement_proposal_kind on improvement_proposal (kind);
                create index if not exists idx_improvement_proposal_violation on improvement_proposal (holdout_violation);
                create index if not exists idx_improvement_proposal_created on improvement_proposal (created_at);
                create index if not exists idx_proposal_decision_proposal on proposal_decision (proposal_id);
                create index if not exists idx_proposal_decision_ts on proposal_decision (ts);
                """
            )
            connection.execute("pragma foreign_keys = on")
            self._cleanup_orphan_edges(connection)
            init_knowledge_graph(connection)
            init_workspace_schema(connection)
            init_reasoning_graph(connection)
            connection.commit()

    def _cleanup_orphan_edges(self, connection: sqlite3.Connection) -> None:
        """Remove edges whose src or dst references a record that no longer exists.

        ir_edges has no FK constraints because it uses virtual entity IDs
        (e.g. ``ent:turn:xxx``, ``ent:user:xxx``, ``prov``, ``evidence`` edges).
        We run a best-effort orphan sweep at open time: any edge where EITHER
        endpoint looks like a record ID (starts with a known prefix) but is
        missing from ir_records is removed. Virtual entity IDs are preserved.
        """
        record_prefixes = ("clm:", "rel:", "sym:", "raw:", "sta:", "evt:")
        prefix_clause = " or ".join(
            f"src_id like '{p}%'" for p in record_prefixes
        )
        connection.execute(
            f"delete from ir_edges "
            f"where ({prefix_clause}) and src_id not in (select id from ir_records)"
        )
        prefix_clause_dst = " or ".join(
            f"dst_id like '{p}%'" for p in record_prefixes
        )
        connection.execute(
            f"delete from ir_edges "
            f"where ({prefix_clause_dst}) and dst_id not in (select id from ir_records)"
        )

    def get_stats(self) -> dict[str, object]:
        with self._pool.checkout() as connection:
            total_records = connection.execute("select count(*) from ir_records").fetchone()[0]
            vector_entries = connection.execute("select count(*) from vector_index").fetchone()[0]
            pack_entries = connection.execute("select count(*) from pack_store").fetchone()[0]
            namespaces = connection.execute("select count(distinct ns) from ir_records").fetchone()[0]
            scopes = connection.execute("select count(distinct scope) from ir_records").fetchone()[0]
            benchmark_runs = connection.execute("select count(*) from benchmark_runs").fetchone()[0]
            machine_artifacts = connection.execute("select count(*) from machine_artifacts").fetchone()[0]
            surface_artifacts = connection.execute("select count(*) from surface_artifacts").fetchone()[0]
            edge_count = connection.execute("select count(*) from ir_edges").fetchone()[0]
            doc_status_count = connection.execute("select count(*) from document_status").fetchone()[0]
            knowledge = graph_stats(connection)

            kinds_rows = connection.execute("select kind, count(*) as c from ir_records group by kind").fetchall()
            record_kinds: dict[str, int] = {}
            for row in kinds_rows:
                try:
                    kind_enum = RecordKind(row["kind"])
                except ValueError:
                    continue
                symbol = SYMBOL_FOR_KIND.get(kind_enum)
                if symbol is None:
                    continue
                record_kinds[symbol] = row["c"]

            # ── Edge kind distribution ──
            edge_kinds_rows = connection.execute(
                "select edge_type, count(*) as c from ir_edges group by edge_type"
            ).fetchall()
            edge_kinds: dict[str, int] = {row["edge_type"]: row["c"] for row in edge_kinds_rows}

            # ── Degree statistics ──
            # avg degree = 2 * edges / nodes  (each edge contributes degree to both endpoints)
            avg_degree = round(2.0 * edge_count / total_records, 2) if total_records > 0 else 0.0
            max_degree_row = connection.execute(
                "select node_id, total_deg from ("
                "  select node_id, sum(deg) as total_deg from ("
                "    select src_id as node_id, count(*) as deg from ir_edges group by src_id"
                "    union all"
                "    select dst_id as node_id, count(*) as deg from ir_edges group by dst_id"
                "  ) group by node_id"
                ") order by total_deg desc limit 1"
            ).fetchone()
            max_degree = max_degree_row["total_deg"] if max_degree_row else 0
            max_degree_node = max_degree_row["node_id"] if max_degree_row else None

            # ── Connected components (lightweight estimate via isolated node count) ──
            # Nodes that appear in edges (either side)
            connected_nodes = connection.execute(
                "select count(distinct n) from ("
                "  select src_id as n from ir_edges"
                "  union"
                "  select dst_id as n from ir_edges"
                ")"
            ).fetchone()[0]
            isolated_nodes = total_records - connected_nodes if total_records > connected_nodes else 0

            # ── Vector index metadata ──
            vector_models_rows = connection.execute(
                "select model_name, dimension, count(*) as c from vector_index group by model_name, dimension"
            ).fetchall()
            vector_models = [
                {"model": row["model_name"], "dimension": row["dimension"], "count": row["c"]}
                for row in vector_models_rows
            ]

            # Drifted vectors: vectors whose updated_at is older than the record's updated_at
            drifted_vectors = connection.execute(
                "select count(*) from vector_index v"
                " join ir_records r on v.record_id = r.id"
                " where r.updated_at > v.updated_at"
            ).fetchone()[0]

            # ── Document status breakdown ──
            doc_status_rows = connection.execute(
                "select extraction_status, indexed_status, count(*) as c"
                " from document_status group by extraction_status, indexed_status"
            ).fetchall()
            doc_statuses: dict[str, int] = {}
            for row in doc_status_rows:
                key = f"{row['extraction_status']}/{row['indexed_status']}"
                doc_statuses[key] = row["c"]

            # ── Ingest pipeline: today's documents ──
            today_prefix = utc_now()[:10]  # "YYYY-MM-DD"
            docs_today = connection.execute(
                "select count(*) from document_status where created_at >= ?",
                (today_prefix,),
            ).fetchone()[0]
            records_today = connection.execute(
                "select count(*) from ir_records where created_at >= ?",
                (today_prefix,),
            ).fetchone()[0]

            # ── Superseded / contradicted counts ──
            superseded_count = connection.execute(
                "select count(*) from ir_records where status = 'superseded'"
            ).fetchone()[0]
            contradicted_count = connection.execute(
                "select count(*) from ir_records where status = 'contradicted'"
            ).fetchone()[0]

            return {
            "total_records": total_records,
            "vector_entries": vector_entries,
            "pack_entries": pack_entries,
            "namespaces": namespaces,
            "scopes": scopes,
            "benchmark_runs": benchmark_runs,
            "machine_artifacts": machine_artifacts,
            "surface_artifacts": surface_artifacts,
            "edge_count": edge_count,
                "doc_status_count": doc_status_count,
                "knowledge_graph": knowledge,
                "knowledge_node_count": knowledge["node_count"],
                "knowledge_edge_count": knowledge["edge_count"],
            "record_kinds": record_kinds,
            "edge_kinds": edge_kinds,
            "avg_degree": avg_degree,
            "max_degree": max_degree,
            "max_degree_node": max_degree_node,
            "connected_nodes": connected_nodes,
            "isolated_nodes": isolated_nodes,
            "vector_models": vector_models,
            "drifted_vectors": drifted_vectors,
            "doc_statuses": doc_statuses,
            "docs_today": docs_today,
            "records_today": records_today,
            "superseded_count": superseded_count,
            "contradicted_count": contradicted_count,
        }

    def list_namespaces(self, limit: int = 100) -> list[str]:
        with self._pool.checkout() as connection:
            rows = connection.execute(
                "select distinct ns from ir_records order by ns limit ?",
                (limit,),
            ).fetchall()
        return [row["ns"] for row in rows]

    def list_scopes(self, ns: str, limit: int = 100) -> list[str]:
        with self._pool.checkout() as connection:
            rows = connection.execute(
                "select distinct scope from ir_records where ns = ? order by scope limit ?",
                (ns, limit),
            ).fetchall()
        return [row["scope"] for row in rows]

    def list_record_summaries(self, ns: str, scope: str, limit: int = 100) -> list[dict[str, object]]:
        with self._pool.checkout() as connection:
            rows = connection.execute(
                """
                select id, kind, status, updated_at
                from ir_records
                where ns = ? and scope = ?
                order by updated_at desc, id
                limit ?
                """,
                (ns, scope, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def _reconcile_entities(self, connection: sqlite3.Connection, batch: IRBatch) -> tuple[dict[str, str], set[str]]:
        """Cross-turn entity coreference, scoped strictly per ``ns``.

        Every ``compile_nl`` call is independent and mints a fresh ``ent:``
        id per label, so the same real-world entity gets a different id in
        every turn it is mentioned in (HISTORY#321/#323 cat1 root cause).
        This makes the FIRST occurrence of a normalized label within an ``ns``
        canonical: later ENT records with the same normalized label (from an
        earlier persist call, or earlier in this same incoming batch) are not
        inserted; ``id_map`` carries their id to the canonical one so callers
        can rewrite CLM/REL references before persisting. Never merges across
        ``ns`` (SEAM's existing multi-tenant isolation boundary, HISTORY#274).
        """
        id_map: dict[str, str] = {}
        skip_ids: set[str] = set()
        batch_ent_records = [r for r in batch.records if r.kind == RecordKind.ENT]
        if not batch_ent_records:
            return id_map, skip_ids
        namespaces = {r.ns for r in batch_ent_records}
        for ns in namespaces:
            canonical_by_norm: dict[str, str] = {}
            for row in connection.execute(
                "select id, payload_json from ir_records where kind = ? and ns = ? order by created_at, id",
                (RecordKind.ENT.value, ns),
            ):
                existing_attrs = json.loads(row["payload_json"]).get("attrs", {})
                label = existing_attrs.get("label")
                if not label:
                    continue
                canonical_by_norm.setdefault(_normalize_entity_label(str(label)), row["id"])
            for record in batch_ent_records:
                if record.ns != ns:
                    continue
                label = record.attrs.get("label")
                if not label:
                    continue
                norm = _normalize_entity_label(str(label))
                canonical_id = canonical_by_norm.get(norm)
                if canonical_id is not None and canonical_id != record.id:
                    id_map[record.id] = canonical_id
                    skip_ids.add(record.id)
                else:
                    canonical_by_norm.setdefault(norm, record.id)
        return id_map, skip_ids

    @staticmethod
    def _remap_entity_refs(record: MIRLRecord, id_map: dict[str, str]) -> None:
        if not id_map:
            return
        if record.kind == RecordKind.CLM:
            subject = record.attrs.get("subject")
            if subject in id_map:
                record.attrs["subject"] = id_map[subject]
        elif record.kind == RecordKind.REL:
            src = record.attrs.get("src")
            if src in id_map:
                record.attrs["src"] = id_map[src]
            dst = record.attrs.get("dst")
            if dst in id_map:
                record.attrs["dst"] = id_map[dst]

    @retry_db_operation()
    def persist_ir(self, batch: IRBatch) -> PersistReport:
        with self._pool.checkout() as connection:
            id_map, skip_ids = self._reconcile_entities(connection, batch)
            stored_ids: list[str] = []
            for record in batch.records:
                if record.id in skip_ids:
                    continue
                self._remap_entity_refs(record, id_map)
                stored_ids.append(record.id)
                # Capture old CLM subject before overwriting.
                old_clm_subject: str | None = None
                if record.kind == RecordKind.CLM:
                    old_row = connection.execute(
                        "select payload_json from ir_records where id = ?",
                        (record.id,),
                    ).fetchone()
                    if old_row is not None:
                        old_attrs = json.loads(old_row[0]).get("attrs", {})
                        old_clm_subject = old_attrs.get("subject")
                payload = json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"))
                connection.execute(
                    """
                    insert or replace into ir_records
                    (id, kind, ns, scope, status, conf, t0, t1, created_at, updated_at, payload_json)
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (record.id, record.kind.value, record.ns, record.scope, record.status.value, record.conf, record.t0, record.t1, record.created_at, record.updated_at, payload),
                )
                self._persist_specialized(connection, record)
                self._persist_edges(connection, record, old_clm_subject=old_clm_subject)
            # The knowledge graph is a deterministic projection of the same
            # canonical MIRL write. It is built automatically for every ingest
            # surface and committed atomically with the records it represents.
            projected = [record for record in batch.records if record.id not in skip_ids]
            project_knowledge_records(connection, projected)
            connection.commit()
        return PersistReport(stored_ids=stored_ids, store_path=self.path)

    @retry_db_operation()
    def upsert_document_status(
        self,
        *,
        document_id: str,
        ns: str,
        scope: str,
        source_ref: str,
        source_hash: str,
        byte_count: int,
        chunk_count: int,
        extraction_status: str,
        indexed_status: str,
        metadata: dict[str, object] | None = None,
        deleted_at: str | None = None,
    ) -> dict[str, object]:
        now = utc_now()
        with self._pool.checkout() as connection:
            existing = connection.execute("select created_at from document_status where document_id = ?", (document_id,)).fetchone()
            created_at = existing["created_at"] if existing else now
            connection.execute(
                """
                insert or replace into document_status
                (document_id, ns, scope, source_ref, source_hash, byte_count, chunk_count,
                 extraction_status, indexed_status, deleted_at, metadata_json, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document_id,
                    ns,
                    scope,
                    source_ref,
                    source_hash,
                    int(byte_count),
                    int(chunk_count),
                    extraction_status,
                    indexed_status,
                    deleted_at,
                    json.dumps(metadata or {}, sort_keys=True, separators=(",", ":")),
                    created_at,
                    now,
                ),
            )
            connection.commit()
        return self.read_document_status(document_id)

    def read_document_status(self, document_id: str) -> dict[str, object]:
        with self._pool.checkout() as connection:
            row = connection.execute("select * from document_status where document_id = ?", (document_id,)).fetchone()
        if row is None:
            raise KeyError(document_id)
        return _document_status_row(row)

    def mark_document_superseded_by_source_ref(self, source_ref: str, except_document_id: str) -> int:
        """Mark all other documents with the same source_ref as deleted (superseded)."""
        now = utc_now()
        with self._pool.checkout() as connection:
            cursor = connection.execute(
                "update document_status set deleted_at = ?, updated_at = ? "
                "where source_ref = ? and document_id != ? and deleted_at is null",
                (now, now, source_ref, except_document_id),
            )
            supersede_knowledge_source(
                connection,
                source_ref=source_ref,
                except_document_id=except_document_id,
                superseded_at=now,
            )
            connection.commit()
            return cursor.rowcount

    def list_document_status(self, limit: int = 20) -> list[dict[str, object]]:
        with self._pool.checkout() as connection:
            rows = connection.execute(
                "select * from document_status order by updated_at desc limit ?",
                (limit,),
            ).fetchall()
        return [_document_status_row(row) for row in rows]

    def _persist_specialized(self, connection: sqlite3.Connection, record: MIRLRecord) -> None:
        attrs = record.attrs
        if record.kind == RecordKind.RAW:
            connection.execute(
                "insert or replace into raw_docs (id, ns, scope, source_ref, content, created_at) values (?, ?, ?, ?, ?, ?)",
                (record.id, record.ns, record.scope, attrs.get("source_ref"), attrs.get("content", ""), record.created_at),
            )
        elif record.kind == RecordKind.SPAN:
            connection.execute(
                "insert or replace into raw_spans (id, raw_id, start, end, span_text, created_at) values (?, ?, ?, ?, ?, ?)",
                (record.id, attrs.get("raw_id"), int(attrs.get("start", 0)), int(attrs.get("end", 0)), attrs.get("text"), record.created_at),
            )
        elif record.kind == RecordKind.SYM:
            connection.execute(
                "insert or replace into symbol_table (id, ns, symbol, expansion, payload_json) values (?, ?, ?, ?, ?)",
                (record.id, record.ns, attrs.get("symbol"), attrs.get("expansion"), json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"))),
            )
        elif record.kind == RecordKind.PACK:
            connection.execute(
                "insert or replace into pack_store (id, mode, lens, refs_json, payload_json, created_at) values (?, ?, ?, ?, ?, ?)",
                (record.id, attrs.get("mode"), attrs.get("lens", "general"), json.dumps(attrs.get("refs", [])), json.dumps(attrs.get("payload", {}), sort_keys=True, separators=(",", ":")), record.created_at),
            )
        elif record.kind == RecordKind.PROV:
            connection.execute(
                "insert or replace into prov_log (id, entity, activity, agent, payload_json) values (?, ?, ?, ?, ?)",
                (record.id, attrs.get("entity"), attrs.get("activity"), attrs.get("agent"), json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"))),
            )

    def _persist_edges(
        self,
        connection: sqlite3.Connection,
        record: MIRLRecord,
        old_clm_subject: str | None = None,
    ) -> None:
        # Remove existing edges for this record so that re-persists with
        # changed edge sets do not leave stale edges behind (H2 integrity fix).
        connection.execute("delete from ir_edges where src_id = ?", (record.id,))
        # Also remove edges keyed by the CLM subject when it differs from record.id.
        if record.kind == RecordKind.CLM:
            subject = record.attrs.get("subject")
            if subject is not None:
                connection.execute("delete from ir_edges where src_id = ?", (str(subject),))
            # Clean up edges from the old subject if it changed.
            if old_clm_subject is not None and old_clm_subject != subject:
                connection.execute("delete from ir_edges where src_id = ?", (str(old_clm_subject),))
        attrs = record.attrs
        edges: list[tuple[str, str, str]] = []
        if record.kind == RecordKind.REL:
            src = attrs.get("src")
            dst = attrs.get("dst")
            if src is not None and dst is not None:
                edges.append((str(src), str(attrs.get("predicate")), str(dst)))
        elif record.kind == RecordKind.CLM:
            subject = attrs.get("subject")
            obj = attrs.get("object")
            if subject is not None and isinstance(obj, str) and ":" in obj:
                edges.append((str(subject), str(attrs.get("predicate")), obj))
        for prov in record.prov:
            edges.append((record.id, "prov", prov))
        for evidence in record.evidence:
            edges.append((record.id, "evidence", evidence))
        for src_id, edge_type, dst_id in edges:
            connection.execute("insert or ignore into ir_edges (src_id, edge_type, dst_id) values (?, ?, ?)", (src_id, edge_type, dst_id))

    def load_ir(
        self,
        ids: list[str] | None = None,
        ns: str | None = None,
        scope: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> IRBatch:
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative")
        if offset < 0:
            raise ValueError("offset must be non-negative")
        query = "select payload_json from ir_records where 1=1"
        params: list[object] = []
        if ids:
            query += f" and id in ({','.join('?' for _ in ids)})"
            params.extend(ids)
        if ns:
            query += " and ns = ?"
            params.append(ns)
        if scope:
            query += " and scope = ?"
            params.append(scope)
        if limit is not None:
            query += " order by id limit ? offset ?"
            params.extend([limit, offset])
        elif offset:
            query += " order by id limit -1 offset ?"
            params.append(offset)
        with self._pool.checkout() as connection:
            rows = connection.execute(query, params).fetchall()
        records = [MIRLRecord.from_dict(json.loads(row["payload_json"])) for row in rows]
        if ids:
            by_id = {record.id: record for record in records}
            records = [by_id[record_id] for record_id in ids if record_id in by_id]
        return IRBatch(records)

    @retry_db_operation()
    def delete_ir(self, ids: list[str], include_vectors: bool = True) -> None:
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        with self._pool.checkout() as connection:
            remove_knowledge_records(connection, ids)
            connection.execute(f"delete from raw_docs where id in ({placeholders})", ids)
            connection.execute(f"delete from raw_spans where id in ({placeholders})", ids)
            connection.execute(f"delete from symbol_table where id in ({placeholders})", ids)
            connection.execute(f"delete from pack_store where id in ({placeholders})", ids)
            connection.execute(f"delete from prov_log where id in ({placeholders})", ids)
            connection.execute(f"delete from ir_edges where src_id in ({placeholders}) or dst_id in ({placeholders})", ids + ids)
            connection.execute(f"delete from projection_index where record_id in ({placeholders})", ids)
            if include_vectors:
                connection.execute(f"delete from vector_index where record_id in ({placeholders})", ids)
            connection.execute(f"delete from ir_records where id in ({placeholders})", ids)
            connection.commit()

    def knowledge_graph(
        self,
        *,
        query: str | None = None,
        root_id: str | None = None,
        namespace: str | None = None,
        scope: str | None = None,
        agent_id: str | None = None,
        kinds: list[str] | None = None,
        at: str | None = None,
        include_history: bool = False,
        limit: int = 300,
        hops: int = 2,
    ) -> dict[str, object]:
        with self._pool.checkout() as connection:
            return query_knowledge_graph(
                connection,
                query=query,
                root_id=root_id,
                namespace=namespace,
                scope=scope,
                agent_id=agent_id,
                kinds=kinds,
                at=at,
                include_history=include_history,
                limit=limit,
                hops=hops,
            )

    def knowledge_node(
        self,
        node_id: str,
        *,
        include_history: bool = True,
        at: str | None = None,
    ) -> dict[str, object]:
        with self._pool.checkout() as connection:
            return knowledge_node_detail(
                connection,
                node_id,
                include_history=include_history,
                at=at,
            )

    def identity_merges(
        self,
        *,
        ns: str | None = None,
        scope: str | None = None,
        statuses: list[str] | None = None,
    ) -> list[dict[str, object]]:
        """Read the identity-merge ledger (graph maturity G2)."""
        with self._pool.checkout() as connection:
            return list_identity_merges(
                connection, ns=ns, scope=scope, statuses=statuses
            )

    def identity_merge_audit(self, node_id: str) -> list[dict[str, object]]:
        """Every merge touching ``node_id`` (any status) plus its evidence."""
        with self._pool.checkout() as connection:
            return identity_merge_audit_detail(connection, node_id)

    @retry_db_operation()
    def generate_identity_merge_candidates(
        self,
        *,
        ns: str | None = None,
        scope: str | None = None,
        max_candidates: int = 500,
    ) -> dict[str, object]:
        """Auto-propose merge candidates; proposals only, never accepted."""
        with self._pool.checkout() as connection:
            summary = generate_identity_merge_candidates_op(
                connection, ns=ns, scope=scope, max_candidates=max_candidates
            )
            connection.commit()
            return summary

    @retry_db_operation()
    def accept_identity_merge(self, merge_id: str) -> str:
        """Operator action: promote a proposed merge to accepted."""
        with self._pool.checkout() as connection:
            status = accept_identity_merge_op(connection, merge_id)
            connection.commit()
            return status

    @retry_db_operation()
    def split_identity_merge(
        self, merge_id: str, *, reason: str | None = None
    ) -> None:
        """Operator action: reversibly undo a merge, retaining evidence."""
        with self._pool.checkout() as connection:
            split_identity_merge_op(connection, merge_id, reason=reason)
            connection.commit()

    def assertable_record_ids(
        self,
        record_ids: list[str],
        *,
        at: str | None = None,
        namespace: str | None = None,
        scope: str | None = None,
    ) -> set[str]:
        """Return the requested records that may enter asserted answer context."""

        # Imported lazily so the answer-context trust boundary does not add a
        # new module-import dependency to storage initialization.
        from .knowledge_graph import assertable_record_ids

        with self._pool.checkout() as connection:
            return assertable_record_ids(
                connection,
                record_ids,
                at=at,
                namespace=namespace,
                scope=scope,
            )

    def read_pack(self, pack_id: str) -> Pack:
        batch = self.load_ir(ids=[pack_id])
        if not batch.records:
            raise KeyError(pack_id)
        record = batch.records[0]
        if record.kind != RecordKind.PACK:
            raise KeyError(pack_id)
        return Pack.from_record(record)

    def trace(self, root_id: str) -> TraceGraph:
        with self._pool.checkout() as connection:
            root = _load_record_by_id(connection, root_id)
            if root is None:
                raise KeyError(root_id)
            records = {root_id: root}
            seen = {root_id}
            order = [root_id]
            queue = [root_id]
            edges: list[dict[str, str]] = []
            edge_keys: set[tuple[str, str, str]] = set()
            while queue:
                current = queue.pop(0)
                record = records[current]
                refs = [(current, "trace", dst, dst) for dst in _trace_refs(record)]
                edge_rows = connection.execute(
                    "select src_id, predicate, dst_id from knowledge_edges "
                    "where (src_id = ? or dst_id = ?) and expired_at is null "
                    "and status not in ('contradicted','superseded','deprecated','deleted_soft') "
                    "order by id",
                    (current, current),
                ).fetchall()
                for row in edge_rows:
                    neighbor = row["dst_id"] if row["src_id"] == current else row["src_id"]
                    refs.append((row["src_id"], row["predicate"], row["dst_id"], neighbor))
                for src, edge_type, dst, neighbor in dict.fromkeys(refs):
                    target = _load_record_by_id(connection, neighbor)
                    if target is None and neighbor not in record.prov and neighbor not in record.evidence:
                        continue
                    edge_key = (src, edge_type, dst)
                    if edge_key not in edge_keys:
                        edge_keys.add(edge_key)
                        edges.append({"src": src, "type": edge_type, "dst": dst})
                    if target is not None and neighbor not in seen:
                        records[neighbor] = target
                        seen.add(neighbor)
                        order.append(neighbor)
                        queue.append(neighbor)
        return TraceGraph(root_id=root_id, nodes=[records[node_id] for node_id in order], edges=edges)

    def write_machine_artifact(
        self,
        source_type: str,
        source_id: str,
        artifact: dict[str, object],
        roundtrip_ok: bool,
        metadata: dict[str, object] | None = None,
    ) -> str:
        artifact_id = f"mx:{uuid4().hex[:12]}"
        machine_text = str(artifact.get("machine_text", "") or "")
        machine_bytes = machine_text.encode("utf-8") if machine_text else b""
        with self._pool.checkout() as connection:
            connection.execute(
                """
                insert or replace into machine_artifacts
                (artifact_id, source_type, source_id, codec, transform_chain, tokenizer, sha256_raw, sha256_machine,
                 bytes_raw, bytes_machine, tokens_raw, tokens_machine, token_savings_ratio, roundtrip_ok,
                 metadata_json, artifact_json, machine_text, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    artifact_id,
                    source_type,
                    source_id,
                    artifact.get("codec"),
                    artifact.get("transform"),
                    artifact.get("token_estimator"),
                    artifact.get("sha256"),
                    hashlib.sha256(machine_bytes).hexdigest() if machine_bytes else None,
                    artifact.get("original_bytes"),
                    artifact.get("machine_bytes"),
                    artifact.get("original_tokens"),
                    artifact.get("machine_tokens"),
                    artifact.get("token_savings_ratio"),
                    1 if roundtrip_ok else 0,
                    json.dumps(metadata or {}, sort_keys=True, separators=(",", ":")),
                    json.dumps(artifact, sort_keys=True, separators=(",", ":")),
                    machine_text or None,
                    utc_now(),
                ),
            )
            connection.commit()
        return artifact_id

    def read_machine_artifact(self, artifact_id: str) -> dict[str, object]:
        with self._pool.checkout() as connection:
            row = connection.execute("select * from machine_artifacts where artifact_id = ?", (artifact_id,)).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        artifact = json.loads(row["artifact_json"])
        return {
            "artifact_id": row["artifact_id"],
            "source_type": row["source_type"],
            "source_id": row["source_id"],
            "codec": row["codec"],
            "transform_chain": row["transform_chain"],
            "tokenizer": row["tokenizer"],
            "sha256_raw": row["sha256_raw"],
            "sha256_machine": row["sha256_machine"],
            "bytes_raw": row["bytes_raw"],
            "bytes_machine": row["bytes_machine"],
            "tokens_raw": row["tokens_raw"],
            "tokens_machine": row["tokens_machine"],
            "token_savings_ratio": row["token_savings_ratio"],
            "roundtrip_ok": bool(row["roundtrip_ok"]),
            "metadata": json.loads(row["metadata_json"]),
            "artifact": artifact,
            "machine_text": row["machine_text"],
            "created_at": row["created_at"],
        }

    def write_surface_artifact(
        self,
        artifact: dict[str, object],
        *,
        source_ref: str | None = None,
        source_sha256: str | None = None,
        verification_status: str = "PASS",
        import_status: str = "not_imported",
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        now = utc_now()
        artifact_path = str(Path(str(artifact.get("path", ""))).expanduser().resolve())
        surface_sha256 = str(artifact.get("surface_sha256") or _file_sha256(artifact_path))
        surface_id = f"hs:{surface_sha256[:16]}"
        payload_format = str(artifact.get("payload_format", "bytes"))
        query_status = "direct_queryable" if payload_format in {"MIRL", "SEAM-RC/1"} else "verify_only"
        merged_metadata = dict(metadata or {})
        merged_metadata["artifact"] = dict(artifact)
        with self._pool.checkout() as connection:
            existing = connection.execute("select created_at from surface_artifacts where surface_id = ?", (surface_id,)).fetchone()
            created_at = existing["created_at"] if existing else now
            connection.execute(
                """
                insert or replace into surface_artifacts
                (surface_id, artifact_path, mode, payload_format, source_ref, source_sha256,
                 payload_sha256, surface_sha256, payload_bytes, surface_bytes, width, height,
                 capacity_bytes, verification_status, query_status, import_status,
                 metadata_json, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    surface_id,
                    artifact_path,
                    str(artifact.get("mode", "")),
                    payload_format,
                    source_ref if source_ref is not None else str(artifact.get("source_ref", "")),
                    source_sha256,
                    str(artifact.get("payload_sha256", "")),
                    surface_sha256,
                    int(artifact.get("payload_bytes", 0)),
                    int(artifact.get("surface_bytes", 0)),
                    int(artifact.get("width", 0)),
                    int(artifact.get("height", 0)),
                    int(artifact.get("capacity_bytes", 0)),
                    verification_status,
                    query_status,
                    import_status,
                    json.dumps(merged_metadata, sort_keys=True, separators=(",", ":")),
                    created_at,
                    now,
                ),
            )
            connection.commit()
        return self.read_surface_artifact(surface_id)

    def read_surface_artifact(self, surface_ref: str) -> dict[str, object]:
        with self._pool.checkout() as connection:
            row = connection.execute(
                """
                select * from surface_artifacts
                where surface_id = ? or artifact_path = ?
                """,
                (surface_ref, str(Path(surface_ref).expanduser().resolve())),
            ).fetchone()
        if row is None:
            raise KeyError(surface_ref)
        return _surface_artifact_row(row)

    def list_surface_artifacts(self, limit: int = 20) -> list[dict[str, object]]:
        with self._pool.checkout() as connection:
            rows = connection.execute(
                "select * from surface_artifacts order by updated_at desc limit ?",
                (limit,),
            ).fetchall()
        return [_surface_artifact_row(row) for row in rows]

    def update_surface_import_status(self, surface_ref: str, import_status: str) -> dict[str, object]:
        current = self.read_surface_artifact(surface_ref)
        with self._pool.checkout() as connection:
            connection.execute(
                "update surface_artifacts set import_status = ?, updated_at = ? where surface_id = ?",
                (import_status, utc_now(), current["surface_id"]),
            )
            connection.commit()
        return self.read_surface_artifact(str(current["surface_id"]))

    def update_surface_artifact_state(
        self,
        surface_ref: str,
        *,
        artifact_path: str | None = None,
        verification_status: str | None = None,
        query_status: str | None = None,
        import_status: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> dict[str, object]:
        current = self.read_surface_artifact(surface_ref)
        merged_metadata = dict(current["metadata"])
        if metadata:
            merged_metadata.update(metadata)
        next_artifact_path = artifact_path or str(current["artifact_path"])
        with self._pool.checkout() as connection:
            connection.execute(
                """
                update surface_artifacts
                set artifact_path = ?,
                    verification_status = ?,
                    query_status = ?,
                    import_status = ?,
                    metadata_json = ?,
                    updated_at = ?
                where surface_id = ?
                """,
                (
                    str(Path(next_artifact_path).expanduser().resolve()),
                    verification_status or str(current["verification_status"]),
                    query_status or str(current["query_status"]),
                    import_status or str(current["import_status"]),
                    json.dumps(merged_metadata, sort_keys=True, separators=(",", ":")),
                    utc_now(),
                    str(current["surface_id"]),
                ),
            )
            connection.commit()
        return self.read_surface_artifact(str(current["surface_id"]))

    def write_projection(
        self,
        record_id: str,
        projection_kind: str,
        projection_text: str,
        tokenizer: str | None = None,
        token_count: int | None = None,
        metadata: dict[str, object] | None = None,
    ) -> str:
        projection_id = f"px:{uuid4().hex[:12]}"
        with self._pool.checkout() as connection:
            connection.execute("delete from projection_index where record_id = ? and projection_kind = ?", (record_id, projection_kind))
            connection.execute(
                """
                insert into projection_index
                (projection_id, record_id, projection_kind, projection_text, tokenizer, token_count, metadata_json, updated_at)
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    projection_id,
                    record_id,
                    projection_kind,
                    projection_text,
                    tokenizer,
                    token_count,
                    json.dumps(metadata or {}, sort_keys=True, separators=(",", ":")),
                    utc_now(),
                ),
            )
            connection.commit()
        return projection_id

    def read_projections(self, record_id: str | None = None, projection_kind: str | None = None) -> list[dict[str, object]]:
        query = "select * from projection_index where 1=1"
        params: list[object] = []
        if record_id is not None:
            query += " and record_id = ?"
            params.append(record_id)
        if projection_kind is not None:
            query += " and projection_kind = ?"
            params.append(projection_kind)
        query += " order by updated_at desc"
        with self._pool.checkout() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            {
                "projection_id": row["projection_id"],
                "record_id": row["record_id"],
                "projection_kind": row["projection_kind"],
                "projection_text": row["projection_text"],
                "tokenizer": row["tokenizer"],
                "token_count": row["token_count"],
                "metadata": json.loads(row["metadata_json"]),
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def write_benchmark_run(self, report: dict[str, object]) -> str:
        manifest = dict(report.get("manifest", {}))
        summary = dict(report.get("summary", {}))
        run_id = str(manifest.get("run_id") or f"bench:{uuid4().hex[:12]}")
        executed_suites = list(manifest.get("executed_suites", []))
        with self._pool.checkout() as connection:
            connection.execute(
                """
                insert or replace into benchmark_runs
                (run_id, requested_suite, executed_suites, status, bundle_hash, manifest_json, summary_json, report_json, created_at)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    manifest.get("requested_suite"),
                    json.dumps(executed_suites),
                    summary.get("status", "FAIL"),
                    report.get("bundle_hash"),
                    json.dumps(manifest, sort_keys=True, separators=(",", ":")),
                    json.dumps(summary, sort_keys=True, separators=(",", ":")),
                    json.dumps(report, sort_keys=True, separators=(",", ":")),
                    manifest.get("created_at") or utc_now(),
                ),
            )
            connection.execute("delete from benchmark_cases where run_id = ?", (run_id,))
            for family_name, family in dict(report.get("families", {})).items():
                for case in family.get("cases", []):
                    connection.execute(
                        """
                        insert into benchmark_cases
                        (run_id, case_id, family, status, case_hash, metrics_json, trace_json, case_json)
                        values (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            f"{family_name}:{case.get('case_id')}",
                            family_name,
                            case.get("status"),
                            case.get("case_hash"),
                            json.dumps(case.get("metrics", {}), sort_keys=True, separators=(",", ":")),
                            json.dumps(case.get("trace", {}), sort_keys=True, separators=(",", ":")),
                            json.dumps(case, sort_keys=True, separators=(",", ":")),
                        ),
                    )
            connection.commit()
        return run_id

    def read_benchmark_run(self, run_id: str) -> dict[str, object]:
        with self._pool.checkout() as connection:
            row = connection.execute("select report_json from benchmark_runs where run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"Benchmark run not found: {run_id}")
        return json.loads(row["report_json"])

    def list_benchmark_runs(self, limit: int = 10) -> list[dict[str, object]]:
        with self._pool.checkout() as connection:
            rows = connection.execute(
                "select run_id, requested_suite, executed_suites, status, bundle_hash, created_at from benchmark_runs order by created_at desc limit ?",
                (limit,),
            ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "requested_suite": row["requested_suite"],
                "executed_suites": json.loads(row["executed_suites"]),
                "status": row["status"],
                "bundle_hash": row["bundle_hash"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # Structured live workspace (append-only operational telemetry)
    # ------------------------------------------------------------------

    @retry_db_operation()
    def create_workspace_run(
        self,
        *,
        run_id: str | None = None,
        ns: str = "local.chat",
        scope: str = "thread",
        agent_id: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        metadata: dict[str, object] | None = None,
        created_at: str | None = None,
    ) -> dict[str, object]:
        with self._pool.checkout() as connection:
            run = create_workspace_run_row(
                connection,
                run_id=run_id,
                ns=ns,
                scope=scope,
                agent_id=agent_id,
                model=model,
                provider=provider,
                metadata=metadata,
                created_at=created_at,
            )
            connection.commit()
        return run.to_dict()

    # ------------------------------------------------------------------
    # Public reasoning graph (append-only, non-canonical artifacts)
    # ------------------------------------------------------------------

    @retry_db_operation()
    def add_reasoning_node(
        self,
        *,
        run_id: str,
        kind: str,
        summary: str,
        confidence: float | None = None,
        agent_id: str | None = None,
        operation: str | None = None,
        knowledge_refs: Iterable[str] = (),
        evidence_record_ids: Iterable[str] = (),
        node_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, object]:
        with self._pool.checkout() as connection:
            node = add_reasoning_node_row(
                connection,
                run_id=run_id,
                kind=kind,
                summary=summary,
                confidence=confidence,
                agent_id=agent_id,
                operation=operation,
                knowledge_refs=knowledge_refs,
                evidence_record_ids=evidence_record_ids,
                node_id=node_id,
                created_at=created_at,
            )
            connection.commit()
        return node

    @retry_db_operation()
    def create_reasoning_run(
        self,
        *,
        objective: str,
        ns: str = "local.reasoning",
        scope: str = "thread",
        agent_id: str | None = None,
        model: str | None = None,
        provider: str | None = None,
    ) -> tuple[dict[str, object], dict[str, object]]:
        """Atomically create a workspace run and its objective node."""

        with self._pool.checkout() as connection:
            run = create_workspace_run_row(
                connection,
                ns=ns,
                scope=scope,
                agent_id=agent_id,
                model=model,
                provider=provider,
            )
            objective_node = add_reasoning_node_row(
                connection,
                run_id=run.run_id,
                kind="objective",
                summary=objective,
                agent_id=agent_id,
            )
            connection.commit()
        return run.to_dict(), objective_node

    @retry_db_operation()
    def add_reasoning_edge(
        self,
        *,
        run_id: str,
        src_node_id: str,
        relation: str,
        dst_node_id: str,
        agent_id: str | None = None,
        edge_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, object]:
        with self._pool.checkout() as connection:
            edge = add_reasoning_edge_row(
                connection,
                run_id=run_id,
                src_node_id=src_node_id,
                relation=relation,
                dst_node_id=dst_node_id,
                agent_id=agent_id,
                edge_id=edge_id,
                created_at=created_at,
            )
            connection.commit()
        return edge

    @retry_db_operation()
    def transition_reasoning_node(
        self,
        *,
        node_id: str,
        status: str,
        reason: str | None = None,
        actor: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, object]:
        with self._pool.checkout() as connection:
            state = transition_reasoning_node(
                connection,
                node_id=node_id,
                status=status,
                reason=reason,
                actor=actor,
                created_at=created_at,
            )
            connection.commit()
        return state

    def reasoning_node(
        self, node_id: str, *, include_history: bool = True
    ) -> dict[str, object]:
        with self._pool.checkout() as connection:
            return get_reasoning_node_row(
                connection, node_id, include_history=include_history
            )

    def reasoning_graph(self, run_id: str) -> dict[str, object]:
        with self._pool.checkout() as connection:
            return reasoning_graph(connection, run_id)

    @retry_db_operation()
    def record_reasoning_retrieval(
        self,
        *,
        run_id: str,
        query: str,
        normalized_query: str,
        filter_ids: Iterable[str],
        filter_kinds: Iterable[str],
        filter_predicate: str | None,
        filter_subject: str | None,
        filter_object_text: str | None,
        leg_limits: dict[str, int],
        mode: str,
        intent: str,
        budget: int,
        graph_hops: int,
        semantic_graph_seeding: bool,
        semantic_backend: str,
        semantic_adapter: str,
        embedding_model: str,
        embedding_dimension: int,
        embedding_revision: str | None,
        candidates: tuple[ReasoningRetrievalCandidate, ...],
        total_candidates: int,
        candidates_truncated: bool,
        candidate_set_sha256: str,
        leg_latency_ms: dict[str, float],
        total_latency_ms: float,
        policy: str,
        graph_at: str | None = None,
        graph_include_history: bool = False,
        agent_id: str | None = None,
    ) -> dict[str, object]:
        with self._pool.checkout() as connection:
            retrieval = record_reasoning_retrieval(
                connection,
                run_id=run_id,
                query=query,
                normalized_query=normalized_query,
                filter_ids=filter_ids,
                filter_kinds=filter_kinds,
                filter_predicate=filter_predicate,
                filter_subject=filter_subject,
                filter_object_text=filter_object_text,
                leg_limits=leg_limits,
                mode=mode,
                intent=intent,
                budget=budget,
                graph_hops=graph_hops,
                semantic_graph_seeding=semantic_graph_seeding,
                semantic_backend=semantic_backend,
                semantic_adapter=semantic_adapter,
                embedding_model=embedding_model,
                embedding_dimension=embedding_dimension,
                embedding_revision=embedding_revision,
                candidates=candidates,
                total_candidates=total_candidates,
                candidates_truncated=candidates_truncated,
                candidate_set_sha256=candidate_set_sha256,
                leg_latency_ms=leg_latency_ms,
                total_latency_ms=total_latency_ms,
                policy=policy,
                graph_at=graph_at,
                graph_include_history=graph_include_history,
                agent_id=agent_id,
            )
            connection.commit()
        return retrieval

    def reasoning_retrieval(self, retrieval_id: str) -> dict[str, object]:
        with self._pool.checkout() as connection:
            return get_reasoning_retrieval_row(connection, retrieval_id)

    def reasoning_retrievals(
        self,
        *,
        run_id: str,
        limit: int = 100,
        after: str | None = None,
        include_candidates: bool = False,
    ) -> list[dict[str, object]]:
        with self._pool.checkout() as connection:
            return list_reasoning_retrievals(
                connection,
                run_id=run_id,
                limit=limit,
                after=after,
                include_candidates=include_candidates,
            )

    @retry_db_operation()
    def record_reasoning_verification(
        self,
        *,
        run_id: str,
        subject_node_id: str,
        check_kind: str,
        check_ref: str,
        verdict: str,
        summary: str,
        result: str | None = None,
        exit_code: int | None = None,
        duration_ms: float | None = None,
        knowledge_refs: Iterable[str] = (),
        evidence_record_ids: Iterable[str] = (),
        agent_id: str | None = None,
        retry_of: str | None = None,
    ) -> dict[str, object]:
        with self._pool.checkout() as connection:
            verification = record_reasoning_verification(
                connection,
                run_id=run_id,
                subject_node_id=subject_node_id,
                check_kind=check_kind,
                check_ref=check_ref,
                verdict=verdict,
                summary=summary,
                result=result,
                exit_code=exit_code,
                duration_ms=duration_ms,
                knowledge_refs=knowledge_refs,
                evidence_record_ids=evidence_record_ids,
                agent_id=agent_id,
                retry_of=retry_of,
            )
            connection.commit()
        return verification

    def reasoning_verification(self, verification_id: str) -> dict[str, object]:
        with self._pool.checkout() as connection:
            return get_reasoning_verification(connection, verification_id)

    def reasoning_verifications(
        self,
        *,
        run_id: str,
        limit: int = 100,
        after: str | None = None,
    ) -> list[dict[str, object]]:
        with self._pool.checkout() as connection:
            return list_reasoning_verifications(
                connection, run_id=run_id, limit=limit, after=after
            )

    @retry_db_operation()
    def finalize_verified_reasoning_outcome(
        self,
        *,
        run_id: str,
        summary: str,
        verification_ids: Iterable[str],
        confidence: float | None = None,
        knowledge_refs: Iterable[str] = (),
        evidence_record_ids: Iterable[str] = (),
        supporting_node_ids: Iterable[str] = (),
        agent_id: str | None = None,
    ) -> dict[str, object]:
        with self._pool.checkout() as connection:
            outcome = finalize_verified_reasoning_outcome(
                connection,
                run_id=run_id,
                summary=summary,
                verification_ids=verification_ids,
                confidence=confidence,
                knowledge_refs=knowledge_refs,
                evidence_record_ids=evidence_record_ids,
                supporting_node_ids=supporting_node_ids,
                agent_id=agent_id,
            )
            connection.commit()
        return outcome

    @retry_db_operation()
    def append_workspace_event(
        self,
        *,
        run_id: str,
        event_type: str,
        payload: dict[str, object] | None = None,
        created_at: str | None = None,
        agent_id: str | None = None,
    ) -> dict[str, object]:
        with self._pool.checkout() as connection:
            event = append_workspace_event_row(
                connection,
                run_id=run_id,
                event_type=event_type,
                payload=payload,
                created_at=created_at,
                agent_id=agent_id,
            )
            connection.commit()
        return event.to_dict()

    def iter_workspace_events(
        self,
        *,
        run_id: str | None = None,
        after: int = 0,
        limit: int = 500,
        ns: str | None = None,
        scope: str | None = None,
    ) -> list[dict[str, object]]:
        clauses = ["event_id > ?"]
        params: list[object] = [max(0, int(after))]
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        if ns is not None:
            clauses.append("ns = ?")
            params.append(ns)
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        params.append(max(1, min(int(limit), 2_000)))
        with self._pool.checkout() as connection:
            rows = connection.execute(
                f"select * from workspace_event where {' and '.join(clauses)} order by event_id limit ?",
                tuple(params),
            ).fetchall()
        return [workspace_event_from_row(row).to_dict() for row in rows]

    def get_workspace_run(
        self,
        run_id: str,
        *,
        include_events: bool = True,
        after: int = 0,
        limit: int = 2_000,
    ) -> dict[str, object]:
        with self._pool.checkout() as connection:
            row = connection.execute(
                "select * from workspace_run where run_id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"workspace run not found: {run_id}")
            run = workspace_run_from_row(row)
            all_event_rows = connection.execute(
                "select * from workspace_event where run_id = ? order by seq",
                (run_id,),
            ).fetchall()
        all_events = [workspace_event_from_row(event_row) for event_row in all_event_rows]
        result: dict[str, object] = {"run": run.to_dict(status=run_status(all_events))}
        if include_events:
            selected = [event for event in all_events if event.event_id > max(0, int(after))]
            result["events"] = [event.to_dict() for event in selected[: max(1, min(int(limit), 2_000))]]
        return result

    def list_workspace_runs(
        self,
        *,
        ns: str | None = None,
        scope: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        clauses: list[str] = []
        params: list[object] = []
        if ns is not None:
            clauses.append("r.ns = ?")
            params.append(ns)
        if scope is not None:
            clauses.append("r.scope = ?")
            params.append(scope)
        where = f"where {' and '.join(clauses)}" if clauses else ""
        params.append(max(1, min(int(limit), 500)))
        with self._pool.checkout() as connection:
            rows = connection.execute(
                f"""
                select r.*,
                    (select e.event_type from workspace_event e
                     where e.run_id = r.run_id and e.event_type in ('completion', 'failure')
                     order by e.seq desc limit 1) as terminal_type
                from workspace_run r {where}
                order by r.created_at desc, r.run_id desc limit ?
                """,
                tuple(params),
            ).fetchall()
        output: list[dict[str, object]] = []
        for row in rows:
            status = "running"
            if row["terminal_type"] == "completion":
                status = "completed"
            elif row["terminal_type"] == "failure":
                status = "failed"
            output.append(workspace_run_from_row(row).to_dict(status=status))
        return output

    @retry_db_operation()
    def write_retrieval_event(
        self,
        *,
        run_id: str,
        query: str,
        candidate_ids: list[str],
        source_kind: str,
        ts: str | None = None,
        scope: str | None = None,
        ranks: list[int] | None = None,
        scores: list[float] | None = None,
        reasons: list[str] | None = None,
        context_hash: str | None = None,
        gold_answer: str | None = None,
        gold_hit_ids: list[str] | None = None,
        context_recall: float | None = None,
        judge_score: float | None = None,
        answer: str | None = None,
        source_ref: str | None = None,
        stale_source: bool = False,
        extra: dict[str, object] | None = None,
    ) -> int:
        """Append a retrieval-outcome event (H2 substrate). Returns new event_id.

        Append-only by contract: there is no update/delete API. Callers must
        not mutate prior events. Stale-source flagging is required for
        backfill from pre-fix bundles; do not flip the flag after the fact.
        """
        if not run_id:
            raise ValueError("run_id is required")
        if not query:
            raise ValueError("query is required")
        if not source_kind:
            raise ValueError("source_kind is required")
        if ranks is not None and len(ranks) != len(candidate_ids):
            raise ValueError("ranks must align with candidate_ids")
        if scores is not None and len(scores) != len(candidate_ids):
            raise ValueError("scores must align with candidate_ids")
        with self._pool.checkout() as connection:
            cursor = connection.execute(
                """
                insert into retrieval_event (
                    ts, run_id, scope, query,
                    candidate_ids_json, ranks_json, scores_json, reasons_json,
                    context_hash, gold_answer, gold_hit_ids_json,
                    context_recall, judge_score, answer,
                    source_kind, source_ref, stale_source, schema_version, extra_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ts or utc_now(),
                    run_id,
                    scope,
                    query,
                    json.dumps(list(candidate_ids), separators=(",", ":")),
                    json.dumps(list(ranks), separators=(",", ":")) if ranks is not None else None,
                    json.dumps(list(scores), separators=(",", ":")) if scores is not None else None,
                    json.dumps(list(reasons), separators=(",", ":")) if reasons is not None else None,
                    context_hash,
                    gold_answer,
                    json.dumps(list(gold_hit_ids), separators=(",", ":")) if gold_hit_ids is not None else None,
                    context_recall,
                    judge_score,
                    answer,
                    source_kind,
                    source_ref,
                    1 if stale_source else 0,
                    1,
                    json.dumps(extra, sort_keys=True, separators=(",", ":")) if extra is not None else None,
                ),
            )
            event_id = cursor.lastrowid
            connection.commit()
        return int(event_id)

    def iter_retrieval_events(
        self,
        *,
        run_id: str | None = None,
        scope: str | None = None,
        include_stale: bool = True,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        """Read retrieval events. Newest first by event_id.

        Defaults include stale-flagged events; callers training rankers should
        pass include_stale=False explicitly.
        """
        clauses: list[str] = []
        params: list[object] = []
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        if not include_stale:
            clauses.append("stale_source = 0")
        where = (" where " + " and ".join(clauses)) if clauses else ""
        sql = f"select * from retrieval_event{where} order by event_id desc"
        if limit is not None:
            sql += " limit ?"
            params.append(int(limit))
        with self._pool.checkout() as connection:
            rows = connection.execute(sql, tuple(params)).fetchall()
        return [_retrieval_event_row(row) for row in rows]

    def count_retrieval_events(
        self,
        *,
        run_id: str | None = None,
        scope: str | None = None,
        include_stale: bool = True,
    ) -> int:
        clauses: list[str] = []
        params: list[object] = []
        if run_id is not None:
            clauses.append("run_id = ?")
            params.append(run_id)
        if scope is not None:
            clauses.append("scope = ?")
            params.append(scope)
        if not include_stale:
            clauses.append("stale_source = 0")
        where = (" where " + " and ".join(clauses)) if clauses else ""
        with self._pool.checkout() as connection:
            row = connection.execute(
                f"select count(*) from retrieval_event{where}", tuple(params)
            ).fetchone()
        return int(row[0])

    # ------------------------------------------------------------------
    # H2 slice 5: improvement_proposal + proposal_decision
    # ------------------------------------------------------------------
    # Append-only pair: improvement_proposal rows are written once and never
    # mutated; status transitions append rows to proposal_decision. Current
    # status = latest decision by ts/decision_id. SEAM never writes to
    # AGENTS.md / REPO_LEDGER.md / PROJECT_STATUS.md from this surface; the
    # gate is operator approval recorded here.

    @retry_db_operation()
    def write_improvement_proposal(
        self,
        *,
        kind: str,
        summary: str,
        rationale: str | None = None,
        evidence_event_ids: list[int] | None = None,
        evidence_case_ids: list[str] | None = None,
        proposed_change: dict[str, object] | None = None,
        holdout_violation: bool = False,
        created_at: str | None = None,
        extra: dict[str, object] | None = None,
    ) -> int:
        """Append a new improvement proposal. Also writes an initial
        ``proposal_decision`` row with status=pending so listing pending
        proposals is one query.

        Append-only: there is no update method. Status transitions go through
        ``record_proposal_decision``; the proposal body itself never changes.
        """
        if not kind:
            raise ValueError("kind is required")
        if not summary:
            raise ValueError("summary is required")
        with self._pool.checkout() as connection:
            cursor = connection.execute(
                """
                insert into improvement_proposal (
                    created_at, kind, summary, rationale,
                    evidence_event_ids_json, evidence_case_ids_json,
                    proposed_change_json, holdout_violation, schema_version, extra_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at or utc_now(),
                    kind,
                    summary,
                    rationale,
                    json.dumps(list(evidence_event_ids), separators=(",", ":")) if evidence_event_ids is not None else None,
                    json.dumps(list(evidence_case_ids), separators=(",", ":")) if evidence_case_ids is not None else None,
                    json.dumps(proposed_change, sort_keys=True, separators=(",", ":")) if proposed_change is not None else None,
                    1 if holdout_violation else 0,
                    1,
                    json.dumps(extra, sort_keys=True, separators=(",", ":")) if extra is not None else None,
                ),
            )
            proposal_id = int(cursor.lastrowid)
            connection.execute(
                """
                insert into proposal_decision (proposal_id, ts, status, reason, actor)
                values (?, ?, 'pending', NULL, NULL)
                """,
                (proposal_id, utc_now()),
            )
            connection.commit()
        return proposal_id

    @retry_db_operation()
    def record_proposal_decision(
        self,
        *,
        proposal_id: int,
        status: str,
        reason: str | None = None,
        actor: str | None = None,
        ts: str | None = None,
    ) -> int:
        """Append a status transition for an existing proposal. Returns the
        new decision_id.

        Append-only: prior decisions are preserved. A reverse decision
        (approve -> reject) leaves both rows in place so the audit trail
        captures the change of mind.
        """
        if status not in ("pending", "approved", "rejected", "superseded"):
            raise ValueError(f"unknown status {status!r}")
        with self._pool.checkout() as connection:
            row = connection.execute(
                "select 1 from improvement_proposal where proposal_id = ?",
                (proposal_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"proposal_id {proposal_id} does not exist")
            cursor = connection.execute(
                """
                insert into proposal_decision (proposal_id, ts, status, reason, actor)
                values (?, ?, ?, ?, ?)
                """,
                (proposal_id, ts or utc_now(), status, reason, actor),
            )
            decision_id = int(cursor.lastrowid)
            connection.commit()
        return decision_id

    def latest_proposal_status(self, proposal_id: int) -> dict[str, object] | None:
        """Return the most recent decision row for one proposal, or None if
        the proposal does not exist."""
        with self._pool.checkout() as connection:
            row = connection.execute(
                """
                select decision_id, proposal_id, ts, status, reason, actor
                from proposal_decision
                where proposal_id = ?
                order by decision_id desc
                limit 1
                """,
                (proposal_id,),
            ).fetchone()
        if row is None:
            return None
        return _proposal_decision_row(row)

    def iter_improvement_proposals(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        holdout_violation: bool | None = None,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        """List proposals newest-first with their latest decision joined."""
        clauses: list[str] = []
        params: list[object] = []
        if kind is not None:
            clauses.append("p.kind = ?")
            params.append(kind)
        if holdout_violation is not None:
            clauses.append("p.holdout_violation = ?")
            params.append(1 if holdout_violation else 0)
        where = (" where " + " and ".join(clauses)) if clauses else ""
        sql = f"""
            select p.*,
                   (select status from proposal_decision d
                    where d.proposal_id = p.proposal_id
                    order by decision_id desc limit 1) as latest_status,
                   (select reason from proposal_decision d
                    where d.proposal_id = p.proposal_id
                    order by decision_id desc limit 1) as latest_reason,
                   (select ts from proposal_decision d
                    where d.proposal_id = p.proposal_id
                    order by decision_id desc limit 1) as latest_status_ts
            from improvement_proposal p{where}
            order by p.proposal_id desc
        """
        if limit is not None:
            sql += " limit ?"
            params.append(int(limit))
        with self._pool.checkout() as connection:
            rows = connection.execute(sql, tuple(params)).fetchall()
        proposals = [_improvement_proposal_row(row) for row in rows]
        if status is not None:
            proposals = [p for p in proposals if p.get("latest_status") == status]
        return proposals

    def count_improvement_proposals(
        self,
        *,
        kind: str | None = None,
        status: str | None = None,
        holdout_violation: bool | None = None,
    ) -> int:
        return len(
            self.iter_improvement_proposals(
                kind=kind, status=status, holdout_violation=holdout_violation
            )
        )

    def iter_proposal_decisions(
        self, proposal_id: int
    ) -> list[dict[str, object]]:
        """All decision rows for one proposal, oldest first."""
        with self._pool.checkout() as connection:
            rows = connection.execute(
                """
                select decision_id, proposal_id, ts, status, reason, actor
                from proposal_decision
                where proposal_id = ?
                order by decision_id asc
                """,
                (proposal_id,),
            ).fetchall()
        return [_proposal_decision_row(row) for row in rows]

    def iter_retrieval_flag_state(self) -> list[dict[str, object]]:
        """Return the persisted applied-flag rows (one per lever).

        ``flag_value`` is JSON-decoded back to its scalar. An empty table is the
        canonical "no overrides" state: ``load_retrieval_flags`` then reproduces
        ``RetrievalFlags()`` exactly, preserving the locked retrieval baseline.
        """
        with self._pool.checkout() as connection:
            rows = connection.execute(
                """
                select flag_key, flag_value, source_proposal_id, applied_at
                from retrieval_flag_state
                order by flag_key asc
                """
            ).fetchall()
        return [
            {
                "flag_key": row["flag_key"],
                "flag_value": json.loads(row["flag_value"]),
                "source_proposal_id": row["source_proposal_id"],
                "applied_at": row["applied_at"],
            }
            for row in rows
        ]

    def upsert_retrieval_flag_state(
        self,
        *,
        flag_key: str,
        flag_value: object,
        source_proposal_id: int | None = None,
        applied_at: str | None = None,
    ) -> None:
        """Write/replace a single applied-flag row. ``flag_value`` is stored
        JSON-encoded so the scalar type round-trips through ``iter_*``."""
        if not flag_key:
            raise ValueError("flag_key is required")
        with self._pool.checkout() as connection:
            connection.execute(
                """
                insert or replace into retrieval_flag_state
                    (flag_key, flag_value, source_proposal_id, applied_at)
                values (?, ?, ?, ?)
                """,
                (
                    flag_key,
                    json.dumps(flag_value, separators=(",", ":")),
                    source_proposal_id,
                    applied_at or utc_now(),
                ),
            )
            connection.commit()

    def replace_retrieval_flag_state(
        self, desired: dict[str, tuple[object, int | None]]
    ) -> None:
        """Atomically reconcile applied-flag state to ``desired``.

        ``desired`` maps ``flag_key -> (flag_value, source_proposal_id)``. The
        whole table is rewritten in one transaction: rows absent from
        ``desired`` are removed, so ``replace_retrieval_flag_state({})`` clears
        all overrides. This makes the table a pure projection of the currently
        approved proposal set, so backing out an approval (re-running apply)
        removes the flag rather than ratcheting it on permanently.
        """
        with self._pool.checkout() as connection:
            connection.execute("delete from retrieval_flag_state")
            now = utc_now()
            for flag_key, (flag_value, source_proposal_id) in desired.items():
                connection.execute(
                    """
                    insert into retrieval_flag_state
                        (flag_key, flag_value, source_proposal_id, applied_at)
                    values (?, ?, ?, ?)
                    """,
                    (
                        flag_key,
                        json.dumps(flag_value, separators=(",", ":")),
                        source_proposal_id,
                        now,
                    ),
                )
            connection.commit()


def _retrieval_event_row(row: sqlite3.Row) -> dict[str, object]:
    def _maybe_json(value):
        if value is None:
            return None
        return json.loads(value)

    return {
        "event_id": int(row["event_id"]),
        "ts": row["ts"],
        "run_id": row["run_id"],
        "scope": row["scope"],
        "query": row["query"],
        "candidate_ids": _maybe_json(row["candidate_ids_json"]) or [],
        "ranks": _maybe_json(row["ranks_json"]),
        "scores": _maybe_json(row["scores_json"]),
        "reasons": _maybe_json(row["reasons_json"]),
        "context_hash": row["context_hash"],
        "gold_answer": row["gold_answer"],
        "gold_hit_ids": _maybe_json(row["gold_hit_ids_json"]),
        "context_recall": row["context_recall"],
        "judge_score": row["judge_score"],
        "answer": row["answer"],
        "source_kind": row["source_kind"],
        "source_ref": row["source_ref"],
        "stale_source": bool(row["stale_source"]),
        "schema_version": int(row["schema_version"]),
        "extra": _maybe_json(row["extra_json"]),
    }


def _improvement_proposal_row(row: sqlite3.Row) -> dict[str, object]:
    def _maybe_json(value):
        if value is None:
            return None
        return json.loads(value)

    return {
        "proposal_id": int(row["proposal_id"]),
        "created_at": row["created_at"],
        "kind": row["kind"],
        "summary": row["summary"],
        "rationale": row["rationale"],
        "evidence_event_ids": _maybe_json(row["evidence_event_ids_json"]),
        "evidence_case_ids": _maybe_json(row["evidence_case_ids_json"]),
        "proposed_change": _maybe_json(row["proposed_change_json"]),
        "holdout_violation": bool(row["holdout_violation"]),
        "schema_version": int(row["schema_version"]),
        "extra": _maybe_json(row["extra_json"]),
        "latest_status": row["latest_status"] if "latest_status" in row.keys() else None,
        "latest_reason": row["latest_reason"] if "latest_reason" in row.keys() else None,
        "latest_status_ts": row["latest_status_ts"] if "latest_status_ts" in row.keys() else None,
    }


def _proposal_decision_row(row: sqlite3.Row) -> dict[str, object]:
    return {
        "decision_id": int(row["decision_id"]),
        "proposal_id": int(row["proposal_id"]),
        "ts": row["ts"],
        "status": row["status"],
        "reason": row["reason"],
        "actor": row["actor"],
    }


def _document_status_row(row: sqlite3.Row) -> dict[str, object]:
    return {
        "document_id": row["document_id"],
        "ns": row["ns"],
        "scope": row["scope"],
        "source_ref": row["source_ref"],
        "source_hash": row["source_hash"],
        "byte_count": row["byte_count"],
        "chunk_count": row["chunk_count"],
        "extraction_status": row["extraction_status"],
        "indexed_status": row["indexed_status"],
        "deleted_at": row["deleted_at"],
        "metadata": json.loads(row["metadata_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _normalize_entity_label(label: str) -> str:
    """Lowercase + collapsed whitespace, the coreference dedup key."""
    return " ".join(label.lower().split())


def _load_record_by_id(connection: sqlite3.Connection, record_id: str) -> MIRLRecord | None:
    row = connection.execute("select payload_json from ir_records where id = ?", (record_id,)).fetchone()
    if row is None:
        return None
    return MIRLRecord.from_dict(json.loads(row["payload_json"]))


def _trace_refs(record: MIRLRecord) -> list[str]:
    refs = list(record.prov) + list(record.evidence)
    for key in ("src", "dst", "target", "raw_id", "subject"):
        value = record.attrs.get(key)
        if isinstance(value, str):
            refs.append(value)
    obj = record.attrs.get("object")
    if isinstance(obj, str):
        refs.append(obj)
    return refs


def _surface_artifact_row(row: sqlite3.Row) -> dict[str, object]:
    return {
        "surface_id": row["surface_id"],
        "artifact_path": row["artifact_path"],
        "mode": row["mode"],
        "payload_format": row["payload_format"],
        "source_ref": row["source_ref"],
        "source_sha256": row["source_sha256"],
        "payload_sha256": row["payload_sha256"],
        "surface_sha256": row["surface_sha256"],
        "payload_bytes": row["payload_bytes"],
        "surface_bytes": row["surface_bytes"],
        "width": row["width"],
        "height": row["height"],
        "capacity_bytes": row["capacity_bytes"],
        "verification_status": row["verification_status"],
        "query_status": row["query_status"],
        "import_status": row["import_status"],
        "metadata": json.loads(row["metadata_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
