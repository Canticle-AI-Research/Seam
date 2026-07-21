"""Free structural preflight for versioned ``event-count/distinct`` policies.

This reads a saved Mem0-harness result artifact and rebuilds the SEAM-COUNT
projection for failed cat1 count questions.  It makes no network or provider
calls and writes no output files.  The report intentionally contains aggregate
structure only: no licensed question, answer, or retrieved-memory text.

Example:

    python -m benchmarks.external.mem0_harness.preflight_event_count_context \
      /path/to/mem0-harness-cat13.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from seam_runtime.event_count_context import (
    EVENT_COUNT_DISTINCT_V1,
    EVENT_COUNT_DISTINCT_V2,
    EVENT_COUNT_POLICIES,
    CountEvidence,
    build_count_context_projection,
    is_count_question,
)


def summarize_record(
    payload: dict[str, Any],
    *,
    policy: str = EVENT_COUNT_DISTINCT_V1,
) -> dict[str, Any]:
    """Return aggregate projection diagnostics for failed cat1 count cases."""

    if policy not in EVENT_COUNT_POLICIES or policy == "off":
        raise ValueError(f"unsupported preflight policy {policy!r}")
    cases = []
    state_counts: Counter[str] = Counter()
    observed_promotions = 0
    planned_demotions = 0
    raw_candidates = 0
    selected_cases = 0
    event_groups = 0
    direct_match_groups = 0
    multi_member_groups = 0
    grouped_member_savings = 0

    for evaluation in payload.get("evaluations", []):
        cutoff = (evaluation.get("cutoff_results") or {}).get("top_200") or {}
        question = str(evaluation.get("question") or "")
        if (
            int(evaluation.get("category") or 0) != 1
            or float(cutoff.get("score") or 0.0) >= 1.0
            or not is_count_question(question)
        ):
            continue
        selected_cases += 1

        search_results = (
            (evaluation.get("retrieval") or {}).get("search_results") or []
        )
        evidence = [
            CountEvidence(
                record_id=str(item.get("id") or f"rank:{index}"),
                text=str(item.get("memory") or ""),
                score=float(item.get("score") or 0.0),
                created_at=str(item.get("created_at") or ""),
                original_rank=index,
            )
            for index, item in enumerate(search_results, 1)
            if str(item.get("memory") or "").strip()
        ]
        projection = build_count_context_projection(
            question,
            evidence,
            policy=policy,
        )
        if projection is None:
            continue

        raw_candidates += len(evidence)
        groups: dict[str, list] = {}
        for row in projection.ranked:
            groups.setdefault(row.group_id, []).append(row)
        event_groups += len(groups)
        direct_match_groups += sum(
            any(row.eligible for row in members) for members in groups.values()
        )
        multi_member_groups += sum(len(members) > 1 for members in groups.values())
        grouped_member_savings += sum(
            max(0, len(members) - 1) for members in groups.values()
        )
        per_case_states = Counter(row.state for row in projection.ranked)
        state_counts.update(per_case_states)
        for new_rank, row in enumerate(projection.ranked, 1):
            old_rank = row.evidence.original_rank
            if row.state == "observed" and new_rank < old_rank:
                observed_promotions += 1
            if row.state in {"planned", "negated", "reference-only"} and new_rank > old_rank:
                planned_demotions += 1
        cases.append(
            {
                "candidate_count": len(projection.ranked),
                "event_group_count": len(groups),
                "projection_id": projection.projection_id,
                "direct_match_group_count": sum(
                    any(row.eligible for row in members)
                    for members in groups.values()
                ),
                "states": dict(sorted(per_case_states.items())),
            }
        )

    return {
        "dry_run": True,
        "policy": policy,
        "provider_calls": 0,
        "selected_failed_cat1_count_cases": selected_cases,
        "projected_cases": len(cases),
        "raw_candidates_preserved_in_projection": raw_candidates,
        "observed_rows_promoted": observed_promotions,
        "non_qualifying_rows_demoted": planned_demotions,
        "event_groups": event_groups,
        "direct_match_groups": direct_match_groups,
        "multi_member_groups": multi_member_groups,
        "grouped_member_savings": grouped_member_savings,
        "state_counts": dict(sorted(state_counts.items())),
        "cases": cases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Free structural preflight for event-count/distinct policies"
    )
    parser.add_argument("record", type=Path, help="Mem0-harness JSON result artifact")
    parser.add_argument(
        "--policy",
        choices=sorted(EVENT_COUNT_POLICIES - {"off"}),
        default=EVENT_COUNT_DISTINCT_V2,
        help="projection policy to inspect (default: event-count/distinct/2)",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="omit per-case projection ids and state counts",
    )
    args = parser.parse_args()

    with args.record.open(encoding="utf-8") as handle:
        report = summarize_record(json.load(handle), policy=args.policy)
    if args.summary_only:
        report.pop("cases", None)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
