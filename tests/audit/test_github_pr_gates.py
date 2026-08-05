from pathlib import Path

import yaml

_MARKER = "pytest" ".mark.external"  # split so this file never matches itself

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github/workflows/ci.yml"

FAST_CI_JOBS = {
    "repo-hygiene",
    "chroma-real-smoke",
    "locomo-quickstart-bil2",
    "package-smoke",
    "pgvector-integration",
}


def _external_test_files() -> set[str]:
    """Every test file carrying the external marker, as repo-relative paths.

    Derived from the tree rather than hardcoded: a new external test must be
    added to the pgvector job or `test_ci_enforces_no_silent_skips` fails.
    This file is excluded -- it names the marker in its own assertions.
    """
    this_file = Path(__file__).resolve()
    found: set[str] = set()
    for directory in ("tests", "test_seam_all"):
        for path in (REPO_ROOT / directory).rglob("test_*.py"):
            if path.resolve() == this_file:
                continue
            if _MARKER in path.read_text(encoding="utf-8"):
                found.add(path.relative_to(REPO_ROOT).as_posix())
    return found


def test_ci_workflow_requires_locomo_bil2_and_chroma_smokes() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    # `dash` is load-bearing, not cosmetic: seam_runtime/tui is the live
    # dashboard, and tests/ enforces strict no-skip, so without the extra the
    # TUI cases fail the run rather than skip. Its absence is also why the 28
    # TextualDashboardApp cases in test_seam_all/ went unexercised in CI.
    assert 'python -m pip install -e ".[server,sbert,rerank,dash]"' in workflow
    assert "python -m tools.ci.verify_dependency_contract" in workflow
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
    real-service (external) tests, and a dedicated job runs EVERY external test
    against the live pgvector service with PGVECTOR_TEST_DSN set.

    The required file set is computed from the test tree, not hardcoded. The
    previous version asserted two filenames while claiming to cover "every
    external test", so when the pgvector job drifted to an explicit 3-file list
    it stayed green while 13 of 23 external tests ran in no lane at all.
    `-m "not external"` deselects rather than skips, so strict no-skip cannot
    catch this; only an explicit invariant can.
    """
    raw = CI_WORKFLOW.read_text(encoding="utf-8")
    assert '-m "not external"' in raw  # main job deselects, not skips

    workflow = yaml.safe_load(raw)
    pgvector_steps = workflow["jobs"]["pgvector-integration"]["steps"]
    commands = " ".join(step.get("run", "") for step in pgvector_steps)
    env_blocks = " ".join(
        " ".join(f"{k}={v}" for k, v in (step.get("env") or {}).items())
        for step in pgvector_steps
    )
    assert "PGVECTOR_TEST_DSN" in env_blocks  # pgvector job sets the gate's DSN

    required = _external_test_files()
    assert required, "no external-marked test files found; the discovery glob is wrong"
    missing = sorted(path for path in required if path not in commands)
    assert not missing, (
        "these files carry pytest.mark.external but the pgvector-integration job "
        f"does not run them, so their tests execute in no CI lane: {missing}"
    )


def test_repo_hygiene_runs_the_configured_linter() -> None:
    """pyproject configures ruff; a required check must actually run it."""
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    commands = " ".join(
        step.get("run", "") for step in workflow["jobs"]["repo-hygiene"]["steps"]
    )
    assert "ruff check" in commands


def test_advisory_suite_waits_for_fast_ci_jobs() -> None:
    """The sole self-hosted runner must finish merge gates before the long suite."""
    workflow = yaml.safe_load(
        CI_WORKFLOW.read_text(encoding="utf-8")
    )

    needs = workflow["jobs"]["test-and-benchmark"]["needs"]
    assert set(needs) == FAST_CI_JOBS
    assert len(needs) == len(FAST_CI_JOBS)
    assert set(needs) <= set(workflow["jobs"])


def test_advisory_suite_reports_slowest_tests() -> None:
    workflow = yaml.safe_load(
        CI_WORKFLOW.read_text(encoding="utf-8")
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
    conftest = Path(REPO_ROOT / "tests/conftest.py").read_text(encoding="utf-8")
    assert "SEAM_STRICT_NO_SKIP" in conftest
    assert "pytest_sessionfinish" in conftest


def test_pull_request_template_keeps_repo_management_checklist_visible() -> None:
    template = Path(REPO_ROOT / ".github/pull_request_template.md").read_text(encoding="utf-8")

    assert "No paid benchmark/API calls" in template
    assert "BIL-2 quickstart" in template
    assert "history/stream" in template.lower()
    assert "secrets" in template.lower()
