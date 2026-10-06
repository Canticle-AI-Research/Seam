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

import re
import subprocess
import sys
from dataclasses import dataclass
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
REFERENCE_GATE_MODULE = "tools.docs.sync_references"
AGENT_CONFIG_MODULE = "tools.git.verify_agent_config"
REQUIRED_GATE_MODULES = {
    AGENT_CONFIG_MODULE,
    "tools.history.verify_handoffs",
    "tools.history.verify_integrity",
    "tools.history.verify_continuity",
    "tools.history.verify_routing",
    "tools.streams.verify_streams",
    WIKI_GATE_MODULE,
    REFERENCE_GATE_MODULE,
}

# There are THREE local gate locations, not two. The first draft of this file
# checked only the Claude hook and the closeout wrapper, and would have passed
# while tools/git-hooks/pre-commit stayed suppressed -- the full suite caught it.
# Any new local gate belongs in this list.
LOCAL_GATE_SCRIPTS = (PREFLIGHT_HOOK, COMMIT_HOOK)

RUN_GATE_RE = re.compile(r'^run_gate "[^"]+"\s+"\$PY" -m (\S+)(.*)$')
BARE_GATE_RE = re.compile(
    r'^"\$PY" -m (tools\.\S+?)((?: [^|]*?)?)\s*(\|\|\s*.+)?$'
)


@dataclass(frozen=True)
class GateInvocation:
    module: str
    args: tuple[str, ...]
    line_number: int
    form: str
    aborts: bool


def _script_gate_invocations(text: str) -> list[GateInvocation]:
    """Parse supported gate forms while keeping presence separate from strength."""

    invocations = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        run_gate = RUN_GATE_RE.match(line)
        if run_gate:
            invocations.append(
                GateInvocation(
                    module=run_gate.group(1),
                    args=tuple(run_gate.group(2).strip().split()),
                    line_number=line_number,
                    form="run_gate",
                    aborts=True,
                )
            )
            continue
        bare = BARE_GATE_RE.match(line)
        if bare:
            invocations.append(
                GateInvocation(
                    module=bare.group(1),
                    args=tuple(bare.group(2).strip().split()),
                    line_number=line_number,
                    form="bare",
                    aborts=bool(
                        bare.group(3)
                        and re.fullmatch(r"\|\|\s*exit 1\s*", bare.group(3))
                    ),
                )
            )
    return invocations


def _gate_lines(script: Path) -> list[str]:
    """Executable supported gate lines from a gate script, comments excluded."""
    lines = script.read_text(encoding="utf-8").splitlines()
    return [
        line
        for line in lines
        if RUN_GATE_RE.match(line) or BARE_GATE_RE.match(line)
    ]


def _script_gate_modules(script: Path) -> set[str]:
    """Return Python modules invoked by supported executable gate lines."""

    return {
        invocation.module
        for invocation in _script_gate_invocations(script.read_text(encoding="utf-8"))
    }


def _required_ci_agent_config_step(workflow: dict) -> dict:
    """Return the unconditional exact validator step from required hygiene."""

    job = workflow["jobs"]["repo-hygiene"]
    assert "if" not in job, "repo-hygiene must not conditionally bypass required gates"
    matches = [
        step
        for step in job["steps"]
        if AGENT_CONFIG_MODULE in str(step.get("run", ""))
    ]
    assert len(matches) == 1, (
        "repo-hygiene must contain exactly one agent-configuration validator step"
    )
    step = matches[0]
    assert "if" not in step, "agent-configuration validation must be unconditional"
    assert not step.get("continue-on-error", False), (
        "agent-configuration validation must fail repo-hygiene"
    )
    assert step["run"].strip() == f"python -m {AGENT_CONFIG_MODULE}", (
        "agent-configuration validation must be an unsuppressed exact command"
    )
    return step


def _assert_commit_hook_agent_config(text: str) -> None:
    invocations = [
        item for item in _script_gate_invocations(text) if item.module == AGENT_CONFIG_MODULE
    ]
    assert len(invocations) == 1, "commit hook must invoke agent-config exactly once"
    invocation = invocations[0]
    assert invocation.args == ("--staged",)
    assert invocation.form == "bare"
    assert invocation.aborts, "early agent-config scope block must abort immediately"
    merge_exit = next(
        index
        for index, line in enumerate(text.splitlines(), start=1)
        if ".git/MERGE_HEAD" in line
    )
    assert invocation.line_number < merge_exit, (
        "agent-config scope block must run before merge/rebase early exits"
    )


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


def test_commit_hook_keeps_agent_config_staged_early_and_aborting():
    _assert_commit_hook_agent_config(COMMIT_HOOK.read_text(encoding="utf-8"))


def test_required_repo_hygiene_enforces_agent_config_unconditionally():
    workflow = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    _required_ci_agent_config_step(workflow)


@pytest.mark.parametrize("script", LOCAL_GATE_SCRIPTS, ids=lambda p: p.name)
def test_parser_detects_removal_of_each_shell_agent_config_invocation(script):
    text = script.read_text(encoding="utf-8")
    invocation = next(
        line for line in text.splitlines() if AGENT_CONFIG_MODULE in line and not line.lstrip().startswith("#")
    )
    mutated = text.replace(f"{invocation}\n", "", 1)

    assert AGENT_CONFIG_MODULE not in {
        item.module for item in _script_gate_invocations(mutated)
    }


