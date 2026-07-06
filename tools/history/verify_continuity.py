"""Verify SEAM continuity rules beyond entry hash integrity."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
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

SESSION_OR_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "provider_session_url",
        re.compile(
            r"https?://[^\s\)\]\}>\"']*(?:claude\.ai|chatgpt\.com|chat\.openai\.com|cursor\.com|/share/|session(?:=|/)|thread(?:=|/))[^\s\)\]\}>\"']*",
            re.IGNORECASE,
        ),
    ),
    (
        "api_key",
        re.compile(
            r"\b(?:sk-or-v1-|sk-ant-|sk-)[A-Za-z0-9_-]{16,}\b"
            r"|\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b"
            r"|github_pat_[A-Za-z0-9_]{20,}"
            r"|\bAIza[0-9A-Za-z_-]{20,}\b"
            r"|\bAKIA[0-9A-Z]{16}\b"
        ),
    ),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "dsn_password",
        re.compile(r"(?i)\b(?:postgres|postgresql|mysql|mongodb|redis)://[^\s:@/]+:[^\s:@/]{3,}@"),
    ),
)


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


def _git_files(repo_root: Path) -> list[Path]:
    try:
        res = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "--cached", "--others", "--exclude-standard"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if res.returncode != 0:
        return []
    return [repo_root / line for line in res.stdout.splitlines() if line.strip()]


def _scan_session_links_and_secrets(repo_root: Path) -> list[str]:
    errors: list[str] = []
    for path in _git_files(repo_root):
        if not path.is_file():
            continue
        try:
            sample = path.read_bytes()[:4096]
        except OSError:
            continue
        if b"\0" in sample:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(repo_root)
        for line_no, line in enumerate(text.splitlines(), 1):
            for name, pattern in SESSION_OR_SECRET_PATTERNS:
                if pattern.search(line):
                    errors.append(f"{rel}:{line_no}: {name}")
    return errors


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
