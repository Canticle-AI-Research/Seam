"""Provider-free G3 qualification on the pinned real LoCoMo conversation corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from seam_runtime.models import SentenceTransformerModel
from seam_runtime.retrieval import RetrievalFlags
from seam_runtime.retrieval_orchestrator import RetrievalOrchestrator
from seam_runtime.runtime import SeamRuntime
from seam_runtime.self_improve import GraphProbeScorer

QUALIFICATION_SCHEMA = "graph-real-corpus-qualification/1"
DEFAULT_DATASET = Path(
    "benchmarks/external/locomo/data/locomo10.json"
)
DEFAULT_MANIFEST = Path(
    "benchmarks/external/locomo/data/locomo10.manifest.json"
)
QUALIFICATION_NAMESPACE = "g3-real-corpus"
QUALIFICATION_SCOPE = "project"
GRAPH_SEED_CANDIDATES = (4, 8, 16, 32)
NOISE_MARGIN = 0.005
REGRESSION_TOLERANCE = 0.005


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _session_items(sample: dict[str, object]) -> list[tuple[str, list[dict[str, object]]]]:
    conversation = sample.get("conversation")
    if not isinstance(conversation, dict):
        raise ValueError("LoCoMo sample conversation must be an object")
    sessions = [
        (key, value)
        for key, value in conversation.items()
        if key.startswith("session_")
        and key.split("_", 1)[1].isdigit()
        and isinstance(value, list)
    ]
    return sorted(
        sessions,
        key=lambda item: int(item[0].split("_", 1)[1]),
    )


def _session_text(turns: list[dict[str, object]]) -> str:
    lines = []
    for turn in turns:
        speaker = str(turn.get("speaker") or "speaker").strip()
        text = str(turn.get("text") or "").strip()
        if text:
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


def _stratified_split(probes):
    """Keep every observed motif represented in both fixed evaluation splits."""

    by_motif: dict[str, list] = {}
    for probe in probes:
        by_motif.setdefault(probe.motif, []).append(probe)
    development = []
    holdout = []
    for motif_probes in by_motif.values():
        development.extend(motif_probes[::2])
        holdout.extend(motif_probes[1::2])
    return development, holdout


def _no_regression(candidate, baseline) -> bool:
    if candidate.aggregate < baseline.aggregate - REGRESSION_TOLERANCE:
        return False
    return all(
        candidate.per_category.get(motif, 0.0)
        >= score - REGRESSION_TOLERANCE
        for motif, score in baseline.per_category.items()
    )


def qualify_real_corpus(
    *,
    dataset_path: Path = DEFAULT_DATASET,
    manifest_path: Path = DEFAULT_MANIFEST,
    sample_index: int = 0,
    sessions: int = 2,
    probe_sample: int = 100,
    embedding_model: str | None = None,
) -> dict[str, object]:
    if sessions < 1:
        raise ValueError("sessions must be positive")
    if probe_sample < 1:
        raise ValueError("probe_sample must be positive")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual_sha256 = _sha256(dataset_path)
    if actual_sha256 != manifest.get("sha256"):
        raise ValueError("LoCoMo dataset hash does not match its pinned manifest")
    samples = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(samples, list) or not 0 <= sample_index < len(samples):
        raise ValueError("sample_index is outside the LoCoMo corpus")
    sample = samples[sample_index]
    if not isinstance(sample, dict):
        raise ValueError("LoCoMo sample must be an object")
    selected_sessions = _session_items(sample)[:sessions]
    if not selected_sessions:
        raise ValueError("LoCoMo sample has no usable sessions")

    model = (
        SentenceTransformerModel(
            model_name=embedding_model,
            local_files_only=True,
        )
        if embedding_model
        else None
    )
    with tempfile.TemporaryDirectory(
        prefix="seam-g3-real-corpus-"
    ) as temp_dir:
        runtime = SeamRuntime(
            Path(temp_dir) / "qualification.db",
            embedding_model=model,
            allow_pgvector_env=False,
        )
        try:
            for session_name, turns in selected_sessions:
                runtime.ingest_text(
                    _session_text(turns),
                    source_ref=(
                        f"locomo://{sample.get('sample_id')}/{session_name}"
                    ),
                    ns=QUALIFICATION_NAMESPACE,
                    scope=QUALIFICATION_SCOPE,
                )
            probes = runtime.store.generate_graph_probes(
                namespace=QUALIFICATION_NAMESPACE,
                scope=QUALIFICATION_SCOPE,
                sample=probe_sample,
                seed=1234,
            )
            if not probes:
                raise RuntimeError("real corpus produced no graph probes")
            development_probes, holdout_probes = _stratified_split(probes)
            if not development_probes or not holdout_probes:
                raise RuntimeError(
                    "real corpus needs non-empty development and holdout probes"
                )
            scorer = GraphProbeScorer(
                development_probes,
                holdout_probes,
                namespace=QUALIFICATION_NAMESPACE,
                scope=QUALIFICATION_SCOPE,
            )
            baseline = RetrievalFlags()
            baseline_report = scorer.score(runtime, baseline)
            baseline_holdout = scorer._score(
                runtime,
                holdout_probes,
                baseline,
                name="graph_probe_holdout",
            )
            candidate_results = []
            for seed_count in GRAPH_SEED_CANDIDATES:
                flags = RetrievalFlags(
                    graph_semantic_seeds=seed_count,
                    graph_semantic_min_score=0.0,
                )
                development_report = scorer.score(runtime, flags)
                holdout_report = scorer._score(
                    runtime,
                    holdout_probes,
                    flags,
                    name="graph_probe_holdout",
                )
                candidate_results.append(
                    {
                        "flags": flags,
                        "development": development_report,
                        "holdout": holdout_report,
                        "development_safe": _no_regression(
                            development_report, baseline_report
                        ),
                        "holdout_safe": _no_regression(
                            holdout_report, baseline_holdout
                        ),
                    }
                )
            safe_candidates = [
                result
                for result in candidate_results
                if result["development_safe"] and result["holdout_safe"]
            ]
            selected = max(
                safe_candidates,
                key=lambda result: result["development"].aggregate,
                default=None,
            )
            selected_improvement = (
                selected
                if selected is not None
                and selected["development"].aggregate
                > baseline_report.aggregate + NOISE_MARGIN
                else None
            )
            trace_candidate = selected or min(
                candidate_results,
                key=lambda result: result["flags"].graph_semantic_seeds,
            )
            candidate = trace_candidate["flags"]

            runtime._retrieval_flags = candidate
            orchestrator = RetrievalOrchestrator(runtime)
            traced = 0
            trace_queries = probes[: min(25, len(probes))]
            for probe in trace_queries:
                result = orchestrator.decide(
                    probe.query,
                    namespace=QUALIFICATION_NAMESPACE,
                    scope=QUALIFICATION_SCOPE,
                    budget=20,
                    mode="mix",
                    graph_hops=3,
                    semantic_graph_seeding=True,
                    candidate_trace_limit=64,
                )
                if any(
                    "graph_node" in candidate_row.sources
                    for candidate_row in result.ranked
                ):
                    traced += 1
            model_name = (
                getattr(runtime.embedding_model, "name", "")
                or runtime.embedding_model.__class__.__name__
            )
            vector_status = runtime.store.node_vector_status(model_name)
            trace_rate = traced / len(trace_queries)
            decision = (
                "propose"
                if selected_improvement is not None
                else "no_change"
            )

            def report_view(result):
                flags = result["flags"]
                development = result["development"]
                holdout = result["holdout"]
                return {
                    "graph_semantic_seeds": flags.graph_semantic_seeds,
                    "graph_semantic_min_score": flags.graph_semantic_min_score,
                    "development": {
                        "aggregate": development.aggregate,
                        "per_motif": development.per_category,
                        "delta": (
                            development.aggregate
                            - baseline_report.aggregate
                        ),
                    },
                    "holdout": {
                        "aggregate": holdout.aggregate,
                        "per_motif": holdout.per_category,
                        "delta": (
                            holdout.aggregate
                            - baseline_holdout.aggregate
                        ),
                    },
                    "development_safe": result["development_safe"],
                    "holdout_safe": result["holdout_safe"],
                }

            checks = {
                "node_vector_coverage": vector_status["coverage"] == 1.0,
                "unsafe_candidates_excluded": (
                    selected_improvement is None
                    or (
                        selected_improvement["development_safe"]
                        and selected_improvement["holdout_safe"]
                    )
                ),
                "selected_from_safe_pool": (
                    selected_improvement is None
                    or selected_improvement in safe_candidates
                ),
                "graph_node_leg_observed": trace_rate > 0.0,
            }
            return {
                "schema": QUALIFICATION_SCHEMA,
                "dataset": {
                    "path": str(dataset_path),
                    "sha256": actual_sha256,
                    "sample_id": sample.get("sample_id"),
                    "sessions": [name for name, _turns in selected_sessions],
                },
                "embedding_model": model_name,
                "provider_calls": 0,
                "probe_count": len(probes),
                "development_probe_count": len(development_probes),
                "holdout_probe_count": len(holdout_probes),
                "motifs": sorted({probe.motif for probe in probes}),
                "baseline": {
                    "development": {
                        "aggregate": baseline_report.aggregate,
                        "per_motif": baseline_report.per_category,
                    },
                    "holdout": {
                        "aggregate": baseline_holdout.aggregate,
                        "per_motif": baseline_holdout.per_category,
                    },
                },
                "candidates": [
                    report_view(result) for result in candidate_results
                ],
                "decision": decision,
                "selected": (
                    report_view(selected_improvement)
                    if selected_improvement is not None
                    else None
                ),
                "traced_candidate": report_view(trace_candidate),
                "node_vectors": vector_status,
                "graph_node_trace_rate": trace_rate,
                "checks": checks,
                "passed": all(checks.values()),
            }
        finally:
            runtime.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--sample-index", type=int, default=0)
    parser.add_argument("--sessions", type=int, default=2)
    parser.add_argument("--probe-sample", type=int, default=100)
    parser.add_argument(
        "--embedding-model",
        default=None,
        help=(
            "Optional cached sentence-transformers model. Omit for the "
            "provider-free hash baseline."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = qualify_real_corpus(
        dataset_path=args.dataset,
        manifest_path=args.manifest,
        sample_index=args.sample_index,
        sessions=args.sessions,
        probe_sample=args.probe_sample,
        embedding_model=args.embedding_model,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
