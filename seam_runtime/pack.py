from __future__ import annotations

import hashlib
import json
from typing import Iterable

from .mirl import IRBatch, MIRLRecord, Pack, RecordKind, token_count
from .symbols import build_symbol_maps

# The meaning-bearing kinds a CONTEXT pack carries (what an LLM reasons over).
# RAW/PROV/SPAN/ENT/SYM are structural and dropped from the prompt - the verbatim
# lives in a content claim's object, entity labels are inlined into claim subjects.
_CONTEXT_CONTENT_KINDS = frozenset({RecordKind.CLM, RecordKind.STA, RecordKind.EVT, RecordKind.REL})

# Sentinel namespace for id-segment aliases (slice 3). The surviving content
# entries still carry full prov/evidence pointers (`prov:compile:<hash>`,
# `span:<hash>:n`) whose document <hash> is the token-expensive part (~7 tokens)
# and repeats across an entry's prov + evidence. A pack-level alias table maps
# each recurring long `:`-segment to a short `$N` symbol; ids are rewritten by
# segment substitution and the table is stored once in the pack, so the encoding
# is exactly reversible (real id segments never start with `$`). This is a §23.1
# alias rule applied to the structured id surface forms.
_ID_ALIAS_PREFIX = "$"
# Only segments worth a `$N` symbol (~2 tokens) get aliased - a short segment
# (`prov`, `compile`, `span`, a numeric index) costs <= the symbol, so aliasing it
# would not reduce tokens. The document hashes are the segments that clear this bar.
_MIN_ID_SEGMENT_TOKENS = 3


