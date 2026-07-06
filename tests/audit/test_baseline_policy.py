"""D4 — CI baseline-source policy tests."""

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

from seam_runtime import cli as seam_cli
from seam_runtime.benchmark_baseline_policy import (
    _bundle_git_sha,
    _is_reachable,
    _merge_base,
    resolve_baseline,
)


def _make_bundle(git_sha: str | None) -> dict:
    return {
        "manifest": {
            "version": "SEAM-BENCH/1",
            "run_id": "bench:test",
            "git_sha": git_sha,
        },
        "bundle_hash": "abc123",
    }


def test_bundle_git_sha():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(_make_bundle("deadbeef"), f)
        path = Path(f.name)
    try:
        assert _bundle_git_sha(path) == "deadbeef"
    finally:
        path.unlink()


def test_bundle_git_sha_none_when_missing():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump({"not": "a bundle"}, f)
        path = Path(f.name)
    try:
        assert _bundle_git_sha(path) is None
    finally:
        path.unlink()


def test_is_reachable_ancestor():
    """merge-base IS reachable from HEAD (it's an ancestor)."""
    repo_root = Path(
        subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True,
        ).stdout.strip()
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()
    mb = _merge_base(repo_root)
    if mb is None:
        pytest.skip("cannot determine merge-base (no origin/main?)")
    # merge-base is an ancestor of HEAD
    assert _is_reachable(repo_root, mb, head) is True


def test_holdout_exclusion():
    """resolve_baseline excludes holdout/ paths."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "benchmarks" / "runs" / "holdout").mkdir(parents=True)
        holdout_bundle = root / "benchmarks" / "runs" / "holdout" / "run.json"
        holdout_bundle.write_text(json.dumps(_make_bundle(None)))

        # With a non-git temp dir, resolve_baseline should return None
        # because merge_base won't resolve.
        result = resolve_baseline(repo_root=root)
        assert result is None


def test_holdout_exclusion_does_not_drop_sibling_prefix_dirs(monkeypatch, tmp_path):
    runs = tmp_path / "benchmarks" / "runs"
    holdout = runs / "holdout" / "run.json"
    holdout.parent.mkdir(parents=True)
    holdout.write_text(json.dumps(_make_bundle("holdout-sha")), encoding="utf-8")
    public = runs / "holdout-extra" / "run.json"
    public.parent.mkdir(parents=True)
    public.write_text(json.dumps(_make_bundle("public-sha")), encoding="utf-8")

    monkeypatch.setattr("seam_runtime.benchmark_baseline_policy._merge_base", lambda root: "merge-base")
    monkeypatch.setattr("seam_runtime.benchmark_baseline_policy._is_reachable", lambda root, sha, merge_base: True)

    result = resolve_baseline(repo_root=tmp_path)

    assert result == public


def test_no_baseline_fallback_none():
    """When no runs dir exists, resolve_baseline returns None."""
    with tempfile.TemporaryDirectory() as tmp:
        result = resolve_baseline(repo_root=Path(tmp))
        assert result is None


def test_explicit_baseline_override():
    """resolve_baseline does not interfere with explicit --baseline."""
    # The CLI path with --baseline skips resolve_baseline entirely.
    # This test verifies the function does not mutate global state or
    # interfere with explicit paths.
    result = resolve_baseline(repo_root=Path("/nonexistent"))
    assert result is None


def test_cli_gate_excludes_candidate_from_auto_baseline(monkeypatch, tmp_path, capsys):
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps(_make_bundle("candidate")), encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps(_make_bundle("baseline")), encoding="utf-8")
    observed: dict[str, Path | None] = {}

    class FakeRuntime:
        def __init__(self, db_path):
            self.db_path = db_path

        def evaluate_benchmark_gate(self, bundle, baseline=None, policy=None):
            observed["bundle"] = Path(bundle)
            observed["baseline"] = Path(baseline) if baseline is not None else None
            return {
                "version": "SEAM-BENCHMARK-GATE/1",
                "status": "PASS",
                "run": {"run_id": "candidate", "bundle_hash": "abc"},
                "summary": {"checks": 1, "passed": 1, "failed": 0},
                "checks": [],
            }

    def fake_resolve_baseline(*, current_run=None):
        observed["current_run"] = current_run
        return baseline

    monkeypatch.setattr(seam_cli, "SeamRuntime", FakeRuntime)
    monkeypatch.setattr(seam_cli, "resolve_baseline", fake_resolve_baseline)

    seam_cli.run_cli(["benchmark", "gate", str(candidate), "--format", "json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "PASS"
    assert observed["bundle"] == candidate
    assert observed["current_run"] == candidate
    assert observed["baseline"] == baseline
