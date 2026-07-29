"""Provider-free R6/G7 qualification contracts and deterministic scoring.

The native executor in this module performs no network or provider calls. It
coordinates caller-supplied local adapters through a versioned envelope,
validates exact tenant/namespace/scope echoes, and makes retry/concurrency
outcomes reproducible. Competitive Mem0 and Zep lanes remain plan-only here:
they may be ``NOT_RUN`` or ``BLOCKED`` but cannot carry borrowed measurements
or score claims.
"""

from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from statistics import median
from typing import Callable, Iterable, Mapping, Sequence

ADAPTER_ENVELOPE_VERSION = "seam-qualification-adapter/1"
QUALIFICATION_MANIFEST_VERSION = "seam-graph-reasoning-manifest/1"
QUALIFICATION_RESULT_VERSION = "seam-graph-reasoning-result/1"
QUALIFICATION_EXECUTION_VERSION = "seam-qualification-execution/1"
ATTRIBUTION_VERSION = "native-graph-incremental/1"

NATIVE_LANES = frozenset({"native_seam", "event_only"})
EXTERNAL_LANES = frozenset({"matched_mem0", "matched_zep"})
ALL_LANES = NATIVE_LANES | EXTERNAL_LANES
PLAN_ONLY_STATUSES = frozenset({"NOT_RUN", "BLOCKED"})
RESULT_STATUSES = frozenset({"PASS", "FAIL"})
ADAPTER_STATUSES = frozenset({"PASS", "ERROR"})
_OPERATIONS = frozenset(
    {"ingest", "search", "delete", "recover", "health", "context"}
)
_RETRYABLE_OPERATIONS = frozenset({"search", "health", "context"})
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SECRET_OPTION_RE = re.compile(
    r"(?:api[-_]?key|password|secret|token|authorization)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class QualificationBoundary:
    tenant_id: str
    namespace: str
    scope: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "tenant_id", _required(self.tenant_id, "tenant_id"))
        object.__setattr__(
            self, "namespace", _required(self.namespace, "namespace")
        )
        object.__setattr__(self, "scope", _required(self.scope, "scope"))

    def to_dict(self) -> dict[str, str]:
        return {
            "tenant_id": self.tenant_id,
            "namespace": self.namespace,
            "scope": self.scope,
        }


