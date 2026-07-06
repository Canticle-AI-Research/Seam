"""Tests for benchmark bundle tamper-evidence (B3) and the publish gate (B2).

B3: `verify_benchmark_bundle` was self-referential — it recomputed a hash and
compared it to the hash stored in the same bundle, so a deliberate edit that
recomputed the hash went undetected. An optional HMAC signature over the BIL
block makes the bundle tamper-evident for anyone without the signing key.

B2: `validate_publication_readiness` (the non-stub-judge + BIL-2 gate) was dead
code wired into no command. It is now reachable via `seam bench publish`.
"""
from __future__ import annotations

import copy

from seam_runtime.benchmark_integrity import (
    result_hash,
    seal_benchmark_bundle,
    sign_benchmark_bundle,
    validate_publication_readiness,
    verify_benchmark_bundle,
)

KEY = b"operator-secret-key"


def _real_result() -> dict:
    return {
        "version": "SEAM-EXTERNAL-MEMORY-BENCHMARK-RESULT/1",
        "benchmark": "locomo",
        "adapter": "seam",
        "dataset": {"name": "locomo10", "fixture_hash": "abc123"},
        "cases": [
            {
                "case_id": "c1",
                "category": "single-hop",
                "judge": {"judge_name": "claude", "judge_model": "claude-x"},
            }
        ],
        "per_category": {"single-hop": 0.4},
    }


class TestSignedTamperEvidence:
    def test_signed_bundle_verifies_with_key(self):
        bundle = seal_benchmark_bundle(_real_result(), level="BIL-2", signing_key=KEY)
        report = verify_benchmark_bundle(bundle, signing_key=KEY)
        assert report["status"] == "PASS"
        assert report["bil"]["signed"] is True
        assert any(c["id"] == "signature" and c["status"] == "PASS" for c in report["checks"])

    def test_edited_result_with_recomputed_hash_still_fails(self):
        """The core B3 fix: recomputing result_hash is not enough without the key."""
        bundle = seal_benchmark_bundle(_real_result(), level="BIL-2", signing_key=KEY)
        tampered = copy.deepcopy(bundle)
        tampered["result"]["per_category"]["single-hop"] = 0.99
        tampered["bil"]["result_hash"] = result_hash(tampered["result"])  # attacker fixes SHA
        report = verify_benchmark_bundle(tampered, signing_key=KEY)
        assert report["status"] == "FAIL"
        assert any(c["id"] == "signature" and c["status"] == "FAIL" for c in report["checks"])

    def test_wrong_key_fails(self):
        bundle = seal_benchmark_bundle(_real_result(), level="BIL-2", signing_key=KEY)
        report = verify_benchmark_bundle(bundle, signing_key=b"different-key")
        assert report["status"] == "FAIL"

    def test_signed_bundle_without_key_warns_not_fails(self):
        bundle = seal_benchmark_bundle(_real_result(), level="BIL-2", signing_key=KEY)
        report = verify_benchmark_bundle(bundle)  # no key available
        assert report["status"] == "PASS"  # WARN is non-fatal
        assert any(c["id"] == "signature" and c["status"] == "WARN" for c in report["checks"])

    def test_unsigned_bundle_backward_compatible(self):
        """Unsigned bundles verify exactly as before; signed flag is explicit."""
        bundle = seal_benchmark_bundle(_real_result(), level="BIL-2")
        report = verify_benchmark_bundle(bundle)
        assert report["status"] == "PASS"
        assert report["bil"]["signed"] is False
        assert not any(c["id"] == "signature" for c in report["checks"])

    def test_sign_after_seal_is_equivalent(self):
        unsigned = seal_benchmark_bundle(_real_result(), level="BIL-2")
        signed = sign_benchmark_bundle(unsigned, KEY)
        assert verify_benchmark_bundle(signed, signing_key=KEY)["status"] == "PASS"


class TestPublicationGate:
    def test_stub_judge_is_blocked(self):
        result = _real_result()
        result["cases"][0]["judge"] = {"judge_name": "stub"}
        bundle = seal_benchmark_bundle(result, level="BIL-2", allow_stub_seal=True)
        readiness = validate_publication_readiness(
            result,
            git_sha="deadbeef",
            fixture_hash="abc123",
            dataset_name="locomo10",
            bil_verification=verify_benchmark_bundle(bundle),
        )
        assert readiness["ready"] is False
        assert "judge_non_stub" in readiness["publication_blocked_by"]

    def test_real_judge_is_ready(self):
        result = _real_result()
        bundle = seal_benchmark_bundle(result, level="BIL-2")
        readiness = validate_publication_readiness(
            result,
            git_sha="deadbeef",
            fixture_hash="abc123",
            dataset_name="locomo10",
            bil_verification=verify_benchmark_bundle(bundle),
        )
        assert readiness["ready"] is True

    def test_missing_git_sha_blocks(self):
        result = _real_result()
        bundle = seal_benchmark_bundle(result, level="BIL-2")
        readiness = validate_publication_readiness(
            result,
            git_sha="",
            fixture_hash="abc123",
            dataset_name="locomo10",
            bil_verification=verify_benchmark_bundle(bundle),
        )
        assert readiness["ready"] is False
        assert "git_sha_present" in readiness["publication_blocked_by"]


class TestPublishCLI:
    def test_publish_command_blocks_stub(self, tmp_path):
        import json
        import subprocess
        import sys

        result = _real_result()
        result["cases"][0]["judge"] = {"judge_name": "stub"}
        result_path = tmp_path / "result.json"
        result_path.write_text(json.dumps(result), encoding="utf-8")

        proc = subprocess.run(
            [sys.executable, "-m", "seam", "bench", "publish", str(result_path), "--format", "json"],
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 1, proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["readiness"]["ready"] is False
