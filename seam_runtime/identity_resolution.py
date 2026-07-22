"""Reversible identity resolution ledger (graph maturity stage G2).

The knowledge graph is a disposable, rebuildable projection of canonical MIRL.
A *merge decision* -- "these two identity nodes are the same entity" -- is not
derivable from MIRL; it is a judgement layered on top. This module owns that
durable decision state.

Design invariants:

* Merges live in their own tables (``identity_merges`` /
  ``identity_merge_evidence``) created in ``init_knowledge_graph`` and are never
  touched by the projection drop+rebuild, so accepted decisions survive
  reprojection.
* No silent destructive merge: absorbing an identity never deletes the alias
  node or its evidence. ``split`` is a reversible status transition with a
  temporal supersession chain, not a delete.
* An identity may be absorbed by at most one canonical. Contradictions (reverse
  merge, cycle, alias already absorbed elsewhere) resolve to an auditable
  ``conflict`` status rather than corrupting the graph.
* This stage is retrieval-inert: it does not alter ``knowledge_node_terms``.
  Signal fusion into retrieval is stage G3.
"""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Iterable, Sequence

from .mirl import utc_now

STATUS_PROPOSED = "proposed"
STATUS_ACCEPTED = "accepted"
STATUS_CONFLICT = "conflict"
STATUS_SPLIT = "split"

_ACTIVE_STATUSES = (STATUS_PROPOSED, STATUS_ACCEPTED)
# Guard against a pathological alias chain / cycle in the ledger.
_MAX_RESOLVE_DEPTH = 64


class IdentityMergeError(ValueError):
    """A merge operation violated a structural invariant."""


def _merge_id(canonical_node_id: str, alias_node_id: str, ns: str, scope: str) -> str:
    key = "\x1f".join((canonical_node_id, alias_node_id, ns, scope))
    return "merge:" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def _node_exists(connection: sqlite3.Connection, node_id: str) -> bool:
    row = connection.execute(
        "select 1 from knowledge_nodes where id = ?", (node_id,)
    ).fetchone()
    return row is not None


def propose_merge(
    connection: sqlite3.Connection,
    *,
    canonical_node_id: str,
    alias_node_id: str,
    ns: str,
    scope: str,
    evidence: Iterable[tuple[str, str, str | None]] = (),
    confidence: float = 0.0,
) -> str:
    """Record a proposed merge of ``alias_node_id`` into ``canonical_node_id``.

    Returns the deterministic merge id. Proposals are non-committal; they only
    take effect on :func:`accept_merge`. A self-merge is rejected outright; a
    proposal that contradicts the current ledger is stored as ``conflict`` so
    the contradiction stays auditable instead of being silently dropped.
    """

    canonical_node_id = str(canonical_node_id).strip()
    alias_node_id = str(alias_node_id).strip()
    if not canonical_node_id or not alias_node_id:
        raise IdentityMergeError("canonical and alias node ids are required")
    if canonical_node_id == alias_node_id:
        raise IdentityMergeError("cannot merge a node with itself")

    merge_id = _merge_id(canonical_node_id, alias_node_id, ns, scope)
    now = utc_now()
    status, reason = _classify_proposal(
        connection,
        canonical_node_id=canonical_node_id,
        alias_node_id=alias_node_id,
        ns=ns,
        scope=scope,
    )
    connection.execute(
        "insert into identity_merges "
        "(id, canonical_node_id, alias_node_id, ns, scope, status, confidence, "
        "reason, created_at, updated_at, superseded_by) "
        "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, null) "
        "on conflict(id) do update set "
        "status = excluded.status, "
        "confidence = excluded.confidence, reason = excluded.reason, "
        "updated_at = excluded.updated_at "
        "where identity_merges.status not in (?, ?)",
        (
            merge_id,
            canonical_node_id,
            alias_node_id,
            ns,
            scope,
            status,
            float(confidence),
            reason,
            now,
            now,
            STATUS_ACCEPTED,
            STATUS_SPLIT,
        ),
    )
    _add_evidence(connection, merge_id, evidence, now)
    return merge_id