@dataclass(frozen=True, slots=True)
class AdapterEnvelope:
    envelope_id: str
    agent_id: str
    operation: str
    boundary: QualificationBoundary
    manifest_fingerprint: str
    payload_json: str
    version: str = ADAPTER_ENVELOPE_VERSION

    @classmethod
    def build(
        cls,
        *,
        agent_id: str,
        operation: str,
        boundary: QualificationBoundary,
        manifest_fingerprint: str,
        payload: Mapping[str, object],
    ) -> AdapterEnvelope:
        selected_agent = _required(agent_id, "agent_id")
        selected_operation = _required(operation, "operation").lower()
        if selected_operation not in _OPERATIONS:
            raise ValueError(f"unsupported adapter operation {selected_operation!r}")
        fingerprint = _sha256(manifest_fingerprint, "manifest_fingerprint")
        payload_json = _canonical_json(dict(payload))
        material = {
            "agent_id": selected_agent,
            "boundary": boundary.to_dict(),
            "manifest_fingerprint": fingerprint,
            "operation": selected_operation,
            "payload": json.loads(payload_json),
            "version": ADAPTER_ENVELOPE_VERSION,
        }
        envelope_id = f"qenv:{_digest(material)[:24]}"
        return cls(
            envelope_id=envelope_id,
            agent_id=selected_agent,
            operation=selected_operation,
            boundary=boundary,
            manifest_fingerprint=fingerprint,
            payload_json=payload_json,
        )

    @property
    def payload(self) -> dict[str, object]:
        value = json.loads(self.payload_json)
        if not isinstance(value, dict):  # Defensive: build always creates an object.
            raise ValueError("adapter payload must be an object")
        return value

    def to_dict(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "boundary": self.boundary.to_dict(),
            "envelope_id": self.envelope_id,
            "manifest_fingerprint": self.manifest_fingerprint,
            "operation": self.operation,
            "payload": self.payload,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class AdapterResponse:
    envelope_id: str
    agent_id: str
    operation: str
    boundary: QualificationBoundary
    status: str
    record_ids: tuple[str, ...] = ()
    latency_us: int = 0
    attempt: int = 1
    version: str = ADAPTER_ENVELOPE_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "envelope_id", _required(self.envelope_id, "envelope_id")
        )
        object.__setattr__(self, "agent_id", _required(self.agent_id, "agent_id"))
        operation = _required(self.operation, "operation").lower()
        if operation not in _OPERATIONS:
            raise ValueError(f"unsupported adapter operation {operation!r}")
        object.__setattr__(self, "operation", operation)
        status = _required(self.status, "status").upper()
        if status not in ADAPTER_STATUSES:
            raise ValueError(f"unsupported adapter status {status!r}")
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self, "record_ids", _refs(self.record_ids, "record_ids", required=False)
        )
        if (
            not isinstance(self.latency_us, int)
            or isinstance(self.latency_us, bool)
            or self.latency_us < 0
        ):
            raise ValueError("latency_us must be a non-negative integer")
        if (
            not isinstance(self.attempt, int)
            or isinstance(self.attempt, bool)
            or self.attempt < 1
        ):
            raise ValueError("attempt must be a positive integer")
        if self.version != ADAPTER_ENVELOPE_VERSION:
            raise ValueError("adapter response version mismatch")

    def to_dict(self) -> dict[str, object]:
        return {
            "agent_id": self.agent_id,
            "attempt": self.attempt,
            "boundary": self.boundary.to_dict(),
            "envelope_id": self.envelope_id,
            "latency_us": self.latency_us,
            "operation": self.operation,
            "record_ids": self.record_ids,
            "status": self.status,
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class ExecutionReport:
    responses: tuple[AdapterResponse, ...]
    requested: int
    completed: int
    recovered: int
    failed: int
    max_workers: int
    recovery_attempts: int
    fingerprint: str
    version: str = QUALIFICATION_EXECUTION_VERSION

    def to_dict(self) -> dict[str, object]:
        return {
            "completed": self.completed,
            "failed": self.failed,
            "fingerprint": self.fingerprint,
            "max_workers": self.max_workers,
            "recovered": self.recovered,
            "recovery_attempts": self.recovery_attempts,
            "requested": self.requested,
            "responses": [response.to_dict() for response in self.responses],
            "version": self.version,
        }


@dataclass(frozen=True, slots=True)
class QualificationCase:
    case_id: str
    boundary: QualificationBoundary
    expected_record_ids: tuple[str, ...]
    category: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "case_id", _required(self.case_id, "case_id"))
        object.__setattr__(self, "category", _required(self.category, "category"))
        object.__setattr__(
            self,
            "expected_record_ids",
            _refs(self.expected_record_ids, "expected_record_ids", required=True),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "boundary": self.boundary.to_dict(),
            "case_id": self.case_id,
            "category": self.category,
            "expected_record_ids": self.expected_record_ids,
        }


