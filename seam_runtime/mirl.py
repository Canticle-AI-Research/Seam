from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable

SCHEMA_VERSION = "mirl/0.1"
VALID_SCOPES = {"global", "org", "project", "user", "thread", "ephemeral"}
PACK_MODES = {"exact", "context", "narrative"}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class RecordKind(str, Enum):
    RAW = "RAW"
    SPAN = "SPAN"
    ENT = "ENT"
    CLM = "CLM"
    EVT = "EVT"
    REL = "REL"
    STA = "STA"
    SYM = "SYM"
    PACK = "PACK"
    FLOW = "FLOW"
    PROV = "PROV"
    META = "META"


SYMBOL_FOR_KIND: dict[RecordKind, str] = {
    RecordKind.ENT: "@",
    RecordKind.CLM: "#",
    RecordKind.EVT: "!",
    RecordKind.REL: ">",
    RecordKind.STA: "~",
    RecordKind.PROV: "^",
    RecordKind.RAW: "%",
    RecordKind.SYM: "=",
    RecordKind.SPAN: "§",
    RecordKind.PACK: "◇",
    RecordKind.FLOW: "→",
    RecordKind.META: "μ",
}
assert set(SYMBOL_FOR_KIND.keys()) == set(RecordKind), "SYMBOL_FOR_KIND must cover every RecordKind"


class Status(str, Enum):
    ASSERTED = "asserted"
    OBSERVED = "observed"
    INFERRED = "inferred"
    HYPOTHETICAL = "hypothetical"
    CONTRADICTED = "contradicted"
    SUPERSEDED = "superseded"
    DEPRECATED = "deprecated"
    DELETED_SOFT = "deleted_soft"


@dataclass
class MIRLRecord:
    id: str
    kind: RecordKind
    ns: str = "local.default"
    scope: str = "project"
    ver: str = SCHEMA_VERSION
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    conf: float = 1.0
    status: Status = Status.ASSERTED
    t0: str | None = None
    t1: str | None = None
    prov: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    ext: dict[str, Any] = field(default_factory=dict)
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "ns": self.ns,
            "scope": self.scope,
            "ver": self.ver,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "conf": round(float(self.conf), 6),
            "status": self.status.value,
            "t0": self.t0,
            "t1": self.t1,
            "prov": list(self.prov),
            "evidence": list(self.evidence),
            "ext": self.ext,
            "attrs": self.attrs,
        }

    def payload_dict(self) -> dict[str, Any]:
        data = self.to_dict()
        data.pop("id")
        data.pop("kind")
        return data

    def to_text_line(self) -> str:
        payload = json.dumps(self.payload_dict(), sort_keys=True, separators=(",", ":"))
        return f"{self.kind.value}|{self.id}|{payload}"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MIRLRecord":
        record_id = data["id"]
        if not isinstance(record_id, str):
            raise TypeError("MIRL id must be a string")
        if not record_id.strip():
            raise ValueError("MIRL id must be nonblank")
        prov = data.get("prov", [])
        evidence = data.get("evidence", [])
        ext = data.get("ext", {})
        attrs = data.get("attrs", {})
        if not isinstance(prov, list):
            raise TypeError("MIRL prov must be a list")
        if not isinstance(evidence, list):
            raise TypeError("MIRL evidence must be a list")
        if not isinstance(ext, dict):
            raise TypeError("MIRL ext must be an object")
        if not isinstance(attrs, dict):
            raise TypeError("MIRL attrs must be an object")
        return cls(
            id=record_id,
            kind=RecordKind(data["kind"]),
            ns=data.get("ns", "local.default"),
            scope=data.get("scope", "project"),
            ver=data.get("ver", SCHEMA_VERSION),
            created_at=data.get("created_at", utc_now()),
            updated_at=data.get("updated_at", utc_now()),
            conf=float(data.get("conf", 1.0)),
            status=Status(data.get("status", Status.ASSERTED.value)),
            t0=data.get("t0"),
            t1=data.get("t1"),
            prov=list(prov),
            evidence=list(evidence),
            ext=dict(ext),
            attrs=dict(attrs),
        )

    @classmethod
    def from_text_line(cls, line: str, line_number: int | None = None) -> "MIRLRecord":
        prefix = f"MIRL line {line_number}" if line_number is not None else "MIRL line"
        try:
            kind, record_id, payload = line.split("|", 2)
        except ValueError as exc:
            raise ValueError(f"{prefix}: expected KIND|id|json payload") from exc
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{prefix}: invalid JSON payload: {exc.msg}") from exc
        data["id"] = record_id
        data["kind"] = kind
        try:
            return cls.from_dict(data)
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{prefix}: invalid MIRL record {record_id!r}: {exc}") from exc


