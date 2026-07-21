"""Provider-free matched-harness evidence/displacement gate for graph memory.

The probe compares the Mem0 facade's frozen RAW retrieval with candidates that
either fill unused result rows or reserve a bounded tail for RAW evidence
reached through SEAM's canonical ``knowledge_edges`` graph retriever. It
consumes existing facade SQLite stores, copies them to a temporary directory
before the graph backfill, and never emits licensed question, answer,
conversation, or memory text.

This is an evidence-presence gate, not an answer score or a product-policy
promotion.  A passing candidate must add at least one exact gold evidence turn
without displacing any exact gold turn already present in the baseline.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from benchmarks.external.mem0_harness.preflight_derived_facts import (
    _DEFAULT_DATASET,
    build_turn_index,
)
from benchmarks.external.mem0_harness.seam_mem0_server import (
    SeamMem0Server,
    append_unique_graph_rows,
)

_BLOCKED_ENV = (
    "SEAM_PGVECTOR_DSN",
    "PGVECTOR_TEST_DSN",
    "SEAM_EMBEDDING_PROVIDER",
)
_COMPOSITIONS = frozenset({"fill-only", "reserved-tail"})
MATCHED_SEARCH_TOP_K = 300
MATCHED_CONTEXT_BUDGET = 60000


def _memory(row: dict[str, Any]) -> str:
    return str(row.get("memory") or "")


def compose_graph_rows(
    baseline: list[dict[str, Any]],
    graph_rows: list[dict[str, Any]],
    *,
    limit: int,
    graph_slots: int,
    composition: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compose graph-unique rows under one explicit displacement contract."""

    if composition not in _COMPOSITIONS:
        raise ValueError(f"unknown graph composition: {composition}")

    baseline = baseline[:limit]
    baseline_memories = {_memory(row) for row in baseline}
    available = (
        max(0, limit - len(baseline))
        if composition == "fill-only"
        else graph_slots
    )
    unique_limit = min(graph_slots, available)
    if unique_limit == 0:
        return baseline, []
    unique_graph: list[dict[str, Any]] = []
    seen = set(baseline_memories)
    for row in graph_rows:
        content = _memory(row)
        if not content or content in seen:
            continue
        seen.add(content)
        unique_graph.append(row)
        if len(unique_graph) >= unique_limit:
            break
    if composition == "fill-only":
        return (
            append_unique_graph_rows(baseline, unique_graph, limit=limit),
            unique_graph,
        )
    keep = max(0, limit - len(unique_graph))
    candidate = [*baseline[:keep], *unique_graph]
    return candidate[:limit], unique_graph