def _classify_proposal(
    connection: sqlite3.Connection,
    *,
    canonical_node_id: str,
    alias_node_id: str,
    ns: str,
    scope: str,
    exclude_merge_id: str | None = None,
) -> tuple[str, str | None]:
    """Return ``(status, reason)`` for a would-be active merge."""

    # Reverse direction already active -> the two disagree on which is canonical.
    reverse_id = _merge_id(alias_node_id, canonical_node_id, ns, scope)
    reverse = connection.execute(
        "select status from identity_merges where id = ?", (reverse_id,)
    ).fetchone()
    if reverse is not None and reverse[0] in _ACTIVE_STATUSES:
        return STATUS_CONFLICT, "reverse merge already recorded"

    # The alias is already absorbed by a different canonical.
    other = connection.execute(
        "select canonical_node_id from identity_merges "
        "where alias_node_id = ? and ns = ? and scope = ? and status = ? "
        "and id != ?",
        (
            alias_node_id,
            ns,
            scope,
            STATUS_ACCEPTED,
            exclude_merge_id or "",
        ),
    ).fetchone()
    if other is not None and str(other[0]) != canonical_node_id:
        return STATUS_CONFLICT, "alias already absorbed by another canonical"

    # Accepting would close a canonical-of cycle.
    if _resolves_to(
        connection,
        start=canonical_node_id,
        target=alias_node_id,
        ns=ns,
        scope=scope,
        skip_merge_id=exclude_merge_id,
    ):
        return STATUS_CONFLICT, "merge would create an identity cycle"

    return STATUS_PROPOSED, None


def _add_evidence(
    connection: sqlite3.Connection,
    merge_id: str,
    evidence: Iterable[tuple[str, str, str | None]],
    now: str,
) -> None:
    for item in evidence:
        kind, detail, source_record_id = item
        connection.execute(
            "insert or ignore into identity_merge_evidence "
            "(merge_id, evidence_kind, detail, source_record_id, created_at) "
            "values (?, ?, ?, ?, ?)",
            (merge_id, str(kind), str(detail), source_record_id, now),
        )


