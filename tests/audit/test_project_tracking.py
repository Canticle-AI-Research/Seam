from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tools.ci import project_tracking

REPO_ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = REPO_ROOT / ".github" / "project-tracking-labels.json"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "project-tracking.yml"


class FakeClient:
    def __init__(
        self,
        *,
        labels: list[dict[str, Any]],
        issue: dict[str, Any] | None = None,
        apply: bool = True,
    ) -> None:
        self.labels = labels
        self.issue = issue
        self.apply = apply
        self.operations: list[tuple[str, Any]] = []

    def list_labels(self) -> list[dict[str, Any]]:
        return self.labels

    def get_issue(self, number: int) -> dict[str, Any]:
        self.operations.append(("get_issue", number))
        assert self.issue is not None
        return self.issue

    def create_label(self, label: project_tracking.CatalogLabel) -> None:
        self.operations.append(("create_label", label.name))

    def update_label(self, label: project_tracking.CatalogLabel) -> None:
        self.operations.append(("update_label", label.name))

    def add_labels(self, number: int, labels: list[str]) -> None:
        self.operations.append(("add_labels", number, tuple(labels)))

    def remove_label(self, number: int, label: str) -> None:
        self.operations.append(("remove_label", number, label))


def _catalog_labels() -> tuple[project_tracking.CatalogLabel, ...]:
    return project_tracking.load_catalog(CATALOG_PATH)


def _label_rows() -> list[dict[str, Any]]:
    return [
        {"name": label.name, "color": label.color, "description": label.description}
        for label in _catalog_labels()
    ]


def _event(action: str, number: int = 41) -> dict[str, Any]:
    return {
        "action": action,
        "repository": {"full_name": "Canticle-AI-Research/Seam"},
        "issue": {"number": number, "state": "open", "labels": []},
    }


def test_catalog_has_bounded_type_status_and_priority_labels() -> None:
    labels = _catalog_labels()
    names = {label.name for label in labels}
    assert names == {
        "type:bug",
        "type:feature",
        "type:research",
        "type:release",
        "type:task",
        "status:triage",
        "status:ready",
        "status:in-progress",
        "status:blocked",
        "status:closed",
        "priority:p0",
        "priority:p1",
        "priority:p2",
        "priority:p3",
    }
    assert all(label.color and len(label.color) == 6 for label in labels)
    assert all(label.description for label in labels)


def test_catalog_reconciliation_is_idempotent_and_updates_only_reviewed_metadata() -> None:
    labels = _catalog_labels()
    current = _label_rows()
    client = FakeClient(labels=current)
    project_tracking.reconcile_catalog(client, labels)
    assert client.operations == []

    changed = [dict(row) for row in current]
    changed[0]["description"] = "stale"
    changed.pop()
    client = FakeClient(labels=changed)
    project_tracking.reconcile_catalog(client, labels)
    assert client.operations == [
        ("update_label", labels[0].name),
        ("create_label", labels[-1].name),
    ]


def test_missing_lifecycle_label_is_created_before_issue_mutation() -> None:
    labels = _catalog_labels()
    current = [row for row in _label_rows() if row["name"] != "status:triage"]
    client = FakeClient(
        labels=current,
        issue={"number": 41, "state": "open", "labels": [{"name": "type:task"}]},
    )
    project_tracking.process_event(
        client,
        repo="Canticle-AI-Research/Seam",
        event_name="issues",
        payload=_event("opened"),
        catalog=labels,
    )
    assert client.operations == [
        ("create_label", "status:triage"),
        ("get_issue", 41),
        ("add_labels", 41, ("status:triage",)),
    ]


@pytest.mark.parametrize("action", ["opened", "reopened", "closed"])
def test_issue_events_re_read_current_state_and_preserve_unrelated_labels(action: str) -> None:
    labels = _catalog_labels()
    client = FakeClient(
        labels=_label_rows(),
        issue={
            "number": 41,
            "state": "closed",
            "labels": [{"name": "type:bug"}, {"name": "customer-visible"}, {"name": "status:ready"}],
        },
    )
    project_tracking.process_event(
        client,
        repo="Canticle-AI-Research/Seam",
        event_name="issues",
        payload=_event(action),
        catalog=labels,
    )
    assert client.operations == [
        ("get_issue", 41),
        ("add_labels", 41, ("status:closed",)),
        ("remove_label", 41, "status:ready"),
    ]


def test_duplicate_open_event_keeps_maintainer_status_and_is_idempotent() -> None:
    client = FakeClient(
        labels=_label_rows(),
        issue={
            "number": 41,
            "state": "open",
            "labels": [{"name": "status:blocked"}, {"name": "priority:p1"}],
        },
    )
    project_tracking.process_event(
        client,
        repo="Canticle-AI-Research/Seam",
        event_name="issues",
        payload=_event("opened"),
        catalog=_catalog_labels(),
    )
    assert client.operations == [("get_issue", 41)]


def test_reopen_race_uses_live_open_state_and_clears_stale_closed_status() -> None:
    client = FakeClient(
        labels=_label_rows(),
        issue={
            "number": 41,
            "state": "open",
            "labels": [{"name": "status:closed"}, {"name": "needs-design"}],
        },
    )
    project_tracking.process_event(
        client,
        repo="Canticle-AI-Research/Seam",
        event_name="issues",
        payload=_event("closed"),
        catalog=_catalog_labels(),
    )
    assert client.operations == [
        ("get_issue", 41),
        ("add_labels", 41, ("status:triage",)),
        ("remove_label", 41, "status:closed"),
    ]


