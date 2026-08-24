from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from enum import Enum

from .mirl import IRBatch, MIRLRecord, ReconcileReport, RecordKind, Status

PREDICATE_CARDINALITY_EXTENSION = "seam.predicate_cardinality"
RECONCILIATION_CONTRACT = "temporal-reconciliation/1"


class PredicateCardinality(str, Enum):
    FUNCTIONAL = "functional"
    MULTIVALUED = "multivalued"


_MULTIVALUED_PREDICATES = frozenset(
    {
        "aliases",
        "content",
        "depends_on",
        "interests",
        "likes",
        "member_of",
        "owns",
        "requires",
        "roles",
        "supports",
        "tags",
    }
)


def predicate_cardinality(record: MIRLRecord) -> PredicateCardinality:
    declared = record.ext.get(PREDICATE_CARDINALITY_EXTENSION)
    if declared is not None:
        try:
            return PredicateCardinality(str(declared).strip().lower())
        except ValueError as exc:
            raise ValueError("unknown predicate cardinality") from exc
    predicate = _normalize_predicate(record.attrs.get("predicate"))
    if predicate in _MULTIVALUED_PREDICATES:
        return PredicateCardinality.MULTIVALUED
    return PredicateCardinality.FUNCTIONAL


def reconcile_ir(batch: IRBatch) -> ReconcileReport:
    """Derive deterministic state without rewriting canonical claims.

    Groups are isolated by namespace and scope. Functional predicates select a
    current value by event time (``t0``), then confidence and record id;
    multivalued predicates retain every distinct value. Equal or missing event
    time can establish a deterministic winner but never fabricates a temporal
    ``supersedes`` relation.
    """

    claims = [record for record in batch.records if record.kind == RecordKind.CLM]
    actions: list[dict[str, object]] = []
    added_records: list[MIRLRecord] = []
    groups: dict[tuple[str, str, str, str], list[MIRLRecord]] = defaultdict(list)

    for claim in claims:
        groups[
            (
                claim.ns,
                claim.scope,
                str(claim.attrs.get("subject")),
                _normalize_predicate(claim.attrs.get("predicate")),
            )
        ].append(claim)

    for boundary_key in sorted(groups):
        ns, scope, subject, predicate = boundary_key
        group = groups[boundary_key]
        if len(group) < 2:
            continue
        cardinalities = {predicate_cardinality(claim) for claim in group}
        if len(cardinalities) != 1:
            raise ValueError("conflicting predicate cardinality declarations")
        cardinality = next(iter(cardinalities))

        objects: dict[str, list[MIRLRecord]] = defaultdict(list)
        object_values: dict[str, object] = {}
        for claim in group:
            key = _canonical_value(claim.attrs.get("object"))
            objects[key].append(claim)
            object_values.setdefault(key, claim.attrs.get("object"))

        representatives: list[MIRLRecord] = []
        for object_key in sorted(objects):
            equivalent = sorted(objects[object_key], key=_winner_key, reverse=True)
            representative = equivalent[0]
            representatives.append(representative)
            if len(equivalent) > 1:
                duplicate_ids = sorted(claim.id for claim in equivalent)
                actions.append({"type": "duplicates", "records": duplicate_ids})
                for duplicate in equivalent[1:]:
                    added_records.append(
                        _relation_record(
                            relation="duplicates",
                            winner=representative,
                            loser=duplicate,
                        )
                    )

        if cardinality is PredicateCardinality.FUNCTIONAL:
            winner = max(representatives, key=_winner_key)
            for loser in sorted(
                (claim for claim in representatives if claim.id != winner.id),
                key=lambda item: item.id,
            ):
                relation = (
                    "supersedes"
                    if _strictly_newer_event_time(winner, loser)
                    else "contradicts"
                )
                actions.append(
                    {"type": relation, "winner": winner.id, "loser": loser.id}
                )
                added_records.append(
                    _relation_record(relation=relation, winner=winner, loser=loser)
                )
            state_value: object = winner.attrs.get("object")
            state_confidence = winner.conf
            state_t0 = winner.t0
            state_t1 = winner.t1
        else:
            ordered_object_keys = sorted(object_values)
            state_value = [object_values[key] for key in ordered_object_keys]
            state_confidence = max(claim.conf for claim in representatives)
            timed = [claim for claim in representatives if _event_time(claim) is not None]
            state_t0 = min(timed, key=lambda item: _event_time(item) or datetime.max.replace(tzinfo=timezone.utc)).t0 if timed else None
            state_t1 = None

        material = "\x1f".join((RECONCILIATION_CONTRACT, ns, scope, subject, predicate))
        state_id = f"sta:reconciled:{hashlib.sha256(material.encode()).hexdigest()[:24]}"
        added_records.append(
            MIRLRecord(
                id=state_id,
                kind=RecordKind.STA,
                ns=ns,
                scope=scope,
                status=Status.INFERRED,
                conf=state_confidence,
                created_at=min(claim.created_at for claim in group),
                updated_at=max(claim.updated_at for claim in group),
                t0=state_t0,
                t1=state_t1,
                prov=sorted({prov for claim in group for prov in claim.prov}),
                evidence=sorted({ev for claim in group for ev in claim.evidence}),
                ext={
                    "reconciliation_contract": RECONCILIATION_CONTRACT,
                    PREDICATE_CARDINALITY_EXTENSION: cardinality.value,
                    "resolved_from": sorted(claim.id for claim in group),
                },
                attrs={"target": subject, "fields": {predicate: state_value}},
            )
        )

    added_records.sort(key=lambda record: record.id)
    actions.sort(key=_action_key)
    return ReconcileReport(added_records=added_records, actions=actions)


