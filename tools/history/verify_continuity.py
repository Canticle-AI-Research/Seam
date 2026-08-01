"""Verify SEAM continuity rules beyond entry hash integrity."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.history.history_lib import (
    HISTORY_PATH,
    INDEX_PATH,
    SNAPSHOTS_DIR,
    Entry,
    parse_entries,
    read_history_bytes,
)
from tools.history.load_snapshot import find_latest, load_and_verify
from tools.history.recorded_fact_audit import audit_recorded_facts
from tools.history.verify_integrity import verify as verify_integrity
from tools.history.verify_routing import verify_routing
from tools.security.secret_scan import scan_worktree


def _index_latest_id(index_path: Path) -> int | None:
    if not index_path.exists():
        return None
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("latest_id:"):
            continue
        raw = line.split(":", 1)[1].strip()
        if raw == "none":
            return None
        return int(raw)
    return None


def _check_supersedes(entries: list[Entry]) -> list[str]:
    errors: list[str] = []
    ids = {e.id for e in entries}
    for e in entries:
        if e.supersedes == "none":
            continue
        try:
            target = int(e.supersedes.lstrip("#"))
        except ValueError:
            errors.append(f"Entry #{e.id:03d} has invalid supersedes value {e.supersedes!r}")
            continue
        if target not in ids:
            errors.append(f"Entry #{e.id:03d} supersedes missing entry #{target:03d}")
        elif target >= e.id:
            errors.append(f"Entry #{e.id:03d} supersedes non-prior entry #{target:03d}")
    return errors


def _scan_session_links_and_secrets(repo_root: Path) -> list[str]:
    return [finding.format() for finding in scan_worktree(repo_root)]


def verify_continuity(
    *,
    history_path: Path = HISTORY_PATH,
    index_path: Path = INDEX_PATH,
    snapshots_dir: Path = SNAPSHOTS_DIR,
    require_latest_snapshot: bool = True,
    scan_secrets: bool = True,
    verify_routes: bool = True,
    audit_recorded_claims: bool = True,
) -> tuple[bool, list[str]]:
    errors: list[str] = []

    ok, integrity_errors = verify_integrity(history_path, index_path)
    if not ok:
        errors.extend(f"integrity: {err}" for err in integrity_errors)

    data = read_history_bytes(history_path)
    entries = parse_entries(data) if data else []
    latest_entry = entries[-1] if entries else None
    index_latest = _index_latest_id(index_path)
    if latest_entry and index_latest != latest_entry.id:
        errors.append(
            f"HISTORY_INDEX.md latest_id {index_latest!r} does not match HISTORY latest #{latest_entry.id:03d}"
        )

    errors.extend(_check_supersedes(entries))

    if require_latest_snapshot and latest_entry:
        latest_snapshot = find_latest(snapshots_dir)
        if latest_snapshot is None:
            errors.append("No snapshot found for latest history entry")
        else:
            snapshot_ok, payload, snapshot_errors = load_and_verify(latest_snapshot, history_path)
            if not snapshot_ok:
                errors.extend(f"snapshot: {err}" for err in snapshot_errors)
            else:
                selected = {int(item["id"]) for item in payload.get("selected_entries", [])}
                if latest_entry.id not in selected:
                    errors.append(
                        f"Latest snapshot {latest_snapshot.name} does not reference latest entry #{latest_entry.id:03d}"
                    )

    if scan_secrets:
        repo_root = history_path.parent
        errors.extend(f"security: {err}" for err in _scan_session_links_and_secrets(repo_root))

    if verify_routes:
        ok, route_errors = verify_routing(repo_root=history_path.parent, history_path=history_path)
        if not ok:
            errors.extend(f"routing: {err}" for err in route_errors)

    if audit_recorded_claims:
        recorded_fact_errors = audit_recorded_facts(
            history_path.parent,
            history_path=history_path,
        )
        errors.extend(f"recorded-fact: {issue.format()}" for issue in recorded_fact_errors)

    return len(errors) == 0, errors


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Verify SEAM temporal continuity rules.")
    p.add_argument("--history", type=Path, default=HISTORY_PATH)
    p.add_argument("--index", type=Path, default=INDEX_PATH)
    p.add_argument("--snapshots-dir", type=Path, default=SNAPSHOTS_DIR)
    p.add_argument("--no-snapshot", action="store_true", help="skip latest snapshot check")
    p.add_argument("--no-secret-scan", action="store_true", help="skip session-link/key scan")
    p.add_argument("--no-routing", action="store_true", help="skip routing taxonomy check")
    p.add_argument("--no-recorded-fact-audit", action="store_true", help="skip checkable recorded-fact claim audit")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    ok, errors = verify_continuity(
        history_path=args.history,
        index_path=args.index,
        snapshots_dir=args.snapshots_dir,
        require_latest_snapshot=not args.no_snapshot,
        scan_secrets=not args.no_secret_scan,
        verify_routes=not args.no_routing,
        audit_recorded_claims=not args.no_recorded_fact_audit,
    )

    if args.json:
        print(json.dumps({"ok": ok, "errors": errors}, indent=2))
    elif ok:
        print("Continuity OK")
    else:
        print("Continuity FAILED:")
        for err in errors:
            print(f"  - {err}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
