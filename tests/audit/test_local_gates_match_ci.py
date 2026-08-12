"""The local commit gates must not be weaker than the required CI check.

HISTORY#535 reached CI with an unscoped test-count claim because the local gates
-- the Claude PreToolUse hook (`tools/claude/preflight_protocol.sh`), the
canonical commit hook (`tools/git-hooks/pre-commit`), and the closeout wrapper
(`tools/history/closeout.py`) -- ran `verify_continuity --no-recorded-fact-audit`
while the required `repo-hygiene` check runs it with the audit enabled. Every
local gate reported success, so the failure was only discoverable after pushing.

The suppression was justified when it was introduced (HISTORY#166: a precedence
checker over-matched per-section prose counts and flagged HISTORY#111/#145).
`require_explicit_pytest_line=True` in the precedence path fixed that, and
HISTORY#536 removed the flag from both local gates.

These tests fail if anyone re-adds it or omits the required wiki-navigation
check. A local gate that is quieter than the gate that will actually block the
PR is a false negative generator, which is strictly worse than having no local
gate at all -- it converts "unverified" into "verified", which is the state an
agent acts on.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PREFLIGHT_HOOK = REPO_ROOT / "tools" / "claude" / "preflight_protocol.sh"
COMMIT_HOOK = REPO_ROOT / "tools" / "git-hooks" / "pre-commit"
CI_YML = REPO_ROOT / ".github" / "workflows" / "ci.yml"

SUPPRESSION_FLAG = "--no-recorded-fact-audit"
WIKI_GATE_MODULE = "tools.docs.verify_wiki"
WIKI_STAGED_FLAG = "--staged"
REQUIRED_GATE_MODULES = {
    "tools.history.verify_handoffs",
    "tools.history.verify_integrity",
    "tools.history.verify_continuity",
    "tools.history.verify_routing",
    "tools.streams.verify_streams",
    WIKI_GATE_MODULE,
}

# There are THREE local gate locations, not two. The first draft of this file
# checked only the Claude hook and the closeout wrapper, and would have passed
# while tools/git-hooks/pre-commit stayed suppressed -- the full suite caught it.
# Any new local gate belongs in this list.
LOCAL_GATE_SCRIPTS = (PREFLIGHT_HOOK, COMMIT_HOOK)


def _gate_lines(script: Path) -> list[str]:
    """Executable run_gate lines from a gate script, comments excluded."""
    lines = script.read_text(encoding="utf-8").splitlines()
    return [line for line in lines if line.strip().startswith("run_gate")]


def _script_gate_modules(script: Path) -> set[str]:
    """Return Python modules invoked by executable run_gate lines."""

    modules = set()
    for line in _gate_lines(script):
        marker = " -m "
        if marker in line:
            modules.add(line.split(marker, 1)[1].split()[0])
    return modules


@pytest.mark.parametrize("script", LOCAL_GATE_SCRIPTS, ids=lambda p: p.name)
def test_local_gate_scripts_do_not_suppress_the_fact_audit(script):
    """Every script gating git state must run the audit the PR check enforces."""
    continuity_gates = [line for line in _gate_lines(script) if "verify_continuity" in line]
    assert continuity_gates, f"{script.name} no longer runs verify_continuity at all"
    for line in continuity_gates:
        assert SUPPRESSION_FLAG not in line, (
            f"{script.name} suppresses the recorded-fact audit that the required "
            f"repo-hygiene check enforces: {line.strip()}"
        )


def test_closeout_wrapper_does_not_suppress_the_fact_audit():
    """The one-shot closeout wrapper must not report success CI would reject."""
    from tools.history.closeout import PREFLIGHT_GATES

    continuity = [args for label, args in PREFLIGHT_GATES if label == "verify_continuity"]
    assert continuity, "closeout no longer runs verify_continuity at all"
    for args in continuity:
        assert SUPPRESSION_FLAG not in args, (
            "closeout.PREFLIGHT_GATES suppresses the recorded-fact audit; a green "
            "closeout would again be weaker than the required repo-hygiene check"
        )


def test_ci_still_enforces_the_fact_audit():
    """Guards the other direction: the local gates are pinned to a live CI check.

    If CI ever stops running the audit, matching the local gates to CI becomes
    meaningless and these tests would pass vacuously.
    """
    ci_text = CI_YML.read_text(encoding="utf-8")
    assert "tools.history.verify_continuity" in ci_text, "CI no longer runs verify_continuity"
    for line in ci_text.splitlines():
        if "tools.history.verify_continuity" in line:
            assert SUPPRESSION_FLAG not in line, (
                f"CI itself now suppresses the fact audit: {line.strip()}"
            )


@pytest.mark.parametrize("script", LOCAL_GATE_SCRIPTS, ids=lambda p: p.name)
def test_local_gate_scripts_enforce_the_required_wiki_check(script):
    """A local green gate must include the wiki check required by CI."""

    wiki_gates = [line for line in _gate_lines(script) if WIKI_GATE_MODULE in line]
    assert wiki_gates, f"{script.name} omits required {WIKI_GATE_MODULE}"


@pytest.mark.parametrize("script", LOCAL_GATE_SCRIPTS, ids=lambda p: p.name)
def test_local_gate_scripts_cover_every_required_continuity_module(script):
    """Prevent a local preflight from quietly omitting a required CI gate."""

    missing = REQUIRED_GATE_MODULES - _script_gate_modules(script)
    assert not missing, f"{script.name} omits required modules: {sorted(missing)}"


def test_closeout_wrapper_enforces_the_required_wiki_check():
    """Closeout must not claim success before required wiki verification."""

    from tools.history.closeout import PREFLIGHT_GATES

    modules = [args[0] for _label, args in PREFLIGHT_GATES]
    assert WIKI_GATE_MODULE in modules


def test_closeout_wrapper_covers_every_required_continuity_module():
    """The closeout wrapper must cover the same continuity modules as CI."""

    from tools.history.closeout import PREFLIGHT_GATES

    modules = {args[0] for _label, args in PREFLIGHT_GATES}
    missing = REQUIRED_GATE_MODULES - modules
    assert not missing, f"closeout omits required modules: {sorted(missing)}"


def test_commit_hook_verifies_the_exact_staged_wiki():
    """An unstaged repair must not mask invalid documentation in the index."""

    wiki_gates = [
        line for line in _gate_lines(COMMIT_HOOK) if WIKI_GATE_MODULE in line
    ]
    assert wiki_gates
    assert all(WIKI_STAGED_FLAG in line for line in wiki_gates)


def test_ci_enforces_wiki_navigation():
    """Pin local wiki gates to a live required repo-hygiene command."""

    workflow = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    runs = [
        step.get("run")
        for step in workflow["jobs"]["repo-hygiene"]["steps"]
        if "run" in step
    ]
    assert f"python -m {WIKI_GATE_MODULE}" in runs


def test_the_fact_audit_actually_rejects_an_unscoped_count_claim(tmp_path):
    """Discrimination: prove the audit these gates run is not inert.

    Without this, every assertion above could hold while the audit itself
    silently passed everything -- the exact failure shape that let a broken
    fingerprint test look green in HISTORY#533.
    """
    from tools.history.test_count_audit import _audit_text

    unscoped = "Verification\n\n35 tests passed on the first execution.\n"
    issues = _audit_text(REPO_ROOT, Path("HISTORY.md"), unscoped)
    assert issues, "the audit accepted a count claim with no pytest path scope"
    assert "lacks pytest path scope" in issues[0]

    # Derive the count instead of hardcoding it: a literal would make this test
    # fail whenever a test is added to this very file, which is drift, not signal.
    from tools.history.test_count_audit import count_static_tests

    actual = count_static_tests([Path(__file__)])
    scoped = (
        "Verified with:\n\n"
        "    pytest tests/audit/test_local_gates_match_ci.py\n\n"
        f"{actual} tests passed on the first execution.\n"
    )
    assert not _audit_text(REPO_ROOT, Path("HISTORY.md"), scoped), (
        "a correctly scoped and accurate claim must pass"
    )


@pytest.mark.parametrize("module", ["tools.history.verify_continuity"])
def test_continuity_gate_passes_on_the_current_tree(module):
    """The enabled audit must be green here, or the change blocks every commit."""
    result = subprocess.run(
        [sys.executable, "-m", module, "--no-snapshot"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"{module} fails with the fact audit enabled:\n{result.stdout}\n{result.stderr}"
    )
