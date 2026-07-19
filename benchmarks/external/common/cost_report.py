"""Post-hoc, tokenizer-true cost report for mem0-harness run artifacts.

Why this exists (operator escalation, 2026-07-19): quoted run costs repeatedly
undershot actual OpenAI billing. Two root causes, both fixed here:

1. **Wrong counting basis.** Estimates were chars/4 arithmetic or scaled from
   other runs. This tool tokenizes the ACTUAL rendered prompts and stored
   completions with ``tiktoken`` using the model's REAL encoding (the gpt-4o /
   gpt-4.1 / gpt-5 families use ``o200k_base``; the repo-internal canonical
   ``cl100k_base`` overcounts those models ~10-20% and older models need it).
2. **Invisible passes.** Result artifacts hold only the LAST clean pass per
   case. Rate-limit storms produce silently re-run cases (strip-and-rerun) and
   billed-but-discarded partial passes that no artifact records. The report
   therefore prints a single-pass figure and labels it a LOWER BOUND on real
   billing — reconcile against the provider dashboard, never the other way.

Usage (repo venv; zero provider calls, read-only):

    python -m benchmarks.external.common.cost_report \
        /path/to/mem0-harness-artifact.json \
        --harness-root /tmp/memory-benchmarks

The artifact must be a Mem0-harness result set (``evaluations`` rows carrying
``retrieval.search_results`` + ``cutoff_results.top_200``). Prompts are
re-rendered through the pinned upstream ``prompts.py`` by file path — the same
contract the runs used — so prompt token counts are exact, not approximated.
Judge completions are approximated from the stored judgment+reason fields
(the raw JSON payload is not persisted); this is a small term (<2%).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

from benchmarks.external.common.pricing import PRICING_SNAPSHOT, estimate_cost_usd

# Longest-prefix match, mirroring pricing._rate(). tiktoken's own
# model-to-encoding table lags new model ids, so we pin the map here.
_ENCODING_BY_MODEL_PREFIX = {
    "gpt-4o": "o200k_base",
    "gpt-4.1": "o200k_base",
    "gpt-5": "o200k_base",
    "o4": "o200k_base",
    "gpt-4": "cl100k_base",
    "gpt-3.5": "cl100k_base",
}


def encoding_for_model(model: str) -> str:
    best = ""
    for prefix in _ENCODING_BY_MODEL_PREFIX:
        if model.startswith(prefix) and len(prefix) > len(best):
            best = prefix
    return _ENCODING_BY_MODEL_PREFIX.get(best, "o200k_base")


def _load_harness_prompts(harness_root: Path):
    path = harness_root / "benchmarks" / "locomo" / "prompts.py"
    spec = importlib.util.spec_from_file_location("mem0_locomo_prompts_cost", path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _format_search_results(search_results: list[dict]) -> list[dict]:
    formatted = []
    for r in sorted(search_results, key=lambda x: x.get("score", 0), reverse=True):
        entry = {"memory": r.get("memory", ""), "score": r.get("score", 0), "id": r.get("id", "")}
        if r.get("created_at"):
            entry["created_at"] = r["created_at"]
        formatted.append(entry)
    return formatted


def report_for_artifact(
    payload: dict,
    prompts,
    *,
    answerer_model: str,
    judge_model: str,
    cutoff: str = "top_200",
    search_limit: int = 200,
) -> dict:
    import tiktoken

    encoders = {
        name: tiktoken.get_encoding(name)
        for name in {encoding_for_model(answerer_model), encoding_for_model(judge_model)}
    }

    def count(model: str, text: str) -> int:
        return len(encoders[encoding_for_model(model)].encode(text or ""))

    totals = {
        "answerer": {"model": answerer_model, "prompt_tokens": 0, "completion_tokens": 0},
        "judge": {"model": judge_model, "prompt_tokens": 0, "completion_tokens": 0},
    }
    cases = 0
    for ev in payload.get("evaluations", []):
        cr = (ev.get("cutoff_results") or {}).get(cutoff) or {}
        generated = (cr.get("generated_answer") or "").strip()
        if not generated:
            continue
        cases += 1
        formatted = _format_search_results(
            list((ev.get("retrieval") or {}).get("search_results") or [])
        )[:search_limit]
        gen_prompt = prompts.get_answer_generation_prompt(
            str(ev.get("question") or ""), formatted,
            reference_date=ev.get("reference_date"), user_profile=ev.get("user_profile"),
        )
        totals["answerer"]["prompt_tokens"] += count(answerer_model, gen_prompt)
        totals["answerer"]["completion_tokens"] += count(answerer_model, generated)

        category = int(ev.get("category") or 0)
        gold = prompts.preprocess_answer(category, str(ev.get("ground_truth_answer") or ""))
        judge_prompt = prompts.get_judge_prompt(
            category, str(ev.get("question") or ""), gold, generated
        )
        totals["judge"]["prompt_tokens"] += count(
            judge_model, str(getattr(prompts, "JUDGE_SYSTEM_PROMPT", "")) + judge_prompt
        )
        # Raw judge JSON is not persisted; judgment+reason is a close floor.
        totals["judge"]["completion_tokens"] += count(
            judge_model, str(cr.get("judgment") or "") + str(cr.get("reason") or "")
        )

    for role in totals.values():
        role["cost_usd"] = estimate_cost_usd(
            role["model"], role["prompt_tokens"], role["completion_tokens"]
        )
    total_cost = sum(r["cost_usd"] or 0.0 for r in totals.values())
    return {
        "pricing_snapshot": PRICING_SNAPSHOT,
        "cases_counted": cases,
        "roles": totals,
        "single_pass_cost_usd": round(total_cost, 4),
        "caveat": (
            "LOWER BOUND: single clean pass over stored cases only. Stripped-and-"
            "rerun cases, aborted partial passes, and provider-side retries are "
            "invisible to artifacts and bill on top of this. Reconcile against "
            "the provider usage dashboard."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Tokenizer-true cost report for a mem0-harness artifact")
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--harness-root", type=Path, required=True)
    parser.add_argument("--answerer-model", default=None, help="Default: artifact metadata")
    parser.add_argument("--judge-model", default=None, help="Default: artifact metadata")
    args = parser.parse_args()

    with args.artifact.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    meta = payload.get("metadata") or {}
    answerer = args.answerer_model or meta.get("answerer_model") or "gpt-4o-mini"
    judge = args.judge_model or meta.get("judge_model") or answerer
    prompts = _load_harness_prompts(args.harness_root)
    report = report_for_artifact(payload, prompts, answerer_model=answerer, judge_model=judge)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
