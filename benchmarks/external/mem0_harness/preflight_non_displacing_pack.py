"""Zero-provider replay gate for the artifact-only non-displacing fact PACK.

This experiment joins a frozen, judged GPT-4o LoCoMo baseline to an auxiliary
GPT-4o-derived-fact retrieval artifact.  It keeps the baseline retrieval rows
as the answerer's logical RAW prefix and attaches one fact plus a bounded set
of novel auxiliary RAW rows inside the protected tail PACK.  No retrieval,
embedding, answerer, judge, or extraction provider is called here.

The checked-in report surface is aggregate plus numeric case metadata only.
The generated candidate artifact contains licensed benchmark text and must be
written to an explicit private path outside the repository.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from benchmarks.external.common.cost_report import encoding_for_model
from benchmarks.external.mem0_harness.microgate_event_count_context import (
    format_search_results,
    load_harness_prompts,
)
from benchmarks.external.mem0_harness.preflight_derived_facts import (
    _DEFAULT_DATASET,
    build_turn_index,
)
from benchmarks.external.mem0_harness.preflight_displacement_audit import (
    fact_source_raw_id,
    is_fact_row,
    run_audit,
)
from benchmarks.external.mem0_harness.upstream_runner import (
    PINNED_HARNESS_REVISION,
    _git_is_clean,
    _git_revision,
)
from seam_runtime.multi_scope_pack import (
    NON_DISPLACING_FACT_POLICY_V1,
    compose_non_displacing_fact_pack,
    expand_logical_raw_rows,
    parse_pack_items,
)

AUDIT_VERSION = "non-displacing-fact-pack-replay/1"
EXPECTED_MODEL = "gpt-4o"
EXPECTED_PROVIDER = "openai"
DEFAULT_CATEGORIES = frozenset({1, 3})
DEFAULT_CONVERSATIONS = frozenset({3, 4, 5})
DEFAULT_EXPECTED_QUESTIONS = 130
DEFAULT_CUTOFF = 200
DEFAULT_FACT_CAP = 1
DEFAULT_NOVEL_RAW_CAP = 3
DEFAULT_MAX_PACK_CHARS = 12_000
DEFAULT_CONTEXT_WINDOW = 128_000
DEFAULT_OUTPUT_RESERVE = 4_096


def _load_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _conversation_idx(evaluation: Mapping[str, Any]) -> int | None:
    value = evaluation.get("conversation_idx")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _in_scope(
    evaluation: Mapping[str, Any],
    *,
    categories: frozenset[int],
    conversations: frozenset[int],
) -> bool:
    try:
        category = int(evaluation.get("category") or 0)
    except (TypeError, ValueError):
        return False
    return category in categories and _conversation_idx(evaluation) in conversations


def _indexed_evaluations(
    payload: Mapping[str, Any],
    *,
    label: str,
    categories: frozenset[int],
    conversations: frozenset[int],
    scoped_only: bool,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    evaluations = payload.get("evaluations")
    if not isinstance(evaluations, list):
        raise ValueError(f"{label} evaluations must be a list")
    selected: list[dict[str, Any]] = []
    by_qid: dict[str, dict[str, Any]] = {}
    for item in evaluations:
        if not isinstance(item, dict):
            raise ValueError(f"{label} evaluation must be an object")
        if scoped_only and not _in_scope(
            item,
            categories=categories,
            conversations=conversations,
        ):
            continue
        qid = str(item.get("question_id") or "")
        if not qid:
            raise ValueError(f"{label} evaluation has no question_id")
        if qid in by_qid:
            raise ValueError(f"{label} has duplicate question_id {qid!r}")
        selected.append(item)
        by_qid[qid] = item
    return selected, by_qid


def _search_rows(evaluation: Mapping[str, Any], *, label: str) -> list[dict[str, Any]]:
    retrieval = evaluation.get("retrieval") or {}
    if not isinstance(retrieval, Mapping):
        raise ValueError(f"{label} retrieval must be an object")
    rows = retrieval.get("search_results")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError(f"{label} retrieval.search_results must be a list of objects")
    return rows


def validate_gpt4o_source_contract(
    baseline_payload: Mapping[str, Any],
    source_config: Mapping[str, Any],
    extraction_stats: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove that both the judged baseline and extracted facts use GPT-4o."""

    metadata = baseline_payload.get("metadata") or {}
    config = source_config.get("config") or {}
    extractor = config.get("extractor") or {}
    errors: list[str] = []
    expected_metadata = {
        "benchmark": "locomo",
        "answerer_model": EXPECTED_MODEL,
        "judge_model": EXPECTED_MODEL,
        "provider": EXPECTED_PROVIDER,
        "top_k": DEFAULT_CUTOFF,
    }
    for key, expected in expected_metadata.items():
        if metadata.get(key) != expected:
            errors.append(f"baseline metadata {key} must be {expected!r}")
    if extractor.get("model") != EXPECTED_MODEL:
        errors.append(f"fact extractor model must be {EXPECTED_MODEL!r}")
    if extractor.get("provider") != EXPECTED_PROVIDER:
        errors.append(f"fact extractor provider must be {EXPECTED_PROVIDER!r}")
    if extractor.get("type") != "openai-multi-speaker-grounded-probe":
        errors.append("fact extractor type must be the cloud multi-speaker probe")
    if config.get("policy") != "multi-speaker-grounded/1":
        errors.append("fact source policy must be multi-speaker-grounded/1")
    provider_calls = extraction_stats.get("provider_calls")
    validated_items = extraction_stats.get("validated_fact_items")
    if not isinstance(provider_calls, int) or provider_calls <= 0:
        errors.append("extraction stats must record positive provider_calls")
    if not isinstance(validated_items, int) or validated_items <= 0:
        errors.append("extraction stats must record positive validated_fact_items")
    if extraction_stats.get("derived_facts_policy") != "multi-speaker-grounded/1":
        errors.append("extraction stats policy must be multi-speaker-grounded/1")
    if errors:
        raise ValueError("GPT-4o source contract mismatch: " + "; ".join(errors))
    return {
        "baseline_answerer_model": EXPECTED_MODEL,
        "baseline_judge_model": EXPECTED_MODEL,
        "fact_extractor_model": EXPECTED_MODEL,
        "provider": EXPECTED_PROVIDER,
        "historical_extraction_provider_calls": provider_calls,
        "historical_validated_fact_items": validated_items,
        "replay_provider_calls": 0,
    }


