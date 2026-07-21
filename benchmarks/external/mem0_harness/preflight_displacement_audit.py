"""Free exact-scope predict-only displacement audit for derived-fact policies.

The #439 handoff names this as the ratchet between the passed representation
free gate and any paid answerer microgate: prove that turning derived facts on
*surfaces* gold evidence without *displacing* the RAW the answerer reads, and
that no previously correct (sentinel) case loses its gold evidence.

This tool is deliberately an auditor, not a benchmark. It consumes two
Mem0-harness result artifacts of the identical schema:

* ``baseline`` -- derived facts OFF (the frozen matched run), and
* ``candidate`` -- ``sentence-grounded-clm/1`` ON, produced by the pinned
  harness in predict-only mode (retrieval recorded, no answerer/judge call).

Both artifacts already carry ``evaluations[].retrieval.search_results`` (the
exact ranked rows the answerer would see), so the audit itself makes **zero**
provider, Ollama, or embedding calls. Producing the candidate artifact is the
heavy, operator-gated step; this comparison is free and fast.

The report is aggregate + per-case NUMERIC only: question ids, categories,
counts, and booleans. It never prints licensed question, answer, turn, or fact
text.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from benchmarks.external.mem0_harness.preflight_derived_facts import (
    _DEFAULT_DATASET,
    build_turn_index,
)

FACT_ROW_PREFIX = "SEAM-FACT/1"

# The displacement gate is clean only when every guard below holds. These are
# the free preconditions for requesting a paid microgate (handoff step 3).
_MIN_MISS_GOLD_NET_GAIN = 1  # facts must surface gold on at least one net miss


def _normalize(value: str) -> str:
    """Casefold and collapse whitespace for robust substring matching."""

    return " ".join(str(value).strip().casefold().split())


def is_fact_row(row: dict[str, Any]) -> bool:
    return str(row.get("memory") or "").startswith(FACT_ROW_PREFIX)


def row_id(row: dict[str, Any]) -> str:
    return str(row.get("id") or "")


def fact_source_raw_id(row: dict[str, Any]) -> str | None:
    """Parse the ``source_raw_id`` embedded in a ``SEAM-FACT/1`` render.

    The render is ``SEAM-FACT/1|<fact-json>\\nSEAM-SOURCE/1|<source-json>``.
    Returns ``None`` if the row is not a well-formed fact render.
    """

    memory = str(row.get("memory") or "")
    if not memory.startswith(FACT_ROW_PREFIX):
        return None
    head = memory.split("\n", 1)[0]
    _, _, payload = head.partition("|")
    try:
        fact = json.loads(payload)
    except (ValueError, TypeError):
        return None
    if not isinstance(fact, dict):
        return None
    source_raw_id = fact.get("source_raw_id")
    return str(source_raw_id) if source_raw_id is not None else None


def gold_texts_for(
    evaluation: dict[str, Any],
    turn_index: list[dict[str, dict[str, str]]],
) -> list[str]:
    """Normalized gold-evidence turn texts for one evaluation."""

    conv_idx = int(evaluation.get("conversation_idx") or 0)
    turns = turn_index[conv_idx] if 0 <= conv_idx < len(turn_index) else {}
    texts: list[str] = []
    for dia_id in evaluation.get("evidence") or []:
        turn = turns.get(str(dia_id))
        if turn is None:
            continue
        normalized = _normalize(turn.get("text") or "")
        if normalized:
            texts.append(normalized)
    return texts


def _gold_present(
    rows: list[dict[str, Any]],
    gold_texts: list[str],
    *,
    cutoff: int,
) -> int:
    """Count gold turns whose text appears in any row within ``cutoff``.

    A gold turn counts as present if its normalized text is a substring of a
    RAW row's memory, OR of a fact row's memory (the ``SEAM-SOURCE/1`` clause
    embeds the exact source text, so a fact can surface gold a RAW row missed).
    """

    if not gold_texts:
        return 0
    haystack = [_normalize(r.get("memory") or "") for r in rows[:cutoff]]
    found = 0
    for gold in gold_texts:
        if any(gold and gold in row_text for row_text in haystack):
            found += 1
    return found


def _ordering_violations(rows: list[dict[str, Any]]) -> int:
    """Facts that appear before their source RAW row (contract breach)."""

    seen_raw_ids: set[str] = set()
    violations = 0
    for row in rows:
        if is_fact_row(row):
            source = fact_source_raw_id(row)
            if source is not None and source not in seen_raw_ids:
                violations += 1
        else:
            rid = row_id(row)
            if rid:
                seen_raw_ids.add(rid)
    return violations


def _ceiling_violations(rows: list[dict[str, Any]], *, cutoff: int) -> int:
    """Prefix positions where facts exceed the 20% derived-fact ceiling."""

    fact_count = 0
    violations = 0
    for position, row in enumerate(rows[:cutoff], start=1):
        if is_fact_row(row):
            fact_count += 1
        # <=20% means facts*5 must not exceed the prefix length.
        if fact_count * 5 > position:
            violations += 1
    return violations


def displacement_for_question(
    baseline_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    gold_texts: list[str],
    *,
    was_correct: bool,
    cutoff: int,
) -> dict[str, Any]:
    """Per-question displacement facts. Pure; no external calls."""

    baseline_raw_ids = {
        row_id(r) for r in baseline_rows[:cutoff] if not is_fact_row(r) and row_id(r)
    }
    candidate_raw_ids = {
        row_id(r) for r in candidate_rows[:cutoff] if not is_fact_row(r) and row_id(r)
    }
    fact_rows = sum(1 for r in candidate_rows[:cutoff] if is_fact_row(r))
    raw_displaced = len(baseline_raw_ids - candidate_raw_ids)

    gold_base = _gold_present(baseline_rows, gold_texts, cutoff=cutoff)
    gold_cand = _gold_present(candidate_rows, gold_texts, cutoff=cutoff)
    gold_delta = gold_cand - gold_base

    return {
        "was_correct": was_correct,
        "gold_total": len(gold_texts),
        "gold_present_baseline": gold_base,
        "gold_present_candidate": gold_cand,
        "gold_delta": gold_delta,
        "gold_gained": gold_delta > 0,
        "gold_lost": gold_delta < 0,
        "fact_rows": fact_rows,
        "raw_displaced": raw_displaced,
        "ordering_violations": _ordering_violations(candidate_rows[:cutoff]),
        "ceiling_violations": _ceiling_violations(candidate_rows, cutoff=cutoff),
        # A sentinel loss is the one hard-blocking failure: a previously correct
        # case whose gold evidence dropped out of the served context.
        "sentinel_gold_loss": bool(was_correct and gold_delta < 0),
    }


def _was_correct(evaluation: dict[str, Any]) -> bool:
    score = (
        (evaluation.get("cutoff_results") or {})
        .get("top_200", {})
        .get("score")
    )
    try:
        return float(score) >= 1.0
    except (TypeError, ValueError):
        return False


def _conversation_idx(evaluation: dict[str, Any]) -> int | None:
    value = evaluation.get("conversation_idx")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def run_audit(
    baseline_payload: dict[str, Any],
    candidate_payload: dict[str, Any],
    turn_index: list[dict[str, dict[str, str]]],
    *,
    categories: frozenset[int] = frozenset({1, 3}),
    cutoff: int = 200,
    limit: int | None = None,
    expected_conversations: frozenset[int],
) -> dict[str, Any]:
    """Compare a baseline and candidate artifact for displacement.

    Evaluations are joined on ``question_id``. Coverage is a hard gate: every
    baseline question in the declared conversation/category scope must appear
    exactly once in the candidate so omitted regressions cannot disappear.
    """

    candidate_evals = list(candidate_payload.get("evaluations", []))
    candidate_by_qid: dict[str, dict[str, Any]] = {}
    duplicate_candidate_qids: set[str] = set()
    for evaluation in candidate_evals:
        qid = str(evaluation.get("question_id"))
        if qid in candidate_by_qid:
            duplicate_candidate_qids.add(qid)
        candidate_by_qid[qid] = evaluation

    scope_conversations = expected_conversations
    if not scope_conversations:
        raise ValueError("expected_conversations must be nonempty")

    expected_baseline_evals = [
        ev
        for ev in baseline_payload.get("evaluations", [])
        if int(ev.get("category") or 0) in categories
        and (
            not scope_conversations
            or _conversation_idx(ev) in scope_conversations
        )
    ]
    if limit is not None:
        expected_baseline_evals = expected_baseline_evals[:limit]

    expected_qids = {
        str(evaluation.get("question_id"))
        for evaluation in expected_baseline_evals
    }
    candidate_qids = set(candidate_by_qid)
    missing_qids = expected_qids - candidate_qids
    baseline_evals = [
        evaluation
        for evaluation in expected_baseline_evals
        if str(evaluation.get("question_id")) in candidate_by_qid
    ]
    expected_sentinels = sum(_was_correct(ev) for ev in expected_baseline_evals)
    expected_misses = len(expected_baseline_evals) - expected_sentinels

    totals = {
        "questions": 0,
        "misses": 0,
        "sentinels": 0,
        "miss_gold_gained": 0,
        "miss_gold_lost": 0,
        "sentinel_gold_gained": 0,
        "sentinel_gold_lost": 0,
        "questions_with_facts": 0,
        "total_fact_rows": 0,
        "total_raw_displaced": 0,
        "ordering_violations": 0,
        "ceiling_violations": 0,
    }
    cases: list[dict[str, Any]] = []

    for evaluation in baseline_evals:
        qid = str(evaluation.get("question_id"))
        candidate = candidate_by_qid[qid]
        baseline_rows = list(
            (evaluation.get("retrieval") or {}).get("search_results") or []
        )
        candidate_rows = list(
            (candidate.get("retrieval") or {}).get("search_results") or []
        )
        gold_texts = gold_texts_for(evaluation, turn_index)
        was_correct = _was_correct(evaluation)
        result = displacement_for_question(
            baseline_rows,
            candidate_rows,
            gold_texts,
            was_correct=was_correct,
            cutoff=cutoff,
        )

        totals["questions"] += 1
        if was_correct:
            totals["sentinels"] += 1
            if result["gold_gained"]:
                totals["sentinel_gold_gained"] += 1
            if result["gold_lost"]:
                totals["sentinel_gold_lost"] += 1
        else:
            totals["misses"] += 1
            if result["gold_gained"]:
                totals["miss_gold_gained"] += 1
            if result["gold_lost"]:
                totals["miss_gold_lost"] += 1
        if result["fact_rows"]:
            totals["questions_with_facts"] += 1
        totals["total_fact_rows"] += result["fact_rows"]
        totals["total_raw_displaced"] += result["raw_displaced"]
        totals["ordering_violations"] += result["ordering_violations"]
        totals["ceiling_violations"] += result["ceiling_violations"]

        cases.append(
            {
                "question_id": qid,
                "category": int(evaluation.get("category") or 0),
                **result,
            }
        )

    miss_net_gold_gain = totals["miss_gold_gained"] - totals["miss_gold_lost"]
    gates = {
        "coverage_complete": bool(expected_qids)
        and not missing_qids
        and not duplicate_candidate_qids,
        # Hard block: no previously correct case may lose gold evidence.
        "no_sentinel_gold_loss": totals["sentinel_gold_lost"] == 0,
        # Contract: a fact never precedes its source RAW, and the 20% ceiling
        # holds at every prefix.
        "ordering_clean": totals["ordering_violations"] == 0,
        "ceiling_clean": totals["ceiling_violations"] == 0,
        # Upside: facts must net-surface gold on the miss set, else the lever
        # buys nothing and is not worth a paid microgate.
        "miss_gold_net_gain": miss_net_gold_gain >= _MIN_MISS_GOLD_NET_GAIN,
    }

    return {
        "dry_run": True,
        "paid_provider_calls": 0,
        "audit": "displacement/1",
        "categories": sorted(categories),
        "cutoff": cutoff,
        "limit": limit,
        "coverage": {
            "expected_conversations": sorted(scope_conversations),
            "expected_questions": len(expected_qids),
            "expected_misses": expected_misses,
            "expected_sentinels": expected_sentinels,
            "candidate_questions": len(candidate_qids & expected_qids),
            "missing_questions": len(missing_qids),
            "duplicate_candidate_qids": len(duplicate_candidate_qids),
        },
        "thresholds": {"min_miss_gold_net_gain": _MIN_MISS_GOLD_NET_GAIN},
        "totals": totals,
        "miss_net_gold_gain": miss_net_gold_gain,
        "gates": gates,
        "gate_passed": all(gates.values()),
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Free exact-scope predict-only derived-fact displacement audit"
    )
    parser.add_argument("baseline", type=Path, help="derived-facts-OFF matched artifact")
    parser.add_argument(
        "candidate",
        type=Path,
        help="derived-facts candidate predict-only artifact (same schema)",
    )
    parser.add_argument("--dataset", type=Path, default=_DEFAULT_DATASET)
    parser.add_argument("--categories", type=int, nargs="+", default=[1, 3])
    parser.add_argument("--cutoff", type=int, default=200)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--expected-conversations",
        type=int,
        nargs="+",
        required=True,
        help="hard coverage scope; every matching baseline question must exist",
    )
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()

    with args.baseline.open(encoding="utf-8") as handle:
        baseline_payload = json.load(handle)
    with args.candidate.open(encoding="utf-8") as handle:
        candidate_payload = json.load(handle)
    with args.dataset.open(encoding="utf-8") as handle:
        dataset = json.load(handle)

    report = run_audit(
        baseline_payload,
        candidate_payload,
        build_turn_index(dataset),
        categories=frozenset(args.categories),
        cutoff=args.cutoff,
        limit=args.limit,
        expected_conversations=frozenset(args.expected_conversations),
    )
    if args.summary_only:
        report.pop("cases", None)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
