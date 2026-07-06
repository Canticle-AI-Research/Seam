from __future__ import annotations

import pytest

from seam_runtime.agent_memory import (
    IngestReport,
    compact_memory_index,
    full_memory_records,
    source_hash,
    stable_document_id,
)
from seam_runtime.mirl import MIRLRecord, RecordKind


def _make_record(id: str, kind: RecordKind = RecordKind.CLM, **attrs) -> MIRLRecord:
    return MIRLRecord.from_dict({
        "id": id,
        "kind": kind.value,
        "ns": "test.ns",
        "scope": "thread",
        "created_at": "2026-05-18T00:00:00Z",
        "updated_at": "2026-05-18T00:00:00Z",
        "t0": "2026-05-18T00:00:00Z",
        "source_ref": "test://input",
        "source_kind": "nl",
        "text": "test record",
        "attrs": attrs,
        "prov": [],
        "evidence": [],
    })


class TestSourceHash:
    def test_deterministic(self):
        assert source_hash("hello") == source_hash("hello")

    def test_different_inputs_differ(self):
        assert source_hash("hello") != source_hash("world")

    def test_output_is_hex_string(self):
        h = source_hash("hello")
        assert len(h) == 64
        int(h, 16)  # does not raise


class TestStableDocumentId:
    def test_deterministic(self):
        a = stable_document_id("ref", "text")
        b = stable_document_id("ref", "text")
        assert a == b

    def test_different_refs_differ(self):
        a = stable_document_id("ref1", "text")
        b = stable_document_id("ref2", "text")
        assert a != b


class TestCompactMemoryIndex:
    def test_includes_query_and_results(self):
        r = _make_record("id:1", kind=RecordKind.CLM, subject="S", predicate="P", object="O")
        payload = compact_memory_index([r], "test query")
        assert payload["query"] == "test query"
        assert len(payload["results"]) == 1
        assert payload["results"][0]["id"] == "id:1"
        assert "next" in payload

    def test_applies_scores_when_provided(self):
        r = _make_record("id:1")
        payload = compact_memory_index([r], "q", scores={"id:1": 0.75})
        assert payload["results"][0]["score"] == 0.75

    def test_empty_records(self):
        payload = compact_memory_index([], "q")
        assert payload["results"] == []


class TestFullMemoryRecords:
    def test_returns_records_list(self):
        r = _make_record("id:1")
        payload = full_memory_records([r])
        assert len(payload["records"]) == 1
        assert payload["records"][0]["id"] == "id:1"

    def test_empty_records(self):
        payload = full_memory_records([])
        assert payload["records"] == []


class TestIngestReport:
    def test_to_dict_roundtrip(self):
        report = IngestReport(document={"source_ref": "test"}, stored_ids=["a", "b"])
        d = report.to_dict()
        assert d["document"]["source_ref"] == "test"
        assert d["stored_ids"] == ["a", "b"]

    def test_frozen_dataclass(self):
        report = IngestReport(document={}, stored_ids=[])
        with pytest.raises(Exception):
            report.stored_ids = ["x"]