@dataclass(frozen=True, slots=True)
class LanePlan:
    lane: str
    status: str
    provider_calls: int
    paid_required: bool
    command: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        lane = _required(self.lane, "lane")
        if lane not in ALL_LANES:
            raise ValueError(f"unknown qualification lane {lane!r}")
        object.__setattr__(self, "lane", lane)
        status = _required(self.status, "status").upper()
        allowed = {"READY"} if lane in NATIVE_LANES else PLAN_ONLY_STATUSES
        if status not in allowed:
            raise ValueError(f"invalid {lane} plan status {status!r}")
        object.__setattr__(self, "status", status)
        if (
            not isinstance(self.provider_calls, int)
            or isinstance(self.provider_calls, bool)
            or self.provider_calls < 0
        ):
            raise ValueError("provider_calls must be a non-negative integer")
        if lane in NATIVE_LANES and (
            self.provider_calls != 0 or self.paid_required
        ):
            raise ValueError("native qualification lanes must be provider-free")
        if lane in EXTERNAL_LANES:
            if not self.paid_required:
                raise ValueError("matched external lanes must retain the paid gate")
            if self.provider_calls != 0:
                raise ValueError("plan-only external lanes cannot claim provider calls")
            _validate_plan_command(self.command, lane=lane)
            if not self.blockers:
                raise ValueError("external plan-only lane must state its blockers")
        object.__setattr__(
            self, "command", tuple(_required(item, "command item") for item in self.command)
        )
        object.__setattr__(
            self, "blockers", tuple(_required(item, "blocker") for item in self.blockers)
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "blockers": self.blockers,
            "command": self.command,
            "lane": self.lane,
            "paid_required": self.paid_required,
            "provider_calls": self.provider_calls,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class QualificationManifest:
    benchmark: str
    dataset_name: str
    dataset_sha256: str
    native_contract_sha256: str
    matched_contract_sha256: str
    cases: tuple[QualificationCase, ...]
    lanes: tuple[LanePlan, ...]
    fingerprint: str
    version: str = QUALIFICATION_MANIFEST_VERSION

    def to_dict(self, *, include_fingerprint: bool = True) -> dict[str, object]:
        payload: dict[str, object] = {
            "benchmark": self.benchmark,
            "cases": [case.to_dict() for case in self.cases],
            "dataset": {
                "name": self.dataset_name,
                "sha256": self.dataset_sha256,
            },
            "lanes": [lane.to_dict() for lane in self.lanes],
            "matched_contract_sha256": self.matched_contract_sha256,
            "native_contract_sha256": self.native_contract_sha256,
            "version": self.version,
        }
        if include_fingerprint:
            payload["fingerprint"] = self.fingerprint
        return payload


@dataclass(frozen=True, slots=True)
class QualificationResult:
    manifest_fingerprint: str
    lane: str
    case_id: str
    boundary: QualificationBoundary
    status: str
    retrieved_record_ids: tuple[str, ...] = ()
    latency_us: int | None = None
    provider_calls: int = 0
    attempt: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "manifest_fingerprint",
            _sha256(self.manifest_fingerprint, "manifest_fingerprint"),
        )
        lane = _required(self.lane, "lane")
        if lane not in ALL_LANES:
            raise ValueError(f"unknown qualification lane {lane!r}")
        object.__setattr__(self, "lane", lane)
        object.__setattr__(self, "case_id", _required(self.case_id, "case_id"))
        status = _required(self.status, "status").upper()
        allowed = RESULT_STATUSES if lane in NATIVE_LANES else PLAN_ONLY_STATUSES
        if status not in allowed:
            raise ValueError(f"invalid {lane} result status {status!r}")
        object.__setattr__(self, "status", status)
        object.__setattr__(
            self,
            "retrieved_record_ids",
            _refs(
                self.retrieved_record_ids,
                "retrieved_record_ids",
                required=False,
            ),
        )
        if (
            not isinstance(self.provider_calls, int)
            or isinstance(self.provider_calls, bool)
            or self.provider_calls < 0
        ):
            raise ValueError("provider_calls must be a non-negative integer")
        if (
            not isinstance(self.attempt, int)
            or isinstance(self.attempt, bool)
            or self.attempt < 1
        ):
            raise ValueError("attempt must be a positive integer")
        if lane in NATIVE_LANES:
            if self.provider_calls != 0:
                raise ValueError("provider-free native result reported provider calls")
            if (
                not isinstance(self.latency_us, int)
                or isinstance(self.latency_us, bool)
                or self.latency_us < 0
            ):
                raise ValueError("native latency_us must be a non-negative integer")
        elif (
            self.retrieved_record_ids
            or self.latency_us is not None
            or self.provider_calls != 0
        ):
            raise ValueError(
                "plan-only external results cannot carry measurements or claims"
            )


