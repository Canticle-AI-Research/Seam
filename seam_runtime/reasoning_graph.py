from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from itertools import islice
from uuid import uuid4

from .mirl import utc_now
from .retrieval_policy import (
    FUSION_POLICY,
    FUSION_POLICY_FINGERPRINT,
    RETRIEVAL_PLANNER,
    RETRIEVAL_REASON_CODES,
    candidate_set_fingerprint,
    contribution_rank,
    fusion_score,
)

REASONING_SCHEMA_VERSION = 1
REASONING_RETRIEVAL_SCHEMA_VERSION = 1
REASONING_VERIFICATION_SCHEMA_VERSION = 1
REASONING_NODE_KINDS = frozenset(
    {
        "objective",
        "question",
        "premise",
        "hypothesis",
        "inference",
        "decision",
        "outcome",
    }
)
REASONING_RELATIONS = frozenset(
    {
        "decomposes",
        "uses",
        "supports",
        "opposes",
        "derives",
        "tests",
        "selects",
        "answers",
        "supersedes",
        "produces",
    }
)
REASONING_STATUSES = frozenset(
    {"open", "supported", "challenged", "accepted", "rejected", "superseded"}
)
_STATUS_TRANSITIONS = {
    "open": frozenset({"supported", "challenged", "accepted", "rejected", "superseded"}),
    "supported": frozenset({"challenged", "accepted", "rejected", "superseded"}),
    "challenged": frozenset({"supported", "accepted", "rejected", "superseded"}),
    "accepted": frozenset({"superseded"}),
    "rejected": frozenset({"superseded"}),
    "superseded": frozenset(),
}
_SUPPORTING_RELATIONS = frozenset({"uses", "supports", "derives", "tests", "answers"})
RETRIEVAL_POLICY = FUSION_POLICY
RETRIEVAL_MODES = frozenset({"vector", "graph", "hybrid", "mix"})
RETRIEVAL_INTENTS = frozenset({"structured", "semantic", "hybrid", "graph", "mix"})
RETRIEVAL_SOURCES = frozenset(
    {"sql", "vector", "graph", "graph_node", "chroma"}
)
MAX_RETRIEVAL_CANDIDATES = 128
REASONING_CHECK_KINDS = frozenset({"test", "tool", "review", "challenge"})
REASONING_VERDICTS = frozenset({"passed", "failed", "error", "contradicted"})


@dataclass(frozen=True)
class ReasoningRetrievalCandidate:
    record_id: str
    rank: int
    score: float
    selected: bool
    sources: Mapping[str, float]
    record_sha256: str
    reasons: tuple[str, ...] = ()


def _table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f"pragma table_info({table})").fetchall()
    }


def _migrate_reasoning_retrieval_schema(connection: sqlite3.Connection) -> None:
    """Add fields introduced while R2 remains an additive local schema."""

    retrieval_columns = _table_columns(connection, "reasoning_retrieval")
    candidate_columns = _table_columns(connection, "reasoning_retrieval_candidate")
    if retrieval_columns and "seq" not in retrieval_columns:
        connection.execute("drop trigger if exists reasoning_retrieval_no_update")
        connection.execute("alter table reasoning_retrieval add column seq integer")
        counters: dict[str, int] = {}
        rows = connection.execute(
            "select retrieval_id, run_id from reasoning_retrieval "
            "order by run_id, created_at, retrieval_id"
        ).fetchall()
        for row in rows:
            run_id = str(row["run_id"])
            counters[run_id] = counters.get(run_id, 0) + 1
            connection.execute(
                "update reasoning_retrieval set seq = ? where retrieval_id = ?",
                (counters[run_id], row["retrieval_id"]),
            )

    retrieval_columns = _table_columns(connection, "reasoning_retrieval")
    identity_columns = {
        "semantic_adapter": "text",
        "embedding_model": "text",
        "embedding_dimension": "integer",
        "embedding_revision": "text",
    }
    missing_identity = set(identity_columns) - retrieval_columns
    if retrieval_columns and missing_identity:
        connection.execute("drop trigger if exists reasoning_retrieval_no_update")
        for column in sorted(missing_identity):
            connection.execute(
                f"alter table reasoning_retrieval add column {column} "
                f"{identity_columns[column]}"
            )
        connection.execute(
            "update reasoning_retrieval set "
            "semantic_adapter = coalesce(semantic_adapter, 'unknown'), "
            "embedding_model = coalesce(embedding_model, 'unknown'), "
            "embedding_dimension = coalesce(embedding_dimension, 0)"
        )
    if retrieval_columns and "graph_node_latency_ms" not in retrieval_columns:
        connection.execute(
            "alter table reasoning_retrieval add column graph_node_latency_ms real"
        )

    snapshot_columns = {"record_ns", "record_scope", "record_sha256"}
    missing_snapshots = snapshot_columns - candidate_columns
    if candidate_columns and missing_snapshots:
        connection.execute(
            "drop trigger if exists reasoning_retrieval_candidate_no_update"
        )
        for column in sorted(missing_snapshots):
            connection.execute(
                f"alter table reasoning_retrieval_candidate add column {column} text"
            )
        rows = connection.execute(
            "select c.candidate_id, c.record_id, rr.ns, rr.scope, ir.payload_json "
            "from reasoning_retrieval_candidate c "
            "join reasoning_retrieval rr on rr.retrieval_id = c.retrieval_id "
            "left join ir_records ir on ir.id = c.record_id"
        ).fetchall()
        for row in rows:
            payload = row["payload_json"]
            digest = (
                hashlib.sha256(payload.encode("utf-8")).hexdigest()
                if isinstance(payload, str)
                else "0" * 64
            )
            connection.execute(
                "update reasoning_retrieval_candidate "
                "set record_ns = ?, record_scope = ?, record_sha256 = ? "
                "where candidate_id = ?",
                (row["ns"], row["scope"], digest, row["candidate_id"]),
            )

    # These guards gained stronger invariants during the additive R2 build.
    # Recreate their definitions below rather than retaining an older trigger
    # under CREATE TRIGGER IF NOT EXISTS.
    for trigger in (
        "reasoning_retrieval_scope_guard",
        "reasoning_retrieval_candidate_scope_guard",
        "reasoning_retrieval_finalize_guard",
        "reasoning_retrieval_seq_guard",
    ):
        connection.execute(f"drop trigger if exists {trigger}")


