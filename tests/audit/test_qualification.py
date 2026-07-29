from __future__ import annotations

import threading
from collections import Counter

import pytest

from seam_runtime.qualification import (
    ADAPTER_ENVELOPE_VERSION,
    AdapterEnvelope,
    AdapterResponse,
    QualificationBoundary,
    QualificationCase,
    QualificationResult,
    build_frozen_manifest,
    execute_provider_free,
    qualify_results,
    verify_frozen_manifest,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64


def _boundary(scope: str = "thread-1") -> QualificationBoundary:
    return QualificationBoundary("tenant-a", "work", scope)


def _command(adapter: str) -> tuple[str, ...]:
    return (
        "python",
        "-m",
        "benchmarks.external.locomo.run",
        "--adapter",
        adapter,
        "--answerer",
        "openai",
        "--judge",
        "openai",
        "--allow-paid",
    )


def _manifest():
    return build_frozen_manifest(
        benchmark="graph-reasoning-g7",
        dataset_name="provider-free-fixture/1",
        dataset_sha256=HASH_A,
        native_contract_sha256=HASH_B,
        matched_contract_sha256=HASH_C,
        cases=(
            QualificationCase(
                "case-2",
                _boundary("thread-2"),
                ("clm:event", "clm:graph"),
                "multi-hop",
            ),
            QualificationCase(
                "case-1",
                _boundary(),
                ("clm:direct",),
                "direct",
            ),
        ),
        mem0_command=_command("mem0"),
        zep_command=_command("zep"),
    )


def test_envelope_is_stable_versioned_and_boundary_explicit() -> None:
    first = AdapterEnvelope.build(
        agent_id="agent-a",
        operation="search",
        boundary=_boundary(),
        manifest_fingerprint=HASH_A,
        payload={"query": "compiler rollback", "limit": 8},
    )
    second = AdapterEnvelope.build(
        agent_id="agent-a",
        operation="search",
        boundary=_boundary(),
        manifest_fingerprint=HASH_A,
        payload={"limit": 8, "query": "compiler rollback"},
    )

    assert first == second
    assert first.version == ADAPTER_ENVELOPE_VERSION
    assert first.envelope_id.startswith("qenv:")
    assert first.to_dict()["boundary"] == {
        "tenant_id": "tenant-a",
        "namespace": "work",
        "scope": "thread-1",
    }


def test_executor_is_deterministic_under_concurrency_and_bounded_recovery() -> None:
    requests = tuple(
        AdapterEnvelope.build(
            agent_id=f"agent-{index}",
            operation="search",
            boundary=_boundary(f"thread-{index}"),
            manifest_fingerprint=HASH_A,
            payload={"query": f"q-{index}"},
        )
        for index in range(8)
    )
    calls: Counter[str] = Counter()
    lock = threading.Lock()

    def adapter(request: AdapterEnvelope) -> AdapterResponse:
        with lock:
            calls[request.envelope_id] += 1
            attempt = calls[request.envelope_id]
        if request.agent_id in {"agent-1", "agent-5"} and attempt == 1:
            raise RuntimeError("synthetic crash")
        return AdapterResponse(
            envelope_id=request.envelope_id,
            agent_id=request.agent_id,
            operation=request.operation,
            boundary=request.boundary,
            status="PASS",
            record_ids=(f"clm:{request.agent_id}",),
            latency_us=int(request.agent_id.split("-")[1]) + 10,
        )

    first = execute_provider_free(
        adapter, reversed(requests), max_workers=4, recovery_attempts=1
    )
    calls.clear()
    second = execute_provider_free(
        adapter, requests, max_workers=4, recovery_attempts=1
    )

    assert first.requested == first.completed == 8
    assert first.recovered == 2
    assert first.failed == 0
    assert first.fingerprint == second.fingerprint
    assert [item.envelope_id for item in first.responses] == sorted(
        item.envelope_id for item in first.responses
    )


@pytest.mark.parametrize("operation", ["ingest", "delete", "recover"])
def test_executor_never_retries_mutating_operations(operation: str) -> None:
    request = AdapterEnvelope.build(
        agent_id="agent-a",
        operation=operation,
        boundary=_boundary(),
        manifest_fingerprint=HASH_A,
        payload={},
    )
    calls = 0

    def failing_adapter(_request: AdapterEnvelope) -> AdapterResponse:
        nonlocal calls
        calls += 1
        raise RuntimeError("synthetic mutation failure")

    report = execute_provider_free(
        failing_adapter, [request], recovery_attempts=3
    )

    assert calls == 1
    assert report.failed == 1
    assert report.responses[0].attempt == 1


def test_executor_fails_closed_on_cross_tenant_response() -> None:
    request = AdapterEnvelope.build(
        agent_id="agent-a",
        operation="search",
        boundary=_boundary(),
        manifest_fingerprint=HASH_A,
        payload={},
    )

    def leaking_adapter(request: AdapterEnvelope) -> AdapterResponse:
        return AdapterResponse(
            request.envelope_id,
            request.agent_id,
            request.operation,
            QualificationBoundary("tenant-b", "work", "thread-1"),
            "PASS",
        )

    report = execute_provider_free(
        leaking_adapter, [request], recovery_attempts=0
    )

    assert report.completed == 0
    assert report.failed == 1
    assert report.responses[0].status == "ERROR"


def test_manifest_freezes_separate_native_and_matched_lanes() -> None:
    manifest = _manifest()

    assert verify_frozen_manifest(manifest)
    assert [case.case_id for case in manifest.cases] == ["case-1", "case-2"]
    plans = {plan.lane: plan for plan in manifest.lanes}
    assert plans["native_seam"].status == "READY"
    assert plans["event_only"].provider_calls == 0
    assert plans["matched_mem0"].status == "NOT_RUN"
    assert plans["matched_mem0"].paid_required is True
    assert plans["matched_zep"].status == "BLOCKED"
    assert "--allow-paid" in plans["matched_zep"].command

    same = _manifest()
    assert same.fingerprint == manifest.fingerprint


def test_external_plan_validation_forbids_implicit_or_secret_execution() -> None:
    with pytest.raises(ValueError, match="allow-paid"):
        build_frozen_manifest(
            benchmark="g7",
            dataset_name="fixture",
            dataset_sha256=HASH_A,
            native_contract_sha256=HASH_B,
            matched_contract_sha256=HASH_C,
            cases=(
                QualificationCase("case", _boundary(), ("clm:1",), "direct"),
            ),
            mem0_command=(
                "python",
                "--adapter",
                "mem0",
            ),
            zep_command=_command("zep"),
        )
    with pytest.raises(ValueError, match="secret"):
        build_frozen_manifest(
            benchmark="g7",
            dataset_name="fixture",
            dataset_sha256=HASH_A,
            native_contract_sha256=HASH_B,
            matched_contract_sha256=HASH_C,
            cases=(
                QualificationCase("case", _boundary(), ("clm:1",), "direct"),
            ),
            mem0_command=(
                "python",
                "--adapter",
                "mem0",
                "--api-key=do-not-embed",
                "--allow-paid",
            ),
            zep_command=_command("zep"),
        )


def _results(manifest):
    by_case = {case.case_id: case for case in manifest.cases}
    return [
        QualificationResult(
            manifest.fingerprint,
            "event_only",
            "case-1",
            by_case["case-1"].boundary,
            "PASS",
            ("clm:direct",),
            100,
        ),
        QualificationResult(
            manifest.fingerprint,
            "native_seam",
            "case-1",
            by_case["case-1"].boundary,
            "PASS",
            ("clm:direct",),
            120,
        ),
        QualificationResult(
            manifest.fingerprint,
            "event_only",
            "case-2",
            by_case["case-2"].boundary,
            "PASS",
            ("clm:event",),
            110,
        ),
        QualificationResult(
            manifest.fingerprint,
            "native_seam",
            "case-2",
            by_case["case-2"].boundary,
            "PASS",
            ("clm:event", "clm:graph"),
            150,
            attempt=2,
        ),
        QualificationResult(
            manifest.fingerprint,
            "matched_mem0",
            "case-1",
            by_case["case-1"].boundary,
            "NOT_RUN",
        ),
        QualificationResult(
            manifest.fingerprint,
            "matched_zep",
            "case-1",
            by_case["case-1"].boundary,
            "BLOCKED",
        ),
    ]


def test_native_usefulness_latency_recovery_and_graph_attribution() -> None:
    manifest = _manifest()
    report = qualify_results(manifest, _results(manifest))

    assert report["paid_provider_calls"] == 0
    assert report["publication_claims_allowed"] is False
    assert report["lanes"]["event_only"]["precision"] == 1.0
    assert report["lanes"]["event_only"]["recall"] == 0.75
    assert report["lanes"]["event_only"]["usefulness"] == 0.833333
    assert report["lanes"]["native_seam"]["usefulness"] == 1.0
    assert report["lanes"]["native_seam"]["recovered_case_count"] == 1
    assert report["attribution"]["usefulness_delta"] == 0.166667
    assert report["attribution"]["latency_p95_delta_us"] == 40
    assert report["attribution"]["graph_incremental_hit_count"] == 1
    case_2 = next(
        item
        for item in report["attribution"]["cases"]
        if item["case_id"] == "case-2"
    )
    assert case_2["graph_incremental_record_ids"] == ("clm:graph",)
    assert report["lanes"]["matched_mem0"]["scores"] is None
    assert report["lanes"]["matched_zep"]["scores"] is None


def test_unexpected_ids_penalize_usefulness_and_fail_the_lane() -> None:
    manifest = _manifest()
    results = _results(manifest)
    results[1] = QualificationResult(
        manifest.fingerprint,
        "native_seam",
        "case-1",
        results[1].boundary,
        "PASS",
        ("clm:direct", "clm:foreign"),
        120,
    )

    report = qualify_results(manifest, results)
    native = report["lanes"]["native_seam"]

    assert native["status"] == "FAIL"
    assert native["failed_case_ids"] == ("case-1",)
    assert native["unexpected_record_ids"] == ("clm:foreign",)
    assert native["precision"] == 0.75
    assert native["recall"] == 1.0
    assert native["usefulness"] == 0.833333
    case_1 = next(
        item
        for item in report["attribution"]["cases"]
        if item["case_id"] == "case-1"
    )
    assert case_1["native_unexpected_record_ids"] == ("clm:foreign",)


def test_result_boundary_manifest_and_completeness_fail_closed() -> None:
    manifest = _manifest()
    results = _results(manifest)
    results[0] = QualificationResult(
        manifest.fingerprint,
        "event_only",
        "case-1",
        QualificationBoundary("tenant-b", "work", "thread-1"),
        "PASS",
        ("clm:direct",),
        100,
    )
    with pytest.raises(ValueError, match="boundary"):
        qualify_results(manifest, results)

    incomplete = [
        result
        for result in _results(manifest)
        if not (result.lane == "native_seam" and result.case_id == "case-2")
    ]
    with pytest.raises(ValueError, match="missing cases"):
        qualify_results(manifest, incomplete)


def test_external_lanes_cannot_carry_measurements_or_score_claims() -> None:
    manifest = _manifest()
    case = manifest.cases[0]
    with pytest.raises(ValueError, match="invalid matched_mem0 result status"):
        QualificationResult(
            manifest.fingerprint,
            "matched_mem0",
            case.case_id,
            case.boundary,
            "PASS",
        )
    with pytest.raises(ValueError, match="cannot carry measurements"):
        QualificationResult(
            manifest.fingerprint,
            "matched_zep",
            case.case_id,
            case.boundary,
            "BLOCKED",
            latency_us=10,
        )


def test_manifest_tamper_is_detected() -> None:
    manifest = _manifest()
    object.__setattr__(manifest, "dataset_name", "changed")
    assert verify_frozen_manifest(manifest) is False
    with pytest.raises(ValueError, match="fingerprint"):
        qualify_results(manifest, [])
