"""H2 slice 5: ``improvement_review`` CLI - the operator gate for proposals.

Subcommands:

* ``propose``   - validate a proposal against the slice 4 holdout manifest
                  (when supplied) and write it to the store.
* ``list``      - show proposals newest-first; optional filters by kind,
                  status, or violation flag.
* ``show``      - show one proposal with its full decision history.
* ``approve``   - append an ``approved`` decision for one proposal.
* ``reject``    - append a ``rejected`` decision for one proposal.
* ``summary``   - counts by status and violation flag.
* ``apply``     - reconcile the persisted retrieval-flag state to the set of
                  currently approved, non-violating proposals that carry a
                  recognized ``{"flags": {...}}`` payload. This is the back half
                  of the H2 self-improvement loop: an approved proposal only
                  changes retrieval behavior once it is applied. Reversible -
                  re-running after an approval is withdrawn removes the flag.

Hard rule (matches ROADMAP H2 spec L1281-1287): this CLI never writes to
``AGENTS.md``, ``REPO_LEDGER.md``, or ``PROJECT_STATUS.md``. The only
filesystem writes are SQLite mutations through ``SQLiteStore``. Operators
land protocol or ranking-policy edits manually after this gate records
approval.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from seam_runtime.improvement import (
    VALID_KINDS,
    proposal_blocks_promotion,
    validate_proposal,
)
from seam_runtime.retrieval import coerce_flag_value, retrieval_flag_field_types
from seam_runtime.storage import SQLiteStore
from tools.h2.holdout_split import load_manifest


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _split_csv_ints(value: str | None) -> list[int]:
    if not value:
        return []
    return [int(item.strip()) for item in value.split(",") if item.strip()]


def _emit(payload: dict | list, *, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
        return
    if isinstance(payload, dict):
        for key, value in payload.items():
            print(f"  {key}: {value!r}")
    else:
        for entry in payload:
            print(entry)


def cmd_propose(args: argparse.Namespace) -> int:
    store = SQLiteStore(Path(args.db))
    evidence_case_ids = _split_csv(args.evidence_cases)
    evidence_event_ids = _split_csv_ints(args.evidence_events)
    proposed_change = json.loads(args.proposed_change_json) if args.proposed_change_json else None

    holdout_assignment = None
    if args.holdout_manifest:
        holdout_assignment = load_manifest(args.holdout_manifest)

    report = validate_proposal(
        kind=args.kind,
        summary=args.summary,
        evidence_case_ids=evidence_case_ids,
        holdout_assignment=holdout_assignment,
    )

    proposal_id = store.write_improvement_proposal(
        kind=args.kind,
        summary=args.summary,
        rationale=args.rationale,
        evidence_event_ids=evidence_event_ids or None,
        evidence_case_ids=evidence_case_ids or None,
        proposed_change=proposed_change,
        holdout_violation=report.holdout_violation,
    )
    payload = {
        "proposal_id": proposal_id,
        "holdout_violation": report.holdout_violation,
        "holdout_case_ids": report.holdout_case_ids,
        "warnings": report.warnings,
    }
    _emit(payload, json_mode=args.json)
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    store = SQLiteStore(Path(args.db))
    proposals = store.iter_improvement_proposals(
        kind=args.kind,
        status=args.status,
        holdout_violation=args.violation,
        limit=args.limit,
    )
    if args.json:
        _emit(proposals, json_mode=True)
    else:
        if not proposals:
            print("(no proposals match the filter)")
        for p in proposals:
            tag = "VIOL" if p["holdout_violation"] else "ok"
            print(
                f"#{p['proposal_id']:03d} [{p['latest_status'] or 'pending'}] "
                f"[{tag}] {p['kind']}: {p['summary']}"
            )
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    store = SQLiteStore(Path(args.db))
    proposals = store.iter_improvement_proposals()
    match = next((p for p in proposals if p["proposal_id"] == args.proposal_id), None)
    if match is None:
        print(f"proposal {args.proposal_id} not found", file=sys.stderr)
        return 1
    decisions = store.iter_proposal_decisions(args.proposal_id)
    payload = {
        "proposal": match,
        "decisions": decisions,
        "blocks_promotion": proposal_blocks_promotion(match),
    }
    _emit(payload, json_mode=True)
    return 0


def _record_decision(args: argparse.Namespace, status: str) -> int:
    store = SQLiteStore(Path(args.db))
    if status == "approved":
        proposal = next(
            (
                row
                for row in store.iter_improvement_proposals()
                if row["proposal_id"] == args.proposal_id
            ),
            None,
        )
        if proposal is None:
            print(f"proposal {args.proposal_id} not found", file=sys.stderr)
            return 1
        change = proposal.get("proposed_change")
        ratchet = change.get("ratchet") if isinstance(change, dict) else None
        # Existing/manual proposals predate the strict ratchet and retain their
        # current operator workflow. New cycle proposals carry this marker and
        # may be approved only after a complete ratchet pass.
        if isinstance(ratchet, dict) and ratchet.get("status") != "pending_approval":
            print(
                f"proposal {args.proposal_id} failed its strict ratchet and cannot be approved",
                file=sys.stderr,
            )
            return 2
    decision_id = store.record_proposal_decision(
        proposal_id=args.proposal_id,
        status=status,
        reason=args.reason,
        actor=args.actor,
    )
    _emit(
        {
            "proposal_id": args.proposal_id,
            "decision_id": decision_id,
            "status": status,
            "reason": args.reason,
            "actor": args.actor,
        },
        json_mode=args.json,
    )
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    return _record_decision(args, "approved")


def cmd_reject(args: argparse.Namespace) -> int:
    return _record_decision(args, "rejected")


def cmd_summary(args: argparse.Namespace) -> int:
    store = SQLiteStore(Path(args.db))
    proposals = store.iter_improvement_proposals()
    counts_by_status: dict[str, int] = {}
    counts_by_kind: dict[str, int] = {}
    violations = 0
    blocks = 0
    for p in proposals:
        status = p.get("latest_status") or "pending"
        counts_by_status[status] = counts_by_status.get(status, 0) + 1
        kind = p.get("kind") or "unknown"
        counts_by_kind[kind] = counts_by_kind.get(kind, 0) + 1
        if p.get("holdout_violation"):
            violations += 1
        if proposal_blocks_promotion(p):
            blocks += 1
    payload = {
        "total": len(proposals),
        "by_status": counts_by_status,
        "by_kind": counts_by_kind,
        "holdout_violations": violations,
        "blocking_promotion": blocks,
    }
    _emit(payload, json_mode=args.json)
    return 0


def compute_apply_plan(store: SQLiteStore):
    """Project the approved proposal set onto a desired retrieval-flag map.

    Returns ``(desired, applied, skipped)`` where ``desired`` maps
    ``flag_key -> (value, source_proposal_id)``. Applicability is gated on the
    ``proposed_change["flags"]`` *payload shape* (validated against
    ``RetrievalFlags``), not on ``kind`` - ``kind`` is human metadata and is
    orthogonal to the flag fields. Proposals are folded in ascending
    proposal_id order so when two approved proposals touch the same flag the
    newest (highest id) wins. Blocked proposals (pending / rejected /
    superseded / holdout violation) never contribute.
    """
    field_types = retrieval_flag_field_types()
    proposals = sorted(
        store.iter_improvement_proposals(), key=lambda p: p["proposal_id"]
    )
    desired: dict[str, tuple[object, int]] = {}
    skipped: list[dict] = []
    for p in proposals:
        pid = p["proposal_id"]
        change = p.get("proposed_change")
        flags_payload = change.get("flags") if isinstance(change, dict) else None
        ratchet = change.get("ratchet") if isinstance(change, dict) else None
        has_payload = isinstance(flags_payload, dict) and bool(flags_payload)
        if proposal_blocks_promotion(p):
            if has_payload:
                skipped.append(
                    {
                        "proposal_id": pid,
                        "reason": "blocked",
                        "status": p.get("latest_status") or "pending",
                        "holdout_violation": bool(p.get("holdout_violation")),
                    }
                )
            continue
        if isinstance(ratchet, dict) and ratchet.get("status") != "pending_approval":
            skipped.append(
                {"proposal_id": pid, "reason": "strict ratchet did not pass"}
            )
            continue
        if not has_payload:
            continue  # approved but nothing to apply (schema_change / other)
        for key, value in flags_payload.items():
            if key not in field_types:
                skipped.append(
                    {"proposal_id": pid, "reason": f"unknown flag {key!r}"}
                )
                continue
            coerced = coerce_flag_value(key, value)
            if coerced is None:
                skipped.append(
                    {"proposal_id": pid, "reason": f"flag {key!r} invalid value/type"}
                )
                continue
            desired[key] = (coerced, pid)  # ascending fold -> newest approval wins
    applied = [
        {"flag": key, "value": value, "proposal_id": pid}
        for key, (value, pid) in sorted(desired.items())
    ]
    return desired, applied, skipped


def cmd_apply(args: argparse.Namespace) -> int:
    store = SQLiteStore(Path(args.db))
    desired, applied, skipped = compute_apply_plan(store)
    if not args.dry_run:
        store.replace_retrieval_flag_state(desired)
    payload = {
        "dry_run": bool(args.dry_run),
        "applied": applied,
        "skipped": skipped,
        "effective_flags": {key: value for key, (value, _pid) in sorted(desired.items())},
    }
    _emit(payload, json_mode=args.json)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="tools.h2.improvement_review",
        description=(
            "H2 slice 5: operator gate for ranking-policy and protocol "
            "improvement proposals. Records proposals + decisions; never "
            "writes to AGENTS.md / REPO_LEDGER.md / PROJECT_STATUS.md."
        ),
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    common_db = argparse.ArgumentParser(add_help=False)
    common_db.add_argument("--db", required=True, help="SQLite path with improvement_proposal table.")
    common_db.add_argument("--json", action="store_true", help="Emit JSON to stdout.")

    prop = sub.add_parser("propose", parents=[common_db], help="Create a new proposal.")
    prop.add_argument("--kind", required=True, choices=list(VALID_KINDS))
    prop.add_argument("--summary", required=True)
    prop.add_argument("--rationale", default=None)
    prop.add_argument("--evidence-events", default=None, help="Comma-separated retrieval_event_ids.")
    prop.add_argument("--evidence-cases", default=None, help="Comma-separated case_ids cited as evidence.")
    prop.add_argument("--proposed-change-json", default=None, help="JSON blob describing the change.")
    prop.add_argument("--holdout-manifest", default=None, help="Path to a slice-4 manifest for the holdout check.")
    prop.set_defaults(func=cmd_propose)

    lst = sub.add_parser("list", parents=[common_db], help="List proposals.")
    lst.add_argument("--kind", default=None)
    lst.add_argument("--status", default=None, help="pending | approved | rejected | superseded")
    lst.add_argument("--violation", type=lambda v: v.lower() in ("true", "1", "yes"), default=None)
    lst.add_argument("--limit", type=int, default=None)
    lst.set_defaults(func=cmd_list)

    show = sub.add_parser("show", parents=[common_db], help="Show one proposal + decisions.")
    show.add_argument("proposal_id", type=int)
    show.set_defaults(func=cmd_show)

    appr = sub.add_parser("approve", parents=[common_db], help="Approve a proposal.")
    appr.add_argument("proposal_id", type=int)
    appr.add_argument("--reason", default=None)
    appr.add_argument("--actor", default=None)
    appr.set_defaults(func=cmd_approve)

    rej = sub.add_parser("reject", parents=[common_db], help="Reject a proposal.")
    rej.add_argument("proposal_id", type=int)
    rej.add_argument("--reason", default=None)
    rej.add_argument("--actor", default=None)
    rej.set_defaults(func=cmd_reject)

    summ = sub.add_parser("summary", parents=[common_db], help="Counts by status / kind / violation.")
    summ.set_defaults(func=cmd_summary)

    app = sub.add_parser(
        "apply",
        parents=[common_db],
        help="Reconcile retrieval-flag state to the approved, non-violating proposal set.",
    )
    app.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and print the plan without writing flag state.",
    )
    app.set_defaults(func=cmd_apply)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover - CLI shim
    sys.exit(main())
