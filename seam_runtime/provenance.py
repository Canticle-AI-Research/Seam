"""Resolve and VERIFY a retrieved record's provenance chain to its source span.

MIRL keeps the whole path from a claim back to the bytes it came from:

    CLM --prov--> PROV                (how the record was compiled)
        --evidence--> SPAN            (which slice of the source)
                        --raw_id--> RAW   (the source text itself)

The data is lossless by construction, but retrieval historically handed back a
record and stopped, so nothing ever resolved or checked that path. This module
walks it and returns a chain that is either COMPLETE and verified, or reports
exactly which hop broke. A provenance system that silently drops a broken link
is worse than one that has none, because it still looks authoritative.

Distinct from ``SQLiteStore.trace()``, which does an unbounded BFS over prov,
evidence AND knowledge_edges and returns nodes+edges. That answers "what is
connected to this?". This answers "prove where this came from, exactly", and
carries the source span text so the caller never has to re-read the store.

Competitive note: systems that extract facts and discard the source cannot
produce this at all - there is no span to return. Chain completeness is
therefore a capability measurement, not a tuning score.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from seam_runtime.mirl import MIRLRecord, RecordKind

# A chain hop is verified only when every one of these holds. Anything else is
# recorded as a defect string rather than being dropped from the result.
DEFECT_NO_EVIDENCE = "no_evidence_links"
DEFECT_SPAN_MISSING = "span_record_missing"
DEFECT_SPAN_NOT_SPAN = "referenced_record_is_not_a_span"
DEFECT_RAW_ID_ABSENT = "span_carries_no_raw_id"
DEFECT_RAW_MISSING = "raw_record_missing"
DEFECT_RAW_NOT_RAW = "referenced_record_is_not_raw"
DEFECT_RAW_CONTENT_MISSING = "raw_carries_no_string_content"
DEFECT_OFFSETS_INVALID = "span_offsets_outside_raw_content"

PROVENANCE_CONTRACT = "provenance-chain/1"


@dataclass(frozen=True, slots=True)
class ProvenanceLink:
    """One resolved evidence hop: claim -> SPAN -> RAW, plus the source text."""

    span_id: str
    raw_id: str | None = None
    start: int | None = None
    end: int | None = None
    text: str | None = None
    verified: bool = False
    defect: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "span_id": self.span_id,
            "raw_id": self.raw_id,
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "verified": self.verified,
            "defect": self.defect,
        }


@dataclass(frozen=True, slots=True)
class ProvenanceChain:
    """Every verified route from one retrieved record back to source bytes."""

    record_id: str
    record_kind: str
    prov_ids: tuple[str, ...] = ()
    links: tuple[ProvenanceLink, ...] = ()
    defect: str | None = None

    @property
    def complete(self) -> bool:
        """True only when there is at least one link and EVERY link verified.

        Deliberately strict: a record with one good link and one broken one is
        not a trustworthy citation, so it does not count toward completeness.
        """

        return bool(self.links) and all(link.verified for link in self.links)

    @property
    def source_text(self) -> tuple[str, ...]:
        """The exact source spans, in link order. Empty when unverified."""

        return tuple(link.text for link in self.links if link.verified and link.text is not None)

    def to_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "record_kind": self.record_kind,
            "contract": PROVENANCE_CONTRACT,
            "prov_ids": list(self.prov_ids),
            "links": [link.to_dict() for link in self.links],
            "complete": self.complete,
            "defect": self.defect,
        }


@dataclass
class _RecordLookup:
    """Batch record fetch with a per-resolution cache.

    A page of candidates usually shares source turns, so the same SPAN and RAW
    records repeat across candidates. Caching keeps chain resolution from
    turning one query into hundreds of point reads.
    """

    store: object
    _cache: dict[str, MIRLRecord | None] = field(default_factory=dict)

    def prefetch(self, record_ids: set[str]) -> None:
        wanted = [rid for rid in record_ids if rid and rid not in self._cache]
        if not wanted:
            return
        batch = self.store.load_ir(ids=wanted)
        for record in batch.records:
            self._cache[record.id] = record
        for rid in wanted:
            self._cache.setdefault(rid, None)

    def get(self, record_id: str | None) -> MIRLRecord | None:
        if not record_id:
            return None
        if record_id not in self._cache:
            self.prefetch({record_id})
        return self._cache.get(record_id)


def _raw_self_chain(record: MIRLRecord) -> ProvenanceChain:
    """A RAW record IS the source, so it is its own verified provenance."""

    content = record.attrs.get("content")
    text = content if isinstance(content, str) else None
    return ProvenanceChain(
        record_id=record.id,
        record_kind=record.kind.value,
        prov_ids=tuple(record.prov),
        links=(
            ProvenanceLink(
                span_id=record.id,
                raw_id=record.id,
                start=0,
                end=len(text) if text is not None else None,
                text=text,
                verified=text is not None,
                defect=None if text is not None else DEFECT_RAW_CONTENT_MISSING,
            ),
        ),
    )


def _resolve_link(span_id: str, lookup: _RecordLookup) -> ProvenanceLink:
    span = lookup.get(span_id)
    if span is None:
        return ProvenanceLink(span_id=span_id, defect=DEFECT_SPAN_MISSING)
    if span.kind is not RecordKind.SPAN:
        return ProvenanceLink(span_id=span_id, defect=DEFECT_SPAN_NOT_SPAN)

    raw_id = span.attrs.get("raw_id")
    if not isinstance(raw_id, str) or not raw_id:
        return ProvenanceLink(span_id=span_id, defect=DEFECT_RAW_ID_ABSENT)

    raw = lookup.get(raw_id)
    if raw is None:
        return ProvenanceLink(span_id=span_id, raw_id=raw_id, defect=DEFECT_RAW_MISSING)
    if raw.kind is not RecordKind.RAW:
        return ProvenanceLink(span_id=span_id, raw_id=raw_id, defect=DEFECT_RAW_NOT_RAW)

    content = raw.attrs.get("content")
    start = span.attrs.get("start")
    end = span.attrs.get("end")
    if not isinstance(content, str):
        return ProvenanceLink(
            span_id=span_id,
            raw_id=raw_id,
            start=start if isinstance(start, int) and not isinstance(start, bool) else None,
            end=end if isinstance(end, int) and not isinstance(end, bool) else None,
            defect=DEFECT_RAW_CONTENT_MISSING,
        )
    if (
        not isinstance(start, int)
        or not isinstance(end, int)
        or isinstance(start, bool)
        or isinstance(end, bool)
        or start < 0
        or end < start
        or end > len(content)
    ):
        return ProvenanceLink(
            span_id=span_id,
            raw_id=raw_id,
            start=start if isinstance(start, int) and not isinstance(start, bool) else None,
            end=end if isinstance(end, int) and not isinstance(end, bool) else None,
            defect=DEFECT_OFFSETS_INVALID,
        )

    return ProvenanceLink(
        span_id=span_id,
        raw_id=raw_id,
        start=start,
        end=end,
        text=content[start:end],
        verified=True,
    )


def resolve_provenance(store, record: MIRLRecord) -> ProvenanceChain:
    """Resolve one record's verified chain back to its source span(s)."""

    return resolve_provenance_many(store, [record])[record.id]


