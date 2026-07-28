"""Provider-free G3 query-shape, determinism, and latency qualification.

The fixture creates one bounded synthetic graph in a temporary SQLite runtime,
then exercises filter-only, lexical traversal, historical traversal, and
cross-leg semantic-seeded query shapes. It reports exact quality checks and a
host-visible latency budget without making network, provider, install, or
download calls.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from seam_runtime.mirl import IRBatch, MIRLRecord, RecordKind
from seam_runtime.retrieval_orchestrator import RetrievalOrchestrator
from seam_runtime.retrieval_policy import (
    FUSION_POLICY,
    FUSION_POLICY_FINGERPRINT,
)
from seam_runtime.runtime import SeamRuntime

QUALIFICATION_SCHEMA = "graph-retrieval-qualification/1"
QUALIFICATION_NAMESPACE = "g3-qualification"
QUALIFICATION_SCOPE = "thread"


@dataclass(frozen=True)
class QueryShape:
    name: str
    query: str
    mode: str
    graph_hops: int
    expected_id: str
    expected_path_hops: int | None = None
    semantic_graph_seeding: bool = False
    graph_include_history: bool = False


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return parsed


def _node_id(index: int) -> str:
    return f"ent:g3-scale-{index:05d}"


def _relation_id(index: int) -> str:
    return f"rel:g3-scale-{index:05d}-{index + 1:05d}"


def _anchor(index: int) -> str:
    return f"ScaleAnchor{index:05d}"


def _synthetic_records(node_count: int) -> list[MIRLRecord]:
    records: list[MIRLRecord] = []
    for index in range(node_count):
        records.append(
            MIRLRecord(
                id=_node_id(index),
                kind=RecordKind.ENT,
                ns=QUALIFICATION_NAMESPACE,
                scope=QUALIFICATION_SCOPE,
                attrs={"label": _anchor(index), "entity_type": "concept"},
            )
        )
        if index + 1 < node_count:
            records.append(
                MIRLRecord(
                    id=_relation_id(index),
                    kind=RecordKind.REL,
                    ns=QUALIFICATION_NAMESPACE,
                    scope=QUALIFICATION_SCOPE,
                    attrs={
                        "src": _node_id(index),
                        "predicate": "next_scale_node",
                        "dst": _node_id(index + 1),
                        "label": f"{_anchor(index)} to {_anchor(index + 1)}",
                    },
                )
            )
    # A same-label distractor in another scope proves every query shape keeps
    # its namespace/scope boundary before ranking and traversal.
    records.append(
        MIRLRecord(
            id="ent:g3-cross-scope-distractor",
            kind=RecordKind.ENT,
            ns=QUALIFICATION_NAMESPACE,
            scope="project",
            attrs={"label": _anchor(0), "entity_type": "concept"},
        )
    )
    return records


def _query_shapes() -> tuple[QueryShape, ...]:
    return (
        QueryShape(
            name="structured-filter",
            query=f"id:{_relation_id(0)}",
            mode="hybrid",
            graph_hops=0,
            expected_id=_relation_id(0),
        ),
        QueryShape(
            name="lexical-hop-1",
            query=_anchor(0),
            mode="graph",
            graph_hops=1,
            expected_id=_node_id(1),
            expected_path_hops=1,
        ),
        QueryShape(
            name="lexical-hop-3",
            query=_anchor(0),
            mode="graph",
            graph_hops=3,
            expected_id=_node_id(3),
            expected_path_hops=3,
        ),
        QueryShape(
            name="history-hop-3",
            query=_anchor(0),
            mode="graph",
            graph_hops=3,
            expected_id=_node_id(3),
            expected_path_hops=3,
            graph_include_history=True,
        ),
        QueryShape(
            name="mixed-semantic-seeded",
            query=_anchor(0),
            mode="mix",
            graph_hops=1,
            expected_id=_relation_id(0),
            semantic_graph_seeding=True,
        ),
    )


def _nearest_rank_percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def qualify_runtime(
    runtime: SeamRuntime,
    *,
    node_count: int,
    repeats: int,
    max_latency_ms: float,
) -> dict[str, object]:
    """Run the fixed qualification shapes against an already seeded runtime."""

    if node_count < 8:
        raise ValueError("node_count must be at least 8")
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    if not math.isfinite(max_latency_ms) or max_latency_ms <= 0:
        raise ValueError("max_latency_ms must be finite and positive")

    orchestrator = RetrievalOrchestrator(runtime)
    shape_reports: list[dict[str, object]] = []
    for shape in _query_shapes():
        # One unmeasured warm-up keeps connection/schema initialization out of
        # the steady-state query latency fixture.
        orchestrator.decide(
            shape.query,
            namespace=QUALIFICATION_NAMESPACE,
            scope=QUALIFICATION_SCOPE,
            budget=20,
            mode=shape.mode,
            graph_hops=shape.graph_hops,
            semantic_graph_seeding=shape.semantic_graph_seeding,
            graph_include_history=shape.graph_include_history,
            candidate_trace_limit=20,
        )
        latencies: list[float] = []
        candidate_runs: list[list[str]] = []
        last_result = None
        for _ in range(repeats):
            started = perf_counter()
            result = orchestrator.decide(
                shape.query,
                namespace=QUALIFICATION_NAMESPACE,
                scope=QUALIFICATION_SCOPE,
                budget=20,
                mode=shape.mode,
                graph_hops=shape.graph_hops,
                semantic_graph_seeding=shape.semantic_graph_seeding,
                graph_include_history=shape.graph_include_history,
                candidate_trace_limit=20,
            )
            wall_ms = (perf_counter() - started) * 1000.0
            latencies.append(max(wall_ms, result.total_latency_ms))
            candidate_runs.append(
                [candidate.record.id for candidate in result.selected]
            )
            last_result = result
        assert last_result is not None
        by_id = {candidate.record.id: candidate for candidate in last_result.selected}
        expected = by_id.get(shape.expected_id)
        path_ok = (
            expected is not None
            and (
                shape.expected_path_hops is None
                or len(expected.graph_path) == shape.expected_path_hops
            )
        )
        boundary_ok = all(
            candidate.record.ns == QUALIFICATION_NAMESPACE
            and candidate.record.scope == QUALIFICATION_SCOPE
            for candidate in last_result.ranked
        )
        deterministic = all(run == candidate_runs[0] for run in candidate_runs[1:])
        multi_source_ok = (
            shape.mode != "mix"
            or any(len(candidate.sources) >= 2 for candidate in last_result.ranked)
        )
        p95_ms = _nearest_rank_percentile(latencies, 0.95)
        checks = {
            "expected_evidence": expected is not None,
            "expected_path": path_ok,
            "boundary_isolation": boundary_ok,
            "deterministic_ranking": deterministic,
            "cross_leg_evidence": multi_source_ok,
            "latency_budget": p95_ms <= max_latency_ms,
        }
        shape_reports.append(
            {
                "name": shape.name,
                "query": shape.query,
                "mode": shape.mode,
                "graph_hops": shape.graph_hops,
                "semantic_graph_seeding": shape.semantic_graph_seeding,
                "graph_include_history": shape.graph_include_history,
                "selected_ids": candidate_runs[0],
                "total_candidates": last_result.total_candidates,
                "latency_ms": {
                    "median": statistics.median(latencies),
                    "p95": p95_ms,
                    "max": max(latencies),
                },
                "checks": checks,
                "passed": all(checks.values()),
            }
        )

    return {
        "schema": QUALIFICATION_SCHEMA,
        "fusion_policy": FUSION_POLICY,
        "fusion_policy_fingerprint": FUSION_POLICY_FINGERPRINT,
        "provider_calls": 0,
        "corpus": {
            "namespace": QUALIFICATION_NAMESPACE,
            "scope": QUALIFICATION_SCOPE,
            "nodes": node_count,
            "edges": node_count - 1,
            "records": (node_count * 2),
        },
        "repeats": repeats,
        "max_latency_ms": max_latency_ms,
        "shapes": shape_reports,
        "passed": all(bool(report["passed"]) for report in shape_reports),
    }


def run_qualification(
    *,
    node_count: int = 2048,
    repeats: int = 5,
    max_latency_ms: float = 250.0,
) -> dict[str, object]:
    """Create the bounded fixture in a temporary runtime and qualify it."""

    if node_count < 8:
        raise ValueError("node_count must be at least 8")
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    if not math.isfinite(max_latency_ms) or max_latency_ms <= 0:
        raise ValueError("max_latency_ms must be finite and positive")
    with tempfile.TemporaryDirectory(prefix="seam-g3-qualification-") as temp_dir:
        runtime = SeamRuntime(
            Path(temp_dir) / "qualification.db",
            allow_pgvector_env=False,
        )
        try:
            started = perf_counter()
            runtime.persist_ir(IRBatch(_synthetic_records(node_count)))
            build_ms = (perf_counter() - started) * 1000.0
            report = qualify_runtime(
                runtime,
                node_count=node_count,
                repeats=repeats,
                max_latency_ms=max_latency_ms,
            )
            report["corpus"]["build_ms"] = build_ms  # type: ignore[index]
            return report
        finally:
            runtime.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", type=_positive_int, default=2048)
    parser.add_argument("--repeats", type=_positive_int, default=5)
    parser.add_argument(
        "--max-latency-ms",
        type=_positive_float,
        default=250.0,
        help="Per-query-shape p95 wall-clock budget after one warm-up.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_qualification(
        node_count=args.nodes,
        repeats=args.repeats,
        max_latency_ms=args.max_latency_ms,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
