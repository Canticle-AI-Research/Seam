"""Tests for Track M publication gate — stub-judge refusal and required metadata."""


def _make_stub_result():
    return {
        "version": "SEAM-EXTERNAL-MEMORY-BENCHMARK-RESULT/1",
        "benchmark": "locomo",
        "adapter": "seam",
        "dataset": {"source": "quickstart", "case_count": 10},
        "run_started_at": "2026-05-20T00:00:00Z",
        "elapsed_seconds": 2.5,
        "scores": {
            "context_recall_mean": 0.65,
            "answer_em_mean": 0.12,
            "answer_f1_mean": 0.34,
        },
        "cases": [
            {
                "case_id": "conv-1::q0",
                "category": "1",
                "scores": {"context_recall": 0.7, "answer_em": 0.0, "answer_f1": 0.3},
                "judge": {"verdict": "correct", "score": 1.0, "rationale": "stub", "judge_name": "stub", "judge_model": "stub-1"},
            },
            {
                "case_id": "conv-1::q1",
                "category": "1",
                "scores": {"context_recall": 0.6, "answer_em": 0.0, "answer_f1": 0.25},
                "judge": {"verdict": "correct", "score": 1.0, "rationale": "stub", "judge_name": "stub", "judge_model": "stub-1"},
            },
        ],
        "integrity_hash": "abc123",
    }


def _make_real_judge_result():
    result = _make_stub_result()
    for case in result["cases"]:
        case["judge"] = {
            "verdict": "correct", "score": 1.0, "rationale": "matches",
            "judge_name": "claude", "judge_model": "claude-haiku-4-5-20251001",
        }
    return result


def _bil2_pass():
    return {
        "status": "PASS",
        "bil": {"level": "BIL-2"},
        "bundle": {"hash": "bundle-hash-123"},
    }


class TestTrackMPublicationGate:
    def test_stub_judge_refused_for_publication(self):
        from seam_runtime.benchmark_integrity import validate_publication_readiness

        result = _make_stub_result()
        report = validate_publication_readiness(
            result,
            git_sha="abc123def456",
            fixture_hash="fixture-hash-123",
            dataset_name="locomo-quickstart",
        )
        assert report["ready"] is False
        assert "judge_non_stub" in report["publication_blocked_by"]

    def test_real_judge_passes_publication_gate_with_all_metadata(self):
        from seam_runtime.benchmark_integrity import validate_publication_readiness

        result = _make_real_judge_result()
        report = validate_publication_readiness(
            result,
            git_sha="abc123def456",
            fixture_hash="fixture-hash-123",
            dataset_name="locomo-quickstart",
            bil_verification=_bil2_pass(),
        )
        assert report["ready"] is True
        assert report["summary"]["failed"] == 0

    def test_missing_git_sha_blocked(self):
        from seam_runtime.benchmark_integrity import validate_publication_readiness

        result = _make_real_judge_result()
        report = validate_publication_readiness(
            result,
            git_sha="",
            fixture_hash="fixture-hash-123",
            dataset_name="locomo-quickstart",
            bil_verification=_bil2_pass(),
        )
        assert report["ready"] is False
        assert "git_sha_present" in report["publication_blocked_by"]

    def test_missing_fixture_hash_blocked(self):
        from seam_runtime.benchmark_integrity import validate_publication_readiness

        result = _make_real_judge_result()
        report = validate_publication_readiness(
            result,
            git_sha="abc123",
            fixture_hash="",
            dataset_name="locomo-quickstart",
            bil_verification=_bil2_pass(),
        )
        assert report["ready"] is False
        assert "fixture_hash_present" in report["publication_blocked_by"]

    def test_missing_dataset_name_blocked(self):
        from seam_runtime.benchmark_integrity import validate_publication_readiness

        result = _make_real_judge_result()
        report = validate_publication_readiness(
            result,
            git_sha="abc123",
            fixture_hash="hash123",
            dataset_name="",
            bil_verification=_bil2_pass(),
        )
        assert report["ready"] is False
        assert "dataset_named" in report["publication_blocked_by"]

    def test_missing_adapter_name_blocked(self):
        from seam_runtime.benchmark_integrity import validate_publication_readiness

        result = _make_real_judge_result()
        result.pop("adapter", None)
        report = validate_publication_readiness(
            result,
            git_sha="abc123",
            fixture_hash="hash123",
            dataset_name="locomo",
            bil_verification=_bil2_pass(),
        )
        assert report["ready"] is False
        assert "adapter_named" in report["publication_blocked_by"]

    def test_no_judge_at_all_blocked(self):
        from seam_runtime.benchmark_integrity import validate_publication_readiness

        result = _make_stub_result()
        for case in result["cases"]:
            case.pop("judge", None)
        report = validate_publication_readiness(
            result,
            git_sha="abc123",
            fixture_hash="hash123",
            dataset_name="locomo",
            bil_verification=_bil2_pass(),
        )
        assert report["ready"] is False
        assert "judge_present" in report["publication_blocked_by"]

    def test_bil2_verification_required_for_publication(self):
        from seam_runtime.benchmark_integrity import validate_publication_readiness

        result = _make_real_judge_result()
        report = validate_publication_readiness(
            result,
            git_sha="abc123",
            fixture_hash="hash123",
            dataset_name="locomo",
        )
        assert report["ready"] is False
        assert "bil2_verified" in report["publication_blocked_by"]

    def test_bil1_verification_blocked(self):
        from seam_runtime.benchmark_integrity import validate_publication_readiness

        result = _make_real_judge_result()
        report = validate_publication_readiness(
            result,
            git_sha="abc123",
            fixture_hash="hash123",
            dataset_name="locomo",
            bil_verification={"status": "PASS", "bil": {"level": "BIL-1"}},
        )
        assert report["ready"] is False
        assert "bil2_verified" in report["publication_blocked_by"]

    def test_publication_gate_output_schema(self):
        from seam_runtime.benchmark_integrity import validate_publication_readiness

        result = _make_real_judge_result()
        report = validate_publication_readiness(
            result,
            git_sha="abc123",
            fixture_hash="hash123",
            dataset_name="locomo",
            bil_verification=_bil2_pass(),
        )
        assert report["version"] == "SEAM-PUBLICATION-READINESS/1"
        assert isinstance(report["ready"], bool)
        assert isinstance(report["checks"], list)
        assert "summary" in report
        assert "publication_blocked_by" in report
