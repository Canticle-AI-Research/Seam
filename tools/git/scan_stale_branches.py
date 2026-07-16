"""Scan local + remote git branches and classify them by safety-to-delete.

Output is advisory. The operator decides what to delete. Run on-demand:

    python -m tools.git.scan_stale_branches
    python -m tools.git.scan_stale_branches --local-only
    python -m tools.git.scan_stale_branches --stale-days 30

Classes the scanner reports:

  on-main           0 unique commits vs main; work is fully merged. Safe to delete.
  merged-pr         backing branch of a MERGED or CLOSED PR. Safe to delete.
  unique-and-stale  unique commits, no PR, last commit > N days ago. REVIEW before deletion.
  unique-and-fresh  unique commits, < N days. Active work.
  open-pr           backing branch of an OPEN or DRAFT PR. Keep.
  protected         in the allowlist (handoff/archive, backup/*, roadmap-*). Keep.

The scanner never deletes anything. It just prints recommendations.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

PROTECTED_PATTERNS: tuple[str, ...] = (
    "main",
    "master",
    "handoff/archive",
    "backup/",
    "roadmap-",
)

DEFAULT_STALE_DAYS = 14


@dataclass
class BranchInfo:
    name: str
    is_remote: bool
    unique_commits: int
    last_commit_date: datetime
    last_commit_sha: str
    pr_state: str | None = None
    pr_number: int | None = None


def _run(*args: str) -> str:
    result = subprocess.run(args, capture_output=True, text=True, check=False)
    return result.stdout.strip()


def list_branches(include_remote: bool) -> list[BranchInfo]:
    refs: list[str] = []
    refs.extend(_run("git", "for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines())
    if include_remote:
        for ref in _run("git", "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin").splitlines():
            if ref in ("origin", "origin/HEAD", "origin/main"):
                continue
            refs.append(ref)

    branches: list[BranchInfo] = []
    for ref in refs:
        if ref == "main":
            continue
        unique = int(_run("git", "rev-list", "--count", f"main..{ref}") or "0")
        date_str = _run("git", "log", "-1", "--format=%cI", ref)
        sha = _run("git", "log", "-1", "--format=%H", ref)
        if not date_str or not sha:
            continue
        branches.append(
            BranchInfo(
                name=ref,
                is_remote=ref.startswith("origin/"),
                unique_commits=unique,
                last_commit_date=datetime.fromisoformat(date_str),
                last_commit_sha=sha,
            )
        )
    return branches


def annotate_with_prs(branches: list[BranchInfo]) -> None:
    try:
        out = _run("gh", "pr", "list", "--state", "all", "--limit", "200",
                   "--json", "headRefName,state,number")
    except FileNotFoundError:
        return
    if not out:
        return
    try:
        prs = json.loads(out)
    except json.JSONDecodeError:
        return

    pr_by_branch: dict[str, tuple[str, int]] = {}
    for pr in prs:
        head = pr.get("headRefName")
        state = pr.get("state")
        number = pr.get("number")
        if head and state and head not in pr_by_branch:
            pr_by_branch[head] = (state, number)

    for branch in branches:
        bare = branch.name[len("origin/"):] if branch.is_remote else branch.name
        entry = pr_by_branch.get(bare)
        if entry:
            branch.pr_state, branch.pr_number = entry


def classify(branch: BranchInfo, stale_days: int) -> str:
    bare = branch.name[len("origin/"):] if branch.is_remote else branch.name

    for pattern in PROTECTED_PATTERNS:
        if bare == pattern or bare.startswith(pattern):
            return "protected"

    if branch.pr_state in ("OPEN", "DRAFT"):
        return "open-pr"
    if branch.pr_state in ("MERGED", "CLOSED"):
        return "merged-pr"

    if branch.unique_commits == 0:
        return "on-main"

    age = datetime.now(timezone.utc) - branch.last_commit_date
    if age > timedelta(days=stale_days):
        return "unique-and-stale"
    return "unique-and-fresh"


CLASS_ORDER = ("on-main", "merged-pr", "unique-and-stale", "unique-and-fresh", "open-pr", "protected")

CLASS_ACTION = {
    "on-main": "DELETE  — 0 unique commits vs main, work is fully merged",
    "merged-pr": "DELETE  — backing branch of a merged or closed PR",
    "unique-and-stale": "REVIEW  — unique commits, no open PR, stale (> {days} days)",
    "unique-and-fresh": "LEAVE   — unique commits, recent activity",
    "open-pr": "KEEP    — backing branch of an open or draft PR",
    "protected": "KEEP    — protected allowlist (handoff/archive, backup/*, roadmap-*)",
}


def format_branch(branch: BranchInfo) -> str:
    age_days = (datetime.now(timezone.utc) - branch.last_commit_date).days
    pr_tag = f" PR#{branch.pr_number}/{branch.pr_state}" if branch.pr_number else ""
    return f"  {branch.name}  ({branch.unique_commits} unique, {age_days}d old, {branch.last_commit_sha[:8]}{pr_tag})"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else "")
    parser.add_argument("--local-only", action="store_true", help="Skip remote branches")
    parser.add_argument("--stale-days", type=int, default=DEFAULT_STALE_DAYS,
                        help=f"Days of inactivity to flag unique-and-stale (default {DEFAULT_STALE_DAYS})")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of report")
    args = parser.parse_args()

    branches = list_branches(include_remote=not args.local_only)
    annotate_with_prs(branches)

    by_class: dict[str, list[BranchInfo]] = {}
    for branch in branches:
        cls = classify(branch, args.stale_days)
        by_class.setdefault(cls, []).append(branch)

    if args.json:
        payload = {
            cls: [
                {
                    "name": b.name,
                    "unique_commits": b.unique_commits,
                    "age_days": (datetime.now(timezone.utc) - b.last_commit_date).days,
                    "sha": b.last_commit_sha,
                    "pr_state": b.pr_state,
                    "pr_number": b.pr_number,
                }
                for b in sorted(by_class.get(cls, []), key=lambda x: x.last_commit_date)
            ]
            for cls in CLASS_ORDER
        }
        print(json.dumps(payload, indent=2))
        return

    print(f"Stale-branch scan (threshold: {args.stale_days} days)")
    print()
    total = 0
    for cls in CLASS_ORDER:
        items = sorted(by_class.get(cls, []), key=lambda b: b.last_commit_date)
        if not items:
            continue
        action = CLASS_ACTION[cls].format(days=args.stale_days)
        print(f"== {cls.upper()} ({len(items)})  {action}")
        for branch in items:
            print(format_branch(branch))
        print()
        total += len(items)
    print(f"Scanned {total} branches.")


if __name__ == "__main__":
    main()
