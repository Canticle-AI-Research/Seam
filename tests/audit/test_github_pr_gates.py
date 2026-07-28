from pathlib import Path

import yaml

FAST_CI_JOBS = {
    "repo-hygiene",
    "chroma-real-smoke",
    "locomo-quickstart-bil2",
    "package-smoke",
    "pgvector-integration",
}


def test_ci_workflow_requires_locomo_bil2_and_chroma_smokes() -> None:
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert 'python -m pip install -e ".[server,sbert,rerank,selfhost]"' in workflow
    assert "python -m tools.history.verify_continuity --no-snapshot" in workflow
    assert "python -m tools.history.verify_handoffs" in workflow
    assert "locomo-quickstart-bil2:" in workflow
    assert "python -m seam bench external --quickstart locomo" in workflow
    assert "python -m seam bench seal locomo.quickstart.json --level BIL-2 --allow-stub-seal" in workflow
    assert "python -m seam bench verify locomo.quickstart.bil2.json --format json" in workflow
    assert "python -m tools.ci.chroma_real_smoke" in workflow
    assert "Secret/session URL scan" in workflow
    assert "git diff --check" in workflow


def test_ci_enforces_no_silent_skips() -> None:
    """The CI must never let a test silently skip: the main job deselects the
    real-service (external) tests, and a dedicated job runs every external test
    against the live pgvector service with PGVECTOR_TEST_DSN set."""
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert '-m "not external"' in workflow            # main job deselects, not skips
    assert "PGVECTOR_TEST_DSN" in workflow              # pgvector job sets the gate's DSN
    # the pgvector job runs the real-service test files (so they cannot silently skip)
    assert "test_pgvector_pk_composite.py" in workflow
    assert "test_substream_isolation.py" in workflow


def test_advisory_suite_waits_for_fast_ci_jobs() -> None:
    """The sole self-hosted runner must finish merge gates before the long suite."""
    workflow = yaml.safe_load(
        Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    )

    needs = workflow["jobs"]["test-and-benchmark"]["needs"]
    assert set(needs) == FAST_CI_JOBS
    assert len(needs) == len(FAST_CI_JOBS)
    assert set(needs) <= set(workflow["jobs"])


def test_advisory_suite_reports_slowest_tests() -> None:
    workflow = yaml.safe_load(
        Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    runs = [
        step.get("run", "")
        for step in workflow["jobs"]["test-and-benchmark"]["steps"]
    ]
    assert any(
        "python -m pytest" in run and "--durations=25" in run
        for run in runs
    )


def test_strict_no_skip_hook_present() -> None:
    """The conftest enforces strict no-skip (default on, opt out with =0)."""
    conftest = Path("tests/conftest.py").read_text(encoding="utf-8")
    assert "SEAM_STRICT_NO_SKIP" in conftest
    assert "pytest_sessionfinish" in conftest


def test_pull_request_template_keeps_repo_management_checklist_visible() -> None:
    template = Path(".github/pull_request_template.md").read_text(encoding="utf-8")

    assert "No paid benchmark/API calls" in template
    assert "BIL-2 quickstart" in template
    assert "history/stream" in template.lower()
    assert "secrets" in template.lower()
