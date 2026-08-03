from __future__ import annotations

import re
from collections.abc import Mapping

from .mirl import PACK_MODES, VALID_SCOPES, IRBatch, MIRLRecord, RecordKind, Status, VerifyReport

NS_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")


def verify_ir(
    batch: IRBatch,
    *,
    known_record_kinds: Mapping[str, RecordKind] | None = None,
    known_records: Mapping[str, MIRLRecord] | None = None,
) -> VerifyReport:
    report = VerifyReport()
    records = batch.by_id()
    stored_kinds = known_record_kinds or {}
    stored_records = known_records or {}
    seen_ids: set[str] = set()
    symbol_map: dict[tuple[str, str], str] = {}

    for record in batch.records:
        valid_record_id = isinstance(record.id, str) and bool(record.id.strip())
        if not valid_record_id:
            report.add(
                "error",
                "invalid_record_id",
                "Record id must be a nonblank string",
            )
        if record.id in seen_ids:
            report.add("error", "duplicate_id", "Record id must be unique", record.id)
        seen_ids.add(record.id)

        if not NS_PATTERN.fullmatch(record.ns):
            report.add("error", "invalid_namespace", f"Invalid namespace: {record.ns}", record.id)
        if record.scope not in VALID_SCOPES:
            report.add("error", "invalid_scope", f"Invalid scope: {record.scope}", record.id)
        if not 0.0 <= record.conf <= 1.0:
            report.add("error", "invalid_confidence", "Confidence must be between 0 and 1", record.id)
        if record.kind != RecordKind.RAW and not isinstance(record.ext, dict):
            report.add("error", "invalid_extension", "ext must be a dictionary", record.id)

        _verify_kind_specific(record, report)

        for prov_id in record.prov:
            target_kind = (
                records[prov_id].kind
                if prov_id in records
                else stored_kinds.get(prov_id)
            )
            if target_kind is None:
                report.add("error", "missing_provenance", f"Missing provenance record {prov_id}", record.id)
            elif target_kind != RecordKind.PROV:
                report.add("error", "invalid_provenance", f"{prov_id} is not a PROV record", record.id)

        for evidence_id in record.evidence:
            target_kind = (
                records[evidence_id].kind
                if evidence_id in records
                else stored_kinds.get(evidence_id)
            )
            if target_kind is None:
                report.add("error", "missing_evidence", f"Missing evidence record {evidence_id}", record.id)
            elif target_kind not in {RecordKind.SPAN, RecordKind.RAW}:
                report.add("error", "invalid_evidence", f"{evidence_id} must be SPAN or RAW", record.id)

        if record.kind == RecordKind.SYM:
            symbol = str(record.attrs.get("symbol", ""))
            expansion = str(record.attrs.get("expansion", ""))
            key = (record.ns, symbol)
            existing = symbol_map.get(key)
            if existing and existing != expansion:
                report.add(
                    "error",
                    "symbol_collision",
                    f"Symbol {symbol} collides with a different expansion in namespace {record.ns}",
                    record.id,
                )
            symbol_map[key] = expansion

    for record in batch.records:
        if record.kind == RecordKind.PACK and record.attrs.get("mode") == "exact":
            _verify_exact_pack(record, records, stored_records, report)

    return report


def _verify_kind_specific(record: MIRLRecord, report: VerifyReport) -> None:
    attrs = record.attrs
    if record.kind == RecordKind.RAW:
        if _missing(attrs, "content"):
            report.add("error", "missing_content", "RAW record requires content", record.id)
        return

    if record.kind == RecordKind.SPAN:
        for key in ("raw_id", "start", "end"):
            if _missing(attrs, key):
                report.add("error", "missing_span_field", f"SPAN record requires {key}", record.id)
    elif record.kind == RecordKind.ENT:
        for key in ("entity_type", "label"):
            if _missing(attrs, key):
                report.add("error", "missing_entity_field", f"ENT record requires {key}", record.id)
    elif record.kind == RecordKind.CLM:
        for key in ("subject", "predicate", "object"):
            if _missing(attrs, key):
                report.add("error", "missing_claim_field", f"CLM record requires {key}", record.id)
    elif record.kind == RecordKind.EVT:
        for key in ("actor", "action"):
            if _missing(attrs, key):
                report.add("error", "missing_event_field", f"EVT record requires {key}", record.id)
    elif record.kind == RecordKind.REL:
        for key in ("src", "predicate", "dst"):
            if _missing(attrs, key):
                report.add("error", "missing_relation_field", f"REL record requires {key}", record.id)
    elif record.kind == RecordKind.STA:
        if _missing(attrs, "target") or _missing(attrs, "fields"):
            report.add("error", "missing_state_field", "STA record requires target and fields", record.id)
    elif record.kind == RecordKind.SYM:
        for key in ("symbol", "expansion"):
            if _missing(attrs, key):
                report.add("error", "missing_symbol_field", f"SYM record requires {key}", record.id)
    elif record.kind == RecordKind.PACK:
        mode = attrs.get("mode")
        if mode not in PACK_MODES:
            report.add("error", "invalid_pack_mode", f"Invalid PACK mode {mode}", record.id)
        if _missing(attrs, "refs") or not isinstance(attrs.get("refs"), list):
            report.add("error", "missing_pack_refs", "PACK record requires refs list", record.id)
        if _missing(attrs, "payload") or not isinstance(attrs.get("payload"), dict):
            report.add("error", "missing_pack_payload", "PACK record requires payload dict", record.id)
    elif record.kind == RecordKind.FLOW:
        if _missing(attrs, "op"):
            report.add("error", "missing_flow_op", "FLOW record requires op", record.id)
    elif record.kind == RecordKind.PROV:
        if _missing(attrs, "entity"):
            report.add(
                "error",
                "missing_prov_entity",
                "PROV record requires entity",
                record.id,
            )
    elif record.kind == RecordKind.META:
        if _missing(attrs, "schema"):
            report.add("error", "missing_meta_schema", "META record requires schema", record.id)

    if record.status.value not in {status.value for status in Status}:
        report.add("error", "invalid_status", f"Invalid status {record.status.value}", record.id)


def _verify_exact_pack(
    record: MIRLRecord,
    records: Mapping[str, MIRLRecord],
    known_records: Mapping[str, MIRLRecord],
    report: VerifyReport,
) -> None:
    refs = record.attrs.get("refs", [])
    payload_records = record.attrs.get("payload", {}).get("records", [])
    if len(refs) != len(payload_records):
        report.add("error", "exact_pack_mismatch", "Exact pack refs and payload record counts differ", record.id)
        return
    for expected_id, encoded_record in zip(refs, payload_records, strict=False):
        original = records.get(expected_id) or known_records.get(expected_id)
        if original is None:
            report.add("error", "exact_pack_missing_ref", f"Exact pack missing referenced record {expected_id}", record.id)
            continue
        if original.to_dict() != encoded_record:
            report.add(
                "error",
                "exact_pack_not_reversible",
                f"Exact pack payload for {expected_id} does not match MIRL JSON equivalence",
                record.id,
            )


def _missing(attrs: dict[str, object], key: str) -> bool:
    value = attrs.get(key)
    return value is None or value == ""
