#!/usr/bin/env python3
"""Validate and surface pending closeout requests for the root release wave."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from datetime import datetime
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


def _load_json(path: Path) -> dict[str, Any]:
    descriptor: int | None = None
    try:
        if path.is_symlink():
            raise CloseoutQueueError(
                f"closeout record must be a regular file: {path.name}"
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
    return value


def _request_hash(value: dict[str, Any]) -> str:
    unsigned = {key: item for key, item in value.items() if key != "request_sha256"}
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(canonical).hexdigest()


def _expected_receipt_path(state_root: Path, request_id: str) -> Path:
    return state_root.resolve() / "receipts" / f"{request_id}.json"


def _receipt_attempt_root(state_root: Path) -> Path:
    return state_root.resolve() / "receipt-attempts"


def _receipt_attempt_path(
    state_root: Path, request_id: str, encoded: bytes
) -> Path:
    digest = hashlib.sha256(encoded).hexdigest()
    return _receipt_attempt_root(state_root) / f"{request_id}-{digest}.json"


def _ensure_state_directory(path: Path, *, label: str) -> None:
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
    if not isinstance(tdd, dict) or set(tdd) != TDD_FIELDS:
        raise CloseoutQueueError("closeout request TDD fields are invalid")
    cycles = _validate_tdd_cycles(tdd.get("cycles"))
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
    if tdd_runtime_paths != visible_runtime_paths:
        raise CloseoutQueueError("closeout request TDD runtime paths do not match changed paths")
    recomputed = assess_tdd(paths, {"tdd_cycles": cycles})
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
    if not isinstance(receipt_path, str) or Path(receipt_path) != expected:
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
            target_receipt["status"] != "QUALIFIED"
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


def _verify_live_scope(request: dict[str, Any]) -> None:
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
    if head != repo["head"] or fingerprint != repo["diff_fingerprint"]:
        raise CloseoutQueueError("closeout live Git scope drifted from request")


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
    _validate_supersession_targets(request, receipt, state_root=state_root)
    encoded = _canonical_record(receipt)
    stored = _stored_receipts(request, state_root=state_root)
    for existing_path, existing in stored:
        if _canonical_record(existing) == encoded:
            _verify_live_scope(request)
            status = (
                "ALREADY_STORED"
                if existing_path
                == _expected_receipt_path(state_root, request["request_id"])
                else "ALREADY_STORED_ATTEMPT"
            )
            return {"status": status, "receipt_path": str(existing_path)}
    if any(existing["status"] == "QUALIFIED" for _, existing in stored):
        raise CloseoutQueueError("conflicting qualified closeout receipt already exists")

    canonical = _expected_receipt_path(state_root, request["request_id"])
    if not stored:
        _ensure_state_directory(canonical.parent, label="receipt")
        _verify_live_scope(request)
        if _publish_record_once(canonical, encoded):
            return {"status": "STORED", "receipt_path": str(canonical)}
        stored = _stored_receipts(request, state_root=state_root)
        for existing_path, existing in stored:
            if _canonical_record(existing) == encoded:
                _verify_live_scope(request)
                return {
                    "status": "ALREADY_STORED",
                    "receipt_path": str(existing_path),
                }
        if any(existing["status"] == "QUALIFIED" for _, existing in stored):
            raise CloseoutQueueError(
                "conflicting qualified closeout receipt already exists"
            )

    attempt = _receipt_attempt_path(state_root, request["request_id"], encoded)
    _ensure_state_directory(attempt.parent, label="receipt-attempt")
    _verify_live_scope(request)
    if not _publish_record_once(attempt, encoded):
        existing = validate_receipt(
            request, _load_json(attempt), state_root=state_root
        )
        if _canonical_record(existing) != encoded:
            raise CloseoutQueueError("conflicting closeout receipt attempt exists")
        _verify_live_scope(request)
        return {"status": "ALREADY_STORED_ATTEMPT", "receipt_path": str(attempt)}
    return {"status": "STORED_ATTEMPT", "receipt_path": str(attempt)}


def pending(state_root: Path = DEFAULT_STATE_ROOT) -> dict[str, Any]:
    """Return validated pending requests without launching a model or writing state."""

    state_root = state_root.resolve()
    requests = _load_queued_requests(state_root)
    if not requests:
        return {"profile": "seam_release_orchestrator", "requests": []}
    requests_by_id = {request["request_id"]: request for request in requests}
    receipts_by_id: dict[str, list[dict[str, Any]]] = {}
    superseded: set[str] = set()
    for request in requests:
        stored = _stored_receipts(request, state_root=state_root)
        receipts = [receipt for _, receipt in stored]
        receipts_by_id[request["request_id"]] = receipts
        for receipt in receipts:
            if receipt["status"] == "QUALIFIED":
                _validate_supersession_targets(
                    request,
                    receipt,
                    state_root=state_root,
                    requests_by_id=requests_by_id,
                )
                superseded.update(receipt["supersedes_request_ids"])
    pending_requests: list[dict[str, Any]] = []
    for request in requests:
        if request["request_id"] in superseded:
            continue
        if any(
            receipt["status"] == "QUALIFIED"
            for receipt in receipts_by_id[request["request_id"]]
        ):
            continue
        pending_requests.append(request)
    return {"profile": "seam_release_orchestrator", "requests": pending_requests}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and process SEAM root closeout queue records."
    )
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("pending", help="Print validated pending requests.")
    store = commands.add_parser("store", help="Validate and atomically store a receipt.")
    store.add_argument("--request", type=Path, required=True)
    store.add_argument("--receipt", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the deterministic queue boundary; never launch a model itself."""

    args = _parser().parse_args(argv)
    try:
        if args.command == "pending":
            result = pending(args.state_root)
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
