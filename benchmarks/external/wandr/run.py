"""Zero-network WANDR replay runner.

Usage:
    python -m benchmarks.external.wandr.run --task smoke --dry-run
    python -m benchmarks.external.wandr.run --task hierarchy --lane native
    python -m benchmarks.external.wandr.run --task hierarchy --ablate

This lane never touches WANDR's official pipeline, which is networked and paid.
It replays a hash-pinned local corpus and measures SEAM's memory behaviour:
source recovery, provenance fidelity, entity canonicalization, deduplication,
and batch recovery. Provider, network, and cost counters are asserted at zero.

A parity result between lanes is a valid outcome. Do not read graph activity as
graph lift: incremental value requires an attributable recovery gain with no
contract regression.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from benchmarks.external.wandr.adapters.seam import LANES, SeamWandrAdapter
from benchmarks.external.wandr.corpus import (
    available_tasks,
    load_task,
    validate_hierarchy,
)
from benchmarks.external.wandr.types import WandrTask, stable_id


def _expected_sources(task: WandrTask) -> dict[str, set[str]]:
    """Canonical source ids that *should* be recoverable per member."""
    from benchmarks.external.wandr.adapters.seam import canonical_url

    expected: dict[str, set[str]] = {}
    for row in task.rows:
        expected.setdefault(row.member_key, set()).add(
            stable_id("source", task.name, canonical_url(row.url))
        )
    return expected


def run_lane(task: WandrTask, lane: str, db_root: Path) -> dict[str, Any]:
    """Ingest and replay one lane. Budgets are identical across lanes."""
    adapter = SeamWandrAdapter(db_root / lane, lane=lane)
    try:
        scope = task.name
        ingest = adapter.ingest_task(scope, task)
        expected = _expected_sources(task)

        per_member: list[dict[str, Any]] = []
        recovered_total = 0
        expected_total = 0
        for member, wanted in expected.items():
            got = set(adapter.recovered_sources(scope, task.name, member))
            hit = wanted & got
            recovered_total += len(hit)
            expected_total += len(wanted)
            per_member.append(
                {
                    "member": member,
                    "expected": len(wanted),
                    "recovered": len(hit),
                    "missing": sorted(wanted - got),
                }
            )

        # Batch recovery: a second adapter over the same store must recover the
        # same evidence, proving persistence rather than in-process state.
        reopened = SeamWandrAdapter(db_root / lane, lane=lane)
        try:
            recheck = sum(
                len(expected[m] & set(reopened.recovered_sources(scope, task.name, m)))
                for m in expected
            )
        finally:
            reopened.close()

        return {
            "lane": lane,
            "ingest": ingest,
            "source_recall": (
                recovered_total / expected_total if expected_total else 0.0
            ),
            "recovered": recovered_total,
            "expected": expected_total,
            "per_member": per_member,
            "batch_recovery_ok": recheck == recovered_total,
            "counters": adapter.counters(),
        }
    finally:
        adapter.close()


def build_report(task: WandrTask, lanes: list[str], db_root: Path) -> dict[str, Any]:
    results = [run_lane(task, lane, db_root) for lane in lanes]
    by_lane = {r["lane"]: r for r in results}

    report: dict[str, Any] = {
        "benchmark": "wandr-replay",
        "mode": "zero-network-replay",
        "official_pipeline_executed": False,
        "task": {
            "name": task.name,
            "task_id": task.task_id,
            "topology": task.topology,
            "rows": len(task.rows),
            "members": len(task.member_keys()),
            "key_hierarchy": [
                {"name": k.name, "required": k.required} for k in task.key_hierarchy
            ],
            "hierarchy_violations": validate_hierarchy(task),
        },
        "lanes": results,
    }

    if "native" in by_lane and "event-only" in by_lane:
        native = by_lane["native"]["source_recall"]
        event = by_lane["event-only"]["source_recall"]
        delta = native - event
        report["ablation"] = {
            "native_source_recall": native,
            "event_only_source_recall": event,
            "delta": delta,
            # Deliberately conservative: parity is the honest default, and a
            # positive delta is only ever "attributable", never "lift".
            "verdict": (
                "parity"
                if abs(delta) < 1e-9
                else ("native-attributable-gain" if delta > 0 else "native-regression")
            ),
        }

    counters = [r["counters"] for r in results]
    report["cost"] = {
        "provider_calls": sum(c["provider_calls"] for c in counters),
        "network_calls": sum(c["network_calls"] for c in counters),
        "cost_usd": sum(c["cost_usd"] for c in counters),
    }
    report["free_lane_verified"] = (
        report["cost"]["provider_calls"] == 0
        and report["cost"]["network_calls"] == 0
        and report["cost"]["cost_usd"] == 0.0
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Zero-network WANDR replay lane for SEAM"
    )
    parser.add_argument("--task", default="smoke", help="pinned replay task name")
    parser.add_argument("--lane", choices=LANES, default="native")
    parser.add_argument(
        "--ablate",
        action="store_true",
        help="run native and event-only lanes for a same-code graph ablation",
    )
    parser.add_argument("--list-tasks", action="store_true")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate the pinned corpus without ingesting or retrieving",
    )
    parser.add_argument("--db-root", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args(argv)

    if args.list_tasks:
        print(json.dumps({"tasks": list(available_tasks())}, indent=2))
        return 0

    task = load_task(args.task)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "task": task.name,
                    "task_id": task.task_id,
                    "topology": task.topology,
                    "rows": len(task.rows),
                    "members": len(task.member_keys()),
                    "hierarchy_violations": validate_hierarchy(task),
                    "mode": "dry-run",
                    "official_pipeline_executed": False,
                },
                indent=2,
            )
        )
        return 0

    lanes = list(LANES) if args.ablate else [args.lane]

    if args.db_root:
        report = build_report(task, lanes, Path(args.db_root))
    else:
        with tempfile.TemporaryDirectory(prefix="wandr-replay-") as tmp:
            report = build_report(task, lanes, Path(tmp))

    payload = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(payload + "\n")
        print(f"Report written to {args.output}")
    else:
        print(payload)

    if not report["free_lane_verified"]:
        print("ERROR: replay lane recorded a non-zero cost counter", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
