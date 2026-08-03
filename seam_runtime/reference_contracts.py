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


class CanonicalReferenceMetadataError(CanonicalReferenceIntegrityError):
    """Reserved record-level reference metadata violates its closed shape."""


class CanonicalReferenceShapeError(CanonicalReferenceIntegrityError):
    """A required MIRL reference uses an invalid scalar or list shape."""


class EndpointType(str, Enum):
    RECORD = "record"
    VIRTUAL = "virtual"


class ReferenceMode(str, Enum):
    """How one schema field treats a scalar value."""

    REQUIRED = "required"
    OPTIONAL = "optional"
    LITERAL = "literal"


class _RequiredReferenceShape(str, Enum):
    SCALAR = "scalar"
    LIST = "list"
    SCALAR_OR_LIST = "scalar_or_list"


@dataclass(frozen=True, slots=True)
class ResolvedReference:
    id: str
    endpoint_type: EndpointType | RecordKind


@dataclass(frozen=True, slots=True)
class TypedIREdge:
    src: ResolvedReference
    edge_type: str
    dst: ResolvedReference


RECONCILIATION_REFERENCE_FIELDS = (
    "supports",
    "contradicts",
    "corrects",
    "supersedes",
    "refutes",
    "corroborates",
    "derived_from",
    "unverified_by",
)

FACET_REFERENCE_FIELDS = (
    "who",
    "what",
    "when",
    "where",
    "why",
    "how",
    "then",
)

_REQUIRED_SCALAR_REFERENCE_GROUPS = {
    RecordKind.SPAN: (("raw_id",),),
    RecordKind.CLM: (("subject",),),
    RecordKind.EVT: (("actor", "subject"),),
    RecordKind.REL: (("src",), ("dst",)),
    RecordKind.STA: (("target", "subject"),),
    RecordKind.PROV: (("entity",),),
}


def remap_record_references(
    record: MIRLRecord,
    id_map: Mapping[str, str],
) -> None:
    """Rewrite only schema-declared MIRL reference positions in place.

    This is the write-side companion to the typed-edge and knowledge-graph
    consumers. It stays closed over their shared reference-bearing fields:
    arbitrary strings elsewhere in ``attrs``/``ext`` remain literal payload
    and are never remapped merely because they resemble an identifier.
    """

    if not id_map:
        return

    record.prov = [_remap_scalar_reference(value, id_map) for value in record.prov]
    record.evidence = [
        _remap_scalar_reference(value, id_map) for value in record.evidence
    ]

    attrs = record.attrs
    if record.kind is RecordKind.SPAN:
        _remap_mapping_reference(attrs, "raw_id", id_map)
    elif record.kind is RecordKind.CLM:
        _remap_mapping_reference(attrs, "subject", id_map)
        _remap_mapping_reference(attrs, "object", id_map)
    elif record.kind is RecordKind.EVT:
        _remap_mapping_reference(attrs, "actor", id_map)
        _remap_mapping_reference(attrs, "subject", id_map)
        _remap_mapping_reference(attrs, "object", id_map)
    elif record.kind is RecordKind.REL:
        _remap_mapping_reference(attrs, "src", id_map)
        _remap_mapping_reference(attrs, "dst", id_map)
    elif record.kind is RecordKind.STA:
        _remap_mapping_reference(attrs, "target", id_map)
        _remap_mapping_reference(attrs, "subject", id_map)
    elif record.kind is RecordKind.PACK:
        _remap_mapping_references(attrs, "refs", id_map)
    elif record.kind is RecordKind.FLOW:
        _remap_mapping_reference(attrs, "src", id_map)
        _remap_mapping_reference(attrs, "dst", id_map)
    elif record.kind is RecordKind.PROV:
        _remap_mapping_reference(attrs, "entity", id_map)

    for container in (attrs, record.ext):
        for edge_type in RECONCILIATION_REFERENCE_FIELDS:
            _remap_mapping_references(container, edge_type, id_map)
    facets = attrs.get("facets")
    if isinstance(facets, dict):
        for facet in FACET_REFERENCE_FIELDS:
            _remap_mapping_reference(facets, facet, id_map)
    _remap_mapping_references(record.ext, VIRTUAL_REFS_EXTENSION, id_map)


