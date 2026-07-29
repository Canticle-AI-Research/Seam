"""Provider-free native G7/R6 qualification over real SEAM runtime paths.

This micro-suite is structural evidence, not a competitive score. It runs the
native G4/G5 graph-context lane and an event-only retrieval ablation against
the same deterministic fixture, then leaves matched Mem0/Zep execution at an
explicit paid plan boundary.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter_ns

from seam_runtime import SeamSDK
from seam_runtime.mirl import RecordKind
from seam_runtime.qualification import (
    AdapterEnvelope,
    AdapterResponse,
    QualificationBoundary,
    QualificationCase,
    QualificationResult,
    build_frozen_manifest,
    execute_provider_free,
    qualify_results,
)

NATIVE_QUALIFICATION_VERSION = "graph-reasoning-native/1"
MATCHED_CONTEXT_TOKEN_BUDGET = 2_000
MATCHED_RESULT_RECORD_BUDGET = 2
MATCHED_FACT_RESERVE_TOKENS = 0
_FIXTURE = (
    {
        "case_id": "direct",
        "query": "Who owns Orbit?",
        "turns": ("Alice owns Orbit.",),
    },
    {
        "case_id": "multi-hop",
        "query": "How is Alice connected to Quartz?",
        "turns": ("Alice owns Orbit.", "Orbit contains Quartz."),
    },
    {
        "case_id": "recurring",
        "query": "What recurring ownership evidence exists?",
        "turns": ("Alice owns Orbit.", "Alice owns Orbit."),
    },
)


def run_provider_free_native_qualification(
    database_path: str | Path | None = None,
) -> dict[str, object]:
    """Run real native/event-only lanes with zero network or provider calls."""

    temporary: TemporaryDirectory[str] | None = None
    if database_path is None:
        temporary = TemporaryDirectory()
        database_path = Path(temporary.name) / "qualification.db"
    path = Path(database_path)
    try:
        with SeamSDK(path, allow_pgvector_env=False) as sdk:
            fixture_rows: list[dict[str, object]] = []
            cases: list[QualificationCase] = []
            for case in _FIXTURE:
                case_id = str(case["case_id"])
                namespace = f"qualification.{case_id}"
                raw_ids: list[str] = []
                for index, text in enumerate(case["turns"]):
                    report = sdk.ingest(
                        str(text),
                        source_ref=f"local://qualification/{case_id}/{index}",
                        ns=namespace,
                        scope="thread",
                    )
                    raw_ids.extend(
                        record_id
                        for record_id in report.stored_ids
                        if record_id.startswith("raw:")
                    )
                sdk.rebuild_graph_products(
                    namespace=namespace,
                    scope="thread",
                )
                boundary = QualificationBoundary(
                    tenant_id=namespace,
                    namespace=namespace,
                    scope="thread",
                )
                cases.append(
                    QualificationCase(
                        case_id=case_id,
                        boundary=boundary,
                        expected_record_ids=tuple(sorted(raw_ids)),
                        category=case_id,
                    )
                )
                fixture_rows.append(
                    {
                        "case_id": case_id,
                        "query": case["query"],
                        "turns": case["turns"],
                    }
                )

            manifest = build_frozen_manifest(
                benchmark=NATIVE_QUALIFICATION_VERSION,
                dataset_name="seam-provider-free-graph-reasoning/1",
                dataset_sha256=_digest(fixture_rows),
                native_contract_sha256=_digest(
                    {
                        "context": "context-assembly/1",
                        "context_token_budget": MATCHED_CONTEXT_TOKEN_BUDGET,
                        "fact_reserve_tokens": MATCHED_FACT_RESERVE_TOKENS,
                        "graph_products": "graph-products/1",
                        "retrieval": "native",
                        "result_record_budget": MATCHED_RESULT_RECORD_BUDGET,
                    }
                ),
                matched_contract_sha256=_digest(
                    {
                        "answerer": "shared",
                        "dataset": "locomo",
                        "judge": "shared",
                        "memory_adapter": "matched",
                    }
                ),
                cases=cases,
                mem0_command=_matched_command("mem0"),
                zep_command=_matched_command("zep"),
            )

            by_id = {str(row["case_id"]): row for row in fixture_rows}
            results: list[QualificationResult] = []
            for case in manifest.cases:
                query = str(by_id[case.case_id]["query"])
                baseline_started = perf_counter_ns()
                candidates = sdk.runtime.store.context_candidates(
                    namespace=case.boundary.namespace,
                    scope=case.boundary.scope,
                )
                baseline_pack = sdk.context(
                    task=query,
                    namespace=case.boundary.namespace,
                    scope=case.boundary.scope,
                    as_of="9999-12-31T23:59:59Z",
                    token_budget=MATCHED_CONTEXT_TOKEN_BUDGET,
                    fact_reserve_tokens=MATCHED_FACT_RESERVE_TOKENS,
                    candidates=[
                        candidate
                        for candidate in candidates
                        if candidate.kind == "episode"
                    ],
                )
                baseline_ids = _bounded_raw_closure(
                    sdk,
                    [
                        record_id
                        for item in baseline_pack.items
                        for record_id in item.record_ids
                    ],
                )
                baseline_latency = max(
                    1, (perf_counter_ns() - baseline_started) // 1_000
                )
                results.append(
                    QualificationResult(
                        manifest.fingerprint,
                        "event_only",
                        case.case_id,
                        case.boundary,
                        "PASS",
                        baseline_ids,
                        baseline_latency,
                    )
                )

                native_started = perf_counter_ns()
                pack = sdk.context(
                    task=query,
                    namespace=case.boundary.namespace,
                    scope=case.boundary.scope,
                    as_of="9999-12-31T23:59:59Z",
                    token_budget=MATCHED_CONTEXT_TOKEN_BUDGET,
                    fact_reserve_tokens=MATCHED_FACT_RESERVE_TOKENS,
                    candidates=candidates,
                )
                native_ids = _bounded_raw_closure(
                    sdk,
                    [
                        record_id
                        for item in pack.items
                        for record_id in item.record_ids
                    ],
                )
                native_latency = max(
                    1, (perf_counter_ns() - native_started) // 1_000
                )
                results.append(
                    QualificationResult(
                        manifest.fingerprint,
                        "native_seam",
                        case.case_id,
                        case.boundary,
                        "PASS",
                        native_ids,
                        native_latency,
                    )
                )

            report = qualify_results(manifest, results)
            concurrent = _concurrency_recovery_probe(sdk, manifest, by_id)
            return {
                "comparison_budget": {
                    "context_token_budget": MATCHED_CONTEXT_TOKEN_BUDGET,
                    "event_only_kinds": ("episode",),
                    "fact_reserve_tokens": MATCHED_FACT_RESERVE_TOKENS,
                    "matched": True,
                    "result_record_budget": MATCHED_RESULT_RECORD_BUDGET,
                },
                "concurrency_recovery": concurrent.to_dict(),
                "manifest": manifest.to_dict(),
                "provider_calls": 0,
                "qualification": report,
                "version": NATIVE_QUALIFICATION_VERSION,
            }
    finally:
        if temporary is not None:
            temporary.cleanup()


def _concurrency_recovery_probe(
    sdk: SeamSDK,
    manifest,
    fixture_by_id: dict[str, dict[str, object]],
):
    envelopes = tuple(
        AdapterEnvelope.build(
            agent_id=f"agent-{index}",
            operation="context",
            boundary=case.boundary,
            manifest_fingerprint=manifest.fingerprint,
            payload={
                "case_id": case.case_id,
                "query": fixture_by_id[case.case_id]["query"],
            },
        )
        for index, case in enumerate(manifest.cases)
    )
    attempts: dict[str, int] = {}
    lock = threading.Lock()
    recovery_id = envelopes[0].envelope_id

    def adapter(request: AdapterEnvelope) -> AdapterResponse:
        with lock:
            attempt = attempts.get(request.envelope_id, 0) + 1
            attempts[request.envelope_id] = attempt
        if request.envelope_id == recovery_id and attempt == 1:
            raise RuntimeError("synthetic interrupted read")
        started = perf_counter_ns()
        pack = sdk.context(
            task=str(request.payload["query"]),
            namespace=request.boundary.namespace,
            scope=request.boundary.scope,
            as_of="9999-12-31T23:59:59Z",
            token_budget=MATCHED_CONTEXT_TOKEN_BUDGET,
            fact_reserve_tokens=MATCHED_FACT_RESERVE_TOKENS,
        )
        return AdapterResponse(
            envelope_id=request.envelope_id,
            agent_id=request.agent_id,
            operation=request.operation,
            boundary=request.boundary,
            status="PASS",
            record_ids=_raw_closure(sdk, pack.refs),
            latency_us=max(1, (perf_counter_ns() - started) // 1_000),
        )

    return execute_provider_free(
        adapter,
        envelopes,
        max_workers=min(4, len(envelopes)),
        recovery_attempts=1,
    )


def _raw_closure(sdk: SeamSDK, record_ids) -> tuple[str, ...]:
    pending = list(dict.fromkeys(str(item) for item in record_ids))
    seen: set[str] = set()
    raws: list[str] = []
    while pending:
        current = pending
        pending = []
        by_id = sdk.runtime.store.load_ir(ids=current).by_id()
        for record_id in current:
            record = by_id.get(record_id)
            if record is None:
                continue
            if record.id in seen:
                continue
            seen.add(record.id)
            if record.kind == RecordKind.RAW:
                raws.append(record.id)
            if record.kind == RecordKind.SPAN:
                raw_id = record.attrs.get("raw_id")
                if raw_id:
                    pending.append(str(raw_id))
            pending.extend(
                ref
                for ref in (*record.prov, *record.evidence)
                if ref not in seen
            )
    return tuple(raws)


def _bounded_raw_closure(sdk: SeamSDK, record_ids) -> tuple[str, ...]:
    return _raw_closure(sdk, record_ids)[:MATCHED_RESULT_RECORD_BUDGET]


def _matched_command(adapter: str) -> tuple[str, ...]:
    return (
        ".venv/bin/python",
        "-m",
        "benchmarks.external.locomo.run",
        "--dataset-path",
        "<locomo-dataset-path>",
        "--adapter",
        adapter,
        "--answerer",
        "openai",
        "--judge",
        "openai",
        "--allow-paid",
    )


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> None:
    print(
        json.dumps(
            run_provider_free_native_qualification(),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