def init_reasoning_graph(connection: sqlite3.Connection) -> None:
    """Create the append-only public reasoning plane.

    The graph records concise, inspectable reasoning artifacts. It deliberately
    has no field for hidden chain-of-thought, activations, logits, or raw model
    traces, and it never promotes a conclusion into canonical MIRL by itself.
    """

    _migrate_reasoning_retrieval_schema(connection)
    connection.executescript(
        """
        create table if not exists reasoning_node (
            node_id text primary key,
            run_id text not null,
            seq integer not null,
            kind text not null check (kind in
                ('objective', 'question', 'premise', 'hypothesis', 'inference', 'decision', 'outcome')),
            summary text not null,
            confidence real check (confidence is null or (confidence >= 0 and confidence <= 1)),
            ns text not null,
            scope text not null,
            agent_id text,
            operation text,
            knowledge_refs_json text not null,
            evidence_record_ids_json text not null,
            created_at text not null,
            schema_version integer not null default 1,
            foreign key (run_id) references workspace_run(run_id),
            unique (run_id, seq)
        );
        create table if not exists reasoning_edge (
            edge_id text primary key,
            run_id text not null,
            seq integer not null,
            src_node_id text not null,
            relation text not null check (relation in
                ('decomposes', 'uses', 'supports', 'opposes', 'derives', 'tests',
                 'selects', 'answers', 'supersedes', 'produces')),
            dst_node_id text not null,
            agent_id text,
            created_at text not null,
            schema_version integer not null default 1,
            foreign key (run_id) references workspace_run(run_id),
            foreign key (src_node_id) references reasoning_node(node_id),
            foreign key (dst_node_id) references reasoning_node(node_id),
            unique (run_id, seq),
            unique (src_node_id, relation, dst_node_id)
        );
        create table if not exists reasoning_state (
            state_id text primary key,
            node_id text not null,
            seq integer not null,
            status text not null check (status in
                ('open', 'supported', 'challenged', 'accepted', 'rejected', 'superseded')),
            reason text,
            actor text,
            created_at text not null,
            schema_version integer not null default 1,
            foreign key (node_id) references reasoning_node(node_id),
            unique (node_id, seq)
        );
        create table if not exists reasoning_retrieval (
            retrieval_id text primary key,
            run_id text not null,
            seq integer not null check (seq >= 1),
            ns text not null,
            scope text not null,
            query_node_id text not null,
            decision_node_id text not null unique,
            query_sha256 text not null,
            normalized_query text not null,
            planner text not null,
            mode text not null check (mode in ('vector', 'graph', 'hybrid', 'mix')),
            intent text not null check (intent in ('structured', 'semantic', 'hybrid', 'graph', 'mix')),
            budget integer not null check (budget >= 1 and budget <= 64),
            graph_hops integer not null check (graph_hops >= 0 and graph_hops <= 3),
            semantic_graph_seeding integer not null check (semantic_graph_seeding in (0, 1)),
            graph_at text,
            graph_include_history integer not null default 0 check (graph_include_history in (0, 1)),
            filter_ids_json text not null,
            filter_kinds_json text not null,
            filter_predicate text,
            filter_subject text,
            filter_object_text text,
            sql_limit integer,
            vector_limit integer,
            graph_limit integer,
            policy text not null,
            policy_fingerprint text not null,
            candidate_set_sha256 text not null,
            semantic_backend text not null,
            semantic_adapter text not null,
            embedding_model text not null,
            embedding_dimension integer not null check (embedding_dimension >= 1),
            embedding_revision text,
            total_candidates integer not null check (total_candidates >= 0),
            recorded_candidates integer not null check
                (recorded_candidates >= 0 and recorded_candidates <= 128),
            selected_count integer not null check
                (selected_count >= 0 and selected_count <= budget
                 and selected_count <= recorded_candidates),
            candidates_truncated integer not null check (candidates_truncated in (0, 1)),
            sql_latency_ms real,
            vector_latency_ms real,
            graph_node_latency_ms real,
            graph_latency_ms real,
            total_latency_ms real not null,
            created_at text not null,
            schema_version integer not null default 1,
            foreign key (run_id) references workspace_run(run_id),
            foreign key (query_node_id) references reasoning_node(node_id),
            foreign key (decision_node_id) references reasoning_node(node_id),
            unique (run_id, seq),
            check (
                (candidates_truncated = 0 and total_candidates = recorded_candidates)
                or
                (candidates_truncated = 1 and total_candidates > recorded_candidates)
            )
        );
        create table if not exists reasoning_retrieval_candidate (
            candidate_id text primary key,
            retrieval_id text not null,
            record_id text not null,
            record_ns text not null,
            record_scope text not null,
            record_sha256 text not null check
                (length(record_sha256) = 64 and record_sha256 not glob '*[^0-9a-f]*'),
            rank integer not null check (rank >= 1),
            score real not null,
            selected integer not null check (selected in (0, 1)),
            sources_json text not null,
            reasons_json text not null,
            disposition_reason text not null,
            created_at text not null,
            schema_version integer not null default 1,
            foreign key (retrieval_id) references reasoning_retrieval(retrieval_id),
            unique (retrieval_id, rank),
            unique (retrieval_id, record_id)
        );
        create table if not exists reasoning_verification (
            verification_id text primary key,
            run_id text not null,
            seq integer not null check (seq >= 1),
            ns text not null,
            scope text not null,
            subject_node_id text not null,
            check_kind text not null check (check_kind in
                ('test', 'tool', 'review', 'challenge')),
            check_ref text not null,
            verdict text not null check (verdict in
                ('passed', 'failed', 'error', 'contradicted')),
            summary text not null,
            result_sha256 text check (
                result_sha256 is null or
                (length(result_sha256) = 64
                 and result_sha256 not glob '*[^0-9a-f]*')
            ),
            result_length integer check (
                result_length is null or result_length >= 0
            ),
            exit_code integer,
            duration_ms real check (duration_ms is null or duration_ms >= 0),
            knowledge_refs_json text not null,
            evidence_record_ids_json text not null,
            agent_id text,
            retry_of text unique,
            created_at text not null,
            schema_version integer not null default 1,
            foreign key (run_id) references workspace_run(run_id),
            foreign key (subject_node_id) references reasoning_node(node_id),
            foreign key (retry_of) references reasoning_verification(verification_id),
            unique (run_id, seq),
            check (
                (result_sha256 is null and result_length is null)
                or
                (result_sha256 is not null and result_length is not null)
            )
        );
        create table if not exists reasoning_outcome_verification (
            outcome_node_id text not null,
            verification_id text not null,
            seq integer not null check (seq >= 1),
            created_at text not null,
            schema_version integer not null default 1,
            primary key (outcome_node_id, verification_id),
            unique (outcome_node_id, seq),
            foreign key (outcome_node_id) references reasoning_node(node_id),
            foreign key (verification_id) references reasoning_verification(verification_id)
        );
        create index if not exists idx_reasoning_node_run on reasoning_node (run_id, seq);
        create index if not exists idx_reasoning_node_ns_scope on reasoning_node (ns, scope);
        create index if not exists idx_reasoning_edge_run on reasoning_edge (run_id, seq);
        create index if not exists idx_reasoning_edge_src on reasoning_edge (src_node_id);
        create index if not exists idx_reasoning_edge_dst on reasoning_edge (dst_node_id);
        create index if not exists idx_reasoning_state_node on reasoning_state (node_id, seq);
        create index if not exists idx_reasoning_retrieval_run on reasoning_retrieval (run_id, seq);
        create unique index if not exists idx_reasoning_retrieval_run_seq_unique
            on reasoning_retrieval (run_id, seq);
        create index if not exists idx_reasoning_retrieval_candidate_decision
            on reasoning_retrieval_candidate (retrieval_id, rank);
        create index if not exists idx_reasoning_verification_run
            on reasoning_verification (run_id, seq);
        create index if not exists idx_reasoning_verification_subject
            on reasoning_verification (subject_node_id, seq);
        create index if not exists idx_reasoning_outcome_verification
            on reasoning_outcome_verification (outcome_node_id, seq);
        create trigger if not exists reasoning_node_no_update
        before update on reasoning_node begin
            select raise(abort, 'reasoning_node is append-only');
        end;
        create trigger if not exists reasoning_node_no_delete
        before delete on reasoning_node begin
            select raise(abort, 'reasoning_node is append-only');
        end;
        create trigger if not exists reasoning_edge_no_update
        before update on reasoning_edge begin
            select raise(abort, 'reasoning_edge is append-only');
        end;
        create trigger if not exists reasoning_edge_no_delete
        before delete on reasoning_edge begin
            select raise(abort, 'reasoning_edge is append-only');
        end;
        create trigger if not exists reasoning_state_no_update
        before update on reasoning_state begin
            select raise(abort, 'reasoning_state is append-only');
        end;
        create trigger if not exists reasoning_state_no_delete
        before delete on reasoning_state begin
            select raise(abort, 'reasoning_state is append-only');
        end;
        create trigger if not exists reasoning_retrieval_no_update
        before update on reasoning_retrieval begin
            select raise(abort, 'reasoning_retrieval is append-only');
        end;
        create trigger if not exists reasoning_retrieval_no_delete
        before delete on reasoning_retrieval begin
            select raise(abort, 'reasoning_retrieval is append-only');
        end;
        create trigger if not exists reasoning_retrieval_seq_guard
        before insert on reasoning_retrieval
        when new.seq is null or typeof(new.seq) != 'integer' or new.seq < 1
        begin
            select raise(abort, 'reasoning retrieval sequence is invalid');
        end;
        create trigger if not exists reasoning_retrieval_candidate_no_update
        before update on reasoning_retrieval_candidate begin
            select raise(abort, 'reasoning_retrieval_candidate is append-only');
        end;
        create trigger if not exists reasoning_retrieval_candidate_no_delete
        before delete on reasoning_retrieval_candidate begin
            select raise(abort, 'reasoning_retrieval_candidate is append-only');
        end;
        create trigger if not exists reasoning_verification_no_update
        before update on reasoning_verification begin
            select raise(abort, 'reasoning_verification is append-only');
        end;
        create trigger if not exists reasoning_verification_no_delete
        before delete on reasoning_verification begin
            select raise(abort, 'reasoning_verification is append-only');
        end;
        create trigger if not exists reasoning_outcome_verification_no_update
        before update on reasoning_outcome_verification begin
            select raise(abort, 'reasoning_outcome_verification is append-only');
        end;
        create trigger if not exists reasoning_outcome_verification_no_delete
        before delete on reasoning_outcome_verification begin
            select raise(abort, 'reasoning_outcome_verification is append-only');
        end;
        create trigger if not exists reasoning_verification_scope_guard
        before insert on reasoning_verification
        when not exists (
            select 1
            from workspace_run r
            join reasoning_node n on n.node_id = new.subject_node_id
            where r.run_id = new.run_id
              and n.run_id = r.run_id
              and new.ns = r.ns and new.scope = r.scope
              and n.ns = r.ns and n.scope = r.scope
        ) begin
            select raise(abort, 'reasoning verification crosses run or scope');
        end;
        create trigger if not exists reasoning_verification_retry_guard
        before insert on reasoning_verification
        when new.retry_of is not null and not exists (
            select 1
            from reasoning_verification prior
            where prior.verification_id = new.retry_of
              and prior.run_id = new.run_id
              and prior.subject_node_id = new.subject_node_id
              and prior.check_kind = new.check_kind
              and prior.check_ref = new.check_ref
        ) begin
            select raise(abort, 'reasoning verification retry identity mismatch');
        end;
        create trigger if not exists reasoning_outcome_verification_guard
        before insert on reasoning_outcome_verification
        when not exists (
            select 1
            from reasoning_node outcome
            join reasoning_verification verification
              on verification.verification_id = new.verification_id
            join reasoning_state outcome_state
              on outcome_state.node_id = outcome.node_id
            where outcome.node_id = new.outcome_node_id
              and outcome.kind = 'outcome'
              and outcome.run_id = verification.run_id
              and outcome.ns = verification.ns
              and outcome.scope = verification.scope
              and outcome_state.seq = (
                  select max(latest.seq) from reasoning_state latest
                  where latest.node_id = outcome.node_id
              )
              and outcome_state.status = 'open'
              and verification.verdict = 'passed'
              and not exists (
                  select 1 from reasoning_verification retry
                  where retry.retry_of = verification.verification_id
              )
        ) begin
            select raise(abort, 'outcome verification is not a current passed check');
        end;
        create trigger if not exists reasoning_retrieval_scope_guard
        before insert on reasoning_retrieval
        when not exists (
            select 1
            from workspace_run r
            join reasoning_node q on q.node_id = new.query_node_id
            join reasoning_node d on d.node_id = new.decision_node_id
            where r.run_id = new.run_id
              and q.run_id = r.run_id and d.run_id = r.run_id
              and new.ns = r.ns and new.scope = r.scope
              and q.ns = r.ns and q.scope = r.scope
              and d.ns = r.ns and d.scope = r.scope
              and q.kind = 'question' and d.kind = 'decision'
        ) begin
            select raise(abort, 'reasoning retrieval nodes cross run or scope');
        end;
        create trigger if not exists reasoning_retrieval_candidate_scope_guard
        before insert on reasoning_retrieval_candidate
        when not exists (
            select 1
            from reasoning_retrieval rr
            join workspace_run r on r.run_id = rr.run_id
            join ir_records ir on ir.id = new.record_id
            where rr.retrieval_id = new.retrieval_id
              and ir.ns = r.ns and ir.scope = r.scope
              and new.record_ns = r.ns and new.record_scope = r.scope
              and length(new.record_sha256) = 64
              and new.record_sha256 not glob '*[^0-9a-f]*'
        ) begin
            select raise(abort, 'reasoning retrieval candidate crosses scope');
        end;
        create trigger if not exists reasoning_retrieval_candidate_finalized_guard
        before insert on reasoning_retrieval_candidate
        when exists (
            select 1
            from reasoning_retrieval rr
            join reasoning_state rs on rs.node_id = rr.decision_node_id
            where rr.retrieval_id = new.retrieval_id
              and rs.seq = (
                  select max(latest.seq) from reasoning_state latest
                  where latest.node_id = rr.decision_node_id
              )
              and rs.status in ('accepted', 'rejected', 'superseded')
        ) begin
            select raise(abort, 'reasoning retrieval is finalized');
        end;
        create trigger if not exists reasoning_retrieval_finalize_guard
        before insert on reasoning_state
        when new.status = 'accepted' and exists (
            select 1 from reasoning_retrieval rr
            where rr.decision_node_id = new.node_id
        ) and exists (
            select 1
            from reasoning_retrieval rr
            where rr.decision_node_id = new.node_id
              and (
                  (select count(*) from reasoning_retrieval_candidate c
                   where c.retrieval_id = rr.retrieval_id) != rr.recorded_candidates
                  or rr.selected_count != min(rr.budget, rr.total_candidates)
                  or
                  (select coalesce(sum(c.selected), 0)
                   from reasoning_retrieval_candidate c
                   where c.retrieval_id = rr.retrieval_id) != rr.selected_count
                  or
                  (rr.recorded_candidates > 0 and (
                      (select min(c.rank) from reasoning_retrieval_candidate c
                       where c.retrieval_id = rr.retrieval_id) != 1
                      or
                      (select max(c.rank) from reasoning_retrieval_candidate c
                       where c.retrieval_id = rr.retrieval_id) != rr.recorded_candidates
                  ))
                  or
                  exists (
                      select 1 from reasoning_retrieval_candidate c
                      where c.retrieval_id = rr.retrieval_id
                        and c.selected != case when c.rank <= rr.selected_count then 1 else 0 end
                  )
              )
        ) begin
            select raise(abort, 'reasoning retrieval candidate coverage is incomplete');
        end;
        """
    )
    _migrate_reasoning_retrieval_time_view(connection)
    _validate_reasoning_retrieval_schema(connection)
    _validate_reasoning_verification_schema(connection)
    # R4 is a derived, append-only pattern plane over verified public
    # justifications. Keep its schema initialization beside the reasoning
    # graph so every existing store upgrades without a separate migration step.
    from .reasoning_patterns import init_reasoning_patterns

    init_reasoning_patterns(connection)


