"""LoCoMo benchmark runner for SEAM.

Usage:
    python -m benchmarks.external.locomo.run --quickstart
    python -m benchmarks.external.locomo.run --dataset-path /path/to/locomo.json --dry-run
    python -m benchmarks.external.locomo.run --dataset-path /path/to/locomo.json --output run.json
    python -m benchmarks.external.locomo.run --dataset-path /path/to/locomo.json --limit 20 --adapter seam

When --quickstart is passed, loads the quickstart fixture and runs with the SEAM adapter.
When --dataset-path is passed, loads from the given path.
--dry-run validates the dataset and prints counts without executing the judge or adapter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path

from benchmarks.external.common.dataset import load_locomo_cases, load_quickstart_cases
from benchmarks.external.common.judge import build_judge
from benchmarks.external.common.runner import (
    run_benchmark_grouped,
    run_benchmark_grouped_parallel,
)


def build_adapter(
    name: str,
    answerer: str | None = None,
    answerer_model: str | None = None,
    decomposer: str | None = None,
    decomposer_model: str | None = None,
    decomposer_max_subq: int = 3,
    abstain_threshold: float = 0.0,
    rerank: str | None = None,
    keep_db: bool = False,
    db_path: str | None = None,
    context_budget: int = 8000,  # HISTORY#320 measured knee (was 2000, starved)
    search_top_k: int = 100,     # HISTORY#320 measured knee (was 20, starved)
    rerank_top_k: int = 20,
    semantic_recovery_mode: str = "baseline",
    record_retrieval_events: bool | None = None,
    retrieval_event_run_id: str | None = None,
):
    """Lazy-import factory so SEAM-only runs don't require Mem0/Zep installed."""
    if name == "seam":
        from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter

        return SeamLocomoAdapter(
            db_path=db_path,
            answerer=answerer, answerer_model=answerer_model,
            decomposer=decomposer, decomposer_model=decomposer_model,
            decomposer_max_subq=decomposer_max_subq,
            abstain_threshold=abstain_threshold,
            rerank=rerank,
            budget=context_budget,
            search_top_k=search_top_k,
            rerank_top_k=rerank_top_k,
            semantic_recovery_mode=semantic_recovery_mode,
            keep_db=keep_db,
            record_retrieval_events=record_retrieval_events,
            run_id=retrieval_event_run_id,
        )
    if name == "mem0":
        from benchmarks.external.locomo.adapters.mem0 import Mem0LocomoAdapter

        return _maybe_wrap_answerer(Mem0LocomoAdapter(), answerer, answerer_model)
    if name == "zep":
        from benchmarks.external.locomo.adapters.zep import ZepLocomoAdapter

        return _maybe_wrap_answerer(ZepLocomoAdapter(), answerer, answerer_model)
    raise ValueError(f"unknown adapter {name!r}")


def _maybe_wrap_answerer(inner, answerer: str | None, answerer_model: str | None):
    """Comparator adapters (mem0/zep) return only retrieved context. When an
    answerer is configured, wrap them so the SAME answerer generates their
    answer from that context -- otherwise the runner judges them on an empty
    prediction (~0) and the head-to-head is not fair. The SEAM adapter is not
    wrapped: it generates its own answer through the same shared prompt."""
    if answerer is None:
        return inner
    from benchmarks.external.common.answerer import SharedAnswererAdapter

    return SharedAnswererAdapter(inner, answerer, answerer_model)