def build_candidate_payload(
    baseline_payload: Mapping[str, Any],
    auxiliary_payload: Mapping[str, Any],
    *,
    categories: frozenset[int] = DEFAULT_CATEGORIES,
    conversations: frozenset[int] = DEFAULT_CONVERSATIONS,
    expected_questions: int = DEFAULT_EXPECTED_QUESTIONS,
    cutoff: int = DEFAULT_CUTOFF,
    fact_cap: int = DEFAULT_FACT_CAP,
    novel_raw_cap: int = DEFAULT_NOVEL_RAW_CAP,
    max_pack_chars: int = DEFAULT_MAX_PACK_CHARS,
) -> dict[str, Any]:
    """Compose the exact-scope predict-only artifact without external calls."""

    if not categories or not conversations:
        raise ValueError("categories and conversations must be nonempty")
    if expected_questions <= 0 or cutoff <= 0:
        raise ValueError("expected_questions and cutoff must be positive")
    if fact_cap != 1:
        raise ValueError("this exact gate requires fact_cap=1")

    baseline, baseline_by_qid = _indexed_evaluations(
        baseline_payload,
        label="baseline",
        categories=categories,
        conversations=conversations,
        scoped_only=True,
    )
    auxiliary, auxiliary_by_qid = _indexed_evaluations(
        auxiliary_payload,
        label="auxiliary",
        categories=categories,
        conversations=conversations,
        scoped_only=False,
    )
    if len(baseline) != expected_questions:
        raise ValueError(
            f"baseline exact scope has {len(baseline)} questions; "
            f"expected {expected_questions}"
        )
    expected_qids = set(baseline_by_qid)
    auxiliary_qids = set(auxiliary_by_qid)
    if auxiliary_qids != expected_qids:
        missing = len(expected_qids - auxiliary_qids)
        extra = len(auxiliary_qids - expected_qids)
        raise ValueError(
            f"auxiliary coverage mismatch: missing={missing}, extra={extra}"
        )

    candidate_evaluations: list[dict[str, Any]] = []
    for baseline_evaluation in baseline:
        qid = str(baseline_evaluation["question_id"])
        auxiliary_evaluation = auxiliary_by_qid[qid]
        if (
            _conversation_idx(auxiliary_evaluation)
            != _conversation_idx(baseline_evaluation)
            or int(auxiliary_evaluation.get("category") or 0)
            != int(baseline_evaluation.get("category") or 0)
        ):
            raise ValueError(f"auxiliary scope metadata mismatch for {qid}")
        baseline_rows = _search_rows(baseline_evaluation, label=f"baseline {qid}")
        auxiliary_rows = _search_rows(auxiliary_evaluation, label=f"auxiliary {qid}")
        fact_rows = [row for row in auxiliary_rows if is_fact_row(row)]
        raw_rows = [row for row in auxiliary_rows if not is_fact_row(row)]
        if len(fact_rows) != fact_cap:
            raise ValueError(
                f"auxiliary {qid} has {len(fact_rows)} fact rows; expected {fact_cap}"
            )
        composed = compose_non_displacing_fact_pack(
            baseline_rows,
            raw_rows,
            fact_rows,
            limit=cutoff,
            policy=NON_DISPLACING_FACT_POLICY_V1,
            fact_limit=fact_cap,
            novel_raw_limit=novel_raw_cap,
            max_pack_chars=max_pack_chars,
        )
        candidate_evaluation = copy.deepcopy(baseline_evaluation)
        candidate_evaluation.pop("cutoff_results", None)
        retrieval = dict(candidate_evaluation.get("retrieval") or {})
        retrieval["search_results"] = composed
        retrieval["total_results"] = len(composed)
        retrieval["search_latency_ms"] = 0.0
        candidate_evaluation["retrieval"] = retrieval
        candidate_evaluations.append(candidate_evaluation)

    return {
        "metadata": {
            "benchmark": "locomo",
            "artifact": AUDIT_VERSION,
            "predict_only": True,
            "provider_calls": 0,
            "policy": NON_DISPLACING_FACT_POLICY_V1,
            "categories": sorted(categories),
            "conversations": sorted(conversations),
            "top_k": cutoff,
            "fact_cap": fact_cap,
            "novel_raw_cap": novel_raw_cap,
            "max_pack_chars": max_pack_chars,
        },
        "evaluations": candidate_evaluations,
    }


