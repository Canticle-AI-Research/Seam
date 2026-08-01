"""Build a LoCoMo corpus without querying it.

Retrieval mutates the SQLite store, so cloning databases *after* a scored run
gives the second arm of an A/B a different pre-query corpus than the first arm
saw. That is exactly the confound a ranking ablation cannot tolerate.

This module performs the ingest half of ``_run_grouped_scope`` and stops. The
resulting directory is a pristine snapshot that can be cloned once per arm, so
every arm starts from byte-identical bytes.

Usage:
    python -m benchmarks.external.locomo.ingest_only \
        --dataset-path /path/to/locomo10.json --db-path /work/base
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from benchmarks.external.common.dataset import load_locomo_cases
from benchmarks.external.common.runner import _group_cases
from benchmarks.external.locomo.run import _locomo_scope_id, build_adapter


def corpus_digest(db_root: Path) -> str:
    """Aggregate SHA-256 over every database file, in stable path order."""
    digest = hashlib.sha256()
    for path in sorted(db_root.rglob("*.db")):
        digest.update(path.relative_to(db_root).as_posix().encode("utf-8"))
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest a LoCoMo corpus only")
    parser.add_argument("--dataset-path", required=True)
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--context-budget", type=int, default=8000)
    parser.add_argument("--search-top-k", type=int, default=100)
    args = parser.parse_args(argv)

    root = Path(args.db_path).expanduser().resolve()
    existing_sqlite_files = sorted(
        path
        for pattern in ("*.db", "*.db-wal", "*.db-shm")
        for path in root.rglob(pattern)
        if path.is_file()
    )
    if existing_sqlite_files:
        relative_paths = ", ".join(
            path.relative_to(root).as_posix() for path in existing_sqlite_files
        )
        raise RuntimeError(
            "LoCoMo ingest-only target root already contains SQLite corpus "
            "files or sidecars; "
            "refusing to build the adapter or run embedding preflight: "
            f"{relative_paths}"
        )

    cases = load_locomo_cases(Path(args.dataset_path))
    adapter = build_adapter(
        "seam",
        keep_db=False,
        db_path=str(root),
        context_budget=args.context_budget,
        search_top_k=args.search_top_k,
    )

    groups = _group_cases(cases, _locomo_scope_id)
    turns = 0
    embedding_preflight = None
    try:
        embedding_preflight = adapter.preflight(groups)
        for scope, group in groups.items():
            adapter.reset(scope)
            for turn in group[0].conversation:
                adapter.ingest_turn(scope, turn)
                turns += 1
            print(f"[ingest] {scope}: {len(group[0].conversation)} turns", flush=True)
    finally:
        close = getattr(adapter, "close", None)
        if callable(close):
            close()

    digest = corpus_digest(root)
    from benchmarks.external.locomo.adapters.seam import (
        canonical_json_sha256,
        embedding_preflight_receipt_sha256,
    )

    embedding_preflight_sha256 = embedding_preflight_receipt_sha256(
        embedding_preflight
    )
    corpus_binding = {
        "schema": "seam-locomo-corpus-contract/1",
        "corpus_digest": digest,
        "embedding_preflight": embedding_preflight,
        "embedding_preflight_sha256": embedding_preflight_sha256,
    }
    report = {
        "scopes": len(groups),
        "cases": len(cases),
        "turns": turns,
        "db_path": str(root),
        "corpus_digest": digest,
        "embedding_preflight": embedding_preflight,
        "embedding_preflight_sha256": embedding_preflight_sha256,
        "corpus_contract": {
            "schema": corpus_binding["schema"],
            "corpus_digest": digest,
            "embedding_preflight_sha256": embedding_preflight_sha256,
            "integrity_sha256": canonical_json_sha256(corpus_binding),
        },
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