@pytest.mark.parametrize(
    "event_name,payload",
    [
        ("pull_request", _event("opened")),
        ("issues", _event("edited")),
        ("issues", {"action": "opened", "repository": {"full_name": "other/repo"}, "issue": {}}),
        ("issues", {"action": "opened", "repository": {"full_name": "Canticle-AI-Research/Seam"}, "issue": {"number": "41"}}),
    ],
)
def test_malformed_or_unexpected_events_are_refused(event_name: str, payload: dict[str, Any]) -> None:
    client = FakeClient(labels=_label_rows())
    with pytest.raises(ValueError):
        project_tracking.process_event(
            client,
            repo="Canticle-AI-Research/Seam",
            event_name=event_name,
            payload=payload,
            catalog=_catalog_labels(),
        )
    assert client.operations == []


def test_workflow_dispatch_only_reconciles_catalog() -> None:
    client = FakeClient(labels=_label_rows())
    project_tracking.process_event(
        client,
        repo="Canticle-AI-Research/Seam",
        event_name="workflow_dispatch",
        payload={"repository": {"full_name": "Canticle-AI-Research/Seam"}},
        catalog=_catalog_labels(),
    )
    assert client.operations == []


def test_dry_run_never_invokes_mutating_gh_commands_and_uses_json_stdin() -> None:
    calls: list[tuple[list[str], str | None]] = []

    def runner(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs.get("input")))
        if "/labels?" in " ".join(argv):
            return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(_label_rows()), stderr="")
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps({"number": 41, "state": "open", "labels": []}),
            stderr="",
        )

    client = project_tracking.GhClient("Canticle-AI-Research/Seam", apply=False, runner=runner)
    project_tracking.process_event(
        client,
        repo="Canticle-AI-Research/Seam",
        event_name="issues",
        payload=_event("opened"),
        catalog=_catalog_labels(),
    )
    assert len(calls) == 2
    assert all(call[0][0:2] == ["gh", "api"] for call in calls)
    assert all("--slurp" not in call[0] and "--paginate" not in call[0] for call in calls)
    assert all("--jq" in call[0] for call in calls)
    issue_jq = calls[1][0][calls[1][0].index("--jq") + 1]
    assert "number" in issue_jq and "state" in issue_jq and "labels" in issue_jq
    assert "body" not in issue_jq
    assert all("--method" not in call[0] or call[0][call[0].index("--method") + 1] == "GET" for call in calls)
    assert all(call[1] is None for call in calls)
    assert client.planned == [("POST", "/repos/Canticle-AI-Research/Seam/issues/41/labels")]


def test_apply_uses_argument_lists_and_json_stdin_for_mutations() -> None:
    calls: list[tuple[list[str], str | None]] = []

    def runner(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs.get("input")))
        return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")

    client = project_tracking.GhClient("Canticle-AI-Research/Seam", apply=True, runner=runner)
    client.add_labels(7, ["status:triage"])
    argv, stdin = calls[0]
    assert argv == [
        "gh",
        "api",
        "--method",
        "POST",
        "/repos/Canticle-AI-Research/Seam/issues/7/labels",
        "--input",
        "-",
    ]
    assert json.loads(stdin or "") == {"labels": ["status:triage"]}


def test_label_listing_uses_projected_explicit_pages_until_a_short_page() -> None:
    calls: list[list[str]] = []

    def runner(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        page = 1 if argv[2].endswith("&page=1") else 2
        rows = [
            {"name": f"label-{index}", "color": "ABCDEF", "description": None}
            for index in range(100 if page == 1 else 1)
        ]
        return subprocess.CompletedProcess(argv, 0, stdout=json.dumps(rows), stderr="")

    client = project_tracking.GhClient("Canticle-AI-Research/Seam", runner=runner)
    labels = client.list_labels()
    assert len(labels) == 101
    assert len(calls) == 2
    assert calls[0][2].endswith("per_page=100&page=1")
    assert calls[1][2].endswith("per_page=100&page=2")
    assert all("--slurp" not in argv and "--paginate" not in argv for argv in calls)
    assert all(argv[argv.index("--jq") + 1] == project_tracking.LABEL_PAGE_JQ for argv in calls)


def test_tracking_workflow_has_scoped_permissions_and_trusted_checkout() -> None:
    raw = WORKFLOW_PATH.read_text(encoding="utf-8")
    document = yaml.safe_load(raw)
    assert document["permissions"] == {"contents": "read", "issues": "write"}
    assert set(document[True]) == {"issues", "workflow_dispatch"}
    assert set(document[True]["issues"]["types"]) == {"opened", "reopened", "closed"}
    job = document["jobs"]["reconcile"]
    assert "github.event.issue.number" in job["concurrency"]["group"]
    checkout = next(step for step in job["steps"] if step.get("uses") == "actions/checkout@v4")
    assert checkout["with"]["persist-credentials"] is False
    assert checkout["with"]["ref"] == "${{ github.event.repository.default_branch }}"
    assert "pull_request_target" not in raw
    assert "--apply" in raw