def _logical_case_state(
    baseline_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    *,
    cutoff: int,
) -> dict[str, int | bool]:
    bounded = baseline_rows[:cutoff]
    expected = [
        {"id": str(row.get("id") or ""), "memory": str(row.get("memory") or "")}
        for row in bounded
    ]
    logical = expand_logical_raw_rows(candidate_rows)
    packs = [row for row in candidate_rows if parse_pack_items(row) is not None]
    items = parse_pack_items(packs[0]) if len(packs) == 1 else None
    facts = sum(item.scope == "grounded_fact" for item in items or ())
    sources = sum(item.scope == "raw_source" for item in items or ())
    auxiliary = sum(item.scope == "raw_episode" for item in items or ())
    source_before_fact = False
    if items is not None:
        fact_indexes = [
            index for index, item in enumerate(items) if item.scope == "grounded_fact"
        ]
        source_indexes = [
            index for index, item in enumerate(items) if item.scope == "raw_source"
        ]
        if len(fact_indexes) == len(source_indexes) == 1:
            fact = items[fact_indexes[0]]
            source = items[source_indexes[0]]
            source_before_fact = (
                source_indexes[0] < fact_indexes[0]
                and fact_source_raw_id({"memory": fact.memory}) == source.record_id
            )
    pack_chars = len(str(packs[0].get("memory") or "")) if packs else 0
    prefix_exact = logical is not None and logical[: len(expected)] == expected
    return {
        "baseline_physical_rows": len(bounded),
        "candidate_physical_rows": len(candidate_rows),
        "physical_row_count_stable": len(candidate_rows) == len(bounded),
        "logical_raw_rows": len(logical or ()),
        "logical_raw_prefix_exact": prefix_exact,
        "pack_rows": len(packs),
        "fact_items": facts,
        "source_raw_items": sources,
        "auxiliary_raw_items": auxiliary,
        "source_before_fact": source_before_fact,
        "pack_chars": pack_chars,
    }


