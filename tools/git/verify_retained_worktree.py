"""Validate one dirty linked worktree against the shared retention ledger.

This helper is deliberately read-only. It does not create, update, remove, or
otherwise reconcile worktrees or cleanup-ledger records.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


LEDGER_SCHEMA = "seam-workspace-cleanup-ledger/v1"


class RetentionValidationError(RuntimeError):
    """The worktree does not have stable, exact retained-ledger coverage."""


@dataclass(frozen=True)
class RetentionObservation:
    common_dir: str
    primary_root: str
    worktree: str
    head: str
    branch: str
    worktree_listing: str
    ledger_path: str
    ledger_bytes: bytes


def _clean_git_environment() -> dict[str, str]:
    env = os.environ.copy()
    for name in tuple(env):
        if name.startswith("GIT_"):
            env.pop(name)
    return env


def _git(cwd: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=_clean_git_environment(),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise RetentionValidationError(f"Git read failed: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        raise RetentionValidationError(f"Git read failed: {detail}")
    return completed.stdout.strip()


def _canonical_directory(path: Path, label: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise RetentionValidationError(f"{label} cannot be resolved: {exc}") from exc
    if not resolved.is_dir():
        raise RetentionValidationError(f"{label} is not a directory: {resolved}")
    return resolved


def _parse_worktrees(raw: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in raw.splitlines():
        if not line:
            if current:
                records.append(current)
                current = {}
            continue
        key, separator, value = line.partition(" ")
        current[key] = value if separator else ""
    if current:
        records.append(current)
    if not records or any("worktree" not in record for record in records):
        raise RetentionValidationError("Git worktree list is missing required records")
    return records


def _absolute_git_path(raw: str, cwd: Path, label: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = cwd / path
    return _canonical_directory(path, label)


def _capture_observation(repo_root: Path, worktree: Path) -> RetentionObservation:
    repo = _canonical_directory(Path(repo_root), "repository root")
    candidate = _canonical_directory(Path(worktree), "retained worktree")

    common_dir = _absolute_git_path(
        _git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"),
        repo,
        "Git common directory",
    )
    listing = _git(repo, "worktree", "list", "--porcelain")
    records = _parse_worktrees(listing)
    primary = _canonical_directory(Path(records[0]["worktree"]), "primary worktree")
    if candidate == primary:
        raise RetentionValidationError("the primary worktree cannot use retained-linked coverage")

    matches = [
        record
        for record in records
        if _canonical_directory(Path(record["worktree"]), "listed worktree") == candidate
    ]
    if len(matches) != 1:
        raise RetentionValidationError("retained worktree is not uniquely registered with Git")
    record = matches[0]
    listed_head = record.get("HEAD", "")
    listed_branch = record.get("branch", "")
    if not listed_head or not listed_branch.startswith("refs/heads/"):
        raise RetentionValidationError("retained worktree must have an attached branch and HEAD")

    candidate_common_dir = _absolute_git_path(
        _git(candidate, "rev-parse", "--path-format=absolute", "--git-common-dir"),
        candidate,
        "retained worktree Git common directory",
    )
    if candidate_common_dir != common_dir:
        raise RetentionValidationError("retained worktree belongs to another Git common directory")

    head = _git(candidate, "rev-parse", "--verify", "HEAD")
    branch = _git(candidate, "symbolic-ref", "--quiet", "--short", "HEAD")
    if head != listed_head or branch != listed_branch.removeprefix("refs/heads/"):
        raise RetentionValidationError("Git worktree identity changed during observation")

    ledger_path = primary / ".seam" / "orchestration" / "cleanup-ledger.json"
    try:
        ledger_bytes = ledger_path.read_bytes()
    except OSError as exc:
        raise RetentionValidationError(f"cleanup ledger cannot be read: {exc}") from exc

    return RetentionObservation(
        common_dir=str(common_dir),
        primary_root=str(primary),
        worktree=str(candidate),
        head=head,
        branch=branch,
        worktree_listing=listing,
        ledger_path=str(ledger_path),
        ledger_bytes=ledger_bytes,
    )


def _parse_review_after(value: object) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise RetentionValidationError("retained record review_after must be an aware timestamp")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise RetentionValidationError("retained record review_after is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise RetentionValidationError("retained record review_after must be timezone-aware")
    return parsed


def _reject_duplicate_json_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    parsed: dict[str, object] = {}
    for key, value in pairs:
        if key in parsed:
            raise RetentionValidationError(f"cleanup ledger has duplicate JSON key: {key}")
        parsed[key] = value
    return parsed


def _validate_ledger(observation: RetentionObservation, now: datetime) -> None:
    try:
        payload = json.loads(
            observation.ledger_bytes,
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RetentionValidationError(f"cleanup ledger JSON is invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise RetentionValidationError("cleanup ledger must be a JSON object")
    if payload.get("schema") != LEDGER_SCHEMA:
        raise RetentionValidationError("cleanup ledger schema does not match")
    if payload.get("primary_root") != observation.primary_root:
        raise RetentionValidationError("cleanup ledger primary_root does not match Git")

    items = payload.get("items")
    if not isinstance(items, list):
        raise RetentionValidationError("cleanup ledger items must be a list")

    paths: set[str] = set()
    matches: list[dict[str, object]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise RetentionValidationError(f"cleanup ledger item {index} must be an object")
        path = item.get("path")
        if not isinstance(path, str) or not path:
            raise RetentionValidationError(f"cleanup ledger item {index} has no path")
        if path in paths:
            raise RetentionValidationError(f"cleanup ledger has duplicate path record: {path}")
        paths.add(path)
        if path == observation.worktree:
            matches.append(item)

    if len(matches) != 1:
        raise RetentionValidationError("cleanup ledger has no exact canonical worktree record")
    item = matches[0]
    if item.get("status") != "retained":
        raise RetentionValidationError("worktree ledger status is not retained")
    if item.get("head") != observation.head:
        raise RetentionValidationError("retained worktree HEAD does not match the ledger")
    if item.get("branch") != observation.branch:
        raise RetentionValidationError("retained worktree branch does not match the ledger")
    for field in ("owner", "reason"):
        value = item.get(field)
        if not isinstance(value, str) or not value.strip():
            raise RetentionValidationError(f"retained record {field} must be nonempty")

    review_after = _parse_review_after(item.get("review_after"))
    if review_after <= now:
        raise RetentionValidationError("retained record review_after has expired")


def verify_retained_worktree(
    repo_root: Path,
    worktree: Path,
    *,
    now: datetime | None = None,
) -> RetentionObservation:
    first = _capture_observation(Path(repo_root), Path(worktree))
    second = _capture_observation(Path(repo_root), Path(worktree))
    if first != second:
        raise RetentionValidationError("Git or cleanup ledger observation changed during validation")
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None or current_time.utcoffset() is None:
        raise RetentionValidationError("validation time must be timezone-aware")
    _validate_ledger(first, current_time)
    return first


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate exact retained-ledger coverage for one linked worktree."
    )
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--worktree", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        verify_retained_worktree(args.repo_root, args.worktree)
    except RetentionValidationError as exc:
        print(f"[SEAM retained-worktree] BLOCKED: {exc}", file=os.sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
