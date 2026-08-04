"""The maintenance report must be a gate, not a bulletin.

HISTORY#525 recorded dirty worktrees as an open finding; it stayed open because
`repository-maintenance.yml` computed a verdict and then uploaded it as an
artifact nobody was gated on. A linked worktree carrying uncommitted work then
survived 13 days. These tests pin the enforcement so it cannot regress to
reporting.
"""
from __future__ import annotations

from pathlib import Path

from tools.ci.github_maintenance_report import build_report

WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/repository-maintenance.yml"
PRE_PUSH = Path(__file__).resolve().parents[2] / "tools/git-hooks/pre-push"


def _worktree(path, dirty, primary=False):
    return {"path": path, "branch": "b", "dirty_file_count": dirty, "is_primary": primary}


class TestWorktreeVerdict:
    def test_dirty_linked_worktree_requires_action(self):
        report = build_report(prs=[], branches=[], worktrees=[_worktree("/w", 12)])
        assert report["status"] == "ACTION_REQUIRED"
        assert report["summary"]["dirty_worktree_count"] == 1

    def test_dirty_primary_worktree_is_not_a_violation(self):
        """Ordinary in-progress editing. A gate that fires here gets disabled."""
        report = build_report(prs=[], branches=[], worktrees=[_worktree("/main", 9, primary=True)])
        assert report["status"] == "PASS"

    def test_clean_worktrees_pass(self):
        report = build_report(prs=[], branches=[], worktrees=[_worktree("/w", 0)])
        assert report["status"] == "PASS"

    def test_worktrees_are_optional_for_callers(self):
        assert build_report(prs=[], branches=[])["status"] == "PASS"


class TestWorkflowIsGated:
    def test_report_runs_with_strict(self):
        assert "--strict" in WORKFLOW.read_text(encoding="utf-8"), (
            "repository-maintenance must run the report with --strict, or the "
            "verdict is advisory again"
        )

    def test_report_is_uploaded_even_when_the_gate_fails(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        assert "if: always()" in text, (
            "the artifact must upload on failure, otherwise a tripped gate gives "
            "no way to see what tripped it"
        )


class TestWorktreeGateIsLocal:
    """CI cannot enforce worktree hygiene, so the hook must.

    A GitHub Actions checkout has exactly one clean worktree, so a CI-side
    worktree gate reports PASS forever. The enforcement has to run where linked
    worktrees actually exist -- on the developer's machine, at push time.
    """

    def test_pre_push_checks_linked_worktrees(self):
        text = PRE_PUSH.read_text(encoding="utf-8")
        assert "git worktree list" in text, "pre-push must enumerate worktrees"
        assert "status --porcelain" in text, "pre-push must detect uncommitted files"

    def test_pre_push_exempts_the_primary_worktree(self):
        text = PRE_PUSH.read_text(encoding="utf-8")
        assert "PRIMARY_WT" in text, (
            "the primary worktree must be exempt; a hook that refuses ordinary "
            "in-progress editing gets bypassed"
        )

    def test_pre_push_override_is_explicit_and_documented(self):
        text = PRE_PUSH.read_text(encoding="utf-8")
        assert "SEAM_ALLOW_DIRTY_WORKTREES" in text, (
            "an un-overridable hook gets deleted; the escape hatch must be named"
        )