def reference_candidate_ids(record: MIRLRecord) -> frozenset[str]:
    """Return scalar ids inspected by the closed reference consumers.

    The result includes required, optional, provenance, evidence, and
    reconciliation-reference fields plus explicit optional facets. Literal-only
    fields and record-id-looking text outside those schema positions are
    deliberately excluded.
    """

    attrs = record.attrs
    values: list[object] = [
        *_required_reference_ids(record.prov, _RequiredReferenceShape.LIST),
        *_required_reference_ids(record.evidence, _RequiredReferenceShape.LIST),
    ]
    if record.kind is RecordKind.SPAN:
        values.append(_required_scalar_reference(record, ("raw_id",)))
    elif record.kind is RecordKind.CLM:
        values.extend(
            (
                _required_scalar_reference(record, ("subject",)),
                attrs.get("object"),
            )
        )
    elif record.kind is RecordKind.EVT:
        values.extend(
            (
                _required_scalar_reference(record, ("actor", "subject")),
                attrs.get("object"),
            )
        )
    elif record.kind is RecordKind.REL:
        values.extend(
            (
                _required_scalar_reference(record, ("src",)),
                _required_scalar_reference(record, ("dst",)),
            )
        )
    elif record.kind is RecordKind.STA:
        values.append(_required_scalar_reference(record, ("target", "subject")))
    elif record.kind is RecordKind.PACK:
        values.extend(
            _required_reference_ids(
                attrs.get("refs"),
                _RequiredReferenceShape.LIST,
            )
        )
    elif record.kind is RecordKind.FLOW:
        values.extend(_flow_reference_ids(record))
    elif record.kind is RecordKind.PROV:
        values.append(_required_scalar_reference(record, ("entity",)))

    for edge_type in RECONCILIATION_REFERENCE_FIELDS:
        values.extend(_reconciliation_reference_ids(record, edge_type))
    facets = attrs.get("facets")
    if isinstance(facets, Mapping):
        values.extend(facets.get(facet) for facet in FACET_REFERENCE_FIELDS)
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

    if VIRTUAL_REFS_EXTENSION not in record.ext:
        return frozenset()
    value = record.ext[VIRTUAL_REFS_EXTENSION]
    if not isinstance(value, list):
        raise CanonicalReferenceMetadataError(
            "virtual reference declaration must be a list of ids"
        )
    refs: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise CanonicalReferenceMetadataError(
                "virtual reference declaration must contain non-empty string ids"
            )
        if item != item.strip():
            raise CanonicalReferenceMetadataError(
                "virtual reference declaration ids must not contain edge whitespace"
            )
        refs.add(item)
    return frozenset(refs)


def validate_record_reference_contract(record: MIRLRecord) -> frozenset[str]:
    """Validate record-level reference metadata and return declared virtual ids.

    Callers validate once before inspecting individual fields, then pass the
    returned set through reference resolution.  This makes the reserved
    extension fail closed even when a record has no references or every
    endpoint resolves canonically.
    """

    virtual_references = explicit_virtual_references(record)
    _validate_required_reference_shapes(record)
    return virtual_references


def _required_reference_ids(
    value: object,
    shape: _RequiredReferenceShape,
) -> tuple[str, ...]:
    """Validate one required reference position without exposing its value."""

    if shape is _RequiredReferenceShape.SCALAR:
        values = (value,)
    elif shape is _RequiredReferenceShape.LIST:
        if not isinstance(value, list):
            raise CanonicalReferenceShapeError("required reference value is invalid")
        values = tuple(value)
    elif isinstance(value, str):
        values = (value,)
    elif isinstance(value, list):
        values = tuple(value)
    else:
        raise CanonicalReferenceShapeError("required reference value is invalid")

    references: list[str] = []
    for item in values:
        if (
            not isinstance(item, str)
            or not item.strip()
            or item != item.strip()
        ):
            raise CanonicalReferenceShapeError("required reference value is invalid")
        references.append(item)
    return tuple(references)


def _required_scalar_reference(
    record: MIRLRecord,
    aliases: tuple[str, ...],
) -> str:
    """Return the preferred required alias after validating every supplied alias."""

    selected: str | None = None
    for field in aliases:
        if field not in record.attrs:
            continue
        reference = _required_reference_ids(
            record.attrs[field],
            _RequiredReferenceShape.SCALAR,
        )[0]
        if selected is None:
            selected = reference
        elif reference != selected:
            raise CanonicalReferenceIntegrityError(
                "required reference aliases disagree"
            )
    if selected is None:
        _required_reference_ids(None, _RequiredReferenceShape.SCALAR)
        raise AssertionError("unreachable")
    return selected


def _reconciliation_reference_ids(
    record: MIRLRecord,
    field: str,
) -> tuple[str, ...]:
    """Validate both pointer containers and return the effective pointer values."""

    attrs_references: tuple[str, ...] | None = None
    if field in record.attrs:
        attrs_references = _required_reference_ids(
            record.attrs[field],
            _RequiredReferenceShape.SCALAR_OR_LIST,
        )
    ext_references: tuple[str, ...] | None = None
    if field in record.ext:
        ext_references = _required_reference_ids(
            record.ext[field],
            _RequiredReferenceShape.SCALAR_OR_LIST,
        )

    if ext_references:
        return ext_references
    if attrs_references is not None:
        return attrs_references
    if ext_references is not None:
        return ext_references
    return ()


