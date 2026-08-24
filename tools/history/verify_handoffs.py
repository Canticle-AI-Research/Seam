"""Verify the canonical tracked handoff registry and supersession chain."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from tools.history.history_lib import (
    HISTORY_PATH,
    REPO_ROOT,
    Entry,
    parse_entries,
    read_history_bytes,
)

HANDOFFS_DIR = REPO_ROOT / "docs" / "handoffs"
INDEX_PATH = HANDOFFS_DIR / "INDEX.md"
SCHEMA = "seam-handoff-registry/v1"
HANDOFF_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
HISTORY_RE = re.compile(r"^HISTORY#(\d+)$")
LINK_RE = re.compile(r"^\[[^\]]+\]\(([^)]+)\)$")
VALID_STATUSES = {"current", "superseded"}
INDEX_HEADER = ["handoff_id", "path", "supersedes", "history", "status"]


@dataclass(frozen=True)
class HandoffRow:
    handoff_id: str
    path: str
    supersedes: str | None
    history: str
    status: str


def _parse_frontmatter(path: Path) -> tuple[dict[str, str], list[str]]:
    errors: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return {}, [f"cannot read {path}: {exc}"]

    if not lines or lines[0].strip() != "---":
        return {}, [f"{path} must start with YAML-style metadata delimited by ---"]

    metadata: dict[str, str] = {}
    closing = None
    for idx, raw in enumerate(lines[1:], start=2):
        if raw.strip() == "---":
            closing = idx
            break
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if ":" not in raw:
            errors.append(f"{path}:{idx} malformed metadata line")
            continue
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip().strip("`\"")
        if not key or not value:
            errors.append(f"{path}:{idx} metadata keys and values must be non-empty")
            continue
        if key in metadata:
            errors.append(f"{path}:{idx} duplicate metadata key {key}")
        metadata[key] = value

    if closing is None:
        errors.append(f"{path} metadata is missing its closing ---")
    return metadata, errors


def _strip_code(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value.startswith("`") and value.endswith("`"):
        return value[1:-1].strip()
    return value


def _split_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return None
    return [cell.strip() for cell in stripped[1:-1].split("|")]


def _parse_index(index_path: Path) -> tuple[dict[str, str], list[HandoffRow], list[str]]:
    metadata, errors = _parse_frontmatter(index_path)
    try:
        lines = index_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return metadata, [], errors

    header_idx = None
    for idx, line in enumerate(lines):
        cells = _split_row(line)
        if cells == INDEX_HEADER:
            header_idx = idx
            break
    if header_idx is None:
        errors.append(f"{index_path} is missing the canonical chain table header")
        return metadata, [], errors
    if header_idx + 1 >= len(lines):
        errors.append(f"{index_path} chain table is missing its separator row")
        return metadata, [], errors

    separator = _split_row(lines[header_idx + 1])
    if separator is None or len(separator) != len(INDEX_HEADER) or not all(
        re.fullmatch(r":?-{3,}:?", cell) for cell in separator
    ):
        errors.append(f"{index_path} has an invalid chain table separator")
        return metadata, [], errors

    rows: list[HandoffRow] = []
    for line_no, line in enumerate(lines[header_idx + 2 :], start=header_idx + 3):
        cells = _split_row(line)
        if cells is None:
            if rows:
                break
            if line.strip():
                errors.append(f"{index_path}:{line_no} expected a handoff table row")
            continue
        if len(cells) != len(INDEX_HEADER):
            errors.append(f"{index_path}:{line_no} expected {len(INDEX_HEADER)} columns")
            continue

        handoff_id = _strip_code(cells[0])
        link = LINK_RE.fullmatch(cells[1])
        if not link:
            errors.append(f"{index_path}:{line_no} path must be a Markdown link")
            path = cells[1]
        else:
            path = link.group(1).strip()
        supersedes_raw = _strip_code(cells[2])
        supersedes = None if supersedes_raw == "none" else supersedes_raw
        rows.append(
            HandoffRow(
                handoff_id=handoff_id,
                path=path,
                supersedes=supersedes,
                history=_strip_code(cells[3]),
                status=_strip_code(cells[4]),
            )
        )

    if not rows:
        errors.append(f"{index_path} chain table must contain at least one handoff")
    return metadata, rows, errors


def _history_entries(history_path: Path) -> tuple[dict[int, Entry], list[str]]:
    try:
        data = read_history_bytes(history_path)
        entries = parse_entries(data) if data else []
    except (OSError, ValueError) as exc:
        return {}, [f"cannot parse history at {history_path}: {exc}"]
    return {entry.id: entry for entry in entries}, []


def _history_time(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _resolve_handoff_path(index_path: Path, raw_path: str, repo_root: Path) -> Path | None:
    candidate = (index_path.parent / raw_path).resolve()
    handoff_root = (repo_root / "docs" / "handoffs").resolve()
    try:
        candidate.relative_to(handoff_root)
    except ValueError:
        return None
    return candidate


def _has_cycle(start: str, parents: dict[str, str | None]) -> bool:
    seen: set[str] = set()
    current: str | None = start
    while current is not None:
        if current in seen:
            return True
        seen.add(current)
        current = parents.get(current)
    return False


def verify_handoffs(
    index_path: Path = INDEX_PATH,
    *,
    repo_root: Path = REPO_ROOT,
    history_path: Path = HISTORY_PATH,
) -> tuple[bool, list[str]]:
    """Return whether the registry is a complete, single-headed linear chain."""
    errors: list[str] = []
    metadata, rows, parse_errors = _parse_index(index_path)
    errors.extend(parse_errors)

    if metadata.get("schema") != SCHEMA:
        errors.append(f"index schema must be {SCHEMA}")
    latest = metadata.get("latest")
    if latest is None:
        errors.append("index metadata must declare latest")

    history_entries, history_errors = _history_entries(history_path)
    errors.extend(history_errors)

    ids: set[str] = set()
    paths: set[Path] = set()
    parents: dict[str, str | None] = {}
    referenced_as_parent: dict[str, list[str]] = {}
    current_ids: list[str] = []

    for row in rows:
        if not HANDOFF_ID_RE.fullmatch(row.handoff_id):
            errors.append(f"invalid handoff id {row.handoff_id!r}")
        if row.handoff_id in ids:
            errors.append(f"duplicate handoff id {row.handoff_id}")
        ids.add(row.handoff_id)
        parents[row.handoff_id] = row.supersedes

        if row.status not in VALID_STATUSES:
            errors.append(f"handoff {row.handoff_id} has invalid status {row.status!r}")
        elif row.status == "current":
            current_ids.append(row.handoff_id)

        match = HISTORY_RE.fullmatch(row.history)
        if not match:
            errors.append(f"handoff {row.handoff_id} has invalid history ref {row.history!r}")
        elif int(match.group(1)) not in history_entries:
            errors.append(f"handoff {row.handoff_id} references missing {row.history}")

        resolved = _resolve_handoff_path(index_path, row.path, repo_root)
        if resolved is None:
            errors.append(f"handoff {row.handoff_id} path escapes docs/handoffs: {row.path}")
            continue
        if resolved == index_path.resolve():
            errors.append(f"handoff {row.handoff_id} cannot point at the registry index")
            continue
        if resolved in paths:
            errors.append(f"duplicate handoff path {row.path}")
        paths.add(resolved)
        if not resolved.is_file():
            errors.append(f"handoff {row.handoff_id} path is missing: {row.path}")
            continue

        doc_meta, doc_errors = _parse_frontmatter(resolved)
        errors.extend(doc_errors)
        expected = {
            "handoff_id": row.handoff_id,
            "supersedes": row.supersedes or "none",
            "handoff_status": row.status,
            "history": row.history,
        }
        for key, expected_value in expected.items():
            if doc_meta.get(key) != expected_value:
                errors.append(
                    f"handoff {row.handoff_id} metadata {key}={doc_meta.get(key)!r}; "
                    f"index expects {expected_value!r}"
                )

    for handoff_id, parent in parents.items():
        if parent is None:
            continue
        if parent not in ids:
            errors.append(f"handoff {handoff_id} supersedes missing target {parent}")
        referenced_as_parent.setdefault(parent, []).append(handoff_id)
        if _has_cycle(handoff_id, parents):
            errors.append(f"handoff chain contains a cycle at {handoff_id}")

    roots = [handoff_id for handoff_id, parent in parents.items() if parent is None]
    if len(roots) != 1:
        errors.append(f"handoff chain must have exactly one root; found {len(roots)}")

    forks = {target: children for target, children in referenced_as_parent.items() if len(children) > 1}
    for target, children in sorted(forks.items()):
        errors.append(f"handoff chain forks at {target}: {', '.join(sorted(children))}")

    heads = [handoff_id for handoff_id in ids if handoff_id not in referenced_as_parent]
    if len(heads) != 1:
        errors.append(f"handoff chain must have exactly one live head; found {len(heads)}")
    elif latest is not None and heads[0] != latest:
        errors.append(f"index latest {latest} does not match live head {heads[0]}")

    if len(current_ids) != 1:
        errors.append(f"handoff registry must have exactly one current status; found {len(current_ids)}")
    elif latest is not None and current_ids[0] != latest:
        errors.append(f"index latest {latest} does not match current handoff {current_ids[0]}")

    if latest is not None and latest not in ids:
        errors.append(f"index latest references missing handoff {latest}")

    if rows and latest is not None and rows[0].handoff_id != latest:
        errors.append(f"newest-first chain must start with index latest {latest}")
    for previous, current in zip(rows, rows[1:]):
        if previous.supersedes != current.handoff_id:
            errors.append(
                f"newest-first order broken: {previous.handoff_id} must supersede {current.handoff_id}"
            )
        previous_match = HISTORY_RE.fullmatch(previous.history)
        current_match = HISTORY_RE.fullmatch(current.history)
        if previous_match and current_match:
            previous_id = int(previous_match.group(1))
            current_id = int(current_match.group(1))
            if previous_id <= current_id:
                errors.append(
                    "handoff history order broken: "
                    f"{previous.handoff_id} {previous.history} must be later than "
                    f"{current.handoff_id} {current.history}"
                )
            previous_entry = history_entries.get(previous_id)
            current_entry = history_entries.get(current_id)
            if previous_entry is not None and current_entry is not None:
                previous_time = _history_time(previous_entry.date)
                current_time = _history_time(current_entry.date)
                if previous_time is None or current_time is None:
                    errors.append(
                        "handoff history entry has an invalid temporal timestamp: "
                        f"{previous.history} or {current.history}"
                    )
                elif previous_time < current_time:
                    errors.append(
                        "handoff temporal order broken: "
                        f"{previous.handoff_id} {previous_entry.date} predates "
                        f"{current.handoff_id} {current_entry.date}"
                    )
    if rows and rows[-1].supersedes is not None:
        errors.append(f"oldest handoff {rows[-1].handoff_id} must supersede none")

    handoff_dir = (repo_root / "docs" / "handoffs").resolve()
    if handoff_dir.is_dir():
        registered = {path for path in paths if path.is_file()}
        for doc_path in sorted(handoff_dir.glob("*.md")):
            resolved = doc_path.resolve()
            if resolved == index_path.resolve():
                continue
            if resolved not in registered:
                errors.append(f"unregistered handoff document: {doc_path.relative_to(repo_root)}")

    return not errors, errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the canonical handoff registry.")
    parser.add_argument("--index", type=Path, default=INDEX_PATH)
    parser.add_argument("--history", type=Path, default=HISTORY_PATH)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    ok, errors = verify_handoffs(args.index, repo_root=args.repo_root, history_path=args.history)
    if args.json:
        print(json.dumps({"ok": ok, "errors": errors}, indent=2))
    elif ok:
        print("Handoff registry OK")
    else:
        print("Handoff registry FAILED:")
        for error in errors:
            print(f"  - {error}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
