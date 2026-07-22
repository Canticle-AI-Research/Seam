"""Zero-provider fact-free ablation of the non-displacing PACK gate.

HISTORY#450 proved the non-displacing PACK passes the exact 130-question gate
(+1 miss, +1 sentinel, zero loss), but an independent recomputation found both
gains come from auxiliary RAW *episodes* -- neither matches the GPT-4o fact nor
its mandatory source item.  This replay isolates that finding: it re-runs the
identical gate with the grounded fact and its source row removed, keeping the
**same auxiliary episode ids** the fact-bearing PACK selected.

To hold the episode set byte-identical, each question first re-composes the
frozen fact-bearing PACK, reads the ``raw_episode`` items it chose, and repacks
exactly those episodes behind the protected RAW tail with no fact and no source
(``raw_protected -> raw_episode x 0..N``).  If the two gains survive, the fact
and source rows are dead weight and the generic auxiliary-RAW PACK carries
forward; if a gain disappears, the fact/source was load-bearing after all.

No retrieval, embedding, answerer, judge, or extraction provider is called.  The
checked-in report is aggregate plus numeric case metadata only; the generated
candidate carries licensed benchmark text and must be written outside the repo.
"""

from __future__ import annotations

import argparse
import copy
import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from benchmarks.external.mem0_harness.microgate_event_count_context import (
    load_harness_prompts,
)
from benchmarks.external.mem0_harness.preflight_derived_facts import (
    _DEFAULT_DATASET,
    build_turn_index,
)
from benchmarks.external.mem0_harness.preflight_displacement_audit import (
    is_fact_row,
    run_audit,
)
from benchmarks.external.mem0_harness.preflight_non_displacing_pack import (
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_CUTOFF,
    DEFAULT_EXPECTED_QUESTIONS,
    DEFAULT_FACT_CAP,
    DEFAULT_MAX_PACK_CHARS,
    DEFAULT_NOVEL_RAW_CAP,
    DEFAULT_OUTPUT_RESERVE,
    EXPECTED_MODEL,
    _indexed_evaluations,
    _load_object,
    _search_rows,
    _sha256,
    _write_new_json,
    audit_prompt_headroom,
    validate_candidate_output_path,
    validate_gpt4o_source_contract,
)
from benchmarks.external.mem0_harness.upstream_runner import (
    PINNED_HARNESS_REVISION,
    _git_is_clean,
    _git_revision,
)
from seam_runtime.multi_scope_pack import (
    NON_DISPLACING_FACT_POLICY_V1,
    NON_DISPLACING_RAW_POLICY_V1,
    compose_non_displacing_fact_pack,
    compose_non_displacing_raw_pack,
    expand_logical_raw_pack_rows,
    parse_pack_items,
    parse_raw_pack_items,
)

AUDIT_VERSION = "non-displacing-raw-pack-replay/1"
DEFAULT_CATEGORIES = frozenset({1, 3})
DEFAULT_CONVERSATIONS = frozenset({3, 4, 5})


def _conversation_idx(evaluation: Mapping[str, Any]) -> int | None:
    value = evaluation.get("conversation_idx")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _fact_version_episode_rows(fact_pack_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """Read the exact ``raw_episode`` ids the fact-bearing PACK selected.

    Returns the ordered episode rows so the fact-free composer repacks the same
    ids.  An empty list means the fact PACK held no auxiliary episode (or the
    question produced no PACK), so the fact-free candidate keeps baseline RAW.
    """

    if not fact_pack_rows:
        return []
    tail = fact_pack_rows[-1]
    items = parse_pack_items(tail)
    if items is None:
        return []
    return [
        {"id": item.record_id, "memory": item.memory}
        for item in items
        if item.scope == "raw_episode"
    ]


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
    """Compose the fact-free exact-scope predict-only artifact, $0 provider calls."""

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
        # Pin the episode set to exactly what the frozen fact PACK selected, then
        # repack those same ids with the fact and source rows removed.
        fact_pack = compose_non_displacing_fact_pack(
            baseline_rows,
            raw_rows,
            fact_rows,
            limit=cutoff,
            policy=NON_DISPLACING_FACT_POLICY_V1,
            fact_limit=fact_cap,
            novel_raw_limit=novel_raw_cap,
            max_pack_chars=max_pack_chars,
        )
        episode_rows = _fact_version_episode_rows(fact_pack)
        composed = compose_non_displacing_raw_pack(
            baseline_rows,
            episode_rows,
            limit=cutoff,
            policy=NON_DISPLACING_RAW_POLICY_V1,
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
            "policy": NON_DISPLACING_RAW_POLICY_V1,
            "episode_source": NON_DISPLACING_FACT_POLICY_V1,
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
    logical = expand_logical_raw_pack_rows(candidate_rows)
    packs = [row for row in candidate_rows if parse_raw_pack_items(row) is not None]
    items = parse_raw_pack_items(packs[0]) if len(packs) == 1 else None
    auxiliary = sum(item.scope == "raw_episode" for item in items or ())
    fact_items = sum(is_fact_row(row) for row in candidate_rows)
    pack_chars = len(str(packs[0].get("memory") or "")) if packs else 0
    prefix_exact = logical is not None and logical[: len(expected)] == expected
    return {
        "baseline_physical_rows": len(bounded),
        "candidate_physical_rows": len(candidate_rows),
        "physical_row_count_stable": len(candidate_rows) == len(bounded),
        "logical_raw_rows": len(logical or ()),
        "logical_raw_prefix_exact": prefix_exact,
        "pack_rows": len(packs),
        "fact_items": fact_items,
        "auxiliary_raw_items": auxiliary,
        "pack_chars": pack_chars,
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
        "total_fact_items": 0,
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
        totals["total_fact_items"] += int(logical["fact_items"])
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
        # The ablation's defining property: no derived fact or source row is
        # served anywhere in the candidate.
        "no_fact_items": totals["total_fact_items"] == 0,
        "logical_raw_preserved": totals["logical_preservation_failures"] == 0,
        "physical_row_count_stable": totals["physical_row_count_failures"] == 0,
        "pack_char_cap": totals["max_pack_chars"] <= max_pack_chars,
        # The hypothesis under test: the auxiliary RAW episodes alone still
        # surface gold on the miss set without the fact.
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
        "policy": NON_DISPLACING_RAW_POLICY_V1,
        "episode_source": NON_DISPLACING_FACT_POLICY_V1,
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Zero-provider fact-free non-displacing RAW PACK replay gate"
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

    validate_candidate_output_path(args.candidate_output)

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
