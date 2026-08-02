"""Reviewed, append-only promotion proposals for verified reasoning outcomes.

This module deliberately stops at an approved MIRL assertion payload.  It does
not insert that payload into ``ir_records``; a later store integration must do
that in an explicit canonical MIRL transaction.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Iterable
from itertools import islice
from uuid import uuid4

from .migrations import execute_script
from .mirl import SCHEMA_VERSION, utc_now

REASONING_PROMOTION_SCHEMA_VERSION = 1
PROMOTION_REVIEW_KINDS = frozenset({"human", "policy"})
PROMOTION_REVIEW_DECISIONS = frozenset({"approved", "rejected"})
PROMOTABLE_ASSERTION_STATUSES = frozenset(
    {"asserted", "observed", "inferred", "hypothetical"}
)
_INACTIVE_KNOWLEDGE_STATUSES = frozenset(
    {"contradicted", "superseded", "deprecated", "deleted_soft"}
)


def init_reasoning_promotion(connection: sqlite3.Connection) -> None:
    """Create the isolated R5 reviewed-promotion ledger."""

    execute_script(
        connection,
        """
        create table if not exists reasoning_promotion_proposal (
            proposal_id text primary key,
            run_id text not null,
            outcome_node_id text not null,
            ns text not null,
            scope text not null,
            assertion_record_id text not null,
            assertion_kind text not null check (assertion_kind = 'CLM'),
            assertion_subject text not null,
            assertion_predicate text not null,
            assertion_object_json text not null,
            assertion_status text not null check (assertion_status in
                ('asserted', 'observed', 'inferred', 'hypothetical')),
            assertion_confidence real not null check (
                assertion_confidence >= 0 and assertion_confidence <= 1
            ),
            assertion_t0 text,
            assertion_t1 text,
            verification_ids_json text not null,
            knowledge_refs_json text not null,
            evidence_fingerprints_json text not null,
            proposal_sha256 text not null check (
                length(proposal_sha256) = 64
                and proposal_sha256 not glob '*[^0-9a-f]*'
            ),
            proposed_by text not null,
            created_at text not null,
            schema_version integer not null default 1,
            foreign key (run_id) references workspace_run(run_id),
            foreign key (outcome_node_id) references reasoning_node(node_id),
            unique (ns, scope, assertion_record_id)
        );
        create table if not exists reasoning_promotion_review (
            review_id text primary key,
            proposal_id text not null,
            seq integer not null check (seq >= 1),
            review_kind text not null check (review_kind in ('human', 'policy')),
            decision text not null check (decision in ('approved', 'rejected')),
            reviewer_id text not null,
            rationale text not null,
            created_at text not null,
            schema_version integer not null default 1,
            foreign key (proposal_id)
                references reasoning_promotion_proposal(proposal_id),
            unique (proposal_id, seq)
        );
        create table if not exists reasoning_promotion_application (
            application_id text primary key,
            proposal_id text not null unique,
            assertion_record_id text not null unique,
            assertion_sha256 text not null check (
                length(assertion_sha256) = 64
                and assertion_sha256 not glob '*[^0-9a-f]*'
            ),
            applied_by text not null,
            created_at text not null,
            schema_version integer not null default 1,
            foreign key (proposal_id)
                references reasoning_promotion_proposal(proposal_id)
        );
        create table if not exists reasoning_promotion_reversal (
            reversal_id text primary key,
            proposal_id text not null unique,
            application_id text not null unique,
            assertion_record_id text not null,
            assertion_sha256 text not null check (
                length(assertion_sha256) = 64
                and assertion_sha256 not glob '*[^0-9a-f]*'
            ),
            reversed_by text not null,
            reason text not null,
            created_at text not null,
            schema_version integer not null default 1,
            foreign key (proposal_id)
                references reasoning_promotion_proposal(proposal_id),
            foreign key (application_id)
                references reasoning_promotion_application(application_id)
        );
        create index if not exists idx_reasoning_promotion_boundary
            on reasoning_promotion_proposal (ns, scope, created_at);
        create index if not exists idx_reasoning_promotion_outcome
            on reasoning_promotion_proposal (outcome_node_id, created_at);
        create index if not exists idx_reasoning_promotion_review
            on reasoning_promotion_review (proposal_id, seq);
        create trigger if not exists reasoning_promotion_proposal_no_update
        before update on reasoning_promotion_proposal begin
            select raise(abort, 'reasoning_promotion_proposal is append-only');
        end;
        create trigger if not exists reasoning_promotion_proposal_no_delete
        before delete on reasoning_promotion_proposal begin
            select raise(abort, 'reasoning_promotion_proposal is append-only');
        end;
        create trigger if not exists reasoning_promotion_review_no_update
        before update on reasoning_promotion_review begin
            select raise(abort, 'reasoning_promotion_review is append-only');
        end;
        create trigger if not exists reasoning_promotion_review_no_delete
        before delete on reasoning_promotion_review begin
            select raise(abort, 'reasoning_promotion_review is append-only');
        end;
        create trigger if not exists reasoning_promotion_application_no_update
        before update on reasoning_promotion_application begin
            select raise(abort, 'reasoning_promotion_application is append-only');
        end;
        create trigger if not exists reasoning_promotion_application_no_delete
        before delete on reasoning_promotion_application begin
            select raise(abort, 'reasoning_promotion_application is append-only');
        end;
        create trigger if not exists reasoning_promotion_reversal_no_update
        before update on reasoning_promotion_reversal begin
            select raise(abort, 'reasoning_promotion_reversal is append-only');
        end;
        create trigger if not exists reasoning_promotion_reversal_no_delete
        before delete on reasoning_promotion_reversal begin
            select raise(abort, 'reasoning_promotion_reversal is append-only');
        end;
        create trigger if not exists reasoning_promotion_proposal_scope_guard
        before insert on reasoning_promotion_proposal
        when not exists (
            select 1
            from workspace_run r
            join reasoning_node n on n.node_id = new.outcome_node_id
            join reasoning_state s on s.node_id = n.node_id
            where r.run_id = new.run_id
              and n.run_id = r.run_id
              and n.kind = 'outcome'
              and n.ns = r.ns and n.scope = r.scope
              and new.ns = r.ns and new.scope = r.scope
              and s.seq = (
                  select max(latest.seq) from reasoning_state latest
                  where latest.node_id = n.node_id
              )
              and s.status = 'accepted'
        ) begin
            select raise(abort,
                'promotion proposal requires a same-scope accepted outcome');
        end;
        create trigger if not exists reasoning_promotion_review_reversal_guard
        before insert on reasoning_promotion_review
        when exists (
            select 1 from reasoning_promotion_reversal reversal
            where reversal.proposal_id = new.proposal_id
        ) begin
            select raise(abort, 'reversed promotion proposals cannot be reviewed');
        end;
        """
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


def _json_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    loaded = json.loads(value)
    if not isinstance(loaded, list):
        return ()
    return tuple(str(item) for item in loaded if isinstance(item, str) and item)


def _bounded_ids(values: Iterable[str], field: str) -> tuple[str, ...]:
    items = list(islice(iter(values), 257))
    if len(items) > 256:
        raise ValueError(f"{field} supports at most 256 references")
    resolved: list[str] = []
    for value in items:
        if not isinstance(value, str):
            raise TypeError(f"{field} values must be strings")
        item = value.strip()
        if item and item not in resolved:
            resolved.append(item)
    return tuple(resolved)


def _assertion_object(value: object) -> str:
    def validate(item: object, depth: int = 0) -> None:
        if depth > 4:
            raise ValueError("assertion object nesting exceeds 4 levels")
        if item is None or isinstance(item, (str, bool, int)):
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError("assertion object numbers must be finite")
            return
        if isinstance(item, (list, tuple)):
            if len(item) > 64:
                raise ValueError("assertion object lists support at most 64 values")
            for child in item:
                validate(child, depth + 1)
            return
        raise TypeError(
            "assertion object must be a JSON scalar or bounded list; "
            "free-form mappings are not accepted"
        )

    validate(value)
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode("utf-8")) > 4096:
        raise ValueError("assertion object exceeds 4096 UTF-8 bytes")
    return encoded


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _latest_outcome_status(
    connection: sqlite3.Connection, outcome_node_id: str
) -> str | None:
    row = connection.execute(
        "select status from reasoning_state where node_id = ? "
        "order by seq desc limit 1",
        (outcome_node_id,),
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


def _record_fingerprint(
    connection: sqlite3.Connection, record_id: str, ns: str, scope: str
) -> str:
    row = connection.execute(
        "select ns, scope, payload_json from ir_records where id = ?", (record_id,)
    ).fetchone()
    if row is None:
        raise KeyError(f"promotion evidence record not found: {record_id}")
    if row["ns"] != ns or row["scope"] != scope:
        raise ValueError(
            f"promotion evidence crosses namespace or scope: {record_id}"
        )
    return _sha256(str(row["payload_json"]))


def _proposal_material(row: sqlite3.Row) -> dict[str, object]:
    return {
        "run_id": str(row["run_id"]),
        "outcome_node_id": str(row["outcome_node_id"]),
        "ns": str(row["ns"]),
        "scope": str(row["scope"]),
        "assertion": {
            "id": str(row["assertion_record_id"]),
            "kind": str(row["assertion_kind"]),
            "subject": str(row["assertion_subject"]),
            "predicate": str(row["assertion_predicate"]),
            "object": json.loads(row["assertion_object_json"]),
            "status": str(row["assertion_status"]),
            "confidence": float(row["assertion_confidence"]),
            "t0": row["assertion_t0"],
            "t1": row["assertion_t1"],
        },
        "verification_ids": list(_json_ids(row["verification_ids_json"])),
        "knowledge_refs": list(_json_ids(row["knowledge_refs_json"])),
        "evidence_fingerprints": json.loads(row["evidence_fingerprints_json"]),
    }


def _material_sha256(material: dict[str, object]) -> str:
    return _sha256(
        json.dumps(
            material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    )


def _provenance_status(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    allow_persisted_assertion: bool = False,
) -> tuple[bool, str]:
    if _latest_outcome_status(connection, str(row["outcome_node_id"])) != "accepted":
        return False, "source outcome is no longer accepted"

    association_ids = tuple(
        str(item["verification_id"])
        for item in connection.execute(
            "select verification_id from reasoning_outcome_verification "
            "where outcome_node_id = ? order by seq",
            (row["outcome_node_id"],),
        ).fetchall()
    )
    stored_ids = _json_ids(row["verification_ids_json"])
    if not stored_ids or association_ids != stored_ids:
        return False, "outcome verification bindings changed"
    for verification_id in stored_ids:
        if (
            _current_verification(
                connection, verification_id, str(row["run_id"])
            )
            is None
        ):
            return False, "verification provenance is stale or non-current"

    for node_id in _json_ids(row["knowledge_refs_json"]):
        current = connection.execute(
            "select ns, scope, status from knowledge_nodes where id = ?",
            (node_id,),
        ).fetchone()
        if (
            current is None
            or current["ns"] != row["ns"]
            or current["scope"] != row["scope"]
            or str(current["status"]) in _INACTIVE_KNOWLEDGE_STATUSES
        ):
            return False, f"knowledge provenance is stale for {node_id}"

    fingerprints = json.loads(row["evidence_fingerprints_json"])
    if not isinstance(fingerprints, dict) or not fingerprints:
        return False, "exact MIRL evidence provenance is missing"
    for record_id, expected in sorted(fingerprints.items()):
        current = connection.execute(
            "select ns, scope, payload_json from ir_records where id = ?",
            (record_id,),
        ).fetchone()
        if (
            current is None
            or current["ns"] != row["ns"]
            or current["scope"] != row["scope"]
            or _sha256(str(current["payload_json"])) != expected
        ):
            return False, f"evidence drift detected for {record_id}"

    if not allow_persisted_assertion and (
        connection.execute(
            "select 1 from ir_records where id = ?", (row["assertion_record_id"],)
        ).fetchone()
        is not None
    ):
        return False, "proposed MIRL assertion id already exists"
    if _material_sha256(_proposal_material(row)) != row["proposal_sha256"]:
        return False, "proposal binding fingerprint mismatch"
    return True, "current verified provenance"


def _persisted_assertion_fingerprint(
    connection: sqlite3.Connection, row: sqlite3.Row
) -> str:
    """Verify Store persisted exactly the reviewed assertion and hash it."""

    record = connection.execute(
        "select * from ir_records where id = ?", (row["assertion_record_id"],)
    ).fetchone()
    if record is None:
        raise ValueError("approved MIRL assertion has not been persisted")
    expected = _approved_assertion(connection, row)
    if (
        record["kind"] != expected["kind"]
        or record["ns"] != expected["ns"]
        or record["scope"] != expected["scope"]
        or record["status"] != expected["status"]
        or not math.isclose(
            float(record["conf"]),
            float(expected["conf"]),
            rel_tol=0,
            abs_tol=1e-9,
        )
        or record["t0"] != expected["t0"]
        or record["t1"] != expected["t1"]
    ):
        raise ValueError("persisted MIRL assertion does not match approved fields")
    payload = json.loads(str(record["payload_json"]))
    if not isinstance(payload, dict):
        raise ValueError("persisted MIRL assertion payload is malformed")
    for field in ("ver", "prov", "evidence", "ext", "attrs"):
        if payload.get(field) != expected[field]:
            raise ValueError(
                f"persisted MIRL assertion does not match approved {field}"
            )
    return _sha256(str(record["payload_json"]))


def _approved_assertion(
    connection: sqlite3.Connection, row: sqlite3.Row
) -> dict[str, object]:
    fingerprint_ids = sorted(json.loads(row["evidence_fingerprints_json"]))
    evidence_ids: list[str] = []
    for record_id in fingerprint_ids:
        record = connection.execute(
            "select kind from ir_records where id = ?", (record_id,)
        ).fetchone()
        if record is not None and str(record["kind"]) in {"RAW", "SPAN"}:
            evidence_ids.append(record_id)
    return {
        "id": str(row["assertion_record_id"]),
        "kind": "CLM",
        "ns": str(row["ns"]),
        "scope": str(row["scope"]),
        "ver": SCHEMA_VERSION,
        "conf": float(row["assertion_confidence"]),
        "status": str(row["assertion_status"]),
        "t0": row["assertion_t0"],
        "t1": row["assertion_t1"],
        "prov": [],
        "evidence": evidence_ids,
        "ext": {
            "reasoning_promotion_proposal_id": str(row["proposal_id"]),
            "reasoning_promotion_sha256": str(row["proposal_sha256"]),
            "reasoning_outcome_node_id": str(row["outcome_node_id"]),
            "reasoning_knowledge_refs": list(
                _json_ids(row["knowledge_refs_json"])
            ),
        },
        "attrs": {
            "subject": str(row["assertion_subject"]),
            "predicate": str(row["assertion_predicate"]),
            "object": json.loads(row["assertion_object_json"]),
        },
    }


def propose_reasoning_promotion(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    outcome_node_id: str,
    assertion_record_id: str,
    assertion_subject: str,
    assertion_predicate: str,
    assertion_object: object,
    assertion_status: str = "inferred",
    assertion_confidence: float = 1.0,
    assertion_t0: str | None = None,
    assertion_t1: str | None = None,
    proposed_by: str,
    proposal_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, object]:
    """Propose one new CLM assertion from a verified accepted outcome."""

    if not connection.in_transaction:
        connection.execute("begin immediate")
    outcome = connection.execute(
        "select * from reasoning_node "
        "where node_id = ? and run_id = ? and kind = 'outcome'",
        (outcome_node_id, run_id),
    ).fetchone()
    if outcome is None:
        raise KeyError(f"verified reasoning outcome not found: {outcome_node_id}")
    if _latest_outcome_status(connection, outcome_node_id) != "accepted":
        raise ValueError("promotion proposals require an accepted outcome")

    verification_ids = tuple(
        str(row["verification_id"])
        for row in connection.execute(
            "select verification_id from reasoning_outcome_verification "
            "where outcome_node_id = ? order by seq",
            (outcome_node_id,),
        ).fetchall()
    )
    if not verification_ids:
        raise ValueError("promotion proposals require a verified accepted outcome")
    verification_rows: list[sqlite3.Row] = []
    for verification_id in verification_ids:
        current = _current_verification(connection, verification_id, run_id)
        if current is None:
            raise ValueError(
                "promotion proposals require current passed verifications"
            )
        verification_rows.append(current)

    knowledge_refs = set(_json_ids(outcome["knowledge_refs_json"]))
    evidence_ids = set(_json_ids(outcome["evidence_record_ids_json"]))
    for verification in verification_rows:
        knowledge_refs.update(_json_ids(verification["knowledge_refs_json"]))
        evidence_ids.update(_json_ids(verification["evidence_record_ids_json"]))
    for node_id in sorted(knowledge_refs):
        node = connection.execute(
            "select ns, scope, status, source_record_id "
            "from knowledge_nodes where id = ?",
            (node_id,),
        ).fetchone()
        if node is None:
            raise KeyError(f"promotion knowledge node not found: {node_id}")
        if node["ns"] != outcome["ns"] or node["scope"] != outcome["scope"]:
            raise ValueError(
                f"promotion knowledge crosses namespace or scope: {node_id}"
            )
        if str(node["status"]) in _INACTIVE_KNOWLEDGE_STATUSES:
            raise ValueError(f"promotion knowledge is not current: {node_id}")
        if node["source_record_id"]:
            evidence_ids.add(str(node["source_record_id"]))
    if not evidence_ids:
        raise ValueError("promotion proposals require exact MIRL evidence")

    resolved_record_id = _required_text(
        assertion_record_id, "assertion_record_id", limit=256
    )
    if (
        connection.execute(
            "select 1 from ir_records where id = ?", (resolved_record_id,)
        ).fetchone()
        is not None
    ):
        raise ValueError("proposed MIRL assertion id already exists")
    resolved_subject = _required_text(
        assertion_subject, "assertion_subject", limit=512
    )
    resolved_predicate = _required_text(
        assertion_predicate, "assertion_predicate", limit=128
    )
    object_json = _assertion_object(assertion_object)
    resolved_status = str(assertion_status).strip().lower()
    if resolved_status not in PROMOTABLE_ASSERTION_STATUSES:
        raise ValueError(f"unsupported assertion status: {assertion_status}")
    if (
        isinstance(assertion_confidence, bool)
        or not isinstance(assertion_confidence, (int, float))
        or not math.isfinite(float(assertion_confidence))
        or not 0 <= float(assertion_confidence) <= 1
    ):
        raise ValueError("assertion_confidence must be finite and between 0 and 1")
    resolved_by = _required_text(proposed_by, "proposed_by", limit=256)
    fingerprints = {
        record_id: _record_fingerprint(
            connection, record_id, str(outcome["ns"]), str(outcome["scope"])
        )
        for record_id in sorted(evidence_ids)
    }
    resolved_id = proposal_id or f"rprom:{uuid4().hex}"
    resolved_created_at = created_at or utc_now()
    values = {
        "run_id": run_id,
        "outcome_node_id": outcome_node_id,
        "ns": str(outcome["ns"]),
        "scope": str(outcome["scope"]),
        "assertion": {
            "id": resolved_record_id,
            "kind": "CLM",
            "subject": resolved_subject,
            "predicate": resolved_predicate,
            "object": json.loads(object_json),
            "status": resolved_status,
            "confidence": float(assertion_confidence),
            "t0": assertion_t0,
            "t1": assertion_t1,
        },
        "verification_ids": list(verification_ids),
        "knowledge_refs": sorted(knowledge_refs),
        "evidence_fingerprints": fingerprints,
    }
    connection.execute(
        """
        insert into reasoning_promotion_proposal
            (proposal_id, run_id, outcome_node_id, ns, scope,
             assertion_record_id, assertion_kind, assertion_subject,
             assertion_predicate, assertion_object_json, assertion_status,
             assertion_confidence, assertion_t0, assertion_t1,
             verification_ids_json, knowledge_refs_json,
             evidence_fingerprints_json, proposal_sha256, proposed_by,
             created_at, schema_version)
        values (?, ?, ?, ?, ?, ?, 'CLM', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            resolved_id,
            run_id,
            outcome_node_id,
            outcome["ns"],
            outcome["scope"],
            resolved_record_id,
            resolved_subject,
            resolved_predicate,
            object_json,
            resolved_status,
            float(assertion_confidence),
            assertion_t0,
            assertion_t1,
            json.dumps(verification_ids, separators=(",", ":")),
            json.dumps(sorted(knowledge_refs), separators=(",", ":")),
            json.dumps(fingerprints, sort_keys=True, separators=(",", ":")),
            _material_sha256(values),
            resolved_by,
            resolved_created_at,
            REASONING_PROMOTION_SCHEMA_VERSION,
        ),
    )
    return get_reasoning_promotion(connection, resolved_id)


