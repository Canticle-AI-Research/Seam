#!/usr/bin/env python3
"""Report a delivery complete only from durable, validated merge evidence."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import stat
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.agents.closeout_queue import (
    CloseoutQueueError,
    _canonical_record,
    _ensure_state_directory,
    _publish_record_once,
    _receipt_is_dispositive,
    validate_receipt,
    validate_request,
)
from tools.ci.pr_lifecycle import REPOSITORY

PLAN_SCHEMA = "seam-delivery-plan/v1"
COMPLETION_SCHEMA = "seam-delivery-completion/v1"
PLAN_FIELDS = {
    "schema", "delivery_id", "repository", "next_action_after_verified",
}
COMPLETION_FIELDS = {
    "schema",
    "delivery_id",
    "repository_common_dir",
    "qualification_state_root",
    "completed_at",
    "expected_candidate",
    "result_main",
    "plan",
    "plan_blob_base64",
    "plan_blob_sha256",
    "request",
    "request_blob_base64",
    "request_blob_sha256",
    "receipt",
    "receipt_blob_base64",
    "receipt_blob_sha256",
    "proof",
    "proof_blob_base64",
    "proof_blob_sha256",
}
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,200}$")
SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_COMPLETION_BYTES = 8 * 1024 * 1024
CANONICAL_GATE_NAMES = (
    "diff-hygiene",
    "agent-config",
    "history-integrity",
    "history-routing",
    "handoffs",
    "continuity",
    "streams",
    "wiki",
    "doc-references",
    "suite-manifest",
    "audit-claims",
)
MINIMUM_REQUIRED_CHECKS = {
    "repo-hygiene",
    "chroma-real-smoke",
    "locomo-quickstart-bil2",
}
PYTHON_GATE_COMMANDS = {
    "agent-config": ("-m", "tools.git.verify_agent_config"),
    "history-integrity": ("-m", "tools.history.verify_integrity"),
    "history-routing": ("-m", "tools.history.verify_routing"),
    "handoffs": ("-m", "tools.history.verify_handoffs"),
    "continuity": ("-m", "tools.history.verify_continuity"),
    "streams": ("-m", "tools.streams.verify_streams"),
    "wiki": ("-m", "tools.docs.verify_wiki"),
    "doc-references": ("-m", "tools.docs.sync_references", "--check"),
    "suite-manifest": ("-m", "tools.release.verify_suite_manifest"),
    "audit-claims": (
        "-m", "tools.docs.verify_audit_claims", "--changed-since", "HEAD^1",
    ),
}


class DeliveryStatusError(RuntimeError):
    """A delivery plan cannot be proven complete from durable local evidence."""


def _read_json_record(
    path: Path, *, maximum: int = MAX_COMPLETION_BYTES
) -> tuple[dict[str, Any], bytes]:
    descriptor: int | None = None
    try:
        if path.is_symlink():
            raise DeliveryStatusError(f"record must be a regular file: {path.name}")
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise DeliveryStatusError(f"record is not a bounded regular file: {path.name}")
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = None
            encoded = handle.read(maximum + 1)
            after = os.fstat(handle.fileno())
        if len(encoded) > maximum:
            raise DeliveryStatusError(f"record is too large: {path.name}")
        identity_before = (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns,
        )
        identity_after = (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns,
        )
        if identity_before != identity_after:
            raise DeliveryStatusError(f"record changed while reading: {path.name}")
        value = json.loads(encoded.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeliveryStatusError(f"cannot read record: {path.name}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not isinstance(value, dict):
        raise DeliveryStatusError(f"record must be an object: {path.name}")
    return value, encoded


def validate_plan(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != PLAN_FIELDS:
        raise DeliveryStatusError("delivery plan fields do not match the v1 contract")
    if value.get("schema") != PLAN_SCHEMA:
        raise DeliveryStatusError("delivery plan schema is unsupported")
    delivery_id = value.get("delivery_id")
    if not isinstance(delivery_id, str) or not SAFE_ID.fullmatch(delivery_id):
        raise DeliveryStatusError("delivery plan delivery_id is unsafe")
    repository = value.get("repository")
    if not isinstance(repository, str) or not REPOSITORY.fullmatch(repository):
        raise DeliveryStatusError("delivery plan repository is invalid")
    next_action = value.get("next_action_after_verified")
    if (
        not isinstance(next_action, str)
        or not next_action.strip()
        or len(next_action) > 2000
        or "\x00" in next_action
    ):
        raise DeliveryStatusError("delivery plan next action is invalid")
    return value


def load_plan(path: Path) -> tuple[dict[str, Any], bytes]:
    value, encoded = _read_json_record(path, maximum=1024 * 1024)
    return validate_plan(value), encoded


def _git(repo_root: Path, *arguments: str, check: bool = True) -> str:
    env = os.environ.copy()
    env.pop("GIT_DIR", None)
    env.pop("GIT_WORK_TREE", None)
    try:
        result = subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeliveryStatusError("Git inspection is unavailable") from exc
    if check and result.returncode:
        raise DeliveryStatusError("Git inspection failed")
    return result.stdout.strip()


def git_common_dir(repo_root: Path) -> Path:
    root = repo_root.resolve(strict=True)
    if _git(root, "rev-parse", "--show-toplevel") != str(root):
        raise DeliveryStatusError("repository root is not a Git worktree root")
    raw = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    common = Path(raw)
    if not common.is_absolute():
        common = root / common
    common = common.resolve(strict=True)
    if common.is_symlink() or not common.is_dir():
        raise DeliveryStatusError("Git common directory is unsafe")
    return common


def completion_path(common_dir: Path, delivery_id: str) -> Path:
    if not SAFE_ID.fullmatch(delivery_id):
        raise DeliveryStatusError("delivery completion identity is unsafe")
    return common_dir / "seam-orchestration" / "delivery-completions" / f"{delivery_id}.json"


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 100:
        raise DeliveryStatusError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise DeliveryStatusError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise DeliveryStatusError(f"{label} lacks timezone")
    return parsed.astimezone(timezone.utc)


def _artifact(record: dict[str, Any], name: str) -> tuple[dict[str, Any], bytes]:
    value = record.get(name)
    encoded_value = record.get(f"{name}_blob_base64")
    digest = record.get(f"{name}_blob_sha256")
    if not isinstance(value, dict):
        raise DeliveryStatusError(f"completion {name} copy is invalid")
    if not isinstance(encoded_value, str) or len(encoded_value) > MAX_COMPLETION_BYTES:
        raise DeliveryStatusError(f"completion {name} blob is invalid")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise DeliveryStatusError(f"completion {name} hash is invalid")
    try:
        encoded = base64.b64decode(encoded_value.encode("ascii"), validate=True)
        decoded = json.loads(encoded.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeliveryStatusError(f"completion {name} blob is invalid") from exc
    if not isinstance(decoded, dict) or decoded != value:
        raise DeliveryStatusError(f"completion {name} copy does not match its blob")
    if hashlib.sha256(encoded).hexdigest() != digest:
        raise DeliveryStatusError(f"completion {name} hash does not match its blob")
    return value, encoded


def build_completion(
    *,
    common_dir: Path,
    qualification_state_root: Path,
    plan: dict[str, Any],
    plan_blob: bytes,
    request: dict[str, Any],
    request_blob: bytes,
    receipt: dict[str, Any],
    receipt_blob: bytes,
    proof: dict[str, Any],
    proof_blob: bytes,
) -> dict[str, Any]:
    def fields(name: str, value: dict[str, Any], blob: bytes) -> dict[str, Any]:
        return {
            name: value,
            f"{name}_blob_base64": base64.b64encode(blob).decode("ascii"),
            f"{name}_blob_sha256": hashlib.sha256(blob).hexdigest(),
        }

    record = {
        "schema": COMPLETION_SCHEMA,
        "delivery_id": plan["delivery_id"],
        "repository_common_dir": str(common_dir),
        "qualification_state_root": str(qualification_state_root),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "expected_candidate": proof["expected_candidate"],
        "result_main": proof["result_main"],
        **fields("plan", plan, plan_blob),
        **fields("request", request, request_blob),
        **fields("receipt", receipt, receipt_blob),
        **fields("proof", proof, proof_blob),
    }
    if len(_canonical_record(record)) > MAX_COMPLETION_BYTES:
        raise DeliveryStatusError("delivery completion exceeds the durable record limit")
    return record


def publish_completion(common_dir: Path, record: dict[str, Any]) -> Path:
    path = completion_path(common_dir, record["delivery_id"])
    try:
        _ensure_state_directory(path.parent, label="delivery-completion")
        if not _publish_record_once(path, _canonical_record(record)):
            raise DeliveryStatusError("delivery completion already exists")
    except CloseoutQueueError as exc:
        raise DeliveryStatusError(str(exc)) from exc
    return path


def _validate_proof(
    proof: dict[str, Any],
    *,
    plan: dict[str, Any],
    request: dict[str, Any],
    receipt: dict[str, Any],
    candidate: str,
    result_main: str,
    completion_time: datetime,
) -> None:
    if set(proof) != {
        "version",
        "status",
        "repository",
        "pull_request",
        "expected_candidate",
        "result_main",
        "merge_method",
        "merged_at",
        "qualification",
        "merge",
        "required_checks",
        "canonical_gates",
    }:
        raise DeliveryStatusError("merge proof fields do not match the v1 contract")
    if (
        proof.get("version") != "seam-merge-verification/1"
        or proof.get("status") != "PASS"
        or proof.get("repository") != plan["repository"]
        or proof.get("expected_candidate") != candidate
        or proof.get("result_main") != result_main
        or proof.get("merge_method") != "merge_commit"
    ):
        raise DeliveryStatusError("merge proof identity is inconsistent")
    pull_request = proof.get("pull_request")
    if isinstance(pull_request, bool) or not isinstance(pull_request, int) or pull_request < 1:
        raise DeliveryStatusError("merge proof pull request identity is invalid")
    qualification = proof.get("qualification")
    if not isinstance(qualification, dict) or set(qualification) != {
        "request_id", "request_sha256", "receipt_completed_at",
    } or (
        qualification.get("request_id") != request.get("request_id")
        or qualification.get("request_sha256") != request.get("request_sha256")
        or qualification.get("receipt_completed_at") != receipt.get("completed_at")
    ):
        raise DeliveryStatusError("merge proof qualification binding is inconsistent")
    merge = proof.get("merge")
    if not isinstance(merge, dict) or set(merge) != {
        "commit", "first_parent", "second_parent",
    } or (
        merge.get("commit") != result_main
        or not isinstance(merge.get("first_parent"), str)
        or not SHA.fullmatch(merge["first_parent"])
        or merge.get("second_parent") != candidate
    ):
        raise DeliveryStatusError("merge proof ancestry binding is inconsistent")
    if (
        request.get("repo", {}).get("head") != candidate
        or receipt.get("scope", {}).get("head") != candidate
    ):
        raise DeliveryStatusError("qualification does not bind the recorded candidate")
    checks = proof.get("required_checks")
    if not isinstance(checks, list) or not checks:
        raise DeliveryStatusError("merge proof required checks are invalid")
    qualification_time = _timestamp(receipt.get("completed_at"), "receipt completion")
    merged_time = _timestamp(proof.get("merged_at"), "merge time")
    check_names: list[str] = []
    for check in checks:
        if not isinstance(check, dict) or set(check) != {
            "name",
            "head_sha",
            "conclusion",
            "started_at",
            "completed_at",
            "app_slug",
            "app_id",
            "ruleset_id",
            "ruleset_integration_id",
        }:
            raise DeliveryStatusError("merge proof required checks are invalid")
        name = check.get("name")
        app_id = check.get("app_id")
        ruleset_id = check.get("ruleset_id")
        integration_id = check.get("ruleset_integration_id")
        if (
            not isinstance(name, str)
            or not name
            or check.get("head_sha") != candidate
            or check.get("conclusion") != "success"
            or check.get("app_slug") != "github-actions"
            or isinstance(app_id, bool)
            or not isinstance(app_id, int)
            or app_id < 1
            or isinstance(ruleset_id, bool)
            or not isinstance(ruleset_id, int)
            or ruleset_id < 1
            or isinstance(integration_id, bool)
            or not isinstance(integration_id, (int, type(None)))
            or (integration_id is not None and integration_id != app_id)
        ):
            raise DeliveryStatusError("merge proof required checks are invalid")
        started = _timestamp(check.get("started_at"), f"required check start: {name}")
        completed = _timestamp(
            check.get("completed_at"), f"required check completion: {name}"
        )
        if started > completed or completed > qualification_time:
            raise DeliveryStatusError("merge proof required check time order is invalid")
        check_names.append(name)
    if (
        len(check_names) != len(set(check_names))
        or not MINIMUM_REQUIRED_CHECKS <= set(check_names)
    ):
        raise DeliveryStatusError("merge proof required checks are incomplete")
    gates = proof.get("canonical_gates")
    if not isinstance(gates, list) or [
        gate.get("name") if isinstance(gate, dict) else None for gate in gates
    ] != list(CANONICAL_GATE_NAMES) or any(
        not isinstance(gate, dict)
        or set(gate) != {"name", "command", "exit_code", "output_sha256"}
        or not _canonical_gate_command(gate["name"], gate.get("command"))
        or gate.get("exit_code") != 0
        or not isinstance(gate.get("output_sha256"), str)
        or not SHA256.fullmatch(gate["output_sha256"])
        for gate in gates
    ):
        raise DeliveryStatusError("merge proof canonical gates are invalid")
    if qualification_time > merged_time or merged_time > completion_time:
        raise DeliveryStatusError("merge proof time order is invalid")


def _canonical_gate_command(name: str, command: object) -> bool:
    if not isinstance(command, list) or not command or not all(
        isinstance(part, str) and part for part in command
    ):
        return False
    if name == "diff-hygiene":
        return command == ["git", "diff", "--check"]
    expected = PYTHON_GATE_COMMANDS.get(name)
    if expected is None or len(command) != len(expected) + 1:
        return False
    interpreter = Path(command[0]).name
    return bool(re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", interpreter)) and tuple(
        command[1:]
    ) == expected


def evaluate(repo_root: Path, plan_path: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve(strict=True)
    expected_plan_path = repo_root / "docs" / "delivery" / "current.json"
    if plan_path.resolve() != expected_plan_path:
        raise DeliveryStatusError("delivery plan must be docs/delivery/current.json")
    plan, plan_blob = load_plan(plan_path)
    common = git_common_dir(repo_root)
    record_path = completion_path(common, plan["delivery_id"])
    record, _ = _read_json_record(record_path)
    if set(record) != COMPLETION_FIELDS or record.get("schema") != COMPLETION_SCHEMA:
        raise DeliveryStatusError("delivery completion fields do not match the v1 contract")
    if record.get("delivery_id") != plan["delivery_id"]:
        raise DeliveryStatusError("delivery completion identity does not match current plan")
    if record.get("repository_common_dir") != str(common):
        raise DeliveryStatusError("delivery completion belongs to another clone")
    state_root_value = record.get("qualification_state_root")
    if not isinstance(state_root_value, str) or not Path(state_root_value).is_absolute():
        raise DeliveryStatusError("delivery completion qualification root is invalid")
    completion_time = _timestamp(record.get("completed_at"), "completion time")
    candidate = record.get("expected_candidate")
    result_main = record.get("result_main")
    if not isinstance(candidate, str) or not SHA.fullmatch(candidate):
        raise DeliveryStatusError("delivery completion candidate is invalid")
    if not isinstance(result_main, str) or not SHA.fullmatch(result_main):
        raise DeliveryStatusError("delivery completion main commit is invalid")

    stored_plan, stored_plan_blob = _artifact(record, "plan")
    request, _ = _artifact(record, "request")
    receipt, _ = _artifact(record, "receipt")
    proof, _ = _artifact(record, "proof")
    validate_plan(stored_plan)
    if stored_plan != plan or stored_plan_blob != plan_blob:
        raise DeliveryStatusError("current delivery plan does not match durable completion")
    if plan["repository"] != proof.get("repository"):
        raise DeliveryStatusError("delivery plan repository does not match merge proof")
    state_root = Path(state_root_value)
    try:
        validate_request(request, state_root=state_root)
        validate_receipt(request, receipt, state_root=state_root)
    except CloseoutQueueError as exc:
        raise DeliveryStatusError(f"durable qualification is invalid: {exc}") from exc
    if not _receipt_is_dispositive(request, receipt):
        raise DeliveryStatusError("durable qualification is not QUALIFIED for exact scope")
    _validate_proof(
        proof,
        plan=plan,
        request=request,
        receipt=receipt,
        candidate=candidate,
        result_main=result_main,
        completion_time=completion_time,
    )

    head_plan = subprocess.run(
        ["git", "show", "HEAD:docs/delivery/current.json"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if head_plan.returncode or head_plan.stdout != plan_blob:
        raise DeliveryStatusError("current delivery plan does not match HEAD plan blob")
    tracked_plan = subprocess.run(
        ["git", "show", f"{result_main}:docs/delivery/current.json"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if tracked_plan.returncode or tracked_plan.stdout != plan_blob:
        raise DeliveryStatusError("delivery plan is not the exact plan blob on verified main")
    parents = _git(repo_root, "rev-list", "--parents", "-n", "1", result_main).split()
    if len(parents) != 3 or parents[2] != candidate:
        raise DeliveryStatusError("verified main no longer has the recorded merge ancestry")
    for ancestor, descendant, label in (
        (candidate, result_main, "candidate"),
        (result_main, "HEAD", "verified main"),
    ):
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=repo_root,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise DeliveryStatusError(f"{label} is not in current Git ancestry")
    return {
        "schema": "seam-delivery-status/v1",
        "status": "VERIFIED",
        "delivery_id": plan["delivery_id"],
        "repository": plan["repository"],
        "result_main": result_main,
        "completion_path": str(record_path),
        "next_action_after_verified": plan["next_action_after_verified"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate durable SEAM delivery completion")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    plan = args.plan or repo_root / "docs" / "delivery" / "current.json"
    try:
        result = evaluate(repo_root, plan)
    except (DeliveryStatusError, OSError) as exc:
        result = {
            "schema": "seam-delivery-status/v1",
            "status": "UNVERIFIED",
            "reason": str(exc),
        }
        if args.json:
            print(json.dumps(result, sort_keys=True))
        else:
            print(f"delivery UNVERIFIED: {exc}")
        return 1
    if args.json:
        print(json.dumps(result, sort_keys=True))
    else:
        print(
            f"delivery VERIFIED: {result['delivery_id']} at {result['result_main']}\n"
            f"next: {result['next_action_after_verified']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