def compose_reserved_graph_rows(
    baseline: list[dict[str, Any]],
    graph_rows: list[dict[str, Any]],
    *,
    limit: int,
    graph_slots: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compatibility wrapper for the aggressive reserved-tail composition."""

    return compose_graph_rows(
        baseline,
        graph_rows,
        limit=limit,
        graph_slots=graph_slots,
        composition="reserved-tail",
    )


def evidence_state(
    rows: Iterable[dict[str, Any]],
    envelopes: Iterable[str],
) -> dict[str, Any]:
    expected = tuple(dict.fromkeys(envelopes))
    memories = {_memory(row) for row in rows}
    present = tuple(envelope for envelope in expected if envelope in memories)
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
    graph_rows: list[dict[str, Any]],
    top_k: int,
    graph_slots: int,
    composition: str = "reserved-tail",
) -> dict[str, Any]:
    candidate, unique_graph = compose_graph_rows(
        baseline,
        graph_rows,
        limit=top_k,
        graph_slots=graph_slots,
        composition=composition,
    )
    baseline_state = evidence_state(baseline, envelopes)
    graph_state = evidence_state(graph_rows, envelopes)
    candidate_state = evidence_state(candidate, envelopes)
    gained_refs = candidate_state["present"] - baseline_state["present"]
    lost_refs = baseline_state["present"] - candidate_state["present"]
    return {
        "question_id": question_id,
        "category": category,
        "gold_refs": baseline_state["expected"],
        "baseline_hits": baseline_state["hits"],
        "graph_hits": graph_state["hits"],
        "candidate_hits": candidate_state["hits"],
        "baseline_any": baseline_state["any"],
        "graph_any": graph_state["any"],
        "candidate_any": candidate_state["any"],
        "baseline_all": baseline_state["all"],
        "graph_all": graph_state["all"],
        "candidate_all": candidate_state["all"],
        "gained_refs": len(gained_refs),
        "lost_refs": len(lost_refs),
        "gained_any": candidate_state["any"] and not baseline_state["any"],
        "lost_any": baseline_state["any"] and not candidate_state["any"],
        "gained_all": candidate_state["all"] and not baseline_state["all"],
        "lost_all": baseline_state["all"] and not candidate_state["all"],
        "baseline_rows": min(len(baseline), top_k),
        "graph_rows": len(graph_rows),
        "unique_graph_rows": len(unique_graph),
        "candidate_rows": len(candidate),
    }


def summarize_cases(
    cases: list[dict[str, Any]],
    *,
    unresolved_refs: int,
) -> dict[str, Any]:
    count_fields = (
        "gold_refs",
        "baseline_hits",
        "graph_hits",
        "candidate_hits",
        "baseline_any",
        "graph_any",
        "candidate_any",
        "baseline_all",
        "graph_all",
        "candidate_all",
        "gained_refs",
        "lost_refs",
        "gained_any",
        "lost_any",
        "gained_all",
        "lost_all",
        "baseline_rows",
        "graph_rows",
        "unique_graph_rows",
        "candidate_rows",
    )
    summary: dict[str, Any] = {"cases": len(cases), "unresolved_refs": unresolved_refs}
    for field in count_fields:
        summary[field] = sum(int(case[field]) for case in cases)
    summary["gate"] = {
        "requires_gained_refs": 1,
        "requires_lost_refs": 0,
        "passed": summary["gained_refs"] >= 1 and summary["lost_refs"] == 0,
    }
    return summary


def _parse_categories(value: str) -> frozenset[int]:
    try:
        categories = frozenset(int(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("categories must be comma-separated integers") from exc
    if not categories:
        raise argparse.ArgumentTypeError("at least one category is required")
    return categories


def _copy_stores(
    source_root: Path,
    destination_root: Path,
    *,
    run_id: str,
    conversations: int,
) -> None:
    for conversation_idx in range(conversations):
        filename = f"locomo_{conversation_idx}_{run_id}.db"
        source = source_root / filename
        if not source.is_file():
            raise FileNotFoundError(f"missing matched facade store: {source}")
        shutil.copy2(source, destination_root / filename)


def run_preflight(
    *,
    dataset_path: Path,
    db_root: Path,
    run_id: str,
    categories: frozenset[int],
    top_k: int,
    graph_slots: int,
    composition: str = "fill-only",
    limit: int | None = None,
) -> dict[str, Any]:
    if top_k <= 0:
        raise ValueError("top_k must be positive")
    if graph_slots <= 0 or graph_slots > top_k:
        raise ValueError("graph_slots must be in [1, top_k]")
    if composition not in _COMPOSITIONS:
        raise ValueError(f"unknown graph composition: {composition}")
    polluted = [name for name in _BLOCKED_ENV if os.environ.get(name)]
    if polluted:
        raise RuntimeError(
            "graph preflight requires local SQLite retrieval; unset " + ", ".join(polluted)
        )

    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    if not isinstance(dataset, list):
        raise ValueError("LoCoMo dataset root must be a list")
    turn_index = build_turn_index(dataset)
    with tempfile.TemporaryDirectory(prefix="seam-graph-preflight-") as temp:
        temp_root = Path(temp)
        _copy_stores(db_root, temp_root, run_id=run_id, conversations=len(dataset))
        server = SeamMem0Server(
            db_path=str(temp_root),
            search_top_k=top_k,
            context_budget=8000,
        )
        cases: list[dict[str, Any]] = []
        unresolved_refs = 0
        try:
            for conversation_idx, conversation in enumerate(dataset):
                user_id = f"locomo_{conversation_idx}_{run_id}"
                runtime = server._adapter._runtime(user_id)
                runtime._retrieval_flags = replace(
                    runtime._retrieval_flags_cached(),
                    # The frozen gpt-4o facade uses the broad retrieval profile
                    # (300 candidates / 60k context chars) before the harness
                    # truncates the response to top_k=200.  Do not substitute
                    # the compact 8k context here: it changes both row count and
                    # ordering and is not matched-harness evidence.
                    search_top_k=MATCHED_SEARCH_TOP_K,
                    context_budget=MATCHED_CONTEXT_BUDGET,
                    conversation_adapter="conversation/2",
                    inference_policy="inference/high-confidence/1",
                    temporal_policy="temporal/1",
                )
                expected_turns = {
                    turn["envelope"] for turn in turn_index[conversation_idx].values()
                }
                actual_turns = {
                    str(record.attrs.get("content") or "")
                    for record in runtime.store.load_ir(
                        ns=f"locomo:{user_id}", scope="thread"
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
                    graph_rows = server._search_graph_raw(user_id, query, graph_slots)
                    cases.append(
                        measure_case(
                            question_id=f"conv{conversation_idx}_q{question_idx}",
                            category=category,
                            envelopes=envelopes,
                            baseline=baseline,
                            graph_rows=graph_rows,
                            top_k=top_k,
                            graph_slots=graph_slots,
                            composition=composition,
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
            "graph_slots": graph_slots,
            "baseline": "matched-facade-raw",
            "candidate": f"baseline-plus-canonical-graph-{composition}",
            "provider_calls": 0,
        },
        "summary": summarize_cases(cases, unresolved_refs=unresolved_refs),
        "changed_cases": changed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Free canonical-graph evidence/displacement preflight."
    )
    parser.add_argument("db_root", type=Path, help="existing matched facade store root")
    parser.add_argument("--run-id", required=True, help="store suffix after locomo_<index>_")
    parser.add_argument("--dataset", type=Path, default=_DEFAULT_DATASET)
    parser.add_argument("--categories", type=_parse_categories, default=frozenset({1, 3}))
    parser.add_argument("--top-k", type=int, default=200)
    parser.add_argument("--graph-slots", type=int, default=40)
    parser.add_argument(
        "--composition",
        choices=sorted(_COMPOSITIONS),
        default="fill-only",
        help="fill unused top-k rows only, or reserve/displace a graph tail",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="omit changed case ids and emit aggregate numeric results only",
    )
    args = parser.parse_args()
    report = run_preflight(
        dataset_path=args.dataset,
        db_root=args.db_root,
        run_id=args.run_id,
        categories=args.categories,
        top_k=args.top_k,
        graph_slots=args.graph_slots,
        composition=args.composition,
        limit=args.limit,
    )
    if args.summary_only:
        report.pop("changed_cases", None)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