def pack_records(records: Iterable[MIRLRecord], lens: str = "general", budget: int = 512, mode: str = "context", profile: str = "default", namespace: str | None = None) -> Pack:
    ordered = sorted(records, key=lambda record: record.id)
    expansion_to_symbol, _ = build_symbol_maps(ordered, namespace=namespace)

    if mode == "exact":
        refs = [record.id for record in ordered]
        pack_id = _pack_id(mode, lens, budget, refs)
        payload = {"records": [record.to_dict() for record in ordered]}
        body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return Pack(pack_id=pack_id, mode=mode, lens=lens, refs=refs, payload=payload, budget=budget, reversible=True, token_cost=token_count(body), profile=profile)

    if mode == "narrative":
        refs = [record.id for record in ordered]
        pack_id = _pack_id(mode, lens, budget, refs)
        summary = _narrative_summary(ordered, lens=lens)
        return Pack(pack_id=pack_id, mode=mode, lens=lens, refs=refs, payload={"summary": summary}, budget=budget, reversible=False, token_cost=token_count(summary), profile=profile)

    # Context mode: truncate by token budget, not record count. DENSE form - the
    # hash-laden record ids dominated the packed tokens, so an entry no longer
    # repeats its own id (it is `refs[position]`), and a claim's subject resolves
    # to the entity LABEL instead of an opaque `ent:...` id. Net: far fewer tokens
    # AND a context an LLM can actually read ("Priya owns billing service").
    ent_label = {record.id: str(record.attrs.get("label", "")) for record in ordered if record.kind == RecordKind.ENT and record.attrs.get("label")}

    def _dense_signal(record: MIRLRecord) -> object:
        signal = _compact_signal(_signal_for_record(record), expansion_to_symbol)
        if record.kind == RecordKind.CLM and isinstance(signal, dict):
            label = ent_label.get(signal.get("subject"))
            if label:
                signal = {**signal, "subject": label}
        return signal

    # Content-only: a context pack is the meaning an LLM reasons over, so it carries
    # only the claim/state/event/relation records. The structural records (RAW is
    # the verbatim already carried in a content claim's object; PROV/SPAN are
    # provenance metadata; ENT labels are inlined into claim subjects above) are
    # dropped from the entries - they live in the store for traceability, not in
    # the prompt. This is the bulk of the NL->PACK density win.
    content_records = [record for record in ordered if record.kind in _CONTEXT_CONTENT_KINDS]

    # Factor the repeated long id segments (document hashes) out of the surviving
    # entries' prov/evidence pointers. Net-win gated: if the alias table does not
    # reduce total tokens, it is dropped and the entries keep full ids - so this is
    # a strict no-regression ratchet on the packed token count (spec §24 spirit:
    # denser only when it proves it stays recoverable, which the stored table does).
    id_alias, id_unalias = _mine_id_aliases(content_records)
    entries = [
        {
            "kind": record.kind.value,
            "signal": _dense_signal(record),
            "prov": [_encode_id(value, id_alias) for value in record.prov],
            "evidence": [_encode_id(value, id_alias) for value in record.evidence],
        }
        for record in content_records
    ]

    # Build payload skeleton to measure overhead tokens
    skeleton = {"lens": lens, "entries": [], "refs": [], "symbols": {symbol: expansion for expansion, symbol in expansion_to_symbol.items()}}
    overhead_tokens = token_count(json.dumps(skeleton, sort_keys=True, separators=(",", ":")))

    included_entries: list[dict[str, object]] = []
    included_ids: list[str] = []
    overflow_ids: list[str] = []
    current_tokens = overhead_tokens

    for record, entry in zip(content_records, entries):
        entry_json = json.dumps(entry, sort_keys=True, separators=(",", ":"))
        entry_tokens = token_count(entry_json)
        if current_tokens + entry_tokens <= budget:
            included_entries.append(entry)
            included_ids.append(record.id)
            current_tokens += entry_tokens
        else:
            overflow_ids.append(record.id)

    # refs[i] is the id of entries[i] - so each entry's id is carried once, in refs.
    refs = included_ids
    pack_id = _pack_id("context", lens, budget, refs)
    payload: dict[str, object] = {"lens": lens, "entries": included_entries, "refs": refs, "symbols": {symbol: expansion for expansion, symbol in expansion_to_symbol.items()}}
    if id_unalias:
        payload["idsym"] = id_unalias
    if overflow_ids:
        payload["overflow"] = {"count": len(overflow_ids), "omitted_ids": overflow_ids}
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return Pack(pack_id=pack_id, mode="context", lens=lens, refs=refs, payload=payload, budget=budget, reversible=False, token_cost=token_count(body), profile=profile)


def _pack_id(mode: str, lens: str, budget: int, refs: list[str]) -> str:
    pack_id_seed = f"{mode}|{lens}|{budget}|{','.join(refs)}".encode("utf-8")
    return f"pack:{mode}:{len(refs)}:{hashlib.sha256(pack_id_seed).hexdigest()[:12]}"


def unpack_exact_pack(pack: Pack) -> IRBatch:
    if pack.mode != "exact":
        raise ValueError("Only exact packs can be unpacked into IRBatch")
    return IRBatch.from_json(pack.payload["records"])


def pack_record(pack: Pack, ns: str = "local.default", scope: str = "project") -> MIRLRecord:
    return pack.to_record(ns=ns, scope=scope)


