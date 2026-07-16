from __future__ import annotations

import copy
import json
import shlex
import subprocess
import sys

import pytest

from seam_runtime.external_memory_benchmarks import (
    benchmark_plan,
    load_memory_benchmark_registry,
    render_external_memory_plan_pretty,
    render_external_memory_report_pretty,
    run_external_memory_benchmarks,
    validate_memory_benchmark_registry,
)

# ---------------------------------------------------------------------------
# Existing tests (preserved)
# ---------------------------------------------------------------------------

def test_memory_benchmark_registry_contains_required_targets() -> None:
    registry = load_memory_benchmark_registry()
    required = set(registry["required_benchmark_ids"])
    assert {
        "locomo",
        "convomem",
        "membench",
        "longmemeval",
        "beam",
        "perltqa",
        "evermembench",
        "memora",
        "mem2actbench",
    }.issubset(required)
    comparator_ids = {item["id"] for item in registry["comparators"]}
    assert {"mem0", "zep_graphiti", "letta_memgpt", "mempalace", "hindsight", "memmachine"}.issubset(comparator_ids)


def test_external_memory_plan_marks_missing_required_commands() -> None:
    plan = benchmark_plan(scope="required")
    assert plan["summary"]["benchmark_count"] == len(plan["required_benchmark_ids"])
    assert plan["summary"]["missing_required_commands"]


def test_external_memory_runner_can_execute_configured_single_benchmark(monkeypatch) -> None:
    command = f'{shlex.quote(sys.executable)} -c "import sys; sys.exit(0)"'
    monkeypatch.setenv("SEAM_BENCH_LOCOMO_COMMAND", command)
    report = run_external_memory_benchmarks(scope="locomo", strict=True)
    assert report["status"] == "PASS"
    assert report["cases"][0]["status"] == "PASS"


def test_external_memory_runner_strict_mode_fails_on_unconfigured_required(monkeypatch) -> None:
    monkeypatch.delenv("SEAM_BENCH_LOCOMO_COMMAND", raising=False)
    report = run_external_memory_benchmarks(scope="locomo", strict=True)
    assert report["status"] == "FAIL"
    assert report["cases"][0]["status"] == "NOT_CONFIGURED"


# ---------------------------------------------------------------------------
# New tests — registry validation
# ---------------------------------------------------------------------------

def test_registry_rejects_duplicate_benchmark_ids() -> None:
    """validate_memory_benchmark_registry raises ValueError on duplicate benchmark ids."""
    registry = load_memory_benchmark_registry()
    bad_registry = copy.deepcopy(registry)
    # Append a copy of the first benchmark to create a duplicate id
    bad_registry["benchmarks"].append(dict(bad_registry["benchmarks"][0]))
    with pytest.raises(ValueError, match="duplicate benchmark ids"):
        validate_memory_benchmark_registry(bad_registry)


def test_registry_rejects_missing_command_env() -> None:
    """validate_memory_benchmark_registry raises ValueError when a benchmark is missing command_env."""
    registry = load_memory_benchmark_registry()
    bad_registry = copy.deepcopy(registry)
    # Delete the command_env key from the first benchmark
    del bad_registry["benchmarks"][0]["command_env"]
    with pytest.raises(ValueError, match="missing command_env"):
        validate_memory_benchmark_registry(bad_registry)


# ---------------------------------------------------------------------------
# New tests — benchmark plan scoping
# ---------------------------------------------------------------------------

def test_benchmark_plan_scope_required() -> None:
    """benchmark_plan(scope='required') returns only benchmarks with required: true."""
    plan = benchmark_plan(scope="required")
    assert len(plan["benchmarks"]) > 0, "expected at least one required benchmark"
    for benchmark in plan["benchmarks"]:
        assert benchmark["required"], (
            f"benchmark {benchmark['id']!r} should have required=True in scope='required' plan"
        )


def test_benchmark_plan_scope_all() -> None:
    """benchmark_plan(scope='all') returns more benchmarks than scope='required'."""
    plan_all = benchmark_plan(scope="all")
    plan_required = benchmark_plan(scope="required")
    assert plan_all["summary"]["benchmark_count"] > plan_required["summary"]["benchmark_count"], (
        f"all scope ({plan_all['summary']['benchmark_count']}) should exceed "
        f"required scope ({plan_required['summary']['benchmark_count']})"
    )


