"""D2 — Stub-judge BIL refusal gate."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from seam_runtime.benchmark_integrity import seal_benchmark_bundle


def _stub_result():
    return {
        "version": "SEAM-EXTERNAL-MEMORY-BENCHMARK-RESULT/1",
        "benchmark": "locomo",
        "adapter": "seam",
        "dataset": {"source": "quickstart", "case_count": 1},
        "scores": {"context_recall_mean": 1.0},
        "cases": [
            {
                "case_id": "conv-1::q0",
                "category": "memory",
                "scores": {"context_recall": 1.0, "answer_em": 1.0, "answer_f1": 1.0},
                "retrieval_latency_ms": 5.0,
                "answer_latency_ms": 10.0,
                "judge": {
                    "verdict": "correct",
                    "score": 1.0,
                    "rationale": "stub always returns correct",
                    "judge_name": "stub",
                    "judge_model": "stub-1",
                },
            }
        ],
    }


def _non_stub_result():
    return {
        "version": "SEAM-EXTERNAL-MEMORY-BENCHMARK-RESULT/1",
        "benchmark": "locomo",
        "adapter": "seam",
        "dataset": {"source": "quickstart", "case_count": 1},
        "scores": {"context_recall_mean": 1.0},
        "cases": [
            {
                "case_id": "conv-1::q0",
                "category": "memory",
                "scores": {"context_recall": 1.0, "answer_em": 1.0, "answer_f1": 1.0},
                "retrieval_latency_ms": 5.0,
                "answer_latency_ms": 10.0,
                "judge": {
                    "verdict": "correct",
                    "score": 1.0,
                    "rationale": "provider judge accepted the answer",
                    "judge_name": "openai",
                    "judge_model": "gpt-5-mini",
                },
            }
        ],
    }


def test_stub_bil2_refuses():
    """Stub result + BIL-2 + default refuses with ValueError."""
    with pytest.raises(ValueError, match="stub judge cannot be sealed above BIL-0"):
        seal_benchmark_bundle(_stub_result(), level="BIL-2")


def test_stub_bil2_allow_stub_seal_succeeds():
    """Stub result + BIL-2 + allow_stub_seal=True succeeds."""
    bundle = seal_benchmark_bundle(_stub_result(), level="BIL-2", allow_stub_seal=True)
    assert bundle["bil"]["level"] == "BIL-2"
    assert bundle["bil"]["result_hash"] is not None


def test_non_stub_bil2_succeeds():
    """Non-stub result + BIL-2 + default succeeds."""
    bundle = seal_benchmark_bundle(_non_stub_result(), level="BIL-2")
    assert bundle["bil"]["level"] == "BIL-2"


def test_cli_stub_seal_refuses_and_allows():
    """CLI smoke: seal with stub result exits non-zero; --allow-stub-seal exits zero."""
    with tempfile.TemporaryDirectory(prefix="seam-d2-cli-") as tmp:
        result_path = Path(tmp) / "stub_result.json"
        result_path.write_text(json.dumps(_stub_result()))
        bundle_path = Path(tmp) / "bundle.json"

        # Without --allow-stub-seal, should exit non-zero.
        proc = subprocess.run(
            [sys.executable, "seam.py", "bench", "seal",
             str(result_path), "--level", "BIL-2", "--output", str(bundle_path)],
            capture_output=True, text=True,
        )
        assert proc.returncode != 0, f"expected non-zero exit, got {proc.returncode}\nstderr: {proc.stderr}"
        assert "stub judge cannot be sealed above BIL-0" in proc.stderr
        assert "Traceback" not in proc.stderr

        # With --allow-stub-seal, should exit zero.
        proc2 = subprocess.run(
            [sys.executable, "seam.py", "bench", "seal",
             str(result_path), "--level", "BIL-2", "--output", str(bundle_path),
             "--allow-stub-seal"],
            capture_output=True, text=True,
        )
        assert proc2.returncode == 0, f"expected zero exit, got {proc2.returncode}\nstderr: {proc2.stderr}"
