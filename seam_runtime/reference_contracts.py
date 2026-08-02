"""Closed MIRL reference and edge contracts.

Reference identity is determined by the field carrying a value plus canonical
record membership.  Punctuation and record-id-looking prefixes are never used
to promote literal text into an identifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping, Protocol, Sequence

from .mirl import MIRLRecord, RecordKind

VIRTUAL_REFS_EXTENSION = "seam.virtual_refs"
_REFERENCE_QUERY_CHUNK_SIZE = 500


class ReferenceQueryCursor(Protocol):
    def fetchall(self) -> Sequence[Sequence[object]]: ...


class ReferenceQueryConnection(Protocol):
    def execute(
        self, statement: str, parameters: Sequence[object] = ()
    ) -> ReferenceQueryCursor: ...


class CanonicalReferenceIntegrityError(RuntimeError):
    """A referenced canonical row violates the closed MIRL kind contract."""


class EndpointType(str, Enum):
    RECORD = "record"
    VIRTUAL = "virtual"


class ReferenceMode(str, Enum):
    """How one schema field treats a scalar value."""

    REQUIRED = "required"
    OPTIONAL = "optional"
    LITERAL = "literal"


@dataclass(frozen=True, slots=True)
class ResolvedReference:
    id: str
    endpoint_type: EndpointType | RecordKind


@dataclass(frozen=True, slots=True)
class TypedIREdge:
    src: ResolvedReference
    edge_type: str
    dst: ResolvedReference


def reference_candidate_ids(record: MIRLRecord) -> frozenset[str]:
    """Return exactly the scalar ids inspected by ``typed_ir_edges``.

    The result includes required, optional, provenance, evidence, and
    epistemic-reference fields. Literal-only fields and record-id-looking text
    outside those schema positions are deliberately excluded.
    """

    attrs = record.attrs
    values: list[object] = [*record.prov, *record.evidence]
    if record.kind is RecordKind.SPAN:
        values.append(attrs.get("raw_id"))
    elif record.kind is RecordKind.CLM:
        values.extend((attrs.get("subject"), attrs.get("object")))
    elif record.kind is RecordKind.EVT:
        values.extend(
            (attrs.get("actor") or attrs.get("subject"), attrs.get("object"))
        )
    elif record.kind is RecordKind.REL:
        values.extend((attrs.get("src"), attrs.get("dst")))
    elif record.kind is RecordKind.STA:
        values.append(attrs.get("target") or attrs.get("subject"))
    elif record.kind is RecordKind.PACK:
        values.extend(_reference_values(attrs.get("refs")))
    elif record.kind is RecordKind.FLOW:
        values.extend((attrs.get("src"), attrs.get("dst")))
    elif record.kind is RecordKind.PROV:
        values.append(attrs.get("entity"))

    for edge_type in ("supports", "contradicts", "corrects", "supersedes"):
        values.extend(
            _reference_values(record.ext.get(edge_type) or attrs.get(edge_type))
        )
    return frozenset(
        value.strip()
        for value in values
        if isinstance(value, str) and value.strip()
    )


def stored_reference_kinds(
    connection: ReferenceQueryConnection,
    candidate_ids: Iterable[str],
) -> dict[str, RecordKind]:
    """Load canonical kinds for only the requested reference candidates."""

    ordered_ids = sorted(set(candidate_ids))
    known: dict[str, RecordKind] = {}
    for offset in range(0, len(ordered_ids), _REFERENCE_QUERY_CHUNK_SIZE):
        chunk = ordered_ids[offset : offset + _REFERENCE_QUERY_CHUNK_SIZE]
        placeholders = ",".join("?" for _ in chunk)
        cursor = connection.execute(
            f"select id, kind from ir_records where id in ({placeholders})",
            chunk,
        )
        for row in cursor.fetchall():
            try:
                known[str(row[0])] = RecordKind(str(row[1]))
            except ValueError as exc:
                raise CanonicalReferenceIntegrityError(
                    "stored canonical reference has an invalid MIRL kind"
                ) from exc
    return known


def explicit_virtual_references(record: MIRLRecord) -> frozenset[str]:
    """Return explicitly declared virtual entity ids for ``record``.

    Virtual identities are an extension-level contract, not an id-prefix
    exception.  This keeps a missing canonical ENT distinguishable from a
    deliberate graph-only identity.
    """

    value = record.ext.get(VIRTUAL_REFS_EXTENSION, ())
    if value in (None, ()):
        return frozenset()
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{VIRTUAL_REFS_EXTENSION} must be a list of ids")
    refs: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(
                f"{VIRTUAL_REFS_EXTENSION} must contain non-empty string ids"
            )
        if item != item.strip():
            raise ValueError(
                f"{VIRTUAL_REFS_EXTENSION} ids must not contain edge whitespace"
            )
        refs.add(item)
    return frozenset(refs)


def resolve_reference(
    record: MIRLRecord,
    value: object,
    *,
    known_record_kinds: Mapping[str, RecordKind],
    mode: ReferenceMode,
) -> ResolvedReference | None:
    """Resolve one value according to an explicit field contract."""

    if mode is ReferenceMode.LITERAL or value is None:
        return None
    if not isinstance(value, str):
        if mode is ReferenceMode.REQUIRED:
            raise TypeError("required MIRL references must be string ids")
        return None
    text = value.strip()
    if not text:
        return None
    if text in known_record_kinds:
        return ResolvedReference(text, known_record_kinds[text])
    if text in explicit_virtual_references(record):
        return ResolvedReference(text, EndpointType.VIRTUAL)
    if mode is ReferenceMode.REQUIRED:
        # A required reference remains typed as canonical even while dangling,
        # so the integrity sweep can remove the orphan deterministically.
        return ResolvedReference(text, EndpointType.RECORD)
    return None


def typed_ir_edges(
    record: MIRLRecord,
    *,
    known_record_kinds: Mapping[str, RecordKind],
) -> tuple[TypedIREdge, ...]:
    """Project one MIRL record into typed canonical/virtual IR edges."""

    record_ref = ResolvedReference(record.id, record.kind)
    attrs = record.attrs
    edges: list[TypedIREdge] = []

    def ref(value: object, mode: ReferenceMode) -> ResolvedReference | None:
        return resolve_reference(
            record,
            value,
            known_record_kinds=known_record_kinds,
            mode=mode,
        )

    def add(
        src: ResolvedReference | None,
        edge_type: object,
        dst: ResolvedReference | None,
    ) -> None:
        if src is None or dst is None or src.id == dst.id:
            return
        edges.append(TypedIREdge(src, str(edge_type or "related_to"), dst))

    for target in record.prov:
        add(record_ref, "prov", ref(target, ReferenceMode.REQUIRED))
    for target in record.evidence:
        add(record_ref, "evidence", ref(target, ReferenceMode.REQUIRED))

    if record.kind is RecordKind.SPAN:
        add(record_ref, "excerpt_of", ref(attrs.get("raw_id"), ReferenceMode.REQUIRED))
    elif record.kind is RecordKind.CLM:
        subject = ref(attrs.get("subject"), ReferenceMode.REQUIRED)
        obj = ref(attrs.get("object"), ReferenceMode.OPTIONAL)
        add(subject, attrs.get("predicate"), obj)
    elif record.kind is RecordKind.EVT:
        actor = ref(
            attrs.get("actor") or attrs.get("subject"), ReferenceMode.REQUIRED
        )
        add(actor, attrs.get("action") or "participated_in", record_ref)
        add(record_ref, "object", ref(attrs.get("object"), ReferenceMode.OPTIONAL))
    elif record.kind is RecordKind.REL:
        add(
            ref(attrs.get("src"), ReferenceMode.REQUIRED),
            attrs.get("predicate"),
            ref(attrs.get("dst"), ReferenceMode.REQUIRED),
        )
    elif record.kind is RecordKind.STA:
        add(
            ref(
                attrs.get("target") or attrs.get("subject"),
                ReferenceMode.REQUIRED,
            ),
            "has_state",
            record_ref,
        )
    elif record.kind is RecordKind.PACK:
        for target in _reference_values(attrs.get("refs")):
            add(record_ref, "ref", ref(target, ReferenceMode.REQUIRED))
    elif record.kind is RecordKind.FLOW:
        add(
            ref(attrs.get("src"), ReferenceMode.REQUIRED),
            attrs.get("predicate") or attrs.get("op") or "flows_to",
            ref(attrs.get("dst"), ReferenceMode.REQUIRED),
        )
    elif record.kind is RecordKind.PROV:
        add(record_ref, "entity", ref(attrs.get("entity"), ReferenceMode.REQUIRED))

    for edge_type in ("supports", "contradicts", "corrects", "supersedes"):
        for target in _reference_values(
            record.ext.get(edge_type) or attrs.get(edge_type)
        ):
            add(record_ref, edge_type, ref(target, ReferenceMode.REQUIRED))

    return tuple(dict.fromkeys(edges))


def _reference_values(value: object) -> Iterable[str]:
    if isinstance(value, str):
        if value.strip():
            yield value
        return
    if isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            if isinstance(item, str) and item.strip():
                yield item