def score_pack(pack: Pack, records: Iterable[MIRLRecord]) -> dict[str, float | int | str]:
    ordered = sorted(records, key=lambda record: record.id)
    record_ids = {record.id for record in ordered}
    ref_coverage = len(record_ids & set(pack.refs)) / max(len(record_ids), 1)
    source_token_cost = _records_token_cost(ordered)
    budget_fit = 1.0 if pack.budget <= 0 or pack.token_cost <= pack.budget else pack.budget / max(pack.token_cost, 1)
    compression_ratio = source_token_cost / max(pack.token_cost, 1) if source_token_cost else 1.0
    compression_score = min(compression_ratio, 1.0)

    if pack.mode == "exact":
        reversibility = 1.0 if unpack_exact_pack(pack).to_json() == IRBatch(ordered).to_json() else 0.0
        provenance_retention = 1.0
        evidence_retention = 1.0
        traceability = 1.0
        overall = (0.50 * reversibility) + (0.20 * ref_coverage) + (0.15 * provenance_retention) + (0.15 * evidence_retention)
    elif pack.mode == "context":
        # CONTEXT deliberately excludes structural RAW/PROV/SPAN/ENT/SYM rows.
        # Measure coverage and traceability against the meaning-bearing record
        # set the contract actually carries; otherwise adding correct provenance
        # to a structural entity makes a faithful context pack score worse.
        context_records = [
            record for record in ordered if record.kind in _CONTEXT_CONTENT_KINDS
        ]
        context_record_ids = {record.id for record in context_records}
        ref_coverage = (
            len(context_record_ids & set(pack.refs)) / len(context_record_ids)
            if context_record_ids
            else 1.0
        )
        entries = _context_entries_by_id(pack)
        id_unalias = pack.payload.get("idsym", {})
        provenance_retention = _list_field_retention(
            context_records, entries, "prov", id_unalias
        )
        evidence_retention = _list_field_retention(
            context_records, entries, "evidence", id_unalias
        )
        reversibility = 0.0
        traceability = (ref_coverage + provenance_retention + evidence_retention) / 3
        overall = (0.40 * traceability) + (0.25 * budget_fit) + (0.20 * compression_score) + (0.15 * ref_coverage)
    else:
        provenance_retention = 0.0
        evidence_retention = 0.0
        reversibility = 0.0
        traceability = ref_coverage
        narrative_density = 1.0 if str(pack.payload.get("summary", "")).strip() else 0.0
        overall = (0.35 * ref_coverage) + (0.25 * budget_fit) + (0.20 * compression_score) + (0.20 * narrative_density)

    return {
        "mode": pack.mode,
        "record_count": len(ordered),
        "token_cost": pack.token_cost,
        "budget": pack.budget,
        "source_token_cost": source_token_cost,
        "ref_coverage": round(ref_coverage, 6),
        "provenance_retention": round(provenance_retention, 6),
        "evidence_retention": round(evidence_retention, 6),
        "traceability": round(traceability, 6),
        "reversibility": round(reversibility, 6),
        "budget_fit": round(budget_fit, 6),
        "compression_ratio": round(compression_ratio, 6),
        "overall": round(overall, 6),
    }


def _signal_for_record(record: MIRLRecord) -> dict[str, object]:
    attrs = record.attrs
    if record.kind == RecordKind.CLM:
        return {"subject": attrs.get("subject"), "predicate": attrs.get("predicate"), "object": attrs.get("object")}
    if record.kind == RecordKind.STA:
        return {"target": attrs.get("target"), "fields": attrs.get("fields")}
    if record.kind == RecordKind.EVT:
        return {"actor": attrs.get("actor"), "action": attrs.get("action"), "object": attrs.get("object")}
    if record.kind == RecordKind.REL:
        return {"src": attrs.get("src"), "predicate": attrs.get("predicate"), "dst": attrs.get("dst")}
    return attrs


def _narrative_summary(records: list[MIRLRecord], lens: str) -> str:
    claims = [record for record in records if record.kind == RecordKind.CLM]
    states = [record for record in records if record.kind == RecordKind.STA]
    if states:
        fields = states[0].attrs.get("fields", {})
        return f"[{lens}] " + "; ".join(f"{key}={value}" for key, value in fields.items())
    if claims:
        return f"[{lens}] " + "; ".join(f"{record.attrs.get('subject')} {record.attrs.get('predicate')} {record.attrs.get('object')}" for record in claims)
    return f"[{lens}] No narrative context available."


def _compact_signal(value: object, expansion_to_symbol: dict[str, str]) -> object:
    if isinstance(value, str):
        return expansion_to_symbol.get(value, value)
    if isinstance(value, list):
        return [_compact_signal(item, expansion_to_symbol) for item in value]
    if isinstance(value, dict):
        compacted: dict[str, object] = {}
        for key, item in value.items():
            compacted_key = expansion_to_symbol.get(key, key)
            compacted[compacted_key] = _compact_signal(item, expansion_to_symbol)
        return compacted
    return value


