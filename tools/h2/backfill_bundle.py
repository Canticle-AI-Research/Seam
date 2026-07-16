"""H2 slice 3: backfill retrieval_event rows from existing benchmark bundles.

Existing LoCoMo result bundles (under ``benchmarks/runs/`` and operator-local
publication directories) carry per-case ``context_recall``, optional judge
verdicts, and optional ``retrieved_context`` (when the run used
``--save-context``). They do NOT carry the question text, the gold answer,
or the candidate IDs/scores from search.

This tool reconstructs as much of the H2 retrieval_event row as the bundle
preserves:

* ``query`` and ``gold_answer`` are recovered by joining the bundle's
  ``case_id`` against the source dataset (auto-resolves the literal string
  ``"quickstart"`` to the bundled quickstart fixture; otherwise pass
  ``--source PATH``).
* ``candidate_ids`` is empty because bundles do not store per-candidate
  record IDs; ``ranks``/``scores``/``reasons`` are likewise null.
* ``context_recall``/``judge_score`` come from the bundle if present.
* ``context_hash`` is computed from ``retrieved_context`` when the bundle
  was produced with ``--save-context``.
* ``answer`` falls back to ``answerer_diagnostics.content_preview`` (the
  first 120 chars the answerer emitted) because the full prediction is
  popped before bundle serialization.

All rows are written with ``source_kind="backfill"`` and
``stale_source=True`` by default: backfilled rows are reconstructed
post-hoc and must never be confused with live retrieval events. Pass
``--no-stale`` to override when you know the bundle was produced after the
ranking/loader fixes in HISTORY#242 and want fresh-equivalent rows.

Per the H2 protocol gate in ROADMAP.md L1282-1287, scoring-weight tuning is
blocked on this substrate; rows produced here are the historical evidence
that feeds slice 4 (dev/holdout split) and slice 5 (improvement review).

CLI::

    python -m tools.h2.backfill_bundle \\
        --bundle benchmarks/runs/locomo_quickstart_2026XXXX.json \\
        --source quickstart \\
        --db /tmp/h2.db

    python -m tools.h2.backfill_bundle \\
        --bundle one.json --bundle two.json \\
        --source /path/to/locomo.json \\
        --db ~/.seam/h2.db
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from benchmarks.external.common.dataset import load_locomo_cases, load_quickstart_cases
from benchmarks.external.common.types import BenchmarkCase
from seam_runtime.storage import SQLiteStore

_QUICKSTART_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "benchmarks"
    / "external"
    / "locomo"
    / "fixtures"
    / "quickstart.json"
)


@dataclass(frozen=True)
class BackfillSummary:
    bundle_path: Path
    run_id: str
    cases_in_bundle: int
    events_written: int
    cases_skipped_no_match: int
    cases_skipped_invalid: int


def load_source_cases(source: str | Path) -> list[BenchmarkCase]:
    """Resolve a ``--source`` value into a list of BenchmarkCase.

    ``"quickstart"`` (case-insensitive) resolves to the bundled fixture.
    Anything else is treated as a path to a LoCoMo JSON file.
    """
    if isinstance(source, str) and source.lower() == "quickstart":
        return load_quickstart_cases()
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"source dataset not found: {path}")
    return load_locomo_cases(path)


def build_case_index(cases: Iterable[BenchmarkCase]) -> dict[str, BenchmarkCase]:
    """Index cases by ``case_id`` for quick join against bundle entries."""
    return {case.case_id: case for case in cases}


def _scope_from_case_id(case_id: str) -> str | None:
    """Derive the conversation scope from a LoCoMo case_id.

    Case IDs are ``{sample_id}::q{index}``; the scope is ``locomo:{sample_id}``.
    Returns None for malformed case_ids so the writer can fall back to the
    bundle-level adapter scope.
    """
    match = re.match(r"^(?P<sample>[^:]+(?:[^:]|:(?!:))*?)::q\d+$", case_id)
    if not match:
        return None
    return f"locomo:{match.group('sample')}"


def derive_run_id(bundle: dict, bundle_path: Path) -> str:
    """Stable, descriptive run_id when the operator did not override one.

    Prefers a sortable timestamp + adapter from the bundle; falls back to the
    bundle filename stem.
    """
    started = bundle.get("run_started_at") or ""
    adapter = bundle.get("adapter") or bundle.get("benchmark") or "unknown"
    if started:
        # Compact ISO without separators so it sorts and stays SQL-safe.
        compact = re.sub(r"[^0-9A-Za-z]", "", started)[:16] or "unknown"
        return f"backfill-{adapter}-{compact}"
    return f"backfill-{adapter}-{bundle_path.stem}"


def backfill_bundle(
    *,
    bundle_path: Path,
    source: str | Path,
    store: SQLiteStore,
    run_id: str | None = None,
    stale: bool = True,
) -> BackfillSummary:
    """Read one bundle, write one retrieval_event per scored case.

    Cases whose ``case_id`` does not appear in the source dataset are
    skipped (logged in the returned summary). The bundle is not modified.
    """
    bundle_path = Path(bundle_path)
    with bundle_path.open("r", encoding="utf-8") as fh:
        bundle = json.load(fh)

    cases = bundle.get("cases") or []
    case_index = build_case_index(load_source_cases(source))

    resolved_run_id = run_id or derive_run_id(bundle, bundle_path)
    adapter_label = str(bundle.get("adapter") or "unknown")
    bundle_basename = bundle_path.name

    written = 0
    skipped_no_match = 0
    skipped_invalid = 0

    for case in cases:
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            skipped_invalid += 1
            continue
        source_case = case_index.get(case_id)
        if source_case is None:
            skipped_no_match += 1
            continue

        scores = case.get("scores") or {}
        context_recall = _coerce_float(scores.get("context_recall"))
        judge = case.get("judge") if isinstance(case.get("judge"), dict) else None
        judge_score = _coerce_float(judge.get("score")) if judge else None

        retrieved_context = case.get("retrieved_context")
        context_hash = (
            hashlib.sha256(retrieved_context.encode("utf-8")).hexdigest()
            if isinstance(retrieved_context, str) and retrieved_context
            else None
        )

        # Bundles pop the full _prediction before serialization; the answerer
        # diagnostics preview (first 120 chars) is the closest available proxy.
        diag = case.get("answerer_diagnostics") if isinstance(case.get("answerer_diagnostics"), dict) else None
        answer_preview = diag.get("content_preview") if diag else None
        answer = answer_preview if isinstance(answer_preview, str) and answer_preview else None

        scope = _scope_from_case_id(case_id) or f"locomo:{adapter_label}"

        extra: dict = {
            "bundle_path": str(bundle_path),
            "category": case.get("category"),
            "scores": {
                "answer_em": scores.get("answer_em"),
                "answer_f1": scores.get("answer_f1"),
            },
            "retrieval_latency_ms": case.get("retrieval_latency_ms"),
            "answer_latency_ms": case.get("answer_latency_ms"),
        }
        if judge:
            extra["judge"] = {
                k: judge.get(k)
                for k in ("verdict", "rationale", "judge_name", "judge_model")
                if judge.get(k) is not None
            }
        if diag:
            extra["answerer_diagnostics"] = diag

        store.write_retrieval_event(
            run_id=resolved_run_id,
            scope=scope,
            query=source_case.question,
            candidate_ids=[],
            context_hash=context_hash,
            gold_answer=source_case.gold_answer,
            context_recall=context_recall,
            judge_score=judge_score,
            answer=answer,
            source_kind="backfill",
            source_ref=f"bundle:{bundle_basename}::{case_id}",
            stale_source=stale,
            extra=extra,
        )
        written += 1

    return BackfillSummary(
        bundle_path=bundle_path,
        run_id=resolved_run_id,
        cases_in_bundle=len(cases),
        events_written=written,
        cases_skipped_no_match=skipped_no_match,
        cases_skipped_invalid=skipped_invalid,
    )


def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_summary(summary: BackfillSummary) -> str:
    parts = [
        f"{summary.bundle_path.name}",
        f"run_id={summary.run_id}",
        f"events_written={summary.events_written}/{summary.cases_in_bundle}",
    ]
    if summary.cases_skipped_no_match:
        parts.append(f"no_match={summary.cases_skipped_no_match}")
    if summary.cases_skipped_invalid:
        parts.append(f"invalid={summary.cases_skipped_invalid}")
    return " | ".join(parts)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tools.h2.backfill_bundle",
        description=(
            "Backfill H2 retrieval_event rows from existing LoCoMo result "
            "bundles. Rows are written with source_kind='backfill' and "
            "stale_source=True by default."
        ),
    )
    parser.add_argument(
        "--bundle",
        action="append",
        required=True,
        metavar="PATH",
        help="Result bundle JSON. Repeatable.",
    )
    parser.add_argument(
        "--source",
        required=True,
        help=(
            "Source dataset for question/gold lookup. Use 'quickstart' for the "
            "bundled fixture, otherwise a path to a LoCoMo JSON file."
        ),
    )
    parser.add_argument(
        "--db",
        required=True,
        help="SQLite path that receives retrieval_event rows.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help=(
            "Override the run_id used for all events written from these "
            "bundles. Default: derived per-bundle from run_started_at + adapter."
        ),
    )
    parser.add_argument(
        "--no-stale",
        action="store_true",
        help=(
            "Write rows with stale_source=False. Only use when the bundle was "
            "produced after the post-HISTORY#242 ranking/loader fixes."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = SQLiteStore(Path(args.db))
    total_written = 0
    for bundle_path in args.bundle:
        summary = backfill_bundle(
            bundle_path=Path(bundle_path),
            source=args.source,
            store=store,
            run_id=args.run_id,
            stale=not args.no_stale,
        )
        print(_format_summary(summary))
        total_written += summary.events_written
    print(f"total events written: {total_written}")
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI shim
    sys.exit(main())