@dataclass
class IRBatch:
    records: list[MIRLRecord]

    def to_text(self) -> str:
        return "\n".join(record.to_text_line() for record in sorted(self.records, key=lambda item: item.id))

    def to_json(self) -> list[dict[str, Any]]:
        return [record.to_dict() for record in sorted(self.records, key=lambda item: item.id)]

    def by_id(self) -> dict[str, MIRLRecord]:
        return {record.id: record for record in self.records}

    def kind(self, kind: RecordKind) -> list[MIRLRecord]:
        return [record for record in self.records if record.kind == kind]

    @classmethod
    def from_text(cls, text: str) -> "IRBatch":
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        return cls([MIRLRecord.from_text_line(line, line_number=index) for index, line in enumerate(lines, start=1)])

    @classmethod
    def from_json(cls, payload: list[dict[str, Any]]) -> "IRBatch":
        return cls([MIRLRecord.from_dict(item) for item in payload])


@dataclass
class VerifyIssue:
    level: str
    code: str
    message: str
    record_id: str | None = None


@dataclass
class VerifyReport:
    issues: list[VerifyIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(issue.level == "error" for issue in self.issues)

    def add(self, level: str, code: str, message: str, record_id: str | None = None) -> None:
        self.issues.append(VerifyIssue(level=level, code=code, message=message, record_id=record_id))

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "issues": [
                {
                    "level": issue.level,
                    "code": issue.code,
                    "message": issue.message,
                    "record_id": issue.record_id,
                }
                for issue in self.issues
            ],
        }


@dataclass
class PersistReport:
    stored_ids: list[str]
    store_path: str

    def to_dict(self) -> dict[str, Any]:
        return {"stored_ids": self.stored_ids, "store_path": self.store_path}


@dataclass
class Pack:
    pack_id: str
    mode: str
    lens: str
    refs: list[str]
    payload: dict[str, Any]
    budget: int
    reversible: bool
    token_cost: int
    profile: str = "default"
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "pack_id": self.pack_id,
            "mode": self.mode,
            "lens": self.lens,
            "refs": self.refs,
            "payload": self.payload,
            "budget": self.budget,
            "reversible": self.reversible,
            "token_cost": self.token_cost,
            "profile": self.profile,
            "created_at": self.created_at,
        }

    def to_record(self, ns: str = "local.default", scope: str = "project") -> MIRLRecord:
        return MIRLRecord(
            id=self.pack_id,
            kind=RecordKind.PACK,
            ns=ns,
            scope=scope,
            status=Status.OBSERVED,
            attrs={
                "mode": self.mode,
                "lens": self.lens,
                "refs": self.refs,
                "payload": self.payload,
                "budget": self.budget,
                "reversible": self.reversible,
                "token_cost": self.token_cost,
                "profile": self.profile,
            },
        )

    @classmethod
    def from_record(cls, record: MIRLRecord) -> "Pack":
        attrs = record.attrs
        return cls(
            pack_id=record.id,
            mode=attrs.get("mode", "context"),
            lens=attrs.get("lens", "general"),
            refs=list(attrs.get("refs", [])),
            payload=dict(attrs.get("payload", {})),
            budget=int(attrs.get("budget", 0)),
            reversible=bool(attrs.get("reversible", False)),
            token_cost=int(attrs.get("token_cost", 0)),
            profile=str(attrs.get("profile", "default")),
            created_at=record.created_at,
        )


@dataclass
class SearchCandidate:
    record: MIRLRecord
    score: float
    reasons: list[str] = field(default_factory=list)
    evidence: list[MIRLRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "record": self.record.to_dict(),
            "score": round(self.score, 6),
            "reasons": self.reasons,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass
class SearchResult:
    query: str
    candidates: list[SearchCandidate]
    # Per-leg retrieval trace, populated only when the caller asks for it via
    # `search_ir(include_trace=True)`. Observational only: it never influences
    # candidate selection or ordering, so a traced run stays byte-identical to
    # an untraced one for ranking-attribution A/Bs.
    trace: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "query": self.query,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }
        # Omitted entirely when absent so existing exact-dict consumers are
        # unaffected by the trace field.
        if self.trace is not None:
            payload["trace"] = self.trace
        return payload


@dataclass
class TraceGraph:
    root_id: str
    nodes: list[MIRLRecord]
    edges: list[dict[str, str]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_id": self.root_id,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": self.edges,
        }


@dataclass
class ReconcileReport:
    added_records: list[MIRLRecord]
    actions: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "added_records": [record.to_dict() for record in self.added_records],
            "actions": self.actions,
        }


@dataclass
class Artifact:
    target: str
    body: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"target": self.target, "body": self.body, "metadata": self.metadata}


def token_count(text: str) -> int:
    from .tokenization import count_tokens
    return count_tokens(text)


def cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    """Cosine similarity for sparse / bag-of-words vectors stored as dicts.

    Keys are token strings, values are weights.  Use this when working with
    the lexical retrieval path (see ``seam_runtime.retrieval``).

    For dense embedding vectors (``list[float]``), use ``seam_runtime.models.cosine`` instead.
    """
    if not left or not right:
        return 0.0
    numerator = sum(left[token] * right.get(token, 0.0) for token in left)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return numerator / (left_norm * right_norm)


def iter_textual_fields(record: MIRLRecord) -> Iterable[str]:
    for key, value in record.attrs.items():
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    yield item
        elif isinstance(value, dict):
            for subvalue in (value[k] for k in sorted(value.keys())):
                if isinstance(subvalue, str):
                    yield subvalue
