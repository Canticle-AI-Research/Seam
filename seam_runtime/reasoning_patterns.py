from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime
from uuid import uuid4

from .migrations import execute_script
from .mirl import utc_now
from .temporal import parse_iso

REASONING_PATTERN_SCHEMA_VERSION = 2
DEFAULT_PATTERN_MAX_AGE_DAYS = 90
DEFAULT_PATTERN_MIN_TRUST = 0.5
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9_.:/+-]*")
_INACTIVE_KNOWLEDGE_STATUSES = frozenset(
    {"contradicted", "superseded", "deprecated", "deleted_soft"}
)
_TASK_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "for",
        "how",
        "in",
        "is",
        "of",
        "on",
        "the",
        "to",
        "what",
        "which",
        "with",
    }
)


def init_reasoning_patterns(connection: sqlite3.Connection) -> None:
    """Create the append-only R4 reasoning-pattern plane.

    Patterns contain only a public structural recipe (node kinds, controlled
    operations, edge relations, and check kinds). They never copy node
    summaries, conclusions, raw tool output, provider payloads, or hidden
    chain-of-thought.
    """

    execute_script(
        connection,
        """
        create table if not exists reasoning_pattern (
            pattern_id text primary key,
            source_run_id text not null,
            source_outcome_node_id text not null unique,
            ns text not null,
            scope text not null,
            task_terms_json text not null,
            task_signature text not null,
            operation text,
            template_json text not null,
            verification_ids_json text not null,
            knowledge_refs_json text not null,
            evidence_fingerprints_json text not null,
            created_at text not null,
            schema_version integer not null default 1,
            foreign key (source_run_id) references workspace_run(run_id),
            foreign key (source_outcome_node_id) references reasoning_node(node_id)
        );
        create table if not exists reasoning_pattern_use (
            use_id text primary key,
            pattern_id text not null,
            run_id text not null,
            created_at text not null,
            schema_version integer not null default 1,
            foreign key (pattern_id) references reasoning_pattern(pattern_id),
            foreign key (run_id) references workspace_run(run_id),
            unique (pattern_id, run_id)
        );
        create table if not exists reasoning_pattern_result (
            result_id text primary key,
            use_id text not null unique,
            outcome_node_id text,
            succeeded integer not null check (succeeded in (0, 1)),
            reason text,
            created_at text not null,
            schema_version integer not null default 1,
            foreign key (use_id) references reasoning_pattern_use(use_id),
            foreign key (outcome_node_id) references reasoning_node(node_id)
        );
        create table if not exists reasoning_pattern_result_disagreement (
            disagreement_id text primary key,
            use_id text not null,
            prior_result_id text not null,
            outcome_node_id text,
            succeeded integer not null check (succeeded in (0, 1)),
            reason text,
            created_at text not null,
            schema_version integer not null default 1,
            foreign key (use_id) references reasoning_pattern_use(use_id),
            foreign key (prior_result_id) references reasoning_pattern_result(result_id),
            foreign key (outcome_node_id) references reasoning_node(node_id)
        );
        create index if not exists idx_reasoning_pattern_boundary
            on reasoning_pattern (ns, scope, created_at);
        create index if not exists idx_reasoning_pattern_signature
            on reasoning_pattern (task_signature);
        create index if not exists idx_reasoning_pattern_use_run
            on reasoning_pattern_use (run_id);
        create index if not exists idx_reasoning_pattern_disagreement_use
            on reasoning_pattern_result_disagreement (use_id, created_at);
        create unique index if not exists idx_reasoning_pattern_disagreement_identity
            on reasoning_pattern_result_disagreement (
                use_id,
                succeeded,
                coalesce(outcome_node_id, '')
            );
        create trigger if not exists reasoning_pattern_no_update
        before update on reasoning_pattern begin
            select raise(abort, 'reasoning_pattern is append-only');
        end;
        create trigger if not exists reasoning_pattern_no_delete
        before delete on reasoning_pattern begin
            select raise(abort, 'reasoning_pattern is append-only');
        end;
        create trigger if not exists reasoning_pattern_use_no_update
        before update on reasoning_pattern_use begin
            select raise(abort, 'reasoning_pattern_use is append-only');
        end;
        create trigger if not exists reasoning_pattern_use_no_delete
        before delete on reasoning_pattern_use begin
            select raise(abort, 'reasoning_pattern_use is append-only');
        end;
        create trigger if not exists reasoning_pattern_result_no_update
        before update on reasoning_pattern_result begin
            select raise(abort, 'reasoning_pattern_result is append-only');
        end;
        create trigger if not exists reasoning_pattern_result_no_delete
        before delete on reasoning_pattern_result begin
            select raise(abort, 'reasoning_pattern_result is append-only');
        end;
        create trigger if not exists reasoning_pattern_disagreement_no_update
        before update on reasoning_pattern_result_disagreement begin
            select raise(abort, 'reasoning_pattern_result_disagreement is append-only');
        end;
        create trigger if not exists reasoning_pattern_disagreement_no_delete
        before delete on reasoning_pattern_result_disagreement begin
            select raise(abort, 'reasoning_pattern_result_disagreement is append-only');
        end;
        create trigger if not exists reasoning_pattern_disagreement_prior_guard
        before insert on reasoning_pattern_result_disagreement
        when not exists (
            select 1 from reasoning_pattern_result r
            where r.result_id = new.prior_result_id
              and r.use_id = new.use_id
        ) begin
            select raise(abort, 'reasoning pattern disagreement prior result does not match use');
        end;
        create trigger if not exists reasoning_pattern_use_scope_guard
        before insert on reasoning_pattern_use
        when not exists (
            select 1
            from reasoning_pattern p
            join workspace_run r on r.run_id = new.run_id
            where p.pattern_id = new.pattern_id
              and p.ns = r.ns and p.scope = r.scope
        ) begin
            select raise(abort, 'reasoning pattern use crosses namespace or scope');
        end;
        create trigger if not exists reasoning_pattern_result_guard
        before insert on reasoning_pattern_result
        when new.succeeded = 1 and (
            new.outcome_node_id is null or not exists (
                select 1
                from reasoning_pattern_use u
                join reasoning_node n on n.node_id = new.outcome_node_id
                join reasoning_state s on s.node_id = n.node_id
                where u.use_id = new.use_id
                  and n.run_id = u.run_id
                  and n.kind = 'outcome'
                  and s.seq = (
                      select max(latest.seq) from reasoning_state latest
                      where latest.node_id = n.node_id
                  )
                  and s.status = 'accepted'
                  and exists (
                      select 1 from reasoning_outcome_verification ov
                      where ov.outcome_node_id = n.node_id
                  )
            )
        ) begin
            select raise(abort, 'successful pattern use requires a verified accepted outcome');
        end;
        create trigger if not exists reasoning_pattern_disagreement_guard
        before insert on reasoning_pattern_result_disagreement
        when new.succeeded = 1 and (
            new.outcome_node_id is null or not exists (
                select 1
                from reasoning_pattern_use u
                join reasoning_node n on n.node_id = new.outcome_node_id
                join reasoning_state s on s.node_id = n.node_id
                where u.use_id = new.use_id
                  and n.run_id = u.run_id
                  and n.kind = 'outcome'
                  and s.seq = (
                      select max(latest.seq) from reasoning_state latest
                      where latest.node_id = n.node_id
                  )
                  and s.status = 'accepted'
                  and exists (
                      select 1 from reasoning_outcome_verification ov
                      where ov.outcome_node_id = n.node_id
                  )
            )
        ) begin
            select raise(abort, 'successful pattern disagreement requires a verified accepted outcome');
        end;
        """
    )


