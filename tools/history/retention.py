"""Prune old snapshots from .seam/snapshots/ according to a retention policy.

Usage:
    python -m tools.history.retention              # dry-run (default)
    python -m tools.history.retention --prune      # actually delete
    python -m tools.history.retention --keep 20    # keep latest 20
    python -m tools.history.retention --max-age 7  # keep snapshots from last 7 days
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
from pathlib import Path

from tools.history.history_lib import SNAPSHOTS_DIR

FILENAME_RE = re.compile(r"^(\d{8})-(\d{6})(?:-(\d{6}))?-(.+)\.json$")


def _parse_snapshot_filename(name: str) -> dict | None:
    """Parse a snapshot filename into its components.

    Handles both formats:
        YYYYMMDD-HHMMSS-XXXXXX-agent.json  (with random suffix)
        YYYYMMDD-HHMMSS-agent.json          (without random suffix)
    """
    m = FILENAME_RE.match(name)
    if not m:
        return None
    date_str, time_str, _random, agent = m.groups()
    try:
        ts = _dt.datetime.strptime(f"{date_str}{time_str}", "%Y%m%d%H%M%S")
    except ValueError:
        return None
    return {
        "date": date_str,
        "time": time_str,
        "agent": agent,
        "timestamp": ts,
        "filename": name,
    }


def _list_snapshots(snapshots_dir: Path) -> list[dict]:
    """List all snapshot files sorted by mtime (newest first)."""
    results = []
    if not snapshots_dir.exists():
        return results
    for p in sorted(snapshots_dir.iterdir()):
        if not p.is_file() or not p.name.endswith(".json"):
            continue
        info = _parse_snapshot_filename(p.name)
        if info is None:
            continue
        stat = p.stat()
        info["path"] = p
        info["size"] = stat.st_size
        info["mtime"] = stat.st_mtime
        results.append(info)
    results.sort(key=lambda x: x["mtime"], reverse=True)
    return results


def _parse_index_latest_entry_id(index_path: Path) -> int | None:
    """Parse HISTORY_INDEX.md to find the latest entry ID."""
    if not index_path.exists():
        return None
    text = index_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("latest_id:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
    return None


def _snapshot_latest_entry_id(snap: dict) -> int | None:
    """Read latest_entry_id from a snapshot file."""
    try:
        data = json.loads(snap["path"].read_text(encoding="utf-8"))
        return data.get("latest_entry_id")
    except (json.JSONDecodeError, OSError, KeyError):
        return None


def compute_retention(
    snapshots: list[dict],
    *,
    keep: int = 10,
    max_age_days: int = 30,
    index_path: Path | None = None,
) -> tuple[list[dict], list[dict]]:
    """Apply retention policy and return (keep, prune) lists.

    Policy:
    1. Always keep the latest N snapshots (by mtime).
    2. Keep at most one snapshot per calendar date — the latest for that date.
       This ensures every day with history entries retains its representative snapshot.
    3. Keep snapshots newer than max_age_days (by mtime).
    Everything else is marked for pruning.
    """
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=max_age_days)
    cutoff_ts = cutoff.timestamp()

    # Build set of dates that already have a "latest per day" kept snapshot
    kept_dates: set[str] = set()

    keep_list: list[dict] = []
    prune_list: list[dict] = []

    for i, snap in enumerate(snapshots):
        reason = None
        snap_date = snap["timestamp"].strftime("%Y-%m-%d")

        if i < keep:
            reason = f"latest-{keep}"
            kept_dates.add(snap_date)
        elif snap_date not in kept_dates:
            reason = "latest-per-day"
            kept_dates.add(snap_date)
        elif snap["mtime"] >= cutoff_ts:
            reason = f"within-{max_age_days}d"

        if reason:
            snap["keep_reason"] = reason
            keep_list.append(snap)
        else:
            prune_list.append(snap)

    return keep_list, prune_list


def _human_size(nbytes: int) -> str:
    if nbytes < 1024:
        return f"{nbytes} B"
    elif nbytes < 1024 * 1024:
        return f"{nbytes / 1024:.1f} KB"
    elif nbytes < 1024 * 1024 * 1024:
        return f"{nbytes / (1024 * 1024):.1f} MB"
    else:
        return f"{nbytes / (1024 * 1024 * 1024):.2f} GB"


def run_retention(
    *,
    snapshots_dir: Path | None = None,
    index_path: Path | None = None,
    keep: int = 10,
    max_age_days: int = 30,
    prune: bool = False,
) -> dict:
    """Execute the retention policy. Returns a summary dict."""
    if snapshots_dir is None:
        snapshots_dir = SNAPSHOTS_DIR

    snapshots = _list_snapshots(snapshots_dir)
    keep_list, prune_list = compute_retention(
        snapshots, keep=keep, max_age_days=max_age_days, index_path=index_path
    )

    total_size = sum(s["size"] for s in snapshots)
    prune_size = sum(s["size"] for s in prune_list)

    if prune:
        for snap in prune_list:
            snap["path"].unlink()

    return {
        "total_snapshots": len(snapshots),
        "kept": len(keep_list),
        "pruned": len(prune_list),
        "total_size": total_size,
        "pruned_size": prune_size,
        "remaining_size": total_size - prune_size,
        "pruned_files": [s["filename"] for s in prune_list],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Prune old snapshots from .seam/snapshots/"
    )
    p.add_argument(
        "--keep",
        type=int,
        default=10,
        help="Number of latest snapshots to always keep (default: 10)",
    )
    p.add_argument(
        "--max-age",
        type=int,
        default=30,
        dest="max_age_days",
        help="Keep snapshots newer than this many days (default: 30)",
    )
    p.add_argument(
        "--snapshots-dir",
        type=Path,
        default=None,
        help="Override snapshots directory",
    )
    p.add_argument(
        "--prune",
        action="store_true",
        help="Actually delete pruned snapshots (default: dry-run)",
    )
    args = p.parse_args(argv)

    mode = "PRUNE" if args.prune else "DRY-RUN"
    print(f"Snapshot retention [{mode}]")
    print(f"  keep latest: {args.keep}")
    print(f"  max age:     {args.max_age_days} days")
    print()

    result = run_retention(
        snapshots_dir=args.snapshots_dir,
        keep=args.keep,
        max_age_days=args.max_age_days,
        prune=args.prune,
    )

    print(f"Total snapshots: {result['total_snapshots']}")
    print(f"Total size:      {_human_size(result['total_size'])}")
    print()
    print(f"Keeping:  {result['kept']} snapshots")
    print(f"Pruning:  {result['pruned']} snapshots ({_human_size(result['pruned_size'])} freed)")
    print(f"Remaining: {_human_size(result['remaining_size'])}")
    print()

    if result["pruned_files"]:
        action = "Would delete" if not args.prune else "Deleted"
        print(f"{action}:")
        for f in result["pruned_files"]:
            print(f"  {f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