def _fixture_hash(cases) -> str:
    """Deterministic hash of the case definitions (questions + gold answers)."""
    payload = json.dumps(
        [{"case_id": c.case_id, "question": c.question, "gold_answer": c.gold_answer, "category": c.category}
         for c in cases],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dry_run_report(cases, dataset_path, judge_name):
    """Print case counts, category breakdown, and fixture hash without running anything."""
    category_counts = Counter(c.category for c in cases)
    report = {
        "dataset_path": str(dataset_path),
        "case_count": len(cases),
        "categories": dict(category_counts),
        "fixture_hash": _fixture_hash(cases),
        "estimated_judge_calls": len(cases) if judge_name and judge_name not in ("none", "stub") else 0,
        "judge": judge_name or "none",
        "mode": "dry-run",
    }
    return report


LOCOMO_NAMED_CATEGORIES = {"single-hop", "multi-hop", "open-domain", "temporal"}


def _validate_locomo_categories(cases) -> list[str]:
    """Validate LoCoMo category coverage. Synthetic fixtures may use numeric
    categories; full LoCoMo releases use the four named categories. The
    validator warns when named categories are missing but only fails when
    zero categories are found."""
    issues = []
    cats_present = {c.category for c in cases if c.category is not None}
    if len(cases) == 0:
        issues.append("No cases found in dataset")
        return issues
    if not cats_present:
        issues.append("No categories found in any case")
        return issues
    named_present = cats_present & LOCOMO_NAMED_CATEGORIES
    numeric_present = {c for c in cats_present if str(c).isdigit()}
    if named_present and len(named_present) < 4:
        issues.append(
            f"Only {len(named_present)}/4 named LoCoMo categories present: {sorted(named_present)}. "
            f"Missing: {sorted(LOCOMO_NAMED_CATEGORIES - named_present)}"
        )
    elif not named_present and not numeric_present:
        issues.append(
            f"Categories present ({sorted(cats_present)}) are neither named LoCoMo categories "
            f"nor numeric synthetic IDs"
        )
    return issues


def _locomo_scope_id(case) -> str:
    return case.case_id.split("::", 1)[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="LoCoMo benchmark runner for SEAM")
    parser.add_argument(
        "--quickstart",
        action="store_true",
        help="Use the bundled quickstart fixture",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=None,
        help="Path to a LoCoMo JSON file (deprecated alias for --dataset-path)",
    )
    parser.add_argument(
        "--dataset-path",
        type=str,
        default=None,
        help="Path to a LoCoMo JSON file",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Write JSON report to this path (prints to stdout if omitted)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of cases",
    )
    parser.add_argument(
        "--adapter",
        choices=["seam", "mem0", "zep"],
        default="seam",
        help="Which adapter to use (default: seam)",
    )
    parser.add_argument(
        "--judge",
        default=None,
        choices=["none", "stub", "claude", "openai"],
        help="LLM judge in addition to string-match scoring",
    )
    parser.add_argument(
        "--judge-model",
        default=None,
        help="Override the default judge model id",
    )
    parser.add_argument(
        "--judge-batch",
        action="store_true",
        help=(
            "Submit judge (and cross-judge) calls via the provider's Batch API "
            "(50%% discount, up to 24h async SLA). Recommended for full runs only; "
            "leave off for interactive/quickstart runs."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate dataset and print counts without executing the benchmark",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of independent case workers for full runs",
    )
    parser.add_argument(
        "--answerer",
        choices=["none", "openai", "claude"],
        default="none",
        help="Generate a short answer from retrieved context (default: none)",
    )
    parser.add_argument(
        "--answerer-model",
        default=None,
        help="Override the default answerer model id",
    )
    parser.add_argument(
        "--judge-cross",
        choices=["none", "stub", "openai", "claude"],
        default="none",
        help="Optional second judge for cross-check (default: none)",
    )
    parser.add_argument(
        "--judge-cross-model",
        default=None,
        help="Override the default cross-check judge model id",
    )
    parser.add_argument(
        "--decomposer",
        choices=["none", "openai", "claude"],
        default="none",
        help="Decompose multi-hop questions into sub-questions (default: none)",
    )
    parser.add_argument(
        "--decomposer-model",
        default=None,
        help="Override the default decomposer model id",
    )
    parser.add_argument(
        "--decomposer-max-subq",
        type=int,
        default=3,
        help="Max sub-questions for decomposition (default: 3)",
    )
    parser.add_argument(
        "--abstain-threshold",
        type=float,
        default=0.0,
        help="Abstain threshold: emit 'unknown' when top score is below this value (default: 0.0)",
    )
    parser.add_argument(
        "--rerank",
        choices=["none", "cross-encoder"],
        default="none",
        help="Re-rank top-K bi-encoder results with a cross-encoder (default: none)",
    )
    parser.add_argument(
        "--save-context",
        action="store_true",
        help="Include per-case retrieved_context in the JSON report for diagnostics",
    )
    parser.add_argument(
        "--keep-db",
        action="store_true",
        help="(seam adapter) Reuse the per-scope SQLite databases between runs instead of deleting on reset. After the first ingest, subsequent runs skip re-ingest and just exercise retrieval/scoring. Use this for tight inner-loop iteration on retrieval/answerer changes.",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="(seam adapter) Directory for per-scope SQLite databases. Default: test_seam/locomo. Use with --keep-db to isolate a benchmark slice from other DBs.",
    )
    parser.add_argument(
        "--semantic-recovery-mode",
        choices=["baseline", "pack-budget", "deep-candidates", "pack-budget-deep"],
        default="baseline",
        help="(seam adapter) Label for default-off semantic recovery experiments. Baseline preserves existing defaults; other modes are explicit measurement labels.",
    )
    parser.add_argument(
        "--context-budget",
        type=int,
        default=8000,
        help="(seam adapter) Character budget for retrieved evidence context (default: 8000, the HISTORY#320 measured knee; was 2000).",
    )
    parser.add_argument(
        "--search-top-k",
        type=int,
        default=100,
        help="(seam adapter) Candidate count requested from search_ir before evidence closure (default: 100, the HISTORY#320 measured knee; was 20).",
    )
    parser.add_argument(
        "--rerank-top-k",
        type=int,
        default=20,
        help="(seam adapter) Candidate count re-ranked when --rerank cross-encoder is enabled (default: 20).",
    )
    parser.add_argument(
        "--record-retrieval-events",
        action="store_true",
        help="(seam adapter) Append retrieval_event rows while answering cases. Default off unless SEAM_RECORD_RETRIEVAL_EVENTS is truthy.",
    )
    parser.add_argument(
        "--retrieval-event-run-id",
        type=str,
        default=None,
        help="(seam adapter) Run id for retrieval_event rows. Default: SEAM_RUN_ID or an auto-generated id.",
    )
    args = parser.parse_args()

    dataset_path = args.dataset_path or args.dataset

    if not args.quickstart and not dataset_path:
        parser.error("Either --quickstart or --dataset-path is required.")
    if args.quickstart and dataset_path:
        parser.error("Cannot specify both --quickstart and --dataset-path.")

    # Load cases
    if args.quickstart:
        cases = load_quickstart_cases()
        source = "quickstart"
    else:
        if not Path(dataset_path).exists():
            print(f"ERROR: dataset not found: {dataset_path}", file=sys.stderr)
            raise SystemExit(1)
        cases = load_locomo_cases(dataset_path)
        source = str(dataset_path)

    # Apply limit
    if args.limit is not None:
        cases = cases[: args.limit]

    # Dry-run mode: validate and report, no execution
    if args.dry_run:
        issues = _validate_locomo_categories(cases)
        report = _dry_run_report(cases, source, args.judge)
        report["validation_issues"] = issues
        report["valid"] = len(issues) == 0
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if report["valid"] else 1)

    answerer = None if args.answerer == "none" else args.answerer
    decomposer = None if args.decomposer == "none" else args.decomposer
    rerank = None if args.rerank == "none" else args.rerank
    judge_cross = build_judge(args.judge_cross, model=args.judge_cross_model) if args.judge_cross != "none" else None

    # Durable result destination resolved BEFORE the run so partial checkpoints
    # and the final bundle share one stable name. A long run that crashes leaves
    # a recoverable <stem>.partial.json on persistent disk (never /tmp).
    archive_dir = _resolve_archive_dir()
    archive_dir.mkdir(parents=True, exist_ok=True)
    run_stem = _run_stem(args, len(cases))
    partial_path = archive_dir / f"{run_stem}.partial.json"

    def _checkpoint(case_results: list[dict], completed: int, total: int) -> None:
        # A flush failure must never crash the run it is protecting.
        try:
            payload = json.dumps(
                {"status": "PARTIAL", "completed": completed, "total": total, "case_results": case_results},
                indent=2, default=str,
            )
            _atomic_write(partial_path, payload)
            print(f"[checkpoint] {completed}/{total} cases flushed to {partial_path}", file=sys.stderr)
        except Exception as exc:
            print(f"WARNING: checkpoint flush failed at {completed}/{total}: {exc!r}", file=sys.stderr)

    # Run benchmark
    if args.workers > 1:
        report = run_benchmark_grouped_parallel(
            adapter_factory=lambda: build_adapter(
                args.adapter, answerer=answerer, answerer_model=args.answerer_model,
                decomposer=decomposer, decomposer_model=args.decomposer_model,
                decomposer_max_subq=args.decomposer_max_subq,
                abstain_threshold=args.abstain_threshold,
                rerank=rerank,
                keep_db=args.keep_db,
                db_path=args.db_path,
                context_budget=args.context_budget,
                search_top_k=args.search_top_k,
                rerank_top_k=args.rerank_top_k,
                semantic_recovery_mode=args.semantic_recovery_mode,
                record_retrieval_events=args.record_retrieval_events,
                retrieval_event_run_id=args.retrieval_event_run_id,
            ),
            adapter_name=args.adapter,
            cases=cases,
            scope_id=_locomo_scope_id,
            dataset_source=source,
            judge_factory=(
                lambda: build_judge(args.judge, model=args.judge_model)
                if args.judge is not None else None
            ),
            judge_cross=judge_cross,
            judge_batch=args.judge_batch,
            workers=args.workers,
            save_context=args.save_context,
            checkpoint=_checkpoint,
        )
    else:
        adapter = build_adapter(
            args.adapter, answerer=answerer, answerer_model=args.answerer_model,
            decomposer=decomposer, decomposer_model=args.decomposer_model,
            decomposer_max_subq=args.decomposer_max_subq,
            abstain_threshold=args.abstain_threshold,
            rerank=rerank,
            keep_db=args.keep_db,
            db_path=args.db_path,
            context_budget=args.context_budget,
            search_top_k=args.search_top_k,
            rerank_top_k=args.rerank_top_k,
            semantic_recovery_mode=args.semantic_recovery_mode,
            record_retrieval_events=args.record_retrieval_events,
            retrieval_event_run_id=args.retrieval_event_run_id,
        )
        judge = build_judge(args.judge, model=args.judge_model)
        report = run_benchmark_grouped(
            adapter=adapter,
            cases=cases,
            scope_id=_locomo_scope_id,
            dataset_source=source,
            judge=judge,
            judge_cross=judge_cross,
            judge_batch=args.judge_batch,
            save_context=args.save_context,
            checkpoint=_checkpoint,
        )

    # Output
    report_json = json.dumps(report, indent=2, default=str)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report_json)
            f.write("\n")
        print(f"Report written to {args.output}")
        if _is_ephemeral_path(args.output):
            print(
                f"WARNING: {args.output} is under a temp directory and will not survive a reboot.",
                file=sys.stderr,
            )
    else:
        print(report_json)

    # Always archive a durable copy so result bundles are never lost to /tmp.
    # Atomic write + fsync + verified read-back, then drop the partial.
    # Emit on stderr so stdout stays pure JSON when --output is not given.
    try:
        archive_path = archive_dir / f"{run_stem}.json"
        _atomic_write(archive_path, report_json + "\n")
        _verify_saved(archive_path, report_json + "\n")
        if partial_path.exists():
            partial_path.unlink()
        print(f"Durable copy archived (verified) to {archive_path}", file=sys.stderr)
    except Exception as exc:  # archiving must never fail a completed run
        kept = partial_path if partial_path.exists() else "(no partial)"
        print(
            f"WARNING: could not archive durable result copy: {exc!r}. "
            f"Last checkpoint retained at {kept}.",
            file=sys.stderr,
        )


