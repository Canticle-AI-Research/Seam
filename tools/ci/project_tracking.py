"""Reconcile SEAM's repository-native project tracking labels and issue state."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import quote

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CATALOG = REPO_ROOT / ".github" / "project-tracking-labels.json"
REPO_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
ALLOWED_ACTIONS = {"opened", "reopened", "closed"}
OPEN_STATUS_PRECEDENCE = ("status:blocked", "status:in-progress", "status:ready")
MAX_EVENT_BYTES = 1024 * 1024
MAX_CATALOG_BYTES = 64 * 1024
LABEL_PAGE_SIZE = 100
MAX_LABEL_PAGES = 100
LABEL_PAGE_JQ = "[.[] | {name, color, description}]"
ISSUE_JQ = "{number, state, labels: [.labels[] | {name}]}"


@dataclass(frozen=True)
class CatalogLabel:
    name: str
    color: str
    description: str


class TrackingClient(Protocol):
    def list_labels(self) -> list[dict[str, Any]]: ...

    def get_issue(self, number: int) -> dict[str, Any]: ...

    def create_label(self, label: CatalogLabel) -> None: ...

    def update_label(self, label: CatalogLabel) -> None: ...

    def add_labels(self, number: int, labels: list[str]) -> None: ...

    def remove_label(self, number: int, label: str) -> None: ...


Runner = Callable[..., subprocess.CompletedProcess[str]]


class GhClient:
    """Small gh-api adapter that sends mutation payloads through JSON stdin."""

    def __init__(self, repo: str, *, apply: bool = False, runner: Runner = subprocess.run) -> None:
        self.repo = _validate_repo(repo)
        self.apply = apply
        self.runner = runner
        self.planned: list[tuple[str, str]] = []

    def _get(self, path: str, *, jq: str) -> Any:
        argv = ["gh", "api", path, "--jq", jq]
        completed = self.runner(argv, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            raise RuntimeError(f"GitHub read failed for {path} (exit {completed.returncode})")
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"GitHub returned invalid JSON for {path}") from exc

    def _mutate(self, method: str, path: str, payload: dict[str, Any] | None = None) -> None:
        self.planned.append((method, path))
        if not self.apply:
            return
        argv = ["gh", "api", "--method", method, path]
        input_value = None
        if payload is not None:
            argv.extend(["--input", "-"])
            input_value = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        completed = self.runner(
            argv,
            check=False,
            capture_output=True,
            text=True,
            input=input_value,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"GitHub mutation failed for {method} {path} (exit {completed.returncode})")

    def list_labels(self) -> list[dict[str, Any]]:
        labels: list[dict[str, Any]] = []
        for page_number in range(1, MAX_LABEL_PAGES + 1):
            path = (
                f"/repos/{self.repo}/labels?per_page={LABEL_PAGE_SIZE}"
                f"&page={page_number}"
            )
            page = self._get(path, jq=LABEL_PAGE_JQ)
            if not isinstance(page, list):
                raise ValueError("GitHub label page must be a list")
            labels.extend(page)
            if len(page) < LABEL_PAGE_SIZE:
                return labels
        raise ValueError(f"GitHub label listing exceeded {MAX_LABEL_PAGES} pages")

    def get_issue(self, number: int) -> dict[str, Any]:
        value = self._get(f"/repos/{self.repo}/issues/{number}", jq=ISSUE_JQ)
        if not isinstance(value, dict):
            raise ValueError("GitHub issue response must be an object")
        return value

    def create_label(self, label: CatalogLabel) -> None:
        self._mutate(
            "POST",
            f"/repos/{self.repo}/labels",
            {"name": label.name, "color": label.color, "description": label.description},
        )

    def update_label(self, label: CatalogLabel) -> None:
        self._mutate(
            "PATCH",
            f"/repos/{self.repo}/labels/{quote(label.name, safe='')}",
            {"color": label.color, "description": label.description},
        )

    def add_labels(self, number: int, labels: list[str]) -> None:
        self._mutate(
            "POST",
            f"/repos/{self.repo}/issues/{number}/labels",
            {"labels": labels},
        )

    def remove_label(self, number: int, label: str) -> None:
        self._mutate(
            "DELETE",
            f"/repos/{self.repo}/issues/{number}/labels/{quote(label, safe='')}",
        )


def _validate_repo(repo: str) -> str:
    if not REPO_PATTERN.fullmatch(repo):
        raise ValueError("repository must use the owner/name form")
    if any(part in {".", ".."} for part in repo.split("/")):
        raise ValueError("repository segments cannot be dot paths")
    return repo


def _read_json(path: Path, *, max_bytes: int) -> Any:
    if not path.is_file() or path.stat().st_size > max_bytes:
        raise ValueError(f"JSON input is missing or exceeds {max_bytes} bytes: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON input: {path}") from exc


def load_catalog(path: Path = DEFAULT_CATALOG) -> tuple[CatalogLabel, ...]:
    value = _read_json(path, max_bytes=MAX_CATALOG_BYTES)
    if not isinstance(value, dict) or value.get("schema") != "seam-project-tracking-labels/v1":
        raise ValueError("unsupported project-tracking label catalog")
    rows = value.get("labels")
    if not isinstance(rows, list) or not rows:
        raise ValueError("project-tracking label catalog must contain labels")
    labels: list[CatalogLabel] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each catalog label must be an object")
        name = row.get("name")
        color = row.get("color")
        description = row.get("description")
        if not isinstance(name, str) or not name or name in seen:
            raise ValueError("catalog label names must be unique non-empty strings")
        if not isinstance(color, str) or re.fullmatch(r"[0-9A-Fa-f]{6}", color) is None:
            raise ValueError(f"catalog label {name} has an invalid color")
        if not isinstance(description, str) or not description.strip():
            raise ValueError(f"catalog label {name} needs a description")
        if not name.startswith(("type:", "status:", "priority:")):
            raise ValueError(f"catalog label {name} is outside the managed namespaces")
        seen.add(name)
        labels.append(CatalogLabel(name=name, color=color.upper(), description=description.strip()))
    return tuple(labels)


def reconcile_catalog(client: TrackingClient, catalog: tuple[CatalogLabel, ...]) -> None:
    current_rows = client.list_labels()
    if not isinstance(current_rows, list):
        raise ValueError("GitHub labels must be a list")
    current: dict[str, dict[str, Any]] = {}
    for row in current_rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise ValueError("GitHub label rows must contain a string name")
        current[row["name"]] = row
    for label in catalog:
        existing = current.get(label.name)
        if existing is None:
            client.create_label(label)
            continue
        color = existing.get("color")
        description = existing.get("description")
        if not isinstance(color, str) or description is not None and not isinstance(description, str):
            raise ValueError(f"GitHub label metadata is malformed for {label.name}")
        if color.upper() != label.color or description != label.description:
            client.update_label(label)


def _validate_event(repo: str, event_name: str, payload: dict[str, Any]) -> tuple[str | None, int | None]:
    repo = _validate_repo(repo)
    if not isinstance(payload, dict):
        raise ValueError("event payload must be an object")
    repository = payload.get("repository")
    if not isinstance(repository, dict) or repository.get("full_name") != repo:
        raise ValueError("event repository does not match --repo")
    if event_name == "workflow_dispatch":
        return None, None
    if event_name != "issues":
        raise ValueError(f"unexpected event type: {event_name}")
    action = payload.get("action")
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"unexpected issue action: {action}")
    issue = payload.get("issue")
    if not isinstance(issue, dict):
        raise ValueError("issue event is missing its issue object")
    number = issue.get("number")
    if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
        raise ValueError("issue number must be a positive integer")
    if issue.get("state") not in {"open", "closed"} or not isinstance(issue.get("labels"), list):
        raise ValueError("issue event contains malformed state or labels")
    return action, number


def _live_issue(value: dict[str, Any], expected_number: int) -> tuple[str, set[str]]:
    number = value.get("number")
    state = value.get("state")
    rows = value.get("labels")
    if number != expected_number or state not in {"open", "closed"} or not isinstance(rows, list):
        raise ValueError("live issue response contains malformed identity, state, or labels")
    names: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise ValueError("live issue response contains a malformed label")
        names.add(row["name"])
    return state, names


def _desired_status(state: str, current: set[str]) -> str:
    if state == "closed":
        return "status:closed"
    return next((name for name in OPEN_STATUS_PRECEDENCE if name in current), "status:triage")


def process_event(
    client: TrackingClient,
    *,
    repo: str,
    event_name: str,
    payload: dict[str, Any],
    catalog: tuple[CatalogLabel, ...],
) -> None:
    _, number = _validate_event(repo, event_name, payload)
    reconcile_catalog(client, catalog)
    if number is None:
        return
    state, current = _live_issue(client.get_issue(number), number)
    managed_statuses = {label.name for label in catalog if label.name.startswith("status:")}
    desired = _desired_status(state, current)
    if desired not in managed_statuses:
        raise ValueError(f"catalog is missing required lifecycle label {desired}")
    if desired not in current:
        client.add_labels(number, [desired])
    for stale in sorted((current & managed_statuses) - {desired}):
        client.remove_label(number, stale)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reconcile SEAM repository project tracking")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--event-name", required=True)
    parser.add_argument("--event-path", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--apply", action="store_true", help="apply planned GitHub label mutations")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = _read_json(args.event_path, max_bytes=MAX_EVENT_BYTES)
        catalog = load_catalog(args.catalog)
        client = GhClient(args.repo, apply=args.apply)
        process_event(
            client,
            repo=args.repo,
            event_name=args.event_name,
            payload=payload,
            catalog=catalog,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"project tracking failed: {type(exc).__name__}: {exc}")
        return 1
    mode = "applied" if args.apply else "planned"
    print(f"project tracking {mode} {len(client.planned)} mutation(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
