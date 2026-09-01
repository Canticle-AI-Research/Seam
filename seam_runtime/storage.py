from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from .context_assembly import ContextCandidate
from .graph_products import (
    GRAPH_PRODUCT_SCHEMA_VERSION,
    GraphProductFact,
    init_graph_products,
)
from .graph_products import (
    graph_product_history as graph_product_history_rows,
)
from .graph_products import (
    read_graph_products as read_graph_product_rows,
)
from .graph_products import (
    rebuild_graph_products as rebuild_graph_product_rows,
)
from .identity_resolution import (
    accept_merge as accept_identity_merge_op,
)
from .identity_resolution import (
    apply_identity_merges,
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
from .improvement_experiments import (
    EXPERIMENT_CONTRACT_VERSION,
    EXPERIMENT_EVENT_KINDS,
    EXPERIMENT_METHOD,
    EXPERIMENT_SCHEMA_VERSION,
    TERMINAL_EXPERIMENT_EVENT_KINDS,
    experiment_definition_sha256,
    experiment_event_row,
    experiment_row,
    init_improvement_experiment_schema,
    validate_experiment_id,
    validate_sha256,
    validate_structured_payload,
)
from .improvement_experiments import (
    canonical_json as canonical_experiment_json,
)
from .improvement_experiments import (
    event_sha256 as improvement_event_sha256,
)
from .knowledge_graph import (
    ADMITTED_RELATION_PREDICATES,
    CURRENT_EXCLUDED_STATUSES,
    GRAPH_NODE_VECTOR_TEXT_VERSION,
    PROJECTION_VERSION,
    graph_stats,
    init_knowledge_graph,
    remove_orphan_node_vectors,
)
from .knowledge_graph import (
    node_detail as knowledge_node_detail,
)
from .knowledge_graph import (
    node_vector_status as graph_node_vector_status,
)
from .knowledge_graph import (
    pending_node_vectors as pending_graph_node_vectors,
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
    reusable_node_vectors as reusable_graph_node_vectors,
)
from .knowledge_graph import (
    search_node_vectors as search_graph_node_vectors,
)
from .knowledge_graph import (
    store_node_vectors as store_graph_node_vectors,
)
from .knowledge_graph import (
    supersede_source as supersede_knowledge_source,
)
from .lifecycle import (
    LIFECYCLE_SCHEMA_VERSION,
    BatchIngestItem,
    apply_scoped_delete,
    batch_ingest_items,
    begin_batch_ingest,
    complete_batch_ingest,
    completed_batch_indexes,
    ensure_no_active_scoped_delete,
    get_lifecycle_operation,
    get_lifecycle_operation_by_idempotency_key,
    init_lifecycle,
    plan_batch_ingest,
    plan_scoped_delete,
    record_batch_item,
    recoverable_operations,
    scoped_delete_retry_matches_current_incarnation,
)
from .migrations import (
    CURRENT_SCHEMA_VERSION,
    FailureInjector,
    MigrationError,
    execute_script,
    initialize_ir_edge_sources_schema,
    migrate_database,
    migrate_memory_database,
    validate_canonical_reference_payloads,
)
from .mirl import (
    SCHEMA_VERSION,
    SYMBOL_FOR_KIND,
    IRBatch,
    MIRLRecord,
    Pack,
    PersistReport,
    RecordKind,
    Status,
    TraceGraph,
    utc_now,
)
from .pool import ConnectionPool, SnapshotAwarePool
from .public_memory_handles import (
    PUBLIC_MEMORY_GENERATION_EXTENSION,
    init_public_memory_handles,
)
from .public_memory_handles import (
    register_public_memory_handles as register_public_memory_handle_rows,
)
from .public_memory_handles import (
    resolve_public_memory_handles as resolve_public_memory_handle_rows,
)
from .public_memory_handles import (
    restore_public_memory_handle_rows as restore_public_memory_handle_row_snapshot,
)
from .public_memory_handles import (
    snapshot_public_memory_handle_rows as snapshot_public_memory_handle_row_snapshot,
)
from .read_snapshot import (
    bind_connection,
    memory_snapshot_key,
    record_physical_open,
    snapshot_key_for_path,
)
from .reasoning_graph import (
    REASONING_RETRIEVAL_SCHEMA_VERSION,
    REASONING_SCHEMA_VERSION,
    REASONING_VERIFICATION_SCHEMA_VERSION,
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
from .reasoning_patterns import (
    REASONING_PATTERN_SCHEMA_VERSION,
    distill_reasoning_pattern,
    get_reasoning_pattern,
    record_reasoning_pattern_result,
    record_successful_pattern_uses,
    search_reasoning_patterns,
    use_reasoning_pattern,
)
from .reasoning_promotion import (
    REASONING_PROMOTION_SCHEMA_VERSION,
    init_reasoning_promotion,
    record_reasoning_promotion_application,
)
from .reasoning_promotion import (
    get_reasoning_promotion as get_reasoning_promotion_row,
)
from .reasoning_promotion import (
    list_reasoning_promotions as list_reasoning_promotion_rows,
)
from .reasoning_promotion import (
    propose_reasoning_promotion as propose_reasoning_promotion_row,
)
from .reasoning_promotion import (
    reasoning_promotion_eligibility as reasoning_promotion_eligibility_row,
)
from .reasoning_promotion import (
    reverse_reasoning_promotion as reverse_reasoning_promotion_row,
)
from .reasoning_promotion import (
    review_reasoning_promotion as review_reasoning_promotion_row,
)
from .reference_contracts import (
    CanonicalRecordAlreadyExistsError,
    CanonicalReferenceIntegrityError,
    reference_candidate_ids,
    remap_record_references,
    stored_reference_kinds,
    typed_ir_edges,
    validate_record_reference_contract,
    validate_typed_ir_edges,
)
from .retry import retry_db_operation
from .store_lease import StoreUseLease
from .temporal import (
    canonical_timestamp_extreme,
    normalize_timestamp,
    register_sqlite_timestamp_functions,
)
from .tenancy import is_principal_namespace, principal_tenant_id
from .vector import LEGACY_VECTOR_TEXT_VERSION, VECTOR_TEXT_VERSION
from .vector_outbox import (
    acknowledge,
    enqueue_index_intents,
    init_vector_outbox,
    pending_count,
    pending_entries,
    record_failure,
)
from .workspace import (
    WORKSPACE_SCHEMA_VERSION,
    init_workspace_schema,
    run_status,
    workspace_event_from_row,
    workspace_run_from_row,
)
from .workspace import (
    append_workspace_event as append_workspace_event_row,
)
from .workspace import (
    create_workspace_run as create_workspace_run_row,
)

LOGGER = logging.getLogger(__name__)

STORE_PROJECTION_VERSIONS = {
    "canonical_mirl": SCHEMA_VERSION,
    "core_storage": "core-storage/4",
    "graph_products": f"graph-products-schema/{GRAPH_PRODUCT_SCHEMA_VERSION}",
    "knowledge_graph": PROJECTION_VERSION,
    "knowledge_graph_vectors": GRAPH_NODE_VECTOR_TEXT_VERSION,
    "lifecycle": f"lifecycle-schema/{LIFECYCLE_SCHEMA_VERSION}",
    "reasoning_graph": f"reasoning-schema/{REASONING_SCHEMA_VERSION}",
    "reasoning_patterns": f"reasoning-pattern-schema/{REASONING_PATTERN_SCHEMA_VERSION}",
    "reasoning_promotion": f"reasoning-promotion-schema/{REASONING_PROMOTION_SCHEMA_VERSION}",
    "reasoning_retrieval": f"reasoning-retrieval-schema/{REASONING_RETRIEVAL_SCHEMA_VERSION}",
    "reasoning_verification": f"reasoning-verification-schema/{REASONING_VERIFICATION_SCHEMA_VERSION}",
    "sqlite_vector": VECTOR_TEXT_VERSION,
    "workspace": f"workspace-schema/{WORKSPACE_SCHEMA_VERSION}",
}

_REFERENCE_REPROJECTION_BATCH_SIZE = 500
_REFERENCE_REPROJECTION_QUEUE = "seam_pending_reference_reprojection"
_VECTOR_INDEX_COLUMNS = (
    "record_id",
    "model_name",
    "dimension",
    "source_text",
    "source_hash",
    "render_version",
    "namespace",
    "scope",
    "vector_json",
    "updated_at",
)


def _prepare_private_database(path: Path) -> None:
    """Create a database path without leaving memory content world-readable."""
    resolved = path.expanduser().resolve()
    parent = resolved.parent
    parent_existed = parent.exists()
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not parent_existed and os.name != "nt":
        parent.chmod(0o700)

    if resolved.exists():
        if not resolved.is_file():
            raise OSError("database path must name a regular file")
        if os.name != "nt":
            resolved.chmod(0o600)
        return

    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        descriptor = os.open(resolved, flags, 0o600)
    except FileExistsError:
        if not resolved.is_file():
            raise OSError("database path must name a regular file") from None
    else:
        os.close(descriptor)
    if os.name != "nt":
        resolved.chmod(0o600)


class SQLiteStore:
    def __init__(
        self,
        path: str | Path = "seam.db",
        pool_size: int | None = None,
        *,
        _migration_failure_injector: FailureInjector | None = None,
        _migration_backup_dir: str | Path | None = None,
    ) -> None:
        self.path = str(path)
        self._mem_anchor: sqlite3.Connection | None = None
        self._store_use_lease: StoreUseLease | None = None
        self._pool: SnapshotAwarePool | None = None
        self._verified_improvement_heads: dict[str, tuple[int, str]] = {}
        try:
            if self.path != ":memory:":
                resolved = Path(self.path).expanduser().resolve()
                self.path = str(resolved)
                # Resolve the snapshot key before anything can open a connection:
                # ``_connect`` reports every physical open against it.
                self._snapshot_key = snapshot_key_for_path(self.path)
                _prepare_private_database(resolved)
                self._store_use_lease = StoreUseLease(resolved)
                self.migration_result = migrate_database(
                    resolved,
                    initialize_schema=self._initialize_current_schema,
                    expected_projection_versions=STORE_PROJECTION_VERSIONS,
                    failure_injector=_migration_failure_injector,
                    backup_dir=_migration_backup_dir,
                )
            else:
                # A private in-memory database cannot be shared by path, so it is
                # keyed on this store and never joins another database's snapshot.
                self._snapshot_key = memory_snapshot_key(self)
                # Keep one anchor connection alive so that the shared in-memory
                # database persists across per-operation connections.
                self._mem_anchor = sqlite3.connect(
                    f"file:mem_{id(self)}?mode=memory&cache=shared",
                    uri=True,
                    timeout=5.0,
                    check_same_thread=False,
                )
                self._mem_anchor.row_factory = sqlite3.Row
                register_sqlite_timestamp_functions(self._mem_anchor)
                self.migration_result = migrate_memory_database(
                    self._mem_anchor,
                    initialize_schema=self._initialize_current_schema,
                    expected_projection_versions=STORE_PROJECTION_VERSIONS,
                )
            resolved_pool_size = pool_size if pool_size is not None else int(os.environ.get("SEAM_DB_POOL_SIZE", "5"))
            # A file database is shared by identity of the file, so any other reader
            # of the same path -- notably the SQLite vector index, which is opened on
            # ``store.path`` -- joins this store's read snapshot.
            self._pool = SnapshotAwarePool(
                ConnectionPool(
                    connect_factory=self._connect,
                    pool_size=resolved_pool_size,
                    idle_timeout=int(os.environ.get("SEAM_DB_POOL_TIMEOUT", "300")),
                ),
                self._snapshot_key,
            )
        except BaseException:
            self.close()
            raise

    @contextmanager
    def read_snapshot(self):
        """Hold one committed read snapshot for the calling context.

        Every read through this store -- and through any other reader keyed to
        the same database -- observes a single committed state for the duration,
        so a candidate set and the fingerprint attesting it can never be
        assembled from states that never coexisted. Writes attempted inside the
        snapshot raise rather than being silently discarded on release.
        """

        with bind_connection(self._snapshot_key, self._pool.checkout_physical) as connection:
            yield connection

    def check_ready(self) -> None:
        """Raise when the canonical store cannot serve a trivial read."""
        with self._pool.checkout() as connection:
            connection.execute("select 1").fetchone()

    def generate_graph_probes(
        self,
        *,
        namespace: str | None = None,
        scope: str | None = None,
        sample: int | None = 100,
        seed: int = 1234,
    ):
        """Generate deterministic graph probes without exposing the pool."""

        from .self_improve import generate_graph_probes

        with self._pool.checkout() as connection:
            return generate_graph_probes(
                connection,
                namespace=namespace,
                scope=scope,
                sample=sample,
                seed=seed,
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
        register_sqlite_timestamp_functions(connection)
        if self.path != ":memory:":
            connection.execute("pragma journal_mode=WAL")
        connection.execute("pragma busy_timeout=5000")
        connection.execute("pragma foreign_keys=ON")
        record_physical_open(self._snapshot_key)
        return connection

    def close(self) -> None:
        try:
            pool = getattr(self, "_pool", None)
            if pool is not None:
                pool.close()
            if self._mem_anchor is not None:
                self._mem_anchor.close()
                self._mem_anchor = None
        finally:
            lease = self._store_use_lease
            if lease is not None:
                lease.close()
                self._store_use_lease = None

    def __enter__(self) -> "SQLiteStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    @property
    def schema_version(self) -> int:
        return CURRENT_SCHEMA_VERSION

    def _initialize_current_schema(self, connection: sqlite3.Connection) -> None:
        execute_script(
            connection,
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
                    src_ref_type text not null default 'record' check (src_ref_type in ('record', 'virtual', 'RAW', 'SPAN', 'ENT', 'CLM', 'EVT', 'REL', 'STA', 'SYM', 'PACK', 'FLOW', 'PROV', 'META')),
                    edge_type text not null,
                    dst_id text not null,
                    dst_ref_type text not null default 'record' check (dst_ref_type in ('record', 'virtual', 'RAW', 'SPAN', 'ENT', 'CLM', 'EVT', 'REL', 'STA', 'SYM', 'PACK', 'FLOW', 'PROV', 'META'))
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
                    render_version text not null default 'mirl-vector-text/2',
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
        initialize_ir_edge_sources_schema(connection)
        connection.execute("pragma foreign_keys = on")
        vector_columns = {
            str(row["name"])
            for row in connection.execute("pragma table_info(vector_index)").fetchall()
        }
        if "source_hash" not in vector_columns:
            connection.execute(
                "alter table vector_index add column "
                "source_hash text not null default ''"
            )
        if "render_version" not in vector_columns:
            connection.execute(
                "alter table vector_index add column render_version text "
                f"not null default '{LEGACY_VECTOR_TEXT_VERSION}'"
            )
        if "namespace" not in vector_columns:
            connection.execute(
                "alter table vector_index add column namespace text not null default ''"
            )
            connection.execute(
                "update vector_index set namespace = coalesce(("
                "select r.ns from ir_records r where r.id = vector_index.record_id"
                "), '')"
            )
        if "scope" not in vector_columns:
            connection.execute(
                "alter table vector_index add column scope text not null default ''"
            )
            connection.execute(
                "update vector_index set scope = coalesce(("
                "select r.scope from ir_records r where r.id = vector_index.record_id"
                "), '')"
            )
        self._ensure_typed_edge_columns(connection)
        self._cleanup_orphan_edges(connection)
        init_knowledge_graph(connection, allow_migration=True)
        init_graph_products(connection)
        init_lifecycle(connection)
        init_public_memory_handles(connection)
        init_workspace_schema(connection)
        init_reasoning_graph(connection)
        init_reasoning_promotion(connection)
        init_improvement_experiment_schema(connection)

    @staticmethod
    def _ensure_typed_edge_columns(connection: sqlite3.Connection) -> None:
        """Upgrade an unversioned legacy ``ir_edges`` table in place.

        Versioned core-storage/1 databases use the registered projection
        migration.  This narrow path exists for pre-registry stores processed
        by the central v0 -> v2 bootstrap.
        """

        columns = {
            str(row[1]) for row in connection.execute("pragma table_info(ir_edges)")
        }
        typed_columns = {"src_ref_type", "dst_ref_type"}
        present = columns & typed_columns
        if present == typed_columns:
            return
        if present:
            raise RuntimeError("ir_edges endpoint typing is only partially installed")
        connection.execute(
            "alter table ir_edges add column src_ref_type text not null "
            "default 'record' check (src_ref_type in ('record', 'virtual', "
            "'RAW', 'SPAN', 'ENT', 'CLM', 'EVT', 'REL', 'STA', 'SYM', "
            "'PACK', 'FLOW', 'PROV', 'META'))"
        )
        connection.execute(
            "alter table ir_edges add column dst_ref_type text not null "
            "default 'record' check (dst_ref_type in ('record', 'virtual', "
            "'RAW', 'SPAN', 'ENT', 'CLM', 'EVT', 'REL', 'STA', 'SYM', "
            "'PACK', 'FLOW', 'PROV', 'META'))"
        )

    def _cleanup_orphan_edges(self, connection: sqlite3.Connection) -> None:
        """Remove invalid endpoints and edge triples without canonical owners."""

        connection.execute(
            "delete from ir_edges where "
            "(src_ref_type != 'virtual' and not exists "
            " (select 1 from ir_records where id = ir_edges.src_id and "
            "  (ir_edges.src_ref_type = 'record' or kind = ir_edges.src_ref_type))) or "
            "(dst_ref_type != 'virtual' and not exists "
            " (select 1 from ir_records where id = ir_edges.dst_id and "
            "  (ir_edges.dst_ref_type = 'record' or kind = ir_edges.dst_ref_type)))"
        )
        connection.execute(
            "delete from ir_edge_sources where source_record_id not in "
            "(select id from ir_records)"
        )
        connection.execute(
            "delete from ir_edges where not exists ("
            "select 1 from ir_edge_sources sources "
            "where sources.src_id = ir_edges.src_id "
            "and sources.edge_type = ir_edges.edge_type "
            "and sources.dst_id = ir_edges.dst_id)"
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

    @retry_db_operation()
    def register_public_memory_handles(
        self,
        *,
        tenant_id: str,
        namespace: str,
        scope: str,
        handles: Mapping[str, tuple[str, str]],
    ) -> None:
        with self._pool.checkout() as connection:
            try:
                connection.execute("begin immediate")
                register_public_memory_handle_rows(
                    connection,
                    tenant_id=tenant_id,
                    namespace=namespace,
                    scope=scope,
                    handles=handles,
                )
                connection.commit()
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise

    def resolve_public_memory_handles(
        self,
        *,
        tenant_id: str,
        namespace: str,
        scope: str,
        handle_ids: Sequence[str],
    ) -> dict[str, tuple[str, str]]:
        with self._pool.checkout() as connection:
            return resolve_public_memory_handle_rows(
                connection,
                tenant_id=tenant_id,
                namespace=namespace,
                scope=scope,
                handle_ids=handle_ids,
            )

    def snapshot_public_memory_handle_rows(
        self,
        record_ids: Iterable[str],
    ) -> tuple[tuple[object, ...], ...]:
        """Capture exact handle rows before a runtime projection write."""

        with self._pool.checkout() as connection:
            return snapshot_public_memory_handle_row_snapshot(
                connection, record_ids
            )

    def _reconcile_entities(
        self,
        connection: sqlite3.Connection,
        batch: IRBatch,
    ) -> tuple[dict[str, str], set[str], list[MIRLRecord]]:
        """Cross-turn entity coreference, scoped per ``(ns, scope)``.

        Every ``compile_nl`` call is independent and mints a fresh ``ent:``
        id per label, so the same real-world entity gets a different id in
        every turn it is mentioned in (HISTORY#321/#323 cat1 root cause).
        The first occurrence of an identity is canonical. An explicit
        ``ext["seam.entity_identity"]`` is the stable identity key; otherwise
        the normalized label remains the backwards-compatible key. Explicitly
        keyed and label-only identities never collapse into one another. Later
        mentions accumulate provenance/evidence on the canonical ENT while
        ``id_map`` rewrites their references. No merge crosses namespace or
        scope.
        """
        id_map: dict[str, str] = {}
        skip_ids: set[str] = set()
        canonical_updates: dict[str, MIRLRecord] = {}
        batch_ent_records = [r for r in batch.records if r.kind == RecordKind.ENT]
        if not batch_ent_records:
            return id_map, skip_ids, []

        incoming_by_id = {record.id: record for record in batch_ent_records}
        boundaries = {(record.ns, record.scope) for record in batch_ent_records}
        for ns, scope in sorted(boundaries):
            canonical_by_identity: dict[tuple[str, str], MIRLRecord] = {}
            for row in connection.execute(
                "select id, payload_json from ir_records "
                "where kind = ? and ns = ? and scope = ? order by created_at, id",
                (RecordKind.ENT.value, ns, scope),
            ):
                existing = MIRLRecord.from_dict(json.loads(row["payload_json"]))
                identity = _entity_identity(existing)
                if identity is None:
                    continue
                canonical_by_identity.setdefault(identity, existing)
            for record in batch_ent_records:
                if (record.ns, record.scope) != (ns, scope):
                    continue
                identity = _entity_identity(record)
                if identity is None:
                    continue
                canonical = canonical_by_identity.get(identity)
                if canonical is not None and canonical.id != record.id:
                    id_map[record.id] = canonical.id
                    skip_ids.add(record.id)
                    if _merge_entity_mentions(canonical, record):
                        if canonical.id in incoming_by_id:
                            _merge_entity_mentions(incoming_by_id[canonical.id], canonical)
                            canonical_by_identity[identity] = incoming_by_id[canonical.id]
                        else:
                            canonical_updates[canonical.id] = canonical
                elif canonical is not None:
                    _merge_entity_mentions(record, canonical)
                    canonical_by_identity[identity] = record
                else:
                    canonical_by_identity[identity] = record
        return id_map, skip_ids, [canonical_updates[key] for key in sorted(canonical_updates)]

    def _persist_ir_on_connection(
        self,
        connection: sqlite3.Connection,
        batch: IRBatch,
        *,
        reconcile_entities: bool = True,
        preserve_node_vectors: bool = False,
        reject_existing_ids: bool = False,
    ) -> list[str]:
        """Persist canonical MIRL and its graph projection in one transaction."""

        record_ids = [record.id for record in batch.records]
        if any(
            not isinstance(record_id, str) or not record_id.strip()
            for record_id in record_ids
        ):
            raise ValueError("canonical record id must be a nonblank string")
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("IR batch contains duplicate record identifiers")
        virtual_references_by_id = {
            record.id: validate_record_reference_contract(record)
            for record in batch.records
        }

        # Entity reconciliation is read-before-write. Acquire the SQLite write
        # lock before that read so pooled writers cannot choose distinct
        # canonical ids from the same stale snapshot.
        if not connection.in_transaction:
            connection.execute("begin immediate")
        incoming_kinds = {record.id: record.kind for record in batch.records}
        stored_incoming_kinds = stored_reference_kinds(connection, incoming_kinds)
        if reject_existing_ids and stored_incoming_kinds:
            # The REST surface is create-only. Perform this check only after
            # BEGIN IMMEDIATE so another process cannot insert a colliding id
            # between the check and the canonical write. Do not include ids in
            # the exception: callers need the conflict class, not store
            # membership disclosure.
            raise CanonicalRecordAlreadyExistsError(
                "one or more canonical record ids already exist"
            )
        if any(
            stored_kind is not incoming_kinds[record_id]
            for record_id, stored_kind in stored_incoming_kinds.items()
        ):
            # This check deliberately precedes entity reconciliation. A same-id
            # ENT that would otherwise be skipped as a duplicate label must not
            # hide an attempted kind change of the canonical row already stored
            # under that identifier.
            raise CanonicalReferenceIntegrityError(
                "canonical record kind cannot change during persistence"
            )
        incoming_boundaries = {
            record.id: (record.ns, record.scope) for record in batch.records
        }
        stored_record_states: dict[str, tuple[str, str, str]] = {}
        ordered_record_ids = sorted(incoming_boundaries)
        for start in range(0, len(ordered_record_ids), 500):
            chunk = ordered_record_ids[start : start + 500]
            placeholders = ",".join("?" for _ in chunk)
            stored_record_states.update(
                {
                    str(row[0]): (
                        str(row[1]),
                        str(row[2]),
                        str(row[3]),
                    )
                    for row in connection.execute(
                        "select id, ns, scope, status "
                        "from ir_records where id in "
                        f"({placeholders})",
                        chunk,
                    ).fetchall()
                }
            )
        stored_boundaries = {
            record_id: (stored[0], stored[1])
            for record_id, stored in stored_record_states.items()
        }
        if any(
            stored_boundary != incoming_boundaries[record_id]
            and (
                is_principal_namespace(stored_boundary[0])
                or is_principal_namespace(incoming_boundaries[record_id][0])
            )
            for record_id, stored_boundary in stored_boundaries.items()
        ):
            # Principal-salted identifiers are immutable ownership keys. A
            # collision must fail closed before entity reconciliation or any
            # derived projection can move a hosted record to another boundary.
            # Legacy/self-host canonical movement remains byte-compatible.
            raise CanonicalReferenceIntegrityError(
                "canonical record boundary cannot change during persistence"
            )
        previous_provenance_targets = self._stored_provenance_targets(
            connection,
            (
                record.id
                for record in batch.records
                if record.kind is RecordKind.PROV
            ),
        )
        id_map, skip_ids, canonical_entity_updates = (
            self._reconcile_entities(connection, batch)
            if reconcile_entities
            else ({}, set(), [])
        )
        projected = [
            *canonical_entity_updates,
            *(record for record in batch.records if record.id not in skip_ids),
        ]
        for record in canonical_entity_updates:
            virtual_references_by_id[record.id] = validate_record_reference_contract(
                record
            )
        for record in projected:
            remap_record_references(record, id_map)
        public_generation_records = [
            record
            for record in projected
            if is_principal_namespace(record.ns)
            and PUBLIC_MEMORY_GENERATION_EXTENSION in record.ext
        ]
        stored_principal_payloads: dict[str, str] = {}
        public_generation_record_ids = sorted(
            {record.id for record in public_generation_records}
        )
        for start in range(0, len(public_generation_record_ids), 500):
            chunk = public_generation_record_ids[start : start + 500]
            placeholders = ",".join("?" for _ in chunk)
            stored_principal_payloads.update(
                {
                    str(row[0]): str(row[1])
                    for row in connection.execute(
                        "select id, payload_json from ir_records where id in "
                        f"({placeholders})",
                        chunk,
                    ).fetchall()
                }
            )
        for namespace, scope in sorted(
            {(record.ns, record.scope) for record in public_generation_records}
        ):
            tenant_id = principal_tenant_id(namespace)
            if tenant_id is None:
                raise CanonicalReferenceIntegrityError(
                    "principal memory namespace is malformed"
                )
            ensure_no_active_scoped_delete(
                connection,
                tenant_id=tenant_id,
                namespace=namespace,
                scope=scope,
                record_ids=(
                    record.id
                    for record in public_generation_records
                    if record.ns == namespace and record.scope == scope
                ),
            )
        replaced_public_generations: list[str] = []
        for record in projected:
            if not is_principal_namespace(record.ns):
                continue
            incoming_generation = record.ext.get(
                PUBLIC_MEMORY_GENERATION_EXTENSION
            )
            if incoming_generation is None:
                continue
            if (
                not isinstance(incoming_generation, str)
                or len(incoming_generation) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in incoming_generation
                )
            ):
                raise CanonicalReferenceIntegrityError(
                    "public memory generation is invalid"
                )
            stored_state = stored_record_states.get(record.id)
            stored_payload_json = stored_principal_payloads.get(record.id)
            if stored_state is None or stored_payload_json is None:
                continue
            stored_payload = json.loads(stored_payload_json)
            stored_ext = stored_payload.get("ext")
            stored_generation = (
                stored_ext.get(PUBLIC_MEMORY_GENERATION_EXTENSION)
                if isinstance(stored_ext, dict)
                else None
            )
            if (
                stored_generation is not None
                and stored_state[2] != Status.DELETED_SOFT.value
                and record.status is not Status.DELETED_SOFT
            ):
                # A duplicate live remember is the same incarnation. Preserve
                # its registered capabilities; only resurrection after a
                # completed delete accepts a newly minted generation.
                record.ext[PUBLIC_MEMORY_GENERATION_EXTENSION] = stored_generation
                continue
            if stored_generation != incoming_generation:
                replaced_public_generations.append(record.id)
        for start in range(0, len(replaced_public_generations), 500):
            chunk = replaced_public_generations[start : start + 500]
            placeholders = ",".join("?" for _ in chunk)
            connection.execute(
                "delete from public_memory_handle where record_id in "
                f"({placeholders})",
                chunk,
            )
        projected_virtual_references = {
            record.id: frozenset(
                id_map.get(reference_id, reference_id)
                for reference_id in virtual_references_by_id[record.id]
            )
            for record in projected
        }
        batch_kinds = {record.id: record.kind for record in projected}
        candidate_ids = {
            candidate_id
            for record in projected
            for candidate_id in reference_candidate_ids(record)
            if candidate_id not in batch_kinds
        }
        known_record_kinds = stored_reference_kinds(connection, candidate_ids)
        known_record_kinds.update(batch_kinds)
        canonical_boundaries = {
            record.id: (record.ns, record.scope) for record in projected
        }
        stored_candidate_ids = sorted(candidate_ids - set(canonical_boundaries))
        for start in range(0, len(stored_candidate_ids), 500):
            chunk = stored_candidate_ids[start : start + 500]
            placeholders = ",".join("?" for _ in chunk)
            canonical_boundaries.update(
                {
                    str(row[0]): (str(row[1]), str(row[2]))
                    for row in connection.execute(
                        "select id, ns, scope from ir_records where id in "
                        f"({placeholders})",
                        chunk,
                    ).fetchall()
                }
            )
        for record in projected:
            if record.kind is not RecordKind.REL:
                continue
            for reference_id in reference_candidate_ids(record):
                reference_boundary = canonical_boundaries.get(reference_id)
                if reference_boundary is not None and reference_boundary != (
                    record.ns,
                    record.scope,
                ):
                    raise CanonicalReferenceIntegrityError(
                        "canonical relation reference crosses its namespace or scope boundary"
                    )
        for record in projected:
            validate_typed_ir_edges(
                typed_ir_edges(
                    record,
                    known_record_kinds=known_record_kinds,
                    validated_virtual_references=(
                        projected_virtual_references[record.id]
                    ),
                ),
                known_record_kinds=known_record_kinds,
            )
        stored_ids: list[str] = []
        edge_records: list[MIRLRecord] = []
        for record in projected:
            stored_ids.append(record.id)
            payload = json.dumps(
                record.to_dict(), sort_keys=True, separators=(",", ":")
            )
            connection.execute(
                """
                insert into ir_records
                (id, kind, ns, scope, status, conf, t0, t1, created_at, updated_at, payload_json)
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(id) do update set
                    kind = excluded.kind,
                    ns = excluded.ns,
                    scope = excluded.scope,
                    status = excluded.status,
                    conf = excluded.conf,
                    t0 = excluded.t0,
                    t1 = excluded.t1,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at,
                    payload_json = excluded.payload_json
                """,
                (
                    record.id,
                    record.kind.value,
                    record.ns,
                    record.scope,
                    record.status.value,
                    record.conf,
                    record.t0,
                    record.t1,
                    record.created_at,
                    record.updated_at,
                    payload,
                ),
            )
            self._persist_specialized(connection, record)
            edge_records.append(record)

        late_provenance_targets: set[str] = set()
        new_target_ids = set(batch_kinds) - set(stored_incoming_kinds)
        reprojection_target_ids = new_target_ids | {
            record.id
            for record in projected
            if record.kind is RecordKind.PROV
        }
        if reprojection_target_ids:
            self._reset_reference_reprojection_queue(connection)
            try:
                self._queue_reference_dependents(
                    connection,
                    target_record_ids=reprojection_target_ids,
                    excluded_source_ids=set(batch_kinds),
                )
                # A mixed batch may contain one owner of a shared virtual edge
                # while another owner remains outside the batch. Clear every
                # queued contributor before the incoming batch emits canonical
                # endpoint types so neither batch order nor batch size matters.
                self._clear_queued_reference_edge_sources(connection)
                self._project_persisted_record_batch(
                    connection,
                    edge_records,
                    known_record_kinds=known_record_kinds,
                    virtual_references_by_id=projected_virtual_references,
                    preserve_node_vectors=preserve_node_vectors,
                    cleanup_orphan_edges=False,
                )
                late_provenance_targets = (
                    self._reproject_queued_reference_dependents(
                        connection,
                        preserve_node_vectors=preserve_node_vectors,
                    )
                )
            finally:
                self._drop_reference_reprojection_queue(connection)
        else:
            self._project_persisted_record_batch(
                connection,
                edge_records,
                known_record_kinds=known_record_kinds,
                virtual_references_by_id=projected_virtual_references,
                preserve_node_vectors=preserve_node_vectors,
            )
        provenance_targets = previous_provenance_targets | {
            str(record.attrs["entity"])
            for record in projected
            if record.kind is RecordKind.PROV
            and isinstance(record.attrs.get("entity"), str)
            and str(record.attrs["entity"]).strip()
        } | late_provenance_targets
        self._reproject_canonical_records(
            connection,
            provenance_targets,
            required_kind=RecordKind.RAW,
            preserve_node_vectors=preserve_node_vectors,
        )
        return stored_ids

    def _project_persisted_record_batch(
        self,
        connection: sqlite3.Connection,
        records: Sequence[MIRLRecord],
        *,
        known_record_kinds: dict[str, RecordKind],
        virtual_references_by_id: dict[str, frozenset[str]],
        preserve_node_vectors: bool,
        cleanup_orphan_edges: bool = True,
    ) -> None:
        """Project one already-written canonical batch without order effects."""

        for record in records:
            self._persist_edges(
                connection,
                record,
                known_record_kinds=known_record_kinds,
                validated_virtual_references=virtual_references_by_id[record.id],
                emit=False,
            )
        for record in records:
            self._persist_edges(
                connection,
                record,
                known_record_kinds=known_record_kinds,
                validated_virtual_references=virtual_references_by_id[record.id],
                clear=False,
            )
        if cleanup_orphan_edges:
            self._delete_unowned_ir_edges(connection)
        project_knowledge_records(
            connection,
            records,
            _validated_virtual_references=virtual_references_by_id,
        )
        if not preserve_node_vectors:
            remove_orphan_node_vectors(connection)

    @retry_db_operation()
    def persist_ir(
        self,
        batch: IRBatch,
        *,
        _preserve_node_vectors: bool = False,
        _enqueue_vector_outbox: bool = False,
        _reject_existing_ids: bool = False,
    ) -> PersistReport:
        with self._pool.checkout() as connection:
            try:
                stored_ids = self._persist_ir_on_connection(
                    connection,
                    batch,
                    preserve_node_vectors=_preserve_node_vectors,
                    reject_existing_ids=_reject_existing_ids,
                )
                outbox_entry_ids: list[int] = []
                if _enqueue_vector_outbox:
                    # Same connection, same transaction, same commit as the
                    # canonical rows. Enqueuing after the commit would
                    # reintroduce exactly the window this exists to close.
                    outbox_entry_ids = enqueue_index_intents(connection, stored_ids)
                connection.commit()
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
        return PersistReport(
            stored_ids=stored_ids,
            store_path=self.path,
            outbox_entry_ids=outbox_entry_ids,
        )

    @retry_db_operation()
    def persist_ingest_outcome(
        self,
        batch: IRBatch,
        *,
        document_id: str,
        ns: str,
        scope: str,
        source_ref: str,
        source_hash: str,
        byte_count: int,
        chunk_count: int,
        metadata: dict[str, object],
        failure_injector: Callable[[str], None] | None = None,
    ) -> tuple[PersistReport, dict[str, object], list[str], list[str]]:
        """Commit the complete canonical ingest outcome in one transaction."""

        inject = failure_injector or (lambda _transition: None)
        now = utc_now()
        with self._pool.checkout() as connection:
            try:
                if not connection.in_transaction:
                    connection.execute("begin immediate")
                old_rows = connection.execute(
                    "select document_id from document_status "
                    "where ns = ? and scope = ? and source_ref = ? "
                    "and document_id != ? and deleted_at is null "
                    "order by document_id",
                    (ns, scope, source_ref, document_id),
                ).fetchall()
                superseded_document_ids = [str(row[0]) for row in old_rows]

                stored_ids = self._persist_ir_on_connection(
                    connection,
                    batch,
                    preserve_node_vectors=True,
                )
                inject("after_canonical_records")

                protected_ids = set(stored_ids)
                for record in batch.records:
                    protected_ids.update(reference_candidate_ids(record))
                superseded_record_ids = self._supersede_ingest_records(
                    connection,
                    superseded_document_ids,
                    protected_ids=protected_ids,
                    superseded_at=now,
                )
                if superseded_document_ids:
                    placeholders = ",".join("?" for _ in superseded_document_ids)
                    connection.execute(
                        "update document_status set deleted_at = ?, updated_at = ? "
                        f"where document_id in ({placeholders})",
                        [now, now, *superseded_document_ids],
                    )
                supersede_knowledge_source(
                    connection,
                    namespace=ns,
                    scope=scope,
                    source_ref=source_ref,
                    except_document_id=document_id,
                    superseded_at=now,
                    superseded_record_ids=superseded_record_ids,
                )
                inject("after_supersession")

                existing = connection.execute(
                    "select created_at from document_status where document_id = ?",
                    (document_id,),
                ).fetchone()
                created_at = str(existing[0]) if existing else now
                connection.execute(
                    """
                    insert or replace into document_status
                    (document_id, ns, scope, source_ref, source_hash, byte_count,
                     chunk_count, extraction_status, indexed_status, deleted_at,
                     metadata_json, created_at, updated_at)
                    values (?, ?, ?, ?, ?, ?, ?, 'compiled', 'pending', null, ?, ?, ?)
                    """,
                    (
                        document_id,
                        ns,
                        scope,
                        source_ref,
                        source_hash,
                        int(byte_count),
                        int(chunk_count),
                        json.dumps(metadata, sort_keys=True, separators=(",", ":")),
                        created_at,
                        now,
                    ),
                )
                inject("after_document_status")

                index_entry_ids = enqueue_index_intents(
                    connection,
                    stored_ids,
                    ingest_document_id=document_id,
                )
                delete_entry_ids = enqueue_index_intents(
                    connection,
                    superseded_record_ids,
                    ingest_document_id=document_id,
                )
                inject("after_vector_intents")
                connection.commit()
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise

        document = self.read_document_status(document_id)
        return (
            PersistReport(
                stored_ids=stored_ids,
                store_path=self.path,
                outbox_entry_ids=[*index_entry_ids, *delete_entry_ids],
            ),
            document,
            superseded_document_ids,
            superseded_record_ids,
        )

    def _supersede_ingest_records(
        self,
        connection: sqlite3.Connection,
        document_ids: Sequence[str],
        *,
        protected_ids: set[str],
        superseded_at: str,
    ) -> list[str]:
        candidates: set[str] = set()
        for old_document_id in document_ids:
            suffix = old_document_id.split(":", 1)[-1]
            candidates.update(
                str(row[0])
                for row in connection.execute(
                    "select id from ir_records where id like ?",
                    (f"%:{suffix}:%",),
                ).fetchall()
            )
        superseded_ids = sorted(candidates - protected_ids)
        for record_id in superseded_ids:
            row = connection.execute(
                "select payload_json from ir_records where id = ?", (record_id,)
            ).fetchone()
            if row is None:
                continue
            payload = json.loads(str(row[0]))
            payload["status"] = Status.SUPERSEDED.value
            payload["updated_at"] = superseded_at
            connection.execute(
                "update ir_records set status = ?, updated_at = ?, payload_json = ? "
                "where id = ?",
                (
                    Status.SUPERSEDED.value,
                    superseded_at,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    record_id,
                ),
            )
        return superseded_ids

    @retry_db_operation()
    def acknowledge_vector_outbox(self, entry_ids: Iterable[int]) -> int:
        """Retire intents whose vector update is durably applied."""

        with self._pool.checkout() as connection:
            removed = acknowledge(connection, entry_ids)
            connection.commit()
        return removed

    @retry_db_operation()
    def complete_ingest_projection(
        self, document_id: str, entry_ids: Iterable[int]
    ) -> dict[str, object]:
        """Retire projection intent and mark its document indexed atomically."""

        with self._pool.checkout() as connection:
            try:
                if not connection.in_transaction:
                    connection.execute("begin immediate")
                acknowledge(connection, entry_ids)
                connection.execute(
                    "update document_status set indexed_status = 'indexed', "
                    "updated_at = ? where document_id = ?",
                    (utc_now(), document_id),
                )
                connection.commit()
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise
        return self.read_document_status(document_id)

    def pending_vector_outbox(self, *, limit: int | None = None) -> list[dict[str, object]]:
        """Return vector index intents that were never acknowledged."""

        with self._pool.checkout() as connection:
            init_vector_outbox(connection)
            connection.commit()
            return pending_entries(connection, limit=limit)

    def pending_vector_outbox_count(self) -> int:
        with self._pool.checkout() as connection:
            return pending_count(connection)

    @retry_db_operation()
    def complete_reconciled_ingest_documents(self) -> int:
        """Mark pending ingest documents indexed once none of their intents remain."""

        now = utc_now()
        with self._pool.checkout() as connection:
            rows = connection.execute(
                "select document_id from document_status "
                "where indexed_status = 'pending' and deleted_at is null"
            ).fetchall()
            completed = 0
            for row in rows:
                document_id = str(row[0])
                pending = connection.execute(
                    "select 1 from vector_outbox "
                    "where ingest_document_id = ? limit 1",
                    (document_id,),
                ).fetchone()
                if pending is not None:
                    continue
                completed += int(
                    connection.execute(
                        "update document_status set indexed_status = 'indexed', "
                        "updated_at = ? where document_id = ? "
                        "and indexed_status = 'pending' and deleted_at is null",
                        (now, document_id),
                    ).rowcount
                    or 0
                )
            connection.commit()
        return completed

    @retry_db_operation()
    def record_vector_outbox_failure(
        self, entry_ids: Iterable[int], *, error_type: str
    ) -> None:
        with self._pool.checkout() as connection:
            record_failure(connection, entry_ids, error_type=error_type)
            connection.commit()

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
            boundary = connection.execute(
                "select ns, scope from document_status where document_id = ?",
                (except_document_id,),
            ).fetchone()
            if boundary is None:
                raise KeyError(except_document_id)
            cursor = connection.execute(
                "update document_status set deleted_at = ?, updated_at = ? "
                "where ns = ? and scope = ? and source_ref = ? "
                "and document_id != ? and deleted_at is null",
                (
                    now,
                    now,
                    str(boundary["ns"]),
                    str(boundary["scope"]),
                    source_ref,
                    except_document_id,
                ),
            )
            supersede_knowledge_source(
                connection,
                namespace=str(boundary["ns"]),
                scope=str(boundary["scope"]),
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
            agent = None
            for value in (
                record.ext.get("agent_id"),
                record.ext.get("agent"),
                attrs.get("agent"),
            ):
                if isinstance(value, str) and value.strip():
                    agent = value.strip()
                    break
            connection.execute(
                "insert or replace into prov_log (id, entity, activity, agent, payload_json) values (?, ?, ?, ?, ?)",
                (record.id, attrs.get("entity"), attrs.get("activity"), agent, json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"))),
            )

    @staticmethod
    def _stored_provenance_targets(
        connection: sqlite3.Connection,
        record_ids: Iterable[str],
    ) -> set[str]:
        """Return canonical entities attributed by the selected PROV rows."""

        ordered_ids = sorted({str(record_id) for record_id in record_ids})
        targets: set[str] = set()
        for offset in range(
            0,
            len(ordered_ids),
            _REFERENCE_REPROJECTION_BATCH_SIZE,
        ):
            chunk = ordered_ids[
                offset : offset + _REFERENCE_REPROJECTION_BATCH_SIZE
            ]
            placeholders = ",".join("?" for _ in chunk)
            rows = connection.execute(
                "select payload_json from ir_records where kind = ? and id in "
                f"({placeholders}) order by id",
                [RecordKind.PROV.value, *chunk],
            ).fetchall()
            for row in rows:
                try:
                    record = MIRLRecord.from_dict(json.loads(row[0]))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    raise CanonicalReferenceIntegrityError(
                        "canonical provenance payload cannot be reprojected"
                    ) from exc
                entity = record.attrs.get("entity")
                if isinstance(entity, str) and entity.strip():
                    targets.add(entity)
        return targets

    def _reproject_records(
        self,
        connection: sqlite3.Connection,
        records: Sequence[MIRLRecord],
        *,
        preserve_node_vectors: bool = False,
        clear_edge_sources: bool = True,
        cleanup_orphan_edges: bool = True,
    ) -> None:
        """Rebuild core edges and KG rows for one bounded canonical slice."""

        if not records:
            return
        virtual_references_by_id = {
            record.id: validate_record_reference_contract(record)
            for record in records
        }
        candidate_ids = {
            candidate_id
            for record in records
            for candidate_id in reference_candidate_ids(record)
        }
        known_record_kinds = stored_reference_kinds(connection, candidate_ids)
        known_record_kinds.update({record.id: record.kind for record in records})
        for record in records:
            validate_typed_ir_edges(
                typed_ir_edges(
                    record,
                    known_record_kinds=known_record_kinds,
                    validated_virtual_references=(
                        virtual_references_by_id[record.id]
                    ),
                ),
                known_record_kinds=known_record_kinds,
            )
        if clear_edge_sources:
            for record in records:
                self._persist_edges(
                    connection,
                    record,
                    known_record_kinds=known_record_kinds,
                    validated_virtual_references=(
                        virtual_references_by_id[record.id]
                    ),
                    emit=False,
                )
        for record in records:
            self._persist_edges(
                connection,
                record,
                known_record_kinds=known_record_kinds,
                validated_virtual_references=(
                    virtual_references_by_id[record.id]
                ),
                clear=False,
            )
        if cleanup_orphan_edges:
            self._delete_unowned_ir_edges(connection)
        if not preserve_node_vectors:
            placeholders = ",".join("?" for _ in records)
            connection.execute(
                "delete from knowledge_node_vectors where node_id in "
                f"({placeholders})",
                [record.id for record in records],
            )
        project_knowledge_records(
            connection,
            records,
            _validated_virtual_references=virtual_references_by_id,
        )
        if not preserve_node_vectors:
            remove_orphan_node_vectors(connection)

    def _reproject_canonical_records(
        self,
        connection: sqlite3.Connection,
        record_ids: Iterable[str],
        *,
        required_kind: RecordKind | None = None,
        preserve_node_vectors: bool = False,
    ) -> None:
        """Load and reproject selected canonical rows in bounded slices."""

        ordered_ids = sorted({str(record_id) for record_id in record_ids})
        for offset in range(
            0,
            len(ordered_ids),
            _REFERENCE_REPROJECTION_BATCH_SIZE,
        ):
            chunk = ordered_ids[
                offset : offset + _REFERENCE_REPROJECTION_BATCH_SIZE
            ]
            placeholders = ",".join("?" for _ in chunk)
            kind_clause = " and kind = ?" if required_kind is not None else ""
            parameters: list[object] = [*chunk]
            if required_kind is not None:
                parameters.append(required_kind.value)
            rows = connection.execute(
                "select payload_json from ir_records where id in "
                f"({placeholders}){kind_clause} order by id",
                parameters,
            ).fetchall()
            records: list[MIRLRecord] = []
            for row in rows:
                try:
                    records.append(MIRLRecord.from_dict(json.loads(row[0])))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    raise CanonicalReferenceIntegrityError(
                        "canonical payload cannot be reprojected"
                    ) from exc
            self._reproject_records(
                connection,
                records,
                preserve_node_vectors=preserve_node_vectors,
            )

    @staticmethod
    def _reset_reference_reprojection_queue(
        connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            f'drop table if exists temp."{_REFERENCE_REPROJECTION_QUEUE}"'
        )
        connection.execute(
            f'create temp table "{_REFERENCE_REPROJECTION_QUEUE}" '
            "(record_id text primary key) without rowid"
        )

    @staticmethod
    def _queue_reference_reprojection_ids(
        connection: sqlite3.Connection,
        record_ids: Iterable[str],
    ) -> None:
        rows = [(str(record_id),) for record_id in record_ids]
        if rows:
            connection.executemany(
                f'insert or ignore into "{_REFERENCE_REPROJECTION_QUEUE}" '
                "(record_id) values (?)",
                rows,
            )

    def _queue_reference_dependents(
        self,
        connection: sqlite3.Connection,
        target_record_ids: set[str],
        *,
        excluded_source_ids: set[str] | None = None,
    ) -> None:
        """Queue canonical rows whose closed references mention target IDs."""

        excluded_sources = excluded_source_ids or set()
        target_tokens = tuple(
            json.dumps(record_id, ensure_ascii=True)
            for record_id in sorted(target_record_ids)
        )
        cursor = connection.execute(
            "select id, payload_json from ir_records order by id"
        )
        while True:
            rows = cursor.fetchmany(_REFERENCE_REPROJECTION_BATCH_SIZE)
            if not rows:
                break
            affected_ids: list[str] = []
            for row in rows:
                record_id = str(row[0])
                if record_id in excluded_sources:
                    continue
                payload_json = str(row[1])
                # Decode only rows that can contain one of the exact JSON
                # string tokens. This keeps a late-target projection bounded
                # to candidate payloads and preserves the existing guarantee
                # that unrelated malformed legacy rows do not break a write.
                if not any(token in payload_json for token in target_tokens):
                    continue
                try:
                    record = MIRLRecord.from_dict(json.loads(payload_json))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    raise CanonicalReferenceIntegrityError(
                        "canonical payload cannot be reprojected"
                    ) from exc
                if reference_candidate_ids(record) & target_record_ids:
                    affected_ids.append(record_id)
            self._queue_reference_reprojection_ids(
                connection,
                affected_ids,
            )

    def _reproject_queued_reference_dependents(
        self,
        connection: sqlite3.Connection,
        *,
        preserve_node_vectors: bool = False,
    ) -> set[str]:
        provenance_targets: set[str] = set()
        # Reference endpoint typing is shared by every owner of a semantic
        # triple. Clear the complete queue before emitting any bounded slice;
        # otherwise a >batch-size virtual -> canonical promotion can encounter
        # stale owners in a later slice and fail halfway through reprojection.
        self._clear_queued_reference_edge_sources(connection)

        last_id = ""
        while True:
            rows = connection.execute(
                "select records.id, records.payload_json from ir_records records "
                f'join "{_REFERENCE_REPROJECTION_QUEUE}" queued '
                "on queued.record_id = records.id where records.id > ? "
                "order by records.id limit ?",
                (last_id, _REFERENCE_REPROJECTION_BATCH_SIZE),
            ).fetchall()
            if not rows:
                break
            records: list[MIRLRecord] = []
            for row in rows:
                try:
                    records.append(MIRLRecord.from_dict(json.loads(row[1])))
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
                    raise CanonicalReferenceIntegrityError(
                        "canonical payload cannot be reprojected"
                    ) from exc
            provenance_targets.update(
                str(record.attrs["entity"])
                for record in records
                if record.kind is RecordKind.PROV
                and isinstance(record.attrs.get("entity"), str)
                and str(record.attrs["entity"]).strip()
            )
            self._reproject_records(
                connection,
                records,
                preserve_node_vectors=preserve_node_vectors,
                clear_edge_sources=False,
                cleanup_orphan_edges=False,
            )
            last_id = str(rows[-1][0])
        self._delete_unowned_ir_edges(connection)
        return provenance_targets

    @staticmethod
    def _clear_queued_reference_edge_sources(
        connection: sqlite3.Connection,
    ) -> None:
        """Clear a temp-queued contributor set in bounded identifier slices."""

        last_id = ""
        while True:
            rows = connection.execute(
                f'select record_id from "{_REFERENCE_REPROJECTION_QUEUE}" '
                "where record_id > ? order by record_id limit ?",
                (last_id, _REFERENCE_REPROJECTION_BATCH_SIZE),
            ).fetchall()
            if not rows:
                break
            record_ids = [str(row[0]) for row in rows]
            placeholders = ",".join("?" for _ in record_ids)
            connection.execute(
                "delete from ir_edge_sources where source_record_id in "
                f"({placeholders})",
                record_ids,
            )
            last_id = record_ids[-1]

    @staticmethod
    def _drop_reference_reprojection_queue(
        connection: sqlite3.Connection,
    ) -> None:
        connection.execute(
            f'drop table if exists temp."{_REFERENCE_REPROJECTION_QUEUE}"'
        )

    def _persist_edges(
        self,
        connection: sqlite3.Connection,
        record: MIRLRecord,
        *,
        known_record_kinds: dict[str, RecordKind],
        validated_virtual_references: frozenset[str],
        clear: bool = True,
        emit: bool = True,
    ) -> None:
        # Ownership is independent of the projected source endpoint. Clearing
        # one canonical record must not erase a triple another record supports.
        if clear:
            connection.execute(
                "delete from ir_edge_sources where source_record_id = ?",
                (record.id,),
            )
        if not emit:
            return
        for edge in typed_ir_edges(
            record,
            known_record_kinds=known_record_kinds,
            validated_virtual_references=validated_virtual_references,
        ):
            edge_key = (edge.src.id, edge.edge_type, edge.dst.id)
            expected_types = (
                edge.src.endpoint_type.value,
                edge.dst.endpoint_type.value,
            )
            stored_types = connection.execute(
                "select src_ref_type, dst_ref_type from ir_edges "
                "where src_id = ? and edge_type = ? and dst_id = ?",
                edge_key,
            ).fetchone()
            if stored_types is None:
                connection.execute(
                    "insert into ir_edges "
                    "(src_id, src_ref_type, edge_type, dst_id, dst_ref_type) "
                    "values (?, ?, ?, ?, ?)",
                    (
                        edge.src.id,
                        *expected_types[:1],
                        edge.edge_type,
                        edge.dst.id,
                        *expected_types[1:],
                    ),
                )
            elif tuple(stored_types) != expected_types:
                contributor = connection.execute(
                    "select 1 from ir_edge_sources where src_id = ? "
                    "and edge_type = ? and dst_id = ? limit 1",
                    edge_key,
                ).fetchone()
                if contributor is not None:
                    raise RuntimeError(
                        "IR edge contributors disagree on endpoint types"
                    )
                # Reuse the semantic edge row when its complete owner set is
                # being reprojected. This preserves stable edge identity across
                # virtual/canonical transitions and compensating rollbacks.
                connection.execute(
                    "update ir_edges set src_ref_type = ?, dst_ref_type = ? "
                    "where src_id = ? and edge_type = ? and dst_id = ?",
                    (*expected_types, *edge_key),
                )
            connection.execute(
                "insert or ignore into ir_edge_sources "
                "(source_record_id, src_id, edge_type, dst_id) "
                "values (?, ?, ?, ?)",
                (record.id, edge.src.id, edge.edge_type, edge.dst.id),
            )

    @staticmethod
    def _delete_unowned_ir_edges(connection: sqlite3.Connection) -> None:
        connection.execute(
            "delete from ir_edges where not exists ("
            "select 1 from ir_edge_sources sources "
            "where sources.src_id = ir_edges.src_id "
            "and sources.edge_type = ir_edges.edge_type "
            "and sources.dst_id = ir_edges.dst_id)"
        )

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
        # SQLite does not guarantee row order without an explicit ORDER BY.
        # ``insert or replace`` can move an otherwise unrelated row to a new
        # rowid, so an unlimited load must be just as deterministic as a
        # paginated load. Requested-ID callers are restored to their explicit
        # input order below after this canonical database order is applied.
        query += " order by id"
        if limit is not None:
            query += " limit ? offset ?"
            params.extend([limit, offset])
        elif offset:
            query += " limit -1 offset ?"
            params.append(offset)
        with self._pool.checkout() as connection:
            rows = connection.execute(query, params).fetchall()
        records = [MIRLRecord.from_dict(json.loads(row["payload_json"])) for row in rows]
        if ids:
            by_id = {record.id: record for record in records}
            records = [by_id[record_id] for record_id in ids if record_id in by_id]
        return IRBatch(records)

    @staticmethod
    def _ordinary_read_eligible_ids(
        connection: sqlite3.Connection, record_ids: Iterable[str]
    ) -> set[str]:
        """Resolve transitive current eligibility without changing retention."""

        requested = {str(record_id) for record_id in record_ids}
        records: dict[str, MIRLRecord] = {}
        pending = set(requested)
        while pending:
            batch = sorted(pending)[:500]
            pending.difference_update(batch)
            placeholders = ",".join("?" for _ in batch)
            rows = connection.execute(
                "select payload_json from ir_records "
                f"where id in ({placeholders})",
                batch,
            ).fetchall()
            for row in rows:
                record = MIRLRecord.from_dict(json.loads(row["payload_json"]))
                if record.id in records:
                    continue
                records[record.id] = record
                pending.update(reference_candidate_ids(record) - records.keys())

        ineligible = {
            record_id
            for record_id, record in records.items()
            if record.status.value in CURRENT_EXCLUDED_STATUSES
        }
        changed = True
        while changed:
            changed = False
            for record_id, record in records.items():
                if record_id not in ineligible and reference_candidate_ids(record) & ineligible:
                    ineligible.add(record_id)
                    changed = True
        return requested & records.keys() - ineligible

    def ordinary_read_ir(
        self,
        ids: list[str] | None = None,
        ns: str | None = None,
        scope: str | None = None,
    ) -> IRBatch:
        """Return current records whose canonical support is also current."""

        batch = self.load_ir(ids=ids, ns=ns, scope=scope)
        with self._pool.checkout() as connection:
            eligible = self._ordinary_read_eligible_ids(
                connection, (record.id for record in batch.records)
            )
        return IRBatch([record for record in batch.records if record.id in eligible])

    @staticmethod
    def _vector_rows_on_connection(
        connection: sqlite3.Connection,
        record_ids: Iterable[str],
    ) -> tuple[tuple[object, ...], ...]:
        ordered_ids = sorted({str(record_id) for record_id in record_ids})
        rows: list[tuple[object, ...]] = []
        columns = ", ".join(_VECTOR_INDEX_COLUMNS)
        for offset in range(
            0,
            len(ordered_ids),
            _REFERENCE_REPROJECTION_BATCH_SIZE,
        ):
            chunk = ordered_ids[
                offset : offset + _REFERENCE_REPROJECTION_BATCH_SIZE
            ]
            placeholders = ",".join("?" for _ in chunk)
            rows.extend(
                tuple(row)
                for row in connection.execute(
                    f"select {columns} from vector_index where record_id in "
                    f"({placeholders}) order by record_id, model_name",
                    chunk,
                ).fetchall()
            )
        return tuple(rows)

    @retry_db_operation()
    def snapshot_vector_rows(
        self,
        record_ids: Iterable[str],
    ) -> tuple[tuple[object, ...], ...]:
        """Capture exact local vector rows for a pending runtime write."""

        with self._pool.checkout() as connection:
            return self._vector_rows_on_connection(connection, record_ids)

    @retry_db_operation()
    def cleanup_orphan_node_vectors(self) -> None:
        """Reap graph-vector rows only after a runtime projection succeeds."""

        with self._pool.checkout() as connection:
            remove_orphan_node_vectors(connection)
            connection.commit()

    @classmethod
    def _restore_vector_rows(
        cls,
        connection: sqlite3.Connection,
        record_ids: Sequence[str],
        previous_rows: Sequence[tuple[object, ...]],
    ) -> None:
        """Restore the local vector slice without rewriting unchanged rows."""

        touched = set(record_ids)
        expected: dict[tuple[object, object], tuple[object, ...]] = {}
        for row in previous_rows:
            if len(row) != len(_VECTOR_INDEX_COLUMNS) or str(row[0]) not in touched:
                raise ValueError("invalid vector rollback snapshot")
            key = (row[0], row[1])
            if key in expected:
                raise ValueError("invalid vector rollback snapshot")
            expected[key] = tuple(row)
        current_rows = cls._vector_rows_on_connection(connection, touched)
        current = {(row[0], row[1]): row for row in current_rows}
        removed_keys = sorted(set(current) - set(expected))
        if removed_keys:
            connection.executemany(
                "delete from vector_index where record_id = ? and model_name = ?",
                removed_keys,
            )
        changed_rows = [
            row
            for key, row in sorted(expected.items())
            if current.get(key) != row
        ]
        if changed_rows:
            placeholders = ", ".join("?" for _ in _VECTOR_INDEX_COLUMNS)
            updates = ", ".join(
                f"{column} = excluded.{column}"
                for column in _VECTOR_INDEX_COLUMNS[2:]
            )
            connection.executemany(
                "insert into vector_index ("
                + ", ".join(_VECTOR_INDEX_COLUMNS)
                + f") values ({placeholders}) "
                "on conflict(record_id, model_name) do update set "
                + updates,
                changed_rows,
            )

    @retry_db_operation()
    def delete_ir(self, ids: list[str], include_vectors: bool = True) -> None:
        if not ids:
            return
        delete_ids = sorted(set(ids))
        with self._pool.checkout() as connection:
            try:
                if not connection.in_transaction:
                    connection.execute("begin immediate")
                self._delete_ir_on_connection(
                    connection,
                    delete_ids,
                    include_vectors=include_vectors,
                )
                connection.commit()
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise

    def _delete_ir_on_connection(
        self,
        connection: sqlite3.Connection,
        delete_ids: Sequence[str],
        *,
        include_vectors: bool,
        preserve_node_vectors: bool = False,
    ) -> None:
        """Delete canonical rows and rebuild affected projections atomically."""

        ordered_delete_ids = sorted(set(delete_ids))
        if not ordered_delete_ids:
            return
        existing_delete_ids = set(
            stored_reference_kinds(connection, ordered_delete_ids)
        )
        try:
            validate_canonical_reference_payloads(
                connection,
                excluded_record_ids=ordered_delete_ids,
            )
        except (
            CanonicalReferenceIntegrityError,
            MigrationError,
            TypeError,
            ValueError,
        ):
            raise CanonicalReferenceIntegrityError(
                "delete would violate required canonical reference closure"
            ) from None

        self._reset_reference_reprojection_queue(connection)
        try:
            self._queue_reference_dependents(
                connection,
                target_record_ids=existing_delete_ids,
                excluded_source_ids=existing_delete_ids,
            )
            self._queue_reference_reprojection_ids(
                connection,
                self._stored_provenance_targets(
                    connection,
                    existing_delete_ids,
                ),
            )

            for offset in range(
                0,
                len(ordered_delete_ids),
                _REFERENCE_REPROJECTION_BATCH_SIZE,
            ):
                chunk = ordered_delete_ids[
                    offset : offset + _REFERENCE_REPROJECTION_BATCH_SIZE
                ]
                placeholders = ",".join("?" for _ in chunk)
                remove_knowledge_records(
                    connection,
                    chunk,
                    revalidate_identity_merges=False,
                )
                if not preserve_node_vectors:
                    connection.execute(
                        "delete from knowledge_node_vectors where node_id in "
                        f"({placeholders})",
                        chunk,
                    )
                connection.execute(
                    "delete from ir_edge_sources where source_record_id in "
                    f"({placeholders})",
                    chunk,
                )
                for table in (
                    "raw_docs",
                    "raw_spans",
                    "symbol_table",
                    "pack_store",
                    "prov_log",
                ):
                    connection.execute(
                        f'delete from "{table}" where id in ({placeholders})',
                        chunk,
                    )
                connection.execute(
                    "delete from projection_index where record_id in "
                    f"({placeholders})",
                    chunk,
                )
                if include_vectors:
                    connection.execute(
                        "delete from vector_index where record_id in "
                        f"({placeholders})",
                        chunk,
                    )
                connection.execute(
                    f"delete from ir_records where id in ({placeholders})",
                    chunk,
                )
            self._reproject_queued_reference_dependents(
                connection,
                preserve_node_vectors=preserve_node_vectors,
            )
            if not preserve_node_vectors:
                remove_orphan_node_vectors(connection)
            # Revalidate only after optional survivors have been reprojected and
            # final orphan cleanup has established the actual node set.
            apply_identity_merges(connection)
        finally:
            self._drop_reference_reprojection_queue(connection)

    @retry_db_operation()
    def restore_ir_after_failed_projection(
        self,
        previous: IRBatch,
        touched_ids: Sequence[str],
        *,
        previous_vector_rows: Sequence[tuple[object, ...]] = (),
        previous_public_memory_handle_rows: Sequence[tuple[object, ...]],
    ) -> None:
        """Restore one failed runtime write without a delete-then-reinsert gap.

        Existing records are overwritten with their prior canonical payloads
        before records introduced by the failed batch are removed. Both phases,
        including core/KG reprojection and optional-reference cleanup, share one
        SQLite write transaction.
        """

        ordered_touched_ids = sorted(set(touched_ids))
        previous_ids = {record.id for record in previous.records}
        introduced_ids = [
            record_id
            for record_id in ordered_touched_ids
            if record_id not in previous_ids
        ]
        with self._pool.checkout() as connection:
            try:
                if not connection.in_transaction:
                    connection.execute("begin immediate")
                if previous.records:
                    self._persist_ir_on_connection(
                    connection,
                    previous,
                    reconcile_entities=False,
                    preserve_node_vectors=True,
                )
                if introduced_ids:
                    self._delete_ir_on_connection(
                        connection,
                        introduced_ids,
                        include_vectors=True,
                        preserve_node_vectors=True,
                    )
                self._restore_vector_rows(
                    connection,
                    ordered_touched_ids,
                    previous_vector_rows,
                )
                restore_public_memory_handle_row_snapshot(
                    connection,
                    ordered_touched_ids,
                    previous_public_memory_handle_rows,
                )
                connection.commit()
            except Exception:
                if connection.in_transaction:
                    connection.rollback()
                raise

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
        semantic_seed_ids: list[str] | None = None,
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
                semantic_seed_ids=semantic_seed_ids,
            )

    def search_node_vectors(
        self,
        query_vector: list[float],
        model_name: str,
        *,
        ns: str | None = None,
        scope: str | None = None,
        limit: int = 20,
        min_score: float = 0.0,
    ) -> list[tuple[str, float]]:
        """Rank graph nodes by cosine against a precomputed query vector."""
        with self._pool.checkout() as connection:
            return search_graph_node_vectors(
                connection,
                query_vector,
                model_name,
                ns=ns,
                scope=scope,
                limit=limit,
                min_score=min_score,
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

    def pending_node_vectors(
        self,
        model_name: str,
        *,
        ns: str | None = None,
        scope: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, object]]:
        """Return graph nodes whose derived vector is missing, stale, or legacy."""
        with self._pool.checkout() as connection:
            return pending_graph_node_vectors(
                connection, model_name, ns=ns, scope=scope, limit=limit
            )

    def reusable_node_vectors(
        self,
        model_name: str,
        source_hashes: Iterable[str],
    ) -> dict[str, list[float]]:
        """Return existing vectors for these content hashes, ignoring ns/scope."""
        with self._pool.checkout() as connection:
            return reusable_graph_node_vectors(connection, model_name, source_hashes)

    def store_node_vectors(
        self,
        model_name: str,
        entries: Iterable[Mapping[str, object]],
    ) -> int:
        """Persist derived graph-node vectors for one embedding model."""
        with self._pool.checkout() as connection:
            written = store_graph_node_vectors(connection, model_name, entries)
            connection.commit()
            return written

    def node_vector_status(self, model_name: str) -> dict[str, object]:
        """Report node-vector coverage as a provider-free improvement signal."""
        with self._pool.checkout() as connection:
            return graph_node_vector_status(connection, model_name)

    @staticmethod
    def _current_graph_product_facts(
        connection: sqlite3.Connection,
        *,
        namespace: str,
        scope: str,
        max_facts: int,
    ) -> list[GraphProductFact]:
        """Resolve current, asserted graph edges into the bounded G4 core input."""

        if max_facts < 1:
            raise ValueError("max_facts must be positive")
        excluded = (
            Status.CONTRADICTED.value,
            Status.SUPERSEDED.value,
            Status.DEPRECATED.value,
            Status.DELETED_SOFT.value,
        )
        placeholders = ",".join("?" for _ in excluded)
        admitted_predicates = sorted(ADMITTED_RELATION_PREDICATES)
        admitted_placeholders = ",".join("?" for _ in admitted_predicates)
        rows = connection.execute(
            "select e.id, e.src_id, src.label as src_label, e.dst_id, "
            "dst.label as dst_label, e.predicate, e.source_record_id "
            "from knowledge_edges e "
            "join knowledge_nodes src on src.id = e.src_id "
            "join knowledge_nodes dst on dst.id = e.dst_id "
            "where e.ns = ? and e.scope = ? "
            "and e.edge_kind in ('semantic', 'causal', 'temporal') "
            f"and e.status not in ({placeholders}) "
            "and (e.expired_at is null or trim(e.expired_at) = '') "
            f"and src.status not in ({placeholders}) "
            f"and dst.status not in ({placeholders}) "
            "and (case when json_valid(e.properties_json) "
            "then json_extract(e.properties_json, '$.relation_id') end is null "
            f"or lower(trim(e.predicate)) in ({admitted_placeholders})) "
            "order by e.id limit ?",
            (
                namespace,
                scope,
                *excluded,
                *excluded,
                *excluded,
                *admitted_predicates,
                max_facts + 1,
            ),
        ).fetchall()
        if len(rows) > max_facts:
            raise ValueError(
                f"graph product rebuild exceeds max_facts={max_facts}"
            )

        from .knowledge_graph import assertable_record_ids

        allowed = assertable_record_ids(
            connection,
            (str(row["source_record_id"]) for row in rows),
            namespace=namespace,
            scope=scope,
        )
        facts: list[GraphProductFact] = []
        for row in rows:
            record_id = str(row["source_record_id"])
            if record_id not in allowed:
                continue
            episodes = connection.execute(
                "select distinct ep.id from knowledge_edge_episodes ee "
                "join knowledge_episodes ep on ep.id = ee.episode_id "
                "where ee.edge_id = ? and ep.ns = ? and ep.scope = ? "
                "and ep.status = 'active' order by ep.id",
                (str(row["id"]), namespace, scope),
            ).fetchall()
            episode_ids = tuple(str(episode["id"]) for episode in episodes)
            if not episode_ids:
                continue
            facts.append(
                GraphProductFact(
                    ns=namespace,
                    scope=scope,
                    record_id=record_id,
                    episode_ids=episode_ids,
                    subject_id=str(row["src_id"]),
                    subject_label=str(row["src_label"]),
                    predicate=str(row["predicate"]),
                    object_id=str(row["dst_id"]),
                    object_label=str(row["dst_label"]),
                    trust_state="supported",
                    current=True,
                )
            )
        return facts

    @retry_db_operation()
    def rebuild_graph_products(
        self,
        *,
        namespace: str,
        scope: str,
        max_facts: int = 10_000,
        min_observation_episodes: int = 2,
        max_sentences_per_product: int = 64,
    ) -> dict[str, object]:
        """Rebuild G4 products from the current trust-gated graph projection."""

        with self._pool.checkout() as connection:
            facts = self._current_graph_product_facts(
                connection,
                namespace=namespace,
                scope=scope,
                max_facts=max_facts,
            )
            result = rebuild_graph_product_rows(
                connection,
                namespace=namespace,
                scope=scope,
                facts=facts,
                max_facts=max_facts,
                min_observation_episodes=min_observation_episodes,
                max_sentences_per_product=max_sentences_per_product,
            )
            connection.commit()
            return result

    def graph_products(
        self,
        *,
        namespace: str,
        scope: str,
        kinds: list[str] | None = None,
        subject_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        """Read the latest complete G4 product snapshot for one boundary."""

        with self._pool.checkout() as connection:
            rows = read_graph_product_rows(
                connection,
                namespace=namespace,
                scope=scope,
                kinds=kinds,
                subject_id=subject_id,
                limit=limit,
            )
            return self._eligible_graph_product_rows(connection, rows)

    @classmethod
    def _eligible_graph_product_rows(
        cls, connection: sqlite3.Connection, rows: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        support = {
            str(record_id)
            for row in rows
            for sentence in row.get("sentences", [])
            if isinstance(sentence, dict)
            for record_id in sentence.get("supporting_record_ids", [])
        }
        eligible = cls._ordinary_read_eligible_ids(connection, support)
        return [
            row
            for row in rows
            if all(
                str(record_id) in eligible
                for sentence in row.get("sentences", [])
                if isinstance(sentence, dict)
                for record_id in sentence.get("supporting_record_ids", [])
            )
        ]

    def graph_product_history(
        self,
        *,
        namespace: str,
        scope: str,
        stable_key: str,
        limit: int = 100,
    ) -> list[dict[str, object]]:
        """Read immutable versions of one boundary-scoped G4 product."""

        with self._pool.checkout() as connection:
            rows = graph_product_history_rows(
                connection,
                namespace=namespace,
                scope=scope,
                stable_key=stable_key,
                limit=limit,
            )
            return self._eligible_graph_product_rows(connection, rows)

    def context_candidates(
        self,
        *,
        namespace: str,
        scope: str,
        max_candidates: int = 10_000,
    ) -> list[ContextCandidate]:
        """Resolve current canonical and G4 rows into bounded G5 inputs.

        The returned values remain disposable projections. Every item retains
        exact canonical MIRL record and graph-episode references; the
        storage-agnostic assembler rechecks boundaries, trust, time, and
        provenance before rendering.
        """

        if not isinstance(namespace, str) or not namespace.strip():
            raise ValueError("namespace must be a non-empty string")
        if not isinstance(scope, str) or not scope.strip():
            raise ValueError("scope must be a non-empty string")
        if max_candidates < 1 or max_candidates > 100_000:
            raise ValueError("max_candidates must be between 1 and 100000")
        ns = namespace.strip()
        selected_scope = scope.strip()
        excluded = (
            Status.CONTRADICTED.value,
            Status.SUPERSEDED.value,
            Status.DEPRECATED.value,
            Status.DELETED_SOFT.value,
        )
        placeholders = ",".join("?" for _ in excluded)

        with self._pool.checkout() as connection:
            candidates: list[ContextCandidate] = []
            facts = self._current_graph_product_facts(
                connection,
                namespace=ns,
                scope=selected_scope,
                max_facts=max_candidates,
            )
            fact_rows: dict[str, sqlite3.Row] = {}
            if facts:
                ids = sorted({fact.record_id for fact in facts})
                id_placeholders = ",".join("?" for _ in ids)
                fact_rows = {
                    str(row["id"]): row
                    for row in connection.execute(
                        "select id, t0, created_at, updated_at from ir_records "
                        f"where id in ({id_placeholders})",
                        ids,
                    ).fetchall()
                }
            for fact in facts:
                row = fact_rows.get(fact.record_id)
                if row is None:
                    continue
                occurred_at = _context_timestamp(
                    row["t0"], row["updated_at"], row["created_at"]
                )
                if occurred_at is None:
                    continue
                candidates.append(
                    ContextCandidate(
                        candidate_id=f"fact:{fact.record_id}",
                        kind="fact",
                        text=(
                            f"{fact.subject_label} "
                            f"{fact.predicate.replace('_', ' ')} "
                            f"{fact.object_label}."
                        ),
                        namespace=ns,
                        scope=selected_scope,
                        trust_state=fact.trust_state,
                        record_ids=(fact.record_id,),
                        episode_ids=fact.episode_ids,
                        occurred_at=occurred_at,
                        entity_ids=tuple(
                            item
                            for item in (fact.subject_id, fact.object_id)
                            if item
                        ),
                    )
                )

            entity_rows = connection.execute(
                "select n.id, n.label, n.source_record_id, n.valid_from, "
                "n.created_at, group_concat(distinct ep.id) as episode_ids "
                "from knowledge_nodes n "
                "join knowledge_node_episodes ne on ne.node_id = n.id "
                "join knowledge_episodes ep on ep.id = ne.episode_id "
                "where n.ns = ? and n.scope = ? "
                "and n.kind in ('entity', 'value', 'agent') "
                f"and n.status not in ({placeholders}) "
                "and ep.ns = ? and ep.scope = ? and ep.status = 'active' "
                "and n.source_record_id is not null "
                "group by n.id, n.label, n.source_record_id, n.valid_from, n.created_at "
                "order by n.id limit ?",
                (
                    ns,
                    selected_scope,
                    *excluded,
                    ns,
                    selected_scope,
                    max_candidates + 1,
                ),
            ).fetchall()
            for row in entity_rows:
                occurred_at = _context_timestamp(
                    row["valid_from"], row["created_at"]
                )
                episode_ids = tuple(
                    sorted(
                        item
                        for item in str(row["episode_ids"] or "").split(",")
                        if item
                    )
                )
                if not episode_ids or occurred_at is None:
                    continue
                candidates.append(
                    ContextCandidate(
                        candidate_id=f"entity:{row['id']}",
                        kind="entity",
                        text=str(row["label"]),
                        namespace=ns,
                        scope=selected_scope,
                        trust_state="supported",
                        record_ids=(str(row["source_record_id"]),),
                        episode_ids=episode_ids,
                        occurred_at=occurred_at,
                        entity_ids=(str(row["id"]),),
                    )
                )

            episode_rows = connection.execute(
                "select ep.id, ep.source_record_id, ep.valid_at, ep.recorded_at, "
                "raw.content from knowledge_episodes ep "
                "join raw_docs raw on raw.id = ep.source_record_id "
                "where ep.ns = ? and ep.scope = ? and ep.status = 'active' "
                "order by ep.id limit ?",
                (ns, selected_scope, max_candidates + 1),
            ).fetchall()
            for row in episode_rows:
                occurred_at = _context_timestamp(
                    row["valid_at"], row["recorded_at"]
                )
                if occurred_at is None:
                    continue
                candidates.append(
                    ContextCandidate(
                        candidate_id=str(row["id"]),
                        kind="episode",
                        text=str(row["content"]),
                        namespace=ns,
                        scope=selected_scope,
                        trust_state="supported",
                        record_ids=(str(row["source_record_id"]),),
                        episode_ids=(str(row["id"]),),
                        occurred_at=occurred_at,
                    )
                )

            products = read_graph_product_rows(
                connection,
                namespace=ns,
                scope=selected_scope,
                limit=min(max_candidates, 1_000),
            )
            for product in products:
                occurred_at = _context_timestamp(product["created_at"])
                if occurred_at is None:
                    continue
                product_id = str(product["product_id"])
                kind = str(product["kind"])
                subject_id = product.get("subject_id")
                for sentence in product["sentences"]:  # type: ignore[union-attr]
                    sentence_row = sentence  # type: ignore[assignment]
                    candidates.append(
                        ContextCandidate(
                            candidate_id=str(sentence_row["sentence_id"]),
                            kind=kind,
                            text=str(sentence_row["text"]),
                            namespace=ns,
                            scope=selected_scope,
                            trust_state="supported",
                            record_ids=tuple(
                                str(item)
                                for item in sentence_row[
                                    "supporting_record_ids"
                                ]
                            ),
                            episode_ids=tuple(
                                str(item)
                                for item in sentence_row[
                                    "supporting_episode_ids"
                                ]
                            ),
                            occurred_at=occurred_at,
                            entity_ids=(
                                (str(subject_id),)
                                if subject_id is not None
                                else ()
                            ),
                            product_id=product_id,
                        )
                    )

        with self._pool.checkout() as connection:
            current_record_ids = _current_context_record_ids(
                connection,
                {
                    record_id
                    for candidate in candidates
                    for record_id in candidate.record_ids
                },
            )
        candidates = [
            candidate
            for candidate in candidates
            if set(candidate.record_ids) <= current_record_ids
        ]
        if len(candidates) > max_candidates:
            raise ValueError(
                f"context candidate projection exceeds max_candidates={max_candidates}"
            )
        return sorted(candidates, key=lambda item: item.candidate_id)

    @retry_db_operation()
    def plan_scoped_delete(
        self,
        *,
        tenant_id: str,
        namespace: str,
        scope: str,
        record_ids: Iterable[str],
        idempotency_key: str,
        actor: str,
        idempotency_context: str | None = None,
        record_generations: Mapping[str, str] | None = None,
    ) -> dict[str, object]:
        with self._pool.checkout() as connection:
            return plan_scoped_delete(
                connection,
                tenant_id=tenant_id,
                namespace=namespace,
                scope=scope,
                record_ids=record_ids,
                idempotency_key=idempotency_key,
                actor=actor,
                idempotency_context=idempotency_context,
                record_generations=record_generations,
            )

    @retry_db_operation()
    def apply_scoped_delete(
        self,
        *,
        tenant_id: str,
        operation_id: str,
        actor: str,
        interrupt_after_intent: bool = False,
        delete_derived_records: Callable[[tuple[str, ...]], None] | None = None,
        require_current_incarnation: bool = False,
    ) -> dict[str, object]:
        with self._pool.checkout() as connection:
            return apply_scoped_delete(
                connection,
                tenant_id=tenant_id,
                operation_id=operation_id,
                actor=actor,
                interrupt_after_intent=interrupt_after_intent,
                delete_derived_records=delete_derived_records,
                rebuild_current_graph_products=self._rebuild_graph_products_on_connection,
                require_current_incarnation=require_current_incarnation,
            )

    def _rebuild_graph_products_on_connection(
        self, connection: sqlite3.Connection, namespace: str, scope: str
    ) -> None:
        facts = self._current_graph_product_facts(
            connection, namespace=namespace, scope=scope, max_facts=10_000
        )
        rebuild_graph_product_rows(
            connection,
            namespace=namespace,
            scope=scope,
            facts=facts,
            max_facts=10_000,
            min_observation_episodes=2,
            max_sentences_per_product=64,
        )

    @retry_db_operation()
    def plan_batch_ingest(
        self,
        *,
        tenant_id: str,
        namespace: str,
        scope: str,
        items: Sequence[BatchIngestItem],
        idempotency_key: str,
        actor: str,
    ) -> dict[str, object]:
        with self._pool.checkout() as connection:
            return plan_batch_ingest(
                connection,
                tenant_id=tenant_id,
                namespace=namespace,
                scope=scope,
                items=items,
                idempotency_key=idempotency_key,
                actor=actor,
            )

    @retry_db_operation()
    def begin_batch_ingest(
        self, *, tenant_id: str, operation_id: str, actor: str
    ) -> dict[str, object]:
        with self._pool.checkout() as connection:
            return begin_batch_ingest(
                connection,
                tenant_id=tenant_id,
                operation_id=operation_id,
                actor=actor,
            )

    @retry_db_operation()
    def record_batch_item(
        self,
        *,
        tenant_id: str,
        operation_id: str,
        item_index: int,
        stored_ids: Iterable[str],
        actor: str,
    ) -> dict[str, object]:
        with self._pool.checkout() as connection:
            return record_batch_item(
                connection,
                tenant_id=tenant_id,
                operation_id=operation_id,
                item_index=item_index,
                stored_ids=stored_ids,
                actor=actor,
            )

    @retry_db_operation()
    def complete_batch_ingest(
        self, *, tenant_id: str, operation_id: str, actor: str
    ) -> dict[str, object]:
        with self._pool.checkout() as connection:
            return complete_batch_ingest(
                connection,
                tenant_id=tenant_id,
                operation_id=operation_id,
                actor=actor,
            )

    def completed_batch_indexes(
        self, *, tenant_id: str, operation_id: str
    ) -> tuple[int, ...]:
        with self._pool.checkout() as connection:
            return completed_batch_indexes(
                connection,
                tenant_id=tenant_id,
                operation_id=operation_id,
            )

    def lifecycle_batch_items(
        self, *, tenant_id: str, operation_id: str
    ) -> tuple[BatchIngestItem, ...]:
        with self._pool.checkout() as connection:
            return batch_ingest_items(
                connection,
                tenant_id=tenant_id,
                operation_id=operation_id,
            )

    def lifecycle_operation(
        self, *, tenant_id: str, operation_id: str
    ) -> dict[str, object]:
        with self._pool.checkout() as connection:
            return get_lifecycle_operation(
                connection,
                tenant_id=tenant_id,
                operation_id=operation_id,
            )

    def lifecycle_operation_by_idempotency_key(
        self, *, tenant_id: str, idempotency_key: str
    ) -> dict[str, object] | None:
        with self._pool.checkout() as connection:
            return get_lifecycle_operation_by_idempotency_key(
                connection,
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
            )

    def scoped_delete_retry_matches_current_incarnation(
        self, *, tenant_id: str, operation_id: str
    ) -> bool:
        with self._pool.checkout() as connection:
            return scoped_delete_retry_matches_current_incarnation(
                connection,
                tenant_id=tenant_id,
                operation_id=operation_id,
            )

    def recoverable_lifecycle_operations(
        self, *, tenant_id: str, limit: int = 100
    ) -> list[dict[str, object]]:
        with self._pool.checkout() as connection:
            return recoverable_operations(
                connection, tenant_id=tenant_id, limit=limit
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
            rows = list_identity_merges(
                connection, ns=ns, scope=scope, statuses=statuses
            )
            return self._ordinary_identity_rows(connection, rows)

    @classmethod
    def _ordinary_identity_rows(
        cls,
        connection: sqlite3.Connection,
        rows: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        touched = {
            str(row[key])
            for row in rows
            for key in ("canonical_node_id", "alias_node_id")
        }
        if not touched:
            return []
        eligible = cls._ordinary_read_eligible_ids(connection, touched)
        placeholders = ",".join("?" for _ in touched)
        present = {
            str(row["id"])
            for row in connection.execute(
                f"select id from ir_records where id in ({placeholders})",
                sorted(touched),
            ).fetchall()
        }
        visible: list[dict[str, object]] = []
        for row in rows:
            endpoints = {
                str(row["canonical_node_id"]),
                str(row["alias_node_id"]),
            }
            if endpoints <= eligible or (
                str(row["status"]) == "conflict"
                and all(endpoint in eligible or endpoint not in present for endpoint in endpoints)
            ):
                visible.append(row)
        return visible

    def identity_merge_audit(self, node_id: str) -> list[dict[str, object]]:
        """Every merge touching ``node_id`` (any status) plus its evidence."""
        with self._pool.checkout() as connection:
            present = connection.execute(
                "select 1 from ir_records where id = ?", (node_id,)
            ).fetchone()
            if present is not None and node_id not in self._ordinary_read_eligible_ids(
                connection, [node_id]
            ):
                return []
            rows = identity_merge_audit_detail(connection, node_id)
            return self._ordinary_identity_rows(connection, rows)

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
        batch = self.ordinary_read_ir(ids=[pack_id])
        if not batch.records:
            raise KeyError(pack_id)
        record = batch.records[0]
        if record.kind != RecordKind.PACK:
            raise KeyError(pack_id)
        pack = Pack.from_record(record)
        if pack.refs:
            referenced = self.load_ir(ids=pack.refs).by_id()
            if len(referenced) != len(set(pack.refs)) or any(
                referenced.get(record_id) is None
                or referenced[record_id].status is Status.DELETED_SOFT
                for record_id in pack.refs
            ):
                # PACK is disposable derived state. Keep the stored artifact
                # for audit, but refuse an ordinary read once any exact support
                # has become lifecycle-ineligible.
                raise KeyError(pack_id)
        return pack

    def trace(self, root_id: str) -> TraceGraph:
        with self._pool.checkout() as connection:
            root = _load_record_by_id(connection, root_id)
            if root is None or root_id not in self._ordinary_read_eligible_ids(connection, [root_id]):
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
                    "where (src_id = ? or dst_id = ?) "
                    "and (expired_at is null or trim(expired_at) = '') "
                    "and status not in ('contradicted','superseded','deprecated','deleted_soft') "
                    "order by id",
                    (current, current),
                ).fetchall()
                for row in edge_rows:
                    neighbor = row["dst_id"] if row["src_id"] == current else row["src_id"]
                    refs.append((row["src_id"], row["predicate"], row["dst_id"], neighbor))
                for src, edge_type, dst, neighbor in dict.fromkeys(refs):
                    target = _load_record_by_id(connection, neighbor)
                    if target is not None and neighbor not in self._ordinary_read_eligible_ids(connection, [neighbor]):
                        continue
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

    def reasoning_patterns(
        self,
        *,
        objective: str,
        ns: str,
        scope: str,
        operation: str | None = None,
        limit: int = 5,
        max_age_days: int = 90,
        min_trust: float = 0.5,
        now: str | None = None,
    ) -> list[dict[str, object]]:
        """Retrieve reusable verified reasoning structures (R4)."""

        with self._pool.checkout() as connection:
            return search_reasoning_patterns(
                connection,
                objective=objective,
                ns=ns,
                scope=scope,
                operation=operation,
                limit=limit,
                max_age_days=max_age_days,
                min_trust=min_trust,
                now=now,
            )

    def reasoning_pattern(self, pattern_id: str) -> dict[str, object]:
        with self._pool.checkout() as connection:
            return get_reasoning_pattern(connection, pattern_id)

    @retry_db_operation()
    def use_reasoning_pattern(
        self, *, pattern_id: str, run_id: str
    ) -> dict[str, object]:
        with self._pool.checkout() as connection:
            result = use_reasoning_pattern(
                connection, pattern_id=pattern_id, run_id=run_id
            )
            connection.commit()
        return result

    @retry_db_operation()
    def record_reasoning_pattern_feedback(
        self,
        *,
        use_id: str,
        expected_run_id: str,
        succeeded: bool,
        outcome_node_id: str | None = None,
        reason: str | None = None,
    ) -> dict[str, object]:
        with self._pool.checkout() as connection:
            result = record_reasoning_pattern_result(
                connection,
                use_id=use_id,
                expected_run_id=expected_run_id,
                succeeded=succeeded,
                outcome_node_id=outcome_node_id,
                reason=reason,
            )
            connection.commit()
        return result

    @retry_db_operation()
    def propose_reasoning_promotion(
        self,
        *,
        run_id: str,
        outcome_node_id: str,
        assertion_record_id: str,
        assertion_subject: str,
        assertion_predicate: str,
        assertion_object: object,
        proposed_by: str,
        assertion_status: str = "inferred",
        assertion_confidence: float = 1.0,
        assertion_t0: str | None = None,
        assertion_t1: str | None = None,
    ) -> dict[str, object]:
        """Append an R5 proposal; this never promotes itself into MIRL."""

        with self._pool.checkout() as connection:
            result = propose_reasoning_promotion_row(
                connection,
                run_id=run_id,
                outcome_node_id=outcome_node_id,
                assertion_record_id=assertion_record_id,
                assertion_subject=assertion_subject,
                assertion_predicate=assertion_predicate,
                assertion_object=assertion_object,
                assertion_status=assertion_status,
                assertion_confidence=assertion_confidence,
                assertion_t0=assertion_t0,
                assertion_t1=assertion_t1,
                proposed_by=proposed_by,
            )
            connection.commit()
            return result

    @retry_db_operation()
    def review_reasoning_promotion(
        self,
        *,
        proposal_id: str,
        review_kind: str,
        decision: str,
        reviewer_id: str,
        rationale: str,
    ) -> dict[str, object]:
        """Append a separate human or policy decision to an R5 proposal."""

        with self._pool.checkout() as connection:
            result = review_reasoning_promotion_row(
                connection,
                proposal_id=proposal_id,
                review_kind=review_kind,
                decision=decision,
                reviewer_id=reviewer_id,
                rationale=rationale,
            )
            connection.commit()
            return result

    def reasoning_promotion_eligibility(
        self, proposal_id: str
    ) -> dict[str, object]:
        """Recheck approval and exact provenance without mutating truth."""

        with self._pool.checkout() as connection:
            return reasoning_promotion_eligibility_row(connection, proposal_id)

    def reasoning_promotion(self, proposal_id: str) -> dict[str, object]:
        with self._pool.checkout() as connection:
            return get_reasoning_promotion_row(connection, proposal_id)

    def reasoning_promotions(
        self, *, ns: str, scope: str, limit: int = 50
    ) -> list[dict[str, object]]:
        with self._pool.checkout() as connection:
            return list_reasoning_promotion_rows(
                connection, ns=ns, scope=scope, limit=limit
            )

    @retry_db_operation()
    def apply_reasoning_promotion(
        self, *, proposal_id: str, applied_by: str
    ) -> dict[str, object]:
        """Atomically revalidate, persist, and audit one approved R5 assertion."""

        from .verify import verify_ir

        with self._pool.checkout() as connection:
            connection.execute("begin immediate")
            eligibility = reasoning_promotion_eligibility_row(
                connection, proposal_id
            )
            if not eligibility["eligible"]:
                raise ValueError(
                    "reasoning promotion is not eligible: "
                    f"{eligibility['reason']}"
                )
            payload = eligibility.get("approved_assertion")
            if not isinstance(payload, dict):
                raise ValueError(
                    "eligible promotion did not return an approved assertion"
                )
            record = MIRLRecord.from_dict(payload)
            batch = IRBatch([record])
            verification_records = self._promotion_reference_records(
                connection, record
            )
            report = verify_ir(IRBatch([*verification_records, record]))
            if not report.valid:
                raise ValueError(
                    "approved promotion assertion is not valid MIRL: "
                    + json.dumps(report.to_dict(), sort_keys=True)
                )
            stored_ids = self._persist_ir_on_connection(connection, batch)
            if stored_ids != [record.id]:
                raise ValueError(
                    "approved promotion did not persist its exact assertion id"
                )
            application = record_reasoning_promotion_application(
                connection,
                proposal_id=proposal_id,
                assertion_record_id=record.id,
                applied_by=applied_by,
            )
            connection.commit()
        return {
            "proposal_id": proposal_id,
            "application": application,
            "record": record.to_dict(),
            "stored_ids": stored_ids,
        }

    @retry_db_operation()
    def reverse_reasoning_promotion(
        self, *, proposal_id: str, reversed_by: str, reason: str
    ) -> dict[str, object]:
        """Append an R5 reversal plus an additive MIRL supersession relation."""

        from .verify import verify_ir

        with self._pool.checkout() as connection:
            connection.execute("begin immediate")
            promotion = get_reasoning_promotion_row(connection, proposal_id)
            reversal = reverse_reasoning_promotion_row(
                connection,
                proposal_id=proposal_id,
                reversed_by=reversed_by,
                reason=reason,
            )
            assertion_id = str(reversal["assertion_record_id"])
            relation_id = (
                "rel:reasoning-promotion-reversal:"
                + hashlib.sha256(proposal_id.encode("utf-8")).hexdigest()[:20]
            )
            evidence_fingerprints = promotion.get(
                "evidence_fingerprints", {}
            )
            evidence_ids = (
                sorted(str(item) for item in evidence_fingerprints)
                if isinstance(evidence_fingerprints, dict)
                else []
            )
            record = MIRLRecord(
                id=relation_id,
                kind=RecordKind.REL,
                ns=str(promotion["ns"]),
                scope=str(promotion["scope"]),
                status=Status.ASSERTED,
                conf=1.0,
                prov=[],
                evidence=self._promotion_evidence_ids(
                    connection, evidence_ids
                ),
                ext={
                    "reasoning_promotion_proposal_id": proposal_id,
                    "reasoning_promotion_reversal_id": str(
                        reversal["reversal_id"]
                    ),
                    "reasoning_promotion_audit_refs": [
                        f"reasoning-promotion:{proposal_id}",
                        "reasoning-promotion-reversal:"
                        f"{reversal['reversal_id']}",
                    ],
                    "supersedes": [assertion_id],
                },
                attrs={
                    "src": relation_id,
                    "predicate": "supersedes",
                    "dst": assertion_id,
                    "reason": str(reversal["reason"]),
                },
            )
            verification_records = self._promotion_reference_records(
                connection, record
            )
            report = verify_ir(IRBatch([*verification_records, record]))
            if not report.valid:
                raise ValueError(
                    "promotion reversal relation is not valid MIRL: "
                    + json.dumps(report.to_dict(), sort_keys=True)
                )
            self._persist_ir_on_connection(connection, IRBatch([record]))
            connection.commit()
            return {
                **reversal,
                "superseding_record": record.to_dict(),
            }

    @staticmethod
    def _promotion_evidence_ids(
        connection: sqlite3.Connection, record_ids: list[str]
    ) -> list[str]:
        """Keep canonical MIRL evidence limited to existing RAW/SPAN records."""

        evidence_ids: list[str] = []
        for record_id in sorted(set(record_ids)):
            row = connection.execute(
                "select kind from ir_records where id = ?", (record_id,)
            ).fetchone()
            if row is not None and str(row["kind"]) in {
                RecordKind.RAW.value,
                RecordKind.SPAN.value,
            }:
                evidence_ids.append(record_id)
        return evidence_ids

    @staticmethod
    def _promotion_reference_records(
        connection: sqlite3.Connection, record: MIRLRecord
    ) -> list[MIRLRecord]:
        """Load exact stored MIRL references for in-transaction verification."""

        reference_ids = sorted(set([*record.prov, *record.evidence]))
        records: list[MIRLRecord] = []
        for record_id in reference_ids:
            row = connection.execute(
                "select payload_json from ir_records where id = ?",
                (record_id,),
            ).fetchone()
            if row is None:
                raise ValueError(
                    f"promotion MIRL reference is missing: {record_id}"
                )
            records.append(MIRLRecord.from_dict(json.loads(str(row[0]))))
        return records

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
        leg_weights: Mapping[str, float] | None = None,
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
                leg_weights=leg_weights,
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
        resolved_verification_ids = tuple(verification_ids)
        with self._pool.checkout() as connection:
            outcome = finalize_verified_reasoning_outcome(
                connection,
                run_id=run_id,
                summary=summary,
                verification_ids=resolved_verification_ids,
                confidence=confidence,
                knowledge_refs=knowledge_refs,
                evidence_record_ids=evidence_record_ids,
                supporting_node_ids=supporting_node_ids,
                agent_id=agent_id,
            )
            connection.commit()
            # Pattern learning is derived state. A failure here must never roll
            # back or invalidate a verified outcome; it remains recoverable from
            # the append-only source run on a later pass.
            try:
                pattern = distill_reasoning_pattern(
                    connection,
                    run_id=run_id,
                    outcome_node_id=str(outcome["node_id"]),
                    verification_ids=resolved_verification_ids,
                )
                feedback = record_successful_pattern_uses(
                    connection,
                    run_id=run_id,
                    outcome_node_id=str(outcome["node_id"]),
                )
                connection.commit()
                outcome["learned_pattern_id"] = pattern["pattern_id"]
                outcome["pattern_feedback_count"] = len(feedback)
            except Exception:
                connection.rollback()
                LOGGER.exception(
                    "Reasoning pattern learning failed; verified outcome remains committed"
                )
                outcome["pattern_learning_pending"] = True
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
    # H2 production experiment ledger
    # ------------------------------------------------------------------

    @retry_db_operation()
    def create_improvement_experiment(
        self,
        *,
        lane: str,
        evaluator_sha256: str,
        dataset_sha256: str,
        baseline_sha256: str,
        definition: Mapping[str, object],
        experiment_id: str | None = None,
        method: str = EXPERIMENT_METHOD,
        created_at: str | None = None,
    ) -> str:
        """Create one immutable experiment definition and its first event."""

        if not isinstance(lane, str) or not lane.strip():
            raise ValueError("experiment lane is required")
        if not isinstance(method, str) or not method.strip():
            raise ValueError("experiment method is required")
        evaluator_sha256 = validate_sha256(
            evaluator_sha256, field_name="evaluator_sha256"
        )
        dataset_sha256 = validate_sha256(
            dataset_sha256, field_name="dataset_sha256"
        )
        baseline_sha256 = validate_sha256(
            baseline_sha256, field_name="baseline_sha256"
        )
        normalized_definition = validate_structured_payload(
            definition, field_name="experiment definition"
        )
        resolved_id = validate_experiment_id(
            experiment_id or f"improve:{uuid4().hex}"
        )
        now = created_at or utc_now()
        lane = lane.strip()
        method = method.strip()
        definition_sha256 = experiment_definition_sha256(
            experiment_id=resolved_id,
            created_at=now,
            contract_version=EXPERIMENT_CONTRACT_VERSION,
            lane=lane,
            method=method,
            evaluator_sha256=evaluator_sha256,
            dataset_sha256=dataset_sha256,
            baseline_sha256=baseline_sha256,
            definition=normalized_definition,
        )
        started_payload = {
            "contract_version": EXPERIMENT_CONTRACT_VERSION,
            "definition_sha256": definition_sha256,
            "schema_version": EXPERIMENT_SCHEMA_VERSION,
        }
        first_event_sha256 = improvement_event_sha256(
            experiment_id=resolved_id,
            sequence=1,
            ts=now,
            event_kind="started",
            payload=started_payload,
            previous_event_sha256=None,
        )
        with self._pool.checkout() as connection:
            connection.execute("begin immediate")
            try:
                connection.execute(
                    """
                    insert into improvement_experiment (
                        experiment_id, created_at, contract_version, lane, method,
                        evaluator_sha256, dataset_sha256, baseline_sha256,
                        definition_json, definition_sha256
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resolved_id,
                        now,
                        EXPERIMENT_CONTRACT_VERSION,
                        lane,
                        method,
                        evaluator_sha256,
                        dataset_sha256,
                        baseline_sha256,
                        canonical_experiment_json(normalized_definition),
                        definition_sha256,
                    ),
                )
                connection.execute(
                    """
                    insert into improvement_experiment_event (
                        experiment_id, sequence, ts, event_kind, payload_json,
                        previous_event_sha256, event_sha256
                    ) values (?, 1, ?, 'started', ?, NULL, ?)
                    """,
                    (
                        resolved_id,
                        now,
                        canonical_experiment_json(started_payload),
                        first_event_sha256,
                    ),
                )
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        self._verified_improvement_heads[resolved_id] = (1, first_event_sha256)
        return resolved_id

    @retry_db_operation()
    def append_improvement_experiment_event(
        self,
        *,
        experiment_id: str,
        event_kind: str,
        payload: Mapping[str, object],
        ts: str | None = None,
    ) -> int:
        """Append one transition after validating the chain and state machine."""

        resolved_id = validate_experiment_id(experiment_id)
        if event_kind not in EXPERIMENT_EVENT_KINDS or event_kind == "started":
            raise ValueError(f"invalid append-only experiment event {event_kind!r}")
        normalized_payload = validate_structured_payload(
            payload, field_name=f"{event_kind} payload"
        )
        now = ts or utc_now()
        with self._pool.checkout() as connection:
            connection.execute("begin immediate")
            try:
                experiment = connection.execute(
                    "select * from improvement_experiment where experiment_id = ?",
                    (resolved_id,),
                ).fetchone()
                if experiment is None:
                    raise ValueError(f"experiment {resolved_id!r} does not exist")
                previous = connection.execute(
                    """
                    select * from improvement_experiment_event
                    where experiment_id = ? order by sequence desc limit 1
                    """,
                    (resolved_id,),
                ).fetchone()
                if previous is None:
                    raise ValueError("experiment event chain is invalid: no events")
                definition_errors = _improvement_experiment_definition_errors(
                    experiment
                )
                if definition_errors:
                    raise ValueError(
                        "experiment event chain is invalid: "
                        + "; ".join(definition_errors)
                    )
                previous_sequence = int(previous["sequence"])
                previous_sha256 = str(previous["event_sha256"])
                cached_head = self._verified_improvement_heads.get(resolved_id)
                if cached_head != (previous_sequence, previous_sha256):
                    rows = connection.execute(
                        """
                        select * from improvement_experiment_event
                        where experiment_id = ? order by sequence asc
                        """,
                        (resolved_id,),
                    ).fetchall()
                    chain_errors = _improvement_experiment_chain_errors(
                        experiment, rows
                    )
                    if chain_errors:
                        raise ValueError(
                            "experiment event chain is invalid: "
                            + "; ".join(chain_errors)
                        )
                    self._verified_improvement_heads[resolved_id] = (
                        previous_sequence,
                        previous_sha256,
                    )
                else:
                    tail_errors = _improvement_experiment_event_row_errors(
                        experiment, previous
                    )
                    if tail_errors:
                        raise ValueError(
                            "experiment event chain is invalid: "
                            + "; ".join(tail_errors)
                        )
                previous_kind = str(previous["event_kind"])
                _validate_improvement_experiment_transition(previous_kind, event_kind)
                sequence = previous_sequence + 1
                digest = improvement_event_sha256(
                    experiment_id=resolved_id,
                    sequence=sequence,
                    ts=now,
                    event_kind=event_kind,
                    payload=normalized_payload,
                    previous_event_sha256=previous_sha256,
                )
                cursor = connection.execute(
                    """
                    insert into improvement_experiment_event (
                        experiment_id, sequence, ts, event_kind, payload_json,
                        previous_event_sha256, event_sha256
                    ) values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        resolved_id,
                        sequence,
                        now,
                        event_kind,
                        canonical_experiment_json(normalized_payload),
                        previous_sha256,
                        digest,
                    ),
                )
                event_id = int(cursor.lastrowid)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
        self._verified_improvement_heads[resolved_id] = (sequence, digest)
        return event_id

    def read_improvement_experiment(
        self, experiment_id: str
    ) -> dict[str, object] | None:
        """Read one definition and its complete event chain."""

        resolved_id = validate_experiment_id(experiment_id)
        with self._pool.checkout() as connection:
            row = connection.execute(
                "select * from improvement_experiment where experiment_id = ?",
                (resolved_id,),
            ).fetchone()
            if row is None:
                return None
            event_rows = connection.execute(
                """
                select * from improvement_experiment_event
                where experiment_id = ? order by sequence asc
                """,
                (resolved_id,),
            ).fetchall()
        payload = experiment_row(row)
        events = [experiment_event_row(event) for event in event_rows]
        payload["events"] = events
        payload["status"] = _improvement_experiment_status(events)
        return payload

    def iter_improvement_experiments(
        self,
        *,
        lane: str | None = None,
        status: str | None = None,
        limit: int | None = 50,
    ) -> list[dict[str, object]]:
        """List immutable experiment definitions newest-first."""

        if limit is not None and (isinstance(limit, bool) or limit < 1):
            raise ValueError("experiment list limit must be positive")
        if status not in {None, "running", "completed", "failed"}:
            raise ValueError("experiment status must be running, completed, or failed")
        clauses: list[str] = []
        params: list[object] = []
        if lane is not None:
            clauses.append("x.lane = ?")
            params.append(lane)
        if status == "running":
            clauses.append("e.event_kind not in ('completed', 'failed')")
        elif status is not None:
            clauses.append("e.event_kind = ?")
            params.append(status)
        where = " where " + " and ".join(clauses) if clauses else ""
        sql = f"""
            with latest as (
                select experiment_id, max(sequence) as sequence, count(*) as event_count
                from improvement_experiment_event
                group by experiment_id
            )
            select x.*, e.event_kind as latest_event_kind,
                   e.ts as latest_event_ts, latest.event_count
            from improvement_experiment x
            join latest on latest.experiment_id = x.experiment_id
            join improvement_experiment_event e
              on e.experiment_id = latest.experiment_id
             and e.sequence = latest.sequence
            {where}
            order by x.created_at desc, x.experiment_id desc
        """
        if limit is not None:
            sql += " limit ?"
            params.append(int(limit))
        with self._pool.checkout() as connection:
            rows = connection.execute(sql, tuple(params)).fetchall()
        experiments: list[dict[str, object]] = []
        for row in rows:
            latest_kind = str(row["latest_event_kind"])
            current_status = (
                latest_kind
                if latest_kind in TERMINAL_EXPERIMENT_EVENT_KINDS
                else "running"
            )
            item = experiment_row(row)
            item.update(
                {
                    "status": current_status,
                    "latest_event_kind": latest_kind,
                    "latest_event_ts": row["latest_event_ts"],
                    "event_count": int(row["event_count"]),
                }
            )
            experiments.append(item)
        return experiments

    def verify_improvement_experiment(
        self, experiment_id: str
    ) -> dict[str, object]:
        """Recompute definition and chained event hashes content-free."""

        resolved_id = validate_experiment_id(experiment_id)
        with self._pool.checkout() as connection:
            row = connection.execute(
                "select * from improvement_experiment where experiment_id = ?",
                (resolved_id,),
            ).fetchone()
            if row is None:
                return {
                    "experiment_id": resolved_id,
                    "valid": False,
                    "event_count": 0,
                    "status": "invalid",
                    "errors": ["experiment does not exist"],
                }
            event_rows = connection.execute(
                """
                select * from improvement_experiment_event
                where experiment_id = ? order by sequence asc
                """,
                (resolved_id,),
            ).fetchall()
        errors = _improvement_experiment_chain_errors(row, event_rows)
        if not errors and event_rows:
            tail = event_rows[-1]
            self._verified_improvement_heads[resolved_id] = (
                int(tail["sequence"]),
                str(tail["event_sha256"]),
            )
        else:
            self._verified_improvement_heads.pop(resolved_id, None)
        return {
            "experiment_id": resolved_id,
            "valid": not errors,
            "event_count": len(event_rows),
            "status": _improvement_experiment_status(
                [experiment_event_row(event) for event in event_rows]
            ),
            "errors": errors,
        }

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


def _validate_improvement_experiment_transition(
    previous_kind: str, event_kind: str
) -> None:
    if previous_kind in TERMINAL_EXPERIMENT_EVENT_KINDS:
        raise ValueError(
            f"cannot append {event_kind!r} after terminal event {previous_kind!r}"
        )
    if event_kind == "failed":
        return
    allowed = {
        "started": {"baseline_evaluated"},
        "baseline_evaluated": {"candidate_evaluated", "completed"},
        "candidate_evaluated": {
            "candidate_evaluated",
            "proposal_created",
            "completed",
        },
        "proposal_created": {"completed"},
    }
    if event_kind not in allowed.get(previous_kind, set()):
        raise ValueError(
            f"invalid experiment transition {previous_kind!r} -> {event_kind!r}"
        )


def _improvement_experiment_definition_errors(
    experiment: sqlite3.Row,
) -> list[str]:
    errors: list[str] = []
    experiment_id = str(experiment["experiment_id"])
    try:
        validate_experiment_id(experiment_id)
    except ValueError:
        errors.append("experiment id is invalid")
    if str(experiment["contract_version"]) != EXPERIMENT_CONTRACT_VERSION:
        errors.append("unsupported experiment contract version")
    if not str(experiment["created_at"]).strip():
        errors.append("experiment creation timestamp is invalid")
    if not str(experiment["lane"]).strip() or not str(experiment["method"]).strip():
        errors.append("experiment lane or method is invalid")
    try:
        definition = json.loads(experiment["definition_json"])
        validate_structured_payload(definition, field_name="experiment definition")
    except (TypeError, ValueError, json.JSONDecodeError):
        definition = None
        errors.append("definition payload is invalid")
    if definition is not None:
        try:
            for field_name in (
                "evaluator_sha256",
                "dataset_sha256",
                "baseline_sha256",
                "definition_sha256",
            ):
                validate_sha256(str(experiment[field_name]), field_name=field_name)
            expected_definition_sha256 = experiment_definition_sha256(
                experiment_id=experiment_id,
                created_at=str(experiment["created_at"]),
                contract_version=str(experiment["contract_version"]),
                lane=str(experiment["lane"]),
                method=str(experiment["method"]),
                evaluator_sha256=str(experiment["evaluator_sha256"]),
                dataset_sha256=str(experiment["dataset_sha256"]),
                baseline_sha256=str(experiment["baseline_sha256"]),
                definition=definition,
            )
        except (TypeError, ValueError):
            errors.append("definition metadata is invalid")
        else:
            if expected_definition_sha256 != str(experiment["definition_sha256"]):
                errors.append("definition hash mismatch")
    return errors


def _improvement_experiment_event_row_errors(
    experiment: sqlite3.Row,
    row: sqlite3.Row,
) -> list[str]:
    """Validate one event independently for cached-head incremental appends."""

    errors: list[str] = []
    experiment_id = str(experiment["experiment_id"])
    sequence = int(row["sequence"])
    kind = str(row["event_kind"])
    previous_raw = row["previous_event_sha256"]
    previous_sha256 = None if previous_raw is None else str(previous_raw)
    if sequence < 1:
        errors.append("event sequence is invalid")
    if kind not in EXPERIMENT_EVENT_KINDS:
        errors.append(f"event {sequence} has unknown kind {kind!r}")
    if not str(row["ts"]).strip():
        errors.append(f"event {sequence} timestamp is invalid")
    try:
        validate_sha256(str(row["event_sha256"]), field_name="event_sha256")
    except ValueError:
        errors.append(f"event {sequence} hash is invalid")
    if sequence == 1:
        if kind != "started":
            errors.append("first experiment event is not started")
        if previous_sha256 is not None:
            errors.append("first experiment event has a previous hash")
    else:
        try:
            validate_sha256(
                previous_sha256 or "",
                field_name="previous_event_sha256",
            )
        except ValueError:
            errors.append(f"event {sequence} previous hash is invalid")
    try:
        payload = json.loads(row["payload_json"])
        normalized_payload = validate_structured_payload(
            payload, field_name=f"event {sequence} payload"
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        normalized_payload = None
        errors.append(f"event {sequence} payload is invalid")
    if normalized_payload is not None:
        if sequence == 1:
            if normalized_payload.get("contract_version") != str(
                experiment["contract_version"]
            ):
                errors.append("started event contract version mismatch")
            if normalized_payload.get("definition_sha256") != str(
                experiment["definition_sha256"]
            ):
                errors.append("started event definition hash mismatch")
            if normalized_payload.get("schema_version") != EXPERIMENT_SCHEMA_VERSION:
                errors.append("started event schema version mismatch")
        expected_sha256 = improvement_event_sha256(
            experiment_id=experiment_id,
            sequence=sequence,
            ts=str(row["ts"]),
            event_kind=kind,
            payload=normalized_payload,
            previous_event_sha256=previous_sha256,
        )
        if expected_sha256 != str(row["event_sha256"]):
            errors.append(f"event {sequence} hash mismatch")
    return errors


def _improvement_experiment_chain_errors(
    experiment: sqlite3.Row,
    event_rows: Sequence[sqlite3.Row],
) -> list[str]:
    errors = _improvement_experiment_definition_errors(experiment)
    experiment_id = str(experiment["experiment_id"])

    if not event_rows:
        return [*errors, "experiment has no events"]

    previous_sha256: str | None = None
    previous_kind: str | None = None
    for expected_sequence, row in enumerate(event_rows, start=1):
        sequence = int(row["sequence"])
        kind = str(row["event_kind"])
        if sequence != expected_sequence:
            errors.append(
                f"event sequence mismatch at {expected_sequence}: stored {sequence}"
            )
        if kind not in EXPERIMENT_EVENT_KINDS:
            errors.append(f"event {sequence} has unknown kind {kind!r}")
        if expected_sequence == 1 and kind != "started":
            errors.append("first experiment event is not started")
        if str(row["previous_event_sha256"] or "") != (previous_sha256 or ""):
            errors.append(f"event {sequence} previous hash mismatch")
        try:
            payload = json.loads(row["payload_json"])
            normalized_payload = validate_structured_payload(
                payload, field_name=f"event {sequence} payload"
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            normalized_payload = None
            errors.append(f"event {sequence} payload is invalid")
        if normalized_payload is not None:
            if expected_sequence == 1:
                if normalized_payload.get("contract_version") != str(
                    experiment["contract_version"]
                ):
                    errors.append("started event contract version mismatch")
                if normalized_payload.get("definition_sha256") != str(
                    experiment["definition_sha256"]
                ):
                    errors.append("started event definition hash mismatch")
                if normalized_payload.get("schema_version") != EXPERIMENT_SCHEMA_VERSION:
                    errors.append("started event schema version mismatch")
            expected_sha256 = improvement_event_sha256(
                experiment_id=experiment_id,
                sequence=sequence,
                ts=str(row["ts"]),
                event_kind=kind,
                payload=normalized_payload,
                previous_event_sha256=previous_sha256,
            )
            if expected_sha256 != str(row["event_sha256"]):
                errors.append(f"event {sequence} hash mismatch")
        if previous_kind is not None:
            try:
                _validate_improvement_experiment_transition(previous_kind, kind)
            except ValueError:
                errors.append(
                    f"invalid event transition {previous_kind!r} -> {kind!r}"
                )
        previous_sha256 = str(row["event_sha256"])
        previous_kind = kind
    return errors


def _improvement_experiment_status(
    events: Sequence[Mapping[str, object]],
) -> str:
    if not events:
        return "invalid"
    latest = str(events[-1].get("event_kind") or "")
    if latest in TERMINAL_EXPERIMENT_EVENT_KINDS:
        return latest
    return "running"


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


def _context_timestamp(*values: object) -> str | None:
    """Return the first parseable timestamp under the shared UTC policy."""

    for value in values:
        normalized = normalize_timestamp(str(value) if value is not None else None)
        if normalized is not None:
            return normalized
    return None


def _current_context_record_ids(
    connection: sqlite3.Connection, record_ids: set[str]
) -> set[str]:
    """Return only canonical supports that remain eligible for current context."""

    current: set[str] = set()
    excluded = tuple(
        status.value
        for status in (
            Status.CONTRADICTED,
            Status.SUPERSEDED,
            Status.DEPRECATED,
            Status.DELETED_SOFT,
        )
    )
    ordered = sorted(record_ids)
    for start in range(0, len(ordered), 500):
        chunk = ordered[start : start + 500]
        if not chunk:
            continue
        placeholders = ",".join("?" for _ in chunk)
        status_placeholders = ",".join("?" for _ in excluded)
        rows = connection.execute(
            "select id from ir_records "
            f"where id in ({placeholders}) "
            f"and status not in ({status_placeholders})",
            [*chunk, *excluded],
        ).fetchall()
        current.update(str(row["id"]) for row in rows)
    return current


def _normalize_entity_label(label: str) -> str:
    """Lowercase + collapsed whitespace, the coreference dedup key."""
    return " ".join(label.lower().split())


def _entity_identity(record: MIRLRecord) -> tuple[str, str] | None:
    explicit = record.ext.get("seam.entity_identity")
    if explicit is not None:
        if (
            not isinstance(explicit, str)
            or not explicit.strip()
            or explicit != explicit.strip()
        ):
            raise ValueError("entity identity key must be a nonblank trimmed string")
        return ("explicit", explicit.casefold())
    label = record.attrs.get("label")
    if not isinstance(label, str) or not label.strip():
        return None
    return ("label", _normalize_entity_label(label))


def _merge_entity_mentions(canonical: MIRLRecord, mention: MIRLRecord) -> bool:
    """Accumulate exact mention anchors without replacing canonical identity."""

    changed = False
    merged_prov = sorted(set(canonical.prov) | set(mention.prov))
    if merged_prov != canonical.prov:
        canonical.prov = merged_prov
        changed = True
    merged_evidence = sorted(set(canonical.evidence) | set(mention.evidence))
    if merged_evidence != canonical.evidence:
        canonical.evidence = merged_evidence
        changed = True
    if changed:
        latest = canonical_timestamp_extreme(
            (canonical.updated_at, mention.updated_at), latest=True
        )
        if latest is not None:
            canonical.updated_at = latest
    return changed


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