def _is_ephemeral_path(path: str) -> bool:
    # Check both the resolved path (catches this OS's real temp dir) and the raw
    # path with normalized separators (catches POSIX /tmp literals on any OS;
    # on Windows Path("/tmp").resolve() becomes "C:\\tmp" and never matches).
    resolved = str(Path(path).resolve())
    raw = path.replace("\\", "/")
    tmp_roots = [str(Path(tempfile.gettempdir()).resolve()), "/tmp", "/var/tmp", "/dev/shm"]

    def _under(value: str, root: str) -> bool:
        return value == root or value.startswith(root + "/") or value.startswith(root + os.sep)

    return any(_under(resolved, root) or _under(raw, root) for root in tmp_roots)


def _resolve_archive_dir() -> Path:
    """Durable result directory. Defaults to ``<repo>/benchmarks/runs/locomo/``
    (persistent storage, never /tmp). Override with ``SEAM_BENCH_RESULTS_DIR``."""
    env_dir = os.environ.get("SEAM_BENCH_RESULTS_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    return Path(__file__).resolve().parents[2] / "runs" / "locomo"


def _run_stem(args: argparse.Namespace, n_cases: int) -> str:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    adapter = getattr(args, "adapter", "seam") or "seam"
    judge = getattr(args, "judge", None)
    parts = [timestamp, str(adapter), f"{n_cases}cases"]
    if judge:
        parts.append(f"judge-{judge}")
    if getattr(args, "quickstart", False):
        parts.append("quickstart")
    return "_".join(parts)


def _atomic_write(path: Path, text: str) -> None:
    """Write durably: temp file in the same dir, fsync, then atomic os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    # fsync the directory entry so the rename itself is durable across crashes.
    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def _verify_saved(path: Path, expected: str) -> None:
    """Read the file back and confirm it is intact, so a 'saved' claim is real."""
    if not path.exists():
        raise RuntimeError(f"archive file missing after write: {path}")
    actual = path.read_text(encoding="utf-8")
    if actual != expected:
        raise RuntimeError(f"archive read-back mismatch at {path} ({len(actual)} vs {len(expected)} bytes)")


if __name__ == "__main__":
    main()