def _flow_reference_ids(record: MIRLRecord) -> tuple[str, ...]:
    """Return a FLOW's optional linked endpoints as one closed pair."""

    if "src" not in record.attrs and "dst" not in record.attrs:
        return ()
    return (
        _required_scalar_reference(record, ("src",)),
        _required_scalar_reference(record, ("dst",)),
    )


def _validate_required_reference_shapes(record: MIRLRecord) -> None:
    _required_reference_ids(record.prov, _RequiredReferenceShape.LIST)
    _required_reference_ids(record.evidence, _RequiredReferenceShape.LIST)
    for aliases in _REQUIRED_SCALAR_REFERENCE_GROUPS.get(record.kind, ()):
        _required_scalar_reference(record, aliases)
    if record.kind is RecordKind.FLOW:
        _flow_reference_ids(record)
    if record.kind is RecordKind.PACK:
        _required_reference_ids(
            record.attrs.get("refs"),
            _RequiredReferenceShape.LIST,
        )
    for field in RECONCILIATION_REFERENCE_FIELDS:
        _reconciliation_reference_ids(record, field)


def resolve_reference(
    record: MIRLRecord,
    value: object,
    *,
    known_record_kinds: Mapping[str, RecordKind],
    mode: ReferenceMode,
    expected_kinds: frozenset[RecordKind] | None = None,
    validated_virtual_references: frozenset[str] | None = None,
) -> ResolvedReference | None:
    """Resolve one value according to an explicit field contract."""

    virtual_references = (
        validate_record_reference_contract(record)
        if validated_virtual_references is None
        else validated_virtual_references
    )
    if mode is ReferenceMode.LITERAL:
        return None
    if mode is ReferenceMode.REQUIRED:
        text = _required_reference_ids(
            value,
            _RequiredReferenceShape.SCALAR,
        )[0]
    elif not isinstance(value, str):
        return None
    else:
        text = value.strip()
        if not text:
            return None
    if text in known_record_kinds:
        actual_kind = known_record_kinds[text]
        if expected_kinds is not None and actual_kind not in expected_kinds:
            raise CanonicalReferenceIntegrityError(
                "canonical reference kind violates field contract"
            )
        return ResolvedReference(text, actual_kind)
    if text in virtual_references:
        if expected_kinds is not None:
            raise CanonicalReferenceIntegrityError(
                "virtual reference violates canonical field-kind contract"
            )
        return ResolvedReference(text, EndpointType.VIRTUAL)
    if mode is ReferenceMode.REQUIRED:
        raise CanonicalReferenceIntegrityError(
            "required canonical reference is missing"
        )
    return None


