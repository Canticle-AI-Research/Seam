from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Callable

from benchmarks.external.common.types import AdapterAnswer, BenchmarkCase, MemorySystemAdapter
from benchmarks.external.common.scoring import aggregate_judge_scores, context_recall, exact_match, token_f1
from benchmarks.external.common.judge import JudgeBatchItem, JudgeVerdict
from benchmarks.external.common.provider_retry import provider_retry

RESULT_VERSION = "SEAM-EXTERNAL-MEMORY-BENCHMARK-RESULT/1"


def _canonical_json(obj) -> str:
    """Canonical JSON serialization: sorted keys, no trailing whitespace."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _integrity_hash(cases_payload: list[dict], scores: dict) -> str:
    """SHA-256 over canonical JSON of cases + scores."""
    payload = _canonical_json({"cases": cases_payload, "scores": scores})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_benchmark(
    *,
    adapter: MemorySystemAdapter,
    cases: list[BenchmarkCase],
    dataset_source: str = "unknown",
    judge: object | None = None,
    judge_batch: bool = False,
    save_context: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Run adapter against cases and return a RunReport dict.

    The report shape matches SEAM-EXTERNAL-MEMORY-BENCHMARK-RESULT/1:
    {version, benchmark, adapter, dataset: {source, case_count},
     run_started_at, elapsed_seconds, scores: {context_recall_mean, answer_em_mean, answer_f1_mean},
     cases: [{case_id, category, scores: {context_recall, answer_em, answer_f1},
              retrieval_latency_ms, answer_latency_ms}],
     integrity_hash}
    """
    started_ts = time.time()
    run_started_at = datetime.now(timezone.utc).isoformat()
    case_results: list[dict] = []

    batch_judge = _select_batch_judge(judge, judge_batch)
    sync_judge = None if batch_judge is not None else judge

    total = len(cases)
    for idx, case in enumerate(cases):
        case_entry = _run_case(adapter, case, sync_judge, save_context=save_context)
        case_results.append(case_entry)

        if progress:
            progress(idx + 1, total)

    if batch_judge is not None:
        _finalize_judge_batch(case_results, batch_judge, key="judge")

    elapsed = time.time() - started_ts
    return _build_report(
        adapter_name=adapter.name,
        dataset_source=dataset_source,
        run_started_at=run_started_at,
        elapsed=elapsed,
        case_results=case_results,
    )


