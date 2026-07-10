"""Operator-gated PAID re-judge of ALREADY-STORED benchmark answers (PR 2 of the
cat1/cat3 -> 0.80 program, HISTORY#371 follow-up).

This is a REPLAY tool, not a benchmark run: it reads ``question`` /
``gold_answer`` / ``generated_answer`` straight out of one or more existing
``RunRecord`` JSON files (written by ``benchmarks.external.common.run_record``)
and re-scores them with a revised judge contract (``judge/2`` --
alias/specificity correctness + separated groundedness, see
``benchmarks.external.common.judge.JUDGE_PROMPT_V2``). It never calls the
retriever or the answerer again -- there is no adapter, no ingest, no store.

Dry-run by default: prints case counts and a cost estimate, constructs no
client, makes zero API calls. Spends ONLY with ``--confirm-paid``, which also
REQUIRES ``--out`` and ``--max-cost-usd`` -- a fail-closed spend cap: the pass
refuses to make a single judge call if the full projected cost already exceeds
the cap, and before every subsequent call re-checks whether the RUNNING ACTUAL
cost plus that call's projection would exceed it, aborting the rest of the run
the moment it would. This bounds the worst-case overshoot to at most one
already-in-flight call whose real cost could not be known before it returned
(an API call cannot be un-spent after the fact) -- it is not a guarantee the
cap is literally never exceeded by a single call's actual usage. Every output
(dry-run estimate and paid report alike) carries full spend/reproducibility
provenance: source-record SHA-256 hashes, the code commit SHA, a UTC
timestamp, and the judge/model/prompt versions used. Mirrors the
``seam improve validate --confirm-paid`` gate (HISTORY#292/#297) and the same
``external_mount_ready`` guard so a paid re-judge can never silently lose its
output to an unmounted external drive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone

from benchmarks.external.common.judge import (
    DEFAULT_JUDGE_PROMPT_VERSION,
    JUDGE_PROMPT_VERSIONS,
    build_judge,
)
from benchmarks.external.common.pricing import estimate_cost_usd
from benchmarks.external.common.run_record import _git_sha, external_mount_ready

# Judge/1's DEFAULT_JUDGE_PROMPT is the original run's contract; re-judging under
# the SAME model isolates the prompt-contract change as the only variable.
DEFAULT_REJUDGE_PROMPT_VERSION = "judge/2"

# ~4 characters per token is the standard rough English-text estimate used
# elsewhere in this benchmark suite's cost-estimation path; good enough for a
# MAX pre-spend estimate, not a claimed exact count (real usage is captured
# post-hoc from the API response, same as every other judge call in the repo).
_CHARS_PER_TOKEN = 4.0
# A judge/2 response adds one more short JSON field (groundedness enum); this
# is a fixed conservative allowance for that field's completion tokens.
_GROUNDEDNESS_FIELD_TOKENS = 12


@dataclass
class _MergedCase:
    case_id: str
    category: str | None
    question: str
    gold_answer: str
    generated_answer: str
    original_verdict: str | None
    original_score: float | None
    original_rationale: str | None
    original_judge_model: str | None
    stored_judge_prompt_tokens: int | None
    stored_judge_completion_tokens: int | None


def _load_cases(record_paths: list[str]) -> "OrderedDict[str, _MergedCase]":
    """Merge cases across records by ``case_id``. Later files override earlier
    ones (the established reconciliation pattern for a token-budget-fix rerun
    overriding a handful of stuck case_ids in the original full run), while
    first-appearance order is preserved for stable output ordering."""
    merged: "OrderedDict[str, _MergedCase]" = OrderedDict()
    for path in record_paths:
        with open(path) as f:
            doc = json.load(f)
        for c in doc.get("cases", []):
            judge_usage = c.get("judge") or {}
            merged[c["case_id"]] = _MergedCase(
                case_id=c["case_id"],
                category=c.get("category"),
                question=c["question"],
                gold_answer=c["gold_answer"],
                generated_answer=(c.get("generated_answer") or ""),
                original_verdict=c.get("verdict"),
                original_score=c.get("judge_score"),
                original_rationale=c.get("judge_rationale"),
                original_judge_model=c.get("judge_model"),
                stored_judge_prompt_tokens=judge_usage.get("prompt_tokens"),
                stored_judge_completion_tokens=judge_usage.get("completion_tokens"),
            )
    return merged


def _sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _source_record_provenance(record_paths: list[str]) -> list[dict]:
    """Path + SHA-256 for every input record, so a rejudge output is always
    traceable back to the EXACT bytes of the answers it scored."""
    return [{"path": p, "sha256": _sha256_file(p)} for p in record_paths]


def _build_provenance(
    source_records: list[dict],
    *,
    judge_name: str,
    judge_model: str,
    prompt_version: str,
    max_cost_usd: float | None = None,
) -> dict:
    return {
        "code_git_sha": _git_sha(),
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_records": source_records,
        "judge_name": judge_name,
        "judge_model": judge_model,
        "prompt_version": prompt_version,
        "judge1_prompt_version": DEFAULT_JUDGE_PROMPT_VERSION,
        "max_cost_usd": max_cost_usd,
    }


def _prompt_char_delta(prompt_version: str) -> int:
    """Character-length delta between the requested prompt template and
    judge/1's, EXCLUDING the {question}/{gold}/{pred} substitution slots (they
    are the same case-by-case content under either version)."""
    def _strip_slots(t: str) -> str:
        return t.replace("{question}", "").replace("{gold}", "").replace("{pred}", "")

    v1 = JUDGE_PROMPT_VERSIONS[DEFAULT_JUDGE_PROMPT_VERSION]
    v2 = JUDGE_PROMPT_VERSIONS[prompt_version]
    return len(_strip_slots(v2)) - len(_strip_slots(v1))


def _prepare_projection(
    cases: "OrderedDict[str, _MergedCase]", prompt_version: str
) -> tuple[list[_MergedCase], int, int, int, int]:
    """Shared projection basis for BOTH the dry-run estimate and the runtime
    budget guard, so the number the operator approves is exactly what the
    guard enforces -- no drift between the two. Returns (judged_cases,
    extra_prompt_tokens_per_case, extra_completion_tokens_per_case,
    avg_stored_prompt_tokens, avg_stored_completion_tokens)."""
    judged = [c for c in cases.values() if c.generated_answer.strip()]
    char_delta = _prompt_char_delta(prompt_version)
    token_delta_in = max(0, round(char_delta / _CHARS_PER_TOKEN))
    token_delta_out = _GROUNDEDNESS_FIELD_TOKENS
    stored_in = [c.stored_judge_prompt_tokens for c in judged if c.stored_judge_prompt_tokens]
    stored_out = [c.stored_judge_completion_tokens for c in judged if c.stored_judge_completion_tokens]
    avg_in = round(sum(stored_in) / len(stored_in)) if stored_in else 0
    avg_out = round(sum(stored_out) / len(stored_out)) if stored_out else 0
    return judged, token_delta_in, token_delta_out, avg_in, avg_out


def _projected_case_tokens(
    c: _MergedCase, token_delta_in: int, token_delta_out: int, avg_in: int, avg_out: int
) -> tuple[int, int]:
    """Projected (prompt_tokens, completion_tokens) for one case's judge/2 call:
    its own real stored judge/1 usage (or the cohort average when missing) plus
    the measured template-length delta."""
    proj_in = (c.stored_judge_prompt_tokens or avg_in) + token_delta_in
    proj_out = (c.stored_judge_completion_tokens or avg_out) + token_delta_out
    return proj_in, proj_out


def estimate_rejudge_cost(
    cases: "OrderedDict[str, _MergedCase]",
    source_records: list[dict],
    *,
    judge_name: str = "openai",
    judge_model: str = "gpt-4o-mini",
    prompt_version: str = DEFAULT_REJUDGE_PROMPT_VERSION,
) -> dict:
    """Zero-cost dry-run estimate of the FULL new judge pass (this is a whole new
    ``judge.score()`` call per case, not an increment on the original run's
    spend). Per-case projected tokens = the case's REAL stored judge token usage
    (grounded in what the original judge call actually cost, not a guess) plus
    the measured template-length delta of the new prompt version. Falls back to
    the average of cases that do have stored usage when a case is missing it.
    Empty generated answers are never judged (certain-incorrect, no call) --
    mirrors ``JudgedLocomoScorer.score``'s rule exactly."""
    judged, token_delta_in, token_delta_out, avg_in, avg_out = _prepare_projection(cases, prompt_version)
    skipped_empty = len(cases) - len(judged)

    total_in = total_out = 0
    stored_in_sum = stored_out_sum = 0
    for c in judged:
        pi, po = _projected_case_tokens(c, token_delta_in, token_delta_out, avg_in, avg_out)
        total_in += pi
        total_out += po
        stored_in_sum += c.stored_judge_prompt_tokens or 0
        stored_out_sum += c.stored_judge_completion_tokens or 0
    max_cost = estimate_cost_usd(judge_model, total_in, total_out)
    return {
        "dry_run": True,
        "provenance": _build_provenance(
            source_records, judge_name=judge_name, judge_model=judge_model, prompt_version=prompt_version
        ),
        "record_cases_total": len(cases),
        "cases_to_rejudge": len(judged),
        "cases_skipped_empty_answer": skipped_empty,
        "prompt_char_delta_vs_judge1": _prompt_char_delta(prompt_version),
        "estimated_extra_prompt_tokens_per_case": token_delta_in,
        "estimated_extra_completion_tokens_per_case": token_delta_out,
        "stored_judge1_tokens_used_as_base": {"prompt_total": stored_in_sum, "completion_total": stored_out_sum},
        "max_estimated_total_input_tokens": total_in,
        "max_estimated_total_output_tokens": total_out,
        "max_estimated_cost_usd": (round(max_cost, 6) if max_cost is not None else None),
        "note": (
            "no API calls made; this replays STORED answers only (no re-retrieval, "
            "no re-answer). The estimate is the FULL cost of a new judge pass over "
            "all cases_to_rejudge, projected from each case's real stored judge/1 "
            "token usage plus the measured judge/2 template-length delta. "
            "Re-run with --confirm-paid --out <path> --max-cost-usd <cap> to execute."
        ),
    }