def _task_terms(text: str) -> tuple[str, ...]:
    terms = {
        match.group(0)
        for match in _WORD_RE.finditer(str(text).lower())
        if match.group(0) not in _TASK_STOPWORDS
    }
    return tuple(sorted(terms))[:128]


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _json_list(value: object) -> list[str]:
    if not isinstance(value, str):
        return []
    loaded = json.loads(value)
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded if isinstance(item, str) and item]


def _latest_status(connection: sqlite3.Connection, node_id: str) -> str | None:
    row = connection.execute(
        "select status from reasoning_state where node_id = ? order by seq desc limit 1",
        (node_id,),
    ).fetchone()
    return str(row["status"]) if row is not None else None


def _current_verification(
    connection: sqlite3.Connection, verification_id: str, run_id: str
) -> sqlite3.Row | None:
    row = connection.execute(
        "select * from reasoning_verification "
        "where verification_id = ? and run_id = ? and verdict = 'passed'",
        (verification_id, run_id),
    ).fetchone()
    if row is None:
        return None
    successor = connection.execute(
        "select 1 from reasoning_verification where retry_of = ?",
        (verification_id,),
    ).fetchone()
    return None if successor is not None else row


def _record_fingerprints(
    connection: sqlite3.Connection, record_ids: set[str]
) -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    for record_id in sorted(record_ids):
        row = connection.execute(
            "select payload_json from ir_records where id = ?", (record_id,)
        ).fetchone()
        if row is not None and isinstance(row["payload_json"], str):
            fingerprints[record_id] = _sha256_text(str(row["payload_json"]))
    return fingerprints


