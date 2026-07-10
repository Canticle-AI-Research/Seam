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
client, makes zero API calls. Spends ONLY with ``--confirm-paid``. Mirrors the
``seam improve validate --confirm-paid`` gate (HISTORY#292/#297) and the same
``external_mount_ready`` guard so a paid re-judge can never silently lose its
output to an unmounted external drive.
"""
from __future__ import annotations

import argparse
import json
from collections import OrderedDict
from dataclasses import dataclass

from benchmarks.external.common.judge import (
    DEFAULT_JUDGE_PROMPT_VERSION,
    JUDGE_PROMPT_VERSIONS,
    build_judge,
)
from benchmarks.external.common.pricing import estimate_cost_usd
from benchmarks.external.common.run_record import external_mount_ready

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


def _prompt_char_delta(prompt_version: str) -> int:
    """Character-length delta between the requested prompt template and
    judge/1's, EXCLUDING the {question}/{gold}/{pred} substitution slots (they
    are the same case-by-case content under either version)."""
    def _strip_slots(t: str) -> str:
        return t.replace("{question}", "").replace("{gold}", "").replace("{pred}", "")

    v1 = JUDGE_PROMPT_VERSIONS[DEFAULT_JUDGE_PROMPT_VERSION]
    v2 = JUDGE_PROMPT_VERSIONS[prompt_version]
    return len(_strip_slots(v2)) - len(_strip_slots(v1))


def estimate_rejudge_cost(
    cases: "OrderedDict[str, _MergedCase]",
    *,
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
    judged = [c for c in cases.values() if c.generated_answer.strip()]
    skipped_empty = len(cases) - len(judged)
    char_delta = _prompt_char_delta(prompt_version)
    token_delta_in = max(0, round(char_delta / _CHARS_PER_TOKEN))
    token_delta_out = _GROUNDEDNESS_FIELD_TOKENS

    stored_in = [c.stored_judge_prompt_tokens for c in judged if c.stored_judge_prompt_tokens]
    stored_out = [c.stored_judge_completion_tokens for c in judged if c.stored_judge_completion_tokens]
    avg_in = round(sum(stored_in) / len(stored_in)) if stored_in else 0
    avg_out = round(sum(stored_out) / len(stored_out)) if stored_out else 0

    n = len(judged)
    total_in = sum((c.stored_judge_prompt_tokens or avg_in) + token_delta_in for c in judged)
    total_out = sum((c.stored_judge_completion_tokens or avg_out) + token_delta_out for c in judged)
    max_cost = estimate_cost_usd(judge_model, total_in, total_out)
    return {
        "dry_run": True,
        "record_cases_total": len(cases),
        "cases_to_rejudge": n,
        "cases_skipped_empty_answer": skipped_empty,
        "judge_model": judge_model,
        "prompt_version": prompt_version,
        "prompt_char_delta_vs_judge1": char_delta,
        "estimated_extra_prompt_tokens_per_case": token_delta_in,
        "estimated_extra_completion_tokens_per_case": token_delta_out,
        "stored_judge1_tokens_used_as_base": {"prompt_total": sum(stored_in), "completion_total": sum(stored_out)},
        "max_estimated_total_input_tokens": total_in,
        "max_estimated_total_output_tokens": total_out,
        "max_estimated_cost_usd": (round(max_cost, 6) if max_cost is not None else None),
        "note": (
            "no API calls made; this replays STORED answers only (no re-retrieval, "
            "no re-answer). The estimate is the FULL cost of a new judge pass over "
            "all cases_to_rejudge, projected from each case's real stored judge/1 "
            "token usage plus the measured judge/2 template-length delta. "
            "Re-run with --confirm-paid to execute."
        ),
    }


def rejudge(
    cases: "OrderedDict[str, _MergedCase]",
    *,
    judge_name: str = "openai",
    judge_model: str = "gpt-4o-mini",
    prompt_version: str = DEFAULT_REJUDGE_PROMPT_VERSION,
) -> dict:
    """Execute the paid re-judge. Caller must have already gated this behind an
    explicit operator confirmation -- this function makes real API calls."""
    judge = build_judge(judge_name, judge_model, prompt_version=prompt_version)
    rows = []
    changed = 0
    groundedness_counts: dict[str, int] = {}
    old_scores: list[float] = []
    new_scores: list[float] = []
    for c in cases.values():
        pred = c.generated_answer.strip()
        if not pred:
            new_verdict, new_score, new_rationale, new_ground = "incorrect", 0.0, "empty answer", "na"
        else:
            verdict_obj = judge.score(question=c.question, gold=c.gold_answer, pred=pred)
            new_verdict, new_score, new_rationale = (
                verdict_obj.verdict, verdict_obj.score, verdict_obj.rationale,
            )
            new_ground = getattr(judge, "last_groundedness", None)
        groundedness_counts[str(new_ground)] = groundedness_counts.get(str(new_ground), 0) + 1
        is_changed = new_verdict != c.original_verdict
        if is_changed:
            changed += 1
        if c.original_score is not None:
            old_scores.append(c.original_score)
        new_scores.append(new_score)
        rows.append({
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
            "rejudged": {
                "verdict": new_verdict,
                "score": new_score,
                "rationale": new_rationale,
                "groundedness": new_ground,
                "judge_model": judge_model,
                "prompt_version": prompt_version,
            },
            "verdict_changed": is_changed,
        })
    n = len(rows)
    return {
        "n_cases": n,
        "n_verdicts_changed": changed,
        "old_score_mean": (round(sum(old_scores) / len(old_scores), 6) if old_scores else None),
        "new_score_mean": (round(sum(new_scores) / len(new_scores), 6) if new_scores else None),
        "groundedness_counts": groundedness_counts,
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
    parser.add_argument("--confirm-paid", action="store_true",
                         help="REQUIRED to spend: without it this prints the case count + cost estimate and makes zero API calls")
    args = parser.parse_args()

    cases = _load_cases(args.records)

    if not args.confirm_paid:
        estimate = estimate_rejudge_cost(
            cases, judge_model=args.judge_model, prompt_version=args.judge_prompt_version
        )
        print(json.dumps(estimate, indent=2))
        return

    if not args.out:
        raise SystemExit("error: --out is required with --confirm-paid")
    ok, why = external_mount_ready(args.out)
    if not ok:
        raise SystemExit(f"error: {why}")

    report = rejudge(
        cases, judge_name=args.judge, judge_model=args.judge_model,
        prompt_version=args.judge_prompt_version,
    )
    import os as _os
    _os.makedirs(_os.path.dirname(_os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2, sort_keys=False)
    summary = {k: v for k, v in report.items() if k != "cases"}
    summary["written_to"] = args.out
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
