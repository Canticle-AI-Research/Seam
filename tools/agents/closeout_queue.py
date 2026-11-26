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
# The most entries an admission record list may hold; the reader rejects more.
ADMISSION_INVENTORY_LIMIT = 512
RETAINED_ROOT_PATH_LIMIT = 1000
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
RETIREMENT_FIELDS = {
    "surviving_receipts",
    "schema", "kind", "request_id", "request_path", "request_bytes_sha256",
    "receipt_path", "receipt_bytes_sha256", "missing_request_ids",
    "preserved_ref", "preserved_commit", "review_path", "review_bytes_sha256",
    "authorization_path", "authorization_bytes_sha256",
    "operator_authority", "authority", "retired_at",
}
RETIREMENT_AUTHORIZATION_FIELDS = {
    "schema", "repository_common_dir", "operator_authority", "approved_at",
    "reviewer", "entries",
}
RETIREMENT_AUTHORIZATION_ENTRY_FIELDS = {
    "surviving_receipts",
    "queue_root", "request_id", "request_sha256", "receipt_sha256", "kind",
    "missing_request_ids", "scope_truncated", "omitted_scope_disposal_authorized",
    "captured_paths_sha256", "acknowledged_hidden_paths",
}
RETIREMENT_REVIEW_FIELDS = {
    "surviving_receipts",
    "schema", "repository_common_dir", "queue_root", "kind", "request_id",
    "request_sha256", "receipt_sha256", "missing_request_ids", "preserved_ref",
    "preserved_commit", "operator_authority", "producer_session_id", "reviewer",
    "reviewed_at", "status", "reason", "authority", "unresolved_findings",
}
# A queue record may be retired only for one of these named reasons.
RETIREMENT_REASONS = {
    "ABANDONED_REQUEST": "NO_UNIQUE_WORK_PRESERVED_COMMIT",
    "MISSING_SUPERSESSION_TARGETS": "UNRECOVERABLE_SUPERSESSION_TARGETS",
}
OPERATOR_AUTHORITY = re.compile(r"^HISTORY#[0-9]{1,6}$")
# Only refs the forge keeps durably: protected main and immutable pull-request heads.
PRESERVED_REF = re.compile(r"^refs/(heads/main|pull/[0-9]{1,9}/head)$")
RETIREMENT_SIGNATURE_TIMEOUT_SECONDS = 300


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
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_NONBLOCK", 0),
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise CloseoutQueueError(
                f"closeout record must be a regular file: {path.name}"
            )
        os.set_blocking(descriptor, True)
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
    retired_missing: set[str] | None = None,
    restored: set[str] | None = None,
) -> set[str]:
    """Validate supersession; only admission may pass operator-retired lost targets."""

    validated = set()
    for request_id in receipt["supersedes_request_ids"]:
        target = (
            requests_by_id.get(request_id)
            if requests_by_id is not None
            else _load_queued_request(request_id, state_root=state_root)
        )
        if target is None and retired_missing and request_id in retired_missing:
            continue
        try:
            _validate_supersession_target(request, target, state_root)
        except CloseoutQueueError:
            if target is None or not restored or request_id not in restored:
                raise
        else:
            validated.add(request_id)
    return validated


def _validate_supersession_target(
    request: dict[str, Any], target: dict[str, Any] | None, state_root: Path
) -> None:
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


# --- Operator-authorized retirement ------------------------------------------
#
# Some queue records can never be qualified or validated again even though they
# protect no unique work: a SessionEnd request whose captured scope is stale
# while its committed work sits on a preserved ref and its untracked scratch is
# still on disk, or a qualified receipt whose superseded requests were lost
# with a removed worktree. A retirement is an immutable, admission-only record
# bound to the exact request, receipt, independent review and operator
# authorization bytes. It never grants assurance, qualification, supersession
# of new receipts, publication or merge authority, and successor admission
# never honours it. Remote preservation, ancestry and stale-scope proofs run
# when the record is written; every later read rechecks the byte bindings, the
# review and authorization contracts, registration and recovery state.
#
# An ABANDONED retirement is an explicit operator decision not to qualify the
# exact captured changes: the authorization binds the digest of the captured
# path list. Untracked bytes are not proven to survive; listed untracked paths
# absent from the captured head and current index are disposed of under that
# authorization, including staged additions later unstaged. These paths
# must still exist and remain unstaged, committed deletions in base..head must
# remain absent from the worktree and index, every index difference against the
# live HEAD is rejected independently of the captured path list, and a
# truncated capture additionally requires a clean tracked tree at the request
# head so no live tracked edit stays unqualified. A non-truncated capture
# instead requires ``acknowledged_hidden_paths`` to name, with its working-tree
# SHA-256, every indexed path outside the captured list whose regular-file
# bytes differ from its stage-zero index entry, whatever its index flags
# (skip-worktree, assume-unchanged) are now or were at capture; the index is
# proven equal to the live HEAD, and the live HEAD must be contained in the
# preserved commit or in origin refs/heads/main as read at write time, so no
# unpublished local commit can carry such bytes past the acknowledgement. A
# differing symlink is never acknowledgeable. The stability signature is taken
# again after the per-file proof. The acknowledgement is checked when the
# record is written; later
# reads do not re-inspect the working tree. Because a clean tree at
# publication cannot prove what paths omitted past the 512-path cap held at
# capture, the authorization entry's explicit
# ``omitted_scope_disposal_authorized`` flag is the operator authority for
# disposing of that unseen omitted scope.
#
# A receipt whose request is gone is ignored unless a missing-target retirement
# covers it; a covered one is identity-checked and hashed into the inventory.
#
# Residual limits: these checks cannot authenticate an operator or reviewer
# against another process running as the same OS user (shared with
# administrative dispositions, REPO_LEDGER "Evidence-backed protocol
# completion"), and a remote ref is observed when the record is written; reads
# re-prove ancestry only from local objects.
#
# Accepted residuals of the non-truncated working-tree proof:
# - Stashes and copies of bytes on other local refs cannot be enumerated; only
#   the working tree, the index and the live HEAD are proven.
# - Any gitlink (submodule) entry refuses the retirement: it has no file bytes
#   to compare or acknowledge.
# - Bytes are compared raw, so a file converted on checkout (eol=crlf,
#   core.autocrlf, a smudge filter) needs acknowledgement although Git reports
#   it clean.
# - With core.filemode=false a mode-only change passes, as it does for Git.
# - The stability signature sees only what Git reports as changed, so the proof
#   does not rely on it for flagged paths: ``_reprove_abandoned_scope`` re-reads
#   the raw bytes, mode/type and stage-zero index entry of every path the proof
#   compared, and the acknowledged set, once before anything is published and
#   again immediately before the retirement record is linked. That is a
#   point-in-time boundary, not a lock: like the receipt store, it does not
#   lock arbitrary editors, so an edit landing after the last re-read and
#   before the link, or one reverted between two reads, is not seen.
#
# ``retire`` refuses, before publishing, a retirement whose three inventory
# entries (plus any covered orphan receipts) would push the admission inventory
# past ADMISSION_INVENTORY_LIMIT. That count is right only for its moment: the
# queue keeps growing afterwards. So ``admit`` checks an inventory that holds
# retirement entries against the limits its own reader applies before it
# replaces the stored record, and on failure leaves the last readable record
# in place. Admission of a never-retired queue is unchanged: over the limit it
# still stores the record and fails on the next read, as it did before
# retirements existed.
#
# Retirement proofs run Git with every GIT_* variable stripped, so origin
# authentication must come from git config (for example core.sshCommand), not
# from GIT_SSH_COMMAND or GIT_ASKPASS. Only the proofs do: ordinary admission
# and successor inventory keep the caller's Git environment.
#
# ``retire`` intentionally creates a permanent, create-only local ref
# refs/seam/preserved/<commit> in the common directory before admission
# passes, and nothing removes it.


