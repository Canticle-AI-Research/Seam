#!/usr/bin/env python3
"""Create one immutable same-worktree successor after context recovery."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.agents import assurance, closeout_queue, context_guardian
from tools.agents.session_end_closeout import (
    SessionEndError,
    _changed_paths,
    assess_tdd,
    runtime_paths,
    validate_session_state,
)

SCHEMA = "seam-session-successor-transition/v1"
MAX_BYTES = 1024 * 1024
MAX_MANIFEST_MEMBER_BYTES = 64 * 1024 * 1024
UNSUPPORTED_JSON_BOMS = (
    b"\xef\xbb\xbf",
    b"\xff\xfe\x00\x00",
    b"\x00\x00\xfe\xff",
    b"\xff\xfe",
    b"\xfe\xff",
)
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,200}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
FIELDS = {
    "schema", "predecessor_session_id", "successor_session_id",
    "recovery_event_id", "repository_common_dir", "worktree_root", "branch",
    "original_base_sha", "activation_sha", "request_id", "artifacts",
    "repair_artifacts", "external_recoveries", "queue_roots",
    "queue_record_sha256s", "created_at",
}
EXTERNAL_RECOVERY_REQUIRED_FIELDS = {
    "schema", "external_root", "session_id", "event_id", "status",
    "missing_checkpoint", "compaction_count", "guardian_state", "handoff",
    "recovery_event", "result_status", "evidence_manifest", "binding_path",
    "binding_sha256",
}
EXTERNAL_RECOVERY_OPTIONAL_FIELDS = {"checkpoint", "result"}
EXTERNAL_SOURCE_REQUIRED_FIELDS = EXTERNAL_RECOVERY_REQUIRED_FIELDS - {
    "binding_path", "binding_sha256"
}


class SuccessorError(RuntimeError):
    """The recovery transition is unsafe, incomplete, or conflicting."""


def _git(repo_root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=repo_root, capture_output=True, text=True, check=False
    )
    if result.returncode:
        raise SuccessorError("successor cannot inspect the Git repository")
    return result.stdout.strip()


def _common_dir(repo_root: Path) -> Path:
    raw = _git(repo_root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    path = Path(raw) if Path(raw).is_absolute() else repo_root / raw
    path = path.resolve(strict=True)
    if path.is_symlink() or not path.is_dir():
        raise SuccessorError("successor Git common directory is unsafe")
    return path


def _safe_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise SuccessorError(f"successor {label} is unsafe")
    return value


def _read_bytes(path: Path) -> bytes:
    descriptor: int | None = None
    try:
        if not path.is_absolute() or ".." in path.parts:
            raise SuccessorError(f"successor artifact path is unsafe: {path.name}")
        if path.is_symlink() or path.resolve(strict=True) != path:
            raise SuccessorError(f"successor artifact must be a regular file: {path.name}")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
            raise SuccessorError(f"successor artifact is unsafe or oversized: {path.name}")
        encoded = b""
        while len(encoded) <= MAX_BYTES:
            chunk = os.read(descriptor, min(65536, MAX_BYTES + 1 - len(encoded)))
            if not chunk:
                break
            encoded += chunk
        after = os.fstat(descriptor)
        before_key = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        after_key = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        if len(encoded) > MAX_BYTES or before_key != after_key:
            raise SuccessorError(f"successor artifact changed while reading: {path.name}")
        return encoded
    except OSError as exc:
        raise SuccessorError(f"cannot read successor artifact: {path.name}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    encoded = _read_bytes(path)
    try:
        value = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SuccessorError(f"cannot decode successor artifact: {path.name}") from exc
    if not isinstance(value, dict):
        raise SuccessorError(f"successor artifact must be an object: {path.name}")
    return value, encoded


def _hash_manifest_member(
    path: Path,
) -> tuple[str, int, bytes | None, int | None, bytes]:
    descriptor: int | None = None
    try:
        if not path.is_absolute() or ".." in path.parts:
            raise SuccessorError(f"successor artifact path is unsafe: {path.name}")
        if path.is_symlink() or path.resolve(strict=True) != path:
            raise SuccessorError(f"successor artifact must be a regular file: {path.name}")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_size > MAX_MANIFEST_MEMBER_BYTES
        ):
            raise SuccessorError(
                f"successor manifest member is unsafe or oversized: {path.name}"
            )
        digest = hashlib.sha256()
        retained = bytearray() if before.st_size <= MAX_BYTES else None
        first_non_whitespace: int | None = None
        significant_prefix = bytearray()
        observed_size = 0
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            digest.update(chunk)
            observed_size += len(chunk)
            if retained is not None:
                retained.extend(chunk)
            if first_non_whitespace is None:
                first_non_whitespace = next(
                    (byte for byte in chunk if byte not in b" \t\r\n"), None
                )
            if len(significant_prefix) < 4:
                for byte in chunk:
                    if not significant_prefix and byte in b" \t\r\n":
                        continue
                    significant_prefix.append(byte)
                    if len(significant_prefix) == 4:
                        break
        after = os.fstat(descriptor)
        before_key = (
            before.st_dev, before.st_ino, before.st_size,
            before.st_mtime_ns, before.st_ctime_ns,
        )
        after_key = (
            after.st_dev, after.st_ino, after.st_size,
            after.st_mtime_ns, after.st_ctime_ns,
        )
        if observed_size != before.st_size or before_key != after_key:
            raise SuccessorError(f"successor artifact changed while reading: {path.name}")
        return (
            digest.hexdigest(),
            observed_size,
            bytes(retained) if retained is not None else None,
            first_non_whitespace,
            bytes(significant_prefix),
        )
    except OSError as exc:
        raise SuccessorError(f"cannot read successor artifact: {path.name}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _canonical(value: dict[str, Any]) -> bytes:
    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    if len(encoded) > MAX_BYTES:
        raise SuccessorError("successor transition exceeds 1 MiB")
    return encoded


def _publish_once(path: Path, encoded: bytes) -> bool:
    ancestor = path.parent
    while not os.path.lexists(ancestor) and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    if ancestor.is_symlink() or not ancestor.is_dir() or ancestor.resolve() != ancestor:
        raise SuccessorError("successor state directory has an unsafe ancestor")
    if os.path.lexists(path.parent) and (path.parent.is_symlink() or not path.parent.is_dir()):
        raise SuccessorError("successor state directory must be a real directory")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink() or path.parent.resolve() != path.parent:
        raise SuccessorError("successor state directory is unsafe")
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


def _transition_path(common_dir: Path, predecessor: str, event_id: str) -> Path:
    key = hashlib.sha256(f"{predecessor}\0{event_id}".encode()).hexdigest()
    return common_dir / "seam-orchestration" / "successors" / f"{key}.json"


def _artifact(path: Path, label: str) -> dict[str, str]:
    encoded = _read_bytes(path)
    return {"label": label, "path": str(path), "sha256": hashlib.sha256(encoded).hexdigest()}


def _validate_artifacts(value: object, *, minimum: int) -> list[dict[str, str]]:
    if not isinstance(value, list) or not minimum <= len(value) <= 32:
        raise SuccessorError("successor artifact inventory is invalid")
    labels: set[str] = set()
    for artifact in value:
        if not isinstance(artifact, dict) or set(artifact) != {"label", "path", "sha256"}:
            raise SuccessorError("successor artifact binding is invalid")
        label, raw_path, digest = artifact.get("label"), artifact.get("path"), artifact.get("sha256")
        if not isinstance(label, str) or not label or label in labels:
            raise SuccessorError("successor artifact label is invalid")
        labels.add(label)
        if not isinstance(raw_path, str) or not Path(raw_path).is_absolute() or ".." in Path(raw_path).parts:
            raise SuccessorError("successor artifact path is unsafe")
        if not isinstance(digest, str) or not SHA256.fullmatch(digest):
            raise SuccessorError("successor artifact hash is invalid")
        if hashlib.sha256(_read_bytes(Path(raw_path))).hexdigest() != digest:
            raise SuccessorError(f"successor artifact changed after transition: {label}")
    return value


def _validate_external_artifact(value: object, external_root: Path) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise SuccessorError("external recovery artifact binding is invalid")
    raw_path, digest = value.get("path"), value.get("sha256")
    if (
        not isinstance(raw_path, str)
        or not Path(raw_path).is_absolute()
        or ".." in Path(raw_path).parts
        or not isinstance(digest, str)
        or not SHA256.fullmatch(digest)
    ):
        raise SuccessorError("external recovery artifact binding is unsafe")
    path = Path(raw_path)
    try:
        path.relative_to(external_root)
    except ValueError as exc:
        raise SuccessorError("external recovery artifact escapes its root") from exc
    if hashlib.sha256(_read_bytes(path)).hexdigest() != digest:
        raise SuccessorError("external recovery artifact changed")
    return value


def _validate_external_recovery(value: object) -> dict[str, Any]:
    fields = set(value) if isinstance(value, dict) else set()
    if (
        not isinstance(value, dict)
        or not EXTERNAL_RECOVERY_REQUIRED_FIELDS.issubset(fields)
        or fields - EXTERNAL_RECOVERY_REQUIRED_FIELDS
        - EXTERNAL_RECOVERY_OPTIONAL_FIELDS
        or value.get("schema") != "seam-external-recovery-binding/v1"
        or value.get("status") != "INHERITED_UNQUALIFIED"
        or value.get("result_status") not in {"RETAINED", "NOT_RETAINED"}
        or not isinstance(value.get("missing_checkpoint"), bool)
    ):
        raise SuccessorError("external recovery binding does not match its contract")
    if ("checkpoint" in value) == value["missing_checkpoint"]:
        raise SuccessorError("external recovery checkpoint binding is inconsistent")
    if ("result" in value) != (value["result_status"] == "RETAINED"):
        raise SuccessorError("external recovery result binding is inconsistent")
    external_root_raw = value.get("external_root")
    if not isinstance(external_root_raw, str) or not Path(external_root_raw).is_absolute():
        raise SuccessorError("external recovery root is invalid")
    external_root = Path(external_root_raw)
    if external_root.resolve(strict=True) != external_root or not external_root.is_dir():
        raise SuccessorError("external recovery root is unsafe")
    _safe_id(value.get("session_id"), "external session")
    _safe_id(value.get("event_id"), "external event")
    if (
        isinstance(value.get("compaction_count"), bool)
        or not isinstance(value.get("compaction_count"), int)
        or value["compaction_count"] < 1
    ):
        raise SuccessorError("external recovery compaction count is invalid")
    _validate_external_artifact(value.get("evidence_manifest"), external_root)
    manifest, _ = _read_json(Path(value["evidence_manifest"]["path"]))
    files_sha256 = manifest.get("files_sha256")
    if files_sha256 is not None:
        if not isinstance(files_sha256, dict):
            raise SuccessorError("external recovery evidence manifest is invalid")
        members: dict[str, object] = files_sha256
        relative_members = False
    else:
        members = manifest
        relative_members = True
    if not 1 <= len(members) <= 512:
        raise SuccessorError("external recovery evidence manifest is invalid")
    observed_members: set[Path] = set()
    verified_members: dict[Path, bytes | None] = {}
    for raw_path, member in members.items():
        digest = member
        expected_size: int | None = None
        if relative_members:
            if not isinstance(member, dict) or set(member) != {"sha256", "size_bytes"}:
                raise SuccessorError("external recovery manifest member is invalid")
            digest = member.get("sha256")
            expected_size = member.get("size_bytes")
        if (
            not isinstance(raw_path, str)
            or ".." in Path(raw_path).parts
            or not isinstance(digest, str)
            or not SHA256.fullmatch(digest)
            or (
                expected_size is not None
                and (
                    isinstance(expected_size, bool)
                    or not isinstance(expected_size, int)
                    or expected_size < 0
                )
            )
        ):
            raise SuccessorError("external recovery manifest member is invalid")
        member_path = external_root / raw_path if relative_members else Path(raw_path)
        if relative_members and Path(raw_path).is_absolute():
            raise SuccessorError("external recovery manifest member is invalid")
        if not relative_members and not member_path.is_absolute():
            raise SuccessorError("external recovery manifest member is invalid")
        try:
            member_path.relative_to(external_root)
        except ValueError as exc:
            raise SuccessorError("external recovery manifest member escapes its root") from exc
        (
            observed_digest,
            observed_size,
            encoded,
            first_non_whitespace,
            significant_prefix,
        ) = _hash_manifest_member(member_path)
        if (
            observed_digest != digest
            or (expected_size is not None and observed_size != expected_size)
        ):
            raise SuccessorError("external recovery manifest member changed")
        if encoded is None and first_non_whitespace == ord("{"):
            raise SuccessorError(
                "external recovery manifest contains an oversized JSON candidate"
            )
        if b"\x00" in significant_prefix or any(
            significant_prefix.startswith(bom) for bom in UNSUPPORTED_JSON_BOMS
        ):
            raise SuccessorError(
                "external recovery manifest contains unsupported JSON encoding"
            )
        if member_path in observed_members:
            raise SuccessorError("external recovery manifest member is duplicated")
        observed_members.add(member_path)
        verified_members[member_path] = encoded

    artifact_fields = ["guardian_state", "recovery_event", "handoff"]
    if "checkpoint" in value:
        artifact_fields.append("checkpoint")
    if "result" in value:
        artifact_fields.append("result")
    for field in artifact_fields:
        _validate_external_artifact(value.get(field), external_root)

    guardian_path = Path(value["guardian_state"]["path"])
    recovery_path = Path(value["recovery_event"]["path"])
    handoff_path = Path(value["handoff"]["path"])
    checkpoint_path = (
        Path(value["checkpoint"]["path"]) if "checkpoint" in value else None
    )
    result_path = Path(value["result"]["path"]) if "result" in value else None
    required_members = {guardian_path, recovery_path, handoff_path}
    if checkpoint_path is not None:
        required_members.add(checkpoint_path)
    if result_path is not None:
        required_members.add(result_path)
    if not required_members.issubset(observed_members):
        raise SuccessorError("external recovery manifest omits a required dependency")

    context_root = guardian_path.parent
    try:
        recovery = context_guardian._load_recovery(
            recovery_path, context_root, value["session_id"]
        )
        guardian = context_guardian._load_state(
            context_root, value["session_id"], handoff_root=handoff_path.parent
        )
        checkpoint = (
            context_guardian._load_checkpoint(context_root, value["session_id"])
            if checkpoint_path is not None
            else None
        )
    except context_guardian.ContextGuardianError as exc:
        raise SuccessorError("external recovery dependency is invalid") from exc
    if guardian_path != context_root / f"{value['session_id']}.json":
        raise SuccessorError("external recovery guardian path is invalid")
    if _read_bytes(handoff_path) != context_guardian._render_recovery_handoff(recovery):
        raise SuccessorError("external recovery handoff does not match its event")
    if (
        recovery["event_id"] != value["event_id"]
        or recovery["missing_checkpoint"] != value["missing_checkpoint"]
        or recovery["compactions_completed"] != value["compaction_count"]
        or guardian["compactions_completed"] != value["compaction_count"]
        or guardian["last_action"] != "HANDOFF_REQUIRED"
        or guardian["recovery_path"] != str(recovery_path)
        or guardian["handoff_path"] != str(handoff_path)
        or guardian["checkpoint_path"]
        != (None if checkpoint_path is None else str(checkpoint_path))
        or (
            checkpoint is not None
            and (
                checkpoint_path
                != context_root / "checkpoints" / f"{value['session_id']}.json"
                or checkpoint["compactions_completed"]
                != recovery["previous_compactions_completed"]
                or checkpoint["usage_percent"]
                != recovery["previous_highest_usage_percent"]
            )
        )
    ):
        raise SuccessorError("external recovery dependencies are inconsistent")

    excluded_candidates = {guardian_path, recovery_path, handoff_path}
    if checkpoint_path is not None:
        excluded_candidates.add(checkpoint_path)
    candidates: list[tuple[Path, dict[str, Any] | None]] = []
    for member_path, encoded in verified_members.items():
        if member_path in excluded_candidates:
            continue
        parsed: dict[str, Any] | None = None
        if encoded is not None:
            try:
                decoded = json.loads(encoded.decode("utf-8"))
                if isinstance(decoded, dict):
                    parsed = decoded
            except (UnicodeDecodeError, json.JSONDecodeError):
                pass
        if (
            member_path.name == "unexpected-compaction-result.json"
            or (
                parsed is not None
                and (
                    parsed.get("recovery_path") == str(recovery_path)
                    or (
                        "action" in parsed
                        and parsed.get("handoff_path") == str(handoff_path)
                    )
                )
            )
        ):
            candidates.append((member_path, parsed))
    if len(candidates) > 1:
        raise SuccessorError("external recovery result inventory is ambiguous")
    if value["result_status"] == "NOT_RETAINED":
        if candidates:
            raise SuccessorError("external recovery result status contradicts retained evidence")
    else:
        if len(candidates) != 1 or candidates[0][0] != result_path:
            raise SuccessorError("external recovery retained result is missing or unbound")
        result = candidates[0][1]
        expected_result_fields = {
            "action", "compactions_completed", "handoff_path", "recovery_path",
            "missing_checkpoint", "previous_last_action",
            "previous_highest_usage_percent",
        }
        if (
            not isinstance(result, dict)
            or set(result) != expected_result_fields
            or result.get("action") != "HANDOFF_REQUIRED"
            or isinstance(result.get("compactions_completed"), bool)
            or not isinstance(result.get("compactions_completed"), int)
            or not isinstance(result.get("missing_checkpoint"), bool)
            or isinstance(result.get("previous_highest_usage_percent"), bool)
            or not isinstance(result.get("previous_highest_usage_percent"), (int, float))
            or result["compactions_completed"] != recovery["compactions_completed"]
            or result["missing_checkpoint"] != recovery["missing_checkpoint"]
            or result["recovery_path"] != str(recovery_path)
            or result["handoff_path"] != str(handoff_path)
            or result["previous_last_action"] != recovery["previous_last_action"]
            or result["previous_highest_usage_percent"]
            != recovery["previous_highest_usage_percent"]
        ):
            raise SuccessorError("external recovery result does not match its event")
    binding_path = value.get("binding_path")
    binding_sha = value.get("binding_sha256")
    if (
        not isinstance(binding_path, str)
        or not Path(binding_path).is_absolute()
        or not isinstance(binding_sha, str)
        or not SHA256.fullmatch(binding_sha)
    ):
        raise SuccessorError("external recovery source binding is invalid")
    source, source_bytes = _read_json(Path(binding_path))
    source_fields = set(value) - {"binding_path", "binding_sha256"}
    if source != {key: value[key] for key in source_fields}:
        raise SuccessorError("external recovery source changed")
    if hashlib.sha256(source_bytes).hexdigest() != binding_sha:
        raise SuccessorError("external recovery source hash changed")
    return value


def _load_external_recovery(path: Path) -> dict[str, Any]:
    source, encoded = _read_json(path)
    fields = set(source)
    if (
        not EXTERNAL_SOURCE_REQUIRED_FIELDS.issubset(fields)
        or fields - EXTERNAL_SOURCE_REQUIRED_FIELDS - EXTERNAL_RECOVERY_OPTIONAL_FIELDS
    ):
        raise SuccessorError("external recovery source does not match its contract")
    value = {
        **source,
        "binding_path": str(path),
        "binding_sha256": hashlib.sha256(encoded).hexdigest(),
    }
    return _validate_external_recovery(value)


def validate_transition(value: object, path: Path) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != FIELDS or value.get("schema") != SCHEMA:
        raise SuccessorError("successor transition does not match its contract")
    predecessor = _safe_id(value.get("predecessor_session_id"), "predecessor session")
    successor = _safe_id(value.get("successor_session_id"), "successor session")
    event_id = _safe_id(value.get("recovery_event_id"), "recovery event")
    if predecessor == successor:
        raise SuccessorError("successor session must differ from predecessor")
    for field in ("repository_common_dir", "worktree_root"):
        raw = value.get(field)
        if not isinstance(raw, str) or not Path(raw).is_absolute() or ".." in Path(raw).parts:
            raise SuccessorError(f"successor {field} is unsafe")
    if path != _transition_path(Path(value["repository_common_dir"]), predecessor, event_id):
        raise SuccessorError("successor transition path is invalid")
    if not isinstance(value.get("branch"), str) or not value["branch"] or len(value["branch"]) > 300:
        raise SuccessorError("successor branch is invalid")
    for field in ("original_base_sha", "activation_sha"):
        if not isinstance(value.get(field), str) or not COMMIT.fullmatch(value[field]):
            raise SuccessorError(f"successor {field} is invalid")
    _safe_id(value.get("request_id"), "request id")
    _validate_artifacts(value.get("artifacts"), minimum=7)
    _validate_artifacts(value.get("repair_artifacts"), minimum=0)
    external = value.get("external_recoveries")
    if not isinstance(external, list) or len(external) > 16:
        raise SuccessorError("successor external recovery inventory is invalid")
    identities: set[tuple[str, str, str]] = set()
    for recovery in external:
        validated = _validate_external_recovery(recovery)
        identity = (
            validated["external_root"], validated["session_id"], validated["event_id"]
        )
        if identity in identities:
            raise SuccessorError("duplicate external recovery binding")
        identities.add(identity)
    hashes = value.get("queue_record_sha256s")
    if not isinstance(hashes, list) or not hashes or hashes != sorted(set(hashes)) or any(not isinstance(item, str) or not item or len(item) > 3000 for item in hashes):
        raise SuccessorError("successor queue inventory is invalid")
    roots = value.get("queue_roots")
    if (
        not isinstance(roots, list)
        or not roots
        or roots != sorted(set(roots))
        or any(
            not isinstance(root, str)
            or not Path(root).is_absolute()
            or ".." in Path(root).parts
            for root in roots
        )
    ):
        raise SuccessorError("successor queue root inventory is invalid")
    try:
        observed = datetime.fromisoformat(str(value.get("created_at")).replace("Z", "+00:00"))
    except ValueError as exc:
        raise SuccessorError("successor timestamp is invalid") from exc
    if observed.tzinfo is None:
        raise SuccessorError("successor timestamp lacks timezone")
    return value


def _load_transition(path: Path) -> tuple[dict[str, Any], bytes]:
    value, encoded = _read_json(path)
    return validate_transition(value, path), encoded


def _transition_for_registration(
    common_dir: Path, registration: dict[str, Any]
) -> tuple[dict[str, Any], str] | None:
    digest = registration.get("successor_transition_sha256")
    if digest is None:
        return None
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise SuccessorError("successor ancestor registration hash is invalid")
    transition_root = common_dir / "seam-orchestration" / "successors"
    matches: list[tuple[dict[str, Any], str]] = []
    for path in sorted(transition_root.glob("*.json")) if transition_root.exists() else []:
        transition, encoded = _load_transition(path)
        observed = hashlib.sha256(encoded).hexdigest()
        if observed == digest:
            matches.append((transition, observed))
    if len(matches) != 1:
        raise SuccessorError("successor ancestor registration lacks one immutable transition")
    return matches[0]


def _artifact_with_label(
    transition: dict[str, Any], label: str
) -> dict[str, str]:
    matches = [item for item in transition["artifacts"] if item["label"] == label]
    if len(matches) != 1:
        raise SuccessorError(f"successor lineage lacks one {label} artifact")
    return matches[0]


def _committed_tail_paths(
    repo_root: Path, request_head: str, activation_sha: str
) -> list[str]:
    for label, commit in (("request head", request_head), ("activation", activation_sha)):
        if _git(repo_root, "rev-parse", "--verify", f"{commit}^{{commit}}") != commit:
            raise SuccessorError(f"successor {label} does not resolve exactly")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", request_head, activation_sha],
        cwd=repo_root,
        check=False,
    )
    if ancestor.returncode:
        raise SuccessorError("successor activation does not descend from its request head")
    history = subprocess.run(
        [
            "git", "rev-list", "--reverse", "--parents",
            f"{request_head}..{activation_sha}",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if history.returncode:
        raise SuccessorError("successor cannot inspect its committed request tail")
    touched: set[str] = set()
    for line in history.stdout.splitlines():
        commit_and_parents = line.split()
        if len(commit_and_parents) != 2:
            raise SuccessorError("successor request has a merge committed tail")
        commit, parent = commit_and_parents
        result = subprocess.run(
            [
                "git", "diff", "--no-renames", "--name-only", "-z",
                parent, commit,
            ],
            cwd=repo_root,
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise SuccessorError("successor cannot inspect its committed request tail")
        touched.update(
            item.decode("utf-8", errors="replace")
            for item in result.stdout.split(b"\x00")
            if item
        )
    return sorted(touched)


def _validate_request_activation(
    repo_root: Path,
    request: dict[str, Any],
    *,
    original_base_sha: str,
    activation_sha: str,
    branch: str,
) -> None:
    request_repo = request["repo"]
    if (
        request_repo["root"] != str(repo_root)
        or request_repo["worktree"] != str(repo_root)
        or request_repo["branch"] != branch
        or request_repo["base_sha"] != original_base_sha
        or request_repo["changed_paths_truncated"] is not False
        or (
            request["change_class"] == "runtime"
            and request["tdd_evidence"]["status"] != "TDD_PROVEN"
        )
    ):
        raise SuccessorError("successor activation lacks complete predecessor evidence")
    tail = _committed_tail_paths(repo_root, request_repo["head"], activation_sha)
    if runtime_paths(tail):
        raise SuccessorError("successor request has a runtime committed tail")


def _validate_request_tdd_prefix(
    request: dict[str, Any], predecessor_state: dict[str, Any]
) -> None:
    request_cycles = request["tdd_evidence"].get("cycles")
    if request_cycles is None:
        if request["change_class"] == "runtime":
            raise SuccessorError(
                "successor predecessor request TDD evidence is missing complete cycles"
            )
        return
    current_cycles = predecessor_state["tdd_cycles"]
    if (
        len(current_cycles) < len(request_cycles)
        or current_cycles[: len(request_cycles)] != request_cycles
    ):
        raise SuccessorError(
            "successor predecessor request TDD evidence is not an immutable state prefix"
        )


def _lineage_obligations(
    repo_root: Path, transition: dict[str, Any]
) -> tuple[set[str], set[str]]:
    common_dir = _common_dir(repo_root)
    state_root = repo_root / ".seam" / "orchestration" / "sessions"
    request_ids: set[str] = set()
    session_ids: set[str] = set()
    seen_digests: set[str] = set()
    current = transition
    for _ in range(32):
        current_path = _transition_path(
            common_dir,
            current["predecessor_session_id"],
            current["recovery_event_id"],
        )
        _, encoded = _load_transition(current_path)
        digest = hashlib.sha256(encoded).hexdigest()
        if digest in seen_digests:
            raise SuccessorError("successor lineage contains a transition cycle")
        seen_digests.add(digest)
        predecessor_id = current["predecessor_session_id"]
        successor_id = current["successor_session_id"]
        if predecessor_id == successor_id:
            raise SuccessorError("successor lineage contains a session cycle")
        session_ids.update({predecessor_id, successor_id})
        if (
            current["repository_common_dir"] != str(common_dir)
            or current["worktree_root"] != str(repo_root)
            or current["branch"] != transition["branch"]
            or current["original_base_sha"] != transition["original_base_sha"]
        ):
            raise SuccessorError("successor lineage repository binding drifted")
        request_artifact = _artifact_with_label(current, "predecessor_request")
        request_path = Path(request_artifact["path"])
        request, _ = _read_json(request_path)
        request = closeout_queue.validate_request(
            request, state_root=request_path.parents[1]
        )
        if (
            request["request_id"] != current["request_id"]
            or request["session_id"] != predecessor_id
        ):
            raise SuccessorError("successor lineage request identity drifted")
        if request["request_id"] in request_ids:
            raise SuccessorError("successor lineage repeats a request")
        request_ids.add(request["request_id"])
        _validate_request_activation(
            repo_root,
            request,
            original_base_sha=current["original_base_sha"],
            activation_sha=current["activation_sha"],
            branch=current["branch"],
        )
        receipt_artifact = _artifact_with_label(current, "predecessor_receipt")
        receipt_path = Path(receipt_artifact["path"])
        receipt, _ = _read_json(receipt_path)
        receipt = closeout_queue.validate_receipt(
            request, receipt, state_root=request_path.parents[1]
        )
        if receipt["status"] == "QUALIFIED":
            raise SuccessorError("successor lineage ancestor receipt is already qualified")
        predecessor_state, _ = _read_json(state_root / f"{predecessor_id}.json")
        successor_state, _ = _read_json(state_root / f"{successor_id}.json")
        try:
            validate_session_state(predecessor_state, expected_session_id=predecessor_id)
            validate_session_state(successor_state, expected_session_id=successor_id)
        except SessionEndError as exc:
            raise SuccessorError(str(exc)) from exc
        _validate_request_tdd_prefix(request, predecessor_state)
        inherited = predecessor_state["tdd_cycles"]
        if (
            predecessor_state["base_sha"] != current["original_base_sha"]
            or successor_state["base_sha"] != current["original_base_sha"]
            or successor_state["tdd_cycles"][: len(inherited)] != inherited
        ):
            raise SuccessorError("successor lineage lost inherited base or TDD evidence")
        registration_artifact = _artifact_with_label(
            current, "predecessor_registration"
        )
        registration_path = Path(registration_artifact["path"])
        registration = assurance._validate_registration(
            assurance._load(registration_path), common_dir, registration_path
        )
        if (
            registration["session_id"] != predecessor_id
            or registration["worktree_root"] != str(repo_root)
            or registration["base_sha"] != current["original_base_sha"]
        ):
            raise SuccessorError("successor lineage registration drifted")
        ancestor = _transition_for_registration(common_dir, registration)
        if ancestor is None:
            return request_ids, session_ids
        ancestor_transition, _ = ancestor
        if ancestor_transition["successor_session_id"] != predecessor_id:
            raise SuccessorError("successor lineage predecessor link is invalid")
        current = ancestor_transition
    raise SuccessorError("successor lineage exceeds the bounded transition depth")


def validate_registration_binding(
    repo_root: Path,
    registration: dict[str, Any],
    *,
    require_complete_tdd: bool = True,
) -> dict[str, Any]:
    digest = registration.get("successor_transition_sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise SuccessorError("successor registration transition hash is invalid")
    common_dir = _common_dir(repo_root)
    transition_root = common_dir / "seam-orchestration" / "successors"
    if transition_root.is_symlink() or (
        transition_root.exists()
        and (not transition_root.is_dir() or transition_root.resolve() != transition_root)
    ):
        raise SuccessorError("successor transition directory is unsafe")
    matched = _transition_for_registration(common_dir, registration)
    if matched is None:
        raise SuccessorError("successor registration lacks one immutable transition")
    transition, _ = matched
    if (
        transition["successor_session_id"] != registration.get("session_id")
        or transition["worktree_root"] != str(repo_root)
        or transition["repository_common_dir"] != str(common_dir)
        or transition["original_base_sha"] != registration.get("base_sha")
    ):
        raise SuccessorError("successor registration does not match its transition")
    descendant = subprocess.run(
        ["git", "merge-base", "--is-ancestor", transition["activation_sha"], "HEAD"],
        cwd=repo_root,
        check=False,
    )
    if descendant.returncode:
        raise SuccessorError("successor HEAD does not descend from its activation")
    if (_git(repo_root, "branch", "--show-current") or "detached") != transition["branch"]:
        raise SuccessorError("successor branch changed after transition")
    state_root = repo_root / ".seam" / "orchestration" / "sessions"
    predecessor, _ = _read_json(state_root / f"{transition['predecessor_session_id']}.json")
    successor_state, _ = _read_json(state_root / f"{transition['successor_session_id']}.json")
    try:
        validate_session_state(predecessor, expected_session_id=transition["predecessor_session_id"])
        validate_session_state(successor_state, expected_session_id=transition["successor_session_id"])
    except SessionEndError as exc:
        raise SuccessorError(str(exc)) from exc
    inherited = predecessor["tdd_cycles"]
    if successor_state["base_sha"] != transition["original_base_sha"] or successor_state["tdd_cycles"][: len(inherited)] != inherited:
        raise SuccessorError("successor session lost inherited base or TDD evidence")
    request_ids, lineage_session_ids = _lineage_obligations(repo_root, transition)
    if require_complete_tdd:
        changed_paths, truncated = _changed_paths(repo_root, transition["original_base_sha"])
        tdd = assess_tdd(changed_paths, successor_state)
        if truncated or (tdd["runtime_paths"] and tdd["status"] != "TDD_PROVEN"):
            raise SuccessorError("successor runtime changes lack complete TDD coverage")
    try:
        closeout_queue.validate_successor_inventory(
            repo_root,
            transition,
            obligation_request_ids=request_ids,
            lineage_session_ids=lineage_session_ids,
        )
    except closeout_queue.CloseoutQueueError as exc:
        raise SuccessorError(str(exc)) from exc
    return transition


def _prevalidate_successor_state(
    state_root: Path,
    transition_path: Path,
    successor_id: str,
    original_base: str,
    predecessor_state: dict[str, Any],
    *,
    objective: str,
    plan: list[str],
    constraints: list[str],
    affected_tests: list[str],
) -> tuple[dict[str, Any], bytes, Path, bool]:
    successor_state = {
        "schema": "seam-agent-session-state/v1",
        "session_id": successor_id,
        "base_sha": original_base,
        "objective": objective,
        "plan": plan,
        "constraints": constraints,
        "affected_tests": affected_tests,
        "tdd_cycles": predecessor_state["tdd_cycles"],
    }
    try:
        validate_session_state(successor_state, expected_session_id=successor_id)
    except SessionEndError as exc:
        raise SuccessorError(str(exc)) from exc
    successor_state_path = state_root / f"{successor_id}.json"
    state_bytes = _canonical(successor_state)
    if not os.path.lexists(successor_state_path):
        return successor_state, state_bytes, successor_state_path, False
    if not transition_path.exists():
        raise SuccessorError(
            "conflicting successor session state lacks immutable transition intent"
        )
    existing_state, existing_bytes = _read_json(successor_state_path)
    try:
        validate_session_state(existing_state, expected_session_id=successor_id)
    except SessionEndError as exc:
        raise SuccessorError(str(exc)) from exc
    stable_fields = set(successor_state) - {"tdd_cycles"}
    if (
        any(existing_state[field] != successor_state[field] for field in stable_fields)
        or existing_state["tdd_cycles"][: len(predecessor_state["tdd_cycles"])]
        != predecessor_state["tdd_cycles"]
    ):
        raise SuccessorError("conflicting successor session state exists")
    return existing_state, existing_bytes, successor_state_path, True


def _prevalidate_assurance_activation(
    repo_root: Path,
    common_dir: Path,
    *,
    predecessor_id: str,
    successor_id: str,
    original_base: str,
    transition_digest: str,
    successor_state_exists: bool,
) -> None:
    registration_path = assurance._registration_path(common_dir, successor_id)
    expected_registration = {
        "schema": assurance.SCHEMA,
        "kind": "registration",
        "repository": assurance.REPOSITORY,
        "repository_common_dir": str(common_dir),
        "session_id": successor_id,
        "worktree_root": str(repo_root),
        "base_sha": original_base,
        "successor_transition_sha256": transition_digest,
    }
    registration_exists = os.path.lexists(registration_path)
    if registration_exists:
        existing = assurance._validate_registration(
            assurance._load(registration_path), common_dir, registration_path
        )
        if assurance._canonical(existing) != assurance._canonical(expected_registration):
            raise SuccessorError("conflicting immutable assurance registration exists")
        if not successor_state_exists:
            raise SuccessorError(
                "successor assurance registration lacks its existing session state"
            )
    active_path = assurance._active_path(common_dir, repo_root)
    if not os.path.lexists(active_path):
        return
    active = assurance._validate_active(
        assurance._load(active_path), common_dir, repo_root
    )
    if active["session_id"] not in {predecessor_id, successor_id}:
        raise SuccessorError("conflicting active assurance binding exists")
    if active["session_id"] == successor_id and (
        not registration_exists or not successor_state_exists
    ):
        raise SuccessorError("active successor assurance binding is incomplete")


def create(
    repo_root: Path,
    state_root: Path,
    successor_session_id: str,
    *,
    predecessor_session_id: str,
    request_id: str,
    recovery_event_id: str,
    repair_paths: list[Path],
    external_recovery_paths: list[Path],
    objective: str,
    plan: list[str],
    constraints: list[str],
    affected_tests: list[str],
) -> dict[str, Any]:
    repo_root = repo_root.resolve(strict=True)
    state_root = state_root.resolve()
    expected_state_root = repo_root / ".seam" / "orchestration" / "sessions"
    if state_root != expected_state_root:
        raise SuccessorError("successor session state must be derived from repo root")
    predecessor = _safe_id(predecessor_session_id, "predecessor session")
    successor_id = _safe_id(successor_session_id, "successor session")
    request_id = _safe_id(request_id, "request id")
    event_id = _safe_id(recovery_event_id, "recovery event")
    if predecessor == successor_id:
        raise SuccessorError("successor session must differ from predecessor")
    common_dir = _common_dir(repo_root)
    context_root = repo_root / ".seam" / "orchestration" / "context"
    queue_root = repo_root / ".seam" / "orchestration" / "session-end"
    predecessor_state_path = state_root / f"{predecessor}.json"
    predecessor_state, _ = _read_json(predecessor_state_path)
    try:
        validate_session_state(predecessor_state, expected_session_id=predecessor)
    except SessionEndError as exc:
        raise SuccessorError(str(exc)) from exc
    original_base = predecessor_state["base_sha"]
    path = _transition_path(common_dir, predecessor, event_id)
    (
        successor_state,
        state_bytes,
        successor_state_path,
        successor_state_exists,
    ) = _prevalidate_successor_state(
        state_root,
        path,
        successor_id,
        original_base,
        predecessor_state,
        objective=objective,
        plan=plan,
        constraints=constraints,
        affected_tests=affected_tests,
    )
    registration_path = assurance._registration_path(common_dir, predecessor)
    registration = assurance._validate_registration(assurance._load(registration_path), common_dir, registration_path)
    if registration["worktree_root"] != str(repo_root) or registration["base_sha"] != original_base:
        raise SuccessorError("predecessor registration does not match original state")
    predecessor_transition: dict[str, Any] | None = None
    obligation_request_ids: set[str] = set()
    lineage_session_ids: set[str] = {predecessor}
    if "successor_transition_sha256" in registration:
        predecessor_transition = validate_registration_binding(
            repo_root, registration, require_complete_tdd=False
        )
        obligation_request_ids, lineage_session_ids = _lineage_obligations(
            repo_root, predecessor_transition
        )
    recovery_path = context_root / "recoveries" / predecessor / f"{event_id}.json"
    context_guardian._load_recovery(recovery_path, context_root, predecessor)
    context_state_path = context_root / f"{predecessor}.json"
    context_state, _ = _read_json(context_state_path)
    if context_state.get("recovery_path") != str(recovery_path):
        raise SuccessorError("predecessor context state does not bind recovery event")
    handoff_path = repo_root / ".context-handoffs" / f"context-handoff-{predecessor}.md"
    if context_state.get("handoff_path") != str(handoff_path):
        raise SuccessorError("predecessor context state does not bind successor handoff")
    request_path = queue_root / "requests" / f"{request_id}.json"
    request, _ = _read_json(request_path)
    request = closeout_queue.validate_request(request, state_root=queue_root)
    if request["session_id"] != predecessor or request["repo"]["root"] != str(repo_root):
        raise SuccessorError("predecessor request identity does not match transition")
    _validate_request_tdd_prefix(request, predecessor_state)
    stored = closeout_queue._stored_receipts(request, state_root=queue_root)
    canonical_receipt = closeout_queue._expected_receipt_path(queue_root, request_id)
    selected = [(path, receipt) for path, receipt in stored if path == canonical_receipt]
    if len(selected) != 1 or selected[0][1]["status"] == "QUALIFIED":
        raise SuccessorError("predecessor requires one canonical non-qualified receipt")
    receipt_path = selected[0][0]
    activation = _git(repo_root, "rev-parse", "HEAD")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", original_base, activation],
        cwd=repo_root,
        check=False,
    )
    if ancestor.returncode:
        raise SuccessorError("successor candidate does not descend from original base")
    branch = _git(repo_root, "branch", "--show-current") or "detached"
    _validate_request_activation(
        repo_root,
        request,
        original_base_sha=original_base,
        activation_sha=activation,
        branch=branch,
    )
    if request_id in obligation_request_ids:
        raise SuccessorError("successor lineage repeats its current request")
    obligation_request_ids.add(request_id)
    lineage_session_ids.add(predecessor)
    artifacts = [
        _artifact(registration_path, "predecessor_registration"),
        _artifact(predecessor_state_path, "predecessor_session_state"),
        _artifact(context_state_path, "predecessor_context_state"),
        _artifact(recovery_path, "predecessor_recovery"),
        _artifact(handoff_path, "predecessor_handoff"),
        _artifact(request_path, "predecessor_request"),
        _artifact(receipt_path, "predecessor_receipt"),
    ]
    checkpoint_path = context_root / "checkpoints" / f"{predecessor}.json"
    if checkpoint_path.exists():
        context_guardian._load_checkpoint(context_root, predecessor)
        artifacts.append(_artifact(checkpoint_path, "predecessor_checkpoint"))
    admission = closeout_queue.admit_successor(
        repo_root,
        obligation_request_ids=obligation_request_ids,
        lineage_session_ids=lineage_session_ids,
        branch=branch,
        original_base_sha=original_base,
        repair_paths=repair_paths,
    )
    repair_artifacts = [
        _artifact(path.resolve(strict=True), f"repair:{index}")
        for index, path in enumerate(repair_paths)
    ]
    external_recoveries = sorted(
        (_load_external_recovery(path) for path in external_recovery_paths),
        key=lambda value: (
            value["external_root"], value["session_id"], value["event_id"]
        ),
    )
    stable = {
        "schema": SCHEMA,
        "predecessor_session_id": predecessor,
        "successor_session_id": successor_id,
        "recovery_event_id": event_id,
        "repository_common_dir": str(common_dir),
        "worktree_root": str(repo_root),
        "branch": branch,
        "original_base_sha": original_base,
        "activation_sha": activation,
        "request_id": request_id,
        "artifacts": artifacts,
        "repair_artifacts": repair_artifacts,
        "external_recoveries": external_recoveries,
        "queue_roots": admission["observed_roots"],
        "queue_record_sha256s": admission["record_sha256s"],
    }
    transition_exists = path.exists()
    if transition_exists:
        transition, encoded = _load_transition(path)
        if {key: value for key, value in transition.items() if key != "created_at"} != stable:
            raise SuccessorError("competing or conflicting successor transition exists")
    else:
        transition = {**stable, "created_at": datetime.now(timezone.utc).isoformat()}
        encoded = _canonical(transition)
    digest = hashlib.sha256(encoded).hexdigest()
    _prevalidate_assurance_activation(
        repo_root,
        common_dir,
        predecessor_id=predecessor,
        successor_id=successor_id,
        original_base=original_base,
        transition_digest=digest,
        successor_state_exists=successor_state_exists,
    )
    if not transition_exists:
        if not _publish_once(path, encoded):
            existing, existing_bytes = _load_transition(path)
            if {
                key: value for key, value in existing.items() if key != "created_at"
            } != stable:
                raise SuccessorError("competing or conflicting successor transition exists")
            transition = existing
            encoded = existing_bytes
            digest = hashlib.sha256(encoded).hexdigest()
    if not successor_state_exists and not _publish_once(successor_state_path, state_bytes):
        existing_state, existing_bytes = _read_json(successor_state_path)
        if existing_bytes != state_bytes or existing_state != successor_state:
            raise SuccessorError("conflicting successor session state exists")
    assurance.register(
        repo_root,
        successor_id,
        original_base,
        successor_transition_sha256=digest,
    )
    return {
        "status": "SUCCESSOR_ACTIVE",
        "transition_path": str(path),
        "transition_sha256": digest,
        "state_path": str(successor_state_path),
    }