def resolve_provenance_many(
    store, records: list[MIRLRecord]
) -> dict[str, ProvenanceChain]:
    """Resolve a page of candidates in one pass, sharing the record cache."""

    lookup = _RecordLookup(store=store)
    span_ids = {span_id for record in records for span_id in record.evidence}
    lookup.prefetch(span_ids)
    # Second wave: the RAW ids those spans point at, fetched as one batch.
    raw_ids: set[str] = set()
    for span_id in span_ids:
        span = lookup.get(span_id)
        if span is not None and span.kind is RecordKind.SPAN:
            raw_id = span.attrs.get("raw_id")
            if isinstance(raw_id, str) and raw_id:
                raw_ids.add(raw_id)
    lookup.prefetch(raw_ids)

    chains: dict[str, ProvenanceChain] = {}
    for record in records:
        if record.kind is RecordKind.RAW:
            chains[record.id] = _raw_self_chain(record)
            continue
        if not record.evidence:
            chains[record.id] = ProvenanceChain(
                record_id=record.id,
                record_kind=record.kind.value,
                prov_ids=tuple(record.prov),
                defect=DEFECT_NO_EVIDENCE,
            )
            continue
        chains[record.id] = ProvenanceChain(
            record_id=record.id,
            record_kind=record.kind.value,
            prov_ids=tuple(record.prov),
            links=tuple(_resolve_link(span_id, lookup) for span_id in record.evidence),
        )
    return chains


def chain_completeness(chains: list[ProvenanceChain]) -> dict[str, object]:
    """The metric: what fraction of retrieved records can prove their origin.

    SEAM's target is 1.00 - the chain is lossless by construction, so anything
    below that is a locatable defect rather than a tuning shortfall. Systems
    that discard the source score 0.00 here and cannot improve without changing
    their storage model.
    """

    total = len(chains)
    if total == 0:
        return {
            "contract": PROVENANCE_CONTRACT,
            "total": 0,
            "complete": 0,
            "completeness": 1.0,
            "defects": {},
        }
    complete = sum(1 for chain in chains if chain.complete)
    defects: dict[str, int] = {}
    for chain in chains:
        if chain.complete:
            continue
        if chain.defect:
            defects[chain.defect] = defects.get(chain.defect, 0) + 1
        for link in chain.links:
            if not link.verified and link.defect:
                defects[link.defect] = defects.get(link.defect, 0) + 1
    return {
        "contract": PROVENANCE_CONTRACT,
        "total": total,
        "complete": complete,
        "completeness": complete / total,
        "defects": dict(sorted(defects.items())),
    }