def run_benchmark_parallel(
    *,
    adapter_factory: Callable[[], MemorySystemAdapter],
    adapter_name: str,
    cases: list[BenchmarkCase],
    dataset_source: str = "unknown",
    judge_factory: Callable[[], object | None] | None = None,
    judge_batch: bool = False,
    workers: int = 4,
    save_context: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Run independent benchmark cases concurrently while preserving report order."""
    if workers <= 1:
        return run_benchmark(
            adapter=adapter_factory(),
            cases=cases,
            dataset_source=dataset_source,
            judge=judge_factory() if judge_factory else None,
            judge_batch=judge_batch,
            save_context=save_context,
            progress=progress,
        )

    started_ts = time.time()
    run_started_at = datetime.now(timezone.utc).isoformat()
    total = len(cases)
    case_results: list[dict | None] = [None] * total

    # When batching the judge, do not score per case in workers; score once at
    # the end against a single judge instance.
    batch_judge = (
        _select_batch_judge(judge_factory() if judge_factory else None, judge_batch)
        if judge_batch
        else None
    )

    def _worker(index: int, case: BenchmarkCase) -> tuple[int, dict]:
        adapter = adapter_factory()
        worker_judge = None if batch_judge is not None else (judge_factory() if judge_factory else None)
        return index, _run_case(adapter, case, worker_judge, save_context=save_context)

    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(_worker, index, case)
            for index, case in enumerate(cases)
        ]
        for future in as_completed(futures):
            index, case_entry = future.result()
            case_results[index] = case_entry
            completed += 1
            if progress:
                progress(completed, total)

    final_results = [case for case in case_results if case is not None]
    if batch_judge is not None:
        _finalize_judge_batch(final_results, batch_judge, key="judge")

    elapsed = time.time() - started_ts
    return _build_report(
        adapter_name=adapter_name,
        dataset_source=dataset_source,
        run_started_at=run_started_at,
        elapsed=elapsed,
        case_results=final_results,
    )


def run_benchmark_grouped(
    *,
    adapter: MemorySystemAdapter,
    cases: list[BenchmarkCase],
    scope_id: Callable[[BenchmarkCase], str],
    dataset_source: str = "unknown",
    judge: object | None = None,
    judge_cross: object | None = None,
    judge_batch: bool = False,
    save_context: bool = False,
    progress: Callable[[int, int], None] | None = None,
    checkpoint: Callable[[list[dict], int, int], None] | None = None,
) -> dict:
    """Run cases grouped by shared conversation scope, ingesting each scope once.

    ``checkpoint`` (if given) is called after every scope completes with the
    accumulated ``case_results`` so far, plus ``(completed, total)``. This lets
    callers flush partial results to durable storage during long runs, so an
    interrupted multi-hour run is not a total loss.
    """
    started_ts = time.time()
    run_started_at = datetime.now(timezone.utc).isoformat()
    total = len(cases)
    case_results: list[dict] = []
    completed = 0

    batch_judge = _select_batch_judge(judge, judge_batch)
    sync_judge = None if batch_judge is not None else judge

    for scope, group in _group_cases(cases, scope_id).items():
        entries = _run_grouped_scope(
            adapter=adapter,
            scope=scope,
            group=group,
            judge=sync_judge,
            save_context=save_context,
        )
        case_results.extend(entries)
        completed += len(entries)
        if progress:
            progress(completed, total)
        if checkpoint:
            checkpoint(case_results, completed, total)

    if batch_judge is not None:
        _finalize_judge_batch(case_results, batch_judge, key="judge")
        if checkpoint:
            checkpoint(case_results, completed, total)

    elapsed = time.time() - started_ts
    return _build_report(
        adapter_name=adapter.name,
        dataset_source=dataset_source,
        run_started_at=run_started_at,
        elapsed=elapsed,
        case_results=case_results,
        judge_cross=judge_cross,
        judge_batch=judge_batch,
    )


def run_benchmark_grouped_parallel(
    *,
    adapter_factory: Callable[[], MemorySystemAdapter],
    adapter_name: str,
    cases: list[BenchmarkCase],
    scope_id: Callable[[BenchmarkCase], str],
    dataset_source: str = "unknown",
    judge_factory: Callable[[], object | None] | None = None,
    judge_cross: object | None = None,
    judge_batch: bool = False,
    workers: int = 4,
    save_context: bool = False,
    progress: Callable[[int, int], None] | None = None,
    checkpoint: Callable[[list[dict], int, int], None] | None = None,
) -> dict:
    """Run grouped scopes concurrently while preserving original case order.

    ``checkpoint`` (if given) is called as each scope-future completes with the
    results accumulated so far, plus ``(completed, total)`` — so a long parallel
    run flushes partial results to durable storage and survives interruption.
    """
    if workers <= 1:
        return run_benchmark_grouped(
            adapter=adapter_factory(),
            cases=cases,
            scope_id=scope_id,
            dataset_source=dataset_source,
            judge=judge_factory() if judge_factory else None,
            judge_cross=judge_cross,
            judge_batch=judge_batch,
            save_context=save_context,
            progress=progress,
            checkpoint=checkpoint,
        )

    started_ts = time.time()
    run_started_at = datetime.now(timezone.utc).isoformat()
    groups = _group_cases(cases, scope_id)
    case_order = {case.case_id: index for index, case in enumerate(cases)}
    total = len(cases)
    case_results: list[dict | None] = [None] * total

    batch_judge = (
        _select_batch_judge(judge_factory() if judge_factory else None, judge_batch)
        if judge_batch
        else None
    )

    def _worker(scope: str, group: list[BenchmarkCase]) -> list[dict]:
        adapter = adapter_factory()
        worker_judge = None if batch_judge is not None else (judge_factory() if judge_factory else None)
        return _run_grouped_scope(
            adapter=adapter,
            scope=scope,
            group=group,
            judge=worker_judge,
            save_context=save_context,
        )

    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(_worker, scope, group)
            for scope, group in groups.items()
        ]
        for future in as_completed(futures):
            entries = future.result()
            for entry in entries:
                case_results[case_order[entry["case_id"]]] = entry
            completed += len(entries)
            if progress:
                progress(completed, total)
            if checkpoint:
                checkpoint([case for case in case_results if case is not None], completed, total)

    final_results = [case for case in case_results if case is not None]
    if batch_judge is not None:
        _finalize_judge_batch(final_results, batch_judge, key="judge")
        if checkpoint:
            checkpoint(final_results, completed, total)

    elapsed = time.time() - started_ts
    return _build_report(
        adapter_name=adapter_name,
        dataset_source=dataset_source,
        run_started_at=run_started_at,
        elapsed=elapsed,
        case_results=final_results,
        judge_cross=judge_cross,
        judge_batch=judge_batch,
    )


def _select_batch_judge(judge: object | None, judge_batch: bool) -> object | None:
    """Return the judge if it supports score_batch and batch mode was requested."""
    if not judge_batch or judge is None:
        return None
    if callable(getattr(judge, "score_batch", None)):
        return judge
    return None


def _run_grouped_scope(
    *,
    adapter: MemorySystemAdapter,
    scope: str,
    group: list[BenchmarkCase],
    judge: object | None,
    save_context: bool,
) -> list[dict]:
    try:
        adapter.reset(scope)
        for turn in group[0].conversation:
            adapter.ingest_turn(scope, turn)
    except Exception as exc:
        return [
            _score_case_error(case, exc, stage="scope", save_context=save_context)
            for case in group
        ]

    entries: list[dict] = []
    for case in group:
        try:
            answer = adapter.answer(scope, case.question)
            entries.append(_score_case(case, answer, judge, save_context=save_context))
        except Exception as exc:
            entries.append(_score_case_error(case, exc, stage="answer", save_context=save_context))
    return entries


def _finalize_judge_batch(case_results: list[dict], judge: object, *, key: str) -> None:
    """Submit one batch job for all cases and fill ``case[key]`` with results.

    Expects each case to carry ``_judge_question``, ``_judge_gold``, and
    ``_prediction`` placeholders left by ``_score_case`` when the sync judge
    was skipped. Per-case errors land as ``{"error": str}`` so the existing
    error-tolerant aggregation continues to work.
    """
    items = [
        JudgeBatchItem(
            custom_id=str(case.get("case_id")),
            question=str(case.get("_judge_question", "")),
            gold=str(case.get("_judge_gold", "")),
            pred=str(case.get("_prediction", "")),
        )
        for case in case_results
    ]
    try:
        verdicts = provider_retry(
            lambda: judge.score_batch(items),
            label=f"{getattr(judge, 'name', 'judge')}.score_batch",
        )
    except Exception as exc:
        for case in case_results:
            case[key] = {"error": f"judge batch failed: {exc}"}
        return
    for case in case_results:
        cid = str(case.get("case_id"))
        value = verdicts.get(cid)
        if isinstance(value, JudgeVerdict):
            case[key] = {
                "verdict": value.verdict,
                "score": value.score,
                "rationale": value.rationale,
                "judge_name": value.judge_name,
                "judge_model": value.judge_model,
            }
        elif isinstance(value, Exception):
            case[key] = {"error": str(value)}
        else:
            case[key] = {"error": "judge batch returned no entry for case"}


def _group_cases(
    cases: list[BenchmarkCase],
    scope_id: Callable[[BenchmarkCase], str],
) -> OrderedDict[str, list[BenchmarkCase]]:
    groups: OrderedDict[str, list[BenchmarkCase]] = OrderedDict()
    for case in cases:
        groups.setdefault(scope_id(case), []).append(case)
    return groups


def _run_case(
    adapter: MemorySystemAdapter,
    case: BenchmarkCase,
    judge: object | None,
    *,
    save_context: bool = False,
) -> dict:
    adapter.reset(case.case_id)

    for turn in case.conversation:
        adapter.ingest_turn(case.case_id, turn)

    answer: AdapterAnswer = adapter.answer(case.case_id, case.question)
    return _score_case(case, answer, judge, save_context=save_context)


def _score_case(
    case: BenchmarkCase,
    answer: AdapterAnswer,
    judge: object | None,
    *,
    save_context: bool = False,
) -> dict:
    cr = context_recall(answer.retrieved_context, case.gold_answer)

    pred = answer.generated_answer if answer.generated_answer is not None else ""
    if answer.generated_answer is not None:
        em = exact_match(answer.generated_answer, case.gold_answer)
        f1 = token_f1(answer.generated_answer, case.gold_answer)
    else:
        em = 0.0
        f1 = 0.0

    case_entry: dict = {
        "case_id": case.case_id,
        "category": case.category,
        "scores": {
            "context_recall": cr,
            "answer_em": em,
            "answer_f1": f1,
        },
        "retrieval_latency_ms": answer.retrieval_latency_ms,
        "answer_latency_ms": answer.answer_latency_ms,
        "_prediction": pred,
        "_judge_question": case.question,
        "_judge_gold": case.gold_answer,
    }
    if save_context:
        case_entry["retrieved_context"] = answer.retrieved_context
        if answer.answerer_diagnostics is not None:
            case_entry["answerer_diagnostics"] = answer.answerer_diagnostics

    if judge is not None:
        try:
            verdict = provider_retry(
                lambda: judge.score(
                    question=case.question,
                    gold=case.gold_answer,
                    pred=pred,
                ),
                label=f"{getattr(judge, 'name', 'judge')}.score",
            )
            case_entry["judge"] = {
                "verdict": verdict.verdict,
                "score": verdict.score,
                "rationale": verdict.rationale,
                "judge_name": verdict.judge_name,
                "judge_model": verdict.judge_model,
            }
        except Exception as exc:
            case_entry["judge"] = {"error": str(exc)}

    return case_entry


def _score_case_error(
    case: BenchmarkCase,
    exc: BaseException,
    *,
    stage: str,
    save_context: bool = False,
) -> dict:
    case_entry: dict = {
        "case_id": case.case_id,
        "category": case.category,
        "scores": {
            "context_recall": 0.0,
            "answer_em": 0.0,
            "answer_f1": 0.0,
        },
        "retrieval_latency_ms": 0.0,
        "answer_latency_ms": 0.0,
        "_prediction": "",
        "_judge_question": case.question,
        "_judge_gold": case.gold_answer,
        "error": {
            "stage": stage,
            "type": type(exc).__name__,
            "message": str(exc),
        },
    }
    if save_context:
        case_entry["retrieved_context"] = ""
    return case_entry


def _build_report(
    *,
    adapter_name: str,
    dataset_source: str,
    run_started_at: str,
    elapsed: float,
    case_results: list[dict],
    judge_cross: object | None = None,
    judge_batch: bool = False,
) -> dict:
    total = len(case_results)

    # Compute means
    if total > 0:
        cr_mean = sum(c["scores"]["context_recall"] for c in case_results) / total
        em_mean = sum(c["scores"]["answer_em"] for c in case_results) / total
        f1_mean = sum(c["scores"]["answer_f1"] for c in case_results) / total
    else:
        cr_mean = em_mean = f1_mean = 0.0

    scores: dict = {
        "context_recall_mean": cr_mean,
        "answer_em_mean": em_mean,
        "answer_f1_mean": f1_mean,
    }

    judge_verdicts = []
    for c in case_results:
        j = c.get("judge")
        if j and "verdict" in j:
            judge_verdicts.append(j)
        else:
            judge_verdicts.append(None)
    if any(v is not None for v in judge_verdicts):
        scores.update(aggregate_judge_scores(judge_verdicts))

    # Cross-check with a second judge when configured
    integrity_hash_excludes: list[str] = []
    if judge_cross is not None:
        batch_cross = _select_batch_judge(judge_cross, judge_batch)
        if batch_cross is not None:
            _finalize_judge_batch(case_results, batch_cross, key="judge_cross")
        else:
            for case in case_results:
                pred = case.get("_prediction", "")
                try:
                    verdict = provider_retry(
                        lambda: judge_cross.score(
                            question=case.get("_judge_question", ""),
                            gold=case.get("_judge_gold", ""),
                            pred=pred,
                        ),
                        label=f"{getattr(judge_cross, 'name', 'judge_cross')}.score",
                    )
                    cross_entry = {
                        "verdict": verdict.verdict,
                        "score": verdict.score,
                        "rationale": verdict.rationale,
                        "judge_name": verdict.judge_name,
                        "judge_model": verdict.judge_model,
                    }
                except Exception as exc:
                    cross_entry = {"error": str(exc)}
                case["judge_cross"] = cross_entry
        cross_verdicts = [case.get("judge_cross", {}) for case in case_results]
        scorable = [v for v in cross_verdicts if "verdict" in v]
        if scorable:
            cross_agg = aggregate_judge_scores(scorable)
            for key, value in cross_agg.items():
                scores[f"judge_cross_{key}"] = value
        primary_verdicts = [
            c.get("judge", {}).get("verdict")
            for c in case_results
            if isinstance(c.get("judge"), dict) and "verdict" in c.get("judge", {})
        ]
        cross_v = [
            c.get("judge_cross", {}).get("verdict")
            for c in case_results
            if isinstance(c.get("judge_cross"), dict) and "verdict" in c.get("judge_cross", {})
        ]
        if primary_verdicts and cross_v and len(primary_verdicts) == len(cross_v):
            agree = sum(1 for p, c2 in zip(primary_verdicts, cross_v) if p == c2)
            scores["judge_cross_agreement_rate"] = agree / len(primary_verdicts)
        integrity_hash_excludes.append("judge_cross")

    # Per-category score breakdown when cases carry category metadata
    _add_per_category_scores(scores, case_results)

    integrity_exclude_keys = {
        "retrieval_latency_ms",
        "answer_latency_ms",
        "judge",
        "_prediction",
        "_judge_question",
        "_judge_gold",
        "judge_cross",
        "retrieved_context",
        "answerer_diagnostics",
    }
    stable_cases = [
        {k: v for k, v in c.items() if k not in integrity_exclude_keys}
        for c in case_results
    ]
    integrity = _integrity_hash(stable_cases, scores)

    for case in case_results:
        case.pop("_judge_question", None)
        case.pop("_judge_gold", None)

    report: dict = {
        "version": RESULT_VERSION,
        "benchmark": "locomo",
        "adapter": adapter_name,
        "dataset": {
            "source": dataset_source,
            "case_count": total,
        },
        "run_started_at": run_started_at,
        "elapsed_seconds": elapsed,
        "scores": scores,
        "cases": case_results,
        "integrity_hash": integrity,
    }
    if integrity_hash_excludes:
        report["integrity_hash_excludes"] = integrity_hash_excludes
    return report


def _add_per_category_scores(scores: dict, case_results: list[dict]) -> None:
    """Mutate *scores* to include per-category means when cases carry category fields.

    Only adds ``per_category`` if at least one case has a non-None category.
    Each entry contains ``context_recall_mean``, ``judge_score_mean`` (when a
    judge verdict is present in the category group), and ``case_count``.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    for case in case_results:
        cat = case.get("category")
        if cat is not None:
            groups[str(cat)].append(case)

    if not groups:
        return

    per_category: dict[str, dict] = {}
    for cat, cases in sorted(groups.items(), key=lambda x: x[0]):
        n = len(cases)
        cr_mean = sum(c["scores"]["context_recall"] for c in cases) / n

        entry: dict = {
            "context_recall_mean": cr_mean,
            "case_count": n,
        }

        judge_scores = [
            c["judge"]["score"]
            for c in cases
            if isinstance(c.get("judge"), dict) and "score" in c["judge"]
        ]
        if judge_scores:
            entry["judge_score_mean"] = sum(judge_scores) / len(judge_scores)

        per_category[cat] = entry

    scores["per_category"] = per_category
