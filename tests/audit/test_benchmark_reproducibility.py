"""D1 — Benchmark reproducibility: prove BIL-2 result_hash is deterministic."""

import copy

import pytest

from benchmarks.external.common.dataset import load_quickstart_cases
from benchmarks.external.common.runner import run_benchmark
from benchmarks.external.locomo.run import build_adapter, build_judge
from seam_runtime.benchmark_integrity import seal_benchmark_bundle


def _non_deterministic_field_paths(a, b, prefix: str = "") -> list[str]:
    """Return dotted paths where two values differ (recursive into dicts and lists)."""
    paths: list[str] = []
    if isinstance(a, dict) and isinstance(b, dict):
        all_keys = sorted(set(a) | set(b))
        for key in all_keys:
            full = f"{prefix}.{key}" if prefix else key
            va = a.get(key)
            vb = b.get(key)
            paths.extend(_non_deterministic_field_paths(va, vb, full))
    elif isinstance(a, list) and isinstance(b, list):
        for i, (ea, eb) in enumerate(zip(a, b)):
            full = f"{prefix}[{i}]"
            paths.extend(_non_deterministic_field_paths(ea, eb, full))
        if len(a) != len(b):
            paths.append(f"{prefix}.length ({len(a)} vs {len(b)})")
    elif a != b:
        paths.append(prefix)
    return paths


def test_bil2_result_hash_deterministic():
    """Two identical quickstart runs with stub judge should produce the same
    BIL-2 result_hash and input_manifest_hash.

    If non-deterministic fields exist (timestamps, run_id, wall-clock),
    this test FAILS with a clear list of the non-deterministic field paths.
    """
    adapter_name = "seam"
    judge_name = "stub"

    cases = load_quickstart_cases()
    adapter_a = build_adapter(adapter_name)
    adapter_b = build_adapter(adapter_name)
    judge_a = build_judge(judge_name)
    judge_b = build_judge(judge_name)

    result_a = run_benchmark(
        adapter=adapter_a,
        cases=copy.deepcopy(cases),
        dataset_source="quickstart",
        judge=judge_a,
    )
    # Close adapter_a before adapter_b reuses the same default db path; otherwise
    # adapter_b.reset() cannot delete the per-case DBs adapter_a still holds open
    # (Windows WinError 32).
    adapter_a.close()
    result_b = run_benchmark(
        adapter=adapter_b,
        cases=copy.deepcopy(cases),
        dataset_source="quickstart",
        judge=judge_b,
    )
    adapter_b.close()

    bundle_a = seal_benchmark_bundle(result_a, level="BIL-2", allow_stub_seal=True)
    bundle_b = seal_benchmark_bundle(result_b, level="BIL-2", allow_stub_seal=True)

    rh_a = bundle_a["bil"]["result_hash"]
    rh_b = bundle_b["bil"]["result_hash"]
    imh_a = bundle_a["bil"]["input_manifest_hash"]
    imh_b = bundle_b["bil"]["input_manifest_hash"]

    # Input manifests should match (they exclude wall-clock fields).
    assert imh_a == imh_b, (
        f"input_manifest_hash mismatch: a={imh_a} b={imh_b}"
    )

    # Check result_hash determinism.
    if rh_a != rh_b:
        nd_paths = _non_deterministic_field_paths(result_a, result_b)
        pytest.fail(
            f"BIL-2 result_hash is non-deterministic.\n"
            f"result_hash_a: {rh_a}\n"
            f"result_hash_b: {rh_b}\n"
            f"Non-deterministic field paths: {nd_paths}\n"
            f"These fields must be redacted from the result before sealing "
            f"for the hash to be deterministic."
        )
