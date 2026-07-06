"""SEAM adapter for the mem0ai/memory-benchmarks harness.

This module implements the expected harness protocol so SEAM can be
evaluated by the standard open-source memory benchmark suite. It wraps
SEAM's runtime APIs (ingest, search, context) behind the interface the
harness expects without copying any upstream benchmark code into this repo.

Usage (against a local harness clone):
    git clone https://github.com/mem0ai/memory-benchmarks ../memory-benchmarks
    .venv/bin/python -m benchmarks.external.mem0_harness.adapter \
        --harness ../memory-benchmarks --dataset locomo --dry-run
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MemoryResult:
    """One retrieved memory entry as returned to the harness."""
    id: str
    memory: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


class SeamMem0HarnessAdapter:
    """SEAM-backed adapter matching the mem0ai/memory-benchmarks interface.

    Each ``scope_id`` maps to a per-conversation SQLite database under
    ``db_root/``, providing complete storage isolation per benchmark case.
    """

    name = "seam"

    def __init__(self, db_root: str | None = None, budget: int = 2000) -> None:
        self._db_root = Path(db_root) if db_root is not None else Path("test_seam/mem0_harness")
        self.budget = budget

    # -- harness protocol --------------------------------------------------

    def add(self, messages: list[dict[str, str]], *, user_id: str) -> None:
        """Ingest a list of conversation messages for a user/scoped session.

        Each message is a dict with ``role`` and ``content`` keys.
        """
        if not messages:
            return
        text = _format_messages(messages)
        if not text.strip():
            return

        rt = _open_runtime(self._db_path(user_id))
        try:
            rt.ingest_text(
                text=text,
                source_ref=f"mem0-harness:{user_id}",
                ns=f"mem0-harness:{user_id}",
                scope="thread",
                persist=True,
            )
        finally:
            _close_runtime(rt)

    def search(self, query: str, *, user_id: str, limit: int = 10) -> list[MemoryResult]:
        """Search memory for records relevant to *query* and return ranked results."""

        rt = _open_runtime(self._db_path(user_id))
        try:
            result = rt.search_ir(query, scope="thread", budget=self.budget)
            output: list[MemoryResult] = []
            for candidate in result.candidates[:limit]:
                rid = candidate.record.id
                record_ids = [rid]
                record_ids.extend(candidate.record.evidence or [])
                record_ids.extend(candidate.record.prov or [])
                pack = rt.pack_ir(record_ids, lens="general", budget=self.budget // max(1, limit), mode="exact")
                pack_dict = pack.to_dict() if hasattr(pack, "to_dict") else {}
                memory_text = json.dumps(pack_dict, sort_keys=True)
                output.append(
                    MemoryResult(
                        id=rid,
                        memory=memory_text,
                        score=candidate.score,
                        metadata={"source": "seam", "kind": candidate.record.kind.value},
                    )
                )
            return output
        finally:
            _close_runtime(rt)

    def delete(self, *, user_id: str) -> None:
        """Remove all memory for a user/scoped session."""
        db = self._db_path(user_id)
        _remove_db_files(db)

    # -- helpers -----------------------------------------------------------

    def _db_path(self, scope_id: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in scope_id)
        return self._db_root / f"{safe}.db"


def _open_runtime(db_path: Path):
    from seam_runtime.runtime import SeamRuntime

    db_path.parent.mkdir(parents=True, exist_ok=True)
    return SeamRuntime(str(db_path))


def _close_runtime(runtime) -> None:
    """Close a runtime's store so the SQLite file is unlocked for delete/cleanup.

    Without this, Windows holds the per-user ``.db`` open and both ``delete()``
    and pytest tempdir teardown fail with WinError 32.
    """
    close = getattr(runtime, "close", None)
    if callable(close):
        close()


def _format_messages(messages: list[dict[str, str]]) -> str:
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        parts.append(f"[{role}] {content}")
    return "\n".join(parts)


def _remove_db_files(db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db_path) + suffix)
        if sidecar.exists():
            sidecar.unlink()


# -- CLI entrypoint for manual harness runs --------------------------------

def main() -> None:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="SEAM mem0 harness adapter")
    parser.add_argument("--harness", help="Path to memory-benchmarks clone")
    parser.add_argument("--dataset", choices=["locomo"], default="locomo")
    parser.add_argument("--dry-run", action="store_true", help="Validate the harness path and print config")
    args = parser.parse_args()

    if args.dry_run:
        if args.harness:
            harness_path = Path(args.harness)
            if not harness_path.is_dir():
                print(f"ERROR: harness path not found: {args.harness}", file=sys.stderr)
                raise SystemExit(1)
            print(f"Harness path: {harness_path.resolve()}")
        print("Adapter: seam (SEAM mem0 harness adapter)")
        print(f"Dataset: {args.dataset}")
        print("Mode: dry-run (no cases executed)")
        print("Ready for real run when --harness points to a valid clone")
        return

    print("Real harness runs require the upstream clone and are deferred.", file=sys.stderr)
    print("Run with --dry-run to validate configuration.", file=sys.stderr)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