def _captured_paths_sha256(request: dict[str, Any]) -> str:
    repo = request["repo"]
    return hashlib.sha256(
        json.dumps(
            {"changed_paths": repo["changed_paths"], "truncated": repo["changed_paths_truncated"]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _validate_retirement_register_root(
    register_root: Path, raw_state_root: Path, state_root: Path
) -> Path:
    """Validate an explicit first-time host registration for a queue without .git."""

    if (
        not isinstance(register_root, Path)
        or not register_root.is_absolute()
        or ".." in register_root.parts
        or register_root.is_symlink()
    ):
        raise CloseoutQueueError("retirement register_root must be a canonical path")
    try:
        resolved = register_root.resolve(strict=True)
    except OSError as exc:
        raise CloseoutQueueError(
            "retirement register_root must be an existing canonical directory"
        ) from exc
    if resolved != register_root or not resolved.is_dir():
        raise CloseoutQueueError(
            "retirement register_root must be a canonical directory"
        )
    if (
        not raw_state_root.is_absolute()
        or ".." in raw_state_root.parts
        or raw_state_root.is_symlink()
        or raw_state_root != state_root
    ):
        raise CloseoutQueueError(
            "retirement state_root must be canonical when registering its host"
        )
    if state_root != resolved / ".seam" / "orchestration" / "session-end":
        raise CloseoutQueueError(
            "retirement register_root is not the canonical host of state_root"
        )
    _validate_queue_path(resolved)
    if os.path.lexists(resolved / ".git"):
        raise CloseoutQueueError(
            "retirement register_root refuses a host with .git metadata"
        )
    try:
        # What _store_root_registration would store must be what the registry
        # reader accepts, or every later admit and retire fails on reading it.
        _retained_root_path(str(resolved))
    except CloseoutQueueError as exc:
        raise CloseoutQueueError(
            f"retirement register_root cannot be registered: {exc}: the registry "
            f"reads a root of at most {RETAINED_ROOT_PATH_LIMIT} characters and this "
            f"one has {len(str(resolved))}; nothing was published"
        ) from exc
    return resolved


def _retirement_common_dir(
    request: dict[str, Any],
    state_root: Path,
    claimed: object,
    *,
    admitting_common_dir: Path | None = None,
    registering_root: Path | None = None,
) -> Path:
    """Verify the reviewed repository and bind the canonical queue host to it.

    Commit proofs run against this Git common directory, so a removed source
    checkout or an unrelated clone at its old path cannot break or redirect a
    retirement. During admission the caller has already verified the host's
    ownership, and the reviewed repository must equal the admitting one.
    Otherwise the host must be a worktree of, or a retained root registered in,
    the reviewed repository; the request source never stands in for the host.
    """

    if not isinstance(claimed, str) or not Path(claimed).is_absolute():
        raise CloseoutQueueError("retirement repository identity is invalid")
    common_dir = Path(claimed)
    if not common_dir.is_dir() or common_dir.is_symlink():
        raise CloseoutQueueError("retirement repository common directory is missing")
    if ".." in common_dir.parts or common_dir.resolve() != common_dir:
        raise CloseoutQueueError("retirement repository common directory is not canonical")
    if os.path.lexists(common_dir / "info" / "grafts"):
        raise CloseoutQueueError("retirement repository contains grafts")
    probe = _git_retirement(
        common_dir,
        f"--git-dir={common_dir}",
        "rev-parse",
        "--path-format=absolute",
        "--git-common-dir",
    )
    if probe.returncode or Path(probe.stdout.strip()).resolve() != common_dir.resolve():
        raise CloseoutQueueError("retirement repository common directory is invalid")
    if admitting_common_dir is not None:
        if common_dir.resolve() != admitting_common_dir.resolve():
            raise CloseoutQueueError("retirement belongs to another repository")
        return common_dir
    host = state_root.resolve()
    if host.parts[-3:] != (".seam", "orchestration", "session-end"):
        raise CloseoutQueueError("retirement queue host is not a canonical queue root")
    host_root = host.parents[2]
    # Same precedence as admission: live worktree metadata wins; a retained
    # registration counts only when the host has no Git metadata at all.
    if os.path.lexists(host_root / ".git"):
        top = _git_retirement(host_root, "rev-parse", "--show-toplevel")
        if top.returncode == 0 and top.stdout.strip() == str(host_root):
            try:
                if _retirement_git_common_dir(host_root) == common_dir.resolve():
                    return common_dir
            except CloseoutQueueError:
                pass
    elif host_root in _load_registered_roots(common_dir) or (
        registering_root is not None and host_root == registering_root
    ):
        return common_dir
    raise CloseoutQueueError("retirement queue host is not bound to the reviewed repository")


def _git_object(common_dir: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return _git_retirement(common_dir, f"--git-dir={common_dir}", *arguments)


def _proof_environment() -> dict[str, str]:
    # Start Git with canonical discovery, config and object/index selection.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return {**env, "GIT_NO_REPLACE_OBJECTS": "1", "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_LAZY_FETCH": "1"}


def _git_paths(repo_root: Path, *arguments: str) -> set[str]:
    result = subprocess.run(
        ["git", "--no-replace-objects", *arguments],
        cwd=repo_root, env=_proof_environment(), capture_output=True, check=False
    )
    if result.returncode:
        raise CloseoutQueueError("retirement cannot list Git paths")
    return {
        os.fsdecode(item)
        for item in result.stdout.split(b"\x00")
        if item
    }


def _index_has_path(repo_root: Path, path: str) -> bool:
    result = subprocess.run(
        ["git", "--no-replace-objects", "--literal-pathspecs", "ls-files", "-s", "-z", "--", path],
        cwd=repo_root, env=_proof_environment(),
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise CloseoutQueueError("retirement cannot inspect Git index")
    return any(item for item in result.stdout.split(b"\x00"))


def _retirement_root(state_root: Path) -> Path:
    return state_root.resolve() / "retirements"


def _retirement_evidence_root(state_root: Path) -> Path:
    # Resolved like _retirement_root, so a relative or symlinked queue root
    # names the same canonical evidence paths that the records bind.
    return state_root.resolve() / "retirement-evidence"


def _retirement_path(state_root: Path, request_id: str) -> Path:
    return _retirement_root(state_root) / f"{request_id}.json"


def _git_retirement(repo_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "--no-replace-objects", *arguments],
        cwd=repo_root, env=_proof_environment(), capture_output=True, text=True, check=False
    )


def _retirement_git_common_dir(repo_root: Path) -> Path:
    # Same answer as _common_dir, asked in the proof environment: ordinary
    # admission keeps the caller's Git environment, a retirement proof does not.
    result = _git_retirement(repo_root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if result.returncode:
        raise CloseoutQueueError("closeout admission cannot inspect Git worktrees")
    path = Path(result.stdout.strip())
    if not path.is_absolute():
        path = repo_root / path
    path = path.resolve(strict=True)
    if path.is_symlink() or not path.is_dir():
        raise CloseoutQueueError("closeout admission Git common directory is unsafe")
    return path


def _commit_contains(common_dir: Path, ancestor: str, descendant: str) -> bool:
    result = _git_object(common_dir, "merge-base", "--is-ancestor", ancestor, descendant)
    if result.returncode not in (0, 1):
        raise CloseoutQueueError("retirement cannot inspect preserved commit ancestry")
    return result.returncode == 0


def _preserved_anchor_ref(commit: str) -> str:
    return f"refs/seam/preserved/{commit}"


def _anchor_preserved_commit(common_dir: Path, commit: str) -> None:
    """Hold the preserved commit under a local ref so gc cannot prune it.

    Every admission re-proves ancestry from local objects. A commit reachable
    only through a deleted branch, or fetched without a destination, has no
    local ref; this one keeps it until an operator removes the anchor.
    """

    ref = _preserved_anchor_ref(commit)
    conflict = CloseoutQueueError(
        f"retirement preserved-commit anchor {ref} exists and does not point at the "
        "preserved commit; inspect it and remove it only if it is not needed"
    )
    if _git_object(common_dir, "symbolic-ref", "-q", ref).returncode == 0:
        raise conflict
    current = _git_object(common_dir, "rev-parse", "--verify", "--quiet", ref)
    if current.returncode == 0:
        if current.stdout.strip() != commit:
            raise conflict
        return
    # An empty old value makes this create-only, so a racing writer cannot be overwritten.
    created = _git_object(common_dir, "update-ref", "--no-deref", ref, commit, "")
    if created.returncode:
        again = _git_object(common_dir, "rev-parse", "--verify", "--quiet", ref)
        if again.returncode == 0 and again.stdout.strip() != commit:
            raise conflict
        if again.returncode:
            raise CloseoutQueueError(f"retirement cannot create preserved-commit anchor {ref}")


def _origin_ref_commit(common_dir: Path, ref: str) -> str:
    try:
        result = subprocess.run(
            ["git", "--no-replace-objects", f"--git-dir={common_dir}", "ls-remote", "--exit-code", "origin", ref],
            cwd=common_dir, env=_proof_environment(),
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CloseoutQueueError("retirement cannot reach origin to prove preserved_ref") from exc
    # ls-remote --exit-code reports 2 when origin answered without the ref; any
    # other failure means origin never answered, which proves nothing about it.
    if result.returncode not in (0, 2):
        raise CloseoutQueueError("retirement cannot reach origin to prove preserved_ref")
    matches = [
        parts[0]
        for parts in (line.split("\t") for line in result.stdout.splitlines())
        if len(parts) == 2 and parts[1] == ref
    ]
    if result.returncode or len(matches) != 1:
        raise CloseoutQueueError("retirement preserved_ref: origin does not hold it")
    return matches[0]


def _validate_retirement_review(
    value: object,
    *,
    review_path: Path,
    state_root: Path,
    common_dir: Path,
    request: dict[str, Any],
    request_bytes: bytes,
    receipt: dict[str, Any] | None,
    receipt_bytes: bytes | None,
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != RETIREMENT_REVIEW_FIELDS
        or value.get("schema") != "seam-closeout-retirement-review/v1"
    ):
        raise CloseoutQueueError("retirement review does not match its strict contract")
    if value.get("repository_common_dir") != str(common_dir):
        raise CloseoutQueueError("retirement review repository identity is invalid")
    if value.get("queue_root") != str(state_root):
        raise CloseoutQueueError("retirement review queue root is invalid")
    kind = value.get("kind")
    if kind not in RETIREMENT_REASONS:
        raise CloseoutQueueError("retirement review kind is invalid")
    expected = {
        "request_id": request["request_id"],
        "request_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "receipt_sha256": (
            hashlib.sha256(receipt_bytes).hexdigest() if receipt_bytes is not None else None
        ),
    }
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            raise CloseoutQueueError(f"retirement review {field} is invalid")
    if value.get("status") != "PASS":
        raise CloseoutQueueError("retirement review status must be PASS")
    if value.get("reason") != RETIREMENT_REASONS[kind]:
        raise CloseoutQueueError("retirement review reason is invalid")
    if value.get("authority") != "admission_only":
        raise CloseoutQueueError("retirement review authority must be admission_only")
    if value.get("unresolved_findings") != []:
        raise CloseoutQueueError("retirement review findings must be empty")
    operator_authority = value.get("operator_authority")
    if not isinstance(operator_authority, str) or not OPERATOR_AUTHORITY.fullmatch(
        operator_authority
    ):
        raise CloseoutQueueError(
            "retirement review operator_authority must name a HISTORY entry"
        )
    preserved_ref = value.get("preserved_ref")
    if not isinstance(preserved_ref, str) or not PRESERVED_REF.fullmatch(preserved_ref):
        raise CloseoutQueueError("retirement review preserved_ref is invalid")
    preserved_commit = value.get("preserved_commit")
    if not isinstance(preserved_commit, str) or not COMMIT.fullmatch(preserved_commit):
        raise CloseoutQueueError("retirement review preserved_commit is invalid")
    if not isinstance(value.get("missing_request_ids"), list):
        raise CloseoutQueueError("retirement missing_request_ids is invalid")
    missing = value["missing_request_ids"]
    if any(not isinstance(item, str) or not SAFE_ID.fullmatch(item) for item in missing):
        raise CloseoutQueueError("retirement missing_request_ids is invalid")
    absent = [item for item in missing if not os.path.lexists(_request_root(state_root) / f"{item}.json")]
    pinned = value["surviving_receipts"]
    if not isinstance(pinned, list):
        raise CloseoutQueueError("invalid surviving receipt inventory")
    expected = []
    for item in pinned:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise CloseoutQueueError("invalid surviving receipt inventory")
        path = Path(item["path"])
        target = path.stem if path.parent == Path("receipts") else path.stem.rpartition("-")[0]
        if target not in missing or target in absent:
            expected.append(item)
    if expected != _surviving_receipts(state_root, absent):
        raise CloseoutQueueError(
            "retirement surviving receipt inventory changed; restore the bound "
            "receipt bytes from backup, or restore the target request so it "
            "validates normally"
        )
    producer = value.get("producer_session_id")
    reviewer = value.get("reviewer")
    if (
        not isinstance(producer, str)
        or not SAFE_ID.fullmatch(producer)
        or not isinstance(reviewer, str)
        or not SAFE_ID.fullmatch(reviewer)
        or producer != reviewer
        or producer == request["session_id"]
    ):
        raise CloseoutQueueError(
            "retirement review requires immutable independent producer provenance"
        )
    reviewed_at = _timestamp(value.get("reviewed_at"), label="retirement review reviewed_at")
    if reviewed_at <= _timestamp(request["created_at"], label="request created_at"):
        raise CloseoutQueueError("retirement review predates its request")
    if receipt is not None and reviewed_at <= _timestamp(
        receipt["completed_at"], label="receipt completed_at"
    ):
        raise CloseoutQueueError("retirement review predates its receipt")
    if not review_path.is_absolute() or ".." in review_path.parts:
        raise CloseoutQueueError("retirement review path is unsafe")
    return value


def _validate_retirement_authorization(
    value: object,
    *,
    common_dir: Path,
    state_root: Path,
    review: dict[str, Any],
    request: dict[str, Any],
) -> dict[str, Any]:
    """Require the exact subject in a finite, operator-authorized manifest."""

    if (
        not isinstance(value, dict)
        or set(value) != RETIREMENT_AUTHORIZATION_FIELDS
        or value.get("schema") != "seam-closeout-retirement-authorization/v1"
    ):
        raise CloseoutQueueError("retirement authorization does not match its strict contract")
    if value.get("repository_common_dir") != str(common_dir):
        raise CloseoutQueueError("retirement authorization repository identity is invalid")
    if value.get("operator_authority") != review["operator_authority"]:
        raise CloseoutQueueError("retirement authorization operator_authority does not match")
    if value.get("reviewer") != review["reviewer"]:
        raise CloseoutQueueError("retirement authorization reviewer does not match")
    _timestamp(value.get("approved_at"), label="retirement authorization approved_at")
    entries = value.get("entries")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 512:
        raise CloseoutQueueError("retirement authorization entries are invalid")
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or set(entry) != RETIREMENT_AUTHORIZATION_ENTRY_FIELDS
            or not isinstance(entry.get("scope_truncated"), bool)
            or not isinstance(entry.get("omitted_scope_disposal_authorized"), bool)
        ):
            raise CloseoutQueueError("retirement authorization entry is invalid")
    truncated = request["repo"]["changed_paths_truncated"]
    subject = {
        "queue_root": str(state_root),
        "request_id": request["request_id"],
        "request_sha256": review["request_sha256"],
        "receipt_sha256": review["receipt_sha256"],
        "kind": review["kind"],
        "missing_request_ids": review["missing_request_ids"],
        "surviving_receipts": review["surviving_receipts"],
        "scope_truncated": truncated,
        "omitted_scope_disposal_authorized": truncated,
        "captured_paths_sha256": _captured_paths_sha256(request),
    }
    matches = []
    for entry in entries:
        paths = entry["acknowledged_hidden_paths"]
        if not isinstance(paths, list) or any(
            not isinstance(item, dict) or set(item) != {"path", "worktree_sha256"}
            or not isinstance(item["path"], str) or not item["path"]
            or not isinstance(item["worktree_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", item["worktree_sha256"])
            for item in paths
        ):
            raise CloseoutQueueError("retirement authorization hidden paths are invalid")
        names = [item["path"] for item in paths]
        if names != sorted(set(names)) or (
            paths and entry["kind"] != "ABANDONED_REQUEST"
        ):
            raise CloseoutQueueError("retirement authorization hidden paths are invalid")
        if entry == {**subject, "acknowledged_hidden_paths": paths}:
            matches.append(entry)
    if len(matches) != 1:
        raise CloseoutQueueError("retirement is not listed in the operator authorization")
    return matches[0]


def _check_retirement_subject(
    *,
    kind: str,
    request: dict[str, Any],
    receipt: dict[str, Any] | None,
    receipt_path: Path | None,
    missing: object,
    state_root: Path,
) -> str:
    """Validate the static subject shape; return the commit that must be preserved."""

    if kind == "ABANDONED_REQUEST":
        if receipt is not None or receipt_path is not None or missing != []:
            raise CloseoutQueueError(
                "abandoned-request retirement binds no receipt and no missing targets"
            )
        return str(request["repo"]["head"])
    if receipt is None or receipt_path is None:
        raise CloseoutQueueError("missing-target retirement requires its qualified receipt")
    stored = {
        path: value for path, value in _stored_receipts(request, state_root=state_root)
    }
    if stored.get(receipt_path) != receipt:
        raise CloseoutQueueError("missing-target retirement receipt is not a stored receipt")
    if not _receipt_is_dispositive(request, receipt):
        raise CloseoutQueueError("missing-target retirement receipt is not dispositive")
    if (
        not isinstance(missing, list)
        or not missing
        or len(missing) > 128
        or any(not isinstance(item, str) or not SAFE_ID.fullmatch(item) for item in missing)
        or missing != sorted(set(missing))
    ):
        raise CloseoutQueueError("retirement missing_request_ids is invalid")
    for item in missing:
        if item not in receipt["supersedes_request_ids"]:
            raise CloseoutQueueError(
                f"retirement target {item} was not superseded by the receipt"
            )
    return str(receipt["scope"]["head"])


class _ActiveOwnership(CloseoutQueueError):
    pass


def _check_abandoned_ownership(request: dict[str, Any], common_dir: Path) -> None:
    """Refuse a request still owned by a registered candidate or recovery claim."""

    from tools.agents import assurance, context_guardian

    repo_root = Path(request["repo"]["root"])
    try:
        registration_path = assurance._registration_path(common_dir, request["session_id"])
        if registration_path.exists():
            registration = assurance._validate_registration(
                assurance._load(registration_path), common_dir, registration_path
            )
            if registration["worktree_root"] == str(repo_root):
                raise _ActiveOwnership(
                    "retirement request has a root-local registered candidate"
                )
        if repo_root.is_dir() and context_guardian.has_unresolved_recovery(
            request["session_id"],
            state_root=repo_root / ".seam" / "orchestration" / "context",
            handoff_root=repo_root / ".context-handoffs",
        ):
            raise _ActiveOwnership("retirement request has an unresolved recovery claim")
    except (OSError, assurance.AssuranceError, context_guardian.ContextGuardianError) as exc:
        # Unreadable ownership state is never evidence that nobody owns the work.
        raise CloseoutQueueError(
            "retirement cannot verify registration or recovery ownership"
        ) from exc


def _worktree_blob(root: Path, name: str, mode: str, oid: str, filemode: bool) -> tuple[bool, str | None]:
    path = root / name
    if path.parent.resolve() != path.parent:
        return False, None
    blob = hashlib.new("sha1" if len(oid) == 40 else "sha256")
    digest = hashlib.sha256()
    try:
        if path.is_symlink():
            actual_mode = "120000"
            target = os.fsencode(os.readlink(path))
            blob.update(f"blob {len(target)}\0".encode())
            blob.update(target)
            digest.update(target)
        else:
            if not path.is_file():
                return False, None
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(fd)
                actual_mode = "100755" if info.st_mode & stat.S_IXUSR else "100644"
                if not stat.S_ISREG(info.st_mode):
                    return False, None
                blob.update(f"blob {info.st_size}\0".encode())
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    blob.update(block)
                    digest.update(block)
    except OSError as exc:
        raise CloseoutQueueError(f"retirement cannot inspect worktree path: {name}") from exc
    regular = {"100644", "100755"}
    matches = (
        mode == actual_mode or (not filemode and mode in regular and actual_mode in regular)
    ) and oid == blob.hexdigest()
    if not matches and not (mode in regular and actual_mode in regular):
        # A differing symlink, on either side, has no acknowledgeable digest:
        # a SHA-256 names the bytes of a regular file and nothing else.
        return False, None
    return matches, digest.hexdigest()


def _worktree_kind(root: Path, name: str) -> int | None:
    """File type and owner-execute bit of a working-tree path, unfollowed."""

    try:
        mode = os.lstat(root / name).st_mode
    except OSError:
        return None
    return stat.S_IFMT(mode) | (mode & stat.S_IXUSR)


def _reprove_abandoned_scope(proof: dict[str, Any]) -> None:
    """Refuse unless everything the proof examined still reads the same.

    Git-visible dirt is not consulted: a skip-worktree or assume-unchanged
    path is invisible to it. The live HEAD, every stage-zero index entry, the
    raw bytes and mode/type of every compared path, the presence of every
    captured path and the acknowledged set are derived again and must equal
    what the proof compared.
    """

    root = proof["root"]
    head = _git_retirement(root, "rev-parse", "--verify", "HEAD")
    changed = None
    hidden = {}
    if head.returncode or head.stdout.strip() != proof["head"]:
        changed = "HEAD"
    elif _git_paths(root, "ls-files", "-s", "-z") != proof["index"]:
        changed = "index"
    else:
        for name, present in proof["present"].items():
            if os.path.lexists(root / name) != present:
                changed = name
        for name, (mode, oid, *compared) in sorted(proof["examined"].items()):
            matches, digest = _worktree_blob(root, name, mode, oid, proof["filemode"])
            if [matches, digest, _worktree_kind(root, name)] != compared:
                changed = name
                break
            if not matches:
                hidden[name] = digest
    if changed is None and hidden != proof["approved"]:
        changed = "acknowledged hidden paths"
    if changed is not None:
        raise CloseoutQueueError(
            f"retirement live scope did not remain stable: {changed} changed after "
            "it was compared and before the retirement record was published"
        )


def _retirement_signatures(root: Path, base: str | None) -> list:
    # Isolate the environment inherited by the shared fingerprint helper's Git children.
    script = (
        "import sys,json; from pathlib import Path; sys.path.insert(0,sys.argv[1]); "
        "from tools.agents.closeout_queue import _live_scope_signature as signature; "
        "print(json.dumps([signature(Path(sys.argv[2]), json.loads(sys.argv[3])) "
        "for _ in range(2)]))"
    )
    failure = CloseoutQueueError("retirement live Git scope could not be recomputed")
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-B", "-c", script, str(REPO_ROOT), str(root), json.dumps(base)],
            env=_proof_environment(), capture_output=True, check=False,
            timeout=RETIREMENT_SIGNATURE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise failure from exc
    if result.returncode:
        raise failure
    try:
        signatures = json.loads(result.stdout)
    except ValueError as exc:
        raise failure from exc
    if (
        not isinstance(signatures, list)
        or len(signatures) != 2
        or any(
            not isinstance(item, list)
            or len(item) != 3
            or not isinstance(item[0], str)
            or not isinstance(item[1], list)
            or not isinstance(item[2], str)
            for item in signatures
        )
    ):
        raise failure
    return signatures


def _prove_live_head_published(
    common_dir: Path, live_head: str, preserved_ref: str, preserved_commit: str
) -> None:
    """Refuse a live HEAD holding commits the origin did not hold at write time."""

    if _commit_contains(common_dir, live_head, preserved_commit):
        return
    if preserved_ref != "refs/heads/main":
        # preserved_ref was read from origin moments ago and equals
        # preserved_commit; main is the only other ref a retirement accepts.
        main = _origin_ref_commit(common_dir, "refs/heads/main")
        if (
            _git_object(common_dir, "cat-file", "-e", main + "^{commit}").returncode == 0
            and _commit_contains(common_dir, live_head, main)
        ):
            return
    raise CloseoutQueueError(
        f"retirement live HEAD {live_head} is not published: neither the preserved "
        "commit nor origin refs/heads/main contains it; publish its commits to "
        "origin main and fetch them, or retire with the request root checked out "
        "at a published commit"
    )


def _prove_abandoned_scope(
    request: dict[str, Any],
    common_dir: Path,
    acknowledged: list,
    *,
    preserved_ref: str,
    preserved_commit: str,
) -> dict[str, Any]:
    """Prove the captured scope is stale and its tracked state is preserved.

    Returns what was examined, for _reprove_abandoned_scope.
    """

    repo = request["repo"]
    try:
        repo_root = Path(repo["root"]).resolve(strict=True)
        # Every proof below runs in the request root. If that path is now only
        # a directory inside some other worktree, Git would answer for the
        # enclosing checkout, relative to a subdirectory.
        if _git_retirement(repo_root, "rev-parse", "--show-toplevel").stdout.strip() != str(repo_root):
            raise CloseoutQueueError(
                "abandoned request root is no longer the active Git root"
            )
        if _retirement_git_common_dir(repo_root) != common_dir.resolve():
            raise CloseoutQueueError("abandoned request root belongs to another repository")
        first, final = _retirement_signatures(repo_root, repo["base_sha"])
    except CloseoutQueueError:
        raise
    except (OSError, RuntimeError) as exc:
        raise CloseoutQueueError(
            "retirement live Git scope could not be recomputed"
        ) from exc
    head = repo["head"]
    if first != final:
        raise CloseoutQueueError("retirement live scope did not remain stable")
    if (final[0], final[2]) == (head, repo["diff_fingerprint"]):
        raise CloseoutQueueError(
            "retirement request scope still matches the live tree; qualify it instead"
        )
    _prove_live_head_published(common_dir, final[0], preserved_ref, preserved_commit)
    tree = {}
    for record in _git_paths(repo_root, "ls-tree", "-r", "-z", head):
        metadata, name = record.split("\t", 1)
        mode, _, oid = metadata.split()
        tree[name] = mode, oid
    tracked = set(tree)
    flagged = {
        record[2:] for record in _git_paths(repo_root, "ls-files", "-v", "-z")
        if record[0].islower() or record[0] == "S"
    }
    committed: set[str] = set()
    if repo["base_sha"]:
        committed = _git_paths(
            repo_root,
            "diff",
            "--no-renames",
            "--name-only",
            "-z",
            repo["base_sha"],
            head,
        )
    if repo["changed_paths_truncated"]:
        if final[0] != head:
            raise CloseoutQueueError(
                "truncated retirement requires the live HEAD to equal the request head"
            )
        for arguments in (("diff", "--quiet", "HEAD"), ("diff", "--cached", "--quiet")):
            if _git_retirement(repo_root, *arguments).returncode:
                raise CloseoutQueueError(
                    "truncated retirement requires a clean tracked tree at the request head"
                )
    mode_setting = _git_retirement(repo_root, "config", "--type=bool", "--default=true", "--get", "core.filemode")
    if mode_setting.returncode or mode_setting.stdout.strip() not in {"true", "false"}:
        raise CloseoutQueueError("retirement cannot determine core.filemode")
    filemode = mode_setting.stdout.strip() == "true"
    hidden = {}
    examined: dict[str, tuple] = {}
    present: dict[str, bool] = {}

    def compare(name: str, mode: str, oid: str) -> tuple[bool, str | None]:
        result = _worktree_blob(repo_root, name, mode, oid, filemode)
        examined[name] = (mode, oid, *result, _worktree_kind(repo_root, name))
        return result

    # A truncated capture is compared with the request head, which the checks
    # above and below prove equal to the live HEAD and to the index.
    comparison_paths = tree.keys() | flagged if repo["changed_paths_truncated"] else ()
    for name in sorted(comparison_paths):
        if name not in tree:
            raise CloseoutQueueError(f"flagged path absent from captured commit: {name}")
        mode, oid = tree[name]
        matches, digest = compare(name, mode, oid)
        if not matches:
            if name not in flagged or digest is None:
                raise CloseoutQueueError(f"retirement requires a clean tracked tree: {name}")
            hidden[name] = digest
    for raw in repo["changed_paths"]:
        path = raw.rstrip("/")
        prefix = path + "/"
        is_tracked = path in tracked or (
            raw.endswith("/") and any(item.startswith(prefix) for item in tracked)
        )
        if is_tracked:
            if path not in committed:
                raise CloseoutQueueError(
                    f"retirement captured a dirty tracked path: {path}"
                )
            if path in flagged or path not in tree or not compare(path, *tree[path])[0]:
                raise CloseoutQueueError(f"retirement captured a flagged path or differs from its commit: {path}")
            if any(
                _git_retirement(
                    repo_root, "--literal-pathspecs", "diff", *cached, "--quiet", head, "--", path
                ).returncode
                for cached in ((), ("--cached",))
            ):
                raise CloseoutQueueError(
                    f"retirement captured a tracked path that differs from its commit: {path}"
                )
        elif path in committed:
            present[path] = False
            if os.path.lexists(repo_root / path) or _index_has_path(repo_root, path):
                raise CloseoutQueueError(
                    f"retirement captured a committed deletion that differs from its commit: {path}"
                )
        else:
            # Authorization disposes of the captured path, including an unstaged addition.
            if _index_has_path(repo_root, path):
                raise CloseoutQueueError(
                    f"retirement captured a staged addition with unpreserved tracked work: {path}"
                )
            present[path] = True
            if not os.path.lexists(repo_root / path):
                raise CloseoutQueueError(
                    f"retirement captured untracked work that is no longer present for authorized disposal: {path}"
                )
    staged_diff = _git_paths(
        repo_root, "diff", "--cached", "--no-renames", "--name-only", "-z", "HEAD"
    )
    indexed = _git_paths(repo_root, "ls-files", "--cached", "-z")
    live_tracked = _git_paths(repo_root, "ls-tree", "-r", "-z", "--name-only", "HEAD")
    staged_outside = sorted(staged_diff | (indexed ^ live_tracked))
    if staged_outside:
        raise CloseoutQueueError(
            f"retirement index differs from live HEAD at staged path: {staged_outside[0]}"
        )
    index_entries = _git_paths(repo_root, "ls-files", "-s", "-z")
    if not repo["changed_paths_truncated"]:
        # One rule for every indexed path outside the capture, whatever its
        # index flags are now or were at capture: its working-tree bytes are
        # compared with its stage-zero index entry, which the check above has
        # just proven equal to the live HEAD.
        captured = {raw.rstrip("/") for raw in repo["changed_paths"]}
        for record in sorted(index_entries):
            metadata, name = record.split("\t", 1)
            if name in captured:
                continue
            mode, oid, stage = metadata.split()
            if stage != "0":
                raise CloseoutQueueError(f"retirement requires a clean tracked tree: {name}")
            matches, digest = compare(name, mode, oid)
            if not matches:
                if digest is None:
                    raise CloseoutQueueError(f"retirement requires a clean tracked tree: {name}")
                hidden[name] = digest
    approved = {item["path"]: item["worktree_sha256"] for item in acknowledged}
    if hidden != approved:
        differences = sorted(name for name in hidden.keys() | approved.keys()
                             if hidden.get(name) != approved.get(name))
        raise CloseoutQueueError(f"retirement hidden paths differ from authorization: {differences}")
    # The signatures above predate the per-file proof; take them again so an
    # edit made while it ran is not published as proven.
    if any(later != final for later in _retirement_signatures(repo_root, repo["base_sha"])):
        raise CloseoutQueueError("retirement live scope did not remain stable")
    proof = {
        "root": repo_root, "filemode": filemode, "head": final[0], "index": index_entries,
        "examined": examined, "present": present, "approved": approved,
    }
    # Git reports nothing for a flagged path, so the signatures cannot see an
    # edit to one: read every compared path again before anything is published.
    _reprove_abandoned_scope(proof)
    return proof


def _prove_missing_supersession_targets(
    request: dict[str, Any],
    receipt: dict[str, Any],
    missing: list[str],
    *,
    state_root: Path,
) -> None:
    """Require missing_request_ids to match absent targets and validate present ones."""

    root = _validated_request_root(state_root)
    if root is None:
        raise CloseoutQueueError("closeout request directory is missing")
    absent: set[str] = set()
    present_by_id: dict[str, dict[str, Any]] = {}
    for target_id in receipt["supersedes_request_ids"]:
        if not os.path.lexists(root / f"{target_id}.json"):
            absent.add(target_id)
        else:
            present_by_id[target_id] = _load_queued_request(
                target_id, state_root=state_root
            )
    for item in missing:
        if item not in absent:
            raise CloseoutQueueError(
                f"retirement target {item} still exists in the queue"
            )
    if sorted(absent) != missing:
        omitted = ", ".join(sorted(absent - set(missing)))
        raise CloseoutQueueError(
            f"retirement missing_request_ids omits absent superseded targets: {omitted}"
        )
    _validate_supersession_targets(
        request,
        receipt,
        state_root=state_root,
        requests_by_id=present_by_id,
        retired_missing=absent,
    )


def _validate_retirement(
    value: object,
    path: Path,
    *,
    state_root: Path,
    admitting_common_dir: Path | None = None,
    registering_root: Path | None = None,
    allow_resumed: bool = False,
) -> tuple[dict[str, Any], bool]:
    if (
        not isinstance(value, dict)
        or set(value) != RETIREMENT_FIELDS
        or value.get("schema") != "seam-closeout-retirement/v1"
        or value.get("kind") not in RETIREMENT_REASONS
        or value.get("authority") != "admission_only"
    ):
        raise CloseoutQueueError("retirement does not match its contract")
    request_id = value.get("request_id")
    if (
        not isinstance(request_id, str)
        or not SAFE_ID.fullmatch(request_id)
        or path != _retirement_path(state_root, request_id)
    ):
        raise CloseoutQueueError("retirement identity is invalid")
    bindings = [
        ("request_path", "request_bytes_sha256"),
        ("review_path", "review_bytes_sha256"),
        ("authorization_path", "authorization_bytes_sha256"),
    ]
    if value["kind"] == "MISSING_SUPERSESSION_TARGETS":
        bindings.append(("receipt_path", "receipt_bytes_sha256"))
    elif value.get("receipt_path") is not None or value.get("receipt_bytes_sha256") is not None:
        raise CloseoutQueueError("abandoned-request retirement binds no receipt")
    loaded: dict[str, tuple[dict[str, Any], bytes]] = {}
    for path_field, hash_field in bindings:
        raw_path, digest = value.get(path_field), value.get(hash_field)
        if (
            not isinstance(raw_path, str)
            or not Path(raw_path).is_absolute()
            or ".." in Path(raw_path).parts
            or not isinstance(digest, str)
            or not SHA256.fullmatch(digest)
        ):
            raise CloseoutQueueError("retirement artifact binding is invalid")
        if path_field in ("review_path", "authorization_path") and (
            raw_path != str(_retirement_evidence_root(state_root) / f"{digest}.json")
        ):
            raise CloseoutQueueError("retirement evidence path is not content-addressed")
        loaded[path_field] = _load_json_record(Path(raw_path))
        if hashlib.sha256(loaded[path_field][1]).hexdigest() != digest:
            raise CloseoutQueueError("retirement artifact changed")
    if Path(value["request_path"]) != _request_root(state_root) / f"{request_id}.json":
        raise CloseoutQueueError("retirement request is not canonically queued")
    request = validate_request(loaded["request_path"][0], state_root=state_root)
    if request["request_id"] != request_id:
        raise CloseoutQueueError("retirement request binding is invalid")
    receipt = None
    receipt_bytes = None
    receipt_path = None
    if "receipt_path" in loaded:
        receipt = validate_receipt(request, loaded["receipt_path"][0], state_root=state_root)
        receipt_bytes = loaded["receipt_path"][1]
        receipt_path = Path(value["receipt_path"])
    common_dir = _retirement_common_dir(
        request,
        state_root,
        loaded["review_path"][0].get("repository_common_dir"),
        admitting_common_dir=admitting_common_dir, registering_root=registering_root,
    )
    review = _validate_retirement_review(
        loaded["review_path"][0],
        review_path=Path(value["review_path"]),
        state_root=state_root,
        common_dir=common_dir,
        request=request,
        request_bytes=loaded["request_path"][1],
        receipt=receipt,
        receipt_bytes=receipt_bytes,
    )
    _validate_retirement_authorization(
        loaded["authorization_path"][0],
        common_dir=common_dir,
        state_root=state_root,
        review=review,
        request=request,
    )
    for field in ("kind", "missing_request_ids", "surviving_receipts", "preserved_ref", "preserved_commit", "operator_authority"):
        if value.get(field) != review[field]:
            raise CloseoutQueueError(f"retirement {field} does not match its review")
    candidate = _check_retirement_subject(
        kind=value["kind"],
        request=request,
        receipt=receipt,
        receipt_path=receipt_path,
        missing=value["missing_request_ids"],
        state_root=state_root,
    )
    if _git_object(common_dir, "cat-file", "-e", value["preserved_commit"] + "^{commit}").returncode:
        # Fetch without a destination, then anchor the exact commit: preserved_ref
        # may have advanced, and an anchor at its new tip would refuse a retire retry.
        raise CloseoutQueueError(
            f"preserved commit unavailable; run in {common_dir}: git fetch origin "
            f"{value['preserved_ref']} && git update-ref "
            f"{_preserved_anchor_ref(value['preserved_commit'])} {value['preserved_commit']} \"\""
        )
    if not _commit_contains(common_dir, candidate, value["preserved_commit"]):
        raise CloseoutQueueError(
            "retirement candidate commit is no longer contained in its preserved commit"
        )
    _timestamp(value.get("retired_at"), label="retirement retired_at")
    active = True
    if value["kind"] == "ABANDONED_REQUEST":
        try:
            _check_abandoned_ownership(request, common_dir)
        except _ActiveOwnership:
            if not allow_resumed:
                raise
            active = False
    return value, active


def _retirement_records(
    state_root: Path,
    request_ids: set[str],
    *,
    admitting_common_dir: Path | None = None,
) -> dict[str, tuple[dict[str, Any], bytes, bool]]:
    """Validate every retirement record, rejecting orphans and unsafe storage."""

    root = _retirement_root(state_root)
    if os.path.lexists(root) and (root.is_symlink() or not root.is_dir()):
        raise CloseoutQueueError("closeout retirement directory must be a real directory")
    records: dict[str, tuple[dict[str, Any], bytes, bool]] = {}
    for path in sorted(root.iterdir()) if root.exists() else ():
        if path.suffix != ".json" or path.is_symlink() or not path.is_file():
            raise CloseoutQueueError(f"closeout retirement directory holds an unexpected entry: {path.name}")
        if path.stem not in request_ids:
            raise CloseoutQueueError(
                f"orphaned retirement record: {path.name}; restore the matching "
                "request from backup"
            )
        value, encoded = _load_json_record(path)
        record, active = _validate_retirement(
            value,
            path,
            state_root=state_root.resolve(),
            admitting_common_dir=admitting_common_dir,
            allow_resumed=True,
        )
        records[path.stem] = (record, encoded, active)
    evidence = _retirement_evidence_root(state_root)
    if os.path.lexists(evidence):
        if evidence.is_symlink() or not evidence.is_dir():
            raise CloseoutQueueError("retirement evidence directory must be a real directory")
        bound = {Path(record[field]) for record, _, _ in records.values()
                 for field in ("review_path", "authorization_path")}
        for path in evidence.iterdir():
            if path in bound or _is_unbound_evidence_copy(path):
                continue
            raise CloseoutQueueError(
                f"unexpected orphaned retirement evidence: {path}; move this entry "
                "out of the retirement-evidence directory, or restore the retirement "
                "record that binds it from backup"
            )
    return records


def _is_unbound_evidence_copy(path: Path) -> bool:
    """Recognise the leftover of a retire interrupted before its record link.

    Evidence copies are published before the retirement record. A copy that no
    record binds is inert, and is ignored and never hashed, only when it is a
    regular file named by its own SHA-256 that holds a bounded JSON record.
    The name is checked before anything is read.
    """

    if not re.fullmatch(r"[0-9a-f]{64}\.json", path.name):
        return False
    try:
        _, encoded = _load_json_record(path)
    except CloseoutQueueError:
        return False
    return path.name == hashlib.sha256(encoded).hexdigest() + ".json"


def _inventory_size_with_retirement(
    common_dir: Path, state_root: Path, record: dict[str, Any], registering_root: Path | None
) -> int:
    """Count the admission inventory entries that publishing ``record`` yields.

    Mirrors the entries _queue_record_sha256s emits, over the roots admission
    reads. It counts without requiring the queue to be admissible, since an
    unretired subject is exactly what keeps admission from passing.
    """

    listed = _git_object(common_dir, "worktree", "list", "--porcelain")
    if listed.returncode:
        raise CloseoutQueueError("retirement cannot inspect Git worktrees")
    roots = {
        line.removeprefix("worktree ")
        for line in listed.stdout.splitlines()
        if line.startswith("worktree ")
    }
    roots.update(str(path) for path in _load_registered_roots(common_dir))
    previous = _load_admission(_admission_path(common_dir), common_dir)
    roots.update((previous or {}).get("registered_roots", []))
    if registering_root is not None:
        roots.add(str(registering_root))
    total = 0
    for raw_root in sorted(roots):
        if not Path(raw_root).is_dir():
            continue
        queue = Path(raw_root).resolve() / ".seam" / "orchestration" / "session-end"
        requests = _load_queued_requests(queue)
        request_ids = {request["request_id"] for request in requests}
        total += len(requests)
        for request in requests:
            total += len(_stored_receipts(request, state_root=queue))
            total += _load_administrative_disposition(queue, request["request_id"]) is not None
        retired = {
            path.stem: _load_json_record(path)[0]
            for path in sorted(_retirement_root(queue).glob("*.json"))
        }
        if queue == state_root:
            retired[record["request_id"]] = record
        # Each retirement contributes its record and its two evidence bindings.
        total += 3 * len(retired)
        covered = {
            target
            for value in retired.values()
            if value.get("kind") == "MISSING_SUPERSESSION_TARGETS"
            and isinstance(value.get("missing_request_ids"), list)
            for target in value["missing_request_ids"]
        }
        if covered:
            total += sum(
                1
                for _, _, request_id in _receipt_inventory_paths(queue)
                if request_id not in request_ids and request_id in covered
            )
    return total


def _publish_retirement_once(path: Path, encoded: bytes, *, state_root: Path) -> bool:
    """Stage outside retirements/ so a crash never leaves a stray entry there."""

    staging = state_root.resolve() / ".retirement-staging"
    _ensure_state_directory(staging, label="retirement staging")
    descriptor, temporary_name = tempfile.mkstemp(dir=staging, prefix=f"{path.stem}.")
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
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return True
    finally:
        temporary.unlink(missing_ok=True)


def retire(
    *,
    request_path: Path,
    review_path: Path,
    authorization_path: Path,
    state_root: Path,
    receipt_path: Path | None = None,
    register_root: Path | None = None,
) -> dict[str, str]:
    """Publish one operator-authorized, admission-only retirement record."""

    raw_state_root = state_root
    state_root = state_root.resolve()
    registered_host = (
        _validate_retirement_register_root(register_root, raw_state_root, state_root)
        if register_root is not None
        else None
    )
    for raw_path in (
        request_path, review_path, authorization_path, *([receipt_path] if receipt_path else [])
    ):
        if (
            not raw_path.is_absolute()
            or ".." in raw_path.parts
            or raw_path.is_symlink()
            or raw_path.resolve(strict=True) != raw_path
        ):
            raise CloseoutQueueError("retirement evidence path is unsafe")
    request_value, request_bytes = _load_json_record(request_path)
    request = validate_request(request_value, state_root=state_root)
    request_id = request["request_id"]
    if request_path != _request_root(state_root) / f"{request_id}.json":
        raise CloseoutQueueError("retirement request is not canonically queued")
    receipt = None
    receipt_bytes = None
    if receipt_path is not None:
        receipt_value, receipt_bytes = _load_json_record(receipt_path)
        receipt = validate_receipt(request, receipt_value, state_root=state_root)
    review_value, review_bytes = _load_json_record(review_path)
    common_dir = _retirement_common_dir(
        request,
        state_root,
        review_value.get("repository_common_dir") if isinstance(review_value, dict) else None,
        registering_root=registered_host,
    )
    review = _validate_retirement_review(
        review_value,
        review_path=review_path,
        state_root=state_root,
        common_dir=common_dir,
        request=request,
        request_bytes=request_bytes,
        receipt=receipt,
        receipt_bytes=receipt_bytes,
    )
    authorization_value, authorization_bytes = _load_json_record(authorization_path)
    entry = _validate_retirement_authorization(
        authorization_value,
        common_dir=common_dir,
        state_root=state_root,
        review=review,
        request=request,
    )
    kind = review["kind"]
    missing = review["missing_request_ids"]
    expected = _retirement_path(state_root, request_id)
    evidence_root = _retirement_evidence_root(state_root)
    value = {
        "schema": "seam-closeout-retirement/v1",
        "kind": kind,
        "request_id": request_id,
        "request_path": str(request_path),
        "request_bytes_sha256": hashlib.sha256(request_bytes).hexdigest(),
        "receipt_path": str(receipt_path) if receipt_path is not None else None,
        "receipt_bytes_sha256": (
            hashlib.sha256(receipt_bytes).hexdigest() if receipt_bytes is not None else None
        ),
        "missing_request_ids": missing,
        "surviving_receipts": review["surviving_receipts"],
        "preserved_ref": review["preserved_ref"],
        "preserved_commit": review["preserved_commit"],
        "review_path": str(evidence_root / (hashlib.sha256(review_bytes).hexdigest() + ".json")),
        "review_bytes_sha256": hashlib.sha256(review_bytes).hexdigest(),
        "authorization_path": str(evidence_root / (hashlib.sha256(authorization_bytes).hexdigest() + ".json")),
        "authorization_bytes_sha256": hashlib.sha256(authorization_bytes).hexdigest(),
        "operator_authority": review["operator_authority"],
        "authority": "admission_only",
        "retired_at": datetime.now(timezone.utc).isoformat(),
    }
    stable_fields = set(value) - {"retired_at"}
    if os.path.lexists(expected):
        existing, _ = _load_json_record(expected)
        if not isinstance(existing, dict) or set(existing) != RETIREMENT_FIELDS:
            _validate_retirement(existing, expected, state_root=state_root, registering_root=registered_host)
        if any(existing.get(field) != value[field] for field in stable_fields):
            if registered_host is None:
                _validate_retirement(existing, expected, state_root=state_root, registering_root=registered_host)
            raise CloseoutQueueError("conflicting retirement exists")
        _validate_retirement(existing, expected, state_root=state_root, registering_root=registered_host)
        _anchor_preserved_commit(common_dir, review["preserved_commit"])
        if registered_host is not None:
            _validate_retirement_register_root(registered_host, raw_state_root, state_root)
            _store_root_registration(common_dir, registered_host)
        return {"status": "ALREADY_RETIRED", "retirement_path": str(expected)}
    if kind == "MISSING_SUPERSESSION_TARGETS" and isinstance(missing, list):
        for item in missing:
            if (
                isinstance(item, str)
                and SAFE_ID.fullmatch(item)
                and os.path.lexists(_request_root(state_root) / f"{item}.json")
            ):
                raise CloseoutQueueError(f"retirement target {item} still exists in the queue")
    candidate = _check_retirement_subject(
        kind=kind,
        request=request,
        receipt=receipt,
        receipt_path=receipt_path,
        missing=missing,
        state_root=state_root,
    )
    if kind == "ABANDONED_REQUEST":
        if any(
            _receipt_is_dispositive(request, stored)
            for _, stored in _stored_receipts(request, state_root=state_root)
        ):
            raise CloseoutQueueError("retirement request already has a dispositive receipt")
        _check_abandoned_ownership(request, common_dir)
    else:
        assert receipt is not None
        _prove_missing_supersession_targets(
            request, receipt, missing, state_root=state_root
        )
    if _origin_ref_commit(common_dir, review["preserved_ref"]) != review["preserved_commit"]:
        raise CloseoutQueueError(
            "retirement preserved_ref: origin does not hold the preserved commit"
        )
    if not _commit_contains(common_dir, candidate, review["preserved_commit"]):
        raise CloseoutQueueError(
            "retirement candidate commit is not preserved by the preserved commit"
        )
    for artifact_path, original_bytes in (
        (request_path, request_bytes),
        (review_path, review_bytes),
        (authorization_path, authorization_bytes),
        *([(receipt_path, receipt_bytes)] if receipt_path is not None else []),
    ):
        if _load_json_record(artifact_path)[1] != original_bytes:
            raise CloseoutQueueError("retirement evidence changed before publication")
    scope_proof = None
    if kind == "ABANDONED_REQUEST":
        if any(
            _receipt_is_dispositive(request, stored)
            for _, stored in _stored_receipts(request, state_root=state_root)
        ):
            raise CloseoutQueueError("retirement request already has a dispositive receipt")
        _check_abandoned_ownership(request, common_dir)
        scope_proof = _prove_abandoned_scope(
            request,
            common_dir,
            entry["acknowledged_hidden_paths"],
            preserved_ref=review["preserved_ref"],
            preserved_commit=review["preserved_commit"],
        )
    else:
        assert receipt is not None
        _prove_missing_supersession_targets(
            request, receipt, missing, state_root=state_root
        )
    if registered_host is not None:
        _validate_retirement_register_root(registered_host, raw_state_root, state_root)
    inventory_size = _inventory_size_with_retirement(common_dir, state_root, value, registered_host)
    if inventory_size > ADMISSION_INVENTORY_LIMIT:
        # Admission would publish this inventory and then never read it back.
        raise CloseoutQueueError(
            f"retirement would grow the admission inventory to {inventory_size} entries "
            f"and admission reads at most {ADMISSION_INVENTORY_LIMIT}; nothing was "
            "published. Reduce the queued records under operator direction first"
        )
    # Anchor before anything is published: no record may outlive its commit.
    _anchor_preserved_commit(common_dir, review["preserved_commit"])
    _ensure_state_directory(evidence_root, label="retirement evidence")
    for field, encoded in (("review_path", review_bytes), ("authorization_path", authorization_bytes)):
        durable = Path(value[field])
        _publish_retirement_once(durable, encoded, state_root=state_root)
        if _load_json_record(durable)[1] != encoded:
            raise CloseoutQueueError("retirement evidence copy differs from original")
    _validate_retirement(value, expected, state_root=state_root, registering_root=registered_host)
    _ensure_state_directory(expected.parent, label="retirement")
    if scope_proof is not None:
        # The publication boundary: the last statement before the record link.
        _reprove_abandoned_scope(scope_proof)
    published = _publish_retirement_once(expected, _canonical_record(value), state_root=state_root)
    if not published:
        existing, _ = _load_json_record(expected)
        _validate_retirement(existing, expected, state_root=state_root, registering_root=registered_host)
        if any(existing[field] != value[field] for field in stable_fields):
            raise CloseoutQueueError("conflicting retirement exists")
    if registered_host is not None:
        _store_root_registration(common_dir, registered_host)
    return {"status": "RETIRED" if published else "ALREADY_RETIRED", "retirement_path": str(expected)}


def _receipt_inventory_paths(state_root: Path):
    for kind in ("receipts", "receipt-attempts"):
        directory = state_root / kind
        if not os.path.lexists(directory):
            continue
        if directory.is_symlink() or not directory.is_dir() or directory.resolve() != directory:
            raise CloseoutQueueError("closeout receipt directory must be a real directory")
        for path in directory.iterdir():
            if path.suffix != ".json" or (path.name.startswith(".") and ".json.tmp." in path.name):
                continue
            request_id = path.stem if kind == "receipts" else path.stem.rpartition("-")[0]
            yield kind, path, request_id


def _surviving_receipts(state_root: Path, missing: list[str]) -> list[dict[str, str]]:
    if not missing:
        return []
    inventory = []
    for kind, path, request_id in _receipt_inventory_paths(state_root):
        if request_id in missing:
            receipt, encoded = _load_json_record(path)
            if receipt.get("request_id") != request_id or (
                kind == "receipt-attempts" and path != _receipt_attempt_path(
                    state_root, request_id, _canonical_record(receipt)
                )
            ):
                raise CloseoutQueueError("invalid surviving target receipt")
            inventory.append({"path": str(path.relative_to(state_root)), "sha256": hashlib.sha256(encoded).hexdigest()})
    return sorted(inventory, key=lambda item: item["path"])


def _orphan_receipts(state_root: Path, requests: set[str], retirements: dict) -> list[str]:
    covered = {
        target for record, _, _ in retirements.values()
        if record["kind"] == "MISSING_SUPERSESSION_TARGETS"
        for target in record["missing_request_ids"]
    }
    hashes = []
    if not covered:
        return hashes
    for kind, path, request_id in _receipt_inventory_paths(state_root):
        if request_id in requests:
            continue
        if request_id not in covered:
            # A receipt no retirement covers is ignored and left unhashed.
            continue
        receipt, encoded = _load_json_record(path)
        if kind == "receipt-attempts" and path != _receipt_attempt_path(
            state_root, request_id, _canonical_record(receipt)
        ):
            raise CloseoutQueueError(f"orphaned receipt attempt content address mismatch: {path}; restore the verified receipt from backup")
        if receipt.get("request_id") != request_id:
            raise CloseoutQueueError(f"orphaned receipt identity mismatch: {path}; restore the verified receipt from backup")
        hashes.append(f"{request_id}|{path.name}|{hashlib.sha256(encoded).hexdigest()}")
    return hashes


def pending(
    state_root: Path = DEFAULT_STATE_ROOT,
    *,
    honor_retirements: bool = False,
    admitting_common_dir: Path | None = None,
) -> dict[str, Any]:
    """Return validated pending requests without launching a model or writing state.

    Every retirement record is validated, and reported under ``retirements``
    only when at least one exists. Public ``pending`` and
    successor inventory keep ``honor_retirements=False``; only ordinary
    admission passes ``honor_retirements=True``.
    """

    state_root = state_root.resolve()
    requests = _load_queued_requests(state_root)
    retirement_records = _retirement_records(
        state_root,
        {request["request_id"] for request in requests},
        admitting_common_dir=admitting_common_dir,
    )
    _orphan_receipts(state_root, {r["request_id"] for r in requests}, retirement_records)
    if not requests:
        return {
            "profile": "seam_release_orchestrator",
            "requests": [],
            "administrative_dispositions": [],
        }
    requests_by_id = {request["request_id"]: request for request in requests}
    receipts_by_id: dict[str, list[dict[str, Any]]] = {}
    superseded: set[str] = set()
    for request in requests:
        stored = _stored_receipts(request, state_root=state_root)
        receipts = [receipt for _, receipt in stored]
        receipts_by_id[request["request_id"]] = receipts
        for receipt_path, receipt in stored:
            if _receipt_is_dispositive(request, receipt):
                retired = retirement_records.get(request["request_id"])
                bound_targets = set()
                if (retired and retired[0]["kind"] == "MISSING_SUPERSESSION_TARGETS"
                        and retired[0]["receipt_path"] == str(receipt_path)):
                    bound_targets.update(retired[0]["missing_request_ids"])
                superseded.update(_validate_supersession_targets(
                    request, receipt, state_root=state_root, requests_by_id=requests_by_id,
                    retired_missing=bound_targets if honor_retirements else None,
                    restored=bound_targets if honor_retirements else None,
                ))
    pending_requests: list[dict[str, Any]] = []
    dispositions: list[dict[str, Any]] = []
    retirements: list[dict[str, Any]] = []
    for request in requests:
        retirement = retirement_records.get(request["request_id"])
        if retirement is not None:
            retirements.append(
                {"request_id": request["request_id"], "retirement": retirement[0]}
            )
        if request["request_id"] in superseded:
            continue
        if any(
            _receipt_is_dispositive(request, receipt)
            for receipt in receipts_by_id[request["request_id"]]
        ):
            continue
        if (
            honor_retirements
            and retirement is not None
            and retirement[2]
            and retirement[0]["kind"] == "ABANDONED_REQUEST"
        ):
            continue
        pending_requests.append(request)
        disposition = _load_administrative_disposition(state_root, request["request_id"])
        if disposition is not None:
            dispositions.append({"request_id": request["request_id"], "receipt_status": "BLOCKED", "disposition": disposition[1]})
    return {
        "profile": "seam_release_orchestrator",
        "requests": pending_requests,
        "administrative_dispositions": dispositions,
        # Absent, as before retirements existed, unless a record is reported.
        **({"retirements": retirements} if retirements else {}),
    }


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
    _check_admission_lists(value)
    _timestamp(value.get("admitted_at"), label="admission admitted_at")
    return value


def _check_admission_lists(value: dict[str, Any]) -> None:
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
            or len(items) > ADMISSION_INVENTORY_LIMIT
            or any(
                not isinstance(item, str)
                or not item
                or len(item) > maximum_length
                for item in items
            )
            or items != sorted(set(items))
        ):
            raise CloseoutQueueError(f"closeout admission {field} is invalid")


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


def _retained_root_path(raw_root: object) -> Path:
    """The registry reader's check of one stored root; writers must pass it too."""

    if (
        not isinstance(raw_root, str)
        or not raw_root
        or len(raw_root) > RETAINED_ROOT_PATH_LIMIT
    ):
        raise CloseoutQueueError("closeout retained-root path is invalid")
    registered_root = Path(raw_root)
    if not registered_root.is_absolute() or ".." in registered_root.parts:
        raise CloseoutQueueError("closeout retained-root path is unsafe")
    return registered_root


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
        registered_root = _retained_root_path(value.get("registered_root"))
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
    root: Path,
    *,
    allowed_dispositions: set[Path] | None = None,
    common_dir: Path | None = None,
) -> tuple[list[str], list[str], set[Path]]:
    state_root = root / ".seam" / "orchestration" / "session-end"
    requests = _load_queued_requests(state_root)
    queue = pending(
        state_root,
        honor_retirements=True if allowed_dispositions is None else False,
        admitting_common_dir=common_dir,
    )
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
    retirement_records = _retirement_records(
        state_root,
        {request["request_id"] for request in requests},
        admitting_common_dir=common_dir,
    )
    if allowed_dispositions is None:
        for request_id in sorted(pending_ids):
            retired = retirement_records.get(request_id)
            if retired is not None and retired[0]["kind"] == "ABANDONED_REQUEST" and not retired[2]:
                raise CloseoutQueueError(
                    f"closeout admission has unresolved requests: {request_id}; its "
                    "retirement is inactive because the retired session is registered "
                    "or holds an unresolved recovery claim again; qualify the request "
                    "or supersede it with a same-lineage QUALIFIED receipt"
                )
    for item in _orphan_receipts(state_root, {r["request_id"] for r in requests}, retirement_records):
        hashes.append(f"{root}|receipt|{item}")
    for request_id, (record, encoded, _) in retirement_records.items():
        # One authorization file may back many retirements, so each line names
        # its request and field; a bare digest would repeat and wedge admission.
        for field in ("review", "authorization"):
            hashes.append(
                f"{root}|retirement-evidence|{request_id}|{field}|"
                f"{record[field + '_bytes_sha256']}"
            )
        hashes.append(
            f"{root}|retirement|{request_id}|{hashlib.sha256(encoded).hexdigest()}"
        )
    return sorted(pending_ids), sorted(set(hashes)), observed_dispositions


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
            resolved, allowed_dispositions=allowed_dispositions, common_dir=common_dir
        )
        if not os.path.lexists(git_metadata) and not hashes:
            raise CloseoutQueueError(
                f"closeout admission retained root has no immutable queue evidence: {raw_root}"
            )
        request_ids.extend(pending_ids)
        record_sha256s.extend(hashes)
        observed_dispositions.update(dispositions)
    return roots, sorted(request_ids), sorted(record_sha256s), sorted(str(path) for path in observed_dispositions)


def _admission_record(
    common_dir: Path,
    registered: list[Path],
    observed_roots: list[str],
    record_sha256s: list[str],
) -> dict[str, Any]:
    return {
        "schema": "seam-queue-admission/v1",
        "kind": "inventory",
        "repository_common_dir": str(common_dir),
        "registered_roots": [str(path) for path in registered],
        "observed_roots": observed_roots,
        "pending_request_ids": [],
        "record_sha256s": record_sha256s,
        "admitted_at": datetime.now(timezone.utc).isoformat(),
    }


def _admission_list_fault(lists: dict[str, list[str]]) -> tuple[str, str]:
    """Why the reader rejects these lists, and what the operator can do.

    Fields are visited in the reader's order, so the cause belongs to the
    field its message names.
    """

    for field in ("registered_roots", "observed_roots", "pending_request_ids", "record_sha256s"):
        items = lists[field]
        if len(items) > ADMISSION_INVENTORY_LIMIT:
            return (
                f"admission reads at most {ADMISSION_INVENTORY_LIMIT} entries per list "
                f"and this inventory holds {len(lists['record_sha256s'])} record "
                f"entries over {len(lists['observed_roots'])} roots",
                "Reduce the queued records",
            )
        maximum_length = 3000 if field == "record_sha256s" else 1000
        longest = max((len(item) for item in items), default=0)
        if longest > maximum_length:
            return (
                f"admission reads entries of at most {maximum_length} characters in "
                f"{field} and this inventory holds one of {longest}",
                "Remove or shorten the root that entry names",
            )
    return "admission cannot read this inventory", "Repair the queue"


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
    record: dict[str, Any] | None = None
    if any(
        any(_retirement_root(Path(root) / ".seam" / "orchestration" / "session-end").glob("*.json"))
        for root in observed_roots
    ):
        # Checked before anything is stored: a record the reader rejects would
        # fail every later admission before it looked at the live queue.
        lists = {
            "registered_roots": [str(path) for path in registered],
            "observed_roots": observed_roots,
            "pending_request_ids": [],
            "record_sha256s": record_sha256s,
        }
        try:
            _check_admission_lists(lists)
        except CloseoutQueueError as exc:
            fault, remedy = _admission_list_fault(lists)
            raise CloseoutQueueError(
                f"{exc}: {fault}; the stored admission record was left unchanged. "
                f"{remedy} under operator direction, then admit again"
            ) from exc
        # The reader also bounds the whole record, so the record is built and
        # encoded here exactly as _write_admission will encode it.
        record = _admission_record(common_dir, registered, observed_roots, record_sha256s)
        encoded_size = len(_canonical_record(record))
        if encoded_size > MAX_RECORD_BYTES:
            raise CloseoutQueueError(
                "closeout admission record is invalid: admission reads a record of at "
                f"most {MAX_RECORD_BYTES} bytes and this inventory encodes to "
                f"{encoded_size} bytes ({len(record_sha256s)} record entries over "
                f"{len(observed_roots)} roots); the stored admission record was left "
                "unchanged. Reduce the queued records or the admitted roots under "
                "operator direction, then admit again"
            )
    for path in registered:
        _store_root_registration(common_dir, path)
    if record is None:
        record = _admission_record(common_dir, registered, observed_roots, record_sha256s)
    _write_admission(record_path, record)
    return record


def _unexpected_successor_pending(
    roots: list[str],
    pending_ids: list[str],
    *,
    obligation_request_ids: set[str],
    lineage_session_ids: set[str],
    worktree_root: str,
    branch: str,
    original_base_sha: str,
    require_obligations: bool,
) -> list[str]:
    pending = set(pending_ids)
    if require_obligations and not obligation_request_ids <= pending:
        missing = sorted(obligation_request_ids - pending)
        raise CloseoutQueueError(
            "successor admission lost inherited obligations: " + ", ".join(missing)
        )
    allowed = set(obligation_request_ids)
    for root in map(Path, roots):
        for request in _load_queued_requests(
            root / ".seam" / "orchestration" / "session-end"
        ):
            if request["request_id"] not in pending:
                continue
            request_repo = request["repo"]
            if (
                request["session_id"] in lineage_session_ids
                and request_repo["root"] == worktree_root
                and request_repo["worktree"] == worktree_root
                and request_repo["branch"] == branch
                and request_repo["base_sha"] == original_base_sha
            ):
                allowed.add(request["request_id"])
    return sorted(pending - allowed)


def admit_successor(
    repo_root: Path,
    *,
    obligation_request_ids: set[str],
    lineage_session_ids: set[str],
    branch: str,
    original_base_sha: str,
    repair_paths: list[Path],
) -> dict[str, Any]:
    """Validate hash-bound lineage obligations plus named admin repairs."""

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
    unexpected = _unexpected_successor_pending(
        roots,
        request_ids,
        obligation_request_ids=obligation_request_ids,
        lineage_session_ids=lineage_session_ids,
        worktree_root=str(repo_root),
        branch=branch,
        original_base_sha=original_base_sha,
        require_obligations=True,
    )
    if unexpected:
        raise CloseoutQueueError(
            "successor admission found unrelated unresolved requests: "
            + ", ".join(unexpected)
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
    repo_root: Path,
    transition: dict[str, Any],
    *,
    obligation_request_ids: set[str],
    lineage_session_ids: set[str],
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
    unexpected = _unexpected_successor_pending(
        roots,
        pending_ids,
        obligation_request_ids=obligation_request_ids,
        lineage_session_ids=lineage_session_ids,
        worktree_root=transition["worktree_root"],
        branch=transition["branch"],
        original_base_sha=transition["original_base_sha"],
        require_obligations=False,
    )
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
    retirement = commands.add_parser(
        "retire",
        help="Record an operator-authorized, admission-only retirement of one queue record.",
    )
    retirement.add_argument("--request", type=Path, required=True)
    retirement.add_argument("--review", type=Path, required=True)
    retirement.add_argument("--authorization", type=Path, required=True)
    retirement.add_argument("--receipt", type=Path)
    retirement.add_argument("--register-root", type=Path)
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
        elif args.command == "retire":
            result = retire(
                request_path=args.request,
                review_path=args.review,
                authorization_path=args.authorization,
                receipt_path=args.receipt,
                register_root=args.register_root,
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