def _mapped_step(
    key_by_id: dict[str, str], node_id: object, *, role: str
) -> str:
    resolved_id = str(node_id)
    try:
        return key_by_id[resolved_id]
    except KeyError as exc:
        raise ValueError(
            f"reasoning pattern {role} node is outside the source run: "
            f"{resolved_id}"
        ) from exc


def distill_reasoning_pattern(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    outcome_node_id: str,
    verification_ids: tuple[str, ...],
    created_at: str | None = None,
) -> dict[str, object]:
    """Distill a verified run into a content-free structural reasoning recipe."""

    outcome = connection.execute(
        "select * from reasoning_node where node_id = ? and run_id = ? and kind = 'outcome'",
        (outcome_node_id, run_id),
    ).fetchone()
    if outcome is None or _latest_status(connection, outcome_node_id) != "accepted":
        raise ValueError("reasoning patterns require an accepted outcome")
    existing = connection.execute(
        "select pattern_id from reasoning_pattern where source_outcome_node_id = ?",
        (outcome_node_id,),
    ).fetchone()
    if existing is not None:
        return get_reasoning_pattern(connection, str(existing["pattern_id"]))

    verified_rows: list[sqlite3.Row] = []
    for verification_id in verification_ids:
        row = _current_verification(connection, verification_id, run_id)
        if row is None:
            raise ValueError("reasoning patterns require current passed verifications")
        verified_rows.append(row)
    if not verified_rows:
        raise ValueError("reasoning patterns require verification provenance")

    nodes = connection.execute(
        "select * from reasoning_node where run_id = ? order by seq", (run_id,)
    ).fetchall()
    edges = connection.execute(
        "select * from reasoning_edge where run_id = ? order by seq", (run_id,)
    ).fetchall()
    objective = next((row for row in nodes if row["kind"] == "objective"), None)
    if objective is None:
        raise ValueError("reasoning pattern source run has no objective")

    key_by_id = {str(row["node_id"]): f"step:{index}" for index, row in enumerate(nodes, 1)}
    steps = [
        {
            "key": key_by_id[str(row["node_id"])],
            "kind": str(row["kind"]),
            "operation": str(row["operation"]) if row["operation"] else None,
        }
        for row in nodes
    ]
    links = [
        {
            "source": _mapped_step(
                key_by_id, row["src_node_id"], role="edge source"
            ),
            "relation": str(row["relation"]),
            "target": _mapped_step(
                key_by_id, row["dst_node_id"], role="edge target"
            ),
        }
        for row in edges
    ]
    checks = [
        {
            "subject": _mapped_step(
                key_by_id, row["subject_node_id"], role="verification subject"
            ),
            "kind": str(row["check_kind"]),
        }
        for row in verified_rows
    ]
    template = {
        "version": "reasoning-pattern/1",
        "steps": steps,
        "links": links,
        "checks": checks,
    }

    knowledge_refs: set[str] = set()
    evidence_ids: set[str] = set()
    operations: list[str] = []
    for row in [*nodes, *verified_rows]:
        columns = set(row.keys())
        if "knowledge_refs_json" in columns:
            knowledge_refs.update(_json_list(row["knowledge_refs_json"]))
        if "evidence_record_ids_json" in columns:
            evidence_ids.update(_json_list(row["evidence_record_ids_json"]))
        if "operation" in columns and row["operation"]:
            operations.append(str(row["operation"]))
    for node_id in sorted(knowledge_refs):
        row = connection.execute(
            "select source_record_id from knowledge_nodes where id = ?", (node_id,)
        ).fetchone()
        if row is not None and row["source_record_id"]:
            evidence_ids.add(str(row["source_record_id"]))

    terms = _task_terms(str(objective["summary"]))
    operation = operations[0] if operations else None
    signature_material = json.dumps(
        {"terms": terms, "operation": operation},
        sort_keys=True,
        separators=(",", ":"),
    )
    pattern_id = f"rpat:{uuid4().hex}"
    resolved_created_at = created_at or utc_now()
    connection.execute(
        """
        insert into reasoning_pattern
            (pattern_id, source_run_id, source_outcome_node_id, ns, scope,
             task_terms_json, task_signature, operation, template_json,
             verification_ids_json, knowledge_refs_json,
             evidence_fingerprints_json, created_at, schema_version)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            pattern_id,
            run_id,
            outcome_node_id,
            outcome["ns"],
            outcome["scope"],
            json.dumps(terms, separators=(",", ":")),
            _sha256_text(signature_material),
            operation,
            json.dumps(template, sort_keys=True, separators=(",", ":")),
            json.dumps(list(verification_ids), separators=(",", ":")),
            json.dumps(sorted(knowledge_refs), separators=(",", ":")),
            json.dumps(
                _record_fingerprints(connection, evidence_ids),
                sort_keys=True,
                separators=(",", ":"),
            ),
            resolved_created_at,
            REASONING_PATTERN_SCHEMA_VERSION,
        ),
    )
    return get_reasoning_pattern(connection, pattern_id)


def _pattern_stats(
    connection: sqlite3.Connection, pattern_id: str
) -> tuple[int, int, int, int]:
    row = connection.execute(
        """
        select
            count(u.use_id) as uses,
            coalesce(sum(case when r.succeeded = 1 then 1 else 0 end), 0) as successes,
            coalesce(sum(case when r.succeeded = 0 then 1 else 0 end), 0) as failures
        from reasoning_pattern_use u
        left join reasoning_pattern_result r on r.use_id = u.use_id
        where u.pattern_id = ?
        """,
        (pattern_id,),
    ).fetchone()
    disagreement = connection.execute(
        """
        select
            count(d.disagreement_id) as disagreements,
            coalesce(sum(case when d.succeeded = 1 then 1 else 0 end), 0) as successes,
            coalesce(sum(case when d.succeeded = 0 then 1 else 0 end), 0) as failures
        from reasoning_pattern_result_disagreement d
        join reasoning_pattern_use u on u.use_id = d.use_id
        where u.pattern_id = ?
        """,
        (pattern_id,),
    ).fetchone()
    return (
        int(row["uses"]),
        int(row["successes"]) + int(disagreement["successes"]),
        int(row["failures"]) + int(disagreement["failures"]),
        int(disagreement["disagreements"]),
    )


def _pattern_disagreements(
    connection: sqlite3.Connection, pattern_id: str
) -> list[dict[str, object]]:
    rows = connection.execute(
        """
        select d.*, r.succeeded as prior_succeeded
        from reasoning_pattern_result_disagreement d
        join reasoning_pattern_use u on u.use_id = d.use_id
        join reasoning_pattern_result r on r.result_id = d.prior_result_id
        where u.pattern_id = ?
        order by d.created_at, d.disagreement_id
        """,
        (pattern_id,),
    ).fetchall()
    return [
        {
            "disagreement_id": str(row["disagreement_id"]),
            "use_id": str(row["use_id"]),
            "prior_result_id": str(row["prior_result_id"]),
            "prior_succeeded": bool(row["prior_succeeded"]),
            "later_succeeded": bool(row["succeeded"]),
            "outcome_node_id": row["outcome_node_id"],
            "reason": row["reason"],
            "created_at": str(row["created_at"]),
        }
        for row in rows
    ]


def _pattern_validity(
    connection: sqlite3.Connection, row: sqlite3.Row
) -> tuple[bool, str]:
    run_id = str(row["source_run_id"])
    if _latest_status(connection, str(row["source_outcome_node_id"])) != "accepted":
        return False, "source outcome is no longer accepted"
    for verification_id in _json_list(row["verification_ids_json"]):
        if _current_verification(connection, verification_id, run_id) is None:
            return False, "verification provenance is stale or superseded"
    fingerprints = json.loads(row["evidence_fingerprints_json"] or "{}")
    if not isinstance(fingerprints, dict):
        return False, "evidence fingerprint ledger is malformed"
    for record_id, expected in fingerprints.items():
        current = connection.execute(
            "select ns, scope, payload_json from ir_records where id = ?",
            (record_id,),
        ).fetchone()
        if (
            current is None
            or current["ns"] != row["ns"]
            or current["scope"] != row["scope"]
            or _sha256_text(str(current["payload_json"])) != expected
        ):
            return False, f"evidence drift detected for {record_id}"
    for node_id in _json_list(row["knowledge_refs_json"]):
        current = connection.execute(
            "select ns, scope, status from knowledge_nodes where id = ?", (node_id,)
        ).fetchone()
        if (
            current is None
            or current["ns"] != row["ns"]
            or current["scope"] != row["scope"]
            or str(current["status"]) in _INACTIVE_KNOWLEDGE_STATUSES
        ):
            return False, f"knowledge provenance is stale for {node_id}"
    return True, "current verified provenance"


def _parse_timestamp(value: str) -> datetime:
    parsed = parse_iso(value)
    if parsed is None:
        raise ValueError("timestamp must be valid ISO-8601")
    return parsed


def _pattern_payload(
    connection: sqlite3.Connection, row: sqlite3.Row
) -> dict[str, object]:
    uses, reuse_successes, failures, disagreement_count = _pattern_stats(
        connection, str(row["pattern_id"])
    )
    successes = 1 + reuse_successes
    trust = successes / (successes + failures)
    return {
        "pattern_id": str(row["pattern_id"]),
        "source_run_id": str(row["source_run_id"]),
        "source_outcome_node_id": str(row["source_outcome_node_id"]),
        "namespace": str(row["ns"]),
        "scope": str(row["scope"]),
        "task_terms": _json_list(row["task_terms_json"]),
        "task_signature": str(row["task_signature"]),
        "operation": row["operation"],
        "template": json.loads(row["template_json"]),
        "verification_ids": _json_list(row["verification_ids_json"]),
        "knowledge_refs": _json_list(row["knowledge_refs_json"]),
        "evidence_record_ids": sorted(
            json.loads(row["evidence_fingerprints_json"] or "{}")
        ),
        "uses": uses,
        "successes": successes,
        "failures": failures,
        "disagreement_count": disagreement_count,
        "disagreements": _pattern_disagreements(
            connection, str(row["pattern_id"])
        ),
        "trust_score": trust,
        "created_at": str(row["created_at"]),
        "schema_version": int(row["schema_version"]),
    }


def get_reasoning_pattern(
    connection: sqlite3.Connection, pattern_id: str
) -> dict[str, object]:
    row = connection.execute(
        "select * from reasoning_pattern where pattern_id = ?", (pattern_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"reasoning pattern not found: {pattern_id}")
    payload = _pattern_payload(connection, row)
    valid, reason = _pattern_validity(connection, row)
    payload["provenance_current"] = valid
    payload["provenance_status"] = reason
    return payload


def search_reasoning_patterns(
    connection: sqlite3.Connection,
    *,
    objective: str,
    ns: str,
    scope: str,
    operation: str | None = None,
    limit: int = 5,
    max_age_days: int = DEFAULT_PATTERN_MAX_AGE_DAYS,
    min_trust: float = DEFAULT_PATTERN_MIN_TRUST,
    now: str | None = None,
) -> list[dict[str, object]]:
    if not isinstance(objective, str) or not objective.strip():
        raise ValueError("reasoning pattern objective is required")
    if not 1 <= limit <= 50:
        raise ValueError("reasoning pattern limit must be between 1 and 50")
    if max_age_days < 1:
        raise ValueError("reasoning pattern max_age_days must be positive")
    if not 0 <= min_trust <= 1:
        raise ValueError("reasoning pattern min_trust must be between 0 and 1")
    query_terms = set(_task_terms(objective))
    horizon = _parse_timestamp(now or utc_now())
    ranked: list[tuple[float, str, dict[str, object]]] = []
    rows = connection.execute(
        "select * from reasoning_pattern where ns = ? and scope = ? order by created_at desc",
        (ns, scope),
    ).fetchall()
    for row in rows:
        valid, reason = _pattern_validity(connection, row)
        if not valid:
            continue
        age_days = max(
            0.0,
            (horizon - _parse_timestamp(str(row["created_at"]))).total_seconds()
            / 86400.0,
        )
        if age_days > max_age_days:
            continue
        payload = _pattern_payload(connection, row)
        trust = float(payload["trust_score"])
        if trust < min_trust:
            continue
        pattern_terms = set(payload["task_terms"])
        union = query_terms | pattern_terms
        similarity = len(query_terms & pattern_terms) / len(union) if union else 0.0
        operation_match = bool(
            operation
            and payload["operation"]
            and str(payload["operation"]).lower() == operation.strip().lower()
        )
        if similarity == 0 and not operation_match:
            continue
        freshness = max(0.0, 1.0 - age_days / max_age_days)
        score = (
            similarity * 0.55
            + (0.15 if operation_match else 0.0)
            + trust * 0.20
            + freshness * 0.05
            + min(0.05, math.log1p(int(payload["successes"])) * 0.02)
        )
        payload.update(
            {
                "match_score": score,
                "task_similarity": similarity,
                "operation_match": operation_match,
                "freshness": freshness,
                "provenance_current": True,
                "provenance_status": reason,
            }
        )
        ranked.append((score, str(payload["pattern_id"]), payload))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [payload for _score, _pattern_id, payload in ranked[:limit]]


def use_reasoning_pattern(
    connection: sqlite3.Connection,
    *,
    pattern_id: str,
    run_id: str,
    created_at: str | None = None,
) -> dict[str, object]:
    pattern = connection.execute(
        "select * from reasoning_pattern where pattern_id = ?", (pattern_id,)
    ).fetchone()
    if pattern is None:
        raise KeyError(f"reasoning pattern not found: {pattern_id}")
    valid, reason = _pattern_validity(connection, pattern)
    if not valid:
        raise ValueError(f"reasoning pattern is not reusable: {reason}")
    existing = connection.execute(
        "select * from reasoning_pattern_use where pattern_id = ? and run_id = ?",
        (pattern_id, run_id),
    ).fetchone()
    if existing is None:
        use_id = f"ruse:{uuid4().hex}"
        resolved_created_at = created_at or utc_now()
        connection.execute(
            "insert into reasoning_pattern_use "
            "(use_id, pattern_id, run_id, created_at, schema_version) "
            "values (?, ?, ?, ?, ?)",
            (
                use_id,
                pattern_id,
                run_id,
                resolved_created_at,
                REASONING_PATTERN_SCHEMA_VERSION,
            ),
        )
    else:
        use_id = str(existing["use_id"])
        resolved_created_at = str(existing["created_at"])
    return {
        "use_id": use_id,
        "pattern": get_reasoning_pattern(connection, pattern_id),
        "run_id": run_id,
        "created_at": resolved_created_at,
    }


def record_reasoning_pattern_result(
    connection: sqlite3.Connection,
    *,
    use_id: str,
    succeeded: bool,
    expected_run_id: str | None = None,
    outcome_node_id: str | None = None,
    reason: str | None = None,
    created_at: str | None = None,
) -> dict[str, object]:
    if not isinstance(succeeded, bool):
        raise TypeError("reasoning pattern result succeeded must be a boolean")
    use = connection.execute(
        "select run_id from reasoning_pattern_use where use_id = ?", (use_id,)
    ).fetchone()
    if use is None:
        raise KeyError(f"reasoning pattern use not found: {use_id}")
    if (
        expected_run_id is not None
        and str(use["run_id"]) != expected_run_id
    ):
        raise ValueError("reasoning pattern use does not belong to this run")
    normalized_reason = str(reason).strip() if reason is not None else ""
    resolved_reason = normalized_reason[:1024] or None
    existing = connection.execute(
        "select * from reasoning_pattern_result where use_id = ?", (use_id,)
    ).fetchone()
    if existing is not None:
        prior = {
            "result_id": str(existing["result_id"]),
            "use_id": str(existing["use_id"]),
            "outcome_node_id": existing["outcome_node_id"],
            "succeeded": bool(existing["succeeded"]),
            "reason": existing["reason"],
            "created_at": str(existing["created_at"]),
        }
        if (
            prior["succeeded"] == succeeded
            and prior["outcome_node_id"] == outcome_node_id
        ):
            return prior
        disagreement = connection.execute(
            "select * from reasoning_pattern_result_disagreement "
            "where use_id = ? and succeeded = ? "
            "and coalesce(outcome_node_id, '') = coalesce(?, '')",
            (use_id, int(succeeded), outcome_node_id),
        ).fetchone()
        if disagreement is None:
            disagreement_id = f"rdis:{uuid4().hex}"
            resolved_created_at = created_at or utc_now()
            disagreement_prior_result_id = str(prior["result_id"])
            connection.execute(
                "insert into reasoning_pattern_result_disagreement "
                "(disagreement_id, use_id, prior_result_id, outcome_node_id, "
                "succeeded, reason, created_at, schema_version) "
                "values (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    disagreement_id,
                    use_id,
                    prior["result_id"],
                    outcome_node_id,
                    int(succeeded),
                    resolved_reason,
                    resolved_created_at,
                    REASONING_PATTERN_SCHEMA_VERSION,
                ),
            )
        else:
            disagreement_id = str(disagreement["disagreement_id"])
            resolved_created_at = str(disagreement["created_at"])
            disagreement_prior_result_id = str(disagreement["prior_result_id"])
            outcome_node_id = disagreement["outcome_node_id"]
            succeeded = bool(disagreement["succeeded"])
            resolved_reason = disagreement["reason"]
        return {
            "result_id": disagreement_id,
            "use_id": use_id,
            "outcome_node_id": outcome_node_id,
            "succeeded": succeeded,
            "reason": resolved_reason,
            "created_at": resolved_created_at,
            "disagrees_with": disagreement_prior_result_id,
        }
    result_id = f"rres:{uuid4().hex}"
    resolved_created_at = created_at or utc_now()
    connection.execute(
        "insert into reasoning_pattern_result "
        "(result_id, use_id, outcome_node_id, succeeded, reason, created_at, schema_version) "
        "values (?, ?, ?, ?, ?, ?, ?)",
        (
            result_id,
            use_id,
            outcome_node_id,
            int(succeeded),
            resolved_reason,
            resolved_created_at,
            REASONING_PATTERN_SCHEMA_VERSION,
        ),
    )
    return {
        "result_id": result_id,
        "use_id": use_id,
        "outcome_node_id": outcome_node_id,
        "succeeded": succeeded,
        "reason": resolved_reason,
        "created_at": resolved_created_at,
    }


def record_successful_pattern_uses(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    outcome_node_id: str,
    created_at: str | None = None,
) -> list[dict[str, object]]:
    rows = connection.execute(
        "select use_id from reasoning_pattern_use where run_id = ? order by created_at",
        (run_id,),
    ).fetchall()
    results = []
    for row in rows:
        results.append(
            record_reasoning_pattern_result(
                connection,
                use_id=str(row["use_id"]),
                succeeded=True,
                expected_run_id=run_id,
                outcome_node_id=outcome_node_id,
                reason="pattern reuse supported a verified accepted outcome",
                created_at=created_at,
            )
        )
    return results
