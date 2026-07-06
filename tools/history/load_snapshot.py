"""Load and verify a snapshot. Prints the resolved pack on success."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from tools.history.history_lib import (
    # Not read as a bare name here (find_latest() reads the live
    # history_lib.SNAPSHOTS_DIR so test monkeypatching of history_lib takes
    # effect) -- re-exported only so test_history_tools.py's _MultiPatch can
    # also patch this module's own attribute of the same name.
    SNAPSHOTS_DIR,  # noqa: F401
    parse_entries,
    read_history_bytes,
)


def _compute_integrity_hash(payload: dict) -> str:
    without = {k: v for k, v in payload.items() if k != "integrity_hash"}
    blob = json.dumps(without, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def find_latest(snapshots_dir: Path | None = None) -> Path | None:
    from tools.history import history_lib
    if snapshots_dir is None:
        snapshots_dir = history_lib.SNAPSHOTS_DIR
    elif not any(snapshots_dir.glob("*.json")):
        repo_snapshot_dir = snapshots_dir / ".seam" / "snapshots"
        if repo_snapshot_dir.exists():
            snapshots_dir = repo_snapshot_dir
    if not snapshots_dir.exists():
        return None
    candidates = sorted(snapshots_dir.glob("*.json"))
    return candidates[-1] if candidates else None


def load_and_verify(
    path: Path, history_path: Path | None = None
) -> tuple[bool, dict, list[str]]:
    from tools.history import history_lib
    if history_path is None:
        history_path = history_lib.HISTORY_PATH
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return False, {}, [f"JSON decode error: {e}"]

    claimed = payload.get("integrity_hash")
    computed = _compute_integrity_hash(payload)
    if claimed != computed:
        errors.append(f"integrity_hash mismatch: claimed={claimed} computed={computed}")

    data = read_history_bytes(history_path)
    entries = parse_entries(data) if data else []
    by_id = {e.id: e for e in entries}

    for ref in payload.get("selected_entries", []):
        eid = ref.get("id")
        expected_short = ref.get("hash")
        e = by_id.get(eid)
        if e is None:
            errors.append(f"Entry #{eid:03d} referenced in snapshot but missing from HISTORY.md")
            continue
        if not e.hash_short.startswith(expected_short.rstrip(".")):
            errors.append(
                f"Entry #{eid:03d} hash mismatch: snapshot={expected_short} "
                f"current={e.hash_short}"
            )

    return len(errors) == 0, payload, errors


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Load and verify a snapshot.")
    p.add_argument("path", nargs="?", default="latest", help="snapshot path or 'latest'")
    p.add_argument("--pack-only", action="store_true", help="print only the pack text")
    args = p.parse_args(argv)

    if args.path == "latest":
        target = find_latest()
        if target is None:
            print("No snapshots found", file=sys.stderr)
            return 2
    else:
        target = Path(args.path)
        if not target.exists():
            print(f"Snapshot not found: {target}", file=sys.stderr)
            return 2

    ok, payload, errors = load_and_verify(target)
    if not ok:
        print(f"Snapshot verification FAILED for {target}:", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    if args.pack_only:
        print(payload.get("pack", ""))
    else:
        print(f"Snapshot OK: {target}")
        print(f"  agent:       {payload.get('agent')}")
        print(f"  timestamp:   {payload.get('timestamp')}")
        print(f"  git_sha:     {payload.get('git_sha')}")
        print(f"  entries:     {len(payload.get('selected_entries', []))}")
        print(f"  tokens_used: {payload.get('tokens_used')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