def test_parity_detection_rejects_closeout_agent_config_removal():
    from tools.history.closeout import PREFLIGHT_GATES

    modules = {args[0] for _label, args in PREFLIGHT_GATES}
    mutated = modules - {AGENT_CONFIG_MODULE}
    assert AGENT_CONFIG_MODULE not in mutated
    assert REQUIRED_GATE_MODULES - mutated == {AGENT_CONFIG_MODULE}


def test_ci_detection_rejects_advisory_only_agent_config():
    workflow = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    workflow["jobs"]["repo-hygiene"]["steps"] = [
        step
        for step in workflow["jobs"]["repo-hygiene"]["steps"]
        if AGENT_CONFIG_MODULE not in str(step.get("run", ""))
    ]
    assert any(
        AGENT_CONFIG_MODULE in str(step.get("run", ""))
        for step in workflow["jobs"]["test-and-benchmark"]["steps"]
    )
    with pytest.raises(AssertionError, match="exactly one"):
        _required_ci_agent_config_step(workflow)


@pytest.mark.parametrize(
    ("needle", "replacement", "message"),
    [
        (" --staged || exit 1", " || exit 1", ""),
        (" || exit 1", " || true", "abort"),
    ],
)
def test_commit_hook_detection_rejects_weakened_scope_block(
    needle, replacement, message
):
    text = COMMIT_HOOK.read_text(encoding="utf-8")
    gate_line = next(
        line
        for line in text.splitlines()
        if AGENT_CONFIG_MODULE in line and line.startswith('"$PY"')
    )
    mutated = text.replace(gate_line, gate_line.replace(needle, replacement), 1)
    with pytest.raises(AssertionError, match=message or None):
        _assert_commit_hook_agent_config(mutated)


def test_commit_hook_detection_rejects_late_scope_block():
    text = COMMIT_HOOK.read_text(encoding="utf-8")
    lines = text.splitlines()
    gate = next(line for line in lines if AGENT_CONFIG_MODULE in line and line.startswith('"$PY"'))
    lines.remove(gate)
    lines.append(gate)
    with pytest.raises(AssertionError, match="before merge/rebase"):
        _assert_commit_hook_agent_config("\n".join(lines))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("if", "${{ false }}", "unconditional"),
        ("continue-on-error", True, "fail repo-hygiene"),
        ("run", f"python -m {AGENT_CONFIG_MODULE} || true", "unsuppressed"),
    ],
)
def test_ci_detection_rejects_agent_config_bypass(field, value, message):
    workflow = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    step = next(
        step
        for step in workflow["jobs"]["repo-hygiene"]["steps"]
        if AGENT_CONFIG_MODULE in str(step.get("run", ""))
    )
    step[field] = value
    with pytest.raises(AssertionError, match=message):
        _required_ci_agent_config_step(workflow)


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


def test_required_hygiene_checks_references_without_generating_or_bypassing():
    workflow = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    steps = [step for step in workflow["jobs"]["repo-hygiene"]["steps"]
             if REFERENCE_GATE_MODULE in step.get("run", "")]
    assert len(steps) == 1
    assert "if" not in steps[0] and not steps[0].get("continue-on-error")
    assert steps[0]["run"] == f"python -m {REFERENCE_GATE_MODULE} --check"


def test_required_hygiene_runs_documentation_regressions():
    workflow = yaml.safe_load(CI_YML.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["repo-hygiene"]["steps"]
    suites = [step for step in steps if "pytest tools/docs/test_sync_references.py" in step.get("run", "")]
    assert len(suites) == 1
    assert "if" not in suites[0] and not suites[0].get("continue-on-error")
    assert suites[0]["run"] == (
        "python -m pytest tools/docs/test_sync_references.py "
        "tests/audit/test_local_gates_match_ci.py tests/audit/test_history_closeout.py -q"
    )
    installs = [step["run"] for step in steps if "pip install" in step.get("run", "")]
    assert any("pytest" in run for run in installs)


def test_commit_hook_checks_exact_staged_references():
    calls = [call for call in _script_gate_invocations(COMMIT_HOOK.read_text(encoding="utf-8"))
             if call.module == REFERENCE_GATE_MODULE]
    assert len(calls) == 1 and calls[0].aborts
    assert calls[0].args == ("--check", "--staged")


def test_scheduled_reference_check_has_no_publication_or_write_permission():
    path = REPO_ROOT / ".github/workflows/documentation-check.yml"
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert workflow["permissions"] == {"contents": "read"}
    assert set(workflow["on"]) == {"schedule", "workflow_dispatch"}
    assert workflow["jobs"]["documentation-check"]["runs-on"] == ["self-hosted", "seam-box"]
    runs = [step.get("run", "") for step in workflow["jobs"]["documentation-check"]["steps"]]
    assert f"python -m {REFERENCE_GATE_MODULE} --check" in runs
    assert all("--update" not in run and "git push" not in run for run in runs)


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
