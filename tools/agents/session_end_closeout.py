#!/usr/bin/env python3
"""Codex SessionEnd hook that queues a bounded closeout-orchestrator request.

The hook deliberately does not read the Codex transcript, run the test suite,
modify continuity records, or launch another model session. It snapshots only
Git state plus the root-maintained session state, then exits. The next root
session dispatches the request to ``seam_release_orchestrator``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_ROOT = REPO_ROOT / ".seam" / "orchestration" / "session-end"
SESSION_STATE_ROOT = REPO_ROOT / ".seam" / "orchestration" / "sessions"
RECURSION_GUARD_ENV = "SEAM_SESSION_END_ACTIVE"
MAX_EVENT_BYTES = 1024 * 1024
MAX_SESSION_STATE_BYTES = 256 * 1024
MAX_CHANGED_PATHS = 512
MAX_UNTRACKED_HASH_BYTES = 64 * 1024 * 1024
HOOK_BUDGET_SECONDS = 2.5
REQUIRED_CLOSEOUT_CHECKS = (
    "confirm current diff fingerprint matches request",
    "git diff --check",
    "run root-supplied affected tests when available",
    "python -m tools.history.verify_integrity",
    "python -m tools.history.verify_routing",
    "python -m tools.history.verify_handoffs",
    "python -m tools.history.verify_continuity",
    "python -m tools.streams.verify_streams",
    "python -m tools.docs.verify_wiki",
)

RUNTIME_PATHS = (
    "seam.py",
    "seam_runtime/",
    "experimental/",
    "installers/",
    "scripts/",
    "tools/",
)
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"https?://(?:chatgpt\.com/share|claude\.ai/share)/\S+", re.I),
)
RFC3339_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


class SessionEndError(RuntimeError):
    """The hook event cannot be converted into a safe closeout request."""


def _bounded_string(value: object, field: str, *, minimum: int, maximum: int) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise SessionEndError(f"session state {field} must be a string of length {minimum}..{maximum}")
    return value


def _bounded_string_list(
    value: object,
    field: str,
    *,
    maximum_items: int,
    maximum_length: int,
    minimum_items: int = 0,
) -> list[str]:
    if not isinstance(value, list) or not minimum_items <= len(value) <= maximum_items:
        raise SessionEndError(
            f"session state {field} must contain {minimum_items}..{maximum_items} items"
        )
    for item in value:
        _bounded_string(item, field, minimum=1, maximum=maximum_length)
    return value


def _rfc3339_datetime(value: str) -> datetime:
    if not RFC3339_DATETIME.fullmatch(value):
        raise SessionEndError("session state phase observed_at must be an RFC 3339 date-time")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SessionEndError(
            "session state phase observed_at must be an RFC 3339 date-time"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SessionEndError("session state phase observed_at must be an RFC 3339 date-time")
    return parsed


def validate_session_state(
    value: object, *, expected_session_id: str | None = None
) -> dict[str, Any]:
    """Validate the stdlib-supported subset pinned by session-state.schema.json."""

    if not isinstance(value, dict):
        raise SessionEndError("root session state must be a JSON object")
    required = {
        "schema",
        "session_id",
        "base_sha",
        "objective",
        "plan",
        "constraints",
        "affected_tests",
        "tdd_cycles",
    }
    missing = sorted(required - set(value))
    extra = sorted(set(value) - required)
    if missing:
        raise SessionEndError(f"session state missing required field: {missing[0]}")
    if extra:
        raise SessionEndError(f"session state has unsupported field: {extra[0]}")
    if value["schema"] != "seam-agent-session-state/v1":
        raise SessionEndError("root session state has an unsupported schema")
    session_id = _bounded_string(value["session_id"], "session_id", minimum=1, maximum=180)
    if expected_session_id is not None and session_id != expected_session_id:
        raise SessionEndError("root session state session_id does not match hook event")
    base_sha = _bounded_string(value["base_sha"], "base_sha", minimum=40, maximum=64)
    if not re.fullmatch(r"[0-9a-f]{40,64}", base_sha):
        raise SessionEndError("session state base_sha must be a lowercase commit hash")
    _bounded_string(value["objective"], "objective", minimum=1, maximum=2000)
    _bounded_string_list(value["plan"], "plan", maximum_items=16, maximum_length=500)
    _bounded_string_list(
        value["constraints"], "constraints", maximum_items=24, maximum_length=500
    )
    _bounded_string_list(
        value["affected_tests"], "affected_tests", maximum_items=128, maximum_length=500
    )
    cycles = value["tdd_cycles"]
    if not isinstance(cycles, list) or len(cycles) > 128:
        raise SessionEndError("session state tdd_cycles must contain at most 128 items")
    for index, cycle in enumerate(cycles):
        if not isinstance(cycle, dict):
            raise SessionEndError(f"session state tdd_cycles[{index}] must be an object")
        cycle_keys = {"behavior", "test_refs", "implementation_refs", "red", "green"}
        if set(cycle) != cycle_keys:
            raise SessionEndError(f"session state tdd_cycles[{index}] fields do not match schema")
        _bounded_string(cycle["behavior"], "behavior", minimum=1, maximum=1000)
        _bounded_string_list(
            cycle["test_refs"],
            "test_refs",
            minimum_items=1,
            maximum_items=32,
            maximum_length=500,
        )
        _bounded_string_list(
            cycle["implementation_refs"],
            "implementation_refs",
            minimum_items=1,
            maximum_items=32,
            maximum_length=500,
        )
        for phase_name in ("red", "green"):
            phase = cycle[phase_name]
            phase_keys = {"command", "exit_code", "observed_at", "fingerprint"}
            if not isinstance(phase, dict) or set(phase) != phase_keys:
                raise SessionEndError(
                    f"session state tdd_cycles[{index}].{phase_name} fields do not match schema"
                )
            _bounded_string(phase["command"], "command", minimum=1, maximum=2000)
            if isinstance(phase["exit_code"], bool) or not isinstance(phase["exit_code"], int):
                raise SessionEndError("session state phase exit_code must be an integer")
            observed_at = _bounded_string(
                phase["observed_at"], "observed_at", minimum=1, maximum=100
            )
            _rfc3339_datetime(observed_at)
            _bounded_string(phase["fingerprint"], "fingerprint", minimum=1, maximum=256)
    return value


def _safe_session_id(value: object) -> str:
    if not isinstance(value, str):
        raise SessionEndError("session_id must be a string")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", value).strip("._")
    if not cleaned:
        raise SessionEndError("session_id is empty after normalization")
    return cleaned[:180]


def _redact(value: object, limit: int = 1000) -> str:
    text = str(value or "").replace("\x00", "")
    for index, pattern in enumerate(SECRET_PATTERNS):
        if index == 2:
            text = pattern.sub(lambda match: f"{match.group(1)}=<redacted>", text)
        else:
            text = pattern.sub("<redacted>", text)
    return text[:limit].strip()


def _git(
    repo_root: Path,
    *args: str,
    check: bool = True,
    deadline: float | None = None,
) -> bytes:
    timeout = HOOK_BUDGET_SECONDS if deadline is None else deadline - time.monotonic()
    if timeout <= 0:
        raise SessionEndError("SessionEnd hook deadline exceeded before Git completed")
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise SessionEndError(
            f"git {' '.join(args)} timed out before the SessionEnd deadline"
        ) from exc
    if check and result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise SessionEndError(f"git {' '.join(args)} failed: {_redact(message, 300)}")
    return result.stdout if result.returncode == 0 else b""


def _git_text(
    repo_root: Path,
    *args: str,
    check: bool = True,
    deadline: float | None = None,
) -> str:
    return (
        _git(repo_root, *args, check=check, deadline=deadline)
        .decode("utf-8", errors="replace")
        .strip()
    )


def _inside_repo(cwd: Path, repo_root: Path) -> bool:
    return cwd == repo_root or repo_root in cwd.parents


def _load_session_state(
    session_id: str, *, repo_root: Path, state_root: Path
) -> dict[str, Any] | None:
    candidates = [
        state_root / "sessions" / f"{session_id}.json",
        state_root.parent / "sessions" / f"{session_id}.json",
        repo_root / ".seam" / "orchestration" / "sessions" / f"{session_id}.json",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        if path.stat().st_size > MAX_SESSION_STATE_BYTES:
            raise SessionEndError("root session state exceeds the 256 KiB bound")
        value = json.loads(path.read_text(encoding="utf-8"))
        return validate_session_state(value, expected_session_id=session_id)
    return None


def _valid_base(
    repo_root: Path, value: object, *, deadline: float | None = None
) -> str | None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", value):
        return None
    resolved = _git_text(
        repo_root,
        "rev-parse",
        "--verify",
        f"{value}^{{commit}}",
        check=False,
        deadline=deadline,
    )
    return resolved or None


def _changed_paths(
    repo_root: Path, base_sha: str | None, *, deadline: float | None = None
) -> tuple[list[str], bool]:
    baseline = base_sha or "HEAD"
    tracked = _git(
        repo_root, "diff", "--name-only", "-z", baseline, deadline=deadline
    ).split(b"\x00")
    untracked = _git(
        repo_root,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        deadline=deadline,
    ).split(b"\x00")
    paths = sorted(
        {
            item.decode("utf-8", errors="replace")
            for item in tracked + untracked
            if item
        }
    )
    truncated = len(paths) > MAX_CHANGED_PATHS
    return paths, truncated


def runtime_paths(paths: list[str]) -> list[str]:
    return [
        path
        for path in paths
        if path == "seam.py" or any(path.startswith(prefix) for prefix in RUNTIME_PATHS[1:])
    ]


def _valid_cycle(cycle: object) -> bool:
    if not isinstance(cycle, dict):
        return False
    red = cycle.get("red")
    green = cycle.get("green")
    if not isinstance(red, dict) or not isinstance(green, dict):
        return False
    required_lists = (cycle.get("test_refs"), cycle.get("implementation_refs"))
    if not all(isinstance(items, list) and all(isinstance(item, str) and item for item in items) for items in required_lists):
        return False
    if not isinstance(cycle.get("behavior"), str) or not cycle["behavior"].strip():
        return False
    for phase in (red, green):
        if not isinstance(phase.get("command"), str) or not phase["command"].strip():
            return False
        if not isinstance(phase.get("fingerprint"), str) or not phase["fingerprint"].strip():
            return False
        if not isinstance(phase.get("observed_at"), str) or not phase["observed_at"].strip():
            return False
    try:
        red_at = _rfc3339_datetime(red["observed_at"])
        green_at = _rfc3339_datetime(green["observed_at"])
    except SessionEndError:
        return False
    return (
        red.get("exit_code") not in (None, 0)
        and green.get("exit_code") == 0
        and red_at <= green_at
    )


def assess_tdd(paths: list[str], state: dict[str, Any] | None) -> dict[str, Any]:
    """Assess recorded red/green evidence against the changed runtime paths."""

    runtime = runtime_paths(paths)
    if not runtime:
        return {
            "status": "TDD_NOT_REQUIRED",
            "runtime_paths": [],
            "covered_runtime_paths": [],
            "missing_runtime_paths": [],
            "cycle_count": 0,
        }
    cycles = state.get("tdd_cycles", []) if state else []
    valid = [cycle for cycle in cycles if _valid_cycle(cycle)]
    covered = sorted(
        {
            ref
            for cycle in valid
            for ref in cycle["implementation_refs"]
            if ref in runtime
        }
    )
    missing = sorted(set(runtime) - set(covered))
    return {
        "status": "TDD_PROVEN" if valid and not missing else "TDD_UNPROVEN",
        "runtime_paths": runtime,
        "covered_runtime_paths": covered,
        "missing_runtime_paths": missing,
        "cycle_count": len(valid),
    }


def _bounded_context(state: dict[str, Any] | None) -> dict[str, Any]:
    if state is None:
        return {
            "source": "root_session_state",
            "available": False,
            "objective": "not supplied",
            "plan": [],
            "constraints": [],
            "affected_tests": [],
        }

    def strings(key: str, *, count: int, width: int) -> list[str]:
        values = state.get(key, [])
        if not isinstance(values, list):
            return []
        return [_redact(value, width) for value in values[:count] if isinstance(value, str)]

    return {
        "source": "root_session_state",
        "available": True,
        "objective": _redact(state.get("objective"), 1200),
        "plan": strings("plan", count=16, width=500),
        "constraints": strings("constraints", count=24, width=500),
        "affected_tests": strings("affected_tests", count=128, width=500),
    }


def _fingerprint(
    repo_root: Path,
    head: str,
    base_sha: str | None,
    paths: list[str],
    *,
    deadline: float | None = None,
) -> str:
    digest = hashlib.sha256()
    digest.update(head.encode("ascii", errors="replace"))
    digest.update((base_sha or "HEAD").encode("ascii", errors="replace"))
    digest.update(
        _git(
            repo_root,
            "diff",
            "--raw",
            "--no-abbrev",
            "-z",
            base_sha or "HEAD",
            deadline=deadline,
        )
    )
    untracked = {
        item.decode("utf-8", errors="replace")
        for item in _git(
            repo_root, "ls-files", "--others", "--exclude-standard", "-z",
            deadline=deadline,
        ).split(b"\x00")
        if item
    }
    total_bytes = 0
    for path in paths:
        if deadline is not None and time.monotonic() >= deadline:
            raise SessionEndError("SessionEnd hook deadline exceeded during fingerprinting")
        digest.update(b"\x00")
        digest.update(path.encode("utf-8", errors="replace"))
        digest.update(b"\x00untracked" if path in untracked else b"\x00tracked")
        path_kind = "untracked path" if path in untracked else "tracked path"
        candidate = repo_root / path
        try:
            candidate.relative_to(repo_root)
            resolved_parent = candidate.parent.resolve(strict=True)
            if not _inside_repo(resolved_parent, repo_root):
                raise ValueError("changed path parent escapes repo")
            metadata = candidate.lstat()
        except FileNotFoundError as exc:
            if path in untracked:
                raise SessionEndError(
                    f"cannot fingerprint untracked path: {_redact(path, 300)}"
                ) from exc
            digest.update(b"\x00deleted")
            continue
        except (OSError, ValueError) as exc:
            raise SessionEndError(
                f"cannot fingerprint changed path: {_redact(path, 300)}"
            ) from exc
        digest.update(str(stat.S_IFMT(metadata.st_mode)).encode("ascii"))
        if stat.S_ISDIR(metadata.st_mode):
            digest.update(b"\x00directory")
            continue
        if stat.S_ISLNK(metadata.st_mode):
            digest.update(os.readlink(candidate).encode("utf-8", errors="replace"))
            after_link = candidate.lstat()
            before_identity = (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_mode,
                metadata.st_size,
                metadata.st_mtime_ns,
                metadata.st_ctime_ns,
            )
            after_identity = (
                after_link.st_dev,
                after_link.st_ino,
                after_link.st_mode,
                after_link.st_size,
                after_link.st_mtime_ns,
                after_link.st_ctime_ns,
            )
            if before_identity != after_identity:
                raise SessionEndError(
                    f"{path_kind} symlink changed during fingerprint: {_redact(path, 300)}"
                )
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise SessionEndError(
                f"changed path is not a regular file: {_redact(path, 300)}"
            )
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(candidate, flags)
        except OSError as exc:
            raise SessionEndError(
                f"cannot open changed path safely: {_redact(path, 300)}"
            ) from exc
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            opened = os.fstat(handle.fileno())
            preopen_identity = (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_mode,
                metadata.st_size,
                metadata.st_mtime_ns,
                metadata.st_ctime_ns,
            )
            opened_identity = (
                opened.st_dev,
                opened.st_ino,
                opened.st_mode,
                opened.st_size,
                opened.st_mtime_ns,
                opened.st_ctime_ns,
            )
            if preopen_identity != opened_identity:
                raise SessionEndError(
                    f"{path_kind} changed before fingerprint: {_redact(path, 300)}"
                )
            total_bytes += opened.st_size
            if total_bytes > MAX_UNTRACKED_HASH_BYTES:
                raise SessionEndError(
                    "changed content exceeds the 64 MiB fingerprint bound"
                )
            while True:
                if deadline is not None and time.monotonic() >= deadline:
                    raise SessionEndError(
                        "SessionEnd hook deadline exceeded during fingerprinting"
                    )
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
            finished = os.fstat(handle.fileno())
        finished_identity = (
            finished.st_dev,
            finished.st_ino,
            finished.st_mode,
            finished.st_size,
            finished.st_mtime_ns,
            finished.st_ctime_ns,
        )
        if opened_identity != finished_identity:
            raise SessionEndError(
                f"{path_kind} changed during fingerprint: {_redact(path, 300)}"
            )
    return digest.hexdigest()


def _canonical_json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _validate_existing_request(
    path: Path,
    *,
    request_id: str,
    session_id: str,
    fingerprint: str,
) -> None:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_EVENT_BYTES:
            raise SessionEndError("conflicting closeout request is not a bounded regular file")
        existing = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SessionEndError("conflicting closeout request cannot be validated") from exc
    if not isinstance(existing, dict):
        raise SessionEndError("conflicting closeout request is not an object")
    stored_hash = existing.get("request_sha256")
    unsigned = {key: item for key, item in existing.items() if key != "request_sha256"}
    computed_hash = hashlib.sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    repo = existing.get("repo")
    if (
        existing.get("schema") != "seam-agent-closeout-request/v1"
        or existing.get("request_id") != request_id
        or existing.get("session_id") != session_id
        or stored_hash != computed_hash
        or not isinstance(repo, dict)
        or repo.get("diff_fingerprint") != fingerprint
    ):
        raise SessionEndError("conflicting closeout request already exists")


def _atomic_json_once(path: Path, value: dict[str, Any]) -> bool:
    if path.parent.is_symlink():
        raise SessionEndError("closeout request directory cannot be a symlink")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    encoded = _canonical_json(value)
    if len(encoded) > MAX_EVENT_BYTES:
        raise SessionEndError("closeout request exceeds the 1 MiB bound")
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
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
    finally:
        temporary.unlink(missing_ok=True)
    return True


def handle_session_end(
    event: dict[str, Any],
    *,
    repo_root: Path = REPO_ROOT,
    state_root: Path = DEFAULT_STATE_ROOT,
    dispatch: bool = False,
) -> dict[str, Any]:
    """Validate one hook event and atomically queue a release-agent request."""

    if os.environ.get(RECURSION_GUARD_ENV) == "1":
        return {"status": "SKIPPED_RECURSION_GUARD"}
    if dispatch:
        raise SessionEndError("SessionEnd supports durable queueing, not nested model dispatch")
    deadline = time.monotonic() + HOOK_BUDGET_SECONDS
    repo_root = repo_root.resolve(strict=True)
    cwd_value = event.get("cwd")
    if not isinstance(cwd_value, str) or not cwd_value:
        raise SessionEndError("cwd is required")
    cwd = Path(cwd_value).expanduser().resolve(strict=True)
    if not _inside_repo(cwd, repo_root):
        return {"status": "SKIPPED_OUTSIDE_REPO"}
    if (
        _git_text(repo_root, "rev-parse", "--show-toplevel", deadline=deadline)
        != str(repo_root)
    ):
        raise SessionEndError("configured repo root is not the active Git root")

    session_id = _safe_session_id(event.get("session_id"))
    state = _load_session_state(session_id, repo_root=repo_root, state_root=state_root)
    base_sha = _valid_base(
        repo_root, state.get("base_sha") if state else None, deadline=deadline
    )
    if state is not None and base_sha is None:
        raise SessionEndError("session state base_sha does not resolve to a commit")
    paths, paths_truncated = _changed_paths(repo_root, base_sha, deadline=deadline)
    if not paths:
        return {"status": "CLEAN_NO_REQUEST"}
    displayed_paths = paths[:MAX_CHANGED_PATHS]

    head = _git_text(repo_root, "rev-parse", "HEAD", deadline=deadline)
    fingerprint = _fingerprint(
        repo_root, head, base_sha, paths, deadline=deadline
    )
    request_id = f"{session_id}-{fingerprint[:16]}"
    request_path = state_root / "requests" / f"{request_id}.json"
    receipt_path = state_root / "receipts" / f"{request_id}.json"
    if os.path.lexists(request_path):
        _validate_existing_request(
            request_path,
            request_id=request_id,
            session_id=session_id,
            fingerprint=fingerprint,
        )
        return {
            "status": "ALREADY_QUEUED",
            "request_id": request_id,
            "request_path": str(request_path),
        }

    runtime = runtime_paths(displayed_paths)
    tdd_evidence = assess_tdd(displayed_paths, state)
    change_class = "runtime" if runtime else "non_runtime"
    if paths_truncated:
        change_class = "runtime"
        tdd_evidence = {
            "status": "TDD_UNPROVEN",
            "runtime_paths": runtime,
            "covered_runtime_paths": [],
            "missing_runtime_paths": runtime,
            "cycle_count": tdd_evidence["cycle_count"],
        }
    request = {
        "schema": "seam-agent-closeout-request/v1",
        "request_id": request_id,
        "session_id": session_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "trigger": "SessionEnd",
        "repo": {
            "root": str(repo_root),
            "cwd": str(cwd),
            "branch": _git_text(
                repo_root,
                "branch",
                "--show-current",
                check=False,
                deadline=deadline,
            )
            or "detached",
            "head": head,
            "base_sha": base_sha,
            "origin_main": _git_text(
                repo_root,
                "rev-parse",
                "origin/main",
                check=False,
                deadline=deadline,
            )
            or None,
            "worktree": str(repo_root),
            "diff_fingerprint": fingerprint,
            "changed_paths": displayed_paths,
            "changed_paths_truncated": paths_truncated,
        },
        "change_class": change_class,
        "context": _bounded_context(state),
        "tdd_evidence": tdd_evidence,
        "authority": {
            "mode": "verify_only",
            "allowed_writes": [],
            "forbidden_actions": [
                "repair source or tests",
                "append or edit HISTORY.md",
                "stage, commit, push, merge, or release",
                "invoke paid providers",
            ],
        },
        "required_checks": list(REQUIRED_CLOSEOUT_CHECKS),
        "receipt_path": str(receipt_path),
        "request_schema": "tools/agents/schemas/closeout-request.schema.json",
        "receipt_schema": "tools/agents/schemas/closeout-receipt.schema.json",
    }
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":")).encode("utf-8")
    request["request_sha256"] = hashlib.sha256(canonical).hexdigest()
    stored = _atomic_json_once(request_path, request)
    if not stored:
        _validate_existing_request(
            request_path,
            request_id=request_id,
            session_id=session_id,
            fingerprint=fingerprint,
        )
        return {
            "status": "ALREADY_QUEUED",
            "request_id": request_id,
            "request_path": str(request_path),
        }
    return {
        "status": "QUEUED",
        "request_id": request_id,
        "request_path": str(request_path),
        "tdd_status": request["tdd_evidence"]["status"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Queue a bounded SEAM closeout-agent request.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    args = parser.parse_args(argv)
    if os.environ.get(RECURSION_GUARD_ENV) == "1":
        print(json.dumps({"status": "SKIPPED_RECURSION_GUARD"}), file=sys.stderr)
        return 0
    try:
        raw = sys.stdin.buffer.read(MAX_EVENT_BYTES + 1)
        if len(raw) > MAX_EVENT_BYTES:
            raise SessionEndError("hook event exceeds the 1 MiB bound")
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise SessionEndError("hook event must be a JSON object")
        result = handle_session_end(
            event,
            repo_root=args.repo_root,
            state_root=args.state_root,
        )
    except Exception as exc:
        print(f"SEAM SessionEnd closeout queue failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