def generate_merge_candidates(
    connection: sqlite3.Connection,
    *,
    ns: str | None = None,
    scope: str | None = None,
    max_candidates: int = 500,
) -> dict[str, object]:
    """Auto-discover likely-same entity pairs and file them as ``proposed``.

    Graph maturity stage G2.2: the candidate generator that feeds the G2.1
    ledger. It never accepts -- acceptance stays a deliberate decision, so no
    merge is ever silent.

    Signal: two DISTINCT entity nodes sharing a full ``normalized_term`` within
    the same ns/scope, where at least one side carries that term as an
    ``alias`` (one node explicitly lists a name that is another node's name).
    Pure same-canonical-name homonyms (two entities both literally named the
    same, neither aliasing the other) are excluded as low-precision noise --
    merging every same-named entity would flood the ledger with false merges.

    Direction is deterministic: the node that owns a shared term as its
    ``canonical`` label is the canonical identity; ties (both alias-only, or
    both canonical) fall back to the lexicographically smaller node id.

    Returns a summary ``{"proposed": [...ids], "conflicts": [...ids],
    "pairs_examined": N}``. Idempotent: deterministic merge ids mean re-running
    upserts the same proposals and never changes an accepted or split decision.
    """

    if max_candidates < 1:
        raise ValueError("max_candidates must be at least 1")

    where = [
        "t1.normalized_term = t2.normalized_term",
        "t1.ns = t2.ns",
        "t1.scope = t2.scope",
        "t1.node_id < t2.node_id",
        "na.kind = 'entity'",
        "nb.kind = 'entity'",
    ]
    params: list[object] = []
    if ns is not None:
        where.append("t1.ns = ?")
        params.append(ns)
    if scope is not None:
        where.append("t1.scope = ?")
        params.append(scope)
    # Select and cap entity PAIRS in SQL before fetching their shared terms.
    # This keeps a graph-wide call from materializing an unbounded cross-join in
    # Python while retaining every shared term needed to choose direction and
    # preserve evidence for each selected pair.
    rows = connection.execute(
        "with candidate_pairs as ("
        "select t1.node_id as node_a, t2.node_id as node_b, "
        "t1.ns as pair_ns, t1.scope as pair_scope "
        "from knowledge_node_terms t1 "
        "join knowledge_node_terms t2 "
        "  on t1.normalized_term = t2.normalized_term "
        "join knowledge_nodes na on na.id = t1.node_id "
        "join knowledge_nodes nb on nb.id = t2.node_id "
        "where " + " and ".join(where) + " "
        "group by t1.node_id, t2.node_id, t1.ns, t1.scope "
        "having max(case when t1.term_kind = 'alias' or t2.term_kind = 'alias' "
        "then 1 else 0 end) = 1 "
        "order by t1.ns, t1.scope, t1.node_id, t2.node_id "
        "limit ?"
        ") "
        "select t1.node_id, t2.node_id, t1.normalized_term, t1.ns, t1.scope, "
        "t1.term_kind, t2.term_kind, t1.source_record_id, t2.source_record_id "
        "from candidate_pairs pairs "
        "join knowledge_node_terms t1 on t1.node_id = pairs.node_a "
        "  and t1.ns = pairs.pair_ns and t1.scope = pairs.pair_scope "
        "join knowledge_node_terms t2 on t2.node_id = pairs.node_b "
        "  and t2.ns = pairs.pair_ns and t2.scope = pairs.pair_scope "
        "  and t2.normalized_term = t1.normalized_term "
        "order by t1.ns, t1.scope, t1.node_id, t2.node_id, t1.normalized_term",
        [*params, int(max_candidates)],
    ).fetchall()

    # Aggregate shared terms per unordered entity pair.
    pairs: dict[tuple[str, str, str, str], dict] = {}
    for row in rows:
        node_a = str(row[0])
        node_b = str(row[1])
        key = (node_a, node_b, str(row[3]), str(row[4]))
        entry = pairs.setdefault(
            key,
            {"terms": {}, "votes": {node_a: 0, node_b: 0}, "alias_evidence": False},
        )
        term = str(row[2])
        kind_a = str(row[5])
        kind_b = str(row[6])
        # Keep the most informative source per shared term.
        entry["terms"].setdefault(term, (row[7] if row[7] is not None else row[8]))
        # A shared term where exactly one side owns it as its canonical label and
        # the other holds it as an alias points to who is canonical (the other
        # aliases into it) and is genuine alias evidence.
        if kind_a == "alias" or kind_b == "alias":
            entry["alias_evidence"] = True
        if kind_a == "canonical" and kind_b == "alias":
            entry["votes"][node_a] += 1
        elif kind_b == "canonical" and kind_a == "alias":
            entry["votes"][node_b] += 1

    proposed: list[str] = []
    conflicts: list[str] = []
    for (node_a, node_b, pair_ns, pair_scope), entry in pairs.items():
        # Require at least one alias relationship; a name both sides own only as
        # their canonical label is a homonym, not evidence of one identity.
        if not entry["alias_evidence"]:
            continue
        votes = entry["votes"]
        if votes[node_a] != votes[node_b]:
            canonical_node_id = node_a if votes[node_a] > votes[node_b] else node_b
            alias_node_id = node_b if canonical_node_id == node_a else node_a
            confidence = 0.6
        else:
            # No directional signal (shared alias only, or symmetric): pick a
            # stable direction and let the human decide the real canonical.
            canonical_node_id, alias_node_id = sorted((node_a, node_b))
            confidence = 0.4
        evidence = [
            ("shared-alias", term, source)
            for term, source in sorted(entry["terms"].items())
        ]
        merge_id = propose_merge(
            connection,
            canonical_node_id=canonical_node_id,
            alias_node_id=alias_node_id,
            ns=pair_ns,
            scope=pair_scope,
            evidence=evidence,
            confidence=confidence,
        )
        status = connection.execute(
            "select status from identity_merges where id = ?", (merge_id,)
        ).fetchone()[0]
        if status == STATUS_CONFLICT:
            conflicts.append(merge_id)
        elif status == STATUS_PROPOSED:
            proposed.append(merge_id)
        if len(proposed) >= max_candidates:
            break

    return {
        "proposed": proposed,
        "conflicts": conflicts,
        "pairs_examined": len(pairs),
    }


