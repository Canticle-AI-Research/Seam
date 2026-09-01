from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .mirl import IRBatch, MIRLRecord, RecordKind


@dataclass(frozen=True)
class IngestOutcome:
    document: dict[str, object]
    stored_ids: list[str]
    superseded_document_ids: list[str] = field(default_factory=list)
    vector_intent_record_ids: list[str] = field(default_factory=list)
    projection_pending: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "document": self.document,
            "stored_ids": list(self.stored_ids),
            "superseded_document_ids": list(self.superseded_document_ids),
            "vector_intent_record_ids": list(self.vector_intent_record_ids),
            "projection_pending": self.projection_pending,
        }


# Compatibility name retained for callers that adopted the original report.
IngestReport = IngestOutcome


def source_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stable_document_id(
    source_ref: str,
    text: str,
    *,
    ns: str | None = None,
    scope: str | None = None,
) -> str:
    boundary_ref = (
        source_ref
        if (ns, scope) in {(None, None), ("local.default", "thread")}
        else f"{ns}\n{scope}\n{source_ref}"
    )
    digest = hashlib.sha256(
        f"{boundary_ref}\n{source_hash(text)}".encode("utf-8")
    ).hexdigest()[:16]
    return f"doc:{digest}"


def namespace_ingest_batch(batch: IRBatch, document_id: str) -> IRBatch:
    suffix = document_id.split(":", 1)[1]
    id_map = {record.id: _document_record_id(record.id, suffix) for record in batch.records}
    records = []
    for record in batch.records:
        cloned = MIRLRecord.from_dict(record.to_dict())
        cloned.id = id_map[record.id]
        cloned.prov = [id_map.get(item, item) for item in cloned.prov]
        cloned.evidence = [id_map.get(item, item) for item in cloned.evidence]
        cloned.attrs = _rewrite_refs(cloned.attrs, id_map)
        records.append(cloned)
    return IRBatch(records)


def compact_memory_index(records: Iterable[MIRLRecord], query: str, scores: dict[str, float] | None = None) -> dict[str, object]:
    scores = scores or {}
    items = []
    for record in records:
        items.append(
            {
                "id": record.id,
                "kind": record.kind.value,
                "score": round(float(scores.get(record.id, 0.0)), 6),
                "summary": _record_summary(record),
                "refs": sorted(set(record.prov + record.evidence)),
            }
        )
    return {"query": query, "results": items, "next": "Use `seam memory get <ids>` for full records."}


def full_memory_records(records: Iterable[MIRLRecord]) -> dict[str, object]:
    return {"records": [record.to_dict() for record in records]}


def neighbor_timeline(batch: IRBatch, record_ids: list[str]) -> dict[str, object]:
    by_id = batch.by_id()
    selected = [by_id[record_id] for record_id in record_ids if record_id in by_id]
    neighbors: dict[str, list[str]] = {}
    for record in selected:
        refs = set(record.prov + record.evidence)
        for key in ("src", "dst", "target", "raw_id", "subject"):
            value = record.attrs.get(key)
            if isinstance(value, str):
                refs.add(value)
        obj = record.attrs.get("object")
        if isinstance(obj, str):
            refs.add(obj)
        neighbors[record.id] = sorted(ref for ref in refs if ref in by_id)
    ordered = sorted(selected, key=lambda item: (item.t0 or item.created_at, item.id))
    return {
        "ids": list(record_ids),
        "timeline": [{"id": record.id, "kind": record.kind.value, "updated_at": record.updated_at} for record in ordered],
        "neighbors": neighbors,
    }


def render_memory_index(payload: dict[str, object]) -> str:
    lines = [f"Memory search: {payload.get('query')}"]
    results = payload.get("results", [])
    if not results:
        lines.append("(none)")
    for index, item in enumerate(results, start=1):
        lines.append(f"{index}. {item['id']} [{item['kind']}] score={item['score']:.3f}")
        if item.get("summary"):
            lines.append(f"   {item['summary']}")
        refs = item.get("refs") or []
        if refs:
            lines.append(f"   refs={', '.join(refs)}")
    lines.append(str(payload.get("next", "")))
    return "\n".join(line for line in lines if line)


def render_memory_records(payload: dict[str, object]) -> str:
    records = payload.get("records", [])
    if not records:
        return "No records found."
    return "\n".join(json.dumps(record, sort_keys=True) for record in records)


def read_path_text(path: str) -> tuple[str, str]:
    if path == "-":
        import sys

        return sys.stdin.read(), "stdin://seam"
    source = Path(path)
    return source.read_bytes().decode("utf-8"), str(source)


def _record_summary(record: MIRLRecord) -> str:
    attrs = record.attrs
    if record.kind == RecordKind.CLM:
        return f"{attrs.get('subject')} {attrs.get('predicate')} {attrs.get('object')}"
    if record.kind == RecordKind.REL:
        return f"{attrs.get('src')} {attrs.get('predicate')} {attrs.get('dst')}"
    if record.kind == RecordKind.STA:
        return f"{attrs.get('target')} {attrs.get('fields')}"
    if record.kind == RecordKind.EVT:
        return f"{attrs.get('actor')} {attrs.get('action')} {attrs.get('object')}"
    return str(attrs)[:180]


def _document_record_id(record_id: str, suffix: str) -> str:
    head, sep, tail = record_id.partition(":")
    if not sep:
        return f"{record_id}:{suffix}"
    return f"{head}:{suffix}:{tail}"


def _rewrite_refs(value, id_map: dict[str, str]):
    if isinstance(value, str):
        return id_map.get(value, value)
    if isinstance(value, list):
        return [_rewrite_refs(item, id_map) for item in value]
    if isinstance(value, dict):
        return {key: _rewrite_refs(item, id_map) for key, item in value.items()}
    return value
