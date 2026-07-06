"""CI1 — Assert .github/workflows/ci.yml contains the four SEAM verify_* steps
in the correct position (after Run tests, before Run benchmark suite)."""

from pathlib import Path

import yaml

CI_YML = Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "ci.yml"

VERIFY_STEPS = [
    "python -m tools.history.verify_integrity",
    "python -m tools.history.verify_continuity --no-snapshot",
    "python -m tools.history.verify_routing",
    "python -m tools.streams.verify_streams",
]


def _load_steps():
    with open(CI_YML) as fh:
        doc = yaml.safe_load(fh)
    return doc["jobs"]["test-and-benchmark"]["steps"]


def test_ci_yaml_loads():
    """CI YAML must parse without error."""
    steps = _load_steps()
    assert isinstance(steps, list)
    assert len(steps) > 0


def test_ci_has_all_four_verify_steps():
    """Every verify step is present in the step list with exact run value."""
    steps = _load_steps()
    runs = [s.get("run") for s in steps if "run" in s]
    for cmd in VERIFY_STEPS:
        assert cmd in runs, f"Missing verify step: {cmd}"


def test_ci_verify_steps_ordered():
    """Verify steps appear in the canonical order within the step list."""
    steps = _load_steps()
    runs = [s.get("run") for s in steps if "run" in s]
    positions = [runs.index(cmd) for cmd in VERIFY_STEPS]
    assert positions == sorted(positions), (
        f"Verify steps are out of order: positions={positions}"
    )


def test_ci_verify_steps_after_tests():
    """All four verify steps appear AFTER the 'Run tests' step."""
    steps = _load_steps()
    run_test_idx = next(
        i for i, s in enumerate(steps) if s.get("name") == "Run tests"
    )
    verify_positions = [
        i for i, s in enumerate(steps)
        if s.get("run") in VERIFY_STEPS
    ]
    for pos in verify_positions:
        assert pos > run_test_idx, (
            f"Verify step {steps[pos].get('run')} at index {pos} "
            f"must be after 'Run tests' at index {run_test_idx}"
        )


def test_ci_verify_steps_before_benchmark():
    """All four verify steps appear BEFORE the 'Run benchmark suite' step."""
    steps = _load_steps()
    bench_idx = next(
        i for i, s in enumerate(steps)
        if s.get("name") == "Run benchmark suite"
    )
    verify_positions = [
        i for i, s in enumerate(steps)
        if s.get("run") in VERIFY_STEPS
    ]
    for pos in verify_positions:
        assert pos < bench_idx, (
            f"Verify step {steps[pos].get('run')} at index {pos} "
            f"must be before 'Run benchmark suite' at index {bench_idx}"
        )
