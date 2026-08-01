from __future__ import annotations

from seam_runtime.mirl import MIRLRecord, RecordKind
from seam_runtime.provenance import (
    DEFECT_RAW_CONTENT_MISSING,
    _raw_self_chain,
    _resolve_link,
)


def test_raw_self_chain_names_missing_string_content_exactly():
    raw = MIRLRecord(
        id="raw:invalid",
        kind=RecordKind.RAW,
        ns="work",
        scope="thread",
        attrs={"content": 7},
    )

    chain = _raw_self_chain(raw)

    assert chain.complete is False
    assert chain.links[0].defect == DEFECT_RAW_CONTENT_MISSING
    assert chain.links[0].raw_id == raw.id


def test_span_chain_names_non_string_raw_content_exactly():
    raw = MIRLRecord(
        id="raw:invalid",
        kind=RecordKind.RAW,
        ns="work",
        scope="thread",
        attrs={"content": 7},
    )
    span = MIRLRecord(
        id="span:invalid",
        kind=RecordKind.SPAN,
        ns="work",
        scope="thread",
        attrs={"raw_id": raw.id, "start": 0, "end": 1},
    )

    class Lookup:
        def get(self, record_id):
            return {raw.id: raw, span.id: span}.get(record_id)

    link = _resolve_link(span.id, Lookup())

    assert link.verified is False
    assert link.defect == DEFECT_RAW_CONTENT_MISSING
    assert link.raw_id == raw.id
