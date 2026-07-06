from __future__ import annotations

import json
from collections import Counter
from typing import Any

CONTEXT_VIEWS = ("pack", "prompt", "evidence", "summary", "records")


def build_context_payload(payload: dict[str, Any], view: str) -> dict[str, Any]:
    enriched = dict(payload)
    enriched["view"] = view
    enriched["output"] = _build_context_output(payload, view)
    return enriched


def render_context_pretty(payload: dict[str, Any]) -> str:
    view = payload.get("view", "pack")
    output = payload.get("output")
    if view == "prompt":
        prompt = str(output or "").strip()
        return prompt or "(no prompt context)"
    if view == "evidence":
        evidence_rows = output if isinstance(output, list) else []
        lines = [
            f"Backend: {payload.get('backend')}",
            f"Query: {payload.get('query')}",
            f"Candidate ids: {', '.join(payload.get('candidate_ids', [])) or '(none)'}",
            "Evidence:",
        ]
        if not evidence_rows:
            lines.append("(none)")
        for index, row in enumerate(evidence_rows, start=1):
            lines.append(f"{index}. {row['citation']} score={row['score']:.3f} sources={_format_sources(row.get('sources', {}))}")
            lines.append(f"   {row['signal']}")
            if row.get("reasons"):
                lines.append(f"   reasons: {', '.join(row['reasons'])}")
            if row.get("prov"):
                lines.append(f"   prov: {', '.join(row['prov'])}")
            if row.get("evidence"):
                lines.append(f"   evidence: {', '.join(row['evidence'])}")
        if payload.get("trace"):
            lines.append("Trace: included")
        return "\n".join(lines)
    if view == "summary":
        summary = output if isinstance(output, dict) else {}
        lines = [
            f"Backend: {payload.get('backend')}",
            f"Query: {payload.get('query')}",
            f"Records: {summary.get('record_count', 0)}",
            f"Kinds: {_format_counter(summary.get('kind_counts', {}))}",
            "Summary:",
        ]
        highlights = summary.get("highlights", [])
        if not highlights:
            lines.append("(none)")
        for index, highlight in enumerate(highlights, start=1):
            lines.append(f"{index}. {highlight}")
        if summary.get("pack_id"):
            lines.append(f"Pack id: {summary['pack_id']}")
        if payload.get("trace"):
            lines.append("Trace: included")
        return "\n".join(lines)
    if view == "records":
        records = output if isinstance(output, list) else []
        if not records:
            return "[]"
        return "\n\n".join(json.dumps(record, indent=2, sort_keys=True) for record in records)

    pack = payload.get("pack", {})
    lines = [
        f"Backend: {payload.get('backend')}",
        f"Query: {payload.get('query')}",
        f"Candidate ids: {', '.join(payload.get('candidate_ids', [])) or '(none)'}",
        f"Pack id: {pack.get('pack_id')}",
        "Context entries:",
    ]
    pack_payload = pack.get("payload", {})
    entries = pack_payload.get("entries", [])
    refs = pack_payload.get("refs", [])
    if not entries:
        lines.append("(none)")
    for index, entry in enumerate(entries, start=1):
        # an entry's id is refs[position] (the dense pack carries it once, in refs)
        record_id = refs[index - 1] if index - 1 < len(refs) else entry.get("id", "?")
        lines.append(f"{index}. {record_id} [{entry.get('kind')}]")
    if payload.get("trace"):
        lines.append("Trace: included")
    return "\n".join(lines)


def _build_context_output(payload: dict[str, Any], view: str) -> object:
    if view == "prompt":
        return _build_prompt_text(payload)
    if view == "evidence":
        return _build_evidence_rows(payload)
    if view == "summary":
        return _build_summary(payload)
    if view == "records":
        return payload.get("records", [])
    return payload.get("pack", {})


def _build_prompt_text(payload: dict[str, Any]) -> str:
    lines = [
        "SEAM retrieved context",
        f"Query: {payload.get('query')}",
        "",
    ]
    evidence_rows = _build_evidence_rows(payload)
    if not evidence_rows:
        lines.append("No supporting records were retrieved.")
        return "\n".join(lines)
    for row in evidence_rows:
        lines.append(f"{row['citation']} {row['signal']}")
    return "\n".join(lines)


def _build_evidence_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    records = payload.get("records", [])
    candidates = payload.get("candidates", [])
    # Resolve claim subjects to entity labels so the rendered context reads
    # "Priya owns billing service", not an opaque "ent:...:hash content ...".
    ent_label = {
        record.get("id"): str(record.get("attrs", {}).get("label", ""))
        for record in records
        if record.get("kind") == "ENT" and record.get("attrs", {}).get("label")
    }
    rows: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        candidate = candidates[index - 1] if index - 1 < len(candidates) else {}
        rows.append(
            {
                "citation": f"[{index}] {record.get('id')} [{record.get('kind')}]",
                "record_id": record.get("id"),
                "kind": record.get("kind"),
                "signal": _record_signal(record, ent_label),
                "score": float(candidate.get("score", 0.0) or 0.0),
                "sources": dict(candidate.get("sources", {})),
                "reasons": list(candidate.get("reasons", [])),
                "prov": list(record.get("prov", [])),
                "evidence": list(record.get("evidence", [])),
            }
        )
    return rows


def _build_summary(payload: dict[str, Any]) -> dict[str, Any]:
    records = payload.get("records", [])
    kind_counts = Counter(record.get("kind", "UNK") for record in records)
    ent_label = {
        record.get("id"): str(record.get("attrs", {}).get("label", ""))
        for record in records
        if record.get("kind") == "ENT" and record.get("attrs", {}).get("label")
    }
    return {
        "query": payload.get("query"),
        "record_count": len(records),
        "kind_counts": dict(sorted(kind_counts.items())),
        "highlights": [_record_signal(record, ent_label) for record in records[:5]],
        "pack_id": payload.get("pack", {}).get("pack_id"),
    }


def _record_signal(record: dict[str, Any], ent_label: dict[str, str] | None = None) -> str:
    attrs = record.get("attrs", {})
    kind = record.get("kind")
    if kind == "CLM":
        subject = attrs.get("subject", "?")
        subject = (ent_label or {}).get(subject, subject)  # resolve ent-id -> label
        return f"{subject} {attrs.get('predicate', '?')} {attrs.get('object', '?')}"
    if kind == "STA":
        fields = attrs.get("fields", {})
        if isinstance(fields, dict) and fields:
            rendered = ", ".join(f"{key}={value}" for key, value in sorted(fields.items()))
            return f"{attrs.get('target', '?')} state {rendered}"
        return f"{attrs.get('target', '?')} state"
    if kind == "EVT":
        return f"{attrs.get('actor', '?')} {attrs.get('action', '?')} {attrs.get('object', '?')}"
    if kind == "REL":
        return f"{attrs.get('src', '?')} {attrs.get('predicate', '?')} {attrs.get('dst', '?')}"
    return json.dumps(attrs, sort_keys=True)


def _format_sources(sources: dict[str, Any]) -> str:
    if not sources:
        return "(none)"
    return ", ".join(f"{name}={float(score):.2f}" for name, score in sources.items())


def _format_counter(counter: dict[str, Any]) -> str:
    if not counter:
        return "(none)"
    return ", ".join(f"{key}={value}" for key, value in counter.items())