def typed_ir_edges(
    record: MIRLRecord,
    *,
    known_record_kinds: Mapping[str, RecordKind],
    validated_virtual_references: frozenset[str] | None = None,
) -> tuple[TypedIREdge, ...]:
    """Project one MIRL record into typed canonical/virtual IR edges."""

    virtual_references = (
        validate_record_reference_contract(record)
        if validated_virtual_references is None
        else validated_virtual_references
    )
    record_ref = ResolvedReference(record.id, record.kind)
    attrs = record.attrs
    edges: list[TypedIREdge] = []

    def ref(
        value: object,
        mode: ReferenceMode,
        expected_kinds: frozenset[RecordKind] | None = None,
    ) -> ResolvedReference | None:
        return resolve_reference(
            record,
            value,
            known_record_kinds=known_record_kinds,
            mode=mode,
            expected_kinds=expected_kinds,
            validated_virtual_references=virtual_references,
        )

    def add(
        src: ResolvedReference | None,
        edge_type: object,
        dst: ResolvedReference | None,
    ) -> None:
        if src is None or dst is None or src.id == dst.id:
            return
        edges.append(TypedIREdge(src, str(edge_type or "related_to"), dst))

    for target in _required_reference_ids(
        record.prov,
        _RequiredReferenceShape.LIST,
    ):
        add(
            record_ref,
            "prov",
            ref(
                target,
                ReferenceMode.REQUIRED,
                frozenset({RecordKind.PROV}),
            ),
        )
    for target in _required_reference_ids(
        record.evidence,
        _RequiredReferenceShape.LIST,
    ):
        add(
            record_ref,
            "evidence",
            ref(
                target,
                ReferenceMode.REQUIRED,
                frozenset({RecordKind.RAW, RecordKind.SPAN}),
            ),
        )

    if record.kind is RecordKind.SPAN:
        add(
            record_ref,
            "excerpt_of",
            ref(
                _required_scalar_reference(record, ("raw_id",)),
                ReferenceMode.REQUIRED,
                frozenset({RecordKind.RAW}),
            ),
        )
    elif record.kind is RecordKind.CLM:
        subject = ref(
            _required_scalar_reference(record, ("subject",)),
            ReferenceMode.REQUIRED,
        )
        obj = ref(attrs.get("object"), ReferenceMode.OPTIONAL)
        add(subject, attrs.get("predicate"), obj)
    elif record.kind is RecordKind.EVT:
        actor = ref(
            _required_scalar_reference(record, ("actor", "subject")),
            ReferenceMode.REQUIRED,
        )
        add(actor, attrs.get("action") or "participated_in", record_ref)
        add(record_ref, "object", ref(attrs.get("object"), ReferenceMode.OPTIONAL))
    elif record.kind is RecordKind.REL:
        add(
            ref(
                _required_scalar_reference(record, ("src",)),
                ReferenceMode.REQUIRED,
            ),
            attrs.get("predicate"),
            ref(
                _required_scalar_reference(record, ("dst",)),
                ReferenceMode.REQUIRED,
            ),
        )
    elif record.kind is RecordKind.STA:
        add(
            ref(
                _required_scalar_reference(record, ("target", "subject")),
                ReferenceMode.REQUIRED,
            ),
            "has_state",
            record_ref,
        )
    elif record.kind is RecordKind.PACK:
        for target in _required_reference_ids(
            attrs.get("refs"),
            _RequiredReferenceShape.LIST,
        ):
            add(record_ref, "ref", ref(target, ReferenceMode.REQUIRED))
    elif record.kind is RecordKind.FLOW:
        flow_references = _flow_reference_ids(record)
        if flow_references:
            add(
                ref(flow_references[0], ReferenceMode.REQUIRED),
                attrs.get("predicate") or attrs.get("op") or "flows_to",
                ref(flow_references[1], ReferenceMode.REQUIRED),
            )
    elif record.kind is RecordKind.PROV:
        add(
            record_ref,
            "entity",
            ref(
                _required_scalar_reference(record, ("entity",)),
                ReferenceMode.REQUIRED,
            ),
        )

    for edge_type in RECONCILIATION_REFERENCE_FIELDS:
        for target in _reconciliation_reference_ids(record, edge_type):
            add(record_ref, edge_type, ref(target, ReferenceMode.REQUIRED))

    return tuple(dict.fromkeys(edges))


def validate_typed_ir_edges(
    edges: Iterable[TypedIREdge],
    *,
    known_record_kinds: Mapping[str, RecordKind],
) -> None:
    """Reject missing or non-exact canonical endpoints before persistence."""

    for edge in edges:
        for endpoint in (edge.src, edge.dst):
            if endpoint.endpoint_type is EndpointType.VIRTUAL:
                continue
            actual_kind = known_record_kinds.get(endpoint.id)
            if actual_kind is None:
                raise CanonicalReferenceIntegrityError(
                    "required canonical reference is missing"
                )
            if (
                endpoint.endpoint_type is EndpointType.RECORD
                or endpoint.endpoint_type is not actual_kind
            ):
                raise CanonicalReferenceIntegrityError(
                    "canonical reference kind does not match typed endpoint"
                )


def _remap_scalar_reference(value: str, id_map: Mapping[str, str]) -> str:
    return id_map.get(value, value)


def _remap_mapping_reference(
    container: dict[str, object],
    field: str,
    id_map: Mapping[str, str],
) -> None:
    value = container.get(field)
    if isinstance(value, str) and value in id_map:
        container[field] = id_map[value]


def _remap_mapping_references(
    container: dict[str, object],
    field: str,
    id_map: Mapping[str, str],
) -> None:
    if field not in container:
        return
    value = container[field]
    if isinstance(value, str):
        container[field] = id_map.get(value, value)
    elif isinstance(value, list):
        container[field] = [
            id_map.get(item, item) if isinstance(item, str) else item
            for item in value
        ]
    elif isinstance(value, tuple):
        container[field] = tuple(
            id_map.get(item, item) if isinstance(item, str) else item
            for item in value
        )
    elif isinstance(value, set):
        container[field] = {
            id_map.get(item, item) if isinstance(item, str) else item
            for item in value
        }
    elif isinstance(value, frozenset):
        container[field] = frozenset(
            id_map.get(item, item) if isinstance(item, str) else item
            for item in value
        )
