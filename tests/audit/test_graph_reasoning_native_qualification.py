from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from benchmarks.graph_reasoning_qualification import (
    _bounded_raw_closure,
    run_provider_free_native_qualification,
)
from seam_runtime import SeamSDK


def test_real_native_qualification_reaches_paid_boundary_provider_free() -> None:
    report = run_provider_free_native_qualification()
    qualification = report["qualification"]

    assert report["provider_calls"] == 0
    assert qualification["paid_provider_calls"] == 0
    assert qualification["publication_claims_allowed"] is False
    assert qualification["lanes"]["native_seam"]["status"] == "PASS"
    assert report["comparison_budget"] == {
        "context_token_budget": 2_000,
        "event_only_kinds": ("episode",),
        "fact_reserve_tokens": 0,
        "matched": True,
        "result_record_budget": 2,
    }
    # Under matched context and result budgets, this structural fixture proves
    # parity and isolation, not an incremental usefulness win.
    assert qualification["lanes"]["event_only"]["usefulness"] == 1.0
    assert qualification["lanes"]["native_seam"]["usefulness"] == 1.0
    assert qualification["attribution"]["usefulness_delta"] == 0.0
    assert qualification["attribution"]["graph_incremental_hit_count"] == 0
    assert report["concurrency_recovery"]["requested"] == 3
    assert report["concurrency_recovery"]["completed"] == 3
    assert report["concurrency_recovery"]["recovered"] == 1
    assert report["concurrency_recovery"]["failed"] == 0
    plans = {
        lane["lane"]: lane for lane in report["manifest"]["lanes"]
    }
    assert plans["matched_mem0"]["status"] == "NOT_RUN"
    assert plans["matched_zep"]["status"] == "BLOCKED"
    assert plans["matched_mem0"]["provider_calls"] == 0
    assert plans["matched_zep"]["provider_calls"] == 0


def test_locomo_paid_capable_direct_run_fails_before_provider_use() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmarks.external.locomo.run",
            "--quickstart",
            "--adapter",
            "mem0",
            "--judge",
            "stub",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "--allow-paid" in completed.stderr
    assert "no paid calls were made" in completed.stderr


def test_locomo_provider_decomposer_fails_before_provider_use() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmarks.external.locomo.run",
            "--quickstart",
            "--adapter",
            "seam",
            "--judge",
            "stub",
            "--decomposer",
            "openai",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 2
    assert "--allow-paid" in completed.stderr
    assert "no paid calls were made" in completed.stderr


def test_result_budget_preserves_retrieval_rank_order(tmp_path: Path) -> None:
    with SeamSDK(
        tmp_path / "rank-order.db", allow_pgvector_env=False
    ) as sdk:
        raw_ids = []
        for index in range(3):
            report = sdk.ingest(
                f"Ranked fact {index}.",
                source_ref=f"local://rank-order/{index}",
                ns="qualification.rank",
                scope="thread",
            )
            raw_ids.append(
                next(
                    record_id
                    for record_id in report.stored_ids
                    if record_id.startswith("raw:")
                )
            )
        ranked = tuple(reversed(raw_ids))

        bounded = _bounded_raw_closure(sdk, ranked)

    assert bounded == ranked[:2]
