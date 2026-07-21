from __future__ import annotations

from unittest.mock import patch

import pytest

from benchmarks.external.mem0_harness.upstream_runner import (
    PINNED_HARNESS_REVISION,
    UpstreamHarnessPlan,
    build_upstream_command,
    execute_upstream_plan,
)


def test_longmemeval_command_uses_full_official_contract():
    command = build_upstream_command(
        benchmark="longmemeval",
        python="/harness/.venv/bin/python",
        project_name="seam-lme",
        mem0_host="http://127.0.0.1:8900",
        predict_only=True,
        top_k=200,
        top_k_cutoffs="10,20,50,200",
        workers=1,
        output_dir="/tmp/lme",
        answerer_model="gpt-4o",
        judge_model="gpt-4o",
        provider="openai",
        dataset_path="/data/longmemeval_s_cleaned.json",
    )

    assert command[1:3] == ("-m", "benchmarks.longmemeval.run")
    assert "--all-questions" in command
    assert "--predict-only" in command
    assert command[command.index("--dataset-path") + 1].endswith(
        "longmemeval_s_cleaned.json"
    )


def test_beam_command_maps_one_million_track_and_full_range():
    command = build_upstream_command(
        benchmark="beam",
        python="/harness/.venv/bin/python",
        project_name="seam-beam",
        mem0_host="http://localhost:8900",
        predict_only=True,
        top_k=200,
        top_k_cutoffs="50,200",
        workers=1,
        output_dir="/tmp/beam",
        answerer_model="gpt-4o",
        judge_model="gpt-4o",
        provider="openai",
        dataset_cache_dir="/data/beam",
        chat_size="1m",
        conversations="0-34",
    )

    assert command[1:3] == ("-m", "benchmarks.beam.run")
    assert command[command.index("--chat-sizes") + 1] == "1M"
    assert command[command.index("--conversations") + 1] == "0-34"


def test_upstream_host_must_be_explicit_loopback():
    with pytest.raises(ValueError, match="loopback"):
        build_upstream_command(
            benchmark="beam",
            python="python",
            project_name="unsafe",
            mem0_host="https://example.com:443",
            predict_only=True,
            top_k=200,
            top_k_cutoffs="50,200",
            workers=1,
            output_dir="/tmp/beam",
            answerer_model="gpt-4o",
            judge_model="gpt-4o",
            provider="openai",
            chat_size="1m",
        )


def _ready_plan(*, paid: bool, size: str = "1M") -> UpstreamHarnessPlan:
    return UpstreamHarnessPlan(
        benchmark="beam",
        harness_root="/tmp",
        harness_revision=PINNED_HARNESS_REVISION,
        python="python",
        command=(
            "python",
            "-m",
            "benchmarks.beam.run",
            "--chat-sizes",
            size,
        ),
        ready=True,
        issues=(),
        paid=paid,
    )


def test_paid_execution_requires_explicit_gate():
    with pytest.raises(RuntimeError, match="provider-paid"):
        execute_upstream_plan(_ready_plan(paid=True), allow_paid=False)


def test_beam_10m_requires_separate_gate_before_process_launch():
    with pytest.raises(RuntimeError, match="BEAM-10M"):
        execute_upstream_plan(
            _ready_plan(paid=False, size="10M"),
            allow_paid=False,
            allow_beam_10m=False,
        )


def test_missing_beam_cache_requires_download_gate_before_process_launch():
    plan = UpstreamHarnessPlan(
        **{
            **_ready_plan(paid=False).__dict__,
            "requires_download": True,
        }
    )
    with pytest.raises(RuntimeError, match="allow-download"):
        execute_upstream_plan(plan, allow_paid=False, allow_download=False)


def test_cutoffs_must_fit_within_retrieval_top_k():
    with pytest.raises(ValueError, match="no greater than top_k"):
        build_upstream_command(
            benchmark="beam",
            python="python",
            project_name="bad-cutoff",
            mem0_host="http://127.0.0.1:8900",
            predict_only=True,
            top_k=50,
            top_k_cutoffs="50,200",
            workers=1,
            output_dir="/tmp/beam",
            answerer_model="gpt-4o",
            judge_model="gpt-4o",
            provider="openai",
            chat_size="1m",
        )


@pytest.mark.parametrize(
    ("target", "extra_args"),
    [
        (
            "longmemeval",
            ["--dataset-path", "/missing/longmemeval.json", "--per-type", "1"],
        ),
        ("beam", ["--track", "1m", "--conversations", "0"]),
    ],
)
def test_seam_cli_forwards_target_plan_without_execution(target, extra_args):
    from seam_runtime.cli import run_cli

    with patch("seam_runtime.cli.subprocess.run") as run:
        run.return_value.returncode = 1
        with pytest.raises(SystemExit, match="1"):
            run_cli(
                [
                    "bench",
                    "external",
                    target,
                    "--harness-root",
                    "/tmp/memory-benchmarks",
                    "--project-name",
                    f"seam-{target}-readiness",
                    "--predict-only",
                    "--plan",
                    *extra_args,
                ]
            )

    command = run.call_args.args[0]
    assert "--plan" in command
    assert "--predict-only" in command