def test_benchmark_plan_scope_unknown_id_raises() -> None:
    """benchmark_plan raises ValueError for an unknown scope id."""
    with pytest.raises(ValueError, match="unknown external memory benchmark scope"):
        benchmark_plan(scope="no-such-benchmark-id")


# ---------------------------------------------------------------------------
# New tests — runner behaviour
# ---------------------------------------------------------------------------

def test_run_external_memory_benchmarks_no_env_vars(monkeypatch) -> None:
    """With no env vars configured, status is ACTION_REQUIRED and every case is NOT_CONFIGURED."""
    registry = load_memory_benchmark_registry()
    # Ensure none of the command_env variables are set
    for item in registry["benchmarks"]:
        monkeypatch.delenv(item["command_env"], raising=False)
    report = run_external_memory_benchmarks(scope="required", strict=False)
    assert report["status"] == "ACTION_REQUIRED", (
        f"expected ACTION_REQUIRED, got {report['status']!r}. "
        f"required_not_configured: {report['summary']['required_not_configured']}"
    )
    for case in report["cases"]:
        assert case["status"] == "NOT_CONFIGURED", (
            f"case {case['id']!r} expected NOT_CONFIGURED, got {case['status']!r}"
        )


# ---------------------------------------------------------------------------
# New tests — pretty renderers
# ---------------------------------------------------------------------------

def test_pretty_renderers_return_non_empty() -> None:
    """render_external_memory_plan_pretty and render_external_memory_report_pretty return non-empty strings."""
    plan = benchmark_plan(scope="required")
    plan_text = render_external_memory_plan_pretty(plan)
    assert plan_text, "render_external_memory_plan_pretty returned empty string"
    assert "SEAM external memory benchmark plan" in plan_text

    # Construct a minimal report-shaped payload so we are not affected by env
    report_payload: dict = {
        "version": "SEAM-EXTERNAL-MEMORY-BENCHMARK-RUN/1",
        "scope": "required",
        "strict": False,
        "status": "PASS",
        "cases": [
            {
                "id": "locomo",
                "name": "LoCoMo",
                "priority": "P1",
                "required": True,
                "command_env": "SEAM_BENCH_LOCOMO_COMMAND",
                "command": "python -m locomo",
                "status": "PASS",
                "returncode": 0,
                "stdout_tail": "",
                "stderr_tail": "",
            }
        ],
        "summary": {
            "case_count": 1,
            "pass_count": 1,
            "fail_count": 0,
            "not_configured_count": 0,
            "required_not_configured": [],
        },
    }
    report_text = render_external_memory_report_pretty(report_payload)
    assert report_text, "render_external_memory_report_pretty returned empty string"
    assert "SEAM external memory benchmarks" in report_text


def test_registry_comparators_have_status_field() -> None:
    """Every comparator must have a status field with a valid value."""
    registry = load_memory_benchmark_registry()
    valid_statuses = {"implemented", "not_implemented", "deprecated"}
    for comparator in registry["comparators"]:
        assert "status" in comparator, (
            f"Comparator {comparator['id']!r} missing required 'status' field"
        )
        assert comparator["status"] in valid_statuses, (
            f"Comparator {comparator['id']!r} has invalid status "
            f"{comparator['status']!r}; expected one of {valid_statuses}"
        )


# ---------------------------------------------------------------------------
# New tests — CLI smoke
# ---------------------------------------------------------------------------

def test_cli_smoke_plan_json() -> None:
    """`python -m tools.run_external_memory_benchmarks --plan --format json` exits 0 and emits valid JSON."""
    result = subprocess.run(
        [sys.executable, "-m", "tools.run_external_memory_benchmarks", "--plan", "--format", "json"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"CLI --plan --format json exited with {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    data = json.loads(result.stdout)
    assert isinstance(data, dict), "expected JSON object at top level"
    assert "version" in data, f"expected 'version' key, got keys: {list(data.keys())}"
