"""Fail-closed pull-request lifecycle gate backed exclusively by the GitHub CLI."""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

POLICY_PATH = ".github/pr-lifecycle-policy.json"
POLICY_VERSION = "seam-pr-lifecycle-policy/1"
SHA = re.compile(r"^[0-9a-f]{40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class LifecycleError(RuntimeError):
    """GitHub state or protected policy cannot be trusted."""


def _gh_json(args: list[str]) -> object:
    completed = _gh(args)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise LifecycleError("GitHub CLI returned malformed JSON") from exc


def _gh_paginated(args: list[str]) -> list[object]:
    """Decode every JSON document emitted by gh 2.46 ``--paginate``.

    Older gh versions do not provide ``--slurp`` and print one complete JSON
    value per page. ``raw_decode`` accepts both newline-delimited and directly
    concatenated values without treating partial or trailing data as success.
    """

    completed = _gh(args)
    decoder = json.JSONDecoder()
    values: list[object] = []
    position = 0
    text = completed.stdout
    while position < len(text):
        while position < len(text) and text[position].isspace():
            position += 1
        if position == len(text):
            break
        try:
            value, position = decoder.raw_decode(text, position)
        except json.JSONDecodeError as exc:
            raise LifecycleError("GitHub CLI returned malformed paginated JSON") from exc
        values.append(value)
    if not values:
        raise LifecycleError("GitHub CLI returned no paginated JSON")
    return values


def _gh(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            ["gh", *args], capture_output=True, text=True, timeout=30, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise LifecycleError(f"GitHub CLI unavailable: {exc}") from exc
    if completed.returncode:
        detail = completed.stderr.strip() or f"exit {completed.returncode}"
        raise LifecycleError(f"gh {' '.join(args[:3])} failed: {detail}")
    return completed


def _authenticate() -> None:
    _gh(["auth", "status", "--hostname", "github.com"])


def _protected_policy(repository: str) -> tuple[str, dict[str, Any]]:
    ref = _gh_json(["api", "--method", "GET", f"repos/{repository}/git/ref/heads/main"])
    if not isinstance(ref, dict) or not isinstance(ref.get("object"), dict):
        raise LifecycleError("protected main ref response is incomplete")
    commit = ref["object"].get("sha")
    if not isinstance(commit, str) or not SHA.fullmatch(commit):
        raise LifecycleError("protected main ref has an invalid commit identity")
    try:
        content = _gh_json(
            ["api", "--method", "GET", f"repos/{repository}/contents/{POLICY_PATH}?ref={commit}"]
        )
    except LifecycleError as exc:
        if "404" not in str(exc):
            raise
        # The first PR introducing this policy cannot read it from protected
        # main yet. The only bootstrap is deliberately stricter: cap one,
        # with no exceptions. Every other transport or parse failure remains fatal.
        return commit, {
            "version": POLICY_VERSION,
            "repository": repository,
            "max_active_prs": 1,
            "blocked_exceptions": [],
        }
    if not isinstance(content, dict) or content.get("type") != "file" or content.get("encoding") != "base64":
        raise LifecycleError("protected-main lifecycle policy response is incomplete")
    try:
        encoded = "".join(str(content["content"]).split())
        raw = base64.b64decode(encoded, validate=True)
        policy = json.loads(raw)
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        raise LifecycleError("protected-main lifecycle policy is malformed") from exc
    if not isinstance(policy, dict):
        raise LifecycleError("protected-main lifecycle policy must be an object")
    _validate_policy(policy, repository)
    return commit, policy


def _validate_policy(policy: dict[str, Any], repository: str) -> None:
    required = {"version", "repository", "max_active_prs", "blocked_exceptions"}
    if set(policy) != required or policy.get("version") != POLICY_VERSION:
        raise LifecycleError("protected-main lifecycle policy fields are invalid")
    if policy.get("repository") != repository:
        raise LifecycleError("policy repository does not match requested repository")
    maximum = policy.get("max_active_prs")
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum != 1:
        raise LifecycleError("policy max_active_prs must be exactly 1")
    if not isinstance(policy.get("blocked_exceptions"), list):
        raise LifecycleError("policy blocked_exceptions must be an array")


def _open_prs(repository: str) -> list[dict[str, Any]]:
    pages = _gh_paginated(
        [
            "api",
            "--method",
            "GET",
            f"repos/{repository}/pulls?state=open&per_page=100",
            "--paginate",
        ]
    )
    if not isinstance(pages, list) or not all(isinstance(page, list) for page in pages):
        raise LifecycleError("paginated pull request response is malformed")
    prs = [item for page in pages for item in page]
    if not all(isinstance(item, dict) for item in prs):
        raise LifecycleError("paginated pull request response contains a malformed item")
    numbers = [item.get("number") for item in prs]
    if any(isinstance(n, bool) or not isinstance(n, int) for n in numbers) or len(set(numbers)) != len(numbers):
        raise LifecycleError("paginated pull request response has invalid identities")
    for pr in prs:
        head = pr.get("head")
        base = pr.get("base")
        if (
            pr.get("state") != "open"
            or not isinstance(pr.get("draft"), bool)
            or not isinstance(head, dict)
            or not isinstance(head.get("sha"), str)
            or not SHA.fullmatch(head["sha"])
            or not isinstance(head.get("ref"), str)
            or not head["ref"]
            or not isinstance(head.get("repo"), dict)
            or not isinstance(head["repo"].get("full_name"), str)
            or not REPOSITORY.fullmatch(head["repo"]["full_name"])
            or not isinstance(base, dict)
            or not isinstance(base.get("ref"), str)
            or not base["ref"]
            or not isinstance(base.get("repo"), dict)
            or base["repo"].get("full_name") != repository
        ):
            raise LifecycleError("open pull request response has incomplete or mismatched identity")
    return prs


def _parse_expiry(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise LifecycleError("exception expiry must be an RFC 3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise LifecycleError("exception expiry must be an RFC 3339 UTC timestamp") from exc
    return parsed


def _validated_exceptions(
    repository: str,
    prs: list[dict[str, Any]],
    policy: dict[str, Any],
    *,
    now: datetime,
) -> list[int]:
    by_number = {pr["number"]: pr for pr in prs}
    accepted: list[int] = []
    seen: set[int] = set()
    fields = {
        "repository", "pull_request", "head_sha", "blocker_issue", "owner", "condition", "expires_at"
    }
    for value in policy["blocked_exceptions"]:
        if not isinstance(value, dict) or set(value) != fields:
            raise LifecycleError("blocked exception fields are invalid")
        number = value.get("pull_request")
        label = f"exception for PR #{number}"
        if value.get("repository") != repository:
            raise LifecycleError(f"{label} repository does not match")
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise LifecycleError(f"{label} pull request identity is invalid")
        if number in seen:
            raise LifecycleError(f"{label} is duplicated")
        seen.add(number)
        expected_sha = value.get("head_sha")
        if not isinstance(expected_sha, str) or not SHA.fullmatch(expected_sha):
            raise LifecycleError(f"{label} head SHA is invalid")
        owner = value.get("owner")
        condition = value.get("condition")
        if not isinstance(owner, str) or not owner.strip() or not isinstance(condition, str) or not condition.strip():
            raise LifecycleError(f"{label} requires an owner and concrete condition")
        expiry = _parse_expiry(value.get("expires_at"))
        issue_number = value.get("blocker_issue")
        if isinstance(issue_number, bool) or not isinstance(issue_number, int) or issue_number < 1:
            raise LifecycleError(f"{label} blocker issue is invalid")
        if number not in by_number:
            continue
        pr_head = by_number[number].get("head")
        actual_sha = pr_head.get("sha") if isinstance(pr_head, dict) else None
        if expected_sha != actual_sha or not isinstance(actual_sha, str) or not SHA.fullmatch(actual_sha):
            raise LifecycleError(f"{label} head SHA does not match the live pull request")
        if expiry <= now:
            raise LifecycleError(f"{label} has expired")
        issue = _gh_json(["api", "--method", "GET", f"repos/{repository}/issues/{issue_number}"])
        if not isinstance(issue, dict) or issue.get("state") != "open" or issue.get("pull_request"):
            raise LifecycleError(f"{label} blocker issue is not an open issue")
        accepted.append(number)
    return accepted


def evaluate(repository: str) -> dict[str, Any]:
    if not REPOSITORY.fullmatch(repository):
        raise LifecycleError("repository must be explicit owner/name")
    _authenticate()
    policy_commit, policy = _protected_policy(repository)
    prs = _open_prs(repository)
    exceptions = _validated_exceptions(
        repository, prs, policy, now=datetime.now(timezone.utc)
    )
    ordinary = len(prs) - len(exceptions)
    cap = policy["max_active_prs"]
    result = {
        "version": "seam-pr-lifecycle-result/1",
        "repository": repository,
        "policy_commit": policy_commit,
        "active_pr_count": len(prs),
        "ordinary_pr_count": ordinary,
        "max_active_prs": cap,
        "exception_prs": sorted(exceptions),
        "status": "PASS" if ordinary <= cap else "FAIL",
    }
    if ordinary > cap:
        raise LifecycleError(f"{len(prs)} active pull requests exceeds cap {cap}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enforce protected-main PR lifecycle policy")
    parser.add_argument("--repo", required=True, help="exact GitHub owner/name")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = evaluate(args.repo)
    except LifecycleError as exc:
        print(f"PR lifecycle FAILED: {exc}", file=sys.stderr)
        return 1 if "exceeds cap" in str(exc) or "exception for PR" in str(exc) else 2
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(
            f"PR lifecycle PASS: {result['active_pr_count']} active, "
            f"{len(result['exception_prs'])} protected exception(s)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
