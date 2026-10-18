#!/usr/bin/env python3
"""Validate and surface pending closeout requests for the root release wave."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.agents.session_end_closeout import (
    DEFAULT_STATE_ROOT,
    REQUIRED_CLOSEOUT_CHECKS,
    SessionEndError,
    _changed_paths,
    _fingerprint,
    _git_text,
    assess_tdd,
    runtime_paths,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_RECORD_BYTES = 1024 * 1024
REQUEST_FIELDS = {
    "schema",
    "request_id",
    "request_sha256",
    "session_id",
    "created_at",
    "trigger",
    "repo",
    "change_class",
    "context",
    "tdd_evidence",
    "authority",
    "required_checks",
    "receipt_path",
    "request_schema",
    "receipt_schema",
}
REPO_FIELDS = {
    "root",
    "cwd",
    "branch",
    "head",
    "base_sha",
    "origin_main",
    "worktree",
    "diff_fingerprint",
    "changed_paths",
    "changed_paths_truncated",
}
CONTEXT_FIELDS = {
    "source",
    "available",
    "objective",
    "plan",
    "constraints",
    "affected_tests",
}
TDD_FIELDS = {
    "status",
    "runtime_paths",
    "covered_runtime_paths",
    "missing_runtime_paths",
    "cycle_count",
    "cycles",
}
LEGACY_TDD_FIELDS = TDD_FIELDS - {"cycles"}
RECEIPT_FIELDS = {
    "schema",
    "request_id",
    "request_sha256",
    "session_id",
    "completed_at",
    "status",
    "supersedes_request_ids",
    "scope",
    "tdd",
    "checks",
    "continuity",
    "project_alignment",
    "next_action",
}
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,200}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
ADMISSION_FIELDS = {
    "schema",
    "kind",
    "repository_common_dir",
    "registered_roots",
    "observed_roots",
    "pending_request_ids",
    "record_sha256s",
    "admitted_at",
}
ROOT_REGISTRATION_FIELDS = {
    "schema",
    "kind",
    "repository_common_dir",
    "registered_root",
}
ADMINISTRATIVE_DISPOSITION_FIELDS = {
    "schema", "status", "request_id", "request_path", "request_bytes_sha256",
    "blocked_receipt_path", "blocked_receipt_bytes_sha256", "prior_request_id",
    "prior_request_path", "prior_request_bytes_sha256", "prior_receipt_path",
    "prior_receipt_bytes_sha256", "projection_sha256", "current_origin_main",
    "prior_origin_main", "review_path", "review_bytes_sha256", "authority",
    "reconciled_at",
}
ADMINISTRATIVE_REVIEW_FIELDS = {
    "schema", "repository_common_dir", "queue_root", "current_request_id",
    "current_request_sha256", "current_receipt_sha256", "prior_request_id",
    "prior_request_sha256", "prior_receipt_sha256", "producer_session_id",
    "reviewer", "reviewed_at", "status", "reason", "authority",
    "unresolved_findings",
}
ADMINISTRATIVE_REASON = "UNCHANGED_NONRUNTIME_TAIL_ASSURANCE_BOUNDARY"


class CloseoutQueueError(RuntimeError):
    """A request or receipt cannot be admitted safely."""


def _timestamp(value: object, *, label: str) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 100:
        raise CloseoutQueueError(f"closeout {label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CloseoutQueueError(f"closeout {label} is invalid") from exc
    if parsed.tzinfo is None:
        raise CloseoutQueueError(f"closeout {label} must include a timezone")
    return parsed


def _load_json_record(path: Path) -> tuple[dict[str, Any], bytes]:
    descriptor: int | None = None
    try:
        if (
            not path.is_absolute()
            or ".." in path.parts
            or path.is_symlink()
            or path.resolve(strict=True) != path
        ):
            raise CloseoutQueueError(
                f"closeout record must use a regular file; path is unsafe: {path.name}"
            )
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise CloseoutQueueError(
                f"closeout record must be a regular file: {path.name}"
            )
        if metadata.st_size > MAX_RECORD_BYTES:
            raise CloseoutQueueError(f"closeout record exceeds 1 MiB: {path.name}")
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            descriptor = None
            encoded = handle.read(MAX_RECORD_BYTES + 1)
            finished = os.fstat(handle.fileno())
        if len(encoded) > MAX_RECORD_BYTES:
            raise CloseoutQueueError(f"closeout record exceeds 1 MiB: {path.name}")
        before = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )
        after = (
            finished.st_dev,
            finished.st_ino,
            finished.st_size,
            finished.st_mtime_ns,
            finished.st_ctime_ns,
        )
        if before != after:
            raise CloseoutQueueError(f"closeout record changed while reading: {path.name}")
        value = json.loads(encoded.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CloseoutQueueError(f"cannot read closeout record: {path.name}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not isinstance(value, dict):
        raise CloseoutQueueError(f"closeout record must be an object: {path.name}")
    return value, encoded


def _load_json(path: Path) -> dict[str, Any]:
    return _load_json_record(path)[0]


def _request_hash(value: dict[str, Any]) -> str:
    unsigned = {key: item for key, item in value.items() if key != "request_sha256"}
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(canonical).hexdigest()


def _expected_receipt_path(state_root: Path, request_id: str) -> Path:
    return state_root.resolve() / "receipts" / f"{request_id}.json"


def _receipt_path_matches(value: str, *, expected: Path, repo_root: str) -> bool:
    # SessionEnd run with a relative --state-root wrote a repo-relative path.
    # Accept only that exact legacy form; it must land on the canonical receipt.
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate == expected
    if ".." in candidate.parts:
        return False
    return (Path(repo_root) / candidate).resolve() == expected


def _receipt_attempt_root(state_root: Path) -> Path:
    return state_root.resolve() / "receipt-attempts"


def _receipt_attempt_path(
    state_root: Path, request_id: str, encoded: bytes
) -> Path:
    digest = hashlib.sha256(encoded).hexdigest()
    return _receipt_attempt_root(state_root) / f"{request_id}-{digest}.json"


def _ensure_state_directory(path: Path, *, label: str) -> None:
    ancestor = path
    while not os.path.lexists(ancestor) and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    if ancestor.is_symlink() or not ancestor.is_dir() or ancestor.resolve() != ancestor:
        raise CloseoutQueueError(f"closeout {label} directory has an unsafe ancestor")
    if os.path.lexists(path) and (path.is_symlink() or not path.is_dir()):
        raise CloseoutQueueError(f"closeout {label} directory must be a real directory")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.resolve() != path:
        raise CloseoutQueueError(f"closeout {label} directory escapes its state root")


def _string_list(
    value: object,
    *,
    maximum: int,
    maximum_length: int = 1000,
    minimum: int = 0,
) -> bool:
    return (
        isinstance(value, list)
        and minimum <= len(value) <= maximum
        and all(
            isinstance(item, str) and 0 < len(item) <= maximum_length
            for item in value
        )
    )


def _validate_tdd_cycles(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 128:
        raise CloseoutQueueError("closeout request TDD cycles are invalid")
    for cycle in value:
        if not isinstance(cycle, dict) or set(cycle) != {
            "behavior",
            "test_refs",
            "implementation_refs",
            "red",
            "green",
        }:
            raise CloseoutQueueError("closeout request TDD cycle fields are invalid")
        if (
            not isinstance(cycle.get("behavior"), str)
            or not 1 <= len(cycle["behavior"]) <= 1000
        ):
            raise CloseoutQueueError("closeout request TDD cycle behavior is invalid")
        for field in ("test_refs", "implementation_refs"):
            if not _string_list(
                cycle.get(field), maximum=32, maximum_length=500, minimum=1
            ):
                raise CloseoutQueueError(
                    f"closeout request TDD cycle {field} is invalid"
                )
        for phase_name in ("red", "green"):
            phase = cycle.get(phase_name)
            if not isinstance(phase, dict) or set(phase) != {
                "command",
                "exit_code",
                "observed_at",
                "fingerprint",
            }:
                raise CloseoutQueueError(
                    f"closeout request TDD {phase_name} phase is invalid"
                )
            if (
                not isinstance(phase.get("command"), str)
                or not 1 <= len(phase["command"]) <= 2000
            ):
                raise CloseoutQueueError(
                    f"closeout request TDD {phase_name} command is invalid"
                )
            if isinstance(phase.get("exit_code"), bool) or not isinstance(
                phase.get("exit_code"), int
            ):
                raise CloseoutQueueError(
                    f"closeout request TDD {phase_name} exit_code is invalid"
                )
            _timestamp(
                phase.get("observed_at"),
                label=f"request TDD {phase_name} observed_at",
            )
            if (
                not isinstance(phase.get("fingerprint"), str)
                or not 1 <= len(phase["fingerprint"]) <= 256
            ):
                raise CloseoutQueueError(
                    f"closeout request TDD {phase_name} fingerprint is invalid"
                )
    return value


def validate_request(
    value: object, *, state_root: Path = DEFAULT_STATE_ROOT
) -> dict[str, Any]:
    """Validate the strict identity, authority, and hash of one queued request."""

    if not isinstance(value, dict) or set(value) != REQUEST_FIELDS:
        raise CloseoutQueueError("closeout request fields do not match the v1 contract")
    if value.get("schema") != "seam-agent-closeout-request/v1":
        raise CloseoutQueueError("unsupported closeout request schema")
    request_id = value.get("request_id")
    if not isinstance(request_id, str) or not SAFE_ID.fullmatch(request_id):
        raise CloseoutQueueError("closeout request_id is unsafe")
    request_sha256 = value.get("request_sha256")
    if not isinstance(request_sha256, str) or not SHA256.fullmatch(request_sha256):
        raise CloseoutQueueError("closeout request_sha256 is invalid")
    if request_sha256 != _request_hash(value):
        raise CloseoutQueueError("closeout request_sha256 does not match request content")
    session_id = value.get("session_id")
    if (
        not isinstance(session_id, str)
        or len(session_id) > 180
        or not SAFE_ID.fullmatch(session_id)
    ):
        raise CloseoutQueueError("closeout request session_id is unsafe")
    if value.get("trigger") != "SessionEnd":
        raise CloseoutQueueError("closeout request trigger is unsupported")
    _timestamp(value.get("created_at"), label="request created_at")
    if value.get("change_class") not in {"runtime", "non_runtime"}:
        raise CloseoutQueueError("closeout request change_class is invalid")
    repo = value.get("repo")
    if not isinstance(repo, dict) or set(repo) != REPO_FIELDS:
        raise CloseoutQueueError("closeout request repo fields do not match the contract")
    for field, maximum in (
        ("root", 1000),
        ("cwd", 1000),
        ("branch", 300),
        ("worktree", 1000),
    ):
        item = repo.get(field)
        if not isinstance(item, str) or not item or len(item) > maximum:
            raise CloseoutQueueError(f"closeout request repo.{field} is invalid")
    if repo["worktree"] != repo["root"]:
        raise CloseoutQueueError("closeout request worktree does not match repo root")
    head = repo.get("head")
    if not isinstance(head, str) or not COMMIT.fullmatch(head):
        raise CloseoutQueueError("closeout request repo.head is invalid")
    fingerprint = repo.get("diff_fingerprint")
    if not isinstance(fingerprint, str) or not SHA256.fullmatch(fingerprint):
        raise CloseoutQueueError("closeout request repo.diff_fingerprint is invalid")
    if request_id != f"{session_id}-{fingerprint[:16]}":
        raise CloseoutQueueError("closeout request identity does not match its scope")
    for field in ("base_sha", "origin_main"):
        commit = repo.get(field)
        if commit is not None and (
            not isinstance(commit, str) or not COMMIT.fullmatch(commit)
        ):
            raise CloseoutQueueError(f"closeout request repo.{field} is invalid")
    paths = repo.get("changed_paths")
    if not isinstance(paths, list) or len(paths) > 512 or not all(
        isinstance(path, str) and 0 < len(path) <= 1000 for path in paths
    ):
        raise CloseoutQueueError("closeout request changed_paths is invalid")
    if len(set(paths)) != len(paths) or any(
        Path(path).is_absolute() or ".." in Path(path).parts for path in paths
    ):
        raise CloseoutQueueError("closeout request changed_paths are unsafe or duplicated")
    if not isinstance(repo.get("changed_paths_truncated"), bool):
        raise CloseoutQueueError("closeout request truncation flag is invalid")
    visible_runtime_paths = set(runtime_paths(paths))
    if visible_runtime_paths and value["change_class"] != "runtime":
        raise CloseoutQueueError(
            "closeout request runtime classification contradicts changed paths"
        )
    context = value.get("context")
    if not isinstance(context, dict) or set(context) != CONTEXT_FIELDS:
        raise CloseoutQueueError("closeout request context fields are invalid")
    if context.get("source") != "root_session_state" or not isinstance(
        context.get("available"), bool
    ):
        raise CloseoutQueueError("closeout request context source is invalid")
    objective = context.get("objective")
    if not isinstance(objective, str) or len(objective) > 1200:
        raise CloseoutQueueError("closeout request context objective is invalid")
    for field in ("plan", "constraints", "affected_tests"):
        if not _string_list(context.get(field), maximum=128, maximum_length=500):
            raise CloseoutQueueError(f"closeout request context {field} is invalid")
    tdd = value.get("tdd_evidence")
    if not isinstance(tdd, dict) or set(tdd) not in {
        frozenset(TDD_FIELDS),
        frozenset(LEGACY_TDD_FIELDS),
    }:
        raise CloseoutQueueError("closeout request TDD fields are invalid")
    cycles = _validate_tdd_cycles(tdd.get("cycles")) if "cycles" in tdd else None
    for field in ("runtime_paths", "covered_runtime_paths", "missing_runtime_paths"):
        if not _string_list(tdd.get(field), maximum=2048):
            raise CloseoutQueueError(f"closeout request TDD {field} is invalid")
        if len(set(tdd[field])) != len(tdd[field]):
            raise CloseoutQueueError(f"closeout request TDD {field} is duplicated")
    cycle_count = tdd.get("cycle_count")
    if isinstance(cycle_count, bool) or not isinstance(cycle_count, int) or cycle_count < 0:
        raise CloseoutQueueError("closeout request TDD cycle_count is invalid")
    tdd_runtime_paths = set(tdd["runtime_paths"])
    covered = set(tdd["covered_runtime_paths"])
    missing = set(tdd["missing_runtime_paths"])
    if covered & missing or covered | missing != tdd_runtime_paths:
        raise CloseoutQueueError("closeout request TDD coverage is inconsistent")
    truncated = repo["changed_paths_truncated"]
    if truncated:
        expected_tdd = "TDD_UNPROVEN"
        if value["change_class"] != "runtime":
            raise CloseoutQueueError(
                "closeout request truncated scope must fail closed as runtime"
            )
    else:
        expected_tdd = (
            "TDD_NOT_REQUIRED"
            if value["change_class"] == "non_runtime"
            else "TDD_PROVEN"
            if tdd_runtime_paths and not missing and cycle_count > 0
            else "TDD_UNPROVEN"
        )
    if tdd.get("status") != expected_tdd:
        raise CloseoutQueueError("closeout request TDD status is inconsistent")
    if not truncated and (value["change_class"] == "runtime") != bool(
        tdd_runtime_paths
    ):
        raise CloseoutQueueError("closeout request TDD runtime classification is inconsistent")
    if not visible_runtime_paths <= tdd_runtime_paths:
        raise CloseoutQueueError("closeout request TDD omits visible runtime paths")
    # Keep immutable v1 requests readable under their original, stricter
    # prefix policy. Never invent coverage or allow an executable omission:
    # only the two exact known classification sets are accepted.
    legacy_documentation = tdd_runtime_paths != visible_runtime_paths
    expected_runtime_paths = set(runtime_paths(paths, include_documentation=legacy_documentation))
    if tdd_runtime_paths != expected_runtime_paths:
        raise CloseoutQueueError("closeout request TDD runtime paths do not match changed paths")
    if cycles is not None:
        recomputed = assess_tdd(
            paths, {"tdd_cycles": cycles}, include_documentation=legacy_documentation,
        )
        if truncated:
            recomputed.update(
                {
                    "status": "TDD_UNPROVEN",
                    "covered_runtime_paths": [],
                    "missing_runtime_paths": recomputed["runtime_paths"],
                }
            )
        for field in (
            "status",
            "runtime_paths",
            "covered_runtime_paths",
            "missing_runtime_paths",
            "cycle_count",
        ):
            if tdd[field] != recomputed[field]:
                raise CloseoutQueueError(
                    "closeout request TDD summary does not recompute from cycle evidence"
                )
    authority = value.get("authority")
    if not isinstance(authority, dict) or set(authority) != {
        "mode",
        "allowed_writes",
        "forbidden_actions",
    }:
        raise CloseoutQueueError("closeout request authority fields are invalid")
    if authority.get("mode") != "verify_only" or authority.get("allowed_writes") != []:
        raise CloseoutQueueError("closeout request grants release-agent write authority")
    if not _string_list(
        authority.get("forbidden_actions"),
        maximum=32,
        maximum_length=1000,
        minimum=1,
    ):
        raise CloseoutQueueError("closeout request forbidden actions are invalid")
    checks = value.get("required_checks")
    if not isinstance(checks, list) or not checks or len(set(checks)) != len(checks) or not all(
        isinstance(check, str) and check for check in checks
    ):
        raise CloseoutQueueError("closeout request required_checks is invalid")
    if checks != list(REQUIRED_CLOSEOUT_CHECKS):
        raise CloseoutQueueError("closeout request weakens or reorders required checks")
    receipt_path = value.get("receipt_path")
    expected = _expected_receipt_path(state_root, request_id)
    if not isinstance(receipt_path, str) or not _receipt_path_matches(
        receipt_path, expected=expected, repo_root=repo["root"]
    ):
        raise CloseoutQueueError("closeout request receipt_path escapes or mismatches state root")
    if value.get("request_schema") != "tools/agents/schemas/closeout-request.schema.json":
        raise CloseoutQueueError("closeout request schema pointer is invalid")
    if value.get("receipt_schema") != "tools/agents/schemas/closeout-receipt.schema.json":
        raise CloseoutQueueError("closeout receipt schema pointer is invalid")
    return value


def validate_receipt(
    request: object,
    receipt: object,
    *,
    state_root: Path = DEFAULT_STATE_ROOT,
) -> dict[str, Any]:
    """Validate one release-orchestrator result against its exact request."""

    request = validate_request(request, state_root=state_root)
    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS:
        raise CloseoutQueueError("closeout receipt fields do not match the v1 contract")
    if receipt.get("schema") != "seam-agent-closeout-receipt/v1":
        raise CloseoutQueueError("unsupported closeout receipt schema")
    for field in ("request_id", "request_sha256", "session_id"):
        if receipt.get(field) != request.get(field):
            raise CloseoutQueueError(f"closeout receipt {field} does not match request")
    _timestamp(receipt.get("completed_at"), label="receipt completed_at")
    status = receipt.get("status")
    if status not in {"QUALIFIED", "NOT_QUALIFIED", "BLOCKED", "INDETERMINATE"}:
        raise CloseoutQueueError("closeout receipt status is invalid")
    supersedes = receipt.get("supersedes_request_ids")
    if (
        not _string_list(supersedes, maximum=128, maximum_length=200)
        or len(set(supersedes)) != len(supersedes)
        or any(not SAFE_ID.fullmatch(item) for item in supersedes)
        or request["request_id"] in supersedes
    ):
        raise CloseoutQueueError("closeout receipt supersession list is invalid")
    if status != "QUALIFIED" and supersedes:
        raise CloseoutQueueError(
            "only a QUALIFIED receipt may supersede older requests"
        )
    scope = receipt.get("scope")
    if not isinstance(scope, dict) or set(scope) != {
        "head",
        "diff_fingerprint",
        "matches_request",
    }:
        raise CloseoutQueueError("closeout receipt scope fields are invalid")
    if not isinstance(scope.get("head"), str) or not COMMIT.fullmatch(scope["head"]):
        raise CloseoutQueueError("closeout receipt scope.head is invalid")
    if not isinstance(scope.get("diff_fingerprint"), str) or not SHA256.fullmatch(
        scope["diff_fingerprint"]
    ):
        raise CloseoutQueueError("closeout receipt scope.diff_fingerprint is invalid")
    if not isinstance(scope.get("matches_request"), bool):
        raise CloseoutQueueError("closeout receipt scope.matches_request is invalid")
    exact_scope = (
        scope["head"] == request["repo"]["head"]
        and scope["diff_fingerprint"] == request["repo"]["diff_fingerprint"]
    )
    if scope["matches_request"] != exact_scope:
        raise CloseoutQueueError("closeout receipt scope consistency is invalid")
    tdd = receipt.get("tdd")
    if not isinstance(tdd, dict) or set(tdd) != {"status", "evidence"}:
        raise CloseoutQueueError("closeout receipt tdd fields are invalid")
    if tdd.get("status") not in {
        "TDD_PROVEN",
        "TDD_UNPROVEN",
        "TDD_NOT_REQUIRED",
    } or not _string_list(tdd.get("evidence"), maximum=128):
        raise CloseoutQueueError("closeout receipt tdd evidence is invalid")
    checks = receipt.get("checks")
    if not isinstance(checks, list) or len(checks) > 128:
        raise CloseoutQueueError("closeout receipt checks are invalid")
    requirements: list[str] = []
    for check in checks:
        if not isinstance(check, dict) or set(check) != {
            "requirement",
            "command",
            "status",
            "exit_code",
            "evidence",
        }:
            raise CloseoutQueueError("closeout receipt check fields are invalid")
        if (
            not isinstance(check.get("requirement"), str)
            or not 1 <= len(check["requirement"]) <= 2000
        ):
            raise CloseoutQueueError("closeout receipt check requirement is invalid")
        requirements.append(check["requirement"])
        if (
            not isinstance(check.get("command"), str)
            or not 1 <= len(check["command"]) <= 2000
        ):
            raise CloseoutQueueError("closeout receipt check command is invalid")
        if check.get("status") not in {"PASS", "FAIL", "BLOCKED", "NOT_RUN"}:
            raise CloseoutQueueError("closeout receipt check status is invalid")
        if isinstance(check.get("exit_code"), bool) or not isinstance(
            check.get("exit_code"), (int, type(None))
        ):
            raise CloseoutQueueError("closeout receipt check exit_code is invalid")
        if (
            not isinstance(check.get("evidence"), str)
            or not 1 <= len(check["evidence"]) <= 2000
        ):
            raise CloseoutQueueError("closeout receipt check evidence is invalid")
    if requirements != request["required_checks"]:
        raise CloseoutQueueError("closeout receipt checks do not cover exact requirements")
    continuity = receipt.get("continuity")
    if not isinstance(continuity, dict) or set(continuity) != {"status", "evidence"}:
        raise CloseoutQueueError("closeout receipt continuity fields are invalid")
    if continuity.get("status") not in {
        "PASS",
        "FAIL",
        "BLOCKED",
        "NOT_RUN",
    } or not _string_list(continuity.get("evidence"), maximum=32):
        raise CloseoutQueueError("closeout receipt continuity evidence is invalid")
    alignment = receipt.get("project_alignment")
    if not isinstance(alignment, dict) or set(alignment) != {"status", "evidence"}:
        raise CloseoutQueueError("closeout receipt project_alignment fields are invalid")
    if alignment.get("status") not in {
        "ALIGNED",
        "DRIFTED",
        "INDETERMINATE",
    } or not _string_list(alignment.get("evidence"), maximum=32):
        raise CloseoutQueueError("closeout receipt project alignment is invalid")
    if (
        not isinstance(receipt.get("next_action"), str)
        or not receipt["next_action"].strip()
        or len(receipt["next_action"]) > 2000
    ):
        raise CloseoutQueueError("closeout receipt next_action is required")
    if status == "QUALIFIED":
        if request["repo"]["changed_paths_truncated"]:
            raise CloseoutQueueError("QUALIFIED receipt cannot admit truncated request scope")
        if not exact_scope:
            raise CloseoutQueueError("QUALIFIED receipt does not match exact request scope")
        if tdd["status"] != request["tdd_evidence"]["status"] or tdd[
            "status"
        ] not in {"TDD_PROVEN", "TDD_NOT_REQUIRED"}:
            raise CloseoutQueueError("QUALIFIED receipt lacks admissible request TDD evidence")
        if any(
            check["status"] != "PASS" or check["exit_code"] != 0
            for check in checks
        ):
            raise CloseoutQueueError("QUALIFIED receipt has a non-passing required check")
        if continuity["status"] != "PASS":
            raise CloseoutQueueError("QUALIFIED receipt lacks passing continuity evidence")
        if alignment["status"] != "ALIGNED":
            raise CloseoutQueueError("QUALIFIED receipt is not aligned with the project plan")
    elif status == "NOT_QUALIFIED":
        failed = (
            tdd["status"] == "TDD_UNPROVEN"
            or any(check["status"] == "FAIL" for check in checks)
            or continuity["status"] == "FAIL"
            or alignment["status"] == "DRIFTED"
        )
        if not failed:
            raise CloseoutQueueError("NOT_QUALIFIED receipt has no failed requirement")
    elif status == "BLOCKED":
        blocked = (
            any(check["status"] == "BLOCKED" for check in checks)
            or continuity["status"] == "BLOCKED"
        )
        if not blocked:
            raise CloseoutQueueError("BLOCKED receipt has no blocked requirement")
    else:
        indeterminate = (
            not exact_scope
            or request["repo"]["changed_paths_truncated"]
            or any(check["status"] == "NOT_RUN" for check in checks)
            or continuity["status"] == "NOT_RUN"
            or alignment["status"] == "INDETERMINATE"
        )
        if not indeterminate:
            raise CloseoutQueueError(
                "INDETERMINATE receipt has no incomplete or drifting evidence"
            )
    return receipt


def _canonical_record(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _publish_record_once(path: Path, encoded: bytes) -> bool:
    """Publish one immutable record, returning false if its name already exists."""

    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.tmp.",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            return False
        os.chmod(path, 0o600)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return True
    finally:
        temporary.unlink(missing_ok=True)


def _stored_receipts(
    request: dict[str, Any], *, state_root: Path
) -> list[tuple[Path, dict[str, Any]]]:
    """Load every immutable receipt for a request, rejecting unsafe storage."""

    paths: list[Path] = []
    canonical = _expected_receipt_path(state_root, request["request_id"])
    receipt_root = canonical.parent
    if os.path.lexists(receipt_root):
        if receipt_root.is_symlink() or not receipt_root.is_dir():
            raise CloseoutQueueError(
                "closeout receipt directory must be a real directory"
            )
        if receipt_root.resolve() != receipt_root:
            raise CloseoutQueueError(
                "closeout receipt directory escapes its state root"
            )
    if os.path.lexists(canonical):
        paths.append(canonical)

    attempt_root = _receipt_attempt_root(state_root)
    if os.path.lexists(attempt_root):
        if attempt_root.is_symlink() or not attempt_root.is_dir():
            raise CloseoutQueueError(
                "closeout receipt-attempt directory must be a real directory"
            )
        if attempt_root.resolve() != attempt_root:
            raise CloseoutQueueError(
                "closeout receipt-attempt directory escapes its state root"
            )
        paths.extend(
            sorted(
                attempt_root.glob(f"{request['request_id']}-*.json"),
                key=lambda item: item.name,
            )
        )

    stored: list[tuple[Path, dict[str, Any]]] = []
    for path in paths:
        receipt = validate_receipt(
            request, _load_json(path), state_root=state_root
        )
        if path != canonical:
            expected = _receipt_attempt_path(
                state_root, request["request_id"], _canonical_record(receipt)
            )
            if path != expected:
                raise CloseoutQueueError(
                    "closeout receipt attempt content address does not match content"
                )
        stored.append((path, receipt))
    return stored


def _request_root(state_root: Path) -> Path:
    return state_root.resolve() / "requests"


def _validated_request_root(state_root: Path) -> Path | None:
    root = _request_root(state_root)
    if not os.path.lexists(root):
        return None
    if root.is_symlink() or not root.is_dir():
        raise CloseoutQueueError("closeout request directory must be a real directory")
    if root.resolve() != root:
        raise CloseoutQueueError("closeout request directory escapes its state root")
    return root


def _load_queued_request(request_id: str, *, state_root: Path) -> dict[str, Any]:
    root = _validated_request_root(state_root)
    if root is None:
        raise CloseoutQueueError("closeout request directory is missing")
    path = root / f"{request_id}.json"
    if not os.path.lexists(path):
        raise CloseoutQueueError("closeout queued request is missing")
    request = validate_request(_load_json(path), state_root=state_root)
    if request["request_id"] != request_id:
        raise CloseoutQueueError("closeout queued request identity is inconsistent")
    return request


def _load_queued_requests(state_root: Path) -> list[dict[str, Any]]:
    root = _validated_request_root(state_root)
    if root is None:
        return []
    requests: list[dict[str, Any]] = []
    identities: set[str] = set()
    for path in sorted(root.glob("*.json"), key=lambda item: item.name):
        request = validate_request(_load_json(path), state_root=state_root)
        if path.name != f"{request['request_id']}.json":
            raise CloseoutQueueError("closeout request filename mismatches its identity")
        if request["request_id"] in identities:
            raise CloseoutQueueError("duplicate closeout request identity")
        identities.add(request["request_id"])
        requests.append(request)
    return requests


def _receipt_is_dispositive(
    request: dict[str, Any], receipt: dict[str, Any]
) -> bool:
    """Return whether a receipt may close or supersede its request."""

    return receipt["status"] == "QUALIFIED" and not (
        request["change_class"] == "runtime"
        and "cycles" not in request["tdd_evidence"]
    )


def _validate_supersession_targets(
    request: dict[str, Any],
    receipt: dict[str, Any],
    *,
    state_root: Path,
    requests_by_id: dict[str, dict[str, Any]] | None = None,
) -> None:
    for request_id in receipt["supersedes_request_ids"]:
        target = (
            requests_by_id.get(request_id)
            if requests_by_id is not None
            else _load_queued_request(request_id, state_root=state_root)
        )
        if target is None:
            raise CloseoutQueueError("superseded closeout request is missing")
        identity_fields = ("root", "worktree", "branch")
        if any(
            target["repo"][field] != request["repo"][field]
            for field in identity_fields
        ):
            raise CloseoutQueueError(
                "closeout receipt cannot supersede another repository lineage"
            )
        if _timestamp(
            target["created_at"], label="superseded request created_at"
        ) >= _timestamp(request["created_at"], label="request created_at"):
            raise CloseoutQueueError(
                "closeout receipt may supersede only an older exact-state request"
            )
        target_receipts = _stored_receipts(target, state_root=state_root)
        if not any(
            not _receipt_is_dispositive(target, target_receipt)
            for _, target_receipt in target_receipts
        ):
            raise CloseoutQueueError(
                "closeout supersession requires validated non-qualified evidence"
            )


def _live_scope_signature(
    repo_root: Path, base_sha: str | None
) -> tuple[str, tuple[str, ...], str]:
    head = _git_text(repo_root, "rev-parse", "HEAD")
    paths, _ = _changed_paths(repo_root, base_sha)
    fingerprint = _fingerprint(repo_root, head, base_sha, paths)
    if _git_text(repo_root, "rev-parse", "HEAD") != head:
        raise CloseoutQueueError("closeout live Git scope drifted during admission")
    return head, tuple(paths), fingerprint


def _verify_live_scope(
    request: dict[str, Any], receipt: dict[str, Any]
) -> None:
    repo = request["repo"]
    try:
        repo_root = Path(repo["root"]).resolve(strict=True)
        if repo_root != Path(repo["worktree"]).resolve(strict=True):
            raise CloseoutQueueError("closeout request worktree is no longer available")
        if _git_text(repo_root, "rev-parse", "--show-toplevel") != str(repo_root):
            raise CloseoutQueueError("closeout request root is no longer the active Git root")
        first = _live_scope_signature(repo_root, repo["base_sha"])
        final = _live_scope_signature(repo_root, repo["base_sha"])
    except (OSError, RuntimeError, SessionEndError) as exc:
        raise CloseoutQueueError(
            "closeout live Git scope could not be recomputed"
        ) from exc
    if first != final:
        raise CloseoutQueueError("closeout live Git scope did not remain stable")
    head, _, fingerprint = final
    live_scope = (head, fingerprint)
    request_scope = (repo["head"], repo["diff_fingerprint"])
    receipt_scope = (
        receipt["scope"]["head"],
        receipt["scope"]["diff_fingerprint"],
    )
    if receipt["scope"]["matches_request"] and live_scope != request_scope:
        raise CloseoutQueueError("closeout live Git scope drifted from request")
    if not receipt["scope"]["matches_request"]:
        if live_scope == request_scope:
            raise CloseoutQueueError(
                "closeout receipt claims drift while live scope still matches request"
            )
        if live_scope != receipt_scope:
            raise CloseoutQueueError(
                "closeout receipt mismatch scope does not describe stable live Git scope"
            )


def store_receipt(
    request: object,
    receipt: object,
    *,
    state_root: Path = DEFAULT_STATE_ROOT,
) -> dict[str, str]:
    """Validate then atomically publish a root-owned receipt without clobbering."""

    state_root = state_root.resolve()
    request = validate_request(request, state_root=state_root)
    queued_request = _load_queued_request(request["request_id"], state_root=state_root)
    if queued_request != request:
        raise CloseoutQueueError("closeout request differs from its queued record")
    receipt = validate_receipt(request, receipt, state_root=state_root)
    if receipt["status"] == "QUALIFIED" and not _receipt_is_dispositive(
        request, receipt
    ):
        raise CloseoutQueueError(
            "QUALIFIED receipt requires independently recomputable cycle evidence"
        )
    _validate_supersession_targets(request, receipt, state_root=state_root)
    encoded = _canonical_record(receipt)
    stored = _stored_receipts(request, state_root=state_root)
    for existing_path, existing in stored:
        if _canonical_record(existing) == encoded:
            _verify_live_scope(request, receipt)
            status = (
                "ALREADY_STORED"
                if existing_path
                == _expected_receipt_path(state_root, request["request_id"])
                else "ALREADY_STORED_ATTEMPT"
            )
            return {"status": status, "receipt_path": str(existing_path)}
    if any(_receipt_is_dispositive(request, existing) for _, existing in stored):
        raise CloseoutQueueError("conflicting qualified closeout receipt already exists")

    if receipt["status"] == "QUALIFIED":
        from tools.agents import assurance

        try:
            result = assurance.check_request(request, state_root=state_root)
            if result["status"] == "NOT_APPLICABLE":
                result = assurance.check_session(
                    Path(request["repo"]["root"]), request["session_id"]
                )
        except assurance.AssuranceError as exc:
            raise CloseoutQueueError(str(exc)) from exc
        if result["status"] == "NOT_APPLICABLE" and assurance.enforcement_active(
            Path(request["repo"]["root"])
        ):
            raise CloseoutQueueError("qualified closeout session is not registered")
        if result["status"] not in {"PASS", "NOT_APPLICABLE"}:
            raise CloseoutQueueError("qualified closeout lacks accepted assurance")
        try:
            transition = assurance.successor_transition(
                Path(request["repo"]["root"]), request["session_id"]
            )
        except assurance.AssuranceError as exc:
            raise CloseoutQueueError(str(exc)) from exc
        if (
            transition is not None
            and transition["request_id"] not in receipt["supersedes_request_ids"]
        ):
            raise CloseoutQueueError(
                "qualified successor receipt must supersede its predecessor request"
            )

    canonical = _expected_receipt_path(state_root, request["request_id"])
    if not stored:
        _ensure_state_directory(canonical.parent, label="receipt")
        _verify_live_scope(request, receipt)
        if _publish_record_once(canonical, encoded):
            return {"status": "STORED", "receipt_path": str(canonical)}
        stored = _stored_receipts(request, state_root=state_root)
        for existing_path, existing in stored:
            if _canonical_record(existing) == encoded:
                _verify_live_scope(request, receipt)
                return {
                    "status": "ALREADY_STORED",
                    "receipt_path": str(existing_path),
                }
        if any(_receipt_is_dispositive(request, existing) for _, existing in stored):
            raise CloseoutQueueError(
                "conflicting qualified closeout receipt already exists"
            )

    attempt = _receipt_attempt_path(state_root, request["request_id"], encoded)
    _ensure_state_directory(attempt.parent, label="receipt-attempt")
    _verify_live_scope(request, receipt)
    if not _publish_record_once(attempt, encoded):
        existing = validate_receipt(
            request, _load_json(attempt), state_root=state_root
        )
        if _canonical_record(existing) != encoded:
            raise CloseoutQueueError("conflicting closeout receipt attempt exists")
        _verify_live_scope(request, receipt)
        return {"status": "ALREADY_STORED_ATTEMPT", "receipt_path": str(attempt)}
    return {"status": "STORED_ATTEMPT", "receipt_path": str(attempt)}


def _administrative_disposition_path(state_root: Path, request_id: str) -> Path:
    return state_root.resolve() / "administrative-dispositions" / f"{request_id}.json"


def _request_projection(request: dict[str, Any]) -> dict[str, Any]:
    projection = json.loads(json.dumps(request))
    for field in ("request_id", "request_sha256", "session_id", "created_at", "receipt_path"):
        projection.pop(field)
    projection["repo"].pop("origin_main")
    return projection


def _projection_sha256(request: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(_request_projection(request), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _administrative_eligible(request: dict[str, Any]) -> bool:
    context = request["context"]
    tdd = request["tdd_evidence"]
    return (
        request["change_class"] == "non_runtime"
        and request["repo"]["changed_paths_truncated"] is False
        and request["repo"]["base_sha"] is None
        and context["available"] is False
        and context["affected_tests"] == []
        and tdd["status"] == "TDD_NOT_REQUIRED"
        and tdd["cycle_count"] == 0
        and tdd.get("cycles", []) == []
    )


def _administrative_blocker(receipt: dict[str, Any]) -> bool:
    return (
        receipt["status"] == "BLOCKED"
        and receipt["tdd"]["status"] == "TDD_NOT_REQUIRED"
        and all(check["status"] == "PASS" and check["exit_code"] == 0 for check in receipt["checks"])
        and receipt["continuity"]["status"] == "BLOCKED"
        and receipt["project_alignment"]["status"] == "ALIGNED"
    )


def _validate_administrative_review(
    value: object,
    *,
    review_path: Path,
    state_root: Path,
    common_dir: Path,
    request: dict[str, Any],
    request_bytes: bytes,
    blocked: dict[str, Any],
    blocked_bytes: bytes,
    prior: dict[str, Any],
    prior_bytes: bytes,
    prior_receipt: dict[str, Any],
    prior_receipt_bytes: bytes,
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != ADMINISTRATIVE_REVIEW_FIELDS
        or value.get("schema") != "seam-closeout-administrative-review/v1"
    ):
        raise CloseoutQueueError("administrative review does not match its strict contract")
    if value.get("repository_common_dir") != str(common_dir):
        raise CloseoutQueueError("administrative review repository identity is invalid")
    if value.get("queue_root") != str(state_root):
        raise CloseoutQueueError("administrative review queue root is invalid")
    expected = {
        "current_request_id": request["request_id"],
        "current_request_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "current_receipt_sha256": hashlib.sha256(blocked_bytes).hexdigest(),
        "prior_request_id": prior["request_id"],
        "prior_request_sha256": hashlib.sha256(prior_bytes).hexdigest(),
        "prior_receipt_sha256": hashlib.sha256(prior_receipt_bytes).hexdigest(),
    }
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            raise CloseoutQueueError(f"administrative review {field} is invalid")
    if value.get("status") != "PASS":
        raise CloseoutQueueError("administrative review status must be PASS")
    if value.get("reason") != ADMINISTRATIVE_REASON:
        raise CloseoutQueueError("administrative review reason is invalid")
    if value.get("authority") != "admission_only":
        raise CloseoutQueueError("administrative review authority must be admission_only")
    if value.get("unresolved_findings") != []:
        raise CloseoutQueueError("administrative review findings must be empty")
    producer = value.get("producer_session_id")
    reviewer = value.get("reviewer")
    if (
        not isinstance(producer, str)
        or not SAFE_ID.fullmatch(producer)
        or not isinstance(reviewer, str)
        or not SAFE_ID.fullmatch(reviewer)
        or producer != reviewer
        or producer in {request["session_id"], prior["session_id"]}
    ):
        raise CloseoutQueueError(
            "administrative review requires immutable independent producer provenance"
        )
    reviewed_at = _timestamp(value.get("reviewed_at"), label="review reviewed_at")
    if reviewed_at <= _timestamp(blocked["completed_at"], label="blocked receipt completed_at"):
        raise CloseoutQueueError("administrative review predates the current blocked receipt")
    if reviewed_at <= _timestamp(prior_receipt["completed_at"], label="prior receipt completed_at"):
        raise CloseoutQueueError("administrative review predates prior qualification")
    if not review_path.is_absolute() or ".." in review_path.parts:
        raise CloseoutQueueError("administrative review path is unsafe")
    return value


def _validate_administrative_disposition(
    value: object, path: Path, *, state_root: Path
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != ADMINISTRATIVE_DISPOSITION_FIELDS
        or value.get("schema") != "seam-closeout-administrative-disposition/v1"
        or value.get("status") != "RECONCILED_DUPLICATE"
    ):
        raise CloseoutQueueError("administrative disposition does not match its contract")
    request_id = value.get("request_id")
    prior_id = value.get("prior_request_id")
    if (
        not isinstance(request_id, str) or not SAFE_ID.fullmatch(request_id)
        or not isinstance(prior_id, str) or not SAFE_ID.fullmatch(prior_id)
        or request_id == prior_id
        or path != _administrative_disposition_path(state_root, request_id)
    ):
        raise CloseoutQueueError("administrative disposition identity is invalid")
    bindings = (
        ("request_path", "request_bytes_sha256"),
        ("blocked_receipt_path", "blocked_receipt_bytes_sha256"),
        ("prior_request_path", "prior_request_bytes_sha256"),
        ("prior_receipt_path", "prior_receipt_bytes_sha256"),
        ("review_path", "review_bytes_sha256"),
    )
    loaded: dict[str, tuple[dict[str, Any], bytes]] = {}
    for path_field, hash_field in bindings:
        raw_path, digest = value.get(path_field), value.get(hash_field)
        if (
            not isinstance(raw_path, str) or not Path(raw_path).is_absolute()
            or ".." in Path(raw_path).parts
            or not isinstance(digest, str) or not SHA256.fullmatch(digest)
        ):
            raise CloseoutQueueError("administrative disposition artifact binding is invalid")
        loaded[path_field] = _load_json_record(Path(raw_path))
        if hashlib.sha256(loaded[path_field][1]).hexdigest() != digest:
            raise CloseoutQueueError("administrative disposition artifact changed")
    request = validate_request(loaded["request_path"][0], state_root=state_root)
    prior = validate_request(loaded["prior_request_path"][0], state_root=state_root)
    if request["request_id"] != request_id or prior["request_id"] != prior_id:
        raise CloseoutQueueError("administrative disposition request binding is invalid")
    if (
        Path(value["request_path"]) != _request_root(state_root) / f"{request_id}.json"
        or Path(value["prior_request_path"]) != _request_root(state_root) / f"{prior_id}.json"
    ):
        raise CloseoutQueueError("administrative disposition requests lack one canonical host")
    blocked = validate_receipt(request, loaded["blocked_receipt_path"][0], state_root=state_root)
    prior_receipt = validate_receipt(prior, loaded["prior_receipt_path"][0], state_root=state_root)
    if Path(value["blocked_receipt_path"]) != _expected_receipt_path(state_root, request_id):
        raise CloseoutQueueError("administrative blocked receipt is not canonically stored")
    if Path(value["prior_receipt_path"]) != _expected_receipt_path(state_root, prior_id):
        raise CloseoutQueueError("administrative prior receipt is not canonically stored")
    if not _administrative_eligible(request) or not _administrative_eligible(prior):
        raise CloseoutQueueError("administrative duplicate is not eligible")
    if not _administrative_blocker(blocked):
        raise CloseoutQueueError("administrative duplicate lacks an assurance-boundary blocker")
    if not _receipt_is_dispositive(prior, prior_receipt):
        raise CloseoutQueueError("administrative prior receipt is not dispositive")
    if _timestamp(prior_receipt["completed_at"], label="prior receipt completed_at") >= _timestamp(request["created_at"], label="request created_at"):
        raise CloseoutQueueError("administrative prior disposition does not predate duplicate")
    projection = _projection_sha256(request)
    if projection != _projection_sha256(prior) or value.get("projection_sha256") != projection:
        raise CloseoutQueueError("administrative requests are not exact duplicates")
    if value.get("current_origin_main") != request["repo"]["origin_main"] or value.get("prior_origin_main") != prior["repo"]["origin_main"]:
        raise CloseoutQueueError("administrative origin_main evidence is invalid")
    if value.get("authority") != "admission_only":
        raise CloseoutQueueError("administrative disposition authority is invalid")
    from tools.agents import assurance, context_guardian
    repo_root = Path(request["repo"]["root"])
    common_dir = assurance._common_dir(repo_root)
    _validate_administrative_review(
        loaded["review_path"][0],
        review_path=Path(value["review_path"]),
        state_root=state_root,
        common_dir=common_dir,
        request=request,
        request_bytes=loaded["request_path"][1],
        blocked=blocked,
        blocked_bytes=loaded["blocked_receipt_path"][1],
        prior=prior,
        prior_bytes=loaded["prior_request_path"][1],
        prior_receipt=prior_receipt,
        prior_receipt_bytes=loaded["prior_receipt_path"][1],
    )
    _timestamp(value.get("reconciled_at"), label="disposition reconciled_at")
    registration_path = assurance._registration_path(common_dir, request["session_id"])
    if registration_path.exists():
        registration = assurance._validate_registration(
            assurance._load(registration_path), common_dir, registration_path
        )
        if registration["worktree_root"] == str(repo_root):
            raise CloseoutQueueError(
                "administrative duplicate has a root-local registered candidate"
            )
    if context_guardian.has_unresolved_recovery(
        request["session_id"],
        state_root=repo_root / ".seam" / "orchestration" / "context",
        handoff_root=repo_root / ".context-handoffs",
    ):
        raise CloseoutQueueError("administrative duplicate has a recovery claim")
    return value


def _load_administrative_disposition(
    state_root: Path, request_id: str
) -> tuple[Path, dict[str, Any], bytes] | None:
    path = _administrative_disposition_path(state_root, request_id)
    if not os.path.lexists(path):
        return None
    value, encoded = _load_json_record(path)
    return path, _validate_administrative_disposition(value, path, state_root=state_root), encoded


def reconcile_duplicate(
    *, request_path: Path, prior_request_path: Path, prior_receipt_path: Path,
    review_path: Path, disposition_path: Path, state_root: Path
) -> dict[str, Any]:
    state_root = state_root.resolve()
    for raw_path in (request_path, prior_request_path, prior_receipt_path, review_path):
        if (
            not raw_path.is_absolute()
            or ".." in raw_path.parts
            or raw_path.is_symlink()
            or raw_path.resolve(strict=True) != raw_path
        ):
            raise CloseoutQueueError("administrative evidence path is unsafe")
    request_path = request_path.resolve(strict=True)
    prior_request_path = prior_request_path.resolve(strict=True)
    prior_receipt_path = prior_receipt_path.resolve(strict=True)
    review_path = review_path.resolve(strict=True)
    request, request_bytes = _load_json_record(request_path)
    request = validate_request(request, state_root=state_root)
    prior, prior_bytes = _load_json_record(prior_request_path)
    prior = validate_request(prior, state_root=state_root)
    expected = _administrative_disposition_path(state_root, request["request_id"])
    if disposition_path.resolve() != expected:
        raise CloseoutQueueError("administrative disposition path is not canonical")
    current_receipts = _stored_receipts(request, state_root=state_root)
    if len(current_receipts) != 1 or current_receipts[0][0] != _expected_receipt_path(state_root, request["request_id"]):
        raise CloseoutQueueError("administrative duplicate requires one canonical blocked receipt")
    blocked_path, blocked = current_receipts[0]
    blocked_bytes = _load_json_record(blocked_path)[1]
    prior_value, prior_receipt_bytes = _load_json_record(prior_receipt_path)
    prior_receipt = validate_receipt(prior, prior_value, state_root=state_root)
    if prior_receipt_path != _expected_receipt_path(state_root, prior["request_id"]):
        raise CloseoutQueueError("administrative prior receipt is not canonical")
    if not _administrative_eligible(request) or not _administrative_eligible(prior):
        raise CloseoutQueueError("administrative duplicate is not eligible")
    if not _administrative_blocker(blocked):
        raise CloseoutQueueError("administrative duplicate lacks an assurance-boundary blocker")
    if not _receipt_is_dispositive(prior, prior_receipt):
        raise CloseoutQueueError("administrative prior receipt is not dispositive")
    if _timestamp(prior_receipt["completed_at"], label="prior receipt completed_at") >= _timestamp(request["created_at"], label="request created_at"):
        raise CloseoutQueueError("administrative prior disposition does not predate duplicate")
    projection = _projection_sha256(request)
    if projection != _projection_sha256(prior):
        raise CloseoutQueueError("administrative requests are not exact duplicates")
    from tools.agents import assurance
    review_value, review_bytes = _load_json_record(review_path)
    _validate_administrative_review(
        review_value,
        review_path=review_path,
        state_root=state_root,
        common_dir=assurance._common_dir(Path(request["repo"]["root"])),
        request=request,
        request_bytes=request_bytes,
        blocked=blocked,
        blocked_bytes=blocked_bytes,
        prior=prior,
        prior_bytes=prior_bytes,
        prior_receipt=prior_receipt,
        prior_receipt_bytes=prior_receipt_bytes,
    )
    if os.path.lexists(expected):
        existing, _ = _load_json_record(expected)
        _validate_administrative_disposition(existing, expected, state_root=state_root)
        if (
            existing["request_bytes_sha256"] != hashlib.sha256(request_bytes).hexdigest()
            or existing["prior_request_bytes_sha256"] != hashlib.sha256(prior_bytes).hexdigest()
            or existing["review_bytes_sha256"] != hashlib.sha256(review_bytes).hexdigest()
        ):
            raise CloseoutQueueError("conflicting administrative disposition exists")
        return {"status": "ALREADY_RECONCILED", "disposition_path": str(expected)}
    value = {
        "schema": "seam-closeout-administrative-disposition/v1",
        "status": "RECONCILED_DUPLICATE",
        "request_id": request["request_id"],
        "request_path": str(request_path),
        "request_bytes_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "blocked_receipt_path": str(blocked_path),
        "blocked_receipt_bytes_sha256": hashlib.sha256(blocked_bytes).hexdigest(),
        "prior_request_id": prior["request_id"],
        "prior_request_path": str(prior_request_path),
        "prior_request_bytes_sha256": hashlib.sha256(prior_bytes).hexdigest(),
        "prior_receipt_path": str(prior_receipt_path),
        "prior_receipt_bytes_sha256": hashlib.sha256(prior_receipt_bytes).hexdigest(),
        "projection_sha256": projection,
        "current_origin_main": request["repo"]["origin_main"],
        "prior_origin_main": prior["repo"]["origin_main"],
        "review_path": str(review_path),
        "review_bytes_sha256": hashlib.sha256(review_bytes).hexdigest(),
        "authority": "admission_only",
        "reconciled_at": datetime.now(timezone.utc).isoformat(),
    }
    _verify_live_scope(request, blocked)
    for artifact_path, original_bytes in (
        (request_path, request_bytes),
        (blocked_path, blocked_bytes),
        (prior_request_path, prior_bytes),
        (prior_receipt_path, prior_receipt_bytes),
        (review_path, review_bytes),
    ):
        if _load_json_record(artifact_path)[1] != original_bytes:
            raise CloseoutQueueError("administrative evidence changed before publication")
    _validate_administrative_disposition(value, expected, state_root=state_root)
    encoded = _canonical_record(value)
    _ensure_state_directory(expected.parent, label="administrative disposition")
    if not _publish_record_once(expected, encoded):
        existing, _ = _load_json_record(expected)
        _validate_administrative_disposition(existing, expected, state_root=state_root)
        stable_fields = set(value) - {"reconciled_at"}
        if any(existing[field] != value[field] for field in stable_fields):
            raise CloseoutQueueError("conflicting administrative disposition exists")
        value = existing
    _validate_administrative_disposition(value, expected, state_root=state_root)
    return {"status": "RECONCILED_DUPLICATE", "disposition_path": str(expected)}


def pending(state_root: Path = DEFAULT_STATE_ROOT) -> dict[str, Any]:
    """Return validated pending requests without launching a model or writing state."""

    state_root = state_root.resolve()
    requests = _load_queued_requests(state_root)
    if not requests:
        return {"profile": "seam_release_orchestrator", "requests": [], "administrative_dispositions": []}
    requests_by_id = {request["request_id"]: request for request in requests}
    receipts_by_id: dict[str, list[dict[str, Any]]] = {}
    superseded: set[str] = set()
    for request in requests:
        stored = _stored_receipts(request, state_root=state_root)
        receipts = [receipt for _, receipt in stored]
        receipts_by_id[request["request_id"]] = receipts
        for receipt in receipts:
            if _receipt_is_dispositive(request, receipt):
                _validate_supersession_targets(
                    request,
                    receipt,
                    state_root=state_root,
                    requests_by_id=requests_by_id,
                )
                superseded.update(receipt["supersedes_request_ids"])
    pending_requests: list[dict[str, Any]] = []
    dispositions: list[dict[str, Any]] = []
    for request in requests:
        if request["request_id"] in superseded:
            continue
        if any(
            _receipt_is_dispositive(request, receipt)
            for receipt in receipts_by_id[request["request_id"]]
        ):
            continue
        pending_requests.append(request)
        disposition = _load_administrative_disposition(state_root, request["request_id"])
        if disposition is not None:
            dispositions.append({"request_id": request["request_id"], "receipt_status": "BLOCKED", "disposition": disposition[1]})
    return {"profile": "seam_release_orchestrator", "requests": pending_requests, "administrative_dispositions": dispositions}


def _git_inventory_text(repo_root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise CloseoutQueueError("closeout admission cannot inspect Git worktrees")
    return result.stdout.strip()


def _common_dir(repo_root: Path) -> Path:
    value = _git_inventory_text(
        repo_root, "rev-parse", "--path-format=absolute", "--git-common-dir"
    )
    path = Path(value)
    if not path.is_absolute():
        path = repo_root / path
    path = path.resolve(strict=True)
    if path.is_symlink() or not path.is_dir():
        raise CloseoutQueueError("closeout admission Git common directory is unsafe")
    return path


def _admission_path(common_dir: Path) -> Path:
    return common_dir / "seam-orchestration" / "queue-admission.json"


def _load_admission(path: Path, common_dir: Path) -> dict[str, Any] | None:
    if not os.path.lexists(path):
        return None
    value = _load_json(path)
    if (
        set(value) != ADMISSION_FIELDS
        or value.get("schema") != "seam-queue-admission/v1"
        or value.get("kind") != "inventory"
    ):
        raise CloseoutQueueError("closeout admission record does not match its contract")
    if value.get("repository_common_dir") != str(common_dir):
        raise CloseoutQueueError("closeout admission record has the wrong repository")
    for field in (
        "registered_roots",
        "observed_roots",
        "pending_request_ids",
        "record_sha256s",
    ):
        items = value.get(field)
        maximum_length = 3000 if field == "record_sha256s" else 1000
        if (
            not isinstance(items, list)
            or len(items) > 512
            or any(
                not isinstance(item, str)
                or not item
                or len(item) > maximum_length
                for item in items
            )
            or items != sorted(set(items))
        ):
            raise CloseoutQueueError(f"closeout admission {field} is invalid")
    _timestamp(value.get("admitted_at"), label="admission admitted_at")
    return value


def _write_admission(path: Path, value: dict[str, Any]) -> None:
    encoded = _canonical_record(value)
    _ensure_state_directory(path.parent, label="admission")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _worktree_roots(repo_root: Path) -> list[Path]:
    roots = []
    for line in _git_inventory_text(repo_root, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            roots.append(Path(line.removeprefix("worktree ")))
    if not roots:
        raise CloseoutQueueError("closeout admission found no Git worktrees")
    return roots


def _registration_root(common_dir: Path) -> Path:
    return common_dir / "seam-orchestration" / "retained-roots"


def _registration_path(common_dir: Path, registered_root: Path) -> Path:
    digest = hashlib.sha256(str(registered_root).encode("utf-8")).hexdigest()
    return _registration_root(common_dir) / f"{digest}.json"


def _load_registered_roots(common_dir: Path) -> list[Path]:
    root = _registration_root(common_dir)
    if not os.path.lexists(root):
        return []
    if root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise CloseoutQueueError("closeout retained-root registry is unsafe")
    registered: list[Path] = []
    for path in sorted(root.glob("*.json"), key=lambda item: item.name):
        value = _load_json(path)
        if (
            set(value) != ROOT_REGISTRATION_FIELDS
            or value.get("schema") != "seam-queue-admission/v1"
            or value.get("kind") != "retained-root"
            or value.get("repository_common_dir") != str(common_dir)
        ):
            raise CloseoutQueueError("closeout retained-root binding is invalid")
        raw_root = value.get("registered_root")
        if not isinstance(raw_root, str) or not raw_root or len(raw_root) > 1000:
            raise CloseoutQueueError("closeout retained-root path is invalid")
        registered_root = Path(raw_root)
        if not registered_root.is_absolute() or ".." in registered_root.parts:
            raise CloseoutQueueError("closeout retained-root path is unsafe")
        if path != _registration_path(common_dir, registered_root):
            raise CloseoutQueueError("closeout retained-root binding name is invalid")
        registered.append(registered_root)
    return registered


def _store_root_registration(common_dir: Path, registered_root: Path) -> None:
    value = {
        "schema": "seam-queue-admission/v1",
        "kind": "retained-root",
        "repository_common_dir": str(common_dir),
        "registered_root": str(registered_root),
    }
    encoded = _canonical_record(value)
    path = _registration_path(common_dir, registered_root)
    _ensure_state_directory(path.parent, label="retained-root registry")
    if _publish_record_once(path, encoded):
        return
    existing = _load_json(path)
    if _canonical_record(existing) != encoded:
        raise CloseoutQueueError("conflicting retained-root binding exists")


def _queue_record_sha256s(
    root: Path, *, allowed_dispositions: set[Path] | None = None
) -> tuple[list[str], list[str], set[Path]]:
    state_root = root / ".seam" / "orchestration" / "session-end"
    requests = _load_queued_requests(state_root)
    queue = pending(state_root)
    pending_ids = {request["request_id"] for request in queue["requests"]}
    hashes: list[str] = []
    observed_dispositions: set[Path] = set()
    for request in requests:
        hosted_elsewhere = (
            request["repo"]["root"] != str(root)
            or request["repo"]["worktree"] != str(root)
        )
        if hosted_elsewhere and request["request_id"] in pending_ids:
            raise CloseoutQueueError("retained closeout request ownership is inconsistent")
        request_path = _request_root(state_root) / f"{request['request_id']}.json"
        reread_request, request_bytes = _load_json_record(request_path)
        if reread_request != request:
            raise CloseoutQueueError("closeout request changed during admission")
        request_digest = hashlib.sha256(request_bytes).hexdigest()
        hashes.append(f"{root}|request|{request['request_id']}|{request_digest}")
        stored_receipts = _stored_receipts(request, state_root=state_root)
        if hosted_elsewhere and not stored_receipts:
            raise CloseoutQueueError(
                "historical hosted request lacks a canonical stored receipt"
            )
        for path, receipt in stored_receipts:
            reread_receipt, receipt_bytes = _load_json_record(path)
            if reread_receipt != receipt:
                raise CloseoutQueueError("closeout receipt changed during admission")
            receipt_digest = hashlib.sha256(receipt_bytes).hexdigest()
            hashes.append(
                f"{root}|receipt|{request['request_id']}|{path.name}|{receipt_digest}"
            )
        disposition = _load_administrative_disposition(state_root, request["request_id"])
        if disposition is not None:
            disposition_path, _, disposition_bytes = disposition
            observed_dispositions.add(disposition_path)
            hashes.append(
                f"{root}|administrative-disposition|{request['request_id']}|"
                f"{hashlib.sha256(disposition_bytes).hexdigest()}"
            )
            if allowed_dispositions is None or disposition_path in allowed_dispositions:
                pending_ids.discard(request["request_id"])
    return sorted(pending_ids), sorted(hashes), observed_dispositions


def _validate_queue_path(root: Path) -> None:
    current = root
    for component in (".seam", "orchestration", "session-end"):
        current = current / component
        if not os.path.lexists(current):
            return
        if current.is_symlink() or not current.is_dir():
            raise CloseoutQueueError(
                f"closeout admission queue path must be a real directory: {current}"
            )


def _admission_inventory(
    repo_root: Path,
    common_dir: Path,
    registered_roots: list[Path],
    *,
    allowed_dispositions: set[Path] | None = None,
) -> tuple[list[str], list[str], list[str], list[str]]:
    roots = sorted({str(path) for path in [*_worktree_roots(repo_root), *registered_roots]})
    request_ids: list[str] = []
    record_sha256s: list[str] = []
    observed_dispositions: set[Path] = set()
    registered_values = {str(path) for path in registered_roots}
    for raw_root in roots:
        path = Path(raw_root)
        if not os.path.lexists(path) or path.is_symlink() or not path.is_dir():
            raise CloseoutQueueError(f"closeout admission registered root is missing: {raw_root}")
        resolved = path.resolve(strict=True)
        git_metadata = resolved / ".git"
        if os.path.lexists(git_metadata):
            if _git_inventory_text(resolved, "rev-parse", "--show-toplevel") != str(resolved):
                raise CloseoutQueueError(f"closeout admission root is not a Git worktree: {raw_root}")
            if _common_dir(resolved) != common_dir:
                raise CloseoutQueueError(f"closeout admission root belongs to another repository: {raw_root}")
        elif str(resolved) not in registered_values:
            raise CloseoutQueueError(
                f"closeout admission non-Git root lacks retained ownership: {raw_root}"
            )
        _validate_queue_path(resolved)
        pending_ids, hashes, dispositions = _queue_record_sha256s(
            resolved, allowed_dispositions=allowed_dispositions
        )
        if not os.path.lexists(git_metadata) and not hashes:
            raise CloseoutQueueError(
                f"closeout admission retained root has no immutable queue evidence: {raw_root}"
            )
        request_ids.extend(pending_ids)
        record_sha256s.extend(hashes)
        observed_dispositions.update(dispositions)
    return roots, sorted(request_ids), sorted(record_sha256s), sorted(str(path) for path in observed_dispositions)


def admit(
    repo_root: Path,
    *,
    register_roots: list[Path] | None = None,
) -> dict[str, Any]:
    """Admit a stable, complete, empty closeout inventory before new writes."""

    repo_root = repo_root.resolve(strict=True)
    common_dir = _common_dir(repo_root)
    record_path = _admission_path(common_dir)
    previous = _load_admission(record_path, common_dir)
    registered = _load_registered_roots(common_dir)
    registered.extend(
        Path(value) for value in (previous or {}).get("registered_roots", [])
    )
    for path in register_roots or []:
        registered.append(path.resolve(strict=True))
    registered = [Path(value) for value in sorted({str(path) for path in registered})]
    first = _admission_inventory(repo_root, common_dir, registered)
    second = _admission_inventory(repo_root, common_dir, registered)
    if first != second:
        raise CloseoutQueueError("closeout admission inventory changed while reading")
    observed_roots, request_ids, record_sha256s, _ = second
    if request_ids:
        raise CloseoutQueueError(
            "closeout admission has unresolved requests: " + ", ".join(request_ids)
        )
    for path in registered:
        _store_root_registration(common_dir, path)
    record = {
        "schema": "seam-queue-admission/v1",
        "kind": "inventory",
        "repository_common_dir": str(common_dir),
        "registered_roots": [str(path) for path in registered],
        "observed_roots": observed_roots,
        "pending_request_ids": [],
        "record_sha256s": record_sha256s,
        "admitted_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_admission(record_path, record)
    return record


def admit_successor(
    repo_root: Path, *, request_id: str, repair_paths: list[Path]
) -> dict[str, Any]:
    """Validate the one predecessor request plus explicitly named admin repairs."""

    repo_root = repo_root.resolve(strict=True)
    common_dir = _common_dir(repo_root)
    previous = _load_admission(_admission_path(common_dir), common_dir)
    registered = _load_registered_roots(common_dir)
    registered.extend(Path(value) for value in (previous or {}).get("registered_roots", []))
    registered = [Path(value) for value in sorted({str(path) for path in registered})]
    repairs = {path.resolve(strict=True) for path in repair_paths}
    first = _admission_inventory(
        repo_root, common_dir, registered, allowed_dispositions=repairs
    )
    second = _admission_inventory(
        repo_root, common_dir, registered, allowed_dispositions=repairs
    )
    if first != second:
        raise CloseoutQueueError("successor admission inventory changed while reading")
    roots, request_ids, record_sha256s, observed = second
    if request_ids != [request_id]:
        raise CloseoutQueueError(
            "successor admission permits only its predecessor request: "
            + ", ".join(request_ids)
        )
    if {str(path) for path in repairs} != set(observed):
        raise CloseoutQueueError("successor repair paths do not match administrative dispositions")
    return {
        "kind": "successor-repair",
        "observed_roots": roots,
        "pending_request_ids": request_ids,
        "record_sha256s": record_sha256s,
    }


def validate_successor_inventory(
    repo_root: Path, transition: dict[str, Any]
) -> None:
    """Recompute a successor's retained roots and preserve its activation evidence."""

    repo_root = repo_root.resolve(strict=True)
    common_dir = _common_dir(repo_root)
    previous = _load_admission(_admission_path(common_dir), common_dir)
    registered = _load_registered_roots(common_dir)
    registered.extend(Path(value) for value in (previous or {}).get("registered_roots", []))
    registered = [Path(value) for value in sorted({str(path) for path in registered})]
    repairs = {Path(item["path"]) for item in transition["repair_artifacts"]}
    first = _admission_inventory(
        repo_root, common_dir, registered, allowed_dispositions=repairs
    )
    second = _admission_inventory(
        repo_root, common_dir, registered, allowed_dispositions=repairs
    )
    if first != second:
        raise CloseoutQueueError("successor queue inventory changed while reading")
    roots, pending_ids, record_sha256s, observed = second
    if roots != transition["queue_roots"]:
        raise CloseoutQueueError("successor retained-root inventory changed")
    if not set(transition["queue_record_sha256s"]).issubset(record_sha256s):
        raise CloseoutQueueError("successor inherited queue evidence changed")
    if {str(path) for path in repairs} != set(observed):
        raise CloseoutQueueError("successor administrative repair inventory changed")
    allowed = {transition["request_id"]}
    for root in map(Path, roots):
        for request in _load_queued_requests(
            root / ".seam" / "orchestration" / "session-end"
        ):
            if (
                request["session_id"] == transition["successor_session_id"]
                and request["repo"]["root"] == transition["worktree_root"]
                and request["repo"]["branch"] == transition["branch"]
                and request["repo"]["base_sha"] == transition["original_base_sha"]
            ):
                allowed.add(request["request_id"])
    unexpected = sorted(set(pending_ids) - allowed)
    if unexpected:
        raise CloseoutQueueError(
            "successor queue gained unresolved obligations: " + ", ".join(unexpected)
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and process SEAM root closeout queue records."
    )
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("pending", help="Print validated pending requests.")
    store = commands.add_parser("store", help="Validate and atomically store a receipt.")
    store.add_argument("--request", type=Path, required=True)
    store.add_argument("--receipt", type=Path, required=True)
    admission = commands.add_parser(
        "admit", help="Admit a stable empty inventory across all retained roots."
    )
    admission.add_argument("--register-root", type=Path, action="append", default=[])
    duplicate = commands.add_parser(
        "reconcile-duplicate",
        help="Record an admission-only disposition for one repeated administrative tail.",
    )
    duplicate.add_argument("--request", type=Path, required=True)
    duplicate.add_argument("--prior-request", type=Path, required=True)
    duplicate.add_argument("--prior-receipt", type=Path, required=True)
    duplicate.add_argument("--review", type=Path, required=True)
    duplicate.add_argument("--disposition", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the deterministic queue boundary; never launch a model itself."""

    args = _parser().parse_args(argv)
    try:
        if args.command == "pending":
            result = pending(args.state_root)
        elif args.command == "admit":
            result = admit(args.repo_root, register_roots=args.register_root)
        elif args.command == "reconcile-duplicate":
            result = reconcile_duplicate(
                request_path=args.request,
                prior_request_path=args.prior_request,
                prior_receipt_path=args.prior_receipt,
                review_path=args.review,
                disposition_path=args.disposition,
                state_root=args.state_root,
            )
        else:
            request = _load_json(args.request)
            receipt = _load_json(args.receipt)
            result = store_receipt(
                request,
                receipt,
                state_root=args.state_root,
            )
    except CloseoutQueueError as exc:
        print(f"closeout queue rejected input: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