def reasoning_promotion_eligibility(
    connection: sqlite3.Connection, proposal_id: str
) -> dict[str, object]:
    """Recheck review state and every bound provenance item."""

    row = connection.execute(
        "select * from reasoning_promotion_proposal where proposal_id = ?",
        (proposal_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"reasoning promotion proposal not found: {proposal_id}")
    reversal = connection.execute(
        "select * from reasoning_promotion_reversal where proposal_id = ?",
        (proposal_id,),
    ).fetchone()
    if reversal is not None:
        return {
            "proposal_id": proposal_id,
            "eligible": False,
            "reason": "promotion approval was reversed",
            "approved_assertion": None,
        }
    application = connection.execute(
        "select * from reasoning_promotion_application where proposal_id = ?",
        (proposal_id,),
    ).fetchone()
    if application is not None:
        return {
            "proposal_id": proposal_id,
            "eligible": False,
            "reason": "promotion proposal was already applied",
            "approved_assertion": None,
        }
    review = connection.execute(
        "select * from reasoning_promotion_review where proposal_id = ? "
        "order by seq desc limit 1",
        (proposal_id,),
    ).fetchone()
    if review is None:
        return {
            "proposal_id": proposal_id,
            "eligible": False,
            "reason": "promotion proposal has not been reviewed",
            "approved_assertion": None,
        }
    if review["decision"] != "approved":
        return {
            "proposal_id": proposal_id,
            "eligible": False,
            "reason": "latest promotion review is not approved",
            "approved_assertion": None,
        }
    current, reason = _provenance_status(connection, row)
    return {
        "proposal_id": proposal_id,
        "eligible": current,
        "reason": reason,
        "approved_assertion": (
            _approved_assertion(connection, row) if current else None
        ),
    }


def review_reasoning_promotion(
    connection: sqlite3.Connection,
    *,
    proposal_id: str,
    review_kind: str,
    decision: str,
    reviewer_id: str,
    rationale: str,
    review_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, object]:
    """Append a separate human or policy review."""

    if not connection.in_transaction:
        connection.execute("begin immediate")
    row = connection.execute(
        "select * from reasoning_promotion_proposal where proposal_id = ?",
        (proposal_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"reasoning promotion proposal not found: {proposal_id}")
    if (
        connection.execute(
            "select 1 from reasoning_promotion_reversal where proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        is not None
    ):
        raise ValueError("reversed promotion proposals cannot be reviewed")
    resolved_kind = str(review_kind).strip().lower()
    if resolved_kind not in PROMOTION_REVIEW_KINDS:
        raise ValueError(f"unsupported promotion review kind: {review_kind}")
    resolved_decision = str(decision).strip().lower()
    if resolved_decision not in PROMOTION_REVIEW_DECISIONS:
        raise ValueError(f"unsupported promotion review decision: {decision}")
    if resolved_decision == "approved":
        current, reason = _provenance_status(connection, row)
        if not current:
            raise ValueError(
                f"promotion approval requires current provenance: {reason}"
            )
    resolved_reviewer = _required_text(reviewer_id, "reviewer_id", limit=256)
    resolved_rationale = _required_text(rationale, "review rationale", limit=2048)
    next_seq = int(
        connection.execute(
            "select coalesce(max(seq), 0) + 1 "
            "from reasoning_promotion_review where proposal_id = ?",
            (proposal_id,),
        ).fetchone()[0]
    )
    resolved_id = review_id or f"rprom-review:{uuid4().hex}"
    resolved_created_at = created_at or utc_now()
    connection.execute(
        """
        insert into reasoning_promotion_review
            (review_id, proposal_id, seq, review_kind, decision, reviewer_id,
             rationale, created_at, schema_version)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            resolved_id,
            proposal_id,
            next_seq,
            resolved_kind,
            resolved_decision,
            resolved_reviewer,
            resolved_rationale,
            resolved_created_at,
            REASONING_PROMOTION_SCHEMA_VERSION,
        ),
    )
    return {
        "review_id": resolved_id,
        "proposal_id": proposal_id,
        "seq": next_seq,
        "review_kind": resolved_kind,
        "decision": resolved_decision,
        "reviewer_id": resolved_reviewer,
        "rationale": resolved_rationale,
        "created_at": resolved_created_at,
        "schema_version": REASONING_PROMOTION_SCHEMA_VERSION,
    }


def record_reasoning_promotion_application(
    connection: sqlite3.Connection,
    *,
    proposal_id: str,
    assertion_record_id: str,
    applied_by: str,
    application_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, object]:
    """Bind an exact Store-persisted MIRL assertion to its approved proposal.

    Store must insert the returned approved assertion through its normal MIRL
    path first, then call this function on the same connection and transaction.
    """

    if not connection.in_transaction:
        connection.execute("begin immediate")
    row = connection.execute(
        "select * from reasoning_promotion_proposal where proposal_id = ?",
        (proposal_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"reasoning promotion proposal not found: {proposal_id}")
    resolved_record_id = _required_text(
        assertion_record_id, "assertion_record_id", limit=256
    )
    if resolved_record_id != row["assertion_record_id"]:
        raise ValueError("application assertion id does not match proposal")
    if (
        connection.execute(
            "select 1 from reasoning_promotion_application where proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        is not None
    ):
        raise ValueError("promotion proposal was already applied")
    if (
        connection.execute(
            "select 1 from reasoning_promotion_reversal where proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        is not None
    ):
        raise ValueError("reversed promotion proposals cannot be applied")
    review = connection.execute(
        "select decision from reasoning_promotion_review where proposal_id = ? "
        "order by seq desc limit 1",
        (proposal_id,),
    ).fetchone()
    if review is None or review["decision"] != "approved":
        raise ValueError("promotion application requires latest approved review")
    current, reason = _provenance_status(
        connection, row, allow_persisted_assertion=True
    )
    if not current:
        raise ValueError(
            f"promotion application requires current provenance: {reason}"
        )
    assertion_sha256 = _persisted_assertion_fingerprint(connection, row)
    resolved_by = _required_text(applied_by, "applied_by", limit=256)
    resolved_id = application_id or f"rprom-application:{uuid4().hex}"
    resolved_created_at = created_at or utc_now()
    connection.execute(
        """
        insert into reasoning_promotion_application
            (application_id, proposal_id, assertion_record_id, assertion_sha256,
             applied_by, created_at, schema_version)
        values (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            resolved_id,
            proposal_id,
            resolved_record_id,
            assertion_sha256,
            resolved_by,
            resolved_created_at,
            REASONING_PROMOTION_SCHEMA_VERSION,
        ),
    )
    return {
        "application_id": resolved_id,
        "proposal_id": proposal_id,
        "assertion_record_id": resolved_record_id,
        "assertion_sha256": assertion_sha256,
        "applied_by": resolved_by,
        "created_at": resolved_created_at,
        "schema_version": REASONING_PROMOTION_SCHEMA_VERSION,
    }


def reverse_reasoning_promotion(
    connection: sqlite3.Connection,
    *,
    proposal_id: str,
    reversed_by: str,
    reason: str,
    reversal_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, object]:
    """Append an audit reversal without rewriting reasoning or MIRL records."""

    if not connection.in_transaction:
        connection.execute("begin immediate")
    proposal = connection.execute(
        "select * from reasoning_promotion_proposal where proposal_id = ?",
        (proposal_id,),
    ).fetchone()
    if proposal is None:
        raise KeyError(f"reasoning promotion proposal not found: {proposal_id}")
    application = connection.execute(
        "select * from reasoning_promotion_application where proposal_id = ?",
        (proposal_id,),
    ).fetchone()
    if application is None:
        raise ValueError("only an applied promotion can be reversed")
    if (
        connection.execute(
            "select 1 from reasoning_promotion_reversal where proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        is not None
    ):
        raise ValueError("promotion application was already reversed")
    current_record = connection.execute(
        "select payload_json from ir_records where id = ?",
        (application["assertion_record_id"],),
    ).fetchone()
    if (
        current_record is None
        or _sha256(str(current_record["payload_json"]))
        != application["assertion_sha256"]
    ):
        raise ValueError("applied MIRL assertion is missing or changed")
    resolved_by = _required_text(reversed_by, "reversed_by", limit=256)
    resolved_reason = _required_text(reason, "reversal reason", limit=2048)
    resolved_id = reversal_id or f"rprom-reversal:{uuid4().hex}"
    resolved_created_at = created_at or utc_now()
    connection.execute(
        """
        insert into reasoning_promotion_reversal
            (reversal_id, proposal_id, application_id, assertion_record_id,
             assertion_sha256, reversed_by, reason, created_at, schema_version)
        values (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            resolved_id,
            proposal_id,
            application["application_id"],
            application["assertion_record_id"],
            application["assertion_sha256"],
            resolved_by,
            resolved_reason,
            resolved_created_at,
            REASONING_PROMOTION_SCHEMA_VERSION,
        ),
    )
    return {
        "reversal_id": resolved_id,
        "proposal_id": proposal_id,
        "application_id": str(application["application_id"]),
        "assertion_record_id": str(application["assertion_record_id"]),
        "assertion_sha256": str(application["assertion_sha256"]),
        "reversed_by": resolved_by,
        "reason": resolved_reason,
        "created_at": resolved_created_at,
        "schema_version": REASONING_PROMOTION_SCHEMA_VERSION,
    }


def get_reasoning_promotion(
    connection: sqlite3.Connection, proposal_id: str
) -> dict[str, object]:
    row = connection.execute(
        "select * from reasoning_promotion_proposal where proposal_id = ?",
        (proposal_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"reasoning promotion proposal not found: {proposal_id}")
    reviews = [
        {
            "review_id": str(item["review_id"]),
            "seq": int(item["seq"]),
            "review_kind": str(item["review_kind"]),
            "decision": str(item["decision"]),
            "reviewer_id": str(item["reviewer_id"]),
            "rationale": str(item["rationale"]),
            "created_at": str(item["created_at"]),
            "schema_version": int(item["schema_version"]),
        }
        for item in connection.execute(
            "select * from reasoning_promotion_review where proposal_id = ? "
            "order by seq",
            (proposal_id,),
        ).fetchall()
    ]
    reversal_row = connection.execute(
        "select * from reasoning_promotion_reversal where proposal_id = ?",
        (proposal_id,),
    ).fetchone()
    application_row = connection.execute(
        "select * from reasoning_promotion_application where proposal_id = ?",
        (proposal_id,),
    ).fetchone()
    current, current_reason = _provenance_status(
        connection,
        row,
        allow_persisted_assertion=application_row is not None,
    )
    eligibility = reasoning_promotion_eligibility(connection, proposal_id)
    return {
        "proposal_id": str(row["proposal_id"]),
        **_proposal_material(row),
        "proposal_sha256": str(row["proposal_sha256"]),
        "proposed_by": str(row["proposed_by"]),
        "created_at": str(row["created_at"]),
        "schema_version": int(row["schema_version"]),
        "provenance_current": current,
        "provenance_status": current_reason,
        "reviews": reviews,
        "application": (
            {
                "application_id": str(application_row["application_id"]),
                "assertion_record_id": str(application_row["assertion_record_id"]),
                "assertion_sha256": str(application_row["assertion_sha256"]),
                "applied_by": str(application_row["applied_by"]),
                "created_at": str(application_row["created_at"]),
                "schema_version": int(application_row["schema_version"]),
            }
            if application_row is not None
            else None
        ),
        "reversal": (
            {
                "reversal_id": str(reversal_row["reversal_id"]),
                "application_id": str(reversal_row["application_id"]),
                "assertion_record_id": str(reversal_row["assertion_record_id"]),
                "assertion_sha256": str(reversal_row["assertion_sha256"]),
                "reversed_by": str(reversal_row["reversed_by"]),
                "reason": str(reversal_row["reason"]),
                "created_at": str(reversal_row["created_at"]),
                "schema_version": int(reversal_row["schema_version"]),
            }
            if reversal_row is not None
            else None
        ),
        "eligible": eligibility["eligible"],
        "eligibility_reason": eligibility["reason"],
        "approved_assertion": eligibility["approved_assertion"],
    }


def list_reasoning_promotions(
    connection: sqlite3.Connection,
    *,
    ns: str,
    scope: str,
    limit: int = 50,
) -> list[dict[str, object]]:
    """List a bounded tenant-scoped proposal slice, newest first."""

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("promotion list limit must be between 1 and 100")
    resolved_ns = _required_text(ns, "ns", limit=256)
    resolved_scope = _required_text(scope, "scope", limit=128)
    rows = connection.execute(
        "select proposal_id from reasoning_promotion_proposal "
        "where ns = ? and scope = ? order by created_at desc, proposal_id limit ?",
        (resolved_ns, resolved_scope, limit),
    ).fetchall()
    return [
        get_reasoning_promotion(connection, str(row["proposal_id"])) for row in rows
    ]