def _context_entries_by_id(pack: Pack) -> dict[str, dict[str, object]]:
    if pack.mode != "context":
        return {}
    entries = pack.payload.get("entries", [])
    refs = pack.payload.get("refs", [])
    # An entry's id is refs[position] (carried once in refs, not repeated per entry).
    return {refs[i]: entry for i, entry in enumerate(entries) if isinstance(entry, dict) and i < len(refs)}


def _list_field_retention(records: list[MIRLRecord], entries: dict[str, dict[str, object]], field: str, id_unalias: dict[str, str] | None = None) -> float:
    if not records:
        return 1.0
    scores: list[float] = []
    for record in records:
        expected = list(getattr(record, field))
        if not expected:
            scores.append(1.0)
            continue
        entry = entries.get(record.id)
        if entry is None:
            scores.append(0.0)
            continue
        # Decode the id aliases so retention is measured against the FULL ids: the
        # alias table round-trips exactly, so a faithful pack still scores 1.0.
        stored = [_decode_id(value, id_unalias) for value in entry.get(field, [])] if id_unalias else list(entry.get(field, []))
        scores.append(1.0 if stored == expected else 0.0)
    return sum(scores) / len(scores)


def _mine_id_aliases(records: list[MIRLRecord]) -> tuple[dict[str, str], dict[str, str]]:
    """Mine recurring long id `:`-segments from the records' prov/evidence.

    Returns (alias, unalias) = (segment->`$N`, `$N`->segment). Only segments that
    recur (frequency >= 2) and cost at least `_MIN_ID_SEGMENT_TOKENS` are aliased,
    and the whole table is kept only if it is a NET token win over the raw ids
    (table cost included) - otherwise empty maps are returned and ids stay full.
    Symbol assignment is deterministic within scope (sorted by -frequency then
    segment), satisfying the §13 determinism/collision/reversibility rules.
    """
    ids = [str(value) for record in records for value in (*record.prov, *record.evidence)]
    if not ids:
        return {}, {}
    segment_counts: dict[str, int] = {}
    for id_value in ids:
        for segment in id_value.split(":"):
            segment_counts[segment] = segment_counts.get(segment, 0) + 1

    alias: dict[str, str] = {}
    unalias: dict[str, str] = {}
    index = 0
    for segment, frequency in sorted(segment_counts.items(), key=lambda item: (-item[1], item[0])):
        if frequency < 2 or segment.startswith(_ID_ALIAS_PREFIX) or token_count(segment) < _MIN_ID_SEGMENT_TOKENS:
            continue
        symbol = f"{_ID_ALIAS_PREFIX}{index}"
        alias[segment] = symbol
        unalias[symbol] = segment
        index += 1

    if not alias:
        return {}, {}

    raw_cost = sum(token_count(id_value) for id_value in ids)
    encoded_cost = sum(token_count(_encode_id(id_value, alias)) for id_value in ids)
    table_cost = token_count(json.dumps(unalias, sort_keys=True, separators=(",", ":")))
    if encoded_cost + table_cost >= raw_cost:
        return {}, {}  # no net win - keep full ids (strict no-regression)
    return alias, unalias


def _encode_id(id_value: str, alias: dict[str, str]) -> str:
    if not alias:
        return id_value
    return ":".join(alias.get(segment, segment) for segment in str(id_value).split(":"))


def _decode_id(id_value: str, unalias: dict[str, str]) -> str:
    if not unalias:
        return id_value
    return ":".join(unalias.get(segment, segment) for segment in str(id_value).split(":"))


def _records_token_cost(records: list[MIRLRecord]) -> int:
    return sum(token_count(json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"))) for record in records)