def audit_prompt_headroom(
    baseline_evaluations: Sequence[Mapping[str, Any]],
    candidate_evaluations: Sequence[Mapping[str, Any]],
    prompts: Any,
    *,
    model: str = EXPECTED_MODEL,
    cutoff: int = DEFAULT_CUTOFF,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
    output_reserve: int = DEFAULT_OUTPUT_RESERVE,
    token_counter: Callable[[str], int] | None = None,
) -> dict[str, int | bool | str]:
    """Render the pinned answerer prompt and prove it fits the model window."""

    if context_window <= 0 or output_reserve < 0:
        raise ValueError("invalid prompt token budget")
    if token_counter is None:
        import tiktoken

        encoder = tiktoken.get_encoding(encoding_for_model(model))
        def count_tokens(value: str) -> int:
            return len(encoder.encode(value))

        token_counter = count_tokens

    candidate_by_qid = {
        str(evaluation.get("question_id") or ""): evaluation
        for evaluation in candidate_evaluations
    }
    baseline_max = 0
    candidate_max = 0
    delta_max = 0
    for baseline in baseline_evaluations:
        qid = str(baseline.get("question_id") or "")
        candidate = candidate_by_qid.get(qid)
        if candidate is None:
            raise ValueError(f"candidate prompt coverage missing {qid!r}")

        def render(evaluation: Mapping[str, Any]) -> str:
            rows = _search_rows(evaluation, label=f"prompt {qid}")
            formatted = format_search_results(rows)[:cutoff]
            return prompts.get_answer_generation_prompt(
                str(evaluation.get("question") or ""),
                formatted,
                reference_date=evaluation.get("reference_date"),
                user_profile=evaluation.get("user_profile"),
            )

        baseline_tokens = token_counter(render(baseline))
        candidate_tokens = token_counter(render(candidate))
        baseline_max = max(baseline_max, baseline_tokens)
        candidate_max = max(candidate_max, candidate_tokens)
        delta_max = max(delta_max, candidate_tokens - baseline_tokens)
    return {
        "model": model,
        "encoding": encoding_for_model(model),
        "context_window": context_window,
        "output_reserve": output_reserve,
        "max_baseline_prompt_tokens": baseline_max,
        "max_candidate_prompt_tokens": candidate_max,
        "max_prompt_token_delta": delta_max,
        "headroom_tokens": context_window - output_reserve - candidate_max,
        "fits_context": candidate_max + output_reserve <= context_window,
    }