def rejudge(
    cases: "OrderedDict[str, _MergedCase]",
    source_records: list[dict],
    *,
    judge_name: str = "openai",
    judge_model: str = "gpt-4o-mini",
    prompt_version: str = DEFAULT_REJUDGE_PROMPT_VERSION,
    max_cost_usd: float,
) -> dict:
    """Execute the paid re-judge. Caller must have already gated this behind an
    explicit operator confirmation -- this function makes real API calls.

    ``max_cost_usd`` is a REQUIRED fail-closed spend cap (no default, so a
    caller cannot forget it): the pass refuses to make a single judge call if
    the full projection already exceeds the cap, and before each subsequent
    call re-checks whether the RUNNING ACTUAL cost plus that call's projection
    would exceed it, aborting the rest of the run the instant it would. The
    worst-case overshoot is bounded to at most one already-in-flight call
    whose real cost could not be known before it returned -- not a guarantee
    that a single call's actual usage can never exceed the cap.
    """
    judged, token_delta_in, token_delta_out, avg_in, avg_out = _prepare_projection(cases, prompt_version)

    projected_total_in = projected_total_out = 0
    for c in judged:
        pi, po = _projected_case_tokens(c, token_delta_in, token_delta_out, avg_in, avg_out)
        projected_total_in += pi
        projected_total_out += po
    projected_total_cost = estimate_cost_usd(judge_model, projected_total_in, projected_total_out)
    if projected_total_cost is None:
        raise RuntimeError(
            f"cannot project cost for unpriced model {judge_model!r}; "
            "fail-closed refuses to spend without a cost bound"
        )
    if projected_total_cost > max_cost_usd:
        raise RuntimeError(
            f"projected max cost ${projected_total_cost:.6f} exceeds --max-cost-usd {max_cost_usd} "
            "-- refusing to make ANY judge calls (fail-closed)"
        )

    judge = build_judge(judge_name, judge_model, prompt_version=prompt_version)
    rows: list[dict] = []
    changed = 0
    groundedness_counts: dict[str, int] = {}
    old_scores: list[float] = []
    new_scores: list[float] = []
    running_cost = 0.0
    actual_prompt_tokens_total = 0
    actual_completion_tokens_total = 0
    cases_judged = 0
    budget_exhausted = False
    cases_skipped_budget_guard: list[str] = []

    for c in cases.values():
        pred = c.generated_answer.strip()
        row_base = {
            "case_id": c.case_id,
            "category": c.category,
            "question": c.question,
            "gold_answer": c.gold_answer,
            "generated_answer": c.generated_answer,
            "original": {
                "verdict": c.original_verdict,
                "score": c.original_score,
                "rationale": c.original_rationale,
                "judge_model": c.original_judge_model,
                "prompt_version": DEFAULT_JUDGE_PROMPT_VERSION,
            },
        }

        if not pred:
            # Certain-incorrect, never judged -- mirrors JudgedLocomoScorer's rule.
            is_changed = "incorrect" != c.original_verdict
            if is_changed:
                changed += 1
            if c.original_score is not None:
                old_scores.append(c.original_score)
            new_scores.append(0.0)
            groundedness_counts["na"] = groundedness_counts.get("na", 0) + 1
            rows.append({
                **row_base,
                "rejudged": {
                    "verdict": "incorrect", "score": 0.0, "rationale": "empty answer",
                    "groundedness": "na", "judge_model": judge_model, "prompt_version": prompt_version,
                    "prompt_tokens": None, "completion_tokens": None, "cost_usd": 0.0,
                },
                "verdict_changed": is_changed,
                "skipped_budget_guard": False,
            })
            continue

        if budget_exhausted:
            cases_skipped_budget_guard.append(c.case_id)
            rows.append({**row_base, "rejudged": None, "verdict_changed": None, "skipped_budget_guard": True})
            continue

        proj_in, proj_out = _projected_case_tokens(c, token_delta_in, token_delta_out, avg_in, avg_out)
        proj_case_cost = estimate_cost_usd(judge_model, proj_in, proj_out) or 0.0
        if running_cost + proj_case_cost > max_cost_usd:
            # Fail-closed: refuse THIS call (and all remaining) rather than risk
            # pushing actual spend over the cap.
            budget_exhausted = True
            cases_skipped_budget_guard.append(c.case_id)
            rows.append({**row_base, "rejudged": None, "verdict_changed": None, "skipped_budget_guard": True})
            continue

        verdict_obj = judge.score(question=c.question, gold=c.gold_answer, pred=pred)
        new_ground = getattr(judge, "last_groundedness", None)
        usage = getattr(judge, "last_usage", None) or {}
        case_cost = estimate_cost_usd(judge_model, usage.get("prompt_tokens"), usage.get("completion_tokens"))
        running_cost += case_cost or 0.0
        actual_prompt_tokens_total += usage.get("prompt_tokens") or 0
        actual_completion_tokens_total += usage.get("completion_tokens") or 0
        cases_judged += 1

        is_changed = verdict_obj.verdict != c.original_verdict
        if is_changed:
            changed += 1
        if c.original_score is not None:
            old_scores.append(c.original_score)
        new_scores.append(verdict_obj.score)
        groundedness_counts[str(new_ground)] = groundedness_counts.get(str(new_ground), 0) + 1
        rows.append({
            **row_base,
            "rejudged": {
                "verdict": verdict_obj.verdict, "score": verdict_obj.score, "rationale": verdict_obj.rationale,
                "groundedness": new_ground, "judge_model": judge_model, "prompt_version": prompt_version,
                "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
                "cost_usd": (round(case_cost, 6) if case_cost is not None else None),
            },
            "verdict_changed": is_changed,
            "skipped_budget_guard": False,
        })

    return {
        "provenance": _build_provenance(
            source_records, judge_name=judge_name, judge_model=judge_model,
            prompt_version=prompt_version, max_cost_usd=max_cost_usd,
        ),
        "n_cases": len(rows),
        "n_cases_judged": cases_judged,
        "n_verdicts_changed": changed,
        "old_score_mean": (round(sum(old_scores) / len(old_scores), 6) if old_scores else None),
        "new_score_mean": (round(sum(new_scores) / len(new_scores), 6) if new_scores else None),
        "groundedness_counts": groundedness_counts,
        "budget_guard": {
            "max_cost_usd": max_cost_usd,
            "projected_total_cost_usd": round(projected_total_cost, 6),
            "budget_exhausted": budget_exhausted,
            "cases_skipped_budget_guard": cases_skipped_budget_guard,
        },
        "actual_tokens": {
            "prompt_total": actual_prompt_tokens_total,
            "completion_total": actual_completion_tokens_total,
        },
        "actual_cost_usd": {"total": round(running_cost, 6)},
        "cases": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record", action="append", required=True, dest="records",
                         help="path to a RunRecord JSON (repeatable; later files override earlier by case_id)")
    parser.add_argument("--judge", default="openai", choices=["openai", "claude"])
    parser.add_argument("--judge-model", default="gpt-4o-mini")
    parser.add_argument("--judge-prompt-version", default=DEFAULT_REJUDGE_PROMPT_VERSION,
                         choices=sorted(JUDGE_PROMPT_VERSIONS))
    parser.add_argument("--out", default=None, help="output path for the rejudge report (required with --confirm-paid)")
    parser.add_argument("--max-cost-usd", type=float, default=None,
                         help="REQUIRED with --confirm-paid: fail-closed USD spend cap. Refuses to start if the "
                              "projected cost exceeds it, and aborts before any call that would push actual spend over it")
    parser.add_argument("--confirm-paid", action="store_true",
                         help="REQUIRED to spend: without it this prints the case count + cost estimate and makes zero API calls")
    args = parser.parse_args()

    cases = _load_cases(args.records)
    source_records = _source_record_provenance(args.records)

    if not args.confirm_paid:
        estimate = estimate_rejudge_cost(
            cases, source_records, judge_name=args.judge,
            judge_model=args.judge_model, prompt_version=args.judge_prompt_version,
        )
        print(json.dumps(estimate, indent=2))
        return

    if not args.out:
        raise SystemExit("error: --out is required with --confirm-paid")
    if args.max_cost_usd is None:
        raise SystemExit("error: --max-cost-usd is required with --confirm-paid (fail-closed: no cap means no spend)")
    ok, why = external_mount_ready(args.out)
    if not ok:
        raise SystemExit(f"error: {why}")

    try:
        report = rejudge(
            cases, source_records, judge_name=args.judge, judge_model=args.judge_model,
            prompt_version=args.judge_prompt_version, max_cost_usd=args.max_cost_usd,
        )
    except RuntimeError as exc:
        raise SystemExit(f"error: {exc}") from exc

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2, sort_keys=False)
    summary = {k: v for k, v in report.items() if k != "cases"}
    summary["written_to"] = args.out
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