def execute_provider_free(
    adapter: Callable[[AdapterEnvelope], AdapterResponse],
    envelopes: Iterable[AdapterEnvelope],
    *,
    max_workers: int = 4,
    recovery_attempts: int = 1,
) -> ExecutionReport:
    """Execute local adapter requests concurrently with bounded retry.

    Latency is adapter-reported in integer microseconds; the executor never
    substitutes nondeterministic wall-clock timings. Responses are sorted by
    deterministic envelope ID before hashing, independent of completion order.
    """

    requests = tuple(envelopes)
    if not callable(adapter):
        raise TypeError("adapter must be callable")
    if not isinstance(max_workers, int) or isinstance(max_workers, bool) or max_workers < 1:
        raise ValueError("max_workers must be a positive integer")
    if (
        not isinstance(recovery_attempts, int)
        or isinstance(recovery_attempts, bool)
        or recovery_attempts < 0
    ):
        raise ValueError("recovery_attempts must be non-negative")
    ids = [request.envelope_id for request in requests]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate adapter envelope IDs")
    for request in requests:
        if request.version != ADAPTER_ENVELOPE_VERSION:
            raise ValueError("adapter envelope version mismatch")

    def _execute(request: AdapterEnvelope) -> AdapterResponse:
        attempts = (
            recovery_attempts
            if request.operation in _RETRYABLE_OPERATIONS
            else 0
        )
        last_attempt = 1
        for attempt in range(1, attempts + 2):
            last_attempt = attempt
            try:
                response = adapter(request)
                _validate_response(request, response)
                if response.attempt != attempt:
                    response = AdapterResponse(
                        envelope_id=response.envelope_id,
                        agent_id=response.agent_id,
                        operation=response.operation,
                        boundary=response.boundary,
                        status=response.status,
                        record_ids=response.record_ids,
                        latency_us=response.latency_us,
                        attempt=attempt,
                    )
                return response
            except Exception:
                if attempt > attempts:
                    break
        return AdapterResponse(
            envelope_id=request.envelope_id,
            agent_id=request.agent_id,
            operation=request.operation,
            boundary=request.boundary,
            status="ERROR",
            attempt=last_attempt,
        )

    responses: list[AdapterResponse] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_execute, request): request for request in requests}
        for future in as_completed(futures):
            responses.append(future.result())
    ordered = tuple(sorted(responses, key=lambda item: item.envelope_id))
    payload = {
        "max_workers": max_workers,
        "recovery_attempts": recovery_attempts,
        "requested_ids": sorted(ids),
        "responses": [response.to_dict() for response in ordered],
        "version": QUALIFICATION_EXECUTION_VERSION,
    }
    return ExecutionReport(
        responses=ordered,
        requested=len(requests),
        completed=sum(response.status == "PASS" for response in ordered),
        recovered=sum(
            response.status == "PASS" and response.attempt > 1
            for response in ordered
        ),
        failed=sum(response.status == "ERROR" for response in ordered),
        max_workers=max_workers,
        recovery_attempts=recovery_attempts,
        fingerprint=_digest(payload),
    )


def build_frozen_manifest(
    *,
    benchmark: str,
    dataset_name: str,
    dataset_sha256: str,
    native_contract_sha256: str,
    matched_contract_sha256: str,
    cases: Sequence[QualificationCase],
    mem0_command: Sequence[str],
    zep_command: Sequence[str],
) -> QualificationManifest:
    """Freeze native and matched lanes into one immutable input manifest."""

    selected_cases = tuple(sorted(cases, key=lambda case: case.case_id))
    case_ids = [case.case_id for case in selected_cases]
    if not selected_cases:
        raise ValueError("qualification manifest requires at least one case")
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("qualification case IDs must be unique")
    lanes = (
        LanePlan("native_seam", "READY", 0, False),
        LanePlan("event_only", "READY", 0, False),
        LanePlan(
            "matched_mem0",
            "NOT_RUN",
            0,
            True,
            tuple(mem0_command),
            (
                "provider-backed extraction and matched answerer/judge require explicit paid approval",
            ),
        ),
        LanePlan(
            "matched_zep",
            "BLOCKED",
            0,
            True,
            tuple(zep_command),
            (
                "live Zep service plus matched answerer/judge require explicit credentials and paid approval",
            ),
        ),
    )
    placeholder = QualificationManifest(
        benchmark=_required(benchmark, "benchmark"),
        dataset_name=_required(dataset_name, "dataset_name"),
        dataset_sha256=_sha256(dataset_sha256, "dataset_sha256"),
        native_contract_sha256=_sha256(
            native_contract_sha256, "native_contract_sha256"
        ),
        matched_contract_sha256=_sha256(
            matched_contract_sha256, "matched_contract_sha256"
        ),
        cases=selected_cases,
        lanes=lanes,
        fingerprint="0" * 64,
    )
    fingerprint = _digest(placeholder.to_dict(include_fingerprint=False))
    return QualificationManifest(
        benchmark=placeholder.benchmark,
        dataset_name=placeholder.dataset_name,
        dataset_sha256=placeholder.dataset_sha256,
        native_contract_sha256=placeholder.native_contract_sha256,
        matched_contract_sha256=placeholder.matched_contract_sha256,
        cases=placeholder.cases,
        lanes=placeholder.lanes,
        fingerprint=fingerprint,
    )


def verify_frozen_manifest(manifest: QualificationManifest) -> bool:
    expected = _digest(manifest.to_dict(include_fingerprint=False))
    return manifest.fingerprint == expected


