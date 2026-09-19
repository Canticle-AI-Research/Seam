"""Regression tests: an interrupted LoCoMo run must be resumable.

Checkpoints were already written durably (see test_locomo_result_durability),
but nothing could read one back, so an interrupted run had to redo every
completed case. That is affordable when a run is billed in cents and fatal
when it is billed against a subscription's rolling rate limit: a full dev
baseline is ~2,396 CLI calls and will cross a limit window mid-run.

These tests lock in: (1) checkpoints identify the case set they came from,
(2) resume refuses a checkpoint from a different case set rather than
silently merging incompatible results, and (3) resume reports exactly which
cases are already done so the runner can skip them.
"""
from __future__ import annotations

import json

import pytest

from benchmarks.external.locomo import run as locomo_run


def _partial(fixture_hash: str, case_ids: list[str], *, total: int = 10) -> dict:
    return {
        "status": "PARTIAL",
        "completed": len(case_ids),
        "total": total,
        "fixture_hash": fixture_hash,
        "case_results": [
            {"case_id": cid, "answer": f"a-{cid}", "judge": {"verdict": "correct"}}
            for cid in case_ids
        ],
    }


class TestCheckpointIdentifiesItsCaseSet:
    def test_checkpoint_payload_records_fixture_hash(self, tmp_path, monkeypatch):
        """A checkpoint without a fixture hash cannot be safely resumed."""
        monkeypatch.setenv("SEAM_BENCH_ARCHIVE_DIR", str(tmp_path))
        payload = locomo_run._checkpoint_payload(
            case_results=[{"case_id": "c1"}],
            completed=1,
            total=4,
            fixture_hash="abc123",
            embedding_preflight=None,
            embedding_preflight_sha256=None,
        )
        assert payload["fixture_hash"] == "abc123"
        assert payload["status"] == "PARTIAL"
        assert payload["completed"] == 1
        assert payload["total"] == 4


class TestResumeRefusesIncompatibleCheckpoints:
    def test_mismatched_fixture_hash_is_rejected(self, tmp_path):
        """Resuming across a different split would fabricate a blended result."""
        path = tmp_path / "run.partial.json"
        path.write_text(json.dumps(_partial("HASH-A", ["c1", "c2"])), encoding="utf-8")
        with pytest.raises(locomo_run.ResumeMismatch):
            locomo_run._resume_state(path, expected_fixture_hash="HASH-B")

    def test_checkpoint_without_fixture_hash_is_rejected(self, tmp_path):
        """Legacy checkpoints predate the identity field and cannot be trusted."""
        legacy = _partial("ignored", ["c1"])
        del legacy["fixture_hash"]
        path = tmp_path / "legacy.partial.json"
        path.write_text(json.dumps(legacy), encoding="utf-8")
        with pytest.raises(locomo_run.ResumeMismatch):
            locomo_run._resume_state(path, expected_fixture_hash="HASH-A")

    def test_missing_file_is_rejected(self, tmp_path):
        with pytest.raises(locomo_run.ResumeMismatch):
            locomo_run._resume_state(tmp_path / "nope.json", expected_fixture_hash="H")

    def test_malformed_json_is_rejected(self, tmp_path):
        path = tmp_path / "bad.partial.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(locomo_run.ResumeMismatch):
            locomo_run._resume_state(path, expected_fixture_hash="H")


class TestResumeReportsCompletedWork:
    def test_returns_completed_ids_and_prior_results(self, tmp_path):
        path = tmp_path / "run.partial.json"
        path.write_text(
            json.dumps(_partial("HASH-A", ["c1", "c2", "c3"])), encoding="utf-8"
        )
        completed, prior = locomo_run._resume_state(path, expected_fixture_hash="HASH-A")
        assert completed == {"c1", "c2", "c3"}
        assert [r["case_id"] for r in prior] == ["c1", "c2", "c3"]

    def test_results_without_case_id_are_not_counted_done(self, tmp_path):
        """A malformed entry must not mask an uncompleted case."""
        payload = _partial("HASH-A", ["c1"])
        payload["case_results"].append({"answer": "orphan"})
        path = tmp_path / "run.partial.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        completed, prior = locomo_run._resume_state(path, expected_fixture_hash="HASH-A")
        assert completed == {"c1"}
        assert len(prior) == 1

    def test_empty_checkpoint_resumes_from_zero(self, tmp_path):
        path = tmp_path / "run.partial.json"
        path.write_text(json.dumps(_partial("HASH-A", [])), encoding="utf-8")
        completed, prior = locomo_run._resume_state(path, expected_fixture_hash="HASH-A")
        assert completed == set()
        assert prior == []


class TestResumeCliIsDeliberatelyNotWiredYet:
    """--resume is withheld until the runner can carry prior results forward.

    Skipping completed cases without seeding them back into the report would
    emit a result missing those cases and aggregate scores computed over the
    remainder only. The seed belongs in common/runner.py (pre-populate
    case_results by index, skip seeded cases), not in a filter here. Until that
    lands, the flag must not exist rather than exist and mislead.
    """

    def test_resume_flag_is_not_exposed(self):
        parser = locomo_run._build_parser()
        args = parser.parse_args(["--dataset-path", "d.json"])
        assert not hasattr(args, "resume")
