"""The operator's cleanup report must not turn a closed PR into deletion proof."""

import json
from datetime import datetime, timezone

import pytest

from tools.git import scan_stale_branches as scanner


@pytest.mark.parametrize("state", ["CLOSED", "MERGED"])
def test_unique_pr_branch_requires_review_in_operator_report(monkeypatch, capsys, state):
    branch = scanner.BranchInfo(
        name="origin/unfinished", is_remote=True, unique_commits=2,
        last_commit_date=datetime.now(timezone.utc), last_commit_sha="a" * 40,
        pr_state=state, pr_number=7,
    )
    monkeypatch.setattr(scanner, "list_branches", lambda include_remote: [branch])
    monkeypatch.setattr(scanner, "annotate_with_prs", lambda branches: None)
    monkeypatch.setattr("sys.argv", ["scan_stale_branches"])
    scanner.main()
    report = capsys.readouterr().out
    assert "unfinished" in report
    assert "REVIEW" in report
    assert "DELETE" not in report


def test_closed_branch_reachable_on_main_is_a_completed_cleanup_candidate(monkeypatch, capsys):
    branch = scanner.BranchInfo(
        name="origin/completed", is_remote=True, unique_commits=0,
        last_commit_date=datetime.now(timezone.utc), last_commit_sha="b" * 40,
        pr_state="CLOSED", pr_number=8,
    )
    monkeypatch.setattr(scanner, "list_branches", lambda include_remote: [branch])
    monkeypatch.setattr(scanner, "annotate_with_prs", lambda branches: None)
    monkeypatch.setattr("sys.argv", ["scan_stale_branches", "--json"])
    scanner.main()
    report = json.loads(capsys.readouterr().out)
    assert [item["name"] for item in report["on-main"]] == ["origin/completed"]