def run_replay(
    baseline_payload: Mapping[str, Any],
    auxiliary_payload: Mapping[str, Any],
    turn_index: list[dict[str, dict[str, str]]],
    prompts: Any,
    *,
    source_contract: Mapping[str, Any],
    categories: frozenset[int] = DEFAULT_CATEGORIES,
    conversations: frozenset[int] = DEFAULT_CONVERSATIONS,
    expected_questions: int = DEFAULT_EXPECTED_QUESTIONS,
    cutoff: int = DEFAULT_CUTOFF,
    fact_cap: int = DEFAULT_FACT_CAP,
    novel_raw_cap: int = DEFAULT_NOVEL_RAW_CAP,
    max_pack_chars: int = DEFAULT_MAX_PACK_CHARS,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
    output_reserve: int = DEFAULT_OUTPUT_RESERVE,
    token_counter: Callable[[str], int] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = build_candidate_payload(
        baseline_payload,
        auxiliary_payload,
        categories=categories,
        conversations=conversations,
        expected_questions=expected_questions,
        cutoff=cutoff,
        fact_cap=fact_cap,
        novel_raw_cap=novel_raw_cap,
        max_pack_chars=max_pack_chars,
    )
    displacement = run_audit(
        dict(baseline_payload),
        candidate,
        turn_index,
        categories=categories,
        cutoff=cutoff,
        expected_conversations=conversations,
    )
    baseline_evaluations, baseline_by_qid = _indexed_evaluations(
        baseline_payload,
        label="baseline",
        categories=categories,
        conversations=conversations,
        scoped_only=True,
    )
    candidate_evaluations, _ = _indexed_evaluations(
        candidate,
        label="candidate",
        categories=categories,
        conversations=conversations,
        scoped_only=False,
    )
    displacement_cases = {
        str(case["question_id"]): case for case in displacement["cases"]
    }

    cases: list[dict[str, Any]] = []
    totals = {
        "questions": 0,
        "questions_with_pack": 0,
        "logical_preservation_failures": 0,
        "physical_row_count_failures": 0,
        "source_order_failures": 0,
        "total_fact_items": 0,
        "total_source_raw_items": 0,
        "total_auxiliary_raw_items": 0,
        "max_pack_chars": 0,
    }
    for candidate_evaluation in candidate_evaluations:
        qid = str(candidate_evaluation["question_id"])
        logical = _logical_case_state(
            _search_rows(baseline_by_qid[qid], label=f"baseline {qid}"),
            _search_rows(candidate_evaluation, label=f"candidate {qid}"),
            cutoff=cutoff,
        )
        totals["questions"] += 1
        totals["questions_with_pack"] += int(logical["pack_rows"] == 1)
        totals["logical_preservation_failures"] += int(
            not logical["logical_raw_prefix_exact"]
        )
        totals["physical_row_count_failures"] += int(
            not logical["physical_row_count_stable"]
        )
        totals["source_order_failures"] += int(not logical["source_before_fact"])
        totals["total_fact_items"] += int(logical["fact_items"])
        totals["total_source_raw_items"] += int(logical["source_raw_items"])
        totals["total_auxiliary_raw_items"] += int(logical["auxiliary_raw_items"])
        totals["max_pack_chars"] = max(
            totals["max_pack_chars"], int(logical["pack_chars"])
        )
        evidence = displacement_cases[qid]
        cases.append(
            {
                "question_id": qid,
                "category": int(candidate_evaluation.get("category") or 0),
                "was_correct": bool(evidence["was_correct"]),
                "gold_present_baseline": int(evidence["gold_present_baseline"]),
                "gold_present_candidate": int(evidence["gold_present_candidate"]),
                "gold_delta": int(evidence["gold_delta"]),
                **logical,
            }
        )

    prompt = audit_prompt_headroom(
        baseline_evaluations,
        candidate_evaluations,
        prompts,
        model=EXPECTED_MODEL,
        cutoff=cutoff,
        context_window=context_window,
        output_reserve=output_reserve,
        token_counter=token_counter,
    )
    evidence_totals = displacement["totals"]
    coverage = displacement["coverage"]
    gates = {
        "exact_scope_coverage": coverage["expected_questions"] == expected_questions
        and coverage["candidate_questions"] == expected_questions
        and coverage["missing_questions"] == 0
        and coverage["duplicate_candidate_qids"] == 0,
        "one_pack_per_question": totals["questions_with_pack"] == expected_questions,
        "one_fact_per_question": totals["total_fact_items"] == expected_questions,
        "one_source_raw_per_question": totals["total_source_raw_items"]
        == expected_questions,
        "source_before_fact": totals["source_order_failures"] == 0,
        "logical_raw_preserved": totals["logical_preservation_failures"] == 0,
        "physical_row_count_stable": totals["physical_row_count_failures"] == 0,
        "pack_char_cap": totals["max_pack_chars"] <= max_pack_chars,
        "miss_gold_gain": evidence_totals["miss_gold_gained"] >= 1,
        "no_miss_gold_loss": evidence_totals["miss_gold_lost"] == 0,
        "no_sentinel_gold_loss": evidence_totals["sentinel_gold_lost"] == 0,
        "prompt_fits_gpt4o_context": bool(prompt["fits_context"]),
        "zero_replay_provider_calls": source_contract.get("replay_provider_calls") == 0,
    }
    report = {
        "audit": AUDIT_VERSION,
        "dry_run": True,
        "paid_provider_calls": 0,
        "policy": NON_DISPLACING_FACT_POLICY_V1,
        "contract": dict(source_contract),
        "parameters": {
            "categories": sorted(categories),
            "conversations": sorted(conversations),
            "expected_questions": expected_questions,
            "cutoff": cutoff,
            "fact_cap": fact_cap,
            "novel_raw_cap": novel_raw_cap,
            "max_pack_chars": max_pack_chars,
        },
        "coverage": coverage,
        "totals": totals,
        "evidence": {
            key: evidence_totals[key]
            for key in (
                "misses",
                "sentinels",
                "miss_gold_gained",
                "miss_gold_lost",
                "sentinel_gold_gained",
                "sentinel_gold_lost",
            )
        },
        "prompt": prompt,
        "gates": gates,
        "gate_passed": all(gates.values()),
        "cases": cases,
    }
    return candidate, report


def _write_new_json(path: Path, payload: Mapping[str, Any]) -> None:
    if not path.parent.is_dir():
        raise FileNotFoundError(f"output parent does not exist: {path.parent}")
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Zero-provider exact-scope non-displacing PACK replay gate"
    )
    parser.add_argument("baseline", type=Path)
    parser.add_argument("auxiliary", type=Path)
    parser.add_argument("--dataset", type=Path, default=_DEFAULT_DATASET)
    parser.add_argument("--source-config", type=Path, required=True)
    parser.add_argument("--extraction-stats", type=Path, required=True)
    parser.add_argument("--harness-root", type=Path, required=True)
    parser.add_argument("--candidate-output", type=Path, required=True)
    parser.add_argument("--report-output", type=Path, required=True)
    parser.add_argument("--categories", type=int, nargs="+", default=[1, 3])
    parser.add_argument(
        "--expected-conversations", type=int, nargs="+", default=[3, 4, 5]
    )
    parser.add_argument("--expected-questions", type=int, default=130)
    parser.add_argument("--cutoff", type=int, default=200)
    parser.add_argument("--fact-cap", type=int, default=1)
    parser.add_argument("--novel-raw-cap", type=int, default=DEFAULT_NOVEL_RAW_CAP)
    parser.add_argument("--max-pack-chars", type=int, default=12_000)
    parser.add_argument("--context-window", type=int, default=128_000)
    parser.add_argument("--output-reserve", type=int, default=4_096)
    args = parser.parse_args()

    revision = _git_revision(args.harness_root)
    if revision != PINNED_HARNESS_REVISION:
        raise RuntimeError(
            f"harness revision mismatch: expected {PINNED_HARNESS_REVISION}, "
            f"got {revision}"
        )
    if not _git_is_clean(args.harness_root):
        raise RuntimeError("upstream harness checkout is not clean")

    baseline_payload = _load_object(args.baseline)
    auxiliary_payload = _load_object(args.auxiliary)
    source_contract = validate_gpt4o_source_contract(
        baseline_payload,
        _load_object(args.source_config),
        _load_object(args.extraction_stats),
    )
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    if not isinstance(dataset, list):
        raise ValueError("LoCoMo dataset root must be a list")
    candidate, report = run_replay(
        baseline_payload,
        auxiliary_payload,
        build_turn_index(dataset),
        load_harness_prompts(args.harness_root),
        source_contract=source_contract,
        categories=frozenset(args.categories),
        conversations=frozenset(args.expected_conversations),
        expected_questions=args.expected_questions,
        cutoff=args.cutoff,
        fact_cap=args.fact_cap,
        novel_raw_cap=args.novel_raw_cap,
        max_pack_chars=args.max_pack_chars,
        context_window=args.context_window,
        output_reserve=args.output_reserve,
    )
    report["inputs"] = {
        "baseline_sha256": _sha256(args.baseline),
        "auxiliary_sha256": _sha256(args.auxiliary),
        "dataset_sha256": _sha256(args.dataset),
        "source_config_sha256": _sha256(args.source_config),
        "extraction_stats_sha256": _sha256(args.extraction_stats),
        "harness_revision": revision,
    }
    _write_new_json(args.candidate_output, candidate)
    report["candidate_sha256"] = _sha256(args.candidate_output)
    _write_new_json(args.report_output, report)
    print(
        json.dumps(
            {
                "audit": AUDIT_VERSION,
                "gate_passed": report["gate_passed"],
                "paid_provider_calls": 0,
                "evidence": report["evidence"],
                "totals": report["totals"],
                "prompt": report["prompt"],
                "gates": report["gates"],
                "candidate_sha256": report["candidate_sha256"],
                "report_sha256": _sha256(args.report_output),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
