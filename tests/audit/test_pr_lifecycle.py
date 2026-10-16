from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _fake_gh(tmp_path: Path, responses: dict[str, object]) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    script = bin_dir / "gh"
    script.write_text(
        """#!/usr/bin/env python3
import json, os, sys
responses = json.loads(os.environ["FAKE_GH_RESPONSES"])
key = " ".join(sys.argv[1:])
item = responses.get(key)
if item is None:
    print(f"unexpected gh invocation: {key}", file=sys.stderr)
    raise SystemExit(97)
if isinstance(item, dict) and "exit" in item:
    print(item.get("stderr", ""), file=sys.stderr)
    raise SystemExit(item["exit"])
if isinstance(item, dict) and "raw" in item:
    print(item["raw"])
    raise SystemExit(0)
if isinstance(item, dict) and "pages" in item:
    for page in item["pages"]:
        print(json.dumps(page))
    raise SystemExit(0)
print(json.dumps(item))
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["FAKE_GH_RESPONSES"] = json.dumps(responses)
    return env


def _run(tmp_path: Path, responses: dict[str, object], *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tools.ci.pr_lifecycle", "--repo", "acme/widget", *extra],
        cwd=REPO_ROOT,
        env=_fake_gh(tmp_path, responses),
        text=True,
        capture_output=True,
        timeout=10,
    )


def _responses(*, prs: list[dict], policy: dict, issues: dict[int, dict] | None = None):
    encoded = __import__("base64").b64encode(json.dumps(policy).encode()).decode()
    values: dict[str, object] = {
        "auth status --hostname github.com": {"raw": "authenticated"},
        "api --method GET repos/acme/widget/git/ref/heads/main": {"object": {"sha": "a" * 40}},
        (
            "api --method GET repos/acme/widget/contents/.github/pr-lifecycle-policy.json"
            f"?ref={'a' * 40}"
        ): {"type": "file", "encoding": "base64", "content": encoded},
        "api --method GET repos/acme/widget/pulls?state=open&per_page=100 --paginate": {"pages": [prs]},
    }
    for number, issue in (issues or {}).items():
        values[f"api --method GET repos/acme/widget/issues/{number}"] = issue
    return values


def _policy(*exceptions: dict) -> dict:
    return {
        "version": "seam-pr-lifecycle-policy/1",
        "repository": "acme/widget",
        "max_active_prs": 1,
        "blocked_exceptions": list(exceptions),
    }


def _pr(
    number: int,
    head: str,
    *,
    draft: bool = False,
    head_repo: str = "acme/widget",
    base_ref: str = "main",
) -> dict:
    return {
        "number": number,
        "draft": draft,
        "state": "open",
        "head": {
            "sha": head,
            "ref": f"change-{number}",
            "repo": {"full_name": head_repo},
        },
        "base": {"ref": base_ref, "repo": {"full_name": "acme/widget"}},
    }


def test_lifecycle_counts_drafts_and_all_paginated_open_prs(tmp_path: Path) -> None:
    responses = _responses(prs=[_pr(1, "1" * 40), _pr(2, "2" * 40, draft=True)], policy=_policy())

    result = _run(tmp_path, responses)

    assert result.returncode == 1
    assert "2 active pull requests exceeds cap 1" in result.stderr


def test_lifecycle_rejects_incomplete_live_pr_records(tmp_path: Path) -> None:
    result = _run(tmp_path, _responses(prs=[{"number": 1}], policy=_policy()))

    assert result.returncode == 2
    assert "pull request response" in result.stderr


def test_lifecycle_rejects_policy_that_expands_the_cap(tmp_path: Path) -> None:
    policy = _policy()
    policy["max_active_prs"] = 2

    result = _run(tmp_path, _responses(prs=[], policy=policy))

    assert result.returncode == 2
    assert "max_active_prs" in result.stderr


def test_lifecycle_counts_fork_and_stacked_prs_toward_the_cap(tmp_path: Path) -> None:
    prs = [
        _pr(1, "1" * 40, head_repo="contributor/widget"),
        _pr(2, "2" * 40, base_ref="feature-stack"),
    ]

    result = _run(tmp_path, _responses(prs=prs, policy=_policy()))

    assert result.returncode == 1
    assert "2 active pull requests exceeds cap 1" in result.stderr


def test_lifecycle_accepts_single_valid_fork_or_stacked_inventory(tmp_path: Path) -> None:
    fork = _run(
        tmp_path / "fork",
        _responses(
            prs=[_pr(1, "1" * 40, head_repo="contributor/widget")],
            policy=_policy(),
        ),
    )
    stacked = _run(
        tmp_path / "stacked",
        _responses(
            prs=[_pr(1, "1" * 40, base_ref="feature-stack")], policy=_policy()
        ),
    )

    assert fork.returncode == 0, fork.stderr
    assert stacked.returncode == 0, stacked.stderr


def test_lifecycle_accepts_only_exact_head_bound_unexpired_blocker_exception(tmp_path: Path) -> None:
    exception = {
        "repository": "acme/widget",
        "pull_request": 2,
        "head_sha": "2" * 40,
        "blocker_issue": 91,
        "owner": "release-owner",
        "condition": "close after upstream release is published",
        "expires_at": "2099-01-01T00:00:00Z",
    }
    responses = _responses(
        prs=[_pr(1, "1" * 40), _pr(2, "2" * 40, draft=True)],
        policy=_policy(exception),
        issues={91: {"number": 91, "state": "open", "pull_request": None}},
    )

    result = _run(tmp_path, responses, "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["active_pr_count"] == 2
    assert payload["exception_prs"] == [2]
    assert payload["policy_commit"] == "a" * 40


def _exception(*, expires_at: str = "2099-01-01T00:00:00Z") -> dict:
    return {
        "repository": "acme/widget",
        "pull_request": 2,
        "head_sha": "2" * 40,
        "blocker_issue": 91,
        "owner": "release-owner",
        "condition": "close after upstream release is published",
        "expires_at": expires_at,
    }


def test_lifecycle_admits_policy_change_while_exception_pr_is_closed(tmp_path: Path) -> None:
    responses = _responses(prs=[_pr(1, "1" * 40)], policy=_policy(_exception()))

    result = _run(tmp_path, responses, "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["active_pr_count"] == 1
    assert payload["ordinary_pr_count"] == 1
    assert payload["exception_prs"] == []


def test_lifecycle_treats_closed_or_expired_dormant_exception_as_nonblocking(
    tmp_path: Path,
) -> None:
    responses = _responses(
        prs=[], policy=_policy(_exception(expires_at="2020-01-01T00:00:00Z"))
    )

    result = _run(tmp_path, responses, "--json")

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["exception_prs"] == []


def test_lifecycle_reopened_exception_requires_exact_head_and_live_blocker(tmp_path: Path) -> None:
    responses = _responses(
        prs=[_pr(1, "1" * 40), _pr(2, "2" * 40)],
        policy=_policy(_exception()),
        issues={91: {"number": 91, "state": "open", "pull_request": None}},
    )

    accepted = _run(tmp_path / "accepted", responses, "--json")
    assert accepted.returncode == 0, accepted.stderr
    assert json.loads(accepted.stdout)["exception_prs"] == [2]

    changed = _responses(
        prs=[_pr(1, "1" * 40), _pr(2, "9" * 40)],
        policy=_policy(_exception()),
        issues={91: {"number": 91, "state": "open", "pull_request": None}},
    )
    rejected = _run(tmp_path / "changed", changed)
    assert rejected.returncode == 1
    assert "head SHA" in rejected.stderr


def test_lifecycle_validates_dormant_exception_identity_and_schema(tmp_path: Path) -> None:
    invalid = _exception()
    invalid["pull_request"] = 0
    invalid["head_sha"] = "short"

    result = _run(tmp_path, _responses(prs=[], policy=_policy(invalid)))

    assert result.returncode == 1
    assert "exception for PR" in result.stderr


def test_lifecycle_rejects_self_exemption_wrong_head_expiry_and_closed_blocker(tmp_path: Path) -> None:
    base = {
        "repository": "acme/widget",
        "pull_request": 2,
        "head_sha": "9" * 40,
        "blocker_issue": 91,
        "owner": "release-owner",
        "condition": "wait for upstream",
        "expires_at": "2020-01-01T00:00:00Z",
    }
    responses = _responses(
        prs=[_pr(1, "1" * 40), _pr(2, "2" * 40)],
        policy=_policy(base),
        issues={91: {"number": 91, "state": "closed"}},
    )

    result = _run(tmp_path, responses)

    assert result.returncode == 1
    assert "exception for PR #2" in result.stderr
    assert "head SHA" in result.stderr


def test_lifecycle_fails_closed_on_auth_transport_and_malformed_pagination(tmp_path: Path) -> None:
    auth_failure = _responses(prs=[], policy=_policy())
    auth_failure["auth status --hostname github.com"] = {"exit": 1, "stderr": "not logged in"}
    assert _run(tmp_path / "auth", auth_failure).returncode == 2

    malformed = _responses(prs=[], policy=_policy())
    malformed["api --method GET repos/acme/widget/pulls?state=open&per_page=100 --paginate"] = {"bad": True}
    result = _run(tmp_path / "malformed", malformed)
    assert result.returncode == 2
    assert "paginated pull request response" in result.stderr


def test_lifecycle_rejects_policy_for_a_different_repository(tmp_path: Path) -> None:
    policy = _policy()
    policy["repository"] = "other/repo"

    result = _run(tmp_path, _responses(prs=[], policy=policy))

    assert result.returncode == 2
    assert "policy repository" in result.stderr


def test_lifecycle_bootstraps_only_the_stricter_empty_exception_policy_on_404(tmp_path: Path) -> None:
    responses = _responses(prs=[_pr(1, "1" * 40)], policy=_policy())
    policy_key = (
        "api --method GET repos/acme/widget/contents/.github/pr-lifecycle-policy.json"
        f"?ref={'a' * 40}"
    )
    responses[policy_key] = {"exit": 1, "stderr": "HTTP 404: Not Found"}

    result = _run(tmp_path, responses, "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["max_active_prs"] == 1
    assert payload["exception_prs"] == []
