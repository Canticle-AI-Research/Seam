"""Paid answerer-parity probe over stored Mem0-harness miss contexts.

The HISTORY#400 scoreboard (SEAM cat1 250/282 = 88.65%) was scored with a
gpt-4o-mini answerer/judge, while mem0's published table uses their gpt-4o
defaults — so the "beat 91%" comparison is cross-answerer. This probe measures
how much of the remaining miss gap is answerer strength alone: for every
stored miss it re-answers the FROZEN stored top-200 context with both
answerer models same-day and judges both arms with the same judge model
(gpt-4o, the published contract), isolating the answerer variable.

Retrieval is never re-run (HISTORY#421 showed current retrieval is neutral vs
the stored lists), no SEAM module is imported (safe while other agents edit
the runtime), and the upstream prompt/judge contract is loaded verbatim by
file path from a local clone of ``mem0ai/memory-benchmarks`` (pin the audited
commit ``4b61c5d``).

This makes PAID provider calls and is operator-gated. Stdout stays
aggregate-only; the full per-case record is written beside the source
artifact (private, never committed).

Example:

    python -m benchmarks.external.mem0_harness.parity_probe_answerer \
      /path/to/mem0-harness-cat13.json \
      --harness-root /path/to/memory-benchmarks --categories 1
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

BASELINE_ANSWERER = "gpt-4o-mini"
PARITY_ANSWERER = "gpt-4o"
JUDGE_MODEL = "gpt-4o"
SEARCH_LIMIT = 200


def load_harness_prompts(harness_root: Path):
    """Import the upstream ``benchmarks/locomo/prompts.py`` by file path."""

    path = harness_root / "benchmarks" / "locomo" / "prompts.py"
    spec = importlib.util.spec_from_file_location("mem0_locomo_prompts_parity", path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def format_search_results(search_results: list[dict]) -> list[dict]:
    """Upstream ``format_search_results`` normalization (score-desc sort)."""

    formatted = []
    for r in sorted(search_results, key=lambda x: x.get("score", 0), reverse=True):
        entry: dict[str, Any] = {
            "memory": r.get("memory", ""),
            "score": r.get("score", 0),
            "id": r.get("id", ""),
        }
        if r.get("created_at"):
            entry["created_at"] = r["created_at"]
        formatted.append(entry)
    return formatted


def select_misses(payload: dict[str, Any], categories: set[int]) -> list[dict[str, Any]]:
    """All stored misses (top-200 score < 1) in the requested categories."""

    selected = []
    for evaluation in payload.get("evaluations", []):
        cutoff = (evaluation.get("cutoff_results") or {}).get("top_200") or {}
        if (
            int(evaluation.get("category") or 0) not in categories
            or float(cutoff.get("score") or 0.0) >= 1.0
        ):
            continue
        selected.append(evaluation)
    return selected


def _openai_call(client, model: str, system: str, user: str, *, json_mode: bool) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": 0,
        "max_tokens": 4096,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    last_error: Exception | None = None
    for attempt in range(5):
        try:
            response = client.chat.completions.create(**kwargs)
            return response.choices[0].message.content or ""
        except Exception as error:  # provider/rate errors: bounded backoff
            last_error = error
            time.sleep(2**attempt)
    raise RuntimeError(f"provider call failed after retries: {last_error}")


def run_case_arm(
    prompts,
    evaluation: dict[str, Any],
    answerer_model: str,
    call: Callable[..., str],
) -> dict[str, Any]:
    """Answer with ``answerer_model`` + judge with JUDGE_MODEL, upstream contract."""

    question = str(evaluation.get("question") or "")
    gold = str(evaluation.get("ground_truth_answer") or "")
    category = int(evaluation.get("category") or 0)
    formatted = format_search_results(
        list((evaluation.get("retrieval") or {}).get("search_results") or [])
    )[:SEARCH_LIMIT]

    gen_prompt = prompts.get_answer_generation_prompt(
        question, formatted, reference_date=evaluation.get("reference_date"),
        user_profile=evaluation.get("user_profile"),
    )
    generated = call(answerer_model, "", gen_prompt, json_mode=False)
    if "ANSWER:" in generated:
        generated = generated.rsplit("ANSWER:", 1)[-1].strip()

    processed_gold = prompts.preprocess_answer(category, gold)
    judge_prompt = prompts.get_judge_prompt(category, question, processed_gold, generated)
    raw = call(JUDGE_MODEL, prompts.JUDGE_SYSTEM_PROMPT, judge_prompt, json_mode=True)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {}
    label = str(parsed.get("label") or "").upper()
    return {
        "answerer_model": answerer_model,
        "generated_answer": generated,
        "label": label,
        "correct": label == "CORRECT",
        "judge_reasoning": str(parsed.get("reasoning") or ""),
    }


def run_probe(
    payload: dict[str, Any],
    prompts,
    call: Callable[..., str],
    categories: set[int],
) -> dict[str, Any]:
    cases = []
    baseline_correct = 0
    parity_correct = 0
    per_category: dict[str, dict[str, int]] = {}
    for evaluation in select_misses(payload, categories):
        baseline = run_case_arm(prompts, evaluation, BASELINE_ANSWERER, call)
        parity = run_case_arm(prompts, evaluation, PARITY_ANSWERER, call)
        baseline_correct += int(baseline["correct"])
        parity_correct += int(parity["correct"])
        cat = str(evaluation.get("category"))
        bucket = per_category.setdefault(cat, {"cases": 0, "baseline": 0, "parity": 0})
        bucket["cases"] += 1
        bucket["baseline"] += int(baseline["correct"])
        bucket["parity"] += int(parity["correct"])
        cases.append(
            {
                "question_id": evaluation.get("question_id"),
                "category": evaluation.get("category"),
                "stored_label": "WRONG",
                "baseline": baseline,
                "parity": parity,
            }
        )
    return {
        "baseline_answerer": BASELINE_ANSWERER,
        "parity_answerer": PARITY_ANSWERER,
        "judge_model": JUDGE_MODEL,
        "selected_miss_cases": len(cases),
        "baseline_rerun_correct": baseline_correct,
        "parity_correct": parity_correct,
        "net_parity_minus_baseline": parity_correct - baseline_correct,
        "per_category": per_category,
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Paid answerer-parity probe over stored miss contexts"
    )
    parser.add_argument("record", type=Path, help="Mem0-harness JSON result artifact")
    parser.add_argument(
        "--harness-root",
        type=Path,
        required=True,
        help="Local clone of mem0ai/memory-benchmarks (pin the audited commit)",
    )
    parser.add_argument(
        "--categories",
        default="1",
        help="Comma-separated categories to probe (default: 1)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Private output record path (default: alongside the source artifact)",
    )
    args = parser.parse_args()

    from openai import OpenAI

    client = OpenAI()

    def call(model: str, system: str, user: str, *, json_mode: bool) -> str:
        return _openai_call(client, model, system, user, json_mode=json_mode)

    prompts = load_harness_prompts(args.harness_root)
    with args.record.open(encoding="utf-8") as handle:
        payload = json.load(handle)

    categories = {int(c) for c in str(args.categories).split(",") if c.strip()}
    report = run_probe(payload, prompts, call, categories)
    report["source_artifact"] = args.record.name
    report["timestamp"] = datetime.now(timezone.utc).isoformat()

    out_path = args.out or args.record.parent / (
        f"{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        "-mem0-parity-probe-answerer.json"
    )
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    summary = {
        key: report[key]
        for key in (
            "baseline_answerer",
            "parity_answerer",
            "judge_model",
            "selected_miss_cases",
            "baseline_rerun_correct",
            "parity_correct",
            "net_parity_minus_baseline",
            "per_category",
        )
    }
    summary["record_written"] = str(out_path)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