def accept_merge(connection: sqlite3.Connection, merge_id: str) -> str:
    """Promote a proposed merge to ``accepted``.

    Re-checks the ledger at accept time: if the proposal now contradicts an
    accepted decision (reverse merge, prior absorption, or cycle) it is marked
    ``conflict`` and NOT accepted. Returns the resulting status.
    """

    row = _load_merge(connection, merge_id)
    if row is None:
        raise IdentityMergeError(f"unknown merge {merge_id!r}")
    status = row["status"]
    if status == STATUS_ACCEPTED:
        return STATUS_ACCEPTED
    if status == STATUS_SPLIT:
        raise IdentityMergeError("cannot accept a split (undone) merge")

    resolved, reason = _classify_proposal(
        connection,
        canonical_node_id=row["canonical_node_id"],
        alias_node_id=row["alias_node_id"],
        ns=row["ns"],
        scope=row["scope"],
        exclude_merge_id=merge_id,
    )
    new_status = STATUS_ACCEPTED if resolved == STATUS_PROPOSED else STATUS_CONFLICT
    connection.execute(
        "update identity_merges set status = ?, reason = ?, updated_at = ? where id = ?",
        (new_status, reason, utc_now(), merge_id),
    )
    return new_status


def mark_conflict(
    connection: sqlite3.Connection, merge_id: str, reason: str
) -> None:
    """Flag a merge as an auditable conflict without destroying it."""

    if _load_merge(connection, merge_id) is None:
        raise IdentityMergeError(f"unknown merge {merge_id!r}")
    connection.execute(
        "update identity_merges set status = ?, reason = ?, updated_at = ? where id = ?",
        (STATUS_CONFLICT, str(reason), utc_now(), merge_id),
    )


def split_merge(
    connection: sqlite3.Connection, merge_id: str, *, reason: str | None = None
) -> None:
    """Reversibly undo a merge.

    The row is retained with ``status = 'split'`` and a supersession stamp; all
    evidence stays in place so the original decision and its justification
    remain fully auditable. Nothing is deleted.
    """

    if _load_merge(connection, merge_id) is None:
        raise IdentityMergeError(f"unknown merge {merge_id!r}")
    now = utc_now()
    connection.execute(
        "update identity_merges set status = ?, reason = ?, superseded_by = ?, "
        "updated_at = ? where id = ?",
        (STATUS_SPLIT, reason, f"split:{now}", now, merge_id),
    )


def apply_identity_merges(connection: sqlite3.Connection) -> int:
    """Re-validate accepted merges against the current node set.

    Called after reprojection and after deletions. An accepted merge whose
    canonical or alias node no longer exists is transitioned to ``conflict``
    (auditable) rather than left dangling. Retrieval-inert: no change to
    ``knowledge_node_terms``. Returns the number of merges newly flagged.

    Idempotent -- a merge already in conflict is left untouched, and a merge
    whose nodes are all present is left accepted.
    """

    rows = connection.execute(
        "select id, canonical_node_id, alias_node_id from identity_merges "
        "where status = ?",
        (STATUS_ACCEPTED,),
    ).fetchall()
    flagged = 0
    now = utc_now()
    for row in rows:
        merge_id = str(row[0])
        canonical_id = str(row[1])
        alias_id = str(row[2])
        missing = [
            node_id
            for node_id in (canonical_id, alias_id)
            if not _node_exists(connection, node_id)
        ]
        if not missing:
            continue
        connection.execute(
            "update identity_merges set status = ?, reason = ?, updated_at = ? where id = ?",
            (
                STATUS_CONFLICT,
                "referenced node(s) absent after reprojection: " + ", ".join(missing),
                now,
                merge_id,
            ),
        )
        flagged += 1
    return flagged


def resolve_canonical(
    connection: sqlite3.Connection, node_id: str, *, ns: str, scope: str
) -> str:
    """Follow accepted merges to the ultimate canonical id for ``node_id``.

    Returns ``node_id`` unchanged when it is not an absorbed alias. Cycle- and
    depth-guarded; a malformed ledger cannot spin forever.
    """

    current = str(node_id)
    seen = {current}
    for _ in range(_MAX_RESOLVE_DEPTH):
        row = connection.execute(
            "select canonical_node_id from identity_merges "
            "where alias_node_id = ? and ns = ? and scope = ? and status = ?",
            (current, ns, scope, STATUS_ACCEPTED),
        ).fetchone()
        if row is None:
            return current
        nxt = str(row[0])
        if nxt in seen:
            return current
        seen.add(nxt)
        current = nxt
    return current


