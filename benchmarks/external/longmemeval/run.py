"""LongMemEval benchmark runner for SEAM.

LongMemEval evaluates 500 questions across five core memory abilities. The
official data encodes six ``question_type`` values; abstention is a cross-cutting
ability marked by ``question_id`` suffixes rather than a seventh type.

Usage:
    python -m benchmarks.external.longmemeval.run --dataset-path /path/to/longmemeval.json --dry-run
    python -m benchmarks.external.longmemeval.run --dataset-path /path/to/longmemeval.json \
        --harness-root /path/to/memory-benchmarks --project-name seam-lme \
        --mem0-host http://127.0.0.1:8900 --predict-only

The full dataset is not bundled; point --dataset-path at a local LongMemEval release.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from benchmarks.external.common.types import BenchmarkCase, ConversationTurn
from benchmarks.external.mem0_harness.upstream_runner import (
    execute_upstream_plan,
    plan_upstream_run,
    render_plan,
)

EXPECTED_QUESTION_TYPES = [
    "single-session-user",
    "single-session-assistant",
    "single-session-preference",
    "multi-session",
    "knowledge-update",
    "temporal-reasoning",
]
EXPECTED_TOTAL_QUESTIONS = 500


def _load_longmemeval_cases(dataset_path: str) -> list[BenchmarkCase]:
    """Parse a LongMemEval JSON dataset into case dicts.

    Supports the official cleaned LongMemEval release shape:
      {"question_id": str, "question_type": str, "question": str, "answer": str,
       "haystack_dates": [str], "haystack_sessions": [[{"role": str, "content": str}]]}

    Also supports the earlier local synthetic shape:
      {"sample_id": str, "conversation": [{"speaker": str, "text": str, ...}],
       "qa": [{"question": str, "gold_answer": str, "category": str}]}
    """
    with open(dataset_path, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    if not isinstance(raw, list):
        raise ValueError("LongMemEval dataset root must be a JSON list")
    cases: list[BenchmarkCase] = []
    seen_ids: set[str] = set()
    for index, sample in enumerate(raw):
        if not isinstance(sample, dict):
            raise ValueError(f"LongMemEval row {index} must be an object")
        if "question_id" in sample and "haystack_sessions" in sample:
            case = _official_case(sample, index)
            if case.case_id in seen_ids:
                raise ValueError(f"duplicate LongMemEval question_id: {case.case_id}")
            seen_ids.add(case.case_id)
            cases.append(case)
            continue

        sid = sample["sample_id"]
        conversation = tuple(
            ConversationTurn(
                speaker=str(turn.get("speaker", turn.get("role", ""))),
                text=str(turn.get("text", turn.get("content", ""))),
                timestamp=turn.get("timestamp"),
            )
            for turn in sample.get("conversation", [])
        )
        for qi, qa in enumerate(sample.get("qa", [])):
            case_id = f"{sid}::q{qi}"
            if case_id in seen_ids:
                raise ValueError(f"duplicate LongMemEval case id: {case_id}")
            seen_ids.add(case_id)
            cases.append(
                BenchmarkCase(
                    case_id=case_id,
                    question=str(qa["question"]),
                    gold_answer=str(qa.get("answer", qa.get("gold_answer", ""))),
                    category=str(qa.get("category", "unknown")),
                    conversation=conversation,
                    metadata={"dataset_format": "synthetic-legacy"},
                )
            )
    return cases


def _official_case(sample: dict, index: int) -> BenchmarkCase:
    question_id = str(sample.get("question_id", f"longmemeval-{index}"))
    question = str(sample.get("question", "")).strip()
    answer = str(sample.get("answer", "")).strip()
    question_type = str(sample.get("question_type", "unknown"))
    sessions = sample.get("haystack_sessions", [])
    dates = sample.get("haystack_dates", [])
    session_ids = sample.get("haystack_session_ids", [])
    if not question:
        raise ValueError(f"LongMemEval {question_id} has an empty question")
    if not isinstance(sessions, list) or not sessions:
        raise ValueError(f"LongMemEval {question_id} has no haystack sessions")
    if not isinstance(dates, list) or len(dates) != len(sessions):
        raise ValueError(
            f"LongMemEval {question_id} haystack_dates/session count mismatch"
        )
    if session_ids and (
        not isinstance(session_ids, list) or len(session_ids) != len(sessions)
    ):
        raise ValueError(
            f"LongMemEval {question_id} haystack_session_ids/session count mismatch"
        )

    turns: list[ConversationTurn] = []
    for session_index, session in enumerate(sessions):
        if not isinstance(session, list) or not session:
            raise ValueError(
                f"LongMemEval {question_id} session {session_index} is empty or malformed"
            )
        timestamp = str(dates[session_index])
        for turn in session:
            if not isinstance(turn, dict):
                raise ValueError(
                    f"LongMemEval {question_id} session {session_index} has a malformed turn"
                )
            role = str(turn.get("role", turn.get("speaker", ""))).strip()
            content = str(turn.get("content", turn.get("text", ""))).strip()
            if role not in {"user", "assistant"} or not content:
                raise ValueError(
                    f"LongMemEval {question_id} contains an invalid role/content pair"
                )
            turns.append(
                ConversationTurn(
                    speaker=role,
                    text=content,
                    timestamp=timestamp,
                )
            )
    return BenchmarkCase(
        case_id=question_id,
        question=question,
        gold_answer=answer,
        category=question_type,
        conversation=tuple(turns),
        metadata={
            "dataset_format": "official-cleaned",
            "question_date": sample.get("question_date"),
            "is_abstention": question_id.endswith("_abs"),
            "haystack_session_ids": tuple(str(value) for value in session_ids),
            "answer_session_ids": tuple(
                str(value) for value in sample.get("answer_session_ids", [])
            ),
        },
    )


def _fixture_hash(cases) -> str:
    payload = json.dumps(
        [
            {
                "case_id": case.case_id,
                "question": case.question,
                "gold_answer": case.gold_answer,
                "category": case.category,
                "conversation": [
                    {
                        "speaker": turn.speaker,
                        "text": turn.text,
                        "timestamp": turn.timestamp,
                    }
                    for turn in case.conversation
                ],
                "metadata": case.metadata,
            }
            for case in cases
        ],
        sort_keys=True,
        default=list,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dry_run_report(cases, dataset_path, judge_name):
    category_counts = Counter(c.category for c in cases)
    present_cats = set(category_counts.keys())
    missing_cats = [c for c in EXPECTED_QUESTION_TYPES if c not in present_cats]
    issues = []
    if missing_cats:
        issues.append(f"Missing expected categories: {missing_cats}")
    if len(cases) != EXPECTED_TOTAL_QUESTIONS:
        issues.append(
            f"Expected {EXPECTED_TOTAL_QUESTIONS} questions, found {len(cases)}"
        )
    official_count = sum(
        1 for case in cases if case.metadata.get("dataset_format") == "official-cleaned"
    )
    if official_count != len(cases):
        issues.append(
            "Competitive execution requires the official cleaned LongMemEval shape"
        )
    missing_question_dates = sum(
        1 for case in cases if not case.metadata.get("question_date")
    )
    if official_count and missing_question_dates:
        issues.append(
            f"{missing_question_dates} official questions are missing question_date"
        )
    return {
        "dataset_path": str(dataset_path),
        "benchmark": "longmemeval",
        "case_count": len(cases),
        "expected_total": EXPECTED_TOTAL_QUESTIONS,
        "categories": dict(category_counts),
        "missing_categories": missing_cats,
        "abstention_count": sum(
            1 for case in cases if case.metadata.get("is_abstention")
        ),
        "missing_question_dates": missing_question_dates,
        "dataset_format": (
            "official-cleaned" if official_count == len(cases) else "non-official-or-mixed"
        ),
        "fixture_hash": _fixture_hash(cases),
        "estimated_judge_calls": len(cases) if judge_name and judge_name not in ("none", "stub") else 0,
        "judge": judge_name or "none",
        "mode": "dry-run",
        "valid": len(issues) == 0,
        "execution_contract": "pinned-upstream-memory-benchmarks-only",
        "validation_issues": issues,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="LongMemEval benchmark runner for SEAM")
    parser.add_argument("--dataset-path", required=True, help="Path to LongMemEval JSON dataset")
    parser.add_argument("--dry-run", action="store_true", help="Validate dataset and print counts without executing")
    parser.add_argument("--plan", action="store_true", help="Print upstream readiness without executing")
    parser.add_argument("--judge", choices=["none", "stub", "claude", "openai"], default=None)
    parser.add_argument("--judge-model", default=None)
    parser.add_argument("--answerer-model", default="gpt-4o")
    parser.add_argument("--provider", choices=["openai", "anthropic", "azure"], default="openai")
    parser.add_argument("--harness-root", help="Pinned mem0ai/memory-benchmarks checkout")
    parser.add_argument("--project-name", help="Upstream run identifier")
    parser.add_argument("--mem0-host", default="http://127.0.0.1:8900")
    parser.add_argument("--predict-only", action="store_true", help="Free ingest+search only; skip answerer and judge")
    parser.add_argument("--allow-paid", action="store_true", help="Acknowledge provider-paid answerer/judge execution")
    parser.add_argument("--per-type", type=int, default=None, help="Upstream stratified smoke size; omit for all 500")
    parser.add_argument("--top-k", type=int, default=200)
    parser.add_argument("--top-k-cutoffs", default="10,20,50,200")
    parser.add_argument("--output-dir", default="/tmp/seam-upstream-benchmarks/longmemeval")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    if not args.plan and not Path(args.dataset_path).is_file():
        parser.error(
            "dataset not found; use the official longmemeval_s_cleaned.json release"
        )

    if args.dry_run:
        cases = _load_longmemeval_cases(args.dataset_path)
        if args.limit is not None:
            cases = cases[: args.limit]
        report = _dry_run_report(cases, args.dataset_path, args.judge)
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if report["valid"] else 1)
    if args.limit is not None:
        parser.error("--limit is dry-run-only; use --per-type for an upstream smoke")
    if not args.harness_root or not args.project_name:
        parser.error(
            "competitive execution requires --harness-root and --project-name; "
            "the local generic scorer is intentionally disabled"
        )
    if not args.predict_only and args.judge in {None, "none", "stub"}:
        parser.error("scored execution requires --judge openai or --judge claude")
    if not args.plan:
        _load_longmemeval_cases(args.dataset_path)
    judge_provider = (
        "anthropic" if args.judge == "claude" else args.judge
        if args.judge in {"openai"}
        else None
    )
    plan = plan_upstream_run(
        benchmark="longmemeval",
        harness_root=args.harness_root,
        project_name=args.project_name,
        mem0_host=args.mem0_host,
        predict_only=args.predict_only,
        top_k=args.top_k,
        top_k_cutoffs=args.top_k_cutoffs,
        workers=args.workers,
        output_dir=args.output_dir,
        answerer_model=args.answerer_model,
        judge_model=args.judge_model or "gpt-4o",
        provider=args.provider,
        judge_provider=judge_provider,
        dataset_path=args.dataset_path,
        per_type=args.per_type,
    )
    print(render_plan(plan))
    if args.plan:
        raise SystemExit(0 if plan.ready else 1)
    try:
        return_code = execute_upstream_plan(plan, allow_paid=args.allow_paid)
    except RuntimeError as exc:
        parser.error(str(exc))
    raise SystemExit(return_code)


if __name__ == "__main__":
    main()
