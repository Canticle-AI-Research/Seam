"""Read-only proof that an exact qualified candidate reached protected main."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.agents.closeout_queue import (
    CloseoutQueueError,
    _canonical_record,
    _load_json_record,
    _load_queued_request,
    _receipt_is_dispositive,
    _stored_receipts,
)
from tools.agents.delivery_status import (
    DeliveryStatusError,
    build_completion,
    git_common_dir,
    load_plan,
    publish_completion,
)
from tools.ci.pr_lifecycle import (
    REPOSITORY,
    LifecycleError,
    _authenticate,
    _gh_json,
    _gh_paginated,
)

SHA = re.compile(r"^[0-9a-f]{40}$")
DEFAULT_REQUIRED_CHECKS = (
    "repo-hygiene",
    "chroma-real-smoke",
    "locomo-quickstart-bil2",
)
CANONICAL_GATES = (
    ("diff-hygiene", ("git", "diff", "--check")),
    ("agent-config", (sys.executable, "-m", "tools.git.verify_agent_config")),
    ("history-integrity", (sys.executable, "-m", "tools.history.verify_integrity")),
    ("history-routing", (sys.executable, "-m", "tools.history.verify_routing")),
    ("handoffs", (sys.executable, "-m", "tools.history.verify_handoffs")),
    ("continuity", (sys.executable, "-m", "tools.history.verify_continuity")),
    ("streams", (sys.executable, "-m", "tools.streams.verify_streams")),
    ("wiki", (sys.executable, "-m", "tools.docs.verify_wiki")),
    ("doc-references", (sys.executable, "-m", "tools.docs.sync_references", "--check")),
    ("suite-manifest", (sys.executable, "-m", "tools.release.verify_suite_manifest")),
    ("audit-claims", (sys.executable, "-m", "tools.docs.verify_audit_claims", "--changed-since", "HEAD^1")),
)


class VerifyMergeError(RuntimeError):
    """The merged state does not satisfy the exact proof contract."""


def _timestamp(value: Any, label: str, *, identity: str | None = None) -> datetime:
    suffix = f": {identity}" if identity is not None else ""
    if not isinstance(value, str):
        raise VerifyMergeError(f"{label} is malformed{suffix}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VerifyMergeError(f"{label} is malformed{suffix}") from exc
    if parsed.tzinfo is None:
        raise VerifyMergeError(f"{label} lacks timezone{suffix}")
    return parsed.astimezone(timezone.utc)


def _run(
    args: tuple[str, ...] | list[str], cwd: Path, *, check: bool = True, timeout: int = 120
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    try:
        completed = subprocess.run(
            list(args), cwd=cwd, env=env, capture_output=True, text=True,
            timeout=timeout, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise VerifyMergeError(f"command unavailable or timed out: {' '.join(args)}") from exc
    if check and completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise VerifyMergeError(f"command failed ({' '.join(args)}): {detail}")
    return completed


def _git(cwd: Path, *args: str) -> str:
    return _run(("git", *args), cwd).stdout.strip()


def _qualification(request_path: Path, receipt_path: Path, candidate: str) -> dict[str, Any]:
    try:
        supplied, request_blob = _load_json_record(request_path)
        request_id = supplied.get("request_id")
        if not isinstance(request_id, str):
            raise VerifyMergeError("qualification request has no queue identity")
        state_root = request_path.resolve().parent.parent
        expected_request = state_root / "requests" / f"{request_id}.json"
        if request_path.resolve() != expected_request:
            raise VerifyMergeError("qualification request is outside its canonical queue")
        request = _load_queued_request(request_id, state_root=state_root)
        if request != supplied:
            raise VerifyMergeError("qualification request differs from its queued record")
        stored = _stored_receipts(request, state_root=state_root)
        selected = [
            receipt for path, receipt in stored if path.resolve() == receipt_path.resolve()
        ]
        if len(selected) != 1:
            raise VerifyMergeError("qualification receipt is not an exact stored queue record")
        validated = selected[0]
        reread_receipt, receipt_blob = _load_json_record(receipt_path)
        if reread_receipt != validated:
            raise VerifyMergeError("qualification receipt changed while being validated")
    except (CloseoutQueueError, OSError) as exc:
        raise VerifyMergeError(f"stored qualification is invalid: {exc}") from exc
    if not _receipt_is_dispositive(request, validated):
        raise VerifyMergeError("stored qualification is not a dispositive QUALIFIED receipt")
    if request["repo"]["head"] != candidate or validated["scope"]["head"] != candidate:
        raise VerifyMergeError("stored qualification does not bind the expected candidate")
    return {
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "receipt_completed_at": validated["completed_at"],
        "_integration_worktree": request["repo"]["worktree"],
        "_state_root": state_root,
        "_request": request,
        "_request_blob": request_blob,
        "_receipt": validated,
        "_receipt_blob": receipt_blob,
    }


def _github_state(
    repository: str, number: int, candidate: str, result_main: str
) -> tuple[dict, list[dict], list[dict]]:
    _authenticate()
    pr = _gh_json(["api", "--method", "GET", f"repos/{repository}/pulls/{number}"])
    if not isinstance(pr, dict):
        raise VerifyMergeError("pull request response is malformed")
    if pr.get("state") != "closed" or pr.get("merged") is not True or not pr.get("merged_at"):
        raise VerifyMergeError("pull request is open or closed but not merged")
    head = pr.get("head")
    base = pr.get("base")
    if (
        not isinstance(head, dict)
        or head.get("sha") != candidate
        or not isinstance(head.get("repo"), dict)
        or not isinstance(head["repo"].get("full_name"), str)
        or not REPOSITORY.fullmatch(head["repo"]["full_name"])
    ):
        raise VerifyMergeError("pull request head does not match expected candidate")
    if (
        not isinstance(base, dict)
        or base.get("ref") != "main"
        or not isinstance(base.get("repo"), dict)
        or base["repo"].get("full_name") != repository
    ):
        raise VerifyMergeError("pull request base is not protected main")
    if pr.get("merge_commit_sha") != result_main:
        raise VerifyMergeError("pull request merge commit does not match expected main")
    main_ref = _gh_json(["api", "--method", "GET", f"repos/{repository}/git/ref/heads/main"])
    if (
        not isinstance(main_ref, dict)
        or not isinstance(main_ref.get("object"), dict)
        or main_ref["object"].get("sha") != result_main
    ):
        raise VerifyMergeError("protected main does not match expected result commit")
    rule_pages = _gh_paginated(
        ["api", "--method", "GET", f"repos/{repository}/rules/branches/main?per_page=100", "--paginate"]
    )
    if not all(isinstance(page, list) for page in rule_pages):
        raise VerifyMergeError("protected-main ruleset pagination response is malformed")
    rules = [rule for page in rule_pages for rule in page]
    if not all(isinstance(rule, dict) for rule in rules):
        raise VerifyMergeError("protected-main ruleset response contains a malformed rule")
    pages = _gh_paginated(
        ["api", "--method", "GET", f"repos/{repository}/commits/{candidate}/check-runs?per_page=100",
         "--paginate"]
    )
    if not isinstance(pages, list) or not all(isinstance(page, dict) for page in pages):
        raise VerifyMergeError("required-check pagination response is malformed")
    runs: list[dict] = []
    for page in pages:
        items = page.get("check_runs")
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise VerifyMergeError("required-check pagination response is incomplete")
        runs.extend(items)
    return pr, runs, rules


def _rule_identities(
    rules: list[dict], identities: tuple[str, ...]
) -> dict[str, dict[str, int | None]]:
    resolved: dict[str, dict[str, int | None]] = {}
    for rule in rules:
        if rule.get("type") != "required_status_checks":
            continue
        ruleset_id = rule.get("ruleset_id")
        parameters = rule.get("parameters")
        checks = parameters.get("required_status_checks") if isinstance(parameters, dict) else None
        if isinstance(ruleset_id, bool) or not isinstance(ruleset_id, int) or not isinstance(checks, list):
            raise VerifyMergeError("protected-main required-check rule is malformed")
        for check in checks:
            if not isinstance(check, dict):
                raise VerifyMergeError("protected-main required-check identity is malformed")
            context = check.get("context")
            integration_id = check.get("integration_id")
            if not isinstance(context, str) or not context:
                raise VerifyMergeError("protected-main required-check context is malformed")
            if isinstance(integration_id, bool) or not isinstance(integration_id, (int, type(None))):
                raise VerifyMergeError(f"required check has malformed app binding: {context}")
            identity = {"ruleset_id": ruleset_id, "ruleset_integration_id": integration_id}
            if context in resolved and resolved[context] != identity:
                raise VerifyMergeError(f"required check has ambiguous ruleset identity: {context}")
            resolved[context] = identity
    missing = [identity for identity in identities if identity not in resolved]
    if missing:
        raise VerifyMergeError(f"required check is absent from protected-main ruleset: {missing[0]}")
    return resolved


def _run_started_at(run: dict, identity: str) -> datetime:
    value = run.get("started_at")
    return _timestamp(value, "required check start", identity=identity)


def _required_checks(
    runs: list[dict], rules: list[dict], candidate: str, identities: tuple[str, ...]
) -> list[dict]:
    rule_identities = _rule_identities(rules, identities)
    evidence = []
    for identity in rule_identities:
        matches = [run for run in runs if run.get("name") == identity]
        if not matches:
            raise VerifyMergeError(f"required check is missing: {identity}")
        if any(run.get("head_sha") != candidate for run in matches):
            raise VerifyMergeError(f"required check has stale head identity: {identity}")
        exact_app = []
        for run in matches:
            app = run.get("app")
            app_id = app.get("id") if isinstance(app, dict) else None
            ruleset_app_id = rule_identities[identity]["ruleset_integration_id"]
            if (
                isinstance(app, dict)
                and app.get("slug") == "github-actions"
                and isinstance(app_id, int)
                and not isinstance(app_id, bool)
                and (ruleset_app_id is None or app_id == ruleset_app_id)
            ):
                exact_app.append(run)
        if not exact_app:
            raise VerifyMergeError(f"required check app does not match protected-main ruleset: {identity}")
        latest = max(exact_app, key=lambda run: _run_started_at(run, identity))
        completed_at = latest.get("completed_at")
        if (
            latest.get("status") != "completed"
            or latest.get("conclusion") != "success"
            or not isinstance(completed_at, str)
        ):
            raise VerifyMergeError(f"required check is stale or unsuccessful: {identity}")
        started = _run_started_at(latest, identity)
        completed = _timestamp(
            completed_at, "required check completion", identity=identity
        )
        if completed < started:
            raise VerifyMergeError(f"required check completed before it started: {identity}")
        evidence.append({
            "name": identity, "head_sha": candidate, "conclusion": "success",
            "started_at": latest["started_at"], "completed_at": completed_at,
            "app_slug": "github-actions", "app_id": latest["app"]["id"],
            **rule_identities[identity],
        })
    return evidence


def _local_merge(worktree: Path, candidate: str, result_main: str) -> dict[str, Any]:
    if not worktree.is_dir():
        raise VerifyMergeError("verification worktree does not exist")
    if _git(worktree, "rev-parse", "--show-toplevel") != str(worktree.resolve()):
        raise VerifyMergeError("verification path is not an isolated worktree root")
    if _git(worktree, "status", "--porcelain"):
        raise VerifyMergeError("verification worktree is not clean")
    if _git(worktree, "rev-parse", "HEAD") != result_main:
        raise VerifyMergeError("verification worktree is not at expected merged main")
    parents = _git(worktree, "rev-list", "--parents", "-n", "1", result_main).split()
    if len(parents) != 3:
        raise VerifyMergeError("result is not an ordinary merge commit; squash/rebase mapping is unsupported")
    if parents[2] != candidate:
        raise VerifyMergeError("ordinary merge second parent is not the expected candidate")
    ancestor = _run(("git", "merge-base", "--is-ancestor", candidate, result_main), worktree, check=False)
    if ancestor.returncode != 0:
        raise VerifyMergeError("expected candidate is not an ancestor of merged main")
    return {"commit": result_main, "first_parent": parents[1], "second_parent": parents[2]}


def _canonical_gates(worktree: Path) -> list[dict[str, Any]]:
    results = []
    for identity, command in CANONICAL_GATES:
        completed = _run(command, worktree, check=False)
        digest = hashlib.sha256((completed.stdout + completed.stderr).encode()).hexdigest()
        results.append(
            {"name": identity, "command": list(command), "exit_code": completed.returncode, "output_sha256": digest}
        )
        if completed.returncode:
            raise VerifyMergeError(f"canonical gate failed: {identity} (exit {completed.returncode})")
    return results


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise VerifyMergeError("merge evidence path already exists") from exc
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def verify(args: argparse.Namespace) -> dict[str, Any]:
    for label, value in (("expected candidate", args.expected_candidate), ("expected main", args.expected_main)):
        if not SHA.fullmatch(value):
            raise VerifyMergeError(f"{label} must be a full lowercase commit SHA")
    plan_context: tuple[dict[str, Any], bytes] | None = None
    if args.plan is not None:
        worktree = args.worktree.resolve()
        expected_plan = worktree / "docs" / "delivery" / "current.json"
        if args.plan.resolve() != expected_plan:
            raise VerifyMergeError("delivery plan must be docs/delivery/current.json in exact main")
        try:
            plan_context = load_plan(args.plan)
        except DeliveryStatusError as exc:
            raise VerifyMergeError(str(exc)) from exc
        if plan_context[0]["repository"] != args.repo:
            raise VerifyMergeError("delivery plan repository does not match requested repository")
        tracked = _run(
            ("git", "show", f"{args.expected_main}:docs/delivery/current.json"),
            worktree,
        ).stdout.encode("utf-8")
        if tracked != plan_context[1]:
            raise VerifyMergeError("delivery plan is not the exact plan blob on expected main")

    qualification = _qualification(args.request, args.receipt, args.expected_candidate)
    integration_worktree = Path(qualification.pop("_integration_worktree")).resolve()
    qualification_state_root = qualification.pop("_state_root")
    request = qualification.pop("_request")
    request_blob = qualification.pop("_request_blob")
    receipt = qualification.pop("_receipt")
    receipt_blob = qualification.pop("_receipt_blob")
    if args.worktree.resolve() == integration_worktree:
        raise VerifyMergeError("merged-main verification requires an isolated worktree")
    pr, runs, rules = _github_state(args.repo, args.pr, args.expected_candidate, args.expected_main)
    checks = _required_checks(runs, rules, args.expected_candidate, tuple(args.required_check))
    qualification_completed = _timestamp(
        qualification["receipt_completed_at"], "qualification completion"
    )
    merged_at = _timestamp(pr["merged_at"], "pull request merge")
    for check in checks:
        if _timestamp(
            check["completed_at"], "required check completion", identity=check["name"]
        ) > qualification_completed:
            raise VerifyMergeError(
                f"required check completed after qualification: {check['name']}"
            )
    if qualification_completed > merged_at:
        raise VerifyMergeError("qualification completed after pull request merge")
    merge = _local_merge(args.worktree.resolve(), args.expected_candidate, args.expected_main)
    gates = _canonical_gates(args.worktree.resolve())
    result = {
        "version": "seam-merge-verification/1",
        "status": "PASS",
        "repository": args.repo,
        "pull_request": args.pr,
        "expected_candidate": args.expected_candidate,
        "result_main": args.expected_main,
        "merge_method": "merge_commit",
        "merged_at": pr["merged_at"],
        "qualification": qualification,
        "merge": merge,
        "required_checks": checks,
        "canonical_gates": gates,
    }
    _write_once(args.evidence, result)
    if plan_context is not None:
        # Gates may execute arbitrary repository code. Recheck exact main and the
        # tracked plan before publishing the durable completion boundary.
        if _git(args.worktree.resolve(), "rev-parse", "HEAD") != args.expected_main:
            raise VerifyMergeError("verification worktree HEAD changed while gates ran")
        if _run(
            ("git", "diff", "--quiet", "HEAD", "--"),
            args.worktree.resolve(),
            check=False,
        ).returncode:
            raise VerifyMergeError("tracked verification state changed while gates ran")
        try:
            current_plan, current_plan_blob = load_plan(args.plan)
        except DeliveryStatusError as exc:
            raise VerifyMergeError(str(exc)) from exc
        if (current_plan, current_plan_blob) != plan_context:
            raise VerifyMergeError("delivery plan changed while merge verification ran")
        proof_blob = _canonical_record(result)
        try:
            common_dir = git_common_dir(args.worktree.resolve())
            completion = build_completion(
                common_dir=common_dir,
                qualification_state_root=qualification_state_root,
                plan=current_plan,
                plan_blob=current_plan_blob,
                request=request,
                request_blob=request_blob,
                receipt=receipt,
                receipt_blob=receipt_blob,
                proof=result,
                proof_blob=proof_blob,
            )
            publish_completion(common_dir, completion)
        except DeliveryStatusError as exc:
            raise VerifyMergeError(str(exc)) from exc
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify exact protected-main merge state")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr", required=True, type=int)
    parser.add_argument("--expected-candidate", required=True)
    parser.add_argument("--expected-main", required=True)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument(
        "--plan",
        type=Path,
        help="exact tracked docs/delivery/current.json to complete durably",
    )
    parser.add_argument("--required-check", action="append", default=list(DEFAULT_REQUIRED_CHECKS))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = verify(args)
    except (VerifyMergeError, LifecycleError) as exc:
        print(f"merge verification FAILED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
