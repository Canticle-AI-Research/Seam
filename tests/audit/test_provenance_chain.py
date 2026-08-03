"""The verified provenance chain: claim -> SPAN -> RAW, back to source bytes.

MIRL retains the whole path from a claim to the text it came from. These tests
pin two things:

1. A complete chain resolves and returns the EXACT source span.
2. A broken chain is REPORTED, never silently dropped. Silent dropping is the
   dangerous failure: the caller still gets an authoritative-looking answer,
   just one that cannot actually be traced. Every defect below asserts the
   specific reason code rather than merely asserting "not complete".
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from seam_runtime import SeamRuntime
from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.provenance import (
    DEFECT_NO_EVIDENCE,
    DEFECT_OFFSETS_INVALID,
    DEFECT_RAW_MISSING,
    DEFECT_SPAN_MISSING,
    DEFECT_SPAN_NOT_SPAN,
    chain_completeness,
    resolve_provenance,
    resolve_provenance_many,
)
from seam_runtime.retrieval_orchestrator import RetrievalOrchestrator

SOURCE = "Priya owns the billing service and reviews it weekly."


@pytest.fixture
def runtime(tmp_path):
    instance = SeamRuntime(tmp_path / "provenance.db", allow_pgvector_env=False)
    try:
        yield instance
    finally:
        instance.close()


def _chain_batch(
    *,
    span_raw_id: str | None = "raw:1",
    start: int = 0,
    end: int = 11,
    include_raw: bool = True,
    include_span: bool = True,
) -> IRBatch:
    """A claim bound to span:1 -> raw:1, with each hop independently breakable."""
    records = [
        MIRLRecord(
            id="ent:priya",
            kind=RecordKind.ENT,
            ns="work",
            scope="thread",
            attrs={"label": "Priya", "entity_type": "person"},
        ),
        MIRLRecord(
            id="clm:1",
            kind=RecordKind.CLM,
            ns="work",
            scope="thread",
            attrs={"subject": "ent:priya", "predicate": "owns", "object": "billing"},
            prov=["prov:1"],
            evidence=["span:1"],
        ),
        MIRLRecord(
            id="prov:1",
            kind=RecordKind.PROV,
            ns="work",
            scope="thread",
            # This PROV describes the RAW source used by the evidence span.
            # Activity alone is metadata, not a canonical provenance link.
            attrs={"entity": "raw:1", "activity": "handwritten-test-fixture"},
        ),
    ]
    if include_span:
        attrs: dict[str, object] = {"start": start, "end": end}
        if span_raw_id is not None:
            attrs["raw_id"] = span_raw_id
        records.append(
            MIRLRecord(
                id="span:1", kind=RecordKind.SPAN, ns="work", scope="thread", attrs=attrs
            )
        )
    if include_raw:
        records.append(
            MIRLRecord(
                id="raw:1",
                kind=RecordKind.RAW,
                ns="work",
                scope="thread",
                attrs={"content": SOURCE, "media_type": "text/plain"},
            )
        )
    return IRBatch(records)


def _rewrite_canonical_payload(runtime: SeamRuntime, record: MIRLRecord) -> None:
    """Simulate post-write damage below the public persistence boundary."""

    payload = json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":"))
    with sqlite3.connect(runtime.store.path) as connection:
        cursor = connection.execute(
            "update ir_records set payload_json = ? where id = ?",
            (payload, record.id),
        )
        assert cursor.rowcount == 1


def _delete_canonical_payload(runtime: SeamRuntime, record_id: str) -> None:
    """Model a truncated restore while leaving the owning record untouched."""

    with sqlite3.connect(runtime.store.path) as connection:
        connection.execute("pragma foreign_keys = off")
        cursor = connection.execute(
            "delete from ir_records where id = ?",
            (record_id,),
        )
        assert cursor.rowcount == 1


def _claim(runtime: SeamRuntime) -> MIRLRecord:
    return next(r for r in runtime.store.load_ir().records if r.id == "clm:1")


def test_complete_chain_returns_the_exact_source_span(runtime: SeamRuntime) -> None:
    runtime.persist_ir(_chain_batch())
    chain = resolve_provenance(runtime.store, _claim(runtime))

    assert chain.complete is True
    assert chain.defect is None
    assert chain.prov_ids == ("prov:1",)
    (link,) = chain.links
    assert link.verified is True
    assert (link.span_id, link.raw_id, link.start, link.end) == ("span:1", "raw:1", 0, 11)
    # The whole point: the caller gets the source text, not just an id, sliced
    # at exactly the span offsets (note the trailing space - byte-exact, not
    # word-rounded).
    assert link.text == SOURCE[0:11] == "Priya owns "
    assert chain.source_text == (SOURCE[0:11],)


def test_raw_record_is_its_own_provenance(runtime: SeamRuntime) -> None:
    runtime.persist_ir(_chain_batch())
    raw = next(r for r in runtime.store.load_ir().records if r.id == "raw:1")
    chain = resolve_provenance(runtime.store, raw)

    assert chain.complete is True
    assert chain.source_text == (SOURCE,)


def test_record_without_evidence_reports_the_gap(runtime: SeamRuntime) -> None:
    # Entities are the live instance of this: they carry compile lineage in
    # `prov` but never declare which span mentioned them, so they cannot prove
    # their origin. The metric must surface that rather than scoring it 1.0.
    runtime.persist_ir(
        IRBatch(
            [
                MIRLRecord(
                    id="ent:priya",
                    kind=RecordKind.ENT,
                    ns="work",
                    scope="thread",
                    attrs={"label": "Priya", "entity_type": "person"},
                )
            ]
        )
    )
    entity = next(r for r in runtime.store.load_ir().records if r.id == "ent:priya")
    chain = resolve_provenance(runtime.store, entity)

    assert chain.complete is False
    assert chain.defect == DEFECT_NO_EVIDENCE
    assert chain.links == ()


@pytest.mark.parametrize(
    ("batch_kwargs", "expected_defect"),
    [
        ({"include_span": False}, DEFECT_SPAN_MISSING),
        ({"include_raw": False}, DEFECT_RAW_MISSING),
        ({"start": 0, "end": 9999}, DEFECT_OFFSETS_INVALID),
        ({"start": 8, "end": 3}, DEFECT_OFFSETS_INVALID),
    ],
)
def test_broken_hops_are_reported_not_dropped(
    runtime: SeamRuntime, batch_kwargs: dict, expected_defect: str
) -> None:
    runtime.persist_ir(_chain_batch())
    damaged = _chain_batch(**batch_kwargs)
    damaged_by_id = {record.id: record for record in damaged.records}
    if "span:1" not in damaged_by_id:
        _delete_canonical_payload(runtime, "span:1")
    elif "raw:1" not in damaged_by_id:
        _delete_canonical_payload(runtime, "raw:1")
    else:
        _rewrite_canonical_payload(runtime, damaged_by_id["span:1"])
    chain = resolve_provenance(runtime.store, _claim(runtime))

    assert chain.complete is False
    # The link SURVIVES in the result carrying its reason - it is not filtered
    # out, because a caller must be able to see that a citation failed.
    (link,) = chain.links
    assert link.verified is False
    assert link.defect == expected_defect
    assert link.text is None
    assert chain.source_text == ()


def test_span_without_raw_id_cannot_be_stored_at_all(runtime: SeamRuntime) -> None:
    """The public write path forbids an unanchored span before storage.

    ``verify_ir`` rejects the missing canonical hop before the SQLite transaction
    starts. The resolver still handles the defect defensively for corrupted or
    non-SQLite backends, but public persistence must fail closed with no partial
    canonical rows.
    """
    with pytest.raises(ValueError, match="missing_span_field"):
        runtime.persist_ir(_chain_batch(span_raw_id=None))
    assert runtime.store.load_ir().records == []


def test_referenced_record_of_wrong_kind_is_rejected(runtime: SeamRuntime) -> None:
    # Persist a valid chain, then model corruption that redirects evidence to a
    # canonical record of the wrong kind.
    runtime.persist_ir(_chain_batch())
    decoy = MIRLRecord(
        id="clm:decoy",
        kind=RecordKind.CLM,
        ns="work",
        scope="thread",
        attrs={
            "subject": "ent:priya",
            "predicate": "claims",
            "object": "decoy",
        },
    )
    runtime.persist_ir(IRBatch([decoy]))
    claim = _claim(runtime)
    claim.evidence = [decoy.id]
    _rewrite_canonical_payload(runtime, claim)
    chain = resolve_provenance(runtime.store, _claim(runtime))

    assert chain.complete is False
    assert chain.links[0].defect == DEFECT_SPAN_NOT_SPAN


def test_runtime_update_resolves_stored_provenance_and_evidence(
    runtime: SeamRuntime,
) -> None:
    runtime.persist_ir(_chain_batch())
    claim = _claim(runtime)
    changed = MIRLRecord.from_dict(claim.to_dict())
    changed.attrs["object"] = "updated with stored provenance"

    report = runtime.persist_ir(IRBatch([changed]))

    assert report.stored_ids == [changed.id]
    stored = runtime.store.load_ir(ids=[changed.id]).records[0]
    assert stored.attrs["object"] == "updated with stored provenance"
    assert stored.prov == claim.prov
    assert stored.evidence == claim.evidence


def test_partial_chain_does_not_count_as_complete(runtime: SeamRuntime) -> None:
    """One good link plus one broken link is NOT a trustworthy citation."""
    runtime.persist_ir(_chain_batch())
    claim = _claim(runtime)
    claim.evidence = ["span:1", "span:missing"]
    _rewrite_canonical_payload(runtime, claim)
    chain = resolve_provenance(runtime.store, _claim(runtime))

    assert [link.verified for link in chain.links] == [True, False]
    assert chain.complete is False


def test_chain_completeness_metric_counts_and_attributes(runtime: SeamRuntime) -> None:
    runtime.persist_ir(_chain_batch())
    good = resolve_provenance(runtime.store, _claim(runtime))
    bad = resolve_provenance_many(
        runtime.store,
        [
            MIRLRecord(
                id="ent:x", kind=RecordKind.ENT, ns="work", scope="thread", attrs={}
            )
        ],
    )["ent:x"]

    metric = chain_completeness([good, bad])
    assert metric["total"] == 2
    assert metric["complete"] == 1
    assert metric["completeness"] == 0.5
    assert metric["defects"] == {DEFECT_NO_EVIDENCE: 1}

    assert chain_completeness([])["completeness"] == 1.0


def test_retrieval_returns_the_chain_only_when_asked(runtime: SeamRuntime) -> None:
    runtime.persist_ir(_chain_batch())
    orchestrator = RetrievalOrchestrator(runtime)

    off = orchestrator.search("billing", scope="thread", budget=5)
    assert off.candidates, "fixture must retrieve something for this test to mean anything"
    assert all(candidate.provenance is None for candidate in off.candidates)

    on = orchestrator.search(
        "billing", scope="thread", budget=5, include_provenance=True
    )
    assert on.candidates, "provenance-enabled retrieval must return the fixture"
    assert all(candidate.provenance is not None for candidate in on.candidates)
    resolved = [c for c in on.candidates if c.record.id == "clm:1"]
    assert len(resolved) == 1
    assert resolved[0].provenance is not None
    assert resolved[0].provenance.complete is True


def test_resolving_provenance_does_not_change_ranking(runtime: SeamRuntime) -> None:
    """Observationally inert, same contract the retrieval trace holds to.

    If enabling provenance could reorder or rescore candidates, every A/B run
    that enabled it would be measuring two changes at once.
    """
    runtime.persist_ir(_chain_batch())
    orchestrator = RetrievalOrchestrator(runtime)

    off = orchestrator.search("billing", scope="thread", budget=10)
    on = orchestrator.search(
        "billing", scope="thread", budget=10, include_provenance=True
    )

    assert [c.record.id for c in off.candidates] == [c.record.id for c in on.candidates]
    assert [c.score for c in off.candidates] == [c.score for c in on.candidates]
