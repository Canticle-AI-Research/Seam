"""Provider-free evidence/displacement gate for reserved multi-scope PACK.

The candidate preserves the final baseline RAW row verbatim inside one
direct-readable PACK row, then uses bounded content quotas for grounded facts,
entity/relationship evidence, date-diverse temporal evidence, and deeper RAW
episodes.  The report emits only counts and case ids, never licensed text.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from benchmarks.external.mem0_harness.preflight_derived_facts import (
    _DEFAULT_DATASET,
    build_turn_index,
)
from benchmarks.external.mem0_harness.preflight_graph_memory import (
    MATCHED_CONTEXT_BUDGET,
    MATCHED_SEARCH_TOP_K,
    _copy_stores,
    _parse_categories,
)
from benchmarks.external.mem0_harness.seam_mem0_server import SeamMem0Server
from seam_runtime.multi_scope_pack import POLICY_V1, pack_scope_counts

_BLOCKED_ENV = (
    "SEAM_PGVECTOR_DSN",
    "PGVECTOR_TEST_DSN",
    "SEAM_EMBEDDING_PROVIDER",
)


def _memory(row: dict[str, Any]) -> str:
    return str(row.get("memory") or "")


def is_multi_scope_pack(row: dict[str, Any]) -> bool:
    return str(row.get("id") or "").startswith(
        "seam-multiscope-1-"
    ) and _memory(row).startswith("SEAM-MULTISCOPE/1|")


def direct_evidence_state(
    rows: Iterable[dict[str, Any]],
    envelopes: Iterable[str],
) -> dict[str, Any]:
    """Count exact RAW rows or exact bodies inside a validated v1 PACK."""

    expected = tuple(dict.fromkeys(envelopes))
    raw_memories: set[str] = set()
    pack_memories: list[str] = []
    for row in rows:
        memory = _memory(row)
        if is_multi_scope_pack(row):
            pack_memories.append(memory)
        else:
            raw_memories.add(memory)
    present = tuple(
        envelope
        for envelope in expected
        if envelope in raw_memories
        or any(envelope in pack for pack in pack_memories)
    )
    return {
        "expected": len(expected),
        "hits": len(present),
        "any": bool(present),
        "all": bool(expected) and len(present) == len(expected),
        "present": frozenset(present),
    }


def measure_case(
    *,
    question_id: str,
    category: int,
    envelopes: list[str],
    baseline: list[dict[str, Any]],
    candidate: list[dict[str, Any]],
) -> dict[str, Any]:
    baseline_state = direct_evidence_state(baseline, envelopes)
    candidate_state = direct_evidence_state(candidate, envelopes)
    gained = candidate_state["present"] - baseline_state["present"]
    lost = baseline_state["present"] - candidate_state["present"]
    packs = [row for row in candidate if is_multi_scope_pack(row)]
    counts = pack_scope_counts(packs[0]) if packs else {}
    return {
        "question_id": question_id,
        "category": category,
        "gold_refs": baseline_state["expected"],
        "baseline_hits": baseline_state["hits"],
        "candidate_hits": candidate_state["hits"],
        "baseline_any": baseline_state["any"],
        "candidate_any": candidate_state["any"],
        "baseline_all": baseline_state["all"],
        "candidate_all": candidate_state["all"],
        "gained_refs": len(gained),
        "lost_refs": len(lost),
        "gained_any": candidate_state["any"] and not baseline_state["any"],
        "lost_any": baseline_state["any"] and not candidate_state["any"],
        "gained_all": candidate_state["all"] and not baseline_state["all"],
        "lost_all": baseline_state["all"] and not candidate_state["all"],
        "baseline_rows": len(baseline),
        "candidate_rows": len(candidate),
        "pack_rows": len(packs),
        "pack_chars": len(_memory(packs[0])) if packs else 0,
        "pack_items": sum(counts.values()),
        **{f"scope_{scope}": count for scope, count in counts.items()},
    }


def summarize_cases(
    cases: list[dict[str, Any]],
    *,
    unresolved_refs: int,
) -> dict[str, Any]:
    fields = sorted(
        {
            key
            for case in cases
            for key, value in case.items()
            if key not in {"question_id", "category"}
            and isinstance(value, (bool, int))
        }
    )
    summary: dict[str, Any] = {
        "cases": len(cases),
        "unresolved_refs": unresolved_refs,
    }
    for field in fields:
        summary[field] = sum(int(case.get(field, 0)) for case in cases)
    summary["max_pack_chars"] = max(
        (int(case["pack_chars"]) for case in cases),
        default=0,
    )
    summary["gate"] = {
        "requires_gained_refs": 1,
        "requires_lost_refs": 0,
        "passed": summary.get("gained_refs", 0) >= 1
        and summary.get("lost_refs", 0) == 0,
    }
    return summary


def run_preflight(
    *,
    dataset_path: Path,
    db_root: Path,
    run_id: str,
    categories: frozenset[int],
    top_k: int,
    limit: int | None = None,
) -> dict[str, Any]:
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    polluted = [name for name in _BLOCKED_ENV if os.environ.get(name)]
    if polluted:
        raise RuntimeError(
            "multi-scope preflight requires local SQLite retrieval; unset "
            + ", ".join(polluted)
        )
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(dataset, list):
        raise ValueError("LoCoMo dataset root must be a list")
    turn_index = build_turn_index(dataset)

    with tempfile.TemporaryDirectory(prefix="seam-multiscope-preflight-") as temp:
        temp_root = Path(temp)
        _copy_stores(
            db_root,
            temp_root,
            run_id=run_id,
            conversations=len(dataset),
        )
        server = SeamMem0Server(
            db_path=str(temp_root),
            search_top_k=top_k,
            context_budget=MATCHED_CONTEXT_BUDGET,
            multi_scope_pack_policy=POLICY_V1,
        )
        cases: list[dict[str, Any]] = []
        unresolved_refs = 0
        try:
            for conversation_idx, conversation in enumerate(dataset):
                user_id = f"locomo_{conversation_idx}_{run_id}"
                runtime = server._adapter._runtime(user_id)
                runtime._retrieval_flags = replace(
                    runtime._retrieval_flags_cached(),
                    search_top_k=MATCHED_SEARCH_TOP_K,
                    context_budget=MATCHED_CONTEXT_BUDGET,
                    conversation_adapter="conversation/2",
                    inference_policy="inference/high-confidence/1",
                    temporal_policy="temporal/1",
                )
                expected_turns = {
                    turn["envelope"]
                    for turn in turn_index[conversation_idx].values()
                }
                actual_turns = {
                    str(record.attrs.get("content") or "")
                    for record in runtime.store.load_ir(
                        ns=f"locomo:{user_id}",
                        scope="thread",
                    ).records
                    if record.kind.value == "RAW"
                }
                if actual_turns != expected_turns:
                    raise RuntimeError(
                        f"store {conversation_idx} does not match the canonical dataset turns"
                    )

                for question_idx, qa in enumerate(conversation.get("qa") or []):
                    category = int(qa.get("category") or 0)
                    if category not in categories:
                        continue
                    envelopes: list[str] = []
                    for evidence_id in qa.get("evidence") or []:
                        turn = turn_index[conversation_idx].get(str(evidence_id))
                        if turn is None:
                            unresolved_refs += 1
                        else:
                            envelopes.append(turn["envelope"])
                    query = str(qa.get("question") or "")
                    baseline = server._search_raw(user_id, query, top_k)
                    candidate = server._apply_multi_scope_pack_policy(
                        user_id,
                        query,
                        baseline,
                        top_k,
                    )
                    cases.append(
                        measure_case(
                            question_id=f"conv{conversation_idx}_q{question_idx}",
                            category=category,
                            envelopes=envelopes,
                            baseline=baseline,
                            candidate=candidate,
                        )
                    )
                    if limit is not None and len(cases) >= limit:
                        break
                if limit is not None and len(cases) >= limit:
                    break
        finally:
            server.close()

    changed = [
        case
        for case in cases
        if case["gained_refs"] or case["lost_refs"]
    ]
    return {
        "contract": {
            "dataset": str(dataset_path),
            "run_id": run_id,
            "categories": sorted(categories),
            "top_k": top_k,
            "retrieval_search_top_k": MATCHED_SEARCH_TOP_K,
            "retrieval_context_budget": MATCHED_CONTEXT_BUDGET,
            "baseline": "matched-facade-raw",
            "candidate": POLICY_V1,
            "provider_calls": 0,
        },
        "summary": summarize_cases(
            cases,
            unresolved_refs=unresolved_refs,
        ),
        "changed_cases": changed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Free reserved multi-scope PACK evidence/displacement gate."
    )
    parser.add_argument("db_root", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--dataset", type=Path, default=_DEFAULT_DATASET)
    parser.add_argument(
        "--categories",
        type=_parse_categories,
        default=frozenset({1, 3}),
    )
    parser.add_argument("--top-k", type=int, default=200)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--summary-only", action="store_true")
    args = parser.parse_args()
    report = run_preflight(
        dataset_path=args.dataset,
        db_root=args.db_root,
        run_id=args.run_id,
        categories=args.categories,
        top_k=args.top_k,
        limit=args.limit,
    )
    if args.summary_only:
        report.pop("changed_cases", None)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
