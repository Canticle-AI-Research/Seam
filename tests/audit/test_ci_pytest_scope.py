"""CI2 — Assert the CI "Run tests" step includes tools/streams/ and tests/
alongside the existing test_seam_all/ and tools/history/test_history_tools.py."""

from pathlib import Path

import yaml

CI_YML = Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "ci.yml"


def _find_run_tests_step():
    with open(CI_YML) as fh:
        doc = yaml.safe_load(fh)
    steps = doc["jobs"]["test-and-benchmark"]["steps"]
    matching = [s for s in steps if s.get("name") == "Run tests"]
    assert len(matching) == 1, (
        f"Expected exactly one 'Run tests' step, found {len(matching)}"
    )
    return matching[0]


def test_ci_yaml_loads():
    """CI YAML must parse without error."""
    with open(CI_YML) as fh:
        doc = yaml.safe_load(fh)
    assert isinstance(doc["jobs"]["test-and-benchmark"]["steps"], list)


def test_single_run_tests_step():
    """There is exactly one step named 'Run tests'."""
    _find_run_tests_step()


def test_run_tests_includes_tools_streams():
    """The Run tests invocation includes tools/streams/."""
    step = _find_run_tests_step()
    assert "tools/streams/" in step["run"], (
        f"'tools/streams/' not found in run: {step['run']}"
    )


def test_run_tests_includes_tests():
    """The Run tests invocation includes tests/."""
    step = _find_run_tests_step()
    assert "tests/" in step["run"], (
        f"'tests/' not found in run: {step['run']}"
    )


def test_run_tests_preserves_existing_paths():
    """The Run tests invocation still includes the original paths."""
    step = _find_run_tests_step()
    assert "test_seam_all/" in step["run"], (
        f"'test_seam_all/' not found in run: {step['run']}"
    )
    assert "tools/history/test_history_tools.py" in step["run"], (
        f"'tools/history/test_history_tools.py' not found in run: {step['run']}"
    )