def _normalize_predicate(value: object) -> str:
    return "_".join(str(value or "").strip().casefold().split())


def _canonical_value(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _event_time(record: MIRLRecord) -> datetime | None:
    if not isinstance(record.t0, str) or not record.t0.strip():
        return None
    try:
        value = datetime.fromisoformat(record.t0.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _winner_key(record: MIRLRecord) -> tuple[int, datetime, float, str]:
    event_time = _event_time(record)
    return (
        int(event_time is not None),
        event_time or datetime.min.replace(tzinfo=timezone.utc),
        float(record.conf),
        record.id,
    )


def _strictly_newer_event_time(winner: MIRLRecord, loser: MIRLRecord) -> bool:
    winner_time = _event_time(winner)
    loser_time = _event_time(loser)
    return winner_time is not None and loser_time is not None and winner_time > loser_time


def _relation_record(
    *, relation: str, winner: MIRLRecord, loser: MIRLRecord
) -> MIRLRecord:
    material = "\x1f".join(
        (
            RECONCILIATION_CONTRACT,
            winner.ns,
            winner.scope,
            relation,
            winner.id,
            loser.id,
        )
    )
    return MIRLRecord(
        id=f"rel:reconciled:{hashlib.sha256(material.encode()).hexdigest()[:24]}",
        kind=RecordKind.REL,
        ns=winner.ns,
        scope=winner.scope,
        status=Status.INFERRED,
        conf=0.75,
        created_at=min(winner.created_at, loser.created_at),
        updated_at=max(winner.updated_at, loser.updated_at),
        t0=winner.t0,
        ext={"reconciliation_contract": RECONCILIATION_CONTRACT},
        attrs={"src": winner.id, "predicate": relation, "dst": loser.id},
    )


def _action_key(action: dict[str, object]) -> tuple[str, str, str]:
    records = action.get("records")
    return (
        str(action.get("type") or ""),
        str(action.get("winner") or (records[0] if isinstance(records, list) and records else "")),
        str(action.get("loser") or (records[-1] if isinstance(records, list) and records else "")),
    )
