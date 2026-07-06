from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROTECTED_BRANCH_PREFIXES = (
    "origin/main",
    "origin/HEAD",
    "origin/handoff/archive",
    "origin/backup/",
    "origin/roadmap-",
)

SENSITIVE_TEXT_PATTERNS = (
    re.compile(
        r"https?://[^\s\)\]\}>\"']*(?:claude\.ai|chatgpt\.com|chat\.openai\.com|cursor\.com|/share/|session(?:=|/)|thread(?:=|/))[^\s\)\]\}>\"']*",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:sk-or-v1-|sk-ant-|sk-)[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}\b"),
)


def build_report(
    *,
    prs: list[dict[str, Any]],
    branches: list[dict[str, Any]],
    now: datetime | None = None,
    stale_days: int = 7,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    open_pr_heads = {_head_ref(pr) for pr in prs if _head_ref(pr)}
    open_prs = [_pr_summary(pr, now) for pr in prs]
    stale_prs = [pr for pr in open_prs if pr["idle_days"] >= stale_days]
    stale_branches = []
    for branch in branches:
        name = str(branch.get("name", ""))
        if _is_protected_branch(name):
            continue
        short_name = name.removeprefix("origin/")
        if short_name in open_pr_heads:
            continue
        committed_at = _parse_time(str(branch.get("committed_at", "")))
        idle_days = _age_days(now, committed_at)
        if idle_days >= stale_days:
            stale_branches.append(
                {
                    "name": _safe_text(name),
                    "sha": _safe_text(str(branch.get("sha", ""))),
                    "idle_days": idle_days,
                    "committed_at": _format_time(committed_at),
                }
            )

    status = "ACTION_REQUIRED" if stale_prs or stale_branches else "PASS"
    return {
        "version": "SEAM-GITHUB-MAINTENANCE/1",
        "generated_at": _format_time(now),
        "stale_days": stale_days,
        "status": status,
        "summary": {
            "open_pr_count": len(open_prs),
            "stale_pr_count": len(stale_prs),
            "stale_branch_without_pr_count": len(stale_branches),
        },
        "open_prs": open_prs,
        "stale_prs": stale_prs,
        "stale_branches_without_pr": stale_branches,
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    lines = [
        "# SEAM GitHub Maintenance Report",
        "",
        f"Status: `{report.get('status')}`",
        f"Generated: `{report.get('generated_at')}`",
        f"Stale threshold: `{report.get('stale_days')}d`",
        "",
        "## Summary",
        "",
        f"- Open PRs: {summary.get('open_pr_count', 0)}",
        f"- Stale PRs: {summary.get('stale_pr_count', 0)}",
        f"- Stale branches without PR: {summary.get('stale_branch_without_pr_count', 0)}",
        "",
        "## Open PRs",
        "",
    ]
    open_prs = report.get("open_prs", [])
    if not open_prs:
        lines.append("- None")
    for pr in open_prs:
        lines.append(_format_pr_line(pr))

    lines.extend(["", "## Stale PRs", ""])
    stale_prs = report.get("stale_prs", [])
    if not stale_prs:
        lines.append("- None")
    for pr in stale_prs:
        lines.append(_format_pr_line(pr))

    lines.extend(["", "## Stale Branches Without PR", ""])
    branches = report.get("stale_branches_without_pr", [])
    if not branches:
        lines.append("- None")
    for branch in branches:
        lines.append(
            f"- `{branch['name']}` at `{branch.get('sha')}` - last commit {branch['idle_days']}d ago"
        )
    lines.append("")
    return "\n".join(lines)


def fetch_open_prs(repo: str, token: str) -> list[dict[str, Any]]:
    url = f"https://api.github.com/repos/{repo}/pulls?state=open&per_page=100"
    prs: list[dict[str, Any]] = []
    while url:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            prs.extend(json.loads(response.read().decode("utf-8")))
            url = _next_link(response.headers.get("Link", ""))
    return prs


def list_remote_branches() -> list[dict[str, Any]]:
    subprocess.run(["git", "fetch", "--prune", "--all"], check=True)
    completed = subprocess.run(
        [
            "git",
            "for-each-ref",
            "refs/remotes/origin",
            "--format=%(refname:short)\t%(objectname:short)\t%(committerdate:iso8601-strict)",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    branches = []
    for line in completed.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        branches.append({"name": parts[0], "sha": parts[1], "committed_at": parts[2]})
    return branches


def resolve_github_token() -> str:
    """Resolve a GitHub API token without printing or persisting it.

    CI provides GITHUB_TOKEN/GH_TOKEN as environment variables. Local operator
    shells often only have `gh auth login`, which stores the token in the OS
    keyring. In that case, ask gh for the token and keep it process-local.
    """
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        return token
    try:
        completed = subprocess.run(
            ["gh", "auth", "token"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return ""
    return completed.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a SEAM GitHub maintenance report")
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "BlackhatShiftey/Seam"))
    parser.add_argument("--stale-days", type=int, default=7)
    parser.add_argument("--output", default="github-maintenance-report.md")
    parser.add_argument("--json-output", default="github-maintenance-report.json")
    args = parser.parse_args(argv)

    token = resolve_github_token()
    if not token:
        raise SystemExit(
            "GITHUB_TOKEN, GH_TOKEN, or a logged-in GitHub CLI is required to fetch pull requests"
        )
    report = build_report(
        prs=fetch_open_prs(args.repo, token),
        branches=list_remote_branches(),
        stale_days=args.stale_days,
    )
    Path(args.output).write_text(render_markdown(report), encoding="utf-8")
    Path(args.json_output).write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(render_markdown(report))
    return 0


def _pr_summary(pr: dict[str, Any], now: datetime) -> dict[str, Any]:
    updated_at = _parse_time(str(pr.get("updated_at", "")))
    created_at = _parse_time(str(pr.get("created_at", "")))
    return {
        "number": pr.get("number"),
        "title": _safe_text(str(pr.get("title", ""))),
        "url": _safe_text(str(pr.get("html_url", ""))),
        "draft": bool(pr.get("draft")),
        "head_ref": _safe_text(_head_ref(pr)),
        "created_at": _format_time(created_at),
        "updated_at": _format_time(updated_at),
        "age_days": _age_days(now, created_at),
        "idle_days": _age_days(now, updated_at),
    }


def _head_ref(pr: dict[str, Any]) -> str:
    head = pr.get("head")
    return str(head.get("ref", "")) if isinstance(head, dict) else ""


def _is_protected_branch(name: str) -> bool:
    return any(name == prefix or name.startswith(prefix) for prefix in PROTECTED_BRANCH_PREFIXES)


def _format_pr_line(pr: dict[str, Any]) -> str:
    draft = " draft" if pr.get("draft") else ""
    return (
        f"- #{pr['number']}{draft}: {pr['title']} "
        f"({pr['url']}) - updated {pr['idle_days']}d ago, head `{pr['head_ref']}`"
    )


def _safe_text(value: str) -> str:
    safe = value
    for pattern in SENSITIVE_TEXT_PATTERNS:
        safe = pattern.sub("<redacted-session-url>", safe)
    return safe


def _parse_time(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _age_days(now: datetime, then: datetime) -> int:
    return max(0, int((now - then).total_seconds() // 86400))


def _next_link(link_header: str) -> str:
    for part in link_header.split(","):
        section = part.strip()
        if 'rel="next"' not in section:
            continue
        if section.startswith("<") and ">" in section:
            return section[1:section.index(">")]
    return ""


if __name__ == "__main__":
    raise SystemExit(main())
