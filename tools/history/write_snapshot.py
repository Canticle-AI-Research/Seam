"""Write a multi-agent handoff snapshot to .seam/snapshots/."""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from tools.history.history_lib import (
    HISTORY_PATH,
    # INDEX_PATH/SNAPSHOTS_DIR aren't read as bare names here (call sites use
    # the live history_lib.INDEX_PATH/history_lib.SNAPSHOTS_DIR so test
    # monkeypatching of history_lib takes effect) -- re-exported only so
    # test_history_tools.py's _MultiPatch can also patch this module's own
    # attribute of the same name.
    INDEX_PATH,  # noqa: F401
    SNAPSHOTS_DIR,  # noqa: F401
    parse_entries,
    read_history_bytes,
)


def _git_sha(cwd: Path) -> str:
    try:
        res = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return res.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def _index_version() -> str:
    from tools.history import history_lib
    path = history_lib.INDEX_PATH
    if not path.exists():
        return "none"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _compute_integrity_hash(payload: dict) -> str:
    """Hash the snapshot JSON excluding the integrity_hash field itself."""
    without = {k: v for k, v in payload.items() if k != "integrity_hash"}
    blob = json.dumps(without, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def write_snapshot(
    *,
    agent: str,
    entry_ids: list[int],
    token_budget: int,
    include_pack: bool = True,
    snapshots_dir: Path | None = None,
    history_path: Path | None = None,
) -> Path:
    from tools.history import history_lib
    if snapshots_dir is None:
        snapshots_dir = history_lib.SNAPSHOTS_DIR
    if history_path is None:
        history_path = history_lib.HISTORY_PATH
    data = read_history_bytes(history_path)
    entries = parse_entries(data) if data else []
    by_id = {e.id: e for e in entries}

    selected = []
    pack_chunks = []
    pack_entry_ids = []
    skipped_entry_ids = []
    tokens_used = 0
    for eid in entry_ids:
        if eid not in by_id:
            raise ValueError(f"Entry #{eid:03d} not found in HISTORY.md")
        e = by_id[eid]
        selected.append({"id": e.id, "hash": e.hash_short})
        if include_pack:
            if tokens_used + e.tokens > token_budget:
                skipped_entry_ids.append(e.id)
                continue
            pack_chunks.append(e.raw.decode("utf-8"))
            pack_entry_ids.append(e.id)
            tokens_used += e.tokens

    now = _dt.datetime.now(_dt.timezone.utc)
    payload = {
        "schema": "seam-snapshot/v1",
        "agent": agent,
        "timestamp": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_sha": _git_sha(HISTORY_PATH.parent),
        "token_budget": token_budget,
        "tokens_used": tokens_used,
        "index_version": _index_version(),
        "latest_entry_id": max(entry_ids) if entry_ids else None,
        "selected_entries": selected,
        "pack_entry_ids": pack_entry_ids if include_pack else [],
        "skipped_entry_ids": skipped_entry_ids if include_pack else [],
        "pack": "\n\n".join(pack_chunks) if include_pack else "",
    }
    payload["integrity_hash"] = _compute_integrity_hash(payload)

    snapshots_dir.mkdir(parents=True, exist_ok=True)
    ts = now.strftime("%Y%m%d-%H%M%S-") + f"{now.microsecond:06d}"
    out_path = snapshots_dir / f"{ts}-{agent}.json"
    if out_path.exists():
        suffix = 1
        while True:
            candidate = snapshots_dir / f"{ts}-{agent}-{suffix:02d}.json"
            if not candidate.exists():
                out_path = candidate
                break
            suffix += 1
    tmp_path = out_path.with_name(f".{out_path.name}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    os.replace(tmp_path, out_path)
    return out_path


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Write a handoff snapshot.")
    p.add_argument("--agent", required=True)
    p.add_argument("--entries", required=True, help="comma-separated entry ids")
    p.add_argument("--token-budget", type=int, default=1800)
    p.add_argument("--no-pack", action="store_true", help="exclude resolved pack text")
    args = p.parse_args(argv)

    entry_ids = [int(x.strip().lstrip("#")) for x in args.entries.split(",") if x.strip()]
    out = write_snapshot(
        agent=args.agent,
        entry_ids=entry_ids,
        token_budget=args.token_budget,
        include_pack=not args.no_pack,
    )
    print(f"Wrote snapshot: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
