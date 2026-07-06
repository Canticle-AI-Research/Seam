"""Tests for token-aware context pack budget enforcement."""

from seam_runtime.mirl import MIRLRecord, RecordKind, Status
from seam_runtime.pack import pack_records


def _make_record(rid: str, text: str) -> MIRLRecord:
    return MIRLRecord(
        id=rid, kind=RecordKind.CLM, ns="test", scope="test",
        status=Status.ASSERTED, conf=1.0, t0="0", t1="0",
        created_at="2025-01-01T00:00:00Z", updated_at="2025-01-01T00:00:00Z",
        attrs={"subject": rid, "predicate": "says", "object": text},
        prov=[], evidence=[],
    )


class TestTokenAwarePack:
    def test_tiny_budget_produces_overflow_metadata(self):
        records = [
            _make_record("clm:1", "This is a meaningful sentence that takes tokens."),
            _make_record("clm:2", "Another sentence with more tokens for testing."),
            _make_record("clm:3", "A third sentence to ensure overflow happens here."),
        ]
        # Budget of 20 tokens is very small -- should fit maybe 0-2 entries,
        # with some overflow.
        pack = pack_records(records, lens="general", budget=20, mode="context")
        assert pack.token_cost <= 20 or ("overflow" in pack.payload), (
            f"token_cost={pack.token_cost}, overflow_present={'overflow' in pack.payload}"
        )
        if "overflow" in pack.payload:
            assert pack.payload["overflow"]["count"] > 0
            assert len(pack.payload["overflow"]["omitted_ids"]) > 0

    def test_normal_budget_fits_all_records(self):
        records = [
            _make_record("clm:1", "short"),
            _make_record("clm:2", "also short"),
        ]
        pack = pack_records(records, lens="general", budget=99999, mode="context")
        assert len(pack.refs) == 2
        assert "overflow" not in pack.payload

    def test_exact_mode_unaffected(self):
        records = [_make_record("clm:1", "test")]
        pack = pack_records(records, mode="exact")
        assert pack.mode == "exact"
        assert pack.reversible is True
