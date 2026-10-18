#!/usr/bin/env python3
"""Persist and enforce exact-state independent assurance for Codex sessions."""

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
from datetime import datetime
from pathlib import Path
from typing import Any

from tools.agents import context_guardian
from tools.agents.session_end_closeout import _changed_paths, _fingerprint

SCHEMA = "seam-independent-assurance/v1"
REPOSITORY = "Canticle-AI-Research/Seam"
MAX_RECORD_BYTES = 256 * 1024
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,180}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
REPORT_FIELDS = {
    "schema",
    "repository",
    "session_id",
    "base_sha",
    "head",
    "changed_paths",
    "content_sha256",
    "reviewed_at",
    "reviewer",
    "status",
    "continuity_included",
    "summary",
}
REGISTRATION_FIELDS = {
    "schema",
    "kind",
    "repository",
    "repository_common_dir",
    "session_id",
    "worktree_root",
    "base_sha",
}
SUCCESSOR_REGISTRATION_FIELDS = REGISTRATION_FIELDS | {"successor_transition_sha256"}
ACTIVE_FIELDS = {
    "schema",
    "kind",
    "repository_common_dir",
    "session_id",
    "worktree_root",
}
ACCEPTED_FIELDS = {"schema", "kind", "report_sha256", "report_bytes", "report"}
SELECTION_FIELDS = {
    "schema",
    "kind",
    "session_id",
    "head",
    "report_sha256",
    "accepted_path",
}
REQUEST_ACCEPTED_FIELDS = {
    "schema",
    "kind",
    "request_id",
    "request_sha256",
    "request_bytes_sha256",
    "report_sha256",
    "report_bytes",
    "report",
}


class AssuranceError(RuntimeError):
    """An assurance record or exact live scope is invalid."""