def _migrate_reasoning_retrieval_time_view(connection: sqlite3.Connection) -> None:
    """Add G3 plan-time fields without rewriting append-only decisions."""

    columns = {
        str(row[1])
        for row in connection.execute("pragma table_info(reasoning_retrieval)").fetchall()
    }
    if "graph_at" not in columns:
        connection.execute("alter table reasoning_retrieval add column graph_at text")
    if "graph_include_history" not in columns:
        connection.execute(
            "alter table reasoning_retrieval add column graph_include_history integer not null default 0"
        )


def _validate_reasoning_retrieval_schema(connection: sqlite3.Connection) -> None:
    required_columns = {
        "retrieval_id",
        "run_id",
        "seq",
        "ns",
        "scope",
        "query_node_id",
        "decision_node_id",
        "query_sha256",
        "normalized_query",
        "planner",
        "mode",
        "intent",
        "budget",
        "graph_hops",
        "semantic_graph_seeding",
        "graph_at",
        "graph_include_history",
        "filter_ids_json",
        "filter_kinds_json",
        "filter_predicate",
        "filter_subject",
        "filter_object_text",
        "sql_limit",
        "vector_limit",
        "graph_limit",
        "policy",
        "policy_fingerprint",
        "candidate_set_sha256",
        "semantic_backend",
        "semantic_adapter",
        "embedding_model",
        "embedding_dimension",
        "embedding_revision",
        "total_candidates",
        "recorded_candidates",
        "selected_count",
        "candidates_truncated",
        "sql_latency_ms",
        "vector_latency_ms",
        "graph_node_latency_ms",
        "graph_latency_ms",
        "total_latency_ms",
        "created_at",
        "schema_version",
    }
    columns = {
        str(row[1])
        for row in connection.execute(
            "pragma table_info(reasoning_retrieval)"
        ).fetchall()
    }
    missing = required_columns - columns
    if missing:
        raise RuntimeError(
            "incompatible reasoning retrieval schema; missing columns: "
            + ", ".join(sorted(missing))
        )
    required_candidate_columns = {
        "candidate_id",
        "retrieval_id",
        "record_id",
        "record_ns",
        "record_scope",
        "record_sha256",
        "rank",
        "score",
        "selected",
        "sources_json",
        "reasons_json",
        "disposition_reason",
        "created_at",
        "schema_version",
    }
    candidate_columns = {
        str(row[1])
        for row in connection.execute(
            "pragma table_info(reasoning_retrieval_candidate)"
        ).fetchall()
    }
    missing_candidate_columns = required_candidate_columns - candidate_columns
    if missing_candidate_columns:
        raise RuntimeError(
            "incompatible reasoning retrieval candidate schema; missing columns: "
            + ", ".join(sorted(missing_candidate_columns))
        )
    required_triggers = {
        "reasoning_retrieval_no_update",
        "reasoning_retrieval_no_delete",
        "reasoning_retrieval_seq_guard",
        "reasoning_retrieval_scope_guard",
        "reasoning_retrieval_candidate_no_update",
        "reasoning_retrieval_candidate_no_delete",
        "reasoning_retrieval_candidate_scope_guard",
        "reasoning_retrieval_candidate_finalized_guard",
        "reasoning_retrieval_finalize_guard",
    }
    triggers = {
        str(row[0])
        for row in connection.execute(
            "select name from sqlite_master where type = 'trigger'"
        ).fetchall()
    }
    missing_triggers = required_triggers - triggers
    if missing_triggers:
        raise RuntimeError(
            "incompatible reasoning retrieval schema; missing triggers: "
            + ", ".join(sorted(missing_triggers))
        )


def _validate_reasoning_verification_schema(connection: sqlite3.Connection) -> None:
    required_columns = {
        "verification_id",
        "run_id",
        "seq",
        "ns",
        "scope",
        "subject_node_id",
        "check_kind",
        "check_ref",
        "verdict",
        "summary",
        "result_sha256",
        "result_length",
        "exit_code",
        "duration_ms",
        "knowledge_refs_json",
        "evidence_record_ids_json",
        "agent_id",
        "retry_of",
        "created_at",
        "schema_version",
    }
    columns = _table_columns(connection, "reasoning_verification")
    missing = required_columns - columns
    if missing:
        raise RuntimeError(
            "incompatible reasoning verification schema; missing columns: "
            + ", ".join(sorted(missing))
        )
    required_association_columns = {
        "outcome_node_id",
        "verification_id",
        "seq",
        "created_at",
        "schema_version",
    }
    association_columns = _table_columns(
        connection, "reasoning_outcome_verification"
    )
    missing_association = required_association_columns - association_columns
    if missing_association:
        raise RuntimeError(
            "incompatible reasoning outcome-verification schema; missing columns: "
            + ", ".join(sorted(missing_association))
        )
    required_triggers = {
        "reasoning_verification_no_update",
        "reasoning_verification_no_delete",
        "reasoning_verification_scope_guard",
        "reasoning_verification_retry_guard",
        "reasoning_outcome_verification_no_update",
        "reasoning_outcome_verification_no_delete",
        "reasoning_outcome_verification_guard",
    }
    triggers = {
        str(row[0])
        for row in connection.execute(
            "select name from sqlite_master where type = 'trigger'"
        ).fetchall()
    }
    missing_triggers = required_triggers - triggers
    if missing_triggers:
        raise RuntimeError(
            "incompatible reasoning verification schema; missing triggers: "
            + ", ".join(sorted(missing_triggers))
        )


