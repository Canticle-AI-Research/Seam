from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .mirl import IRBatch, MIRLRecord, RecordKind, Status, utc_now

ENTITY_RE = re.compile(r'^entity\s+(\w+)\s+"([^"]+)"\s+as\s+(\S+)$')
BLOCK_RE = re.compile(r"^(claim|state|pack|retrieve|raw|span|rel|symbol)\s+(\S+):$")


@dataclass
class ParsedBlock:
    kind: str
    identifier: str
    fields: dict[str, Any]


def compile_dsl(text: str, ns: str = "local.default", scope: str = "project") -> IRBatch:
    top_entities: list[MIRLRecord] = []
    blocks = _parse_blocks(text)

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        entity_match = ENTITY_RE.fullmatch(line)
        if entity_match:
            entity_type, label, identifier = entity_match.groups()
            top_entities.append(
                MIRLRecord(
                    id=identifier,
                    kind=RecordKind.ENT,
                    ns=ns,
                    scope=scope,
                    attrs={"entity_type": entity_type, "label": label},
                )
            )

    records = top_entities[:]
    created_at = utc_now()
    for block in blocks:
        record = _block_to_record(block, ns=ns, scope=scope, created_at=created_at)
        if record is not None:
            records.append(record)
    return IRBatch(records)


def _parse_blocks(text: str) -> list[ParsedBlock]:
    blocks: list[ParsedBlock] = []
    current: ParsedBlock | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ENTITY_RE.fullmatch(stripped):
            continue
        block_match = BLOCK_RE.fullmatch(stripped)
        if block_match:
            if current is not None:
                blocks.append(current)
            current = ParsedBlock(kind=block_match.group(1), identifier=block_match.group(2), fields={})
            continue
        if current is None:
            raise ValueError(f"Unexpected DSL line outside block: {line}")
        if not line.startswith("  "):
            raise ValueError(f"Block field must be indented: {line}")
        key, value = _parse_field(stripped)
        if key == "include":
            current.fields.setdefault("include", []).append(value)
        elif key == "field":
            current.fields.setdefault("fields", {})[value[0]] = value[1]
        else:
            current.fields[key] = value
    if current is not None:
        blocks.append(current)
    return blocks


def _parse_field(line: str) -> tuple[str, Any]:
    parts = line.split(" ", 2)
    if len(parts) < 2:
        raise ValueError(f"Invalid field line: {line}")
    key = parts[0]
    if key == "field":
        if len(parts) != 3:
            raise ValueError(f"field entries require key and value: {line}")
        return key, (parts[1], _parse_scalar(parts[2]))
    value = _parse_scalar(parts[1] if len(parts) == 2 else parts[1] + " " + parts[2])
    return key, value


def _is_int_literal(value: str) -> bool:
    """Match ``-?\\d+`` without a regex (linear, no backtracking)."""
    body = value[1:] if value[:1] == "-" else value
    return bool(body) and body.isdecimal()


def _is_float_literal(value: str) -> bool:
    """Match ``-?\\d+\\.\\d+`` without a regex (linear, no backtracking)."""
    body = value[1:] if value[:1] == "-" else value
    left, dot, right = body.partition(".")
    return bool(dot) and left.isdecimal() and right.isdecimal()


def _parse_scalar(text: str) -> Any:
    value = text.strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [] if not inner else [_parse_scalar(item.strip()) for item in inner.split(",")]
    if _is_int_literal(value):
        return int(value)
    if _is_float_literal(value):
        return float(value)
    lowered = value.lower()
    if lowered in {"asserted", "observed", "inferred", "hypothetical", "contradicted", "superseded", "deprecated", "deleted_soft"}:
        return lowered
    return value


def _block_to_record(block: ParsedBlock, ns: str, scope: str, created_at: str) -> MIRLRecord | None:
    status = Status(str(block.fields.get("status", Status.ASSERTED.value)))
    conf = float(block.fields.get("confidence", block.fields.get("conf", 1.0)))
    evidence = _ensure_list(block.fields.get("evidence"))
    prov = _ensure_list(block.fields.get("prov"))
    kind = {
        "raw": RecordKind.RAW,
        "span": RecordKind.SPAN,
        "claim": RecordKind.CLM,
        "state": RecordKind.STA,
        "pack": RecordKind.PACK,
        "retrieve": RecordKind.FLOW,
        "rel": RecordKind.REL,
        "symbol": RecordKind.SYM,
    }[block.kind]

    if kind == RecordKind.RAW:
        attrs = {"source_ref": block.fields.get("source", f"dsl://{block.identifier}"), "content": block.fields.get("text", "")}
    elif kind == RecordKind.SPAN:
        attrs = {"raw_id": block.fields.get("raw"), "start": int(block.fields.get("start", 0)), "end": int(block.fields.get("end", 0))}
    elif kind == RecordKind.CLM:
        attrs = {"subject": block.fields.get("subject"), "predicate": block.fields.get("predicate"), "object": block.fields.get("object")}
    elif kind == RecordKind.STA:
        attrs = {"target": block.fields.get("target"), "fields": dict(block.fields.get("fields", {}))}
    elif kind == RecordKind.PACK:
        attrs = {
            "mode": str(block.fields.get("mode", "context")),
            "lens": str(block.fields.get("lens", "general")),
            "budget": int(block.fields.get("budget", 512)),
            "refs": [item for item in block.fields.get("include", [])],
            "payload": {},
            "reversible": str(block.fields.get("mode", "context")) == "exact",
            "token_cost": 0,
            "profile": str(block.fields.get("profile", "default")),
        }
    elif kind == RecordKind.FLOW:
        attrs = {"op": "search", "query": block.fields.get("query"), "lens": block.fields.get("lens", "general"), "budget": int(block.fields.get("budget", 10))}
    elif kind == RecordKind.REL:
        attrs = {"src": block.fields.get("src"), "predicate": block.fields.get("predicate"), "dst": block.fields.get("dst")}
    elif kind == RecordKind.SYM:
        attrs = {"symbol": block.fields.get("symbol"), "expansion": block.fields.get("expansion")}
    else:
        return None

    return MIRLRecord(
        id=block.identifier,
        kind=kind,
        ns=str(block.fields.get("namespace", ns)),
        scope=str(block.fields.get("scope", scope)),
        created_at=created_at,
        updated_at=created_at,
        conf=conf,
        status=status,
        prov=prov,
        evidence=evidence,
        attrs=attrs,
    )


def _ensure_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]