def _git(repo_root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise AssuranceError("assurance cannot inspect the Git repository")
    return result.stdout.strip()


def _common_dir(repo_root: Path) -> Path:
    value = _git(repo_root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    path = Path(value)
    if not path.is_absolute():
        path = repo_root / path
    path = path.resolve(strict=True)
    if path.is_symlink() or not path.is_dir():
        raise AssuranceError("assurance Git common directory is unsafe")
    return path


def _canonical(value: dict[str, Any]) -> bytes:
    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(encoded) > MAX_RECORD_BYTES:
        raise AssuranceError("assurance record exceeds 256 KiB")
    return encoded


def _ensure_directory(path: Path) -> None:
    ancestor = path
    while not os.path.lexists(ancestor) and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    if ancestor.is_symlink() or not ancestor.is_dir() or ancestor.resolve() != ancestor:
        raise AssuranceError("assurance state directory has an unsafe ancestor")
    if os.path.lexists(path) and (path.is_symlink() or not path.is_dir()):
        raise AssuranceError("assurance state directory must be a real directory")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.resolve() != path:
        raise AssuranceError("assurance state directory is unsafe")


def _publish_once(path: Path, encoded: bytes) -> bool:
    _ensure_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
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


def _write_replace(path: Path, value: dict[str, Any]) -> None:
    encoded = _canonical(value)
    _ensure_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load(path: Path) -> dict[str, Any]:
    descriptor: int | None = None
    try:
        if path.is_symlink():
            raise AssuranceError("assurance record must not be a symlink")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_RECORD_BYTES:
            raise AssuranceError("assurance record is unsafe or oversized")
        encoded = b""
        while len(encoded) <= MAX_RECORD_BYTES:
            chunk = os.read(descriptor, min(65536, MAX_RECORD_BYTES + 1 - len(encoded)))
            if not chunk:
                break
            encoded += chunk
        if len(encoded) > MAX_RECORD_BYTES:
            raise AssuranceError("assurance record exceeds 256 KiB")
        value = json.loads(encoded.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssuranceError(f"cannot load assurance record: {path.name}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if not isinstance(value, dict):
        raise AssuranceError("assurance record must be an object")
    return value


def _session_id(value: object) -> str:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise AssuranceError("assurance session_id is unsafe")
    return value


def _worktree_key(repo_root: Path) -> str:
    return hashlib.sha256(str(repo_root).encode("utf-8")).hexdigest()


def _registration_root(common_dir: Path) -> Path:
    return common_dir / "seam-orchestration" / "assurance" / "registrations"


def _registration_path(common_dir: Path, session_id: str) -> Path:
    return _registration_root(common_dir) / f"{_session_id(session_id)}.json"


def _active_path(common_dir: Path, repo_root: Path) -> Path:
    return common_dir / "seam-orchestration" / "assurance" / "active" / f"{_worktree_key(repo_root)}.json"


def _accepted_path(common_dir: Path, session_id: str) -> Path:
    return common_dir / "seam-orchestration" / "assurance" / "accepted" / session_id


def _selection_path(common_dir: Path, session_id: str) -> Path:
    return common_dir / "seam-orchestration" / "assurance" / "selected" / f"{session_id}.json"


def _validate_registration(value: dict[str, Any], common_dir: Path, path: Path) -> dict[str, Any]:
    if (
        set(value) not in (REGISTRATION_FIELDS, SUCCESSOR_REGISTRATION_FIELDS)
        or value.get("schema") != SCHEMA
        or value.get("kind") != "registration"
        or value.get("repository") != REPOSITORY
        or value.get("repository_common_dir") != str(common_dir)
    ):
        raise AssuranceError("assurance registration does not match its contract")
    _session_id(value.get("session_id"))
    raw_root = value.get("worktree_root")
    if not isinstance(raw_root, str) or not raw_root or len(raw_root) > 1000:
        raise AssuranceError("assurance worktree root is invalid")
    root = Path(raw_root)
    if not root.is_absolute() or ".." in root.parts:
        raise AssuranceError("assurance worktree root is unsafe")
    base_sha = value.get("base_sha")
    if not isinstance(base_sha, str) or not COMMIT.fullmatch(base_sha):
        raise AssuranceError("assurance registered base is invalid")
    if path != _registration_path(common_dir, value["session_id"]):
        raise AssuranceError("assurance registration path does not match its session")
    transition_digest = value.get("successor_transition_sha256")
    if transition_digest is not None and (
        not isinstance(transition_digest, str) or not SHA256.fullmatch(transition_digest)
    ):
        raise AssuranceError("assurance successor transition hash is invalid")
    return value


def _validate_active(
    value: dict[str, Any], common_dir: Path, repo_root: Path
) -> dict[str, Any]:
    if (
        set(value) != ACTIVE_FIELDS
        or value.get("schema") != SCHEMA
        or value.get("kind") != "active-worktree"
        or value.get("repository_common_dir") != str(common_dir)
        or value.get("worktree_root") != str(repo_root)
    ):
        raise AssuranceError("active assurance binding does not match its contract")
    _session_id(value.get("session_id"))
    return value


def register(
    repo_root: Path,
    session_id: str,
    base_sha: str,
    *,
    successor_transition_sha256: str | None = None,
) -> dict[str, Any]:
    """Persist the active session binding for one worktree."""

    repo_root = repo_root.resolve(strict=True)
    session_id = _session_id(session_id)
    if not isinstance(base_sha, str) or not COMMIT.fullmatch(base_sha):
        raise AssuranceError("assurance base_sha is invalid")
    if _git(repo_root, "rev-parse", "--verify", f"{base_sha}^{{commit}}") != base_sha:
        raise AssuranceError("assurance base_sha does not resolve exactly")
    common_dir = _common_dir(repo_root)
    active_path = _active_path(common_dir, repo_root)
    if active_path.is_file():
        active = _validate_active(_load(active_path), common_dir, repo_root)
        if active["session_id"] != session_id:
            context_root = repo_root / ".seam" / "orchestration" / "context"
            if context_guardian.has_unresolved_recovery(
                active["session_id"],
                state_root=context_root,
                handoff_root=repo_root / ".context-handoffs",
            ) and successor_transition_sha256 is None:
                raise AssuranceError(
                    "recovered active binding requires the successor transition CLI"
                )
    value = {
        "schema": SCHEMA,
        "kind": "registration",
        "repository": REPOSITORY,
        "repository_common_dir": str(common_dir),
        "session_id": session_id,
        "worktree_root": str(repo_root),
        "base_sha": base_sha,
    }
    if successor_transition_sha256 is not None:
        if not SHA256.fullmatch(successor_transition_sha256):
            raise AssuranceError("assurance successor transition hash is invalid")
        value["successor_transition_sha256"] = successor_transition_sha256
        from tools.agents import successor

        successor.validate_registration_binding(
            repo_root, value, require_complete_tdd=False
        )
    registration_path = _registration_path(common_dir, session_id)
    encoded = _canonical(value)
    if not _publish_once(registration_path, encoded):
        existing = _validate_registration(_load(registration_path), common_dir, registration_path)
        if _canonical(existing) != encoded:
            raise AssuranceError("conflicting immutable assurance registration exists")
    active = {
        "schema": SCHEMA,
        "kind": "active-worktree",
        "repository_common_dir": str(common_dir),
        "session_id": session_id,
        "worktree_root": str(repo_root),
    }
    _write_replace(_active_path(common_dir, repo_root), active)
    return {"session_id": session_id, "status": "REGISTERED"}


def _registrations(common_dir: Path) -> list[dict[str, Any]]:
    root = _registration_root(common_dir)
    if not os.path.lexists(root):
        return []
    if root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise AssuranceError("assurance registration directory is unsafe")
    result = []
    for path in sorted(root.glob("*.json"), key=lambda item: item.name):
        result.append(_validate_registration(_load(path), common_dir, path))
    return result


def _active_bindings(common_dir: Path) -> list[dict[str, Any]]:
    root = common_dir / "seam-orchestration" / "assurance" / "active"
    if not os.path.lexists(root):
        return []
    if root.is_symlink() or not root.is_dir() or root.resolve() != root:
        raise AssuranceError("active assurance directory is unsafe")
    result = []
    for path in sorted(root.glob("*.json"), key=lambda item: item.name):
        value = _load(path)
        raw_root = value.get("worktree_root")
        if not isinstance(raw_root, str):
            raise AssuranceError("active assurance worktree is invalid")
        repo_root = Path(raw_root)
        if path != _active_path(common_dir, repo_root):
            raise AssuranceError("active assurance binding path is invalid")
        result.append(_validate_active(value, common_dir, repo_root))
    return result


def _registration_for(repo_root: Path, session_id: str) -> tuple[Path, dict[str, Any]] | None:
    common_dir = _common_dir(repo_root)
    path = _registration_path(common_dir, session_id)
    if not path.is_file():
        return None
    value = _validate_registration(_load(path), common_dir, path)
    if "successor_transition_sha256" in value:
        from tools.agents import successor

        try:
            successor.validate_registration_binding(repo_root, value)
        except successor.SuccessorError as exc:
            raise AssuranceError(str(exc)) from exc
    active_path = _active_path(common_dir, repo_root)
    if not active_path.is_file():
        raise AssuranceError("session has no active assurance worktree binding")
    active = _validate_active(_load(active_path), common_dir, repo_root)
    if active["session_id"] != session_id:
        raise AssuranceError("session is not the active assurance worktree binding")
    return common_dir, value


def _timestamp(value: object) -> None:
    if not isinstance(value, str) or len(value) > 80:
        raise AssuranceError("assurance reviewed_at is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AssuranceError("assurance reviewed_at is invalid") from exc
    if parsed.tzinfo is None:
        raise AssuranceError("assurance reviewed_at must include a timezone")


def _validate_report(value: dict[str, Any], session_id: str) -> dict[str, Any]:
    if set(value) != REPORT_FIELDS or value.get("schema") != SCHEMA:
        raise AssuranceError("assurance report does not match its contract")
    if value.get("repository") != REPOSITORY or value.get("session_id") != session_id:
        raise AssuranceError("assurance report identity does not match registration")
    if value.get("status") != "PASS" or value.get("continuity_included") is not True:
        raise AssuranceError("assurance report must pass and include continuity")
    for field in ("base_sha", "head"):
        if not isinstance(value.get(field), str) or not COMMIT.fullmatch(value[field]):
            raise AssuranceError(f"assurance {field} is invalid")
    if not isinstance(value.get("content_sha256"), str) or not SHA256.fullmatch(value["content_sha256"]):
        raise AssuranceError("assurance content_sha256 is invalid")
    paths = value.get("changed_paths")
    if (
        not isinstance(paths, list)
        or len(paths) > 4096
        or paths != sorted(set(paths))
        or any(not isinstance(path, str) or not path or len(path) > 1000 or path.startswith("/") or ".." in Path(path).parts for path in paths)
    ):
        raise AssuranceError("assurance changed_paths are invalid")
    summary = value.get("summary")
    if not isinstance(summary, list) or not summary or len(summary) > 32 or any(not isinstance(item, str) or not item.strip() or len(item) > 2000 for item in summary):
        raise AssuranceError("assurance summary is invalid")
    reviewer = value.get("reviewer")
    if (
        not isinstance(reviewer, str)
        or not reviewer.strip()
        or len(reviewer) > 200
        or "\n" in reviewer
        or "\r" in reviewer
    ):
        raise AssuranceError("assurance reviewer is invalid")
    _timestamp(value.get("reviewed_at"))
    return value


def _report_source(path: Path, session_id: str) -> tuple[dict[str, Any], bytes]:
    first = _load(path)
    raw = path.read_bytes()
    second = _load(path)
    if first != second or raw != path.read_bytes():
        raise AssuranceError("assurance report changed while reading")
    return _validate_report(second, session_id), raw


def _load_selected_report(
    common_dir: Path, session_id: str
) -> dict[str, Any]:
    selection_path = _selection_path(common_dir, session_id)
    if not selection_path.is_file():
        raise AssuranceError("registered session lacks accepted assurance")
    selection = _load(selection_path)
    if (
        set(selection) != SELECTION_FIELDS
        or selection.get("schema") != SCHEMA
        or selection.get("kind") != "selected-report"
        or selection.get("session_id") != session_id
        or not isinstance(selection.get("report_sha256"), str)
        or not SHA256.fullmatch(selection["report_sha256"])
        or not isinstance(selection.get("head"), str)
        or not COMMIT.fullmatch(selection["head"])
    ):
        raise AssuranceError("selected assurance record is invalid")
    accepted_path = Path(str(selection.get("accepted_path")))
    expected = _accepted_path(common_dir, session_id) / f"{selection['report_sha256']}.json"
    if accepted_path != expected:
        raise AssuranceError("selected assurance path is invalid")
    accepted = _load(accepted_path)
    if (
        set(accepted) != ACCEPTED_FIELDS
        or accepted.get("schema") != SCHEMA
        or accepted.get("kind") != "accepted-report"
        or accepted.get("report_sha256") != selection["report_sha256"]
        or not isinstance(accepted.get("report_bytes"), str)
        or not isinstance(accepted.get("report"), dict)
    ):
        raise AssuranceError("accepted assurance record is invalid")
    report_bytes = accepted["report_bytes"].encode("utf-8")
    try:
        parsed_report = json.loads(report_bytes)
    except json.JSONDecodeError as exc:
        raise AssuranceError("accepted assurance report bytes are invalid") from exc
    if (
        hashlib.sha256(report_bytes).hexdigest() != accepted["report_sha256"]
        or parsed_report != accepted["report"]
    ):
        raise AssuranceError("accepted assurance report hash is invalid")
    report = _validate_report(accepted["report"], session_id)
    if report["head"] != selection["head"]:
        raise AssuranceError("selected assurance head is invalid")
    return report


def _live_scope(repo_root: Path, base_sha: str) -> tuple[str, list[str], str]:
    head = _git(repo_root, "rev-parse", "HEAD")
    paths, truncated = _changed_paths(repo_root, base_sha)
    if truncated:
        raise AssuranceError("assurance changed path scope is truncated")
    return head, paths, _fingerprint(repo_root, head, base_sha, paths)


def _require_clean_candidate(repo_root: Path) -> None:
    if _git(repo_root, "status", "--porcelain=v1", "--untracked-files=all"):
        raise AssuranceError("assurance requires a clean committed candidate")


def _check_recovery(
    repo_root: Path, session_id: str, registration: dict[str, Any] | None = None
) -> None:
    if registration is not None and "successor_transition_sha256" in registration:
        from tools.agents import successor

        try:
            successor.validate_registration_binding(repo_root, registration)
        except successor.SuccessorError as exc:
            raise AssuranceError(str(exc)) from exc
    state_root = repo_root / ".seam" / "orchestration" / "context"
    if context_guardian.has_unresolved_recovery(
        session_id,
        state_root=state_root,
        handoff_root=repo_root / ".context-handoffs",
    ):
        raise AssuranceError("unexpected compaction recovery requires a successor session")


def accept(repo_root: Path, session_id: str, report_path: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve(strict=True)
    session_id = _session_id(session_id)
    binding = _registration_for(repo_root, session_id)
    if binding is None:
        raise AssuranceError("session is not registered for assurance")
    common_dir, registration = binding
    if registration["worktree_root"] != str(repo_root):
        raise AssuranceError("assurance session belongs to a different worktree")
    report, report_bytes = _report_source(report_path, session_id)
    if report["base_sha"] != registration["base_sha"]:
        raise AssuranceError("assurance report does not match registered base")
    _check_recovery(repo_root, session_id, registration)
    _require_clean_candidate(repo_root)
    first = _live_scope(repo_root, report["base_sha"])
    second = _live_scope(repo_root, report["base_sha"])
    if first != second:
        raise AssuranceError("assurance scope changed while reading")
    if second != (report["head"], report["changed_paths"], report["content_sha256"]):
        raise AssuranceError("assurance report does not match exact live scope")
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    destination = _accepted_path(common_dir, session_id) / f"{report_sha256}.json"
    accepted = {
        "schema": SCHEMA,
        "kind": "accepted-report",
        "report_sha256": report_sha256,
        "report_bytes": report_bytes.decode("utf-8"),
        "report": report,
    }
    created = _publish_once(destination, _canonical(accepted))
    if not created and _canonical(_load(destination)) != _canonical(accepted):
        raise AssuranceError("conflicting immutable assurance report exists")
    _write_replace(
        _selection_path(common_dir, session_id),
        {
            "schema": SCHEMA,
            "kind": "selected-report",
            "session_id": session_id,
            "head": report["head"],
            "report_sha256": report_sha256,
            "accepted_path": str(destination),
        },
    )
    return {
        "report_sha256": report_sha256,
        "session_id": session_id,
        "status": "ACCEPTED" if created else "ALREADY_ACCEPTED",
    }


def check_session(
    repo_root: Path, session_id: str, *, expected_head: str | None = None
) -> dict[str, Any]:
    repo_root = repo_root.resolve(strict=True)
    session_id = _session_id(session_id)
    binding = _registration_for(repo_root, session_id)
    if binding is None:
        common_dir = _common_dir(repo_root)
        if any(
            active["session_id"] == session_id
            and active["worktree_root"] == str(repo_root)
            for active in _active_bindings(common_dir)
        ):
            raise AssuranceError("active assurance binding lacks immutable registration")
        return {"session_id": session_id, "status": "NOT_APPLICABLE"}
    common_dir, registration = binding
    bound_root = Path(registration["worktree_root"])
    if not bound_root.is_dir():
        raise AssuranceError("registered assurance worktree is missing")
    report = _load_selected_report(common_dir, session_id)
    if report["base_sha"] != registration["base_sha"]:
        raise AssuranceError("accepted assurance does not match registered base")
    if expected_head is not None and report["head"] != expected_head:
        raise AssuranceError("accepted assurance does not match outgoing head")
    _check_recovery(bound_root, session_id, registration)
    _require_clean_candidate(bound_root)
    first = _live_scope(bound_root, report["base_sha"])
    second = _live_scope(bound_root, report["base_sha"])
    if first != second:
        raise AssuranceError("assurance scope changed while checking")
    if second != (report["head"], report["changed_paths"], report["content_sha256"]):
        raise AssuranceError("scope changed after assurance")
    return {"session_id": session_id, "status": "PASS"}


def successor_transition(repo_root: Path, session_id: str) -> dict[str, Any] | None:
    """Return the validated transition for a successor registration, if present."""

    repo_root = repo_root.resolve(strict=True)
    binding = _registration_for(repo_root, _session_id(session_id))
    if binding is None:
        return None
    _, registration = binding
    if "successor_transition_sha256" not in registration:
        return None
    from tools.agents import successor

    try:
        return successor.validate_registration_binding(repo_root, registration)
    except successor.SuccessorError as exc:
        raise AssuranceError(str(exc)) from exc


def check_push(repo_root: Path, expected_head: str) -> dict[str, Any]:
    repo_root = repo_root.resolve(strict=True)
    common_dir = _common_dir(repo_root)
    if not isinstance(expected_head, str) or not COMMIT.fullmatch(expected_head):
        raise AssuranceError("outgoing head is invalid")
    registrations = _registrations(common_dir)
    registrations_by_session = {
        registration["session_id"]: registration for registration in registrations
    }
    active_bindings = _active_bindings(common_dir)
    for active in active_bindings:
        registration = registrations_by_session.get(active["session_id"])
        if registration is None or registration["worktree_root"] != active["worktree_root"]:
            raise AssuranceError("active assurance binding lacks immutable registration")

    current = next(
        (item for item in active_bindings if item["worktree_root"] == str(repo_root)),
        None,
    )
    current_registrations = [
        item for item in registrations if item["worktree_root"] == str(repo_root)
    ]
    if current is None and current_registrations:
        raise AssuranceError("registered worktree lacks active assurance binding")
    if current is not None:
        result = check_session(
            repo_root, current["session_id"], expected_head=expected_head
        )
        if result["status"] != "PASS":
            raise AssuranceError("active assurance session is not enforceable")
        return {"sessions": [result], "status": "PASS"}

    for active in active_bindings:
        registration = registrations_by_session[active["session_id"]]
        bound_root = Path(registration["worktree_root"])
        if bound_root.is_dir() and _git(bound_root, "rev-parse", "HEAD") == expected_head:
            result = check_session(
                bound_root,
                active["session_id"],
                expected_head=expected_head,
            )
            if result["status"] != "PASS":
                raise AssuranceError("registered outgoing candidate is not enforceable")
            return {"sessions": [result], "status": "PASS"}
        report = _load_selected_report(common_dir, active["session_id"])
        if report["head"] != expected_head:
            continue
        result = check_session(
            Path(registration["worktree_root"]),
            active["session_id"],
            expected_head=expected_head,
        )
        if result["status"] != "PASS":
            raise AssuranceError("registered outgoing candidate is not enforceable")
        return {"sessions": [result], "status": "PASS"}
    active_sessions = {item["session_id"] for item in active_bindings}
    for registration in registrations:
        if registration["session_id"] in active_sessions:
            continue
        try:
            report = _load_selected_report(common_dir, registration["session_id"])
        except AssuranceError as exc:
            if "lacks accepted assurance" in str(exc):
                continue
            raise
        if report["head"] == expected_head:
            raise AssuranceError(
                "registered outgoing candidate lacks active assurance binding"
            )
    return {"sessions": [], "status": "NOT_APPLICABLE"}


def enforcement_active(repo_root: Path) -> bool:
    common_dir = _common_dir(repo_root.resolve(strict=True))
    return os.path.lexists(_registration_root(common_dir))


def _request_assurance_root(common_dir: Path, request_id: str) -> Path:
    return (
        common_dir
        / "seam-orchestration"
        / "assurance"
        / "requests"
        / _session_id(request_id)
    )


def accept_request(
    repo_root: Path, request_path: Path, report_path: Path, state_root: Path
) -> dict[str, Any]:
    """Bind assurance directly to one pre-enforcement immutable queued request."""

    from tools.agents import closeout_queue

    repo_root = repo_root.resolve(strict=True)
    state_root = state_root.resolve()
    first_raw = request_path.read_bytes()
    request = closeout_queue.validate_request(_load(request_path), state_root=state_root)
    expected_path = state_root / "requests" / f"{request['request_id']}.json"
    if request_path.resolve(strict=True) != expected_path.resolve(strict=True):
        raise AssuranceError("administrative assurance requires the queued request path")
    second_raw = request_path.read_bytes()
    if first_raw != second_raw or _load(request_path) != request:
        raise AssuranceError("queued request changed while reading")
    request_repo = request["repo"]
    if request_repo["root"] != str(repo_root):
        raise AssuranceError("queued request belongs to a different repository root")
    report, report_bytes = _report_source(report_path, request["session_id"])
    expected_scope = (
        request_repo["base_sha"],
        request_repo["head"],
        request_repo["changed_paths"],
        request_repo["diff_fingerprint"],
    )
    report_scope = (
        report["base_sha"],
        report["head"],
        report["changed_paths"],
        report["content_sha256"],
    )
    if report_scope != expected_scope:
        raise AssuranceError("administrative assurance does not match queued request scope")
    _check_recovery(repo_root, request["session_id"])
    _require_clean_candidate(repo_root)
    first = _live_scope(repo_root, report["base_sha"])
    second = _live_scope(repo_root, report["base_sha"])
    if first != second or second != (
        report["head"],
        report["changed_paths"],
        report["content_sha256"],
    ):
        raise AssuranceError("administrative assurance does not match stable live scope")
    report_sha256 = hashlib.sha256(report_bytes).hexdigest()
    accepted = {
        "schema": SCHEMA,
        "kind": "accepted-request-report",
        "request_id": request["request_id"],
        "request_sha256": request["request_sha256"],
        "request_bytes_sha256": hashlib.sha256(first_raw).hexdigest(),
        "report_sha256": report_sha256,
        "report_bytes": report_bytes.decode("utf-8"),
        "report": report,
    }
    root = _request_assurance_root(_common_dir(repo_root), request["request_id"])
    destination = root / f"{report_sha256}.json"
    created = _publish_once(destination, _canonical(accepted))
    if not created and _canonical(_load(destination)) != _canonical(accepted):
        raise AssuranceError("conflicting request assurance report exists")
    _write_replace(root / "selected.json", accepted)
    return {
        "report_sha256": report_sha256,
        "request_id": request["request_id"],
        "status": "ACCEPTED" if created else "ALREADY_ACCEPTED",
    }


def check_request(request: dict[str, Any], *, state_root: Path) -> dict[str, Any]:
    repo_root = Path(request["repo"]["root"]).resolve(strict=True)
    root = _request_assurance_root(_common_dir(repo_root), request["request_id"])
    selected_path = root / "selected.json"
    if not selected_path.is_file():
        return {"request_id": request["request_id"], "status": "NOT_APPLICABLE"}
    accepted = _load(selected_path)
    if (
        set(accepted) != REQUEST_ACCEPTED_FIELDS
        or accepted.get("schema") != SCHEMA
        or accepted.get("kind") != "accepted-request-report"
        or accepted.get("request_id") != request["request_id"]
        or accepted.get("request_sha256") != request["request_sha256"]
        or not isinstance(accepted.get("request_bytes_sha256"), str)
        or not SHA256.fullmatch(accepted["request_bytes_sha256"])
        or not isinstance(accepted.get("report_sha256"), str)
        or not SHA256.fullmatch(accepted["report_sha256"])
        or not isinstance(accepted.get("report_bytes"), str)
        or not isinstance(accepted.get("report"), dict)
    ):
        raise AssuranceError("request assurance record is invalid")
    immutable = root / f"{accepted['report_sha256']}.json"
    if not immutable.is_file() or _canonical(_load(immutable)) != _canonical(accepted):
        raise AssuranceError("selected request assurance lacks immutable evidence")
    queued_path = state_root.resolve() / "requests" / f"{request['request_id']}.json"
    if hashlib.sha256(queued_path.read_bytes()).hexdigest() != accepted.get(
        "request_bytes_sha256"
    ):
        raise AssuranceError("queued request bytes changed after assurance")
    report = _validate_report(accepted["report"], request["session_id"])
    report_bytes = accepted["report_bytes"].encode("utf-8")
    try:
        parsed_report = json.loads(report_bytes)
    except json.JSONDecodeError as exc:
        raise AssuranceError("request assurance report bytes are invalid") from exc
    if (
        hashlib.sha256(report_bytes).hexdigest() != accepted["report_sha256"]
        or parsed_report != report
    ):
        raise AssuranceError("request assurance report hash is invalid")
    _check_recovery(repo_root, request["session_id"])
    _require_clean_candidate(repo_root)
    live = _live_scope(repo_root, report["base_sha"])
    if live != (report["head"], report["changed_paths"], report["content_sha256"]):
        raise AssuranceError("scope changed after request assurance")
    return {"request_id": request["request_id"], "status": "PASS"}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    register_command = commands.add_parser("register")
    register_command.add_argument("--session-id", required=True)
    register_command.add_argument("--base-sha", required=True)
    accept_command = commands.add_parser("accept")
    accept_command.add_argument("--session-id", required=True)
    accept_command.add_argument("--report", type=Path, required=True)
    check_command = commands.add_parser("check")
    check_command.add_argument("--session-id", required=True)
    check_push_command = commands.add_parser("check-push")
    check_push_command.add_argument("--head", required=True)
    accept_request_command = commands.add_parser("accept-request")
    accept_request_command.add_argument("--request", type=Path, required=True)
    accept_request_command.add_argument("--report", type=Path, required=True)
    accept_request_command.add_argument("--state-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "register":
            result = register(args.repo_root, args.session_id, args.base_sha)
        elif args.command == "accept":
            result = accept(args.repo_root, args.session_id, args.report)
        elif args.command == "check":
            result = check_session(args.repo_root, args.session_id)
        elif args.command == "accept-request":
            result = accept_request(
                args.repo_root, args.request, args.report, args.state_root
            )
        else:
            result = check_push(args.repo_root, args.head)
    except (AssuranceError, context_guardian.ContextGuardianError, OSError, ValueError) as exc:
        print(f"assurance failed closed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