def _resolves_to(
    connection: sqlite3.Connection,
    *,
    start: str,
    target: str,
    ns: str,
    scope: str,
    skip_merge_id: str | None = None,
) -> bool:
    """True if following accepted merges from ``start`` reaches ``target``."""

    current = str(start)
    seen = {current}
    for _ in range(_MAX_RESOLVE_DEPTH):
        row = connection.execute(
            "select id, canonical_node_id from identity_merges "
            "where alias_node_id = ? and ns = ? and scope = ? and status = ?",
            (current, ns, scope, STATUS_ACCEPTED),
        ).fetchone()
        if row is None:
            return False
        if skip_merge_id is not None and str(row[0]) == skip_merge_id:
            return False
        nxt = str(row[1])
        if nxt == target:
            return True
        if nxt in seen:
            return False
        seen.add(nxt)
        current = nxt
    return False


def _load_merge(connection: sqlite3.Connection, merge_id: str) -> dict | None:
    row = connection.execute(
        "select id, canonical_node_id, alias_node_id, ns, scope, status, "
        "confidence, reason, created_at, updated_at, superseded_by "
        "from identity_merges where id = ?",
        (merge_id,),
    ).fetchone()
    if row is None:
        return None
    return _merge_dict(row)


def _merge_dict(row: sqlite3.Row) -> dict:
    return {
        "id": str(row[0]),
        "canonical_node_id": str(row[1]),
        "alias_node_id": str(row[2]),
        "ns": str(row[3]),
        "scope": str(row[4]),
        "status": str(row[5]),
        "confidence": float(row[6]),
        "reason": row[7],
        "created_at": str(row[8]),
        "updated_at": str(row[9]),
        "superseded_by": row[10],
    }


def list_merges(
    connection: sqlite3.Connection,
    *,
    ns: str | None = None,
    scope: str | None = None,
    statuses: Sequence[str] | None = None,
) -> list[dict]:
    """List merges, most-recently-updated first, with optional filters."""

    where: list[str] = []
    params: list[object] = []
    if ns is not None:
        where.append("ns = ?")
        params.append(ns)
    if scope is not None:
        where.append("scope = ?")
        params.append(scope)
    if statuses:
        where.append("status in (" + ",".join("?" for _ in statuses) + ")")
        params.extend(statuses)
    clause = (" where " + " and ".join(where)) if where else ""
    rows = connection.execute(
        "select id, canonical_node_id, alias_node_id, ns, scope, status, "
        "confidence, reason, created_at, updated_at, superseded_by "
        "from identity_merges" + clause + " order by updated_at desc, id",
        params,
    ).fetchall()
    return [_merge_dict(row) for row in rows]


def merge_audit(connection: sqlite3.Connection, node_id: str) -> list[dict]:
    """Every merge (any status) touching ``node_id`` plus its evidence.

    This is the auditability contract: an absorbed identity and the reasons it
    was absorbed remain fully recoverable even after a split.
    """

    node_id = str(node_id)
    rows = connection.execute(
        "select id, canonical_node_id, alias_node_id, ns, scope, status, "
        "confidence, reason, created_at, updated_at, superseded_by "
        "from identity_merges where canonical_node_id = ? or alias_node_id = ? "
        "order by updated_at desc, id",
        (node_id, node_id),
    ).fetchall()
    result: list[dict] = []
    for row in rows:
        merge = _merge_dict(row)
        evidence_rows = connection.execute(
            "select evidence_kind, detail, source_record_id, created_at "
            "from identity_merge_evidence where merge_id = ? order by created_at, evidence_kind",
            (merge["id"],),
        ).fetchall()
        merge["evidence"] = [
            {
                "evidence_kind": str(ev[0]),
                "detail": str(ev[1]),
                "source_record_id": ev[2],
                "created_at": str(ev[3]),
            }
            for ev in evidence_rows
        ]
        result.append(merge)
    return result
