from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_quickstart(*extra_args: str, output_path: str | None = None) -> subprocess.CompletedProcess:
    """Run `python -m benchmarks.external.locomo.run --quickstart`, optionally with --output."""
    cmd = [sys.executable, "-m", "benchmarks.external.locomo.run", "--quickstart"]
    cmd.extend(extra_args)
    if output_path is not None:
        cmd.extend(["--output", output_path])
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": ""}
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def _parse_stdout_json(result: subprocess.CompletedProcess) -> dict:
    """Parse stdout as JSON, failing the current test if parsing fails."""
    assert result.stdout, "stdout is empty"
    data = json.loads(result.stdout)
    assert isinstance(data, dict), f"expected JSON object, got {type(data).__name__}"
    return data


@pytest.fixture(scope="module")
def quickstart_run() -> tuple[subprocess.CompletedProcess, dict, float]:
    """Run the common full quickstart once for all read-only output assertions."""
    t0 = time.monotonic()
    result = _run_quickstart()
    elapsed = time.monotonic() - t0
    assert result.returncode == 0, (
        f"expected returncode 0, got {result.returncode}\n"
        f"stderr: {result.stderr}"
    )
    return result, _parse_stdout_json(result), elapsed


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_quickstart_cli_exits_zero(quickstart_run) -> None:
    """`--quickstart` exits with returncode 0 and emits valid JSON on stdout."""
    _, data, _ = quickstart_run
    assert data, "parsed JSON should be non-empty"


def test_quickstart_cli_output_has_integrity_hash(quickstart_run) -> None:
    """`--quickstart` output contains a 64-character hex integrity_hash."""
    _, data, _ = quickstart_run
    ih = data.get("integrity_hash")
    assert isinstance(ih, str), f"integrity_hash should be str, got {type(ih).__name__}"
    assert len(ih) == 64, f"expected 64-char hex, got {len(ih)} chars"
    # Verify it is a valid hex string.
    int(ih, 16)


def test_quickstart_cli_output_version(quickstart_run) -> None:
    """`--quickstart` output declares the expected version, benchmark, and adapter."""
    _, data, _ = quickstart_run

    assert data.get("version") == "SEAM-EXTERNAL-MEMORY-BENCHMARK-RESULT/1", (
        f"unexpected version: {data.get('version')!r}"
    )
    assert data.get("benchmark") == "locomo", (
        f"unexpected benchmark: {data.get('benchmark')!r}"
    )
    assert data.get("adapter") == "seam", (
        f"unexpected adapter: {data.get('adapter')!r}"
    )


def test_quickstart_cli_output_scores_populated(quickstart_run) -> None:
    """`--quickstart` output includes scores and a non-empty cases list."""
    _, data, _ = quickstart_run

    scores = data.get("scores")
    assert isinstance(scores, dict), f"scores should be dict, got {type(scores).__name__}"

    cr_mean = scores.get("context_recall_mean")
    assert isinstance(cr_mean, (int, float)), (
        f"context_recall_mean should be numeric, got {type(cr_mean).__name__}"
    )

    em_mean = scores.get("answer_em_mean")
    assert isinstance(em_mean, (int, float)), (
        f"answer_em_mean should be numeric, got {type(em_mean).__name__}"
    )

    cases = data.get("cases")
    assert isinstance(cases, list), f"cases should be list, got {type(cases).__name__}"
    assert len(cases) > 0, "cases list should be non-empty"


def test_integrity_hash_stable_across_runs(tmp_path, quickstart_run) -> None:
    """Running --quickstart twice produces the same integrity_hash."""
    out_b = str(tmp_path / "run_b.json")

    res_b = _run_quickstart(output_path=out_b)
    assert res_b.returncode == 0, f"run_b failed with returncode {res_b.returncode}\nstderr: {res_b.stderr}"

    _, data_a, _ = quickstart_run
    with open(out_b) as f:
        data_b = json.load(f)

    assert data_a["integrity_hash"] == data_b["integrity_hash"], (
        f"integrity_hash mismatch:\n  run_a: {data_a['integrity_hash']}\n  run_b: {data_b['integrity_hash']}"
    )


def test_save_context_cli_includes_retrieved_context_without_changing_integrity_hash(tmp_path) -> None:
    out_default = str(tmp_path / "default.json")
    out_context = str(tmp_path / "context.json")

    res_default = _run_quickstart("--limit", "1", output_path=out_default)
    assert res_default.returncode == 0, (
        f"default run failed with returncode {res_default.returncode}\nstderr: {res_default.stderr}"
    )
    res_context = _run_quickstart("--limit", "1", "--save-context", output_path=out_context)
    assert res_context.returncode == 0, (
        f"context run failed with returncode {res_context.returncode}\nstderr: {res_context.stderr}"
    )

    with open(out_default) as f:
        data_default = json.load(f)
    with open(out_context) as f:
        data_context = json.load(f)

    assert "retrieved_context" not in data_default["cases"][0]
    assert data_context["cases"][0]["retrieved_context"]
    assert data_context["integrity_hash"] == data_default["integrity_hash"]


def test_quickstart_completes_under_180_seconds(quickstart_run) -> None:
    """`--quickstart` completes in under 180 seconds."""
    _, _, elapsed = quickstart_run
    assert elapsed < 180, (
        f"expected elapsed < 180 s, got {elapsed:.2f} s"
    )
