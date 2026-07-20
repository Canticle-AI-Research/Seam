"""Paid answerer-only microgate for versioned ``event-count/distinct`` policies.

Reruns ONLY the failed cat1 count questions from a saved Mem0-harness result
artifact through the unmodified upstream answer/judge contract, in two arms:

- ``baseline``: the stored ``retrieval.search_results`` exactly as recorded.
- ``candidate``: the same stored results passed through the facade's real
  ``_apply_count_context_policy`` code path (SEAM-COUNT projection first, one
  lowest-ranked memory displaced), i.e. what ``/search`` would have returned
  with ``SEAM_COUNT_CONTEXT_POLICY`` set to the selected policy (``--policy``,
  default ``event-count/distinct/1``; pass ``event-count/distinct/2`` to gate
  the same-event-grouping revision).

Both arms are answered and judged fresh in the same invocation so lever effect
is separable from answerer rerun noise. The stored per-case judgments remain
the reference scoreboard; this gate never relabels the source artifact.

The upstream prompt/judge contract is loaded verbatim from a local clone of
``mem0ai/memory-benchmarks`` (pin the audited commit, e.g. ``4b61c5d``); the
prompts module is imported by file path so the clone's ``benchmarks`` package
never shadows SEAM's. Case selection matches
``preflight_event_count_context`` exactly.

This makes PAID provider calls (answerer + judge per case per arm) and is
operator-gated. Stdout stays aggregate-only; the full per-case record is
written next to the source artifact (private, never committed).

Example:

    python -m benchmarks.external.mem0_harness.microgate_event_count_context \
      /path/to/mem0-harness-cat13.json \
      --harness-root /path/to/memory-benchmarks
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from benchmarks.external.mem0_harness.seam_mem0_server import (
    _apply_count_context_policy,
)
from seam_runtime.event_count_context import (
    EVENT_COUNT_DISTINCT_V1,
    EVENT_COUNT_POLICIES,
    is_count_question,
)
from seam_runtime.retrieval import RetrievalFlags

ANSWERER_MODEL = "gpt-4o-mini"
JUDGE_MODEL = "gpt-4o-mini"
SEARCH_LIMIT = 200


class _FlagRuntime:
    """Minimal runtime stub exposing the facade's cached-flags hook."""

    def __init__(self, flags: RetrievalFlags) -> None:
        self._flags = flags

    def _retrieval_flags_cached(self) -> RetrievalFlags:
        return self._flags


def load_harness_prompts(harness_root: Path):
    """Import the upstream ``benchmarks/locomo/prompts.py`` by file path."""

    path = harness_root / "benchmarks" / "locomo" / "prompts.py"
    spec = importlib.util.spec_from_file_location("mem0_locomo_prompts", path)
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


def select_cases(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Failed cat1 count questions; same predicate as the free preflight."""

    selected = []
    for evaluation in payload.get("evaluations", []):
        cutoff = (evaluation.get("cutoff_results") or {}).get("top_200") or {}
        question = str(evaluation.get("question") or "")
        if (
            int(evaluation.get("category") or 0) != 1
            or float(cutoff.get("score") or 0.0) >= 1.0
            or not is_count_question(question)
        ):
            continue
        selected.append(evaluation)
    return selected


def candidate_results(
    stored_results: list[dict],
    question: str,
    *,
    policy: str = EVENT_COUNT_DISTINCT_V1,
) -> list[dict]:
    """Run the stored results through the facade's real projection path."""

    runtime = _FlagRuntime(RetrievalFlags(count_context_policy=policy))
    normalized = [
        {
            "id": str(item.get("id") or ""),
            "memory": str(item.get("memory") or ""),
            "score": float(item.get("score") or 0.0),
            "created_at": str(item.get("created_at") or ""),
        }
        for item in stored_results
    ]
    return _apply_count_context_policy(runtime, question, normalized, SEARCH_LIMIT)


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
    results: list[dict],
    call: Callable[..., str],
) -> dict[str, Any]:
    """Answer + judge one arm using the upstream contract verbatim."""

    question = str(evaluation.get("question") or "")
    gold = str(evaluation.get("ground_truth_answer") or "")
    reference_date = evaluation.get("reference_date")
    formatted = format_search_results(results)[:SEARCH_LIMIT]

    gen_prompt = prompts.get_answer_generation_prompt(
        question, formatted, reference_date=reference_date,
        user_profile=evaluation.get("user_profile"),
    )
    generated = call(ANSWERER_MODEL, "", gen_prompt, json_mode=False)
    if "ANSWER:" in generated:
        generated = generated.rsplit("ANSWER:", 1)[-1].strip()

    processed_gold = prompts.preprocess_answer(1, gold)
    judge_prompt = prompts.get_judge_prompt(1, question, processed_gold, generated)
    raw = call(JUDGE_MODEL, prompts.JUDGE_SYSTEM_PROMPT, judge_prompt, json_mode=True)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = {}
    label = str(parsed.get("label") or "").upper()
    return {
        "generated_answer": generated,
        "label": label,
        "correct": label == "CORRECT",
        "judge_reasoning": str(parsed.get("reasoning") or ""),
    }


def run_microgate(
    payload: dict[str, Any],
    prompts,
    call: Callable[..., str],
    *,
    policy: str = EVENT_COUNT_DISTINCT_V1,
) -> dict[str, Any]:
    cases = []
    baseline_correct = 0
    candidate_correct = 0
    for evaluation in select_cases(payload):
        question = str(evaluation.get("question") or "")
        stored = list((evaluation.get("retrieval") or {}).get("search_results") or [])
        projected = candidate_results(stored, question, policy=policy)
        baseline = run_case_arm(prompts, evaluation, stored, call)
        candidate = run_case_arm(prompts, evaluation, projected, call)
        baseline_correct += int(baseline["correct"])
        candidate_correct += int(candidate["correct"])
        cases.append(
            {
                "question_id": evaluation.get("question_id"),
                "projection_applied": projected is not stored
                and bool(projected)
                and str(projected[0].get("id", "")).startswith("seam-count:"),
                "stored_label": "WRONG",
                "baseline": baseline,
                "candidate": candidate,
            }
        )
    return {
        "policy": policy,
        "answerer_model": ANSWERER_MODEL,
        "judge_model": JUDGE_MODEL,
        "selected_cases": len(cases),
        "baseline_rerun_correct": baseline_correct,
        "candidate_correct": candidate_correct,
        "net_candidate_minus_baseline": candidate_correct - baseline_correct,
        "gate_threshold_flips": 7,
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Paid answerer-only microgate for event-count/distinct/1"
    )
    parser.add_argument("record", type=Path, help="Mem0-harness JSON result artifact")
    parser.add_argument(
        "--harness-root",
        type=Path,
        required=True,
        help="Local clone of mem0ai/memory-benchmarks (pin the audited commit)",
    )
    parser.add_argument(
        "--policy",
        choices=sorted(EVENT_COUNT_POLICIES - {"off"}),
        default=EVENT_COUNT_DISTINCT_V1,
        help="count context policy to gate (default: event-count/distinct/1)",
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

    report = run_microgate(payload, prompts, call, policy=args.policy)
    report["source_artifact"] = args.record.name
    report["timestamp"] = datetime.now(timezone.utc).isoformat()

    out_path = args.out or args.record.parent / (
        f"{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        "-mem0-microgate-event-count.json"
    )
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    summary = {
        key: report[key]
        for key in (
            "policy",
            "selected_cases",
            "baseline_rerun_correct",
            "candidate_correct",
            "net_candidate_minus_baseline",
            "gate_threshold_flips",
        )
    }
    summary["record_written"] = str(out_path)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