def qualify_results(
    manifest: QualificationManifest,
    results: Iterable[QualificationResult],
) -> dict[str, object]:
    """Score provider-free lanes and retain external lanes as plans only."""

    if not verify_frozen_manifest(manifest):
        raise ValueError("qualification manifest fingerprint mismatch")
    cases = {case.case_id: case for case in manifest.cases}
    planned_lanes = {plan.lane for plan in manifest.lanes}
    missing_native_lanes = NATIVE_LANES - planned_lanes
    if missing_native_lanes:
        raise ValueError(
            "manifest missing native lanes: "
            + ", ".join(sorted(missing_native_lanes))
        )
    observed: dict[tuple[str, str], QualificationResult] = {}
    for result in results:
        if result.manifest_fingerprint != manifest.fingerprint:
            raise ValueError("qualification result manifest mismatch")
        if result.lane not in planned_lanes:
            raise ValueError(
                f"result lane {result.lane!r} is not in the manifest"
            )
        case = cases.get(result.case_id)
        if case is None:
            raise ValueError(f"unknown qualification case {result.case_id!r}")
        if result.boundary != case.boundary:
            raise ValueError("qualification result boundary mismatch")
        key = (result.lane, result.case_id)
        if key in observed:
            raise ValueError("duplicate qualification lane/case result")
        observed[key] = result

    lane_reports: dict[str, dict[str, object]] = {}
    for plan in manifest.lanes:
        lane_results = [
            observed[(plan.lane, case.case_id)]
            for case in manifest.cases
            if (plan.lane, case.case_id) in observed
        ]
        if plan.lane in EXTERNAL_LANES:
            if lane_results and any(
                result.status not in PLAN_ONLY_STATUSES for result in lane_results
            ):
                raise ValueError("external lane contains an unverified score claim")
            lane_reports[plan.lane] = {
                "blockers": plan.blockers,
                "case_count": len(lane_results),
                "command": plan.command,
                "paid_required": True,
                "provider_calls": 0,
                "scores": None,
                "status": plan.status,
            }
            continue
        missing = [
            case.case_id
            for case in manifest.cases
            if (plan.lane, case.case_id) not in observed
        ]
        if missing:
            raise ValueError(f"{plan.lane} missing cases: {', '.join(missing)}")
        passed = [result for result in lane_results if result.status == "PASS"]
        case_metrics = [
            _retrieval_metrics(
                result.retrieved_record_ids,
                cases[result.case_id].expected_record_ids,
            )
            for result in passed
        ]
        unexpected_by_case = {
            result.case_id: metrics["unexpected_record_ids"]
            for result, metrics in zip(passed, case_metrics)
            if metrics["unexpected_record_ids"]
        }
        failed_case_ids = {
            result.case_id
            for result in lane_results
            if result.status == "FAIL"
        } | set(unexpected_by_case)
        latencies = [int(result.latency_us or 0) for result in passed]
        lane_reports[plan.lane] = {
            "case_count": len(lane_results),
            "failed_case_ids": tuple(sorted(failed_case_ids)),
            "latency_us": _latency_summary(latencies),
            "precision": round(
                sum(float(metrics["precision"]) for metrics in case_metrics)
                / max(len(lane_results), 1),
                6,
            ),
            "provider_calls": 0,
            "recall": round(
                sum(float(metrics["recall"]) for metrics in case_metrics)
                / max(len(lane_results), 1),
                6,
            ),
            "recovered_case_count": sum(result.attempt > 1 for result in passed),
            "status": (
                "PASS"
                if len(passed) == len(lane_results) and not failed_case_ids
                else "FAIL"
            ),
            "unexpected_record_ids": tuple(
                sorted(
                    {
                        record_id
                        for record_ids in unexpected_by_case.values()
                        for record_id in record_ids
                    }
                )
            ),
            "usefulness": round(
                sum(float(metrics["usefulness"]) for metrics in case_metrics)
                / max(len(lane_results), 1),
                6,
            ),
        }

    attribution_cases: list[dict[str, object]] = []
    for case in manifest.cases:
        native = observed[("native_seam", case.case_id)]
        baseline = observed[("event_only", case.case_id)]
        expected = set(case.expected_record_ids)
        native_hits = set(native.retrieved_record_ids) & expected
        baseline_hits = set(baseline.retrieved_record_ids) & expected
        incremental = tuple(sorted(native_hits - baseline_hits))
        attribution_cases.append(
            {
                "case_id": case.case_id,
                "event_only_hits": tuple(sorted(baseline_hits)),
                "event_only_unexpected_record_ids": tuple(
                    sorted(set(baseline.retrieved_record_ids) - expected)
                ),
                "graph_incremental_record_ids": incremental,
                "native_hits": tuple(sorted(native_hits)),
                "native_unexpected_record_ids": tuple(
                    sorted(set(native.retrieved_record_ids) - expected)
                ),
            }
        )
    native_score = float(lane_reports["native_seam"]["usefulness"])
    baseline_score = float(lane_reports["event_only"]["usefulness"])
    native_p95 = int(lane_reports["native_seam"]["latency_us"]["p95"])
    baseline_p95 = int(lane_reports["event_only"]["latency_us"]["p95"])
    report = {
        "attribution": {
            "cases": attribution_cases,
            "graph_incremental_hit_count": sum(
                len(case["graph_incremental_record_ids"])
                for case in attribution_cases
            ),
            "latency_p95_delta_us": native_p95 - baseline_p95,
            "usefulness_delta": round(native_score - baseline_score, 6),
            "version": ATTRIBUTION_VERSION,
        },
        "lanes": lane_reports,
        "manifest_fingerprint": manifest.fingerprint,
        "paid_provider_calls": 0,
        "publication_claims_allowed": False,
        "version": QUALIFICATION_RESULT_VERSION,
    }
    report["result_fingerprint"] = _digest(report)
    return report


