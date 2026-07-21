"""Paired paid microgate for ``canonical-graph-fill/1``.

The gate reuses one fresh, matched LoCoMo ingest for both arms.  Baseline and
candidate retrieval are produced from the same copied SQLite stores; the only
difference is that the candidate fills otherwise-unused top-200 rows with RAW
evidence reached through SEAM's canonical graph retriever.  Free-gate gain
cases supplied explicitly by the operator workflow are accompanied by
previously-correct, context-changing sentinels.

Provider calls are disabled unless ``--allow-paid`` is supplied.  Stdout is
aggregate-only; licensed text and per-case answers are written only to the
explicit private output record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from benchmarks.external.common.cost_report import encoding_for_model
from benchmarks.external.common.pricing import PRICING_SNAPSHOT, estimate_cost_usd
from benchmarks.external.mem0_harness.microgate_event_count_context import (
    format_search_results,
    load_harness_prompts,
)
from benchmarks.external.mem0_harness.preflight_derived_facts import (
    _DEFAULT_DATASET,
    build_turn_index,
)
from benchmarks.external.mem0_harness.preflight_graph_memory import (
    _BLOCKED_ENV,
    MATCHED_CONTEXT_BUDGET,
    MATCHED_SEARCH_TOP_K,
    _copy_stores,
    evidence_state,
)
from benchmarks.external.mem0_harness.seam_mem0_server import (
    GRAPH_CONTEXT_FILL_V1,
    SeamMem0Server,
)
from benchmarks.external.mem0_harness.upstream_runner import (
    PINNED_HARNESS_REVISION,
    _git_is_clean,
    _git_revision,
)

ANSWERER_MODEL = "gpt-4o"
JUDGE_MODEL = "gpt-4o"
TOP_K = 200
GRAPH_SLOTS = 40
DEFAULT_SENTINELS_PER_CATEGORY = 2
PROMOTION_NET_GAIN = 2
_QUESTION_ID = re.compile(r"^conv(?P<conversation>\d+)_q(?P<question>\d+)$")


def _parse_question_id(question_id: str) -> tuple[int, int]:
    match = _QUESTION_ID.fullmatch(question_id)
    if match is None:
        raise ValueError(f"invalid LoCoMo question id: {question_id!r}")
    return int(match["conversation"]), int(match["question"])


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _validate_harness(root: Path) -> str:
    revision = _git_revision(root)
    if revision != PINNED_HARNESS_REVISION:
        raise RuntimeError(
            f"harness revision mismatch: expected {PINNED_HARNESS_REVISION}, got {revision}"
        )
    if not _git_is_clean(root):
        raise RuntimeError("upstream harness checkout is not clean")
    return revision


def _validate_sentinel_record(payload: dict[str, Any]) -> set[str]:
    meta = payload.get("metadata") or {}
    expected = {
        "benchmark": "locomo",
        "answerer_model": ANSWERER_MODEL,
        "judge_model": JUDGE_MODEL,
        "top_k": TOP_K,
    }
    mismatches = [
        f"{key}={meta.get(key)!r} (expected {value!r})"
        for key, value in expected.items()
        if meta.get(key) != value
    ]
    if sorted(meta.get("categories") or []) != [1, 3]:
        mismatches.append("categories must be exactly [1, 3]")
    if mismatches:
        raise ValueError("sentinel record contract mismatch: " + "; ".join(mismatches))

    correct: set[str] = set()
    evaluations = payload.get("evaluations")
    if not isinstance(evaluations, list):
        raise ValueError("sentinel record evaluations must be a list")
    for evaluation in evaluations:
        score = ((evaluation.get("cutoff_results") or {}).get("top_200") or {}).get(
            "score"
        )
        if isinstance(score, (int, float)) and score >= 1:
            question_id = str(evaluation.get("question_id") or "")
            _parse_question_id(question_id)
            correct.add(question_id)
    if not correct:
        raise ValueError("sentinel record has no correct top-200 cases")
    return correct


def _evaluation_path(predicted_dir: Path, question_id: str) -> Path:
    path = predicted_dir / f"{question_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"missing fresh predict-only case: {path}")
    return path


def _load_evaluation(
    predicted_dir: Path,
    dataset: list[dict[str, Any]],
    question_id: str,
) -> dict[str, Any]:
    conversation_idx, question_idx = _parse_question_id(question_id)
    evaluation = _load_json(_evaluation_path(predicted_dir, question_id))
    qa = dataset[conversation_idx]["qa"][question_idx]
    checks = {
        "question_id": question_id,
        "category": int(qa["category"]),
        "question": str(qa["question"]),
        "ground_truth_answer": str(qa["answer"]),
    }
    for key, expected in checks.items():
        if evaluation.get(key) != expected:
            raise RuntimeError(f"fresh prediction mismatch for {question_id}: {key}")
    return evaluation


def _evidence_context(
    conversation_idx: int,
    evidence_ids: list[str],
    dataset: list[dict[str, Any]],
) -> str:
    conversation = dataset[conversation_idx]["conversation"]
    session_dates: dict[str, str] = {}
    for key, value in conversation.items():
        if key.startswith("session_") and key.endswith("_date_time"):
            session_dates[key.removeprefix("session_").removesuffix("_date_time")] = str(
                value
            )
    lookup: dict[str, str] = {}
    for key, turns in conversation.items():
        if not key.startswith("session_") or key.endswith("_date_time"):
            continue
        if not isinstance(turns, list):
            continue
        for turn in turns:
            dia_id = str(turn.get("dia_id") or "")
            if not dia_id:
                continue
            match = re.match(r"D(\d+):", dia_id)
            date_suffix = ""
            if match and session_dates.get(match.group(1)):
                date_suffix = f", said on {session_dates[match.group(1)]}"
            lookup[dia_id] = (
                f"[{dia_id}{date_suffix}] {turn.get('speaker', '')}: "
                f'"{turn.get("text", "")}"'
            )
    return "\n".join(lookup[evidence_id] for evidence_id in evidence_ids if evidence_id in lookup)


def _configure_runtime(server: SeamMem0Server, user_id: str) -> Any:
    runtime = server._adapter._runtime(user_id)
    runtime._retrieval_flags = replace(
        runtime._retrieval_flags_cached(),
        search_top_k=MATCHED_SEARCH_TOP_K,
        context_budget=MATCHED_CONTEXT_BUDGET,
        conversation_adapter="conversation/2",
        inference_policy="inference/high-confidence/1",
        temporal_policy="temporal/1",
    )
    return runtime


def _validate_store(
    runtime: Any,
    *,
    namespace: str,
    expected_turns: set[str],
    conversation_idx: int,
) -> None:
    actual_turns = {
        str(record.attrs.get("content") or "")
        for record in runtime.store.load_ir(ns=namespace, scope="thread").records
        if record.kind.value == "RAW"
    }
    if actual_turns != expected_turns:
        raise RuntimeError(
            f"store {conversation_idx} does not match the canonical dataset turns"
        )


def _case_context(
    *,
    server: SeamMem0Server,
    dataset: list[dict[str, Any]],
    turn_index: dict[int, dict[str, dict[str, Any]]],
    predicted_dir: Path,
    run_id: str,
    question_id: str,
    role: str,
) -> dict[str, Any]:
    conversation_idx, question_idx = _parse_question_id(question_id)
    evaluation = _load_evaluation(predicted_dir, dataset, question_id)
    qa = dataset[conversation_idx]["qa"][question_idx]
    user_id = f"locomo_{conversation_idx}_{run_id}"
    baseline = server._search_raw(user_id, str(qa["question"]), TOP_K)
    graph_rows = server._search_graph_raw(user_id, str(qa["question"]), GRAPH_SLOTS)
    candidate = server._apply_graph_context_policy(
        user_id, str(qa["question"]), baseline, TOP_K
    )

    fresh_rows = list((evaluation.get("retrieval") or {}).get("search_results") or [])
    live_memories = [str(row.get("memory") or "") for row in format_search_results(baseline)]
    fresh_memories = [str(row.get("memory") or "") for row in fresh_rows]
    if live_memories != fresh_memories:
        mismatch = next(
            (
                index
                for index, (live, fresh) in enumerate(
                    zip(live_memories, fresh_memories, strict=False)
                )
                if live != fresh
            ),
            min(len(live_memories), len(fresh_memories)),
        )

        def digest(values: list[str]) -> str:
            encoded = json.dumps(values, ensure_ascii=False, separators=(",", ":"))
            return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]

        raise RuntimeError(
            f"fresh predict-only retrieval mismatch for {question_id}: "
            f"live_rows={len(live_memories)} fresh_rows={len(fresh_memories)} "
            f"first_mismatch={mismatch} live_sha256={digest(live_memories)} "
            f"fresh_sha256={digest(fresh_memories)}"
        )

    envelopes: list[str] = []
    for evidence_id in qa.get("evidence") or []:
        turn = turn_index[conversation_idx].get(str(evidence_id))
        if turn is not None:
            envelopes.append(str(turn["envelope"]))
    baseline_state = evidence_state(baseline, envelopes)
    candidate_state = evidence_state(candidate, envelopes)
    gained = candidate_state["present"] - baseline_state["present"]
    lost = baseline_state["present"] - candidate_state["present"]
    if lost:
        raise RuntimeError(f"candidate displaced exact evidence for {question_id}")

    return {
        "question_id": question_id,
        "category": int(qa["category"]),
        "role": role,
        "evaluation": evaluation,
        "baseline": baseline,
        "candidate": candidate,
        "evidence_context": _evidence_context(
            conversation_idx,
            [str(value) for value in qa.get("evidence") or []],
            dataset,
        ),
        "evidence": {
            "gold_refs": baseline_state["expected"],
            "baseline_hits": baseline_state["hits"],
            "candidate_hits": candidate_state["hits"],
            "gained_refs": len(gained),
            "lost_refs": len(lost),
            "baseline_all": baseline_state["all"],
            "candidate_all": candidate_state["all"],
            "graph_rows": len(graph_rows),
            "rows_added": len(candidate) - len(baseline),
        },
    }


def _sentinel_candidates(
    correct_ids: set[str],
    dataset: list[dict[str, Any]],
    predicted_dir: Path,
    excluded: set[str],
) -> dict[int, list[str]]:
    by_category: dict[int, list[str]] = {1: [], 3: []}
    for question_id in sorted(correct_ids, key=_parse_question_id):
        if question_id in excluded:
            continue
        conversation_idx, question_idx = _parse_question_id(question_id)
        category = int(dataset[conversation_idx]["qa"][question_idx]["category"])
        if category not in by_category:
            continue
        evaluation = _load_evaluation(predicted_dir, dataset, question_id)
        rows = list((evaluation.get("retrieval") or {}).get("search_results") or [])
        if len(rows) < TOP_K:
            by_category[category].append(question_id)
    return by_category


def prepare_cases(
    *,
    dataset_path: Path,
    db_root: Path,
    run_id: str,
    predicted_dir: Path,
    sentinel_record: Path,
    gain_ids: tuple[str, ...],
    sentinels_per_category: int = DEFAULT_SENTINELS_PER_CATEGORY,
) -> list[dict[str, Any]]:
    polluted = [name for name in _BLOCKED_ENV if os.environ.get(name)]
    if polluted:
        raise RuntimeError(
            "graph microgate requires local SQLite retrieval; unset " + ", ".join(polluted)
        )
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(dataset, list):
        raise ValueError("LoCoMo dataset root must be a list")
    turn_index = build_turn_index(dataset)
    correct_ids = _validate_sentinel_record(_load_json(sentinel_record))

    with tempfile.TemporaryDirectory(prefix="seam-graph-microgate-") as temp:
        temp_root = Path(temp)
        _copy_stores(db_root, temp_root, run_id=run_id, conversations=len(dataset))
        server = SeamMem0Server(
            db_path=str(temp_root),
            search_top_k=TOP_K,
            context_budget=8000,
            graph_context_policy=GRAPH_CONTEXT_FILL_V1,
        )
        try:
            for conversation_idx in range(len(dataset)):
                user_id = f"locomo_{conversation_idx}_{run_id}"
                runtime = _configure_runtime(server, user_id)
                expected_turns = {
                    turn["envelope"] for turn in turn_index[conversation_idx].values()
                }
                _validate_store(
                    runtime,
                    namespace=f"locomo:{user_id}",
                    expected_turns=expected_turns,
                    conversation_idx=conversation_idx,
                )

            selected = [
                _case_context(
                    server=server,
                    dataset=dataset,
                    turn_index=turn_index,
                    predicted_dir=predicted_dir,
                    run_id=run_id,
                    question_id=question_id,
                    role="gain",
                )
                for question_id in gain_ids
            ]
            if any(case["evidence"]["gained_refs"] <= 0 for case in selected):
                raise RuntimeError("a declared gain case no longer gains exact evidence")

            sentinel_pool = _sentinel_candidates(
                correct_ids, dataset, predicted_dir, set(gain_ids)
            )
            for category in (1, 3):
                accepted = 0
                for question_id in sentinel_pool[category]:
                    case = _case_context(
                        server=server,
                        dataset=dataset,
                        turn_index=turn_index,
                        predicted_dir=predicted_dir,
                        run_id=run_id,
                        question_id=question_id,
                        role="sentinel",
                    )
                    evidence = case["evidence"]
                    if (
                        evidence["baseline_all"]
                        and evidence["candidate_all"]
                        and evidence["gained_refs"] == 0
                        and evidence["rows_added"] > 0
                    ):
                        selected.append(case)
                        accepted += 1
                        if accepted >= sentinels_per_category:
                            break
                if accepted != sentinels_per_category:
                    raise RuntimeError(
                        f"could not select {sentinels_per_category} category-{category} sentinels"
                    )
            return selected
        finally:
            server.close()


def run_case_arm(
    prompts: Any,
    case: dict[str, Any],
    results: list[dict[str, Any]],
    call: Callable[..., str],
) -> dict[str, Any]:
    evaluation = case["evaluation"]
    category = int(evaluation["category"])
    question = str(evaluation["question"])
    formatted = format_search_results(results)[:TOP_K]
    generation_prompt = prompts.get_answer_generation_prompt(
        question,
        formatted,
        reference_date=evaluation.get("reference_date"),
        user_profile=evaluation.get("user_profile"),
    )
    generated = call(ANSWERER_MODEL, "", generation_prompt, json_mode=False)
    if "ANSWER:" in generated:
        generated = generated.rsplit("ANSWER:", 1)[-1].strip()

    gold = prompts.preprocess_answer(
        category, str(evaluation.get("ground_truth_answer") or "")
    )
    evidence_context = str(case.get("evidence_context") or "")
    if evidence_context:
        judge_prompt = prompts.get_judge_prompt_with_evidence(
            category, question, gold, generated, evidence_context
        )
    else:
        judge_prompt = prompts.get_judge_prompt(category, question, gold, generated)
    raw = call(
        JUDGE_MODEL,
        str(prompts.JUDGE_SYSTEM_PROMPT),
        judge_prompt,
        json_mode=True,
    )
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


def summarize_results(cases: list[dict[str, Any]]) -> dict[str, Any]:
    baseline_correct = sum(int(case["baseline_result"]["correct"]) for case in cases)
    candidate_correct = sum(int(case["candidate_result"]["correct"]) for case in cases)
    sentinel_losses = sum(
        int(
            case["role"] == "sentinel"
            and case["baseline_result"]["correct"]
            and not case["candidate_result"]["correct"]
        )
        for case in cases
    )
    net = candidate_correct - baseline_correct
    return {
        "selected_cases": len(cases),
        "gain_cases": sum(case["role"] == "gain" for case in cases),
        "sentinel_cases": sum(case["role"] == "sentinel" for case in cases),
        "baseline_correct": baseline_correct,
        "candidate_correct": candidate_correct,
        "net_candidate_minus_baseline": net,
        "sentinel_losses": sentinel_losses,
        "promotion_gate": {
            "requires_net_gain": PROMOTION_NET_GAIN,
            "requires_sentinel_losses": 0,
            "passed": net >= PROMOTION_NET_GAIN and sentinel_losses == 0,
        },
    }


class OpenAICaller:
    def __init__(self, client: Any, *, rpm: int) -> None:
        if rpm <= 0:
            raise ValueError("rpm must be positive")
        self.client = client
        self.minimum_interval = 60.0 / rpm
        self.last_started = 0.0
        self.usage: list[dict[str, Any]] = []

    def __call__(
        self,
        model: str,
        system: str,
        user: str,
        *,
        json_mode: bool,
    ) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        request: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 4096,
        }
        if json_mode:
            request["response_format"] = {"type": "json_object"}
        last_error: Exception | None = None
        for attempt in range(5):
            delay = self.minimum_interval - (time.monotonic() - self.last_started)
            if delay > 0:
                time.sleep(delay)
            self.last_started = time.monotonic()
            try:
                response = self.client.chat.completions.create(**request)
                usage = getattr(response, "usage", None)
                prompt_tokens = getattr(usage, "prompt_tokens", None)
                completion_tokens = getattr(usage, "completion_tokens", None)
                self.usage.append(
                    {
                        "role": "judge" if json_mode else "answerer",
                        "model": model,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "cost_usd": estimate_cost_usd(
                            model, prompt_tokens, completion_tokens
                        ),
                    }
                )
                return response.choices[0].message.content or ""
            except Exception as error:  # provider/rate errors: bounded backoff
                last_error = error
                time.sleep(2**attempt)
        raise RuntimeError(f"provider call failed after retries: {last_error}")


def _estimated_paid_boundary(
    cases: list[dict[str, Any]], prompts: Any, *, max_output_tokens: int = 4096
) -> dict[str, Any]:
    import tiktoken

    encoding = tiktoken.get_encoding(encoding_for_model(ANSWERER_MODEL))
    answer_input = 0
    judge_input_floor = 0
    for case in cases:
        evaluation = case["evaluation"]
        for arm in ("baseline", "candidate"):
            generation = prompts.get_answer_generation_prompt(
                str(evaluation["question"]),
                format_search_results(case[arm])[:TOP_K],
                reference_date=evaluation.get("reference_date"),
                user_profile=evaluation.get("user_profile"),
            )
            answer_input += len(encoding.encode(generation))
            judge_input_floor += len(
                encoding.encode(str(prompts.JUDGE_SYSTEM_PROMPT) + str(evaluation["question"]))
            )
    calls = len(cases) * 4
    worst_output = calls * max_output_tokens
    conservative_cost = estimate_cost_usd(
        ANSWERER_MODEL, answer_input + judge_input_floor, worst_output
    )
    return {
        "provider_calls": calls,
        "answer_input_tokens_exact": answer_input,
        "judge_input_tokens_floor": judge_input_floor,
        "max_output_tokens": worst_output,
        "conservative_cost_usd": conservative_cost,
        "pricing_snapshot": PRICING_SNAPSHOT,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Paired paid microgate for canonical-graph-fill/1"
    )
    parser.add_argument("db_root", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--predicted-dir", type=Path, required=True)
    parser.add_argument("--sentinel-record", type=Path, required=True)
    parser.add_argument("--harness-root", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=_DEFAULT_DATASET)
    parser.add_argument(
        "--gain-ids",
        required=True,
        help="comma-separated ids from a currently passing broad-profile free gate",
    )
    parser.add_argument(
        "--sentinels-per-category", type=int, default=DEFAULT_SENTINELS_PER_CATEGORY
    )
    parser.add_argument("--rpm", type=int, default=8)
    parser.add_argument("--max-cost-usd", type=float, default=3.0)
    parser.add_argument("--allow-paid", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    if args.sentinels_per_category <= 0:
        raise ValueError("sentinels-per-category must be positive")
    gain_ids = tuple(value.strip() for value in args.gain_ids.split(",") if value.strip())
    if not gain_ids:
        raise ValueError("at least one gain id is required")
    harness_revision = _validate_harness(args.harness_root.resolve())
    cases = prepare_cases(
        dataset_path=args.dataset,
        db_root=args.db_root,
        run_id=args.run_id,
        predicted_dir=args.predicted_dir,
        sentinel_record=args.sentinel_record,
        gain_ids=gain_ids,
        sentinels_per_category=args.sentinels_per_category,
    )
    prompts = load_harness_prompts(args.harness_root)
    estimate = _estimated_paid_boundary(cases, prompts)
    if estimate["conservative_cost_usd"] is None:
        raise RuntimeError("gpt-4o is missing from the pricing table")
    if float(estimate["conservative_cost_usd"]) > args.max_cost_usd:
        raise RuntimeError(
            f"conservative cost ${estimate['conservative_cost_usd']:.4f} exceeds "
            f"--max-cost-usd ${args.max_cost_usd:.4f}"
        )

    selection = {
        "policy": GRAPH_CONTEXT_FILL_V1,
        "answerer_model": ANSWERER_MODEL,
        "judge_model": JUDGE_MODEL,
        "harness_revision": harness_revision,
        "run_id": args.run_id,
        "retrieval_search_top_k": MATCHED_SEARCH_TOP_K,
        "retrieval_context_budget": MATCHED_CONTEXT_BUDGET,
        "selected_cases": len(cases),
        "gain_cases": sum(case["role"] == "gain" for case in cases),
        "sentinel_cases": sum(case["role"] == "sentinel" for case in cases),
        "case_ids": [case["question_id"] for case in cases],
        "paid_boundary": estimate,
    }
    if not args.allow_paid:
        print(json.dumps({**selection, "paid": False}, indent=2, sort_keys=True))
        return
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not available in the environment")
    if args.out is None:
        raise RuntimeError("--out is required for a paid run")

    from openai import OpenAI

    caller = OpenAICaller(OpenAI(), rpm=args.rpm)
    private_cases: list[dict[str, Any]] = []
    for case in cases:
        baseline_result = run_case_arm(
            prompts, case, case["baseline"], caller
        )
        candidate_result = run_case_arm(
            prompts, case, case["candidate"], caller
        )
        private_cases.append(
            {
                "question_id": case["question_id"],
                "category": case["category"],
                "role": case["role"],
                "evidence": case["evidence"],
                "baseline_result": baseline_result,
                "candidate_result": candidate_result,
            }
        )

    summary = summarize_results(private_cases)
    exact_costs = [row["cost_usd"] for row in caller.usage]
    exact_cost = (
        None
        if any(value is None for value in exact_costs)
        else sum(float(value) for value in exact_costs)
    )
    report = {
        **selection,
        "paid": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "usage": caller.usage,
        "exact_table_priced_cost_usd": exact_cost,
        "cases": private_cases,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                **summary,
                "exact_table_priced_cost_usd": exact_cost,
                "record_written": str(args.out),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