def _required_text(value: str, field: str, *, limit: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    resolved = value.strip()
    if not resolved:
        raise ValueError(f"{field} is required")
    if len(resolved) > limit:
        raise ValueError(f"{field} exceeds {limit} characters")
    return resolved


def _reference_ids(values: Iterable[str], field: str) -> tuple[str, ...]:
    bounded = list(islice(iter(values), 257))
    if len(bounded) > 256:
        raise ValueError(f"{field} supports at most 256 references")
    resolved: list[str] = []
    for value in bounded:
        if not isinstance(value, str):
            raise TypeError(f"{field} values must be strings")
        item = value.strip()
        if item and item not in resolved:
            resolved.append(item)
    return tuple(resolved)


def _run_row(connection: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    row = connection.execute(
        "select run_id, ns, scope, agent_id from workspace_run where run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"workspace run not found: {run_id}")
    return row


def _validate_references(
    connection: sqlite3.Connection,
    *,
    ns: str,
    scope: str,
    knowledge_refs: tuple[str, ...],
    evidence_record_ids: tuple[str, ...],
) -> None:
    for node_id in knowledge_refs:
        row = connection.execute(
            "select ns, scope from knowledge_nodes where id = ?", (node_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"knowledge node not found: {node_id}")
        if row["ns"] != ns or row["scope"] != scope:
            raise ValueError(f"knowledge reference crosses namespace or scope: {node_id}")
    for record_id in evidence_record_ids:
        row = connection.execute(
            "select ns, scope from ir_records where id = ?", (record_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"evidence record not found: {record_id}")
        if row["ns"] != ns or row["scope"] != scope:
            raise ValueError(f"evidence reference crosses namespace or scope: {record_id}")


def add_reasoning_node(
    connection: sqlite3.Connection,
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
    # Sequence allocation and insertion share a write lock, matching the
    # workspace event contract. Callers already inside a transaction retain
    # control of their own transaction boundary.
    if not connection.in_transaction:
        connection.execute("begin immediate")
    resolved_kind = str(kind).strip().lower()
    if resolved_kind not in REASONING_NODE_KINDS:
        raise ValueError(f"unsupported reasoning node kind: {kind}")
    resolved_summary = _required_text(summary, "reasoning summary", limit=4096)
    if confidence is not None and not 0 <= float(confidence) <= 1:
        raise ValueError("confidence must be between 0 and 1")
    resolved_operation = None
    if operation is not None:
        resolved_operation = _required_text(operation, "operation", limit=128)
    resolved_knowledge = _reference_ids(knowledge_refs, "knowledge_refs")
    resolved_evidence = _reference_ids(evidence_record_ids, "evidence_record_ids")
    if resolved_kind == "premise" and not (resolved_knowledge or resolved_evidence):
        raise ValueError("premise nodes require a knowledge or evidence reference")

    run = _run_row(connection, run_id)
    _validate_references(
        connection,
        ns=run["ns"],
        scope=run["scope"],
        knowledge_refs=resolved_knowledge,
        evidence_record_ids=resolved_evidence,
    )
    resolved_node_id = node_id or f"reason:{uuid4().hex}"
    resolved_created_at = created_at or utc_now()
    next_seq = connection.execute(
        "select coalesce(max(seq), 0) + 1 from reasoning_node where run_id = ?", (run_id,)
    ).fetchone()[0]
    connection.execute(
        """
        insert into reasoning_node
            (node_id, run_id, seq, kind, summary, confidence, ns, scope, agent_id,
             operation, knowledge_refs_json, evidence_record_ids_json, created_at, schema_version)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            resolved_node_id,
            run_id,
            next_seq,
            resolved_kind,
            resolved_summary,
            None if confidence is None else float(confidence),
            run["ns"],
            run["scope"],
            agent_id or run["agent_id"],
            resolved_operation,
            json.dumps(resolved_knowledge, separators=(",", ":")),
            json.dumps(resolved_evidence, separators=(",", ":")),
            resolved_created_at,
            REASONING_SCHEMA_VERSION,
        ),
    )
    connection.execute(
        """
        insert into reasoning_state
            (state_id, node_id, seq, status, reason, actor, created_at, schema_version)
        values (?, ?, 1, 'open', ?, ?, ?, ?)
        """,
        (
            f"reason-state:{uuid4().hex}",
            resolved_node_id,
            "node created",
            agent_id or run["agent_id"],
            resolved_created_at,
            REASONING_SCHEMA_VERSION,
        ),
    )
    return get_reasoning_node(connection, resolved_node_id)


def add_reasoning_edge(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    src_node_id: str,
    relation: str,
    dst_node_id: str,
    agent_id: str | None = None,
    edge_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, object]:
    if not connection.in_transaction:
        connection.execute("begin immediate")
    resolved_relation = str(relation).strip().lower()
    if resolved_relation not in REASONING_RELATIONS:
        raise ValueError(f"unsupported reasoning relation: {relation}")
    if src_node_id == dst_node_id:
        raise ValueError("reasoning edges cannot be self-referential")
    run = _run_row(connection, run_id)
    rows = connection.execute(
        "select node_id, run_id, ns, scope from reasoning_node where node_id in (?, ?)",
        (src_node_id, dst_node_id),
    ).fetchall()
    by_id = {row["node_id"]: row for row in rows}
    missing = [node_id for node_id in (src_node_id, dst_node_id) if node_id not in by_id]
    if missing:
        raise KeyError(f"reasoning node not found: {missing[0]}")
    for row in by_id.values():
        if row["run_id"] != run_id or row["ns"] != run["ns"] or row["scope"] != run["scope"]:
            raise ValueError("reasoning edges cannot cross runs, namespaces, or scopes")
    next_seq = connection.execute(
        "select coalesce(max(seq), 0) + 1 from reasoning_edge where run_id = ?", (run_id,)
    ).fetchone()[0]
    resolved_edge_id = edge_id or f"reason-edge:{uuid4().hex}"
    resolved_created_at = created_at or utc_now()
    connection.execute(
        """
        insert into reasoning_edge
            (edge_id, run_id, seq, src_node_id, relation, dst_node_id, agent_id,
             created_at, schema_version)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            resolved_edge_id,
            run_id,
            next_seq,
            src_node_id,
            resolved_relation,
            dst_node_id,
            agent_id or run["agent_id"],
            resolved_created_at,
            REASONING_SCHEMA_VERSION,
        ),
    )
    return {
        "edge_id": resolved_edge_id,
        "run_id": run_id,
        "seq": next_seq,
        "src_node_id": src_node_id,
        "relation": resolved_relation,
        "dst_node_id": dst_node_id,
        "agent_id": agent_id or run["agent_id"],
        "created_at": resolved_created_at,
        "schema_version": REASONING_SCHEMA_VERSION,
    }


def _current_status(connection: sqlite3.Connection, node_id: str) -> sqlite3.Row:
    row = connection.execute(
        "select * from reasoning_state where node_id = ? order by seq desc limit 1",
        (node_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"reasoning node not found: {node_id}")
    return row


def _has_support(connection: sqlite3.Connection, node: sqlite3.Row) -> bool:
    if json.loads(node["knowledge_refs_json"]) or json.loads(node["evidence_record_ids_json"]):
        return True
    placeholders = ",".join("?" for _ in _SUPPORTING_RELATIONS)
    row = connection.execute(
        f"select 1 from reasoning_edge where dst_node_id = ? "
        f"and relation in ({placeholders}) limit 1",
        (node["node_id"], *sorted(_SUPPORTING_RELATIONS)),
    ).fetchone()
    if row is not None:
        return True
    return (
        connection.execute(
            "select 1 from reasoning_retrieval where decision_node_id = ? limit 1",
            (node["node_id"],),
        ).fetchone()
        is not None
    )


def transition_reasoning_node(
    connection: sqlite3.Connection,
    *,
    node_id: str,
    status: str,
    reason: str | None = None,
    actor: str | None = None,
    created_at: str | None = None,
) -> dict[str, object]:
    if not connection.in_transaction:
        connection.execute("begin immediate")
    resolved_status = str(status).strip().lower()
    if resolved_status not in REASONING_STATUSES:
        raise ValueError(f"unsupported reasoning status: {status}")
    node = connection.execute(
        "select * from reasoning_node where node_id = ?", (node_id,)
    ).fetchone()
    if node is None:
        raise KeyError(f"reasoning node not found: {node_id}")
    current = _current_status(connection, node_id)
    if resolved_status not in _STATUS_TRANSITIONS[current["status"]]:
        raise ValueError(
            f"invalid reasoning status transition: {current['status']} -> {resolved_status}"
        )
    if (
        resolved_status == "accepted"
        and node["kind"] in {"inference", "decision", "outcome"}
        and not _has_support(connection, node)
    ):
        raise ValueError(f"accepted {node['kind']} nodes require explicit support")
    resolved_reason = None
    if reason is not None:
        resolved_reason = _required_text(reason, "transition reason", limit=2048)
    next_seq = int(current["seq"]) + 1
    resolved_created_at = created_at or utc_now()
    state_id = f"reason-state:{uuid4().hex}"
    connection.execute(
        """
        insert into reasoning_state
            (state_id, node_id, seq, status, reason, actor, created_at, schema_version)
        values (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            state_id,
            node_id,
            next_seq,
            resolved_status,
            resolved_reason,
            actor,
            resolved_created_at,
            REASONING_SCHEMA_VERSION,
        ),
    )
    return {
        "state_id": state_id,
        "node_id": node_id,
        "seq": next_seq,
        "status": resolved_status,
        "reason": resolved_reason,
        "actor": actor,
        "created_at": resolved_created_at,
        "schema_version": REASONING_SCHEMA_VERSION,
    }


def _retrieval_candidate_rows(
    connection: sqlite3.Connection,
    *,
    ns: str,
    scope: str,
    candidates: Iterable[ReasoningRetrievalCandidate],
    budget: int,
    total_candidates: int,
) -> tuple[ReasoningRetrievalCandidate, ...]:
    resolved = tuple(islice(iter(candidates), MAX_RETRIEVAL_CANDIDATES + 1))
    if len(resolved) > MAX_RETRIEVAL_CANDIDATES:
        raise ValueError(
            f"reasoning retrieval supports at most {MAX_RETRIEVAL_CANDIDATES} candidates"
        )
    if total_candidates < len(resolved):
        raise ValueError("total_candidates cannot be smaller than the recorded pool")
    if not all(
        isinstance(candidate, ReasoningRetrievalCandidate) for candidate in resolved
    ):
        raise TypeError("retrieval candidates must be ReasoningRetrievalCandidate values")
    expected_ranks = list(range(1, len(resolved) + 1))
    if [candidate.rank for candidate in resolved] != expected_ranks:
        raise ValueError("retrieval candidate ranks must be contiguous and ordered")
    expected_selected = min(budget, total_candidates)
    if len(resolved) < expected_selected:
        raise ValueError("recorded candidates must include every selected result")
    if [candidate.selected for candidate in resolved] != [
        rank <= expected_selected for rank in expected_ranks
    ]:
        raise ValueError("selected candidates must be the ranked budget prefix")

    seen_ids: set[str] = set()
    for candidate in resolved:
        if isinstance(candidate.rank, bool) or not isinstance(candidate.rank, int):
            raise TypeError("retrieval candidate rank must be an integer")
        if not isinstance(candidate.selected, bool):
            raise TypeError("retrieval candidate selected must be a boolean")
        if not isinstance(candidate.record_id, str):
            raise TypeError("candidate record_id must be a string")
        record_id = candidate.record_id
        if not record_id.strip():
            raise ValueError("candidate record_id is required")
        if record_id in seen_ids:
            raise ValueError(f"duplicate retrieval candidate: {record_id}")
        seen_ids.add(record_id)
        row = connection.execute(
            "select ns, scope, payload_json from ir_records where id = ?", (record_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"retrieval candidate record not found: {record_id}")
        if row["ns"] != ns or row["scope"] != scope:
            raise ValueError(
                f"retrieval candidate crosses namespace or scope: {record_id}"
            )
        if re.fullmatch(r"[0-9a-f]{64}", candidate.record_sha256) is None:
            raise ValueError("candidate record_sha256 must be a lowercase SHA-256 digest")
        if candidate.record_sha256 != hashlib.sha256(
            row["payload_json"].encode("utf-8")
        ).hexdigest():
            raise ValueError(f"retrieval candidate changed before recording: {record_id}")
        if isinstance(candidate.score, bool) or not isinstance(candidate.score, (int, float)):
            raise TypeError("retrieval candidate score must be numeric")
        if not math.isfinite(float(candidate.score)) or abs(float(candidate.score)) > 1_000_000:
            raise ValueError("retrieval candidate score must be finite")
        if not candidate.sources:
            raise ValueError("retrieval candidates require at least one score source")
        if len(candidate.sources) > len(RETRIEVAL_SOURCES):
            raise ValueError("retrieval candidate has too many score sources")
        for source, score in candidate.sources.items():
            if source not in RETRIEVAL_SOURCES:
                raise ValueError(f"unsupported retrieval score source: {source}")
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise TypeError("retrieval source scores must be numeric")
            if not math.isfinite(float(score)) or abs(float(score)) > 1_000_000:
                raise ValueError("retrieval source scores must be finite")
            contribution_rank(float(score))
        expected_score = fusion_score(candidate.sources)
        if not math.isclose(
            float(candidate.score), expected_score, rel_tol=1e-12, abs_tol=1e-12
        ):
            raise ValueError("retrieval candidate score does not match the pinned policy")
        if len(candidate.reasons) > 32:
            raise ValueError("retrieval candidates support at most 32 reasons")
        for reason in candidate.reasons:
            if reason not in RETRIEVAL_REASON_CODES:
                raise ValueError(f"unsupported retrieval reason code: {reason}")
    expected_order = sorted(resolved, key=lambda item: (-item.score, item.record_id))
    if [candidate.record_id for candidate in resolved] != [
        candidate.record_id for candidate in expected_order
    ]:
        raise ValueError("retrieval candidates do not match the pinned policy order")
    return resolved


def _latency(value: float | None, field: str, *, required: bool = False) -> float | None:
    if value is None:
        if required:
            raise ValueError(f"{field} is required")
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field} must be numeric")
    resolved = float(value)
    if not math.isfinite(resolved) or resolved < 0 or resolved > 86_400_000:
        raise ValueError(f"{field} must be a finite non-negative duration")
    return resolved


def record_reasoning_retrieval(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    query: str,
    normalized_query: str,
    filter_ids: Iterable[str],
    filter_kinds: Iterable[str],
    filter_predicate: str | None,
    filter_subject: str | None,
    filter_object_text: str | None,
    leg_limits: Mapping[str, int],
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
    candidates: Iterable[ReasoningRetrievalCandidate],
    total_candidates: int,
    candidates_truncated: bool,
    candidate_set_sha256: str,
    leg_latency_ms: Mapping[str, float],
    total_latency_ms: float,
    policy: str = RETRIEVAL_POLICY,
    graph_at: str | None = None,
    graph_include_history: bool = False,
    agent_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, object]:
    """Atomically append a bounded retrieval decision and its reasoning nodes."""

    if not connection.in_transaction:
        connection.execute("begin immediate")
    run = _run_row(connection, run_id)
    resolved_query = _required_text(query, "retrieval query", limit=4096)
    if not isinstance(normalized_query, str):
        raise TypeError("normalized retrieval query must be a string")
    resolved_normalized = normalized_query.strip()
    if len(resolved_normalized) > 4096:
        raise ValueError("normalized retrieval query exceeds 4096 characters")
    resolved_filter_ids = _reference_ids(filter_ids, "retrieval filter_ids")
    resolved_filter_kinds = _reference_ids(filter_kinds, "retrieval filter_kinds")
    if len(resolved_filter_ids) > 64 or len(resolved_filter_kinds) > 32:
        raise ValueError("retrieval filter list exceeds its bounded plan limit")
    resolved_filter_predicate = (
        _required_text(filter_predicate, "filter predicate", limit=256)
        if filter_predicate is not None
        else None
    )
    resolved_filter_subject = (
        _required_text(filter_subject, "filter subject", limit=256)
        if filter_subject is not None
        else None
    )
    resolved_filter_object = (
        _required_text(filter_object_text, "filter object", limit=512)
        if filter_object_text is not None
        else None
    )
    resolved_mode = str(mode).strip().lower()
    if resolved_mode not in RETRIEVAL_MODES:
        raise ValueError(f"unsupported retrieval mode: {mode}")
    resolved_intent = str(intent).strip().lower()
    if resolved_intent not in RETRIEVAL_INTENTS:
        raise ValueError(f"unsupported retrieval intent: {intent}")
    if isinstance(budget, bool) or not isinstance(budget, int):
        raise TypeError("reasoning retrieval budget must be an integer")
    if not 1 <= budget <= 64:
        raise ValueError("reasoning retrieval budget must be between 1 and 64")
    if isinstance(graph_hops, bool) or not isinstance(graph_hops, int):
        raise TypeError("reasoning retrieval graph_hops must be an integer")
    if not 0 <= graph_hops <= 3:
        raise ValueError("reasoning retrieval graph_hops must be between 0 and 3")
    if not isinstance(semantic_graph_seeding, bool):
        raise TypeError("semantic_graph_seeding must be a boolean")
    resolved_graph_at = (
        _required_text(graph_at, "graph_at", limit=128)
        if graph_at is not None
        else None
    )
    if not isinstance(graph_include_history, bool):
        raise TypeError("graph_include_history must be a boolean")
    unknown_legs = set(leg_limits) - {"sql", "vector", "graph"}
    if unknown_legs:
        raise ValueError(f"unsupported retrieval leg: {sorted(unknown_legs)[0]}")
    resolved_leg_limits: dict[str, int | None] = {}
    for leg in ("sql", "vector", "graph"):
        value = leg_limits.get(leg)
        if value is None:
            resolved_leg_limits[leg] = None
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("retrieval leg limits must be integers")
        if not 1 <= value <= 4096:
            raise ValueError("retrieval leg limits must be between 1 and 4096")
        resolved_leg_limits[leg] = value
    if policy != RETRIEVAL_POLICY:
        raise ValueError(f"unsupported retrieval policy: {policy}")
    resolved_backend = _required_text(
        semantic_backend, "semantic backend", limit=64
    ).lower()
    if resolved_backend not in {"seam", "chroma"}:
        raise ValueError("semantic backend must be 'seam' or 'chroma'")
    resolved_adapter = _required_text(
        semantic_adapter, "semantic adapter", limit=128
    )
    resolved_embedding_model = _required_text(
        embedding_model, "embedding model", limit=512
    )
    if isinstance(embedding_dimension, bool) or not isinstance(
        embedding_dimension, int
    ):
        raise TypeError("embedding_dimension must be an integer")
    if not 1 <= embedding_dimension <= 1_000_000:
        raise ValueError("embedding_dimension must be between 1 and 1000000")
    resolved_embedding_revision = (
        _required_text(embedding_revision, "embedding revision", limit=256)
        if embedding_revision is not None
        else None
    )
    if isinstance(total_candidates, bool) or not isinstance(total_candidates, int):
        raise TypeError("total_candidates must be an integer")
    if total_candidates < 0:
        raise ValueError("total_candidates must be non-negative")
    if not isinstance(candidates_truncated, bool):
        raise TypeError("candidates_truncated must be a boolean")
    if re.fullmatch(r"[0-9a-f]{64}", candidate_set_sha256) is None:
        raise ValueError("candidate_set_sha256 must be a lowercase SHA-256 digest")
    resolved_candidates = _retrieval_candidate_rows(
        connection,
        ns=run["ns"],
        scope=run["scope"],
        candidates=candidates,
        budget=int(budget),
        total_candidates=int(total_candidates),
    )
    if bool(candidates_truncated) != (total_candidates > len(resolved_candidates)):
        raise ValueError("candidates_truncated does not match the recorded pool")
    if not candidates_truncated:
        expected_fingerprint = candidate_set_fingerprint(
            (
                candidate.record_id,
                candidate.score,
                candidate.sources,
            )
            for candidate in resolved_candidates
        )
        if candidate_set_sha256 != expected_fingerprint:
            raise ValueError("candidate_set_sha256 does not match the recorded pool")
    unknown_latency = set(leg_latency_ms) - RETRIEVAL_SOURCES
    if unknown_latency:
        raise ValueError(
            f"unsupported retrieval latency source: {sorted(unknown_latency)[0]}"
        )
    latencies = {
        source: _latency(leg_latency_ms.get(source), f"{source}_latency_ms")
        for source in RETRIEVAL_SOURCES
    }
    resolved_total_latency = _latency(
        total_latency_ms, "total_latency_ms", required=True
    )
    assert resolved_total_latency is not None
    resolved_created_at = created_at or utc_now()
    resolved_agent = agent_id or run["agent_id"]

    query_node = add_reasoning_node(
        connection,
        run_id=run_id,
        kind="question",
        summary=resolved_query,
        agent_id=resolved_agent,
        operation=f"retrieval:{resolved_mode}",
        created_at=resolved_created_at,
    )
    objective_row = connection.execute(
        "select node_id from reasoning_node "
        "where run_id = ? and kind = 'objective' order by seq limit 1",
        (run_id,),
    ).fetchone()
    if objective_row is not None:
        add_reasoning_edge(
            connection,
            run_id=run_id,
            src_node_id=str(objective_row["node_id"]),
            relation="decomposes",
            dst_node_id=str(query_node["node_id"]),
            agent_id=resolved_agent,
            created_at=resolved_created_at,
        )
    selected_ids = tuple(
        candidate.record_id for candidate in resolved_candidates if candidate.selected
    )
    decision_node = add_reasoning_node(
        connection,
        run_id=run_id,
        kind="decision",
        summary=(
            f"Selected {len(selected_ids)} of {total_candidates} ranked retrieval "
            f"candidates using {policy}."
        ),
        agent_id=resolved_agent,
        operation=policy,
        evidence_record_ids=selected_ids,
        created_at=resolved_created_at,
    )
    add_reasoning_edge(
        connection,
        run_id=run_id,
        src_node_id=str(query_node["node_id"]),
        relation="produces",
        dst_node_id=str(decision_node["node_id"]),
        agent_id=resolved_agent,
        created_at=resolved_created_at,
    )

    retrieval_id = f"reason-retrieval:{uuid4().hex}"
    retrieval_seq = int(
        connection.execute(
            "select coalesce(max(seq), 0) + 1 from reasoning_retrieval where run_id = ?",
            (run_id,),
        ).fetchone()[0]
    )
    connection.execute(
        """
        insert into reasoning_retrieval
            (retrieval_id, run_id, seq, ns, scope, query_node_id, decision_node_id, query_sha256,
             normalized_query, planner, mode, intent, budget, graph_hops,
             semantic_graph_seeding, filter_ids_json, filter_kinds_json,
             filter_predicate, filter_subject, filter_object_text, sql_limit,
             vector_limit, graph_limit, policy,
             policy_fingerprint, candidate_set_sha256, semantic_backend,
             semantic_adapter, embedding_model, embedding_dimension,
             embedding_revision,
             total_candidates, recorded_candidates,
             selected_count, candidates_truncated, sql_latency_ms,
             vector_latency_ms, graph_node_latency_ms, graph_latency_ms,
             total_latency_ms, created_at,
             graph_at, graph_include_history,
             schema_version)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            retrieval_id,
            run_id,
            retrieval_seq,
            run["ns"],
            run["scope"],
            query_node["node_id"],
            decision_node["node_id"],
            hashlib.sha256(resolved_query.encode("utf-8")).hexdigest(),
            resolved_normalized,
            RETRIEVAL_PLANNER,
            resolved_mode,
            resolved_intent,
            int(budget),
            int(graph_hops),
            int(semantic_graph_seeding),
            json.dumps(resolved_filter_ids, separators=(",", ":")),
            json.dumps(resolved_filter_kinds, separators=(",", ":")),
            resolved_filter_predicate,
            resolved_filter_subject,
            resolved_filter_object,
            resolved_leg_limits["sql"],
            resolved_leg_limits["vector"],
            resolved_leg_limits["graph"],
            policy,
            FUSION_POLICY_FINGERPRINT,
            candidate_set_sha256,
            resolved_backend,
            resolved_adapter,
            resolved_embedding_model,
            int(embedding_dimension),
            resolved_embedding_revision,
            int(total_candidates),
            len(resolved_candidates),
            len(selected_ids),
            int(bool(candidates_truncated)),
            latencies["sql"],
            latencies["vector"] if latencies["vector"] is not None else latencies["chroma"],
            latencies["graph_node"],
            latencies["graph"],
            resolved_total_latency,
            resolved_created_at,
            resolved_graph_at,
            int(graph_include_history),
        ),
    )
    for candidate in resolved_candidates:
        connection.execute(
            """
            insert into reasoning_retrieval_candidate
                (candidate_id, retrieval_id, record_id, record_ns, record_scope,
                 record_sha256, rank, score, selected,
                 sources_json, reasons_json, disposition_reason, created_at,
                 schema_version)
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (
                f"reason-candidate:{uuid4().hex}",
                retrieval_id,
                candidate.record_id,
                run["ns"],
                run["scope"],
                candidate.record_sha256,
                candidate.rank,
                float(candidate.score),
                int(candidate.selected),
                json.dumps(
                    {key: float(value) for key, value in sorted(candidate.sources.items())},
                    separators=(",", ":"),
                ),
                json.dumps(candidate.reasons, separators=(",", ":")),
                "selected within budget" if candidate.selected else "below ranked cutoff",
                resolved_created_at,
            ),
        )
    transition_reasoning_node(
        connection,
        node_id=str(decision_node["node_id"]),
        status="accepted",
        reason="retrieval policy executed",
        actor=resolved_agent,
        created_at=resolved_created_at,
    )
    return get_reasoning_retrieval(connection, retrieval_id)


def record_reasoning_verification(
    connection: sqlite3.Connection,
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
    verification_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, object]:
    """Append one bounded public check result without retaining its raw output."""

    if not connection.in_transaction:
        connection.execute("begin immediate")
    run = _run_row(connection, run_id)
    subject = connection.execute(
        "select run_id, ns, scope from reasoning_node where node_id = ?",
        (subject_node_id,),
    ).fetchone()
    if subject is None:
        raise KeyError(f"reasoning node not found: {subject_node_id}")
    if (
        subject["run_id"] != run_id
        or subject["ns"] != run["ns"]
        or subject["scope"] != run["scope"]
    ):
        raise ValueError("verification subject does not belong to this session")

    resolved_kind = str(check_kind).strip().lower()
    if resolved_kind not in REASONING_CHECK_KINDS:
        raise ValueError(f"unsupported verification check kind: {check_kind}")
    resolved_ref = _required_text(check_ref, "verification check_ref", limit=512)
    resolved_verdict = str(verdict).strip().lower()
    if resolved_verdict not in REASONING_VERDICTS:
        raise ValueError(f"unsupported verification verdict: {verdict}")
    resolved_summary = _required_text(summary, "verification summary", limit=2048)
    if result is not None and not isinstance(result, str):
        raise TypeError("verification result must be a string")
    result_bytes = result.encode("utf-8") if result is not None else None
    result_sha256 = (
        hashlib.sha256(result_bytes).hexdigest() if result_bytes is not None else None
    )
    result_length = len(result_bytes) if result_bytes is not None else None
    if exit_code is not None and (
        isinstance(exit_code, bool) or not isinstance(exit_code, int)
    ):
        raise TypeError("verification exit_code must be an integer")
    if duration_ms is not None:
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, (int, float)):
            raise TypeError("verification duration_ms must be numeric")
        if not math.isfinite(float(duration_ms)) or float(duration_ms) < 0:
            raise ValueError("verification duration_ms must be finite and non-negative")
    resolved_knowledge = _reference_ids(
        knowledge_refs, "verification knowledge_refs"
    )
    resolved_evidence = _reference_ids(
        evidence_record_ids, "verification evidence_record_ids"
    )
    _validate_references(
        connection,
        ns=run["ns"],
        scope=run["scope"],
        knowledge_refs=resolved_knowledge,
        evidence_record_ids=resolved_evidence,
    )

    resolved_retry = None
    if retry_of is not None:
        resolved_retry = _required_text(retry_of, "verification retry_of", limit=128)
        prior = connection.execute(
            "select * from reasoning_verification where verification_id = ?",
            (resolved_retry,),
        ).fetchone()
        if prior is None:
            raise KeyError(f"reasoning verification not found: {resolved_retry}")
        if prior["run_id"] != run_id:
            raise ValueError("verification retry does not belong to this session")
        if (
            prior["subject_node_id"] != subject_node_id
            or prior["check_kind"] != resolved_kind
            or prior["check_ref"] != resolved_ref
        ):
            raise ValueError(
                "verification retry must use the same subject and check identity"
            )
        successor = connection.execute(
            "select verification_id from reasoning_verification where retry_of = ?",
            (resolved_retry,),
        ).fetchone()
        if successor is not None:
            raise ValueError("reasoning verification already has a retry")

    resolved_id = verification_id or f"reason-verify:{uuid4().hex}"
    resolved_created_at = created_at or utc_now()
    next_seq = int(
        connection.execute(
            "select coalesce(max(seq), 0) + 1 from reasoning_verification "
            "where run_id = ?",
            (run_id,),
        ).fetchone()[0]
    )
    connection.execute(
        """
        insert into reasoning_verification
            (verification_id, run_id, seq, ns, scope, subject_node_id,
             check_kind, check_ref, verdict, summary, result_sha256,
             result_length, exit_code, duration_ms, knowledge_refs_json,
             evidence_record_ids_json, agent_id, retry_of, created_at,
             schema_version)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            resolved_id,
            run_id,
            next_seq,
            run["ns"],
            run["scope"],
            subject_node_id,
            resolved_kind,
            resolved_ref,
            resolved_verdict,
            resolved_summary,
            result_sha256,
            result_length,
            exit_code,
            None if duration_ms is None else float(duration_ms),
            json.dumps(resolved_knowledge, separators=(",", ":")),
            json.dumps(resolved_evidence, separators=(",", ":")),
            agent_id or run["agent_id"],
            resolved_retry,
            resolved_created_at,
            REASONING_VERIFICATION_SCHEMA_VERSION,
        ),
    )
    return get_reasoning_verification(connection, resolved_id)


def _verification_from_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    compact: bool = False,
) -> dict[str, object]:
    successor = connection.execute(
        "select verification_id from reasoning_verification where retry_of = ?",
        (row["verification_id"],),
    ).fetchone()
    result: dict[str, object] = {
        "verification_id": row["verification_id"],
        "run_id": row["run_id"],
        "seq": row["seq"],
        "subject_node_id": row["subject_node_id"],
        "check_kind": row["check_kind"],
        "check_ref": row["check_ref"],
        "verdict": row["verdict"],
        "summary": row["summary"],
        "retry_of": row["retry_of"],
        "superseded_by": (
            successor["verification_id"] if successor is not None else None
        ),
        "created_at": row["created_at"],
        "schema_version": row["schema_version"],
    }
    if compact:
        result.pop("run_id")
        return result
    result.update(
        {
            "ns": row["ns"],
            "scope": row["scope"],
            "result_sha256": row["result_sha256"],
            "result_length": row["result_length"],
            "exit_code": row["exit_code"],
            "duration_ms": row["duration_ms"],
            "knowledge_refs": json.loads(row["knowledge_refs_json"]),
            "evidence_record_ids": json.loads(row["evidence_record_ids_json"]),
            "agent_id": row["agent_id"],
        }
    )
    return result


def get_reasoning_verification(
    connection: sqlite3.Connection, verification_id: str
) -> dict[str, object]:
    row = connection.execute(
        "select * from reasoning_verification where verification_id = ?",
        (verification_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"reasoning verification not found: {verification_id}")
    return _verification_from_row(connection, row)


def list_reasoning_verifications(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    limit: int = 100,
    after: str | None = None,
) -> list[dict[str, object]]:
    _run_row(connection, run_id)
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise TypeError("reasoning verification limit must be an integer")
    if not 1 <= limit <= 100:
        raise ValueError("reasoning verification limit must be between 1 and 100")
    clauses = ["run_id = ?"]
    params: list[object] = [run_id]
    if after is not None:
        cursor = connection.execute(
            "select seq from reasoning_verification "
            "where run_id = ? and verification_id = ?",
            (run_id, after),
        ).fetchone()
        if cursor is None:
            raise KeyError(f"reasoning verification cursor not found: {after}")
        clauses.append("seq > ?")
        params.append(cursor["seq"])
    params.append(limit)
    rows = connection.execute(
        f"select * from reasoning_verification where {' and '.join(clauses)} "
        "order by seq limit ?",
        tuple(params),
    ).fetchall()
    return [_verification_from_row(connection, row) for row in rows]


def finalize_verified_reasoning_outcome(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    summary: str,
    verification_ids: Iterable[str],
    confidence: float | None = None,
    knowledge_refs: Iterable[str] = (),
    evidence_record_ids: Iterable[str] = (),
    supporting_node_ids: Iterable[str] = (),
    agent_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, object]:
    """Atomically accept an outcome supported by current passed checks."""

    if not connection.in_transaction:
        connection.execute("begin immediate")
    bounded_ids = list(islice(iter(verification_ids), 65))
    if len(bounded_ids) > 64:
        raise ValueError("verified outcomes support at most 64 verifications")
    resolved_ids: list[str] = []
    for value in bounded_ids:
        if not isinstance(value, str):
            raise TypeError("verification_ids values must be strings")
        item = value.strip()
        if item and item not in resolved_ids:
            resolved_ids.append(item)
    if not resolved_ids:
        raise ValueError("verified outcomes require at least one verification")

    verification_rows: list[sqlite3.Row] = []
    for verification_id in resolved_ids:
        row = connection.execute(
            "select * from reasoning_verification where verification_id = ?",
            (verification_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"reasoning verification not found: {verification_id}")
        if row["run_id"] != run_id:
            raise ValueError("reasoning verification does not belong to this session")
        successor = connection.execute(
            "select 1 from reasoning_verification where retry_of = ?",
            (verification_id,),
        ).fetchone()
        if row["verdict"] != "passed" or successor is not None:
            raise ValueError(
                "verified outcomes require current passed verifications"
            )
        verification_rows.append(row)

    resolved_supporting = _reference_ids(
        supporting_node_ids, "supporting_node_ids"
    )
    resolved_created_at = created_at or utc_now()
    outcome = add_reasoning_node(
        connection,
        run_id=run_id,
        kind="outcome",
        summary=summary,
        confidence=confidence,
        agent_id=agent_id,
        knowledge_refs=knowledge_refs,
        evidence_record_ids=evidence_record_ids,
        created_at=resolved_created_at,
    )
    outcome_id = str(outcome["node_id"])
    support_ids = list(resolved_supporting)
    for row in verification_rows:
        subject_id = str(row["subject_node_id"])
        if subject_id not in support_ids:
            support_ids.append(subject_id)
    for subject_id in support_ids:
        add_reasoning_edge(
            connection,
            run_id=run_id,
            src_node_id=subject_id,
            relation="supports",
            dst_node_id=outcome_id,
            agent_id=agent_id,
            created_at=resolved_created_at,
        )
    for seq, verification_id in enumerate(resolved_ids, start=1):
        connection.execute(
            """
            insert into reasoning_outcome_verification
                (outcome_node_id, verification_id, seq, created_at, schema_version)
            values (?, ?, ?, ?, ?)
            """,
            (
                outcome_id,
                verification_id,
                seq,
                resolved_created_at,
                REASONING_VERIFICATION_SCHEMA_VERSION,
            ),
        )
    transition_reasoning_node(
        connection,
        node_id=outcome_id,
        status="accepted",
        reason="session outcome verified",
        actor=agent_id,
        created_at=resolved_created_at,
    )
    return get_reasoning_node(connection, outcome_id)


def _state_from_row(row: sqlite3.Row) -> dict[str, object]:
    return {
        "state_id": row["state_id"],
        "node_id": row["node_id"],
        "seq": row["seq"],
        "status": row["status"],
        "reason": row["reason"],
        "actor": row["actor"],
        "created_at": row["created_at"],
        "schema_version": row["schema_version"],
    }


def _node_from_row(
    connection: sqlite3.Connection, row: sqlite3.Row, *, include_history: bool
) -> dict[str, object]:
    states = connection.execute(
        "select * from reasoning_state where node_id = ? order by seq", (row["node_id"],)
    ).fetchall()
    result: dict[str, object] = {
        "node_id": row["node_id"],
        "run_id": row["run_id"],
        "seq": row["seq"],
        "kind": row["kind"],
        "summary": row["summary"],
        "confidence": row["confidence"],
        "status": states[-1]["status"],
        "ns": row["ns"],
        "scope": row["scope"],
        "agent_id": row["agent_id"],
        "operation": row["operation"],
        "knowledge_refs": json.loads(row["knowledge_refs_json"]),
        "evidence_record_ids": json.loads(row["evidence_record_ids_json"]),
        "created_at": row["created_at"],
        "schema_version": row["schema_version"],
        "verification_ids": [
            association["verification_id"]
            for association in connection.execute(
                "select verification_id from reasoning_outcome_verification "
                "where outcome_node_id = ? order by seq",
                (row["node_id"],),
            ).fetchall()
        ],
    }
    if include_history:
        result["state_history"] = [_state_from_row(state) for state in states]
    return result


def get_reasoning_node(
    connection: sqlite3.Connection, node_id: str, *, include_history: bool = True
) -> dict[str, object]:
    row = connection.execute(
        "select * from reasoning_node where node_id = ?", (node_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"reasoning node not found: {node_id}")
    return _node_from_row(connection, row, include_history=include_history)


def _retrieval_candidate_from_row(
    connection: sqlite3.Connection, row: sqlite3.Row
) -> dict[str, object]:
    current = connection.execute(
        "select ns, scope, payload_json from ir_records where id = ?",
        (row["record_id"],),
    ).fetchone()
    if current is None:
        integrity = "missing"
    elif current["ns"] != row["record_ns"] or current["scope"] != row["record_scope"]:
        integrity = "boundary_changed"
    elif hashlib.sha256(current["payload_json"].encode("utf-8")).hexdigest() != row[
        "record_sha256"
    ]:
        integrity = "content_changed"
    else:
        integrity = "current"
    return {
        "candidate_id": row["candidate_id"],
        "retrieval_id": row["retrieval_id"],
        "record_id": row["record_id"],
        "record_namespace": row["record_ns"],
        "record_scope": row["record_scope"],
        "record_sha256": row["record_sha256"],
        "record_integrity": integrity,
        "rank": row["rank"],
        "score": row["score"],
        "selected": bool(row["selected"]),
        "sources": json.loads(row["sources_json"]),
        "reason_codes": json.loads(row["reasons_json"]),
        "disposition_reason": row["disposition_reason"],
        "created_at": row["created_at"],
        "schema_version": row["schema_version"],
    }


def _retrieval_from_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    include_candidates: bool,
) -> dict[str, object]:
    result: dict[str, object] = {
        "retrieval_id": row["retrieval_id"],
        "run_id": row["run_id"],
        "seq": row["seq"],
        "query_node_id": row["query_node_id"],
        "decision_node_id": row["decision_node_id"],
        "query_sha256": row["query_sha256"],
        "normalized_query": row["normalized_query"],
        "planner": row["planner"],
        "mode": row["mode"],
        "intent": row["intent"],
        "budget": row["budget"],
        "graph_hops": row["graph_hops"],
        "semantic_graph_seeding": bool(row["semantic_graph_seeding"]),
        "graph_at": row["graph_at"],
        "graph_include_history": bool(row["graph_include_history"]),
        "filters": {
            "ids": json.loads(row["filter_ids_json"]),
            "kinds": json.loads(row["filter_kinds_json"]),
            "namespace": row["ns"],
            "scope": row["scope"],
            "predicate": row["filter_predicate"],
            "subject": row["filter_subject"],
            "object_text": row["filter_object_text"],
        },
        "leg_limits": {
            "sql": row["sql_limit"],
            "vector": row["vector_limit"],
            "graph": row["graph_limit"],
        },
        "policy": row["policy"],
        "policy_fingerprint": row["policy_fingerprint"],
        "candidate_set_sha256": row["candidate_set_sha256"],
        "semantic_backend": row["semantic_backend"],
        "semantic_adapter": row["semantic_adapter"],
        "embedding_model": row["embedding_model"],
        "embedding_dimension": row["embedding_dimension"],
        "embedding_revision": row["embedding_revision"],
        "total_candidates": row["total_candidates"],
        "recorded_candidates": row["recorded_candidates"],
        "selected_count": row["selected_count"],
        "candidates_truncated": bool(row["candidates_truncated"]),
        "latency_ms": {
            "sql": row["sql_latency_ms"],
            "vector": row["vector_latency_ms"],
            "graph_node": row["graph_node_latency_ms"],
            "graph": row["graph_latency_ms"],
            "total": row["total_latency_ms"],
        },
        "created_at": row["created_at"],
        "schema_version": row["schema_version"],
    }
    if include_candidates:
        candidate_rows = connection.execute(
            "select * from reasoning_retrieval_candidate "
            "where retrieval_id = ? order by rank",
            (row["retrieval_id"],),
        ).fetchall()
        result["candidates"] = [
            _retrieval_candidate_from_row(connection, candidate)
            for candidate in candidate_rows
        ]
    return result


def get_reasoning_retrieval(
    connection: sqlite3.Connection, retrieval_id: str
) -> dict[str, object]:
    row = connection.execute(
        "select * from reasoning_retrieval where retrieval_id = ?", (retrieval_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"reasoning retrieval not found: {retrieval_id}")
    return _retrieval_from_row(connection, row, include_candidates=True)


def list_reasoning_retrievals(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    limit: int = 100,
    after: str | None = None,
    include_candidates: bool = False,
) -> list[dict[str, object]]:
    _run_row(connection, run_id)
    if not 1 <= limit <= 100:
        raise ValueError("reasoning retrieval limit must be between 1 and 100")
    clauses = ["run_id = ?"]
    params: list[object] = [run_id]
    if after is not None:
        cursor = connection.execute(
            "select seq from reasoning_retrieval where run_id = ? and retrieval_id = ?",
            (run_id, after),
        ).fetchone()
        if cursor is None:
            raise KeyError(f"reasoning retrieval cursor not found: {after}")
        clauses.append("seq > ?")
        params.append(cursor["seq"])
    params.append(limit)
    rows = connection.execute(
        f"select * from reasoning_retrieval where {' and '.join(clauses)} "
        "order by seq limit ?",
        tuple(params),
    ).fetchall()
    return [
        _retrieval_from_row(
            connection, row, include_candidates=include_candidates
        )
        for row in rows
    ]


def reasoning_graph(connection: sqlite3.Connection, run_id: str) -> dict[str, object]:
    run = _run_row(connection, run_id)
    node_rows = connection.execute(
        "select * from reasoning_node where run_id = ? order by seq", (run_id,)
    ).fetchall()
    edge_rows = connection.execute(
        "select * from reasoning_edge where run_id = ? order by seq", (run_id,)
    ).fetchall()
    retrieval_rows = connection.execute(
        "select * from reasoning_retrieval where run_id = ? "
        "order by seq limit 101",
        (run_id,),
    ).fetchall()
    verification_rows = connection.execute(
        "select * from reasoning_verification where run_id = ? "
        "order by seq limit 101",
        (run_id,),
    ).fetchall()
    return {
        "run_id": run_id,
        "ns": run["ns"],
        "scope": run["scope"],
        "canonical_truth": False,
        "automatic_promotion": False,
        "retrievals": [
            _retrieval_from_row(connection, row, include_candidates=False)
            for row in retrieval_rows[:100]
        ],
        "retrievals_truncated": len(retrieval_rows) > 100,
        "verifications": [
            _verification_from_row(connection, row, compact=True)
            for row in verification_rows[:100]
        ],
        "verifications_truncated": len(verification_rows) > 100,
        "nodes": [
            _node_from_row(connection, row, include_history=True) for row in node_rows
        ],
        "edges": [
            {
                "edge_id": row["edge_id"],
                "run_id": row["run_id"],
                "seq": row["seq"],
                "src_node_id": row["src_node_id"],
                "relation": row["relation"],
                "dst_node_id": row["dst_node_id"],
                "agent_id": row["agent_id"],
                "created_at": row["created_at"],
                "schema_version": row["schema_version"],
            }
            for row in edge_rows
        ],
    }
