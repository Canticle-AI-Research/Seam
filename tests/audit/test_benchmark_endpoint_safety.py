"""W2 — /benchmark endpoint policy + suite validation."""

import os

import pytest
from fastapi.testclient import TestClient

from seam_runtime.runtime import SeamRuntime
from seam_runtime.server import create_app


@pytest.fixture
def bench_client():
    """Create a TestClient without rate limiting interfering."""
    os.environ["SEAM_API_RATE_LIMIT_PER_MINUTE"] = "0"
    runtime = SeamRuntime(":memory:")
    app = create_app(runtime)
    yield TestClient(app)
    os.environ.pop("SEAM_API_RATE_LIMIT_PER_MINUTE", None)


def test_benchmark_smoke_all(bench_client):
    """POST /benchmark {"suite":"all"} returns 200."""
    resp = bench_client.post("/benchmark", json={"suite": "all"})
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_benchmark_rejects_invalid_suite(bench_client):
    """POST /benchmark {"suite":"../etc"} returns 422 or 400 with 'invalid suite'."""
    resp = bench_client.post("/benchmark", json={"suite": "../etc"})
    assert resp.status_code in (400, 422)
    assert "invalid suite" in resp.json()["detail"].lower()


def test_benchmark_holdout_rejected_without_env(bench_client):
    """POST /benchmark with holdout=true returns 403 when env is not set."""
    resp = bench_client.post("/benchmark", json={"suite": "all", "holdout": True})
    assert resp.status_code == 403
    detail = resp.json()["detail"].lower()
    assert "holdout" in detail or "seam_api_allow_benchmark_holdout" in detail


def test_benchmark_holdout_allowed_with_env(bench_client, monkeypatch):
    """POST /benchmark with holdout=true + env vars returns 200."""
    calls = []

    def _fake_run_benchmark_suite(runtime, *, suite, persist, holdout):
        calls.append({"suite": suite, "persist": persist, "holdout": holdout})
        return {"ok": True, "suite": suite, "holdout": holdout}

    monkeypatch.setattr("seam_runtime.benchmarks.run_benchmark_suite", _fake_run_benchmark_suite)
    os.environ["SEAM_API_ALLOW_BENCHMARK_HOLDOUT"] = "1"
    os.environ["SEAM_API_CONFIRM_HOLDOUT"] = "1"
    try:
        resp = bench_client.post("/benchmark", json={"suite": "all", "holdout": True})
        assert resp.status_code == 200
        assert resp.json()["holdout"] is True
        assert calls == [{"suite": "all", "persist": False, "holdout": True}]
    finally:
        os.environ.pop("SEAM_API_ALLOW_BENCHMARK_HOLDOUT", None)
        os.environ.pop("SEAM_API_CONFIRM_HOLDOUT", None)


def test_benchmark_valid_suites(bench_client):
    """POST /benchmark with each known suite returns 200."""
    from seam_runtime.benchmarks import BENCHMARK_SUITES
    for suite in BENCHMARK_SUITES:
        resp = bench_client.post("/benchmark", json={"suite": suite})
        assert resp.status_code == 200, f"suite {suite!r} returned {resp.status_code}"