def _validate_response(
    request: AdapterEnvelope, response: AdapterResponse
) -> None:
    if not isinstance(response, AdapterResponse):
        raise TypeError("adapter must return AdapterResponse")
    if (
        response.envelope_id != request.envelope_id
        or response.agent_id != request.agent_id
        or response.operation != request.operation
        or response.boundary != request.boundary
        or response.version != request.version
    ):
        raise ValueError("adapter response does not exactly echo request boundary")


def _validate_plan_command(command: Sequence[str], *, lane: str) -> None:
    if not command:
        raise ValueError(f"{lane} run plan requires an exact command")
    items = tuple(_required(item, "command item") for item in command)
    expected_adapter = "mem0" if lane == "matched_mem0" else "zep"
    if "--adapter" not in items:
        raise ValueError(f"{lane} command must pin --adapter")
    adapter_index = items.index("--adapter") + 1
    if adapter_index >= len(items) or items[adapter_index] != expected_adapter:
        raise ValueError(f"{lane} command must pin adapter {expected_adapter}")
    if "--allow-paid" not in items:
        raise ValueError(f"{lane} command must retain --allow-paid")
    for index, item in enumerate(items):
        if "=" in item and _SECRET_OPTION_RE.search(item.split("=", 1)[0]):
            raise ValueError("run plan must not embed secret values")
        if _SECRET_OPTION_RE.search(item) and index + 1 < len(items):
            next_item = items[index + 1]
            if not next_item.startswith("-"):
                raise ValueError("run plan must not embed secret values")


def _retrieval_metrics(
    retrieved_record_ids: Sequence[str], expected_record_ids: Sequence[str]
) -> dict[str, object]:
    retrieved = set(retrieved_record_ids)
    expected = set(expected_record_ids)
    hits = retrieved & expected
    precision = len(hits) / len(retrieved) if retrieved else 0.0
    recall = len(hits) / len(expected)
    usefulness = (
        (2.0 * precision * recall) / (precision + recall)
        if precision + recall
        else 0.0
    )
    return {
        "precision": precision,
        "recall": recall,
        "unexpected_record_ids": tuple(sorted(retrieved - expected)),
        "usefulness": usefulness,
    }


def _latency_summary(values: Sequence[int]) -> dict[str, int]:
    if not values:
        return {"count": 0, "median": 0, "p95": 0}
    ordered = sorted(values)
    p95_index = max(0, (95 * len(ordered) + 99) // 100 - 1)
    return {
        "count": len(ordered),
        "median": int(median(ordered)),
        "p95": int(ordered[p95_index]),
    }


def _refs(
    values: object, field: str, *, required: bool
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or values is None:
        raise TypeError(f"{field} must be an iterable of strings")
    try:
        refs = tuple(sorted({_required(value, field) for value in values}))
    except TypeError as exc:
        raise TypeError(f"{field} must be an iterable of strings") from exc
    if required and not refs:
        raise ValueError(f"{field} must not be empty")
    return refs


def _required(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} must not be empty")
    return normalized


def _sha256(value: object, field: str) -> str:
    normalized = _required(value, field).lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return normalized


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()
