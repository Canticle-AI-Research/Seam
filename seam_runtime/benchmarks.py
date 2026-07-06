from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from importlib.util import find_spec
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from .context_views import build_context_payload, render_context_pretty
from .dsl import compile_dsl
from .evals import default_retrieval_fixtures, run_retrieval_benchmark
from .holographic import (
    decode_surface,
    encode_surface,
    query_surface,
    verify_surface,
)
from .lossless import (
    _structural_quote_spans,
    benchmark_text_lossless,
    compress_text_readable,
    count_prompt_tokens,
    decompress_text_readable,
    parse_readable_machine_text,
    query_readable_compressed,
)
from .models import HashEmbeddingModel, cosine
from .storage import SQLiteStore
from .surface_adapters import SurfaceFileAdapter
from .vector import INDEXABLE_KINDS, SQLiteVectorIndex

if TYPE_CHECKING:
    from .runtime import SeamRuntime


BENCHMARK_VERSION = "SEAM-BENCH/1"
BENCHMARK_SUITES = ("lossless", "readable", "surface", "retrieval", "embedding", "long_context", "persistence", "agent_tasks")
BENCHMARK_GATE_VERSION = "SEAM-BENCH-GATE/1"

BENCHMARK_ROOT = Path(__file__).resolve().parent.parent / "benchmarks"
FIXTURE_ROOT = BENCHMARK_ROOT / "fixtures"
HOLDOUT_FIXTURE_ROOT = FIXTURE_ROOT / "holdout"
HOLDOUT_RUN_ROOT = BENCHMARK_ROOT / "runs" / "holdout"
LOSSLESS_FIXTURE_PATH = FIXTURE_ROOT / "lossless_cases.json"
READABLE_FIXTURE_PATH = FIXTURE_ROOT / "readable_cases.json"
SURFACE_FIXTURE_PATH = FIXTURE_ROOT / "surface_cases.json"
LONG_CONTEXT_FIXTURE_PATH = FIXTURE_ROOT / "long_context_cases.json"
AGENT_TASK_FIXTURE_PATH = FIXTURE_ROOT / "agent_tasks.json"
RETRIEVAL_FIXTURE_PATH = Path(__file__).resolve().parent.parent / "docs" / "retrieval_gold_fixtures.json"
LOSSLESS_DEMO_PATH = Path(__file__).resolve().parent.parent / "tools" / "lossless_demo_input.txt"
HOLDOUT_BENCHMARK_SUITES = ("lossless", "readable", "surface", "retrieval", "embedding", "long_context", "agent_tasks")
DEFAULT_BENCHMARK_GATE_POLICY: dict[str, Any] = {
    "version": BENCHMARK_GATE_VERSION,
    "required_families": list(BENCHMARK_SUITES),
    "summary": {
        "status": {"equals": "PASS"},
        "family_count": {"minimum": len(BENCHMARK_SUITES)},
        "case_count": {"minimum": 19},
        "exactness_rate": {"minimum": 1.0},
    },
    "families": {
        "lossless": {
            "pass_rate": {"minimum": 1.0},
            "exactness_rate": {"minimum": 1.0},
            "worst_case_savings": {"minimum": 0.30},
        },
        "readable": {
            "pass_rate": {"minimum": 1.0},
            "exactness_rate": {"minimum": 1.0},
            "direct_text_exact_rate": {"minimum": 1.0},
            "direct_read_equivalence_rate": {"minimum": 1.0},
            "direct_query_exactness_rate": {"minimum": 1.0},
        },
        "surface": {
            "pass_rate": {"minimum": 1.0},
            "surface_exact_rate": {"minimum": 1.0},
            "payload_hash_match_rate": {"minimum": 1.0},
            "direct_query_exactness_rate": {"minimum": 1.0},
            "stored_lookup_rate": {"minimum": 1.0},
            "stored_query_exactness_rate": {"minimum": 1.0},
            "repair_success_rate": {"minimum": 1.0},
            "repair_query_exactness_rate": {"minimum": 1.0},
        },
        "retrieval": {
            "pass_rate": {"minimum": 1.0},
            "hybrid_recall_at_k": {"minimum": 1.0},
            "machine_hybrid_recall_at_k": {"minimum": 1.0},
            "exact_pack_reversible_rate": {"minimum": 1.0},
        },
        "embedding": {
            "pass_rate": {"minimum": 1.0},
            "top1_rate": {"minimum": 1.0},
            "min_margin": {"minimum": 0.05},
        },
        "long_context": {
            "pass_rate": {"minimum": 1.0},
            "hit_rate": {"minimum": 1.0},
            "prompt_contains_rate": {"minimum": 1.0},
            "avg_prompt_token_savings_vs_records": {"minimum": 0.10},
        },
        "persistence": {
            "pass_rate": {"minimum": 1.0},
            "durability_rate": {"minimum": 1.0},
        },
        "agent_tasks": {
            "pass_rate": {"minimum": 1.0},
            "task_success_rate": {"minimum": 1.0},
            "avg_prompt_token_savings_vs_records": {"minimum": 0.10},
        },
    },
    "baseline": {
        "status_regressions": {"maximum": 0},
        "metric_regressions": {"maximum": 0},
        "removed_cases": {"maximum": 0},
    },
}


def run_benchmark_suite(
    runtime: "SeamRuntime",
    suite: str = "all",
    tokenizer: str = "auto",
    min_token_savings: float = 0.30,
    persist: bool = False,
    include_machine_text: bool = False,
    bundle_path: str | Path | None = None,
    holdout: bool = False,
) -> dict[str, Any]:
    selected_suites = _selected_suites(suite, holdout=holdout)
    run_id = f"{'bench-holdout' if holdout else 'bench'}:{uuid4().hex[:12]}"
    family_reports: dict[str, dict[str, Any]] = {}

    for family in selected_suites:
        if family == "lossless":
            family_reports[family] = _run_lossless_family(
                runtime,
                tokenizer=tokenizer,
                min_token_savings=min_token_savings,
                persist=persist,
                include_machine_text=include_machine_text,
                fixture_path=_holdout_fixture_path(LOSSLESS_FIXTURE_PATH) if holdout else LOSSLESS_FIXTURE_PATH,
                require_fixture=holdout,
            )
            continue
        if family == "readable":
            family_reports[family] = _run_readable_family(
                runtime,
                tokenizer=tokenizer,
                persist=persist,
                include_machine_text=include_machine_text,
                fixture_path=_holdout_fixture_path(READABLE_FIXTURE_PATH) if holdout else READABLE_FIXTURE_PATH,
                require_fixture=holdout,
            )
            continue
        if family == "surface":
            family_reports[family] = _run_surface_family(
                runtime,
                persist=persist,
                include_payload=include_machine_text,
                fixture_path=_holdout_fixture_path(SURFACE_FIXTURE_PATH) if holdout else SURFACE_FIXTURE_PATH,
                require_fixture=holdout,
            )
            continue
        if family == "retrieval":
            family_reports[family] = _run_retrieval_family(
                runtime,
                fixture_path=_holdout_fixture_path(RETRIEVAL_FIXTURE_PATH) if holdout else RETRIEVAL_FIXTURE_PATH,
            )
            continue
        if family == "embedding":
            family_reports[family] = _run_embedding_family(
                runtime,
                fixture_path=_holdout_fixture_path(RETRIEVAL_FIXTURE_PATH) if holdout else RETRIEVAL_FIXTURE_PATH,
            )
            continue
        if family == "long_context":
            family_reports[family] = _run_long_context_family(
                runtime,
                tokenizer=tokenizer,
                persist=persist,
                fixture_path=_holdout_fixture_path(LONG_CONTEXT_FIXTURE_PATH) if holdout else LONG_CONTEXT_FIXTURE_PATH,
                require_fixture=holdout,
            )
            continue
        if family == "persistence":
            family_reports[family] = _run_persistence_family(runtime, tokenizer=tokenizer)
            continue
        if family == "agent_tasks":
            family_reports[family] = _run_agent_task_family(
                runtime,
                tokenizer=tokenizer,
                persist=persist,
                fixture_path=_holdout_fixture_path(AGENT_TASK_FIXTURE_PATH) if holdout else AGENT_TASK_FIXTURE_PATH,
                require_fixture=holdout,
            )
            continue

    manifest = {
        "version": BENCHMARK_VERSION,
        "run_id": run_id,
        "requested_suite": suite,
        "executed_suites": selected_suites,
        "fixture_scope": "holdout" if holdout else "public",
        "publish_only": holdout,
        "created_at": _utc_now(),
        "git_sha": _git_sha(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "db_path": runtime.store.path,
        "tokenizer": tokenizer,
        "min_token_savings": round(min_token_savings, 6),
        "dependencies": {
            "rich": find_spec("rich") is not None,
            "chromadb": find_spec("chromadb") is not None,
            "tiktoken": find_spec("tiktoken") is not None,
        },
        "dataset_hashes": _dataset_manifest(holdout=holdout),
    }
    summary = _build_suite_summary(family_reports)
    report = {
        "manifest": manifest,
        "summary": summary,
        "families": family_reports,
        "improvement_loop": _aggregate_family_actions(family_reports),
    }
    report["bundle_hash"] = _hash_payload(report, "bundle_hash")

    if bundle_path is not None:
        Path(bundle_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    if persist:
        runtime.store.write_benchmark_run(report)
    return report


def verify_benchmark_bundle(bundle: str | Path | dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(Path(bundle).read_text(encoding="utf-8")) if isinstance(bundle, (str, Path)) else dict(bundle)
    expected_bundle_hash = payload.get("bundle_hash")
    actual_bundle_hash = _hash_payload(payload, "bundle_hash")
    bundle_hash_ok = expected_bundle_hash == actual_bundle_hash
    case_results: list[dict[str, Any]] = []

    for family_name, family in payload.get("families", {}).items():
        for case in family.get("cases", []):
            expected_case_hash = case.get("case_hash")
            actual_case_hash = _hash_payload(case, "case_hash")
            case_results.append(
                {
                    "family": family_name,
                    "case_id": case.get("case_id"),
                    "expected_case_hash": expected_case_hash,
                    "actual_case_hash": actual_case_hash,
                    "ok": expected_case_hash == actual_case_hash,
                }
            )

    return {
        "status": "PASS" if bundle_hash_ok and all(item["ok"] for item in case_results) else "FAIL",
        "bundle_hash_ok": bundle_hash_ok,
        "expected_bundle_hash": expected_bundle_hash,
        "actual_bundle_hash": actual_bundle_hash,
        "case_checks": case_results,
    }


def evaluate_benchmark_gate(
    bundle: str | Path | dict[str, Any],
    baseline: str | Path | dict[str, Any] | None = None,
    policy: str | Path | dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = _load_benchmark_payload(bundle)
    gate_policy = _load_gate_policy(policy)
    verification = verify_benchmark_bundle(payload)
    checks: list[dict[str, Any]] = [
        _gate_check(
            scope="bundle",
            metric="integrity",
            actual=verification["status"],
            rule={"equals": "PASS"},
            message="bundle hash and case hashes must verify",
        )
    ]

    summary = payload.get("summary", {})
    for metric, rule in gate_policy.get("summary", {}).items():
        checks.append(_gate_check("summary", metric, summary.get(metric), rule))

    families = payload.get("families", {})
    for family_name in gate_policy.get("required_families", []):
        checks.append(
            _gate_check(
                scope=f"family.{family_name}",
                metric="present",
                actual=family_name in families,
                rule={"equals": True},
                message=f"required benchmark family is missing: {family_name}",
            )
        )

    for family_name, family_rules in gate_policy.get("families", {}).items():
        family = families.get(family_name)
        if not family:
            continue
        family_summary = family.get("summary", {})
        for metric, rule in family_rules.items():
            checks.append(_gate_check(f"family.{family_name}", metric, family_summary.get(metric), rule))

    diff_payload = None
    if baseline is not None:
        diff_payload = diff_benchmark_runs(baseline, payload)
        diff_summary = diff_payload.get("summary", {})
        checks.append(
            _gate_check(
                scope="baseline",
                metric="integrity",
                actual=diff_summary.get("bundle_hash_ok_a") and diff_summary.get("bundle_hash_ok_b"),
                rule={"equals": True},
                message="baseline and candidate bundles must verify before comparing regressions",
            )
        )
        for metric, rule in gate_policy.get("baseline", {}).items():
            checks.append(_gate_check("baseline", metric, diff_summary.get(metric), rule))

    failed = [check for check in checks if check["status"] != "PASS"]
    return {
        "version": BENCHMARK_GATE_VERSION,
        "status": "PASS" if not failed else "FAIL",
        "run": _run_ref(payload),
        "policy": gate_policy,
        "verification": verification,
        "baseline_diff": diff_payload,
        "summary": {
            "checks": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
        },
        "checks": checks,
    }


def render_benchmark_gate_pretty(payload: dict[str, Any]) -> str:
    summary = payload.get("summary", {})
    run = payload.get("run", {})
    lines = [
        f"SEAM benchmark gate: {payload.get('status')}",
        f"Run: {run.get('run_id')} ({run.get('bundle_hash')})",
        f"Checks: {summary.get('passed')}/{summary.get('checks')} passed",
        "",
        "Failed checks:",
    ]
    failed = [check for check in payload.get("checks", []) if check.get("status") != "PASS"]
    if not failed:
        lines.append("- none")
    for check in failed[:20]:
        lines.append(
            f"- {check.get('scope')}::{check.get('metric')} actual={check.get('actual')} "
            f"rule={check.get('rule')} message={check.get('message')}"
        )
    if payload.get("baseline_diff"):
        diff_summary = payload["baseline_diff"].get("summary", {})
        lines.extend(
            [
                "",
                "Baseline diff:",
                f"- status={diff_summary.get('status')}",
                f"- status_regressions={diff_summary.get('status_regressions')}",
                f"- metric_regressions={diff_summary.get('metric_regressions')}",
                f"- removed_cases={diff_summary.get('removed_cases')}",
            ]
        )
    return "\n".join(lines)


def diff_benchmark_runs(run_a: str | Path | dict[str, Any], run_b: str | Path | dict[str, Any]) -> dict[str, Any]:
    payload_a = _load_benchmark_payload(run_a)
    payload_b = _load_benchmark_payload(run_b)
    verification_a = verify_benchmark_bundle(payload_a)
    verification_b = verify_benchmark_bundle(payload_b)
    cases_a = _flatten_benchmark_cases(payload_a)
    cases_b = _flatten_benchmark_cases(payload_b)

    by_hash_a = {case["case_hash"]: case for case in cases_a if case.get("case_hash")}
    by_hash_b = {case["case_hash"]: case for case in cases_b if case.get("case_hash")}
    matched_hashes = sorted(set(by_hash_a) & set(by_hash_b))
    compared: list[dict[str, Any]] = []
    used_a: set[str] = set()
    used_b: set[str] = set()

    for case_hash in matched_hashes:
        left = by_hash_a[case_hash]
        right = by_hash_b[case_hash]
        compared.append(_diff_case(left, right, join_key=case_hash, join_type="case_hash"))
        used_a.add(left["identity"])
        used_b.add(right["identity"])

    identity_a = {case["identity"]: case for case in cases_a if case["identity"] not in used_a}
    identity_b = {case["identity"]: case for case in cases_b if case["identity"] not in used_b}
    for identity in sorted(set(identity_a) & set(identity_b)):
        compared.append(_diff_case(identity_a[identity], identity_b[identity], join_key=identity, join_type="case_id"))
        used_a.add(identity)
        used_b.add(identity)

    added = [case for case in cases_b if case["identity"] not in used_b]
    removed = [case for case in cases_a if case["identity"] not in used_a]
    metric_deltas = [delta for case in compared for delta in case["metric_deltas"]]
    status_improvements = sum(1 for case in compared if case["status_delta"] == "improved")
    status_regressions = sum(1 for case in compared if case["status_delta"] == "regressed")
    metric_improvements = sum(1 for delta in metric_deltas if delta["indicator"] == "green")
    metric_regressions = sum(1 for delta in metric_deltas if delta["indicator"] == "red")
    summary = {
        "status": "REGRESSED" if status_regressions or metric_regressions else "IMPROVED" if status_improvements or metric_improvements else "UNCHANGED",
        "cases_a": len(cases_a),
        "cases_b": len(cases_b),
        "cases_compared": len(compared),
        "exact_case_hash_matches": sum(1 for case in compared if case["join_type"] == "case_hash"),
        "changed_case_matches": sum(1 for case in compared if case["join_type"] == "case_id"),
        "added_cases": len(added),
        "removed_cases": len(removed),
        "status_improvements": status_improvements,
        "status_regressions": status_regressions,
        "metric_improvements": metric_improvements,
        "metric_regressions": metric_regressions,
        "bundle_hash_ok_a": verification_a["status"] == "PASS",
        "bundle_hash_ok_b": verification_b["status"] == "PASS",
    }
    return {
        "version": "SEAM-BENCH-DIFF/1",
        "run_a": _run_ref(payload_a),
        "run_b": _run_ref(payload_b),
        "summary": summary,
        "cases": compared,
        "added_cases": [_case_ref(case) for case in added],
        "removed_cases": [_case_ref(case) for case in removed],
        "verification": {"run_a": verification_a, "run_b": verification_b},
    }


def render_benchmark_diff_pretty(payload: dict[str, Any]) -> str:
    summary = payload.get("summary", {})
    run_a = payload.get("run_a", {})
    run_b = payload.get("run_b", {})
    lines = [
        f"SEAM benchmark diff: {summary.get('status')}",
        f"Run A: {run_a.get('run_id')} ({run_a.get('bundle_hash')})",
        f"Run B: {run_b.get('run_id')} ({run_b.get('bundle_hash')})",
        f"Compared: {summary.get('cases_compared')} cases "
        f"({summary.get('exact_case_hash_matches')} hash matches, {summary.get('changed_case_matches')} changed matches)",
        f"Added/removed: {summary.get('added_cases')}/{summary.get('removed_cases')}",
        f"Status: {summary.get('status_improvements')} improved, {summary.get('status_regressions')} regressed",
        f"Metrics: {summary.get('metric_improvements')} green, {summary.get('metric_regressions')} red",
        "",
        "Case deltas:",
    ]
    for case in payload.get("cases", [])[:20]:
        marker = _status_marker(case.get("status_delta"))
        lines.append(
            f"- {marker} {case.get('family')}::{case.get('case_id')} "
            f"status={case.get('status_a')}->{case.get('status_b')} join={case.get('join_type')}"
        )
        for delta in case.get("metric_deltas", [])[:6]:
            lines.append(
                f"  [{delta['indicator']}] {delta['metric']}: {delta['a']} -> {delta['b']} "
                f"({delta['delta']:+.6g})"
            )
    for case in payload.get("added_cases", [])[:10]:
        lines.append(f"- [green] ADDED {case.get('family')}::{case.get('case_id')}")
    for case in payload.get("removed_cases", [])[:10]:
        lines.append(f"- [red] REMOVED {case.get('family')}::{case.get('case_id')}")
    if len(lines) == 9:
        lines.append("- no per-case deltas")
    return "\n".join(lines)


def write_holdout_benchmark_bundle(payload: dict[str, Any], output_dir: str | Path | None = None) -> Path:
    manifest = payload.get("manifest", {})
    if manifest.get("fixture_scope") != "holdout":
        raise ValueError("write_holdout_benchmark_bundle only accepts holdout benchmark payloads")
    run_id = str(manifest.get("run_id", f"bench-holdout:{uuid4().hex[:12]}")).replace(":", "_")
    created = str(manifest.get("created_at", _utc_now())).replace(":", "").replace("-", "").replace("Z", "Z")
    directory = Path(output_dir) if output_dir is not None else HOLDOUT_RUN_ROOT
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{created}_{run_id}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def render_benchmark_pretty(payload: dict[str, Any]) -> str:
    manifest = payload.get("manifest", {})
    summary = payload.get("summary", {})
    family_lines = []
    for family_name, family in payload.get("families", {}).items():
        family_summary = family.get("summary", {})
        family_lines.append(
            "- "
            f"{family_name}: pass_rate={float(family_summary.get('pass_rate', 0.0)):.1%} "
            f"cases={family_summary.get('case_count', 0)} "
            f"signals={_render_key_metrics(family_name, family_summary)}"
        )
    action_lines = [f"- {action}" for action in payload.get("improvement_loop", [])[:8]]
    if not action_lines:
        action_lines = ["- no immediate regressions detected"]
    return "\n".join(
        [
            f"SEAM benchmark suite: {summary.get('status')}",
            f"Run id: {manifest.get('run_id')}",
            f"Suits: {', '.join(manifest.get('executed_suites', []))}",
            f"Cases: {summary.get('case_count')} ({summary.get('passed_cases')} passed)",
            f"Exactness rate: {float(summary.get('exactness_rate', 0.0)):.1%}",
            f"Token savings p50: {float(summary.get('token_savings_p50', 0.0)):.1%}",
            f"Git SHA: {manifest.get('git_sha') or '(unavailable)'}",
            f"Bundle hash: {payload.get('bundle_hash')}",
            "",
            "Families:",
            *family_lines,
            "",
            "Improvement loop:",
            *action_lines,
        ]
    )


def render_benchmark_verification_pretty(payload: dict[str, Any]) -> str:
    lines = [
        f"Benchmark bundle verification: {payload.get('status')}",
        f"Bundle hash OK: {'yes' if payload.get('bundle_hash_ok') else 'no'}",
    ]
    for item in payload.get("case_checks", [])[:10]:
        lines.append(f"- {item['family']}::{item['case_id']} => {'OK' if item['ok'] else 'MISMATCH'}")
    return "\n".join(lines)


def _run_lossless_family(
    runtime: "SeamRuntime",
    tokenizer: str,
    min_token_savings: float,
    persist: bool,
    include_machine_text: bool,
    fixture_path: Path = LOSSLESS_FIXTURE_PATH,
    require_fixture: bool = False,
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for config in _load_json_fixture(fixture_path, _default_lossless_cases(), require_exists=require_fixture):
        text = _resolve_lossless_text(config)
        result = benchmark_text_lossless(
            text,
            tokenizer=tokenizer,
            min_token_savings=float(config.get("min_token_savings", min_token_savings)),
        )
        artifact_id = None
        if persist:
            artifact_id = runtime.store.write_machine_artifact(
                source_type="benchmark.lossless",
                source_id=config["name"],
                artifact=result.artifact.to_dict(include_machine_text=True),
                roundtrip_ok=result.roundtrip_match,
                metadata={"family": "lossless", "case": config["name"]},
            )
        case = {
            "case_id": config["name"],
            "status": "PASS" if result.passed else "FAIL",
            "metrics": {
                "roundtrip_match": result.roundtrip_match,
                "meets_target": result.meets_target,
                "token_savings_ratio": round(result.artifact.token_savings_ratio, 6),
                "byte_savings_ratio": round(result.artifact.byte_savings_ratio, 6),
                "intelligence_per_token_gain": round(result.artifact.intelligence_per_token_gain, 6),
                "machine_tokens": result.artifact.machine_tokens,
                "original_tokens": result.artifact.original_tokens,
            },
            "trace": result.to_dict(include_machine_text=include_machine_text),
            "debug_flags": list(result.flags),
            "improvement_loop": _lossless_actions(result, config["name"]),
        }
        if artifact_id is not None:
            case["artifact_id"] = artifact_id
        cases.append(_stamp_case_hash(case))

    summary = {
        "case_count": len(cases),
        "pass_rate": _ratio(sum(1 for case in cases if case["status"] == "PASS"), len(cases)),
        "exactness_rate": _ratio(sum(1 for case in cases if case["metrics"]["roundtrip_match"]), len(cases)),
        "avg_token_savings": _average(case["metrics"]["token_savings_ratio"] for case in cases),
        "avg_gain": _average(case["metrics"]["intelligence_per_token_gain"] for case in cases),
        "worst_case_savings": min((case["metrics"]["token_savings_ratio"] for case in cases), default=0.0),
    }
    return {
        "family": "lossless",
        "summary": summary,
        "cases": cases,
        "improvement_loop": _unique_actions(case["improvement_loop"] for case in cases),
    }


def _run_readable_family(
    runtime: "SeamRuntime",
    tokenizer: str,
    persist: bool,
    include_machine_text: bool,
    fixture_path: Path = READABLE_FIXTURE_PATH,
    require_fixture: bool = False,
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for config in _load_json_fixture(fixture_path, _default_readable_cases(), require_exists=require_fixture):
        text = _resolve_lossless_text(config)
        artifact = compress_text_readable(
            text,
            source_ref=str(config.get("source_ref", f"benchmark://readable/{config['name']}")),
            granularity=str(config.get("granularity", "auto")),
            tokenizer=tokenizer,
        )
        parsed = parse_readable_machine_text(artifact.machine_text)
        direct_text = _read_rc1_text_direct(parsed)
        rebuilt = decompress_text_readable(artifact.machine_text)
        direct_sha256 = hashlib.sha256(direct_text.encode("utf-8")).hexdigest()
        rebuilt_sha256 = hashlib.sha256(rebuilt.encode("utf-8")).hexdigest()
        source_quotes = _quote_span_records(text)
        compressed_quotes = _compressed_quote_records(parsed)
        source_terms = sorted(set(_benchmark_terms(text)))
        compressed_terms = sorted(set(parsed.get("index", {}).get("terms", {}).keys()))
        query_checks = _readable_query_checks(artifact.machine_text, config, source_quotes)
        direct_quote_match = source_quotes == compressed_quotes
        term_coverage = set(source_terms).issubset(set(compressed_terms))
        direct_text_match = direct_text == text and direct_sha256 == artifact.sha256
        rebuild_match = rebuilt == text and rebuilt_sha256 == artifact.sha256
        direct_query_exactness = all(item["ok"] for item in query_checks)
        info_equivalent = direct_text_match and rebuild_match and direct_quote_match and term_coverage and direct_query_exactness
        artifact_id = None
        if persist:
            artifact_id = runtime.store.write_machine_artifact(
                source_type="benchmark.readable",
                source_id=config["name"],
                artifact=artifact.to_dict(include_machine_text=True),
                roundtrip_ok=rebuild_match,
                metadata={"family": "readable", "case": config["name"], "format": "SEAM-RC/1"},
            )
        trace = {
            "source_sha256": artifact.sha256,
            "direct_read_sha256": direct_sha256,
            "rebuilt_sha256": rebuilt_sha256,
            "direct_read_text": direct_text if bool(config.get("include_direct_text_trace", False)) else None,
            "source_quotes": source_quotes,
            "compressed_quotes": compressed_quotes,
            "source_terms": source_terms,
            "compressed_terms": compressed_terms,
            "query_checks": query_checks,
            "artifact": artifact.to_dict(include_machine_text=include_machine_text),
        }
        case = {
            "case_id": config["name"],
            "status": "PASS" if info_equivalent else "FAIL",
            "metrics": {
                "roundtrip_match": rebuild_match,
                "direct_text_match": direct_text_match,
                "direct_quote_match": direct_quote_match,
                "direct_query_exactness": direct_query_exactness,
                "term_coverage": term_coverage,
                "info_equivalent": info_equivalent,
                "quote_count": len(source_quotes),
                "query_check_count": len(query_checks),
                "token_savings_ratio": round(artifact.token_savings_ratio, 6),
                "intelligence_per_token_gain": round(artifact.intelligence_per_token_gain, 6),
                "machine_tokens": artifact.machine_tokens,
                "original_tokens": artifact.original_tokens,
            },
            "trace": trace,
            "debug_flags": _readable_flags(direct_text_match, rebuild_match, direct_quote_match, direct_query_exactness, term_coverage),
            "improvement_loop": _readable_actions(config["name"], direct_text_match, rebuild_match, direct_quote_match, direct_query_exactness, term_coverage),
        }
        if artifact_id is not None:
            case["artifact_id"] = artifact_id
        cases.append(_stamp_case_hash(case))

    summary = {
        "case_count": len(cases),
        "pass_rate": _ratio(sum(1 for case in cases if case["status"] == "PASS"), len(cases)),
        "exactness_rate": _ratio(sum(1 for case in cases if case["metrics"]["roundtrip_match"]), len(cases)),
        "direct_text_exact_rate": _ratio(sum(1 for case in cases if case["metrics"]["direct_text_match"]), len(cases)),
        "direct_read_equivalence_rate": _ratio(sum(1 for case in cases if case["metrics"]["info_equivalent"]), len(cases)),
        "direct_query_exactness_rate": _ratio(sum(1 for case in cases if case["metrics"]["direct_query_exactness"]), len(cases)),
        "quote_match_rate": _ratio(sum(1 for case in cases if case["metrics"]["direct_quote_match"]), len(cases)),
        "avg_token_savings": _average(case["metrics"]["token_savings_ratio"] for case in cases),
        "avg_gain": _average(case["metrics"]["intelligence_per_token_gain"] for case in cases),
    }
    return {
        "family": "readable",
        "summary": summary,
        "cases": cases,
        "improvement_loop": _unique_actions(case["improvement_loop"] for case in cases),
    }


def _run_surface_family(
    runtime: "SeamRuntime",
    persist: bool,
    include_payload: bool,
    fixture_path: Path = SURFACE_FIXTURE_PATH,
    require_fixture: bool = False,
) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="seam-bench-surface-") as temp_dir:
        temp_root = Path(temp_dir)
        surface_store = SQLiteStore(temp_root / "surface-library.db")
        for config in _load_json_fixture(fixture_path, _default_surface_cases(), require_exists=require_fixture):
            payload_bytes, payload_format = _surface_case_payload(config)
            surface_path = temp_root / f"{config['name']}.seam.png"
            artifact = encode_surface(
                payload_bytes,
                output_path=surface_path,
                mode=str(config.get("mode", "rgb24")),
                payload_format=payload_format,
                source_ref=str(config.get("source_ref", f"benchmark://surface/{config['name']}")),
            )
            decoded = decode_surface(surface_path)
            verification = verify_surface(surface_path)
            surface_exact = decoded.payload == payload_bytes
            payload_hash_match = decoded.payload_sha256 == hashlib.sha256(payload_bytes).hexdigest()
            source_quotes = (
                _quote_span_records(_resolve_lossless_text(config))
                if str(config.get("payload_kind", "readable")) == "readable"
                else []
            )
            query_checks = _surface_query_checks(surface_path, config, source_quotes)
            direct_query_exactness = all(item["ok"] for item in query_checks)
            stored_trace = _surface_stored_query_and_repair_checks(
                surface_store,
                artifact.to_dict(),
                surface_path,
                source_sha256=hashlib.sha256(payload_bytes).hexdigest(),
                config=config,
                artifact_dir=temp_root / "stored-surfaces" / str(config["name"]),
            )
            stored_lookup = bool(stored_trace["stored_lookup"])
            stored_query_exactness = bool(stored_trace["stored_query_exactness"])
            repair_ok = bool(stored_trace["repair_ok"])
            repair_query_exactness = bool(stored_trace["repair_query_exactness"])
            artifact_id = None
            if persist:
                artifact_id = runtime.store.write_machine_artifact(
                    source_type="benchmark.surface",
                    source_id=config["name"],
                    artifact={
                        "surface": artifact.to_dict(),
                        "payload": decoded.to_dict(include_payload=include_payload),
                    },
                    roundtrip_ok=surface_exact,
                    metadata={"family": "surface", "case": config["name"], "format": "SEAM-HS/1"},
                )
            case = {
                "case_id": config["name"],
                "status": (
                    "PASS"
                    if (
                        surface_exact
                        and payload_hash_match
                        and verification.ok
                        and direct_query_exactness
                        and stored_lookup
                        and stored_query_exactness
                        and repair_ok
                        and repair_query_exactness
                    )
                    else "FAIL"
                ),
                "metrics": {
                    "roundtrip_match": surface_exact,
                    "surface_exact": surface_exact,
                    "payload_hash_match": payload_hash_match,
                    "direct_query_exactness": direct_query_exactness,
                    "stored_lookup": stored_lookup,
                    "stored_query_exactness": stored_query_exactness,
                    "repair_ok": repair_ok,
                    "repair_query_exactness": repair_query_exactness,
                    "payload_bytes": artifact.payload_bytes,
                    "surface_bytes": artifact.surface_bytes,
                    "capacity_bytes": artifact.capacity_bytes,
                    "capacity_used_ratio": round(artifact.capacity_used_ratio, 6),
                },
                "trace": {
                    "artifact": artifact.to_dict(),
                    "verification": verification.to_dict(),
                    "query_checks": query_checks,
                    "stored_surface": stored_trace,
                    "payload": decoded.to_dict(include_payload=include_payload),
                },
                "debug_flags": _surface_flags(
                    surface_exact,
                    payload_hash_match,
                    verification.ok,
                    direct_query_exactness,
                    stored_lookup,
                    stored_query_exactness,
                    repair_ok,
                    repair_query_exactness,
                ),
                "improvement_loop": _surface_actions(
                    config["name"],
                    surface_exact,
                    payload_hash_match,
                    verification.ok,
                    direct_query_exactness,
                    stored_lookup,
                    stored_query_exactness,
                    repair_ok,
                    repair_query_exactness,
                ),
            }
            if artifact_id is not None:
                case["artifact_id"] = artifact_id
            cases.append(_stamp_case_hash(case))
        # Close the store before the TemporaryDirectory is cleaned up; on Windows
        # an open SQLite handle locks surface-library.db and cleanup raises WinError 32.
        surface_store.close()

    summary = {
        "case_count": len(cases),
        "pass_rate": _ratio(sum(1 for case in cases if case["status"] == "PASS"), len(cases)),
        "surface_exact_rate": _ratio(sum(1 for case in cases if case["metrics"]["surface_exact"]), len(cases)),
        "payload_hash_match_rate": _ratio(sum(1 for case in cases if case["metrics"]["payload_hash_match"]), len(cases)),
        "direct_query_exactness_rate": _ratio(sum(1 for case in cases if case["metrics"]["direct_query_exactness"]), len(cases)),
        "stored_lookup_rate": _ratio(sum(1 for case in cases if case["metrics"]["stored_lookup"]), len(cases)),
        "stored_query_exactness_rate": _ratio(sum(1 for case in cases if case["metrics"]["stored_query_exactness"]), len(cases)),
        "repair_success_rate": _ratio(sum(1 for case in cases if case["metrics"]["repair_ok"]), len(cases)),
        "repair_query_exactness_rate": _ratio(sum(1 for case in cases if case["metrics"]["repair_query_exactness"]), len(cases)),
        "avg_capacity_used_ratio": _average(case["metrics"]["capacity_used_ratio"] for case in cases),
    }
    return {
        "family": "surface",
        "summary": summary,
        "cases": cases,
        "improvement_loop": _unique_actions(case["improvement_loop"] for case in cases),
    }


def _run_retrieval_family(runtime: "SeamRuntime", fixture_path: Path = RETRIEVAL_FIXTURE_PATH) -> dict[str, Any]:
    benchmark = run_retrieval_benchmark(
        fixtures=default_retrieval_fixtures(fixture_path),
        embedding_model=runtime.embedding_model,
    )
    cases: list[dict[str, Any]] = []
    ndcg_scores: list[float] = []
    for fixture in benchmark["fixtures"]:
        hybrid = fixture["tracks"]["hybrid"]
        raw = fixture["tracks"]["raw"]
        mac_nat_q = fixture["tracks"]["machine_nat_query"]
        mac_vec = fixture["tracks"]["machine_vector"]
        mac_hyb = fixture["tracks"]["machine_hybrid"]
        ndcg = _ndcg_at_k(hybrid["ranked_ids"], fixture["expected_ids"])
        ndcg_scores.append(ndcg)
        case = {
            "case_id": fixture["name"],
            "status": "PASS"
            if hybrid["hit"] and fixture["packs"]["exact"]["reversibility"] == 1.0 and fixture["packs"]["context"]["traceability"] >= 0.66
            else "FAIL",
            "metrics": {
                "hybrid_hit": hybrid["hit"],
                "hybrid_recall_at_k": hybrid["recall_at_k"],
                "hybrid_mrr": hybrid["reciprocal_rank"],
                "hybrid_ndcg_at_k": round(ndcg, 6),
                "raw_recall_at_k": raw["recall_at_k"],
                "hybrid_vs_raw_recall_delta": round(hybrid["recall_at_k"] - raw["recall_at_k"], 6),
                "machine_nat_query_recall": mac_nat_q["recall_at_k"],
                "machine_vector_recall": mac_vec["recall_at_k"],
                "machine_hybrid_recall": mac_hyb["recall_at_k"],
                "machine_hybrid_vs_nat_hybrid_delta": round(mac_hyb["recall_at_k"] - hybrid["recall_at_k"], 6),
                "exact_pack_reversible": fixture["packs"]["exact"]["reversibility"] == 1.0,
                "context_traceability": fixture["packs"]["context"]["traceability"],
            },
            "trace": fixture,
            "debug_flags": _retrieval_flags(fixture),
            "improvement_loop": _retrieval_actions(fixture),
        }
        cases.append(_stamp_case_hash(case))

    summary = {
        "case_count": len(cases),
        "pass_rate": _ratio(sum(1 for case in cases if case["status"] == "PASS"), len(cases)),
        "hybrid_hit_rate": benchmark["summary"]["tracks"]["hybrid"]["hit_rate"],
        "hybrid_mrr": benchmark["summary"]["tracks"]["hybrid"]["mrr"],
        "hybrid_recall_at_k": benchmark["summary"]["tracks"]["hybrid"]["recall_at_k"],
        "hybrid_ndcg_at_k": _average(ndcg_scores),
        "machine_hybrid_hit_rate": benchmark["summary"]["tracks"]["machine_hybrid"]["hit_rate"],
        "machine_hybrid_mrr": benchmark["summary"]["tracks"]["machine_hybrid"]["mrr"],
        "machine_hybrid_recall_at_k": benchmark["summary"]["tracks"]["machine_hybrid"]["recall_at_k"],
        "exact_pack_reversible_rate": _ratio(
            sum(1 for case in cases if case["metrics"]["exact_pack_reversible"]),
            len(cases),
        ),
    }
    return {
        "family": "retrieval",
        "summary": summary,
        "cases": cases,
        "improvement_loop": _unique_actions(case["improvement_loop"] for case in cases),
    }


def _run_embedding_family(runtime: "SeamRuntime", fixture_path: Path = RETRIEVAL_FIXTURE_PATH) -> dict[str, Any]:
    model = runtime.embedding_model or HashEmbeddingModel()
    cases: list[dict[str, Any]] = []
    margins: list[float] = []

    for fixture in default_retrieval_fixtures(fixture_path):
        batch = compile_dsl(fixture.source, scope="project")
        query_vector = model.embed(fixture.query)
        scores: dict[str, float] = {}
        for record in batch.records:
            if record.kind not in INDEXABLE_KINDS:
                continue
            scores[record.id] = cosine(query_vector, model.embed(SQLiteVectorIndex.render_record_text(record)))
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        expected_scores = [score for record_id, score in ranked if record_id in fixture.expected_ids]
        distractor_scores = [score for record_id, score in ranked if record_id not in fixture.expected_ids]
        top_record_id = ranked[0][0] if ranked else None
        expected_best = max(expected_scores, default=0.0)
        distractor_best = max(distractor_scores, default=0.0)
        margin = expected_best - distractor_best
        margins.append(margin)
        case = {
            "case_id": fixture.name,
            "status": "PASS" if top_record_id in fixture.expected_ids and margin >= 0.0 else "FAIL",
            "metrics": {
                "top1_correct": top_record_id in fixture.expected_ids,
                "expected_best_score": round(expected_best, 6),
                "distractor_best_score": round(distractor_best, 6),
                "separation_margin": round(margin, 6),
            },
            "trace": {
                "query": fixture.query,
                "expected_ids": fixture.expected_ids,
                "top_ranked": [{"record_id": record_id, "score": round(score, 6)} for record_id, score in ranked[:5]],
                "embedding_model": model.name,
            },
            "debug_flags": ["weak_margin"] if margin < 0.05 else [],
            "improvement_loop": _embedding_actions(top_record_id, fixture.expected_ids, margin),
        }
        cases.append(_stamp_case_hash(case))

    summary = {
        "case_count": len(cases),
        "pass_rate": _ratio(sum(1 for case in cases if case["status"] == "PASS"), len(cases)),
        "top1_rate": _ratio(sum(1 for case in cases if case["metrics"]["top1_correct"]), len(cases)),
        "avg_margin": _average(margins),
        "min_margin": min(margins, default=0.0),
        "embedding_model": model.name,
    }
    return {
        "family": "embedding",
        "summary": summary,
        "cases": cases,
        "improvement_loop": _unique_actions(case["improvement_loop"] for case in cases),
    }

def _run_long_context_family(
    runtime: "SeamRuntime",
    tokenizer: str,
    persist: bool,
    fixture_path: Path = LONG_CONTEXT_FIXTURE_PATH,
    require_fixture: bool = False,
) -> dict[str, Any]:
    from seam_runtime.retrieval_orchestrator import RetrievalOrchestrator

    cases: list[dict[str, Any]] = []
    for config in _load_json_fixture(fixture_path, _default_long_context_cases(), require_exists=require_fixture):
        temp_db = Path(tempfile.gettempdir()) / f"seam-bench-long-{uuid4().hex}.db"
        temp_runtime = runtime.__class__(temp_db)
        try:
            batch = compile_dsl(_build_long_context_dsl(config), scope="project")
            temp_runtime.persist_ir(batch)
            rag = RetrievalOrchestrator(temp_runtime).rag(
                config["query"],
                budget=int(config.get("budget", 5)),
                pack_budget=int(config.get("pack_budget", 128)),
            )
            prompt_payload = build_context_payload(rag.to_dict(), view="prompt")
            summary_payload = build_context_payload(rag.to_dict(), view="summary")
            records_payload = build_context_payload(rag.to_dict(), view="records")
            prompt_text = render_context_pretty(prompt_payload)
            summary_text = render_context_pretty(summary_payload)
            records_text = json.dumps(records_payload["output"], indent=2, sort_keys=True)
            prompt_tokens, estimator = count_prompt_tokens(prompt_text, tokenizer=tokenizer)
            records_tokens, _ = count_prompt_tokens(records_text, tokenizer=tokenizer)
            expected_hit = any(record_id in config["expected_ids"] for record_id in rag.candidate_ids)
            prompt_contains = all(snippet in prompt_text for snippet in config.get("required_prompt_snippets", []))
            summary_contains = all(snippet in summary_text for snippet in config.get("required_summary_snippets", []))
            projection_id = None
            if persist:
                temp_runtime.store.write_projection(
                    record_id=f"benchmark:{config['name']}",
                    projection_kind="prompt",
                    projection_text=prompt_text,
                    tokenizer=estimator,
                    metadata={"family": "long_context", "case": config["name"]},
                )
                projection_id = temp_runtime.store.write_projection(
                    record_id=f"benchmark:{config['name']}",
                    projection_kind="records",
                    projection_text=records_text,
                    tokenizer=estimator,
                    metadata={"family": "long_context", "case": config["name"]},
                )
            case = {
                "case_id": config["name"],
                "status": "PASS" if expected_hit and prompt_contains and summary_contains else "FAIL",
                "metrics": {
                    "expected_hit": expected_hit,
                    "prompt_contains": prompt_contains,
                    "summary_contains": summary_contains,
                    "prompt_tokens": prompt_tokens,
                    "records_tokens": records_tokens,
                    "prompt_token_savings_vs_records": round(_savings_ratio(records_tokens, prompt_tokens), 6),
                    "token_estimator": estimator,
                },
                "trace": {
                    "query": config["query"],
                    "candidate_ids": rag.candidate_ids,
                    "prompt": prompt_text,
                    "summary": summary_text,
                },
                "debug_flags": _long_context_flags(expected_hit, prompt_contains, summary_contains, prompt_tokens, records_tokens),
                "improvement_loop": _long_context_actions(expected_hit, prompt_contains, summary_contains, prompt_tokens, records_tokens),
            }
            if projection_id is not None:
                case["projection_id"] = projection_id
            cases.append(_stamp_case_hash(case))
        finally:
            # Close the runtime before deleting temp_db; an open SQLite handle
            # blocks deletion on Windows (WinError 32) and leaks the temp file.
            temp_runtime.close()
            _cleanup_temp_db(temp_db)

    summary = {
        "case_count": len(cases),
        "pass_rate": _ratio(sum(1 for case in cases if case["status"] == "PASS"), len(cases)),
        "hit_rate": _ratio(sum(1 for case in cases if case["metrics"]["expected_hit"]), len(cases)),
        "prompt_contains_rate": _ratio(sum(1 for case in cases if case["metrics"]["prompt_contains"]), len(cases)),
        "avg_prompt_token_savings_vs_records": _average(case["metrics"]["prompt_token_savings_vs_records"] for case in cases),
    }
    return {
        "family": "long_context",
        "summary": summary,
        "cases": cases,
        "improvement_loop": _unique_actions(case["improvement_loop"] for case in cases),
    }
def _run_persistence_family(runtime: "SeamRuntime", tokenizer: str) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="seam-bench-persist-") as temp_dir:
        temp_db = Path(temp_dir) / "persistence.db"
        temp_runtime = runtime.__class__(temp_db)
        batch = compile_dsl(
            """
entity project "SEAM" as p1
claim c1:
  subject p1
  predicate translator_for
  object natural_language
claim c2:
  subject p1
  predicate projection_index
  object tokenizer_projection
"""
        )
        temp_runtime.persist_ir(batch)
        reopened_runtime = runtime.__class__(temp_db)
        search = reopened_runtime.search_ir("translator natural language", budget=3)
        case = {
            "case_id": "persist_reload_search",
            "status": "PASS" if any(candidate.record.id == "c1" for candidate in search.candidates) else "FAIL",
            "metrics": {
                "candidate_count": len(search.candidates),
                "expected_hit": any(candidate.record.id == "c1" for candidate in search.candidates),
            },
            "trace": search.to_dict(),
            "debug_flags": [],
            "improvement_loop": ["inspect persistence/load path if expected records do not survive reopen"]
            if not any(candidate.record.id == "c1" for candidate in search.candidates)
            else [],
        }
        cases.append(_stamp_case_hash(case))

        lossless = benchmark_text_lossless("SEAM preserves exact context while compressing token usage for lossless recovery.\n" * 12, tokenizer=tokenizer)
        artifact_id = reopened_runtime.store.write_machine_artifact(
            source_type="benchmark.persistence",
            source_id="machine_artifact_roundtrip",
            artifact=lossless.artifact.to_dict(include_machine_text=True),
            roundtrip_ok=lossless.roundtrip_match,
            metadata={"family": "persistence"},
        )
        artifact = reopened_runtime.store.read_machine_artifact(artifact_id)
        case = {
            "case_id": "machine_artifact_roundtrip",
            "status": "PASS" if artifact.get("roundtrip_ok") and artifact.get("sha256_raw") == lossless.artifact.sha256 else "FAIL",
            "metrics": {
                "roundtrip_ok": artifact.get("roundtrip_ok"),
                "token_savings_ratio": artifact.get("token_savings_ratio"),
            },
            "trace": artifact,
            "debug_flags": [],
            "improvement_loop": ["inspect machine_artifacts schema and serialization if roundtrip metadata does not reload"]
            if not artifact.get("roundtrip_ok")
            else [],
        }
        cases.append(_stamp_case_hash(case))

        projection_id = reopened_runtime.store.write_projection(
            record_id="benchmark:persistence",
            projection_kind="prompt",
            projection_text="SEAM retrieved context\n[1] c1 [CLM] p1 translator_for natural_language",
            tokenizer="char4_approx",
            metadata={"family": "persistence"},
        )
        projections = reopened_runtime.store.read_projections("benchmark:persistence")
        case = {
            "case_id": "projection_index_roundtrip",
            "status": "PASS" if any(item["projection_kind"] == "prompt" for item in projections) else "FAIL",
            "metrics": {
                "projection_count": len(projections),
                "projection_id": projection_id,
            },
            "trace": projections,
            "debug_flags": [],
            "improvement_loop": ["inspect projection index writes if benchmark projections are missing after reload"]
            if not any(item["projection_kind"] == "prompt" for item in projections)
            else [],
        }
        cases.append(_stamp_case_hash(case))

        sample_run = {
            "manifest": {"run_id": "bench:persistence-sample", "version": BENCHMARK_VERSION},
            "summary": {"status": "PASS"},
            "families": {},
            "improvement_loop": [],
            "bundle_hash": "sample",
        }
        reopened_runtime.store.write_benchmark_run(sample_run)
        loaded_run = reopened_runtime.store.read_benchmark_run("bench:persistence-sample")
        case = {
            "case_id": "benchmark_run_roundtrip",
            "status": "PASS" if loaded_run.get("summary", {}).get("status") == "PASS" else "FAIL",
            "metrics": {
                "loaded": bool(loaded_run),
                "status": loaded_run.get("summary", {}).get("status"),
            },
            "trace": loaded_run,
            "debug_flags": [],
            "improvement_loop": ["inspect benchmark_runs schema if stored benchmark reports do not reload"]
            if loaded_run.get("summary", {}).get("status") != "PASS"
            else [],
        }
        cases.append(_stamp_case_hash(case))
        # Close both transient runtimes before the TemporaryDirectory is cleaned
        # up; otherwise Windows keeps persistence.db locked and cleanup fails.
        reopened_runtime.close()
        temp_runtime.close()

    summary = {
        "case_count": len(cases),
        "pass_rate": _ratio(sum(1 for case in cases if case["status"] == "PASS"), len(cases)),
        "durability_rate": _ratio(sum(1 for case in cases if case["status"] == "PASS"), len(cases)),
    }
    return {
        "family": "persistence",
        "summary": summary,
        "cases": cases,
        "improvement_loop": _unique_actions(case["improvement_loop"] for case in cases),
    }


def _run_agent_task_family(
    runtime: "SeamRuntime",
    tokenizer: str,
    persist: bool,
    fixture_path: Path = AGENT_TASK_FIXTURE_PATH,
    require_fixture: bool = False,
) -> dict[str, Any]:
    from seam_runtime.retrieval_orchestrator import RetrievalOrchestrator

    cases: list[dict[str, Any]] = []
    for config in _load_json_fixture(fixture_path, _default_agent_task_cases(), require_exists=require_fixture):
        temp_db = Path(tempfile.gettempdir()) / f"seam-bench-agent-{uuid4().hex}.db"
        temp_runtime = runtime.__class__(temp_db)
        try:
            batch = compile_dsl(config["dsl"], scope="project")
            temp_runtime.persist_ir(batch)
            rag = RetrievalOrchestrator(temp_runtime).rag(
                config["query"],
                budget=int(config.get("budget", 5)),
                pack_budget=int(config.get("pack_budget", 128)),
            )
            prompt_payload = build_context_payload(rag.to_dict(), view="prompt")
            evidence_payload = build_context_payload(rag.to_dict(), view="evidence")
            summary_payload = build_context_payload(rag.to_dict(), view="summary")
            records_payload = build_context_payload(rag.to_dict(), view="records")
            prompt_text = render_context_pretty(prompt_payload)
            summary_text = render_context_pretty(summary_payload)
            records_text = render_context_pretty(records_payload)
            evidence_rows = evidence_payload["output"]
            payload_text = records_text if records_text != "[]" else prompt_text
            payload_benchmark = benchmark_text_lossless(payload_text, tokenizer=tokenizer, min_token_savings=0.10)
            prompt_tokens, estimator = count_prompt_tokens(prompt_text, tokenizer=tokenizer)
            records_tokens, _ = count_prompt_tokens(records_text, tokenizer=tokenizer)
            expected_hit = any(record_id in config["expected_ids"] for record_id in rag.candidate_ids)
            prompt_contains = all(snippet in prompt_text for snippet in config.get("required_prompt_snippets", []))
            summary_contains = all(snippet in summary_text for snippet in config.get("required_summary_snippets", []))
            evidence_contains = any(row["record_id"] in config["expected_ids"] for row in evidence_rows)
            records_contain = all(record_id in records_text for record_id in config["expected_ids"])
            artifact_id = None
            if persist:
                artifact_id = temp_runtime.store.write_machine_artifact(
                    source_type="benchmark.agent_task",
                    source_id=config["name"],
                    artifact=payload_benchmark.artifact.to_dict(include_machine_text=True),
                    roundtrip_ok=payload_benchmark.roundtrip_match,
                    metadata={"family": "agent_tasks", "case": config["name"], "projection": "exact_payload"},
                )
            case = {
                "case_id": config["name"],
                "status": "PASS"
                if expected_hit and prompt_contains and summary_contains and evidence_contains and records_contain and payload_benchmark.roundtrip_match
                else "FAIL",
                "metrics": {
                    "expected_hit": expected_hit,
                    "prompt_contains": prompt_contains,
                    "summary_contains": summary_contains,
                    "evidence_contains": evidence_contains,
                    "records_contain": records_contain,
                    "prompt_tokens": prompt_tokens,
                    "records_tokens": records_tokens,
                    "prompt_token_savings_vs_records": round(_savings_ratio(records_tokens, prompt_tokens), 6),
                    "exact_payload_lossless_savings": round(payload_benchmark.artifact.token_savings_ratio, 6),
                    "exact_payload_roundtrip_match": payload_benchmark.roundtrip_match,
                    "token_estimator": estimator,
                },
                "trace": {
                    "query": config["query"],
                    "candidate_ids": rag.candidate_ids,
                    "prompt": prompt_text,
                    "summary": summary_text,
                    "evidence": evidence_rows,
                    "exact_payload_compression": payload_benchmark.to_dict(include_machine_text=False),
                },
                "debug_flags": _agent_task_flags(
                    expected_hit,
                    prompt_contains,
                    summary_contains,
                    evidence_contains,
                    records_contain,
                    prompt_tokens,
                    records_tokens,
                ),
                "improvement_loop": _agent_task_actions(
                    expected_hit,
                    prompt_contains,
                    summary_contains,
                    evidence_contains,
                    records_contain,
                    prompt_tokens,
                    records_tokens,
                    payload_benchmark.artifact.token_savings_ratio,
                ),
            }
            if artifact_id is not None:
                case["artifact_id"] = artifact_id
            cases.append(_stamp_case_hash(case))
        finally:
            # Close the runtime before deleting temp_db; an open SQLite handle
            # blocks deletion on Windows (WinError 32) and leaks the temp file.
            temp_runtime.close()
            _cleanup_temp_db(temp_db)

    summary = {
        "case_count": len(cases),
        "pass_rate": _ratio(sum(1 for case in cases if case["status"] == "PASS"), len(cases)),
        "task_success_rate": _ratio(sum(1 for case in cases if case["metrics"]["expected_hit"]), len(cases)),
        "avg_prompt_token_savings_vs_records": _average(case["metrics"]["prompt_token_savings_vs_records"] for case in cases),
        "avg_exact_payload_lossless_savings": _average(case["metrics"]["exact_payload_lossless_savings"] for case in cases),
    }
    return {
        "family": "agent_tasks",
        "summary": summary,
        "cases": cases,
        "improvement_loop": _unique_actions(case["improvement_loop"] for case in cases),
    }
def _build_suite_summary(family_reports: dict[str, dict[str, Any]]) -> dict[str, Any]:
    cases = [case for family in family_reports.values() for case in family.get("cases", [])]
    token_savings = [
        case["metrics"].get("token_savings_ratio")
        for case in cases
        if isinstance(case.get("metrics", {}).get("token_savings_ratio"), (int, float))
    ]
    exactness_values = []
    for case in cases:
        metrics = case.get("metrics", {})
        if "roundtrip_match" in metrics:
            exactness_values.append(1.0 if metrics["roundtrip_match"] else 0.0)
        elif "exact_pack_reversible" in metrics:
            exactness_values.append(1.0 if metrics["exact_pack_reversible"] else 0.0)
        elif "prompt_roundtrip_match" in metrics:
            exactness_values.append(1.0 if metrics["prompt_roundtrip_match"] else 0.0)
    passed_cases = sum(1 for case in cases if case["status"] == "PASS")
    return {
        "status": "PASS" if cases and passed_cases == len(cases) else "FAIL",
        "family_count": len(family_reports),
        "case_count": len(cases),
        "passed_cases": passed_cases,
        "exactness_rate": _average(exactness_values) if exactness_values else 1.0,
        "token_savings_p50": _percentile(token_savings, 0.50),
        "token_savings_p95": _percentile(token_savings, 0.95),
        "token_savings_min": min(token_savings, default=0.0),
    }


def _aggregate_family_actions(family_reports: dict[str, dict[str, Any]]) -> list[str]:
    family_actions = [family.get("improvement_loop", []) for family in family_reports.values()]
    summary = _build_suite_summary(family_reports)
    actions = _unique_actions(family_actions)
    if summary["exactness_rate"] < 1.0:
        actions.insert(0, "Lossless and exact reconstruction gates must stay at 100% before release.")
    if summary.get("token_savings_available") and summary["token_savings_p50"] < 0.30:
        actions.append("Median token savings are below the machine-efficiency target; add stronger reversible transforms and projection rules.")
    return actions


def _load_json_fixture(path: Path, fallback: list[dict[str, Any]], require_exists: bool = False) -> list[dict[str, Any]]:
    if not path.exists():
        if require_exists:
            raise ValueError(f"Required benchmark fixture is missing: {path}")
        return fallback
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _default_lossless_cases() -> list[dict[str, Any]]:
    return [
        {"name": "lossless_demo_input", "source_file": str(LOSSLESS_DEMO_PATH), "min_token_savings": 0.75},
        {
            "name": "operator_memory_repeat",
            "text": "\n".join(["SEAM preserves exact context while compressing token usage for lossless recovery."] * 32),
            "min_token_savings": 0.30,
        },
    ]


def _default_readable_cases() -> list[dict[str, Any]]:
    return [
        {
            "name": "rc1_recipe_exact_direct_read",
            "text": "\n".join(
                [
                    "Recipe: Lemon Rice",
                    "Yield: 2 servings",
                    "Ingredients:",
                    "- 1 cup cooked rice",
                    "- 1 tablespoon lemon juice",
                    "- 1 teaspoon olive oil",
                    "- 1/4 teaspoon salt",
                    "Steps:",
                    "1. Warm the olive oil in a pan for 30 seconds.",
                    "2. Stir in the cooked rice and salt.",
                    "3. Turn off the heat and fold in the lemon juice.",
                    "Note: \"Serve immediately while warm.\"",
                ]
            ),
            "queries": [
                "Recipe Lemon Rice",
                "1 tablespoon lemon juice",
                "1/4 teaspoon salt",
                "Warm the olive oil in a pan for 30 seconds",
                '"Serve immediately while warm."',
            ],
            "include_direct_text_trace": True,
        },
        {
            "name": "rc1_exact_quote_table_number",
            "text": "\n".join(
                [
                    '# Operator Note',
                    'Decision: "SEAM-RC/1 is the working compressed document."',
                    'Budget table:',
                    '| item | value |',
                    '| original_tokens | 128 |',
                    '| rc1_tokens | 96 |',
                    'Requirement: quote spans, table cells, numbers, and provenance stay directly queryable.',
                ]
            ),
            "queries": [
                '"SEAM-RC/1 is the working compressed document."',
                "original_tokens 128",
                "rc1_tokens 96",
            ],
        },
        {
            "name": "rc1_repeated_direct_read_contract",
            "text": (
                'Rule: "Compressed SEAM language is read directly." '
                "Exact source details remain in machine-language chunks. "
                'Rule: "Compressed SEAM language is read directly."'
            ),
            "queries": [
                '"Compressed SEAM language is read directly."',
                "machine-language chunks",
            ],
        },
    ]


def _default_surface_cases() -> list[dict[str, Any]]:
    return [
        {
            "name": "hs1_rc1_direct_query_rgb24",
            "payload_kind": "readable",
            "mode": "rgb24",
            "text": (
                'Surface note: "Holographic Surface stores SEAM-RC/1 as exact pixel bytes." '
                "Direct queries read the embedded machine language without OCR or SQLite import."
            ),
            "queries": [
                '"Holographic Surface stores SEAM-RC/1 as exact pixel bytes."',
                "without OCR SQLite import",
            ],
        },
        {
            "name": "hs1_mirl_direct_search_bw1",
            "payload_kind": "mirl",
            "mode": "bw1",
            "dsl": """
entity project "SEAM" as p1
claim c1:
  subject p1
  predicate holographic_surface
  object direct_read_memory
claim c2:
  subject p1
  predicate stores
  object machine_language_pixels
""",
            "queries": ["holographic_surface direct_read_memory", "machine_language_pixels"],
        },
        {
            "name": "hs1_rc1_direct_query_rgba32",
            "payload_kind": "readable",
            "mode": "rgba32",
            "text": (
                'Surface density note: "RGBA32 stores four exact channel bytes per pixel." '
                "SEAM keeps RGB24 as the default and uses RGBA32 only when explicitly requested."
            ),
            "queries": [
                '"RGBA32 stores four exact channel bytes per pixel."',
                "explicitly requested",
            ],
        },
        {
            "name": "hs1_rc1_direct_query_rgba64",
            "payload_kind": "readable",
            "mode": "rgba64",
            "text": (
                'Surface density note: "RGBA64 stores eight exact channel bytes per pixel." '
                "SEAM uses RGBA64 only when 16-bit channel density is explicitly requested."
            ),
            "queries": [
                '"RGBA64 stores eight exact channel bytes per pixel."',
                "16-bit channel density",
            ],
        },
    ]


def _surface_case_payload(config: dict[str, Any]) -> tuple[bytes, str]:
    payload_kind = str(config.get("payload_kind", "readable"))
    if payload_kind == "readable":
        text = _resolve_lossless_text(config)
        artifact = compress_text_readable(
            text,
            source_ref=str(config.get("source_ref", f"benchmark://surface/{config['name']}")),
            granularity=str(config.get("granularity", "auto")),
            tokenizer=str(config.get("tokenizer", "char4_approx")),
        )
        return artifact.machine_text.encode("utf-8"), "SEAM-RC/1"
    if payload_kind == "mirl":
        batch = compile_dsl(str(config["dsl"]), scope=str(config.get("scope", "project")))
        return batch.to_text().encode("utf-8"), "MIRL"
    if "payload" in config:
        return str(config["payload"]).encode("utf-8"), str(config.get("payload_format", "bytes"))
    raise ValueError(f"Unsupported surface fixture payload_kind: {payload_kind}")


def _surface_query_checks(
    surface_path: Path,
    config: dict[str, Any],
    source_quotes: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    checks = []
    use_precision = source_quotes is not None
    quotes = source_quotes or []
    for query in config.get("queries", []):
        result = query_surface(surface_path, str(query), limit=5).to_dict()
        hits = result.get("hits", [])
        if use_precision:
            expected = _expected_query_text(str(query), quotes)
            ok = any(_hit_satisfies_expected(hit, expected) for hit in hits)
        else:
            expected = str(query)
            ok = bool(hits)
        checks.append(
            {
                "query": query,
                "expected": expected,
                "ok": ok,
                "hit_count": len(hits),
                "top_hit": hits[0] if hits else None,
            }
        )
    return checks


def _surface_stored_query_and_repair_checks(
    surface_store: SQLiteStore,
    artifact: dict[str, object],
    surface_path: Path,
    *,
    source_sha256: str,
    config: dict[str, Any],
    artifact_dir: Path,
) -> dict[str, Any]:
    surface_bytes = surface_path.read_bytes()
    surface_sha256 = hashlib.sha256(surface_bytes).hexdigest()
    artifact_payload = dict(artifact)
    redundant = SurfaceFileAdapter(artifact_dir).store_copy(surface_path, surface_sha256)
    artifact_payload["original_path"] = artifact_payload.get("path")
    artifact_payload["path"] = redundant.artifact_path
    artifact_payload["surface_sha256"] = redundant.surface_sha256
    stored = surface_store.write_surface_artifact(
        artifact_payload,
        source_ref=str(artifact_payload.get("source_ref", "")),
        source_sha256=source_sha256,
        verification_status="PASS",
        metadata={
            "stored_by": "surface benchmark",
            "redundant_copy": redundant.to_dict(),
        },
    )

    surface_id = str(stored["surface_id"])
    surface_path.unlink()
    original_removed = not surface_path.exists()
    stored_after_delete = surface_store.read_surface_artifact(surface_id)
    stored_path = Path(str(stored_after_delete["artifact_path"]))
    stored_lookup = (
        stored_path.exists()
        and str(stored_after_delete["surface_sha256"]) == redundant.surface_sha256
        and str(stored_after_delete["surface_id"]) == surface_id
    )
    stored_query_checks = _surface_query_checks(stored_path, config) if stored_lookup and original_removed else []
    stored_query_exactness = stored_lookup and original_removed and all(item["ok"] for item in stored_query_checks)

    surface_path.write_bytes(surface_bytes)
    if stored_path.exists():
        stored_path.unlink()
    repair = SurfaceFileAdapter(stored_path.parent).repair_copy(
        stored_path,
        surface_sha256=redundant.surface_sha256,
        source_path=surface_path,
    )
    repair_ok = repair.status == "PASS"
    repaired = surface_store.update_surface_artifact_state(
        surface_id,
        artifact_path=repair.artifact_path,
        verification_status="PASS" if repair_ok else "FAIL",
        query_status=str(stored_after_delete["query_status"]) if repair_ok else "unavailable",
        metadata={"last_benchmark_repair": repair.to_dict()},
    )
    repaired_path = Path(str(repaired["artifact_path"]))
    repair_query_checks = _surface_query_checks(repaired_path, config) if repair_ok and repaired_path.exists() else []
    repair_query_exactness = repair_ok and all(item["ok"] for item in repair_query_checks)

    return {
        "surface_id": surface_id,
        "stored_lookup": stored_lookup,
        "original_removed_before_stored_query": original_removed,
        "stored_query_exactness": stored_query_exactness,
        "repair_ok": repair_ok,
        "repair_query_exactness": repair_query_exactness,
        "stored_path": str(stored_path),
        "stored_row": stored_after_delete,
        "redundant_copy": redundant.to_dict(),
        "stored_query_checks": stored_query_checks,
        "repair": repair.to_dict(),
        "repaired_row": repaired,
        "repair_query_checks": repair_query_checks,
    }


def _surface_flags(
    surface_exact: bool,
    payload_hash_match: bool,
    verify_ok: bool,
    direct_query_exactness: bool,
    stored_lookup: bool,
    stored_query_exactness: bool,
    repair_ok: bool,
    repair_query_exactness: bool,
) -> list[str]:
    flags = []
    if not surface_exact:
        flags.append("surface_decode_mismatch")
    if not payload_hash_match:
        flags.append("payload_hash_mismatch")
    if not verify_ok:
        flags.append("surface_verify_failed")
    if not direct_query_exactness:
        flags.append("surface_direct_query_failed")
    if not stored_lookup:
        flags.append("surface_stored_lookup_failed")
    if not stored_query_exactness:
        flags.append("surface_stored_query_failed")
    if not repair_ok:
        flags.append("surface_repair_failed")
    if not repair_query_exactness:
        flags.append("surface_repair_query_failed")
    return flags


def _surface_actions(
    case_name: str,
    surface_exact: bool,
    payload_hash_match: bool,
    verify_ok: bool,
    direct_query_exactness: bool,
    stored_lookup: bool,
    stored_query_exactness: bool,
    repair_ok: bool,
    repair_query_exactness: bool,
) -> list[str]:
    actions = []
    if not surface_exact:
        actions.append(f"inspect SEAM-HS/1 pixel packing for {case_name}; decoded payload must be byte-exact")
    if not payload_hash_match or not verify_ok:
        actions.append(f"inspect SEAM-HS/1 envelope/hash verification for {case_name}")
    if not direct_query_exactness:
        actions.append(f"inspect surface query dispatch for {case_name}; embedded MIRL/RC payloads must be directly searchable")
    if not stored_lookup:
        actions.append(f"inspect surface library metadata lookup for {case_name}; stored hs:<hash> IDs must resolve to verified PNG copies")
    if not stored_query_exactness:
        actions.append(f"inspect stored surface query path for {case_name}; direct answers must survive deletion of the original output path")
    if not repair_ok or not repair_query_exactness:
        actions.append(f"inspect surface repair path for {case_name}; repaired redundant copies must be hash-safe and directly queryable")
    return actions


def _default_long_context_cases() -> list[dict[str, Any]]:
    return [
        {
            "name": "translator_anchor_early",
            "query": "predicate:translator_for object:natural_language",
            "expected_ids": ["anchor_early"],
            "required_prompt_snippets": ["translator_for", "natural_language"],
            "required_summary_snippets": ["translator_for", "natural_language"],
            "filler_count": 18,
            "target_position": "early",
            "target": {"id": "anchor_early", "predicate": "translator_for", "object": "natural_language"},
        },
        {
            "name": "projection_anchor_late",
            "query": "predicate:projection_index object:tokenizer_projection",
            "expected_ids": ["anchor_late"],
            "required_prompt_snippets": ["projection_index", "tokenizer_projection"],
            "required_summary_snippets": ["projection_index", "tokenizer_projection"],
            "filler_count": 18,
            "target_position": "late",
            "target": {"id": "anchor_late", "predicate": "projection_index", "object": "tokenizer_projection"},
        },
    ]


def _default_agent_task_cases() -> list[dict[str, Any]]:
    return [
        {
            "name": "translator_context_task",
            "query": "predicate:translator_for object:natural_language",
            "expected_ids": ["c1"],
            "required_prompt_snippets": ["translator_for", "natural_language"],
            "required_summary_snippets": ["translator_for", "natural_language"],
            "dsl": """
entity project "SEAM" as p1
claim c1:
  subject p1
  predicate translator_for
  object natural_language
claim c2:
  subject p1
  predicate memory_runtime
  object durable_context
claim c3:
  subject p1
  predicate exact_rebuild
  object source_state
""",
        },
        {
            "name": "projection_context_task",
            "query": "predicate:projection_index object:tokenizer_projection",
            "expected_ids": ["c2"],
            "required_prompt_snippets": ["projection_index", "tokenizer_projection"],
            "required_summary_snippets": ["projection_index", "tokenizer_projection"],
            "dsl": """
entity project "SEAM" as p1
claim c1:
  subject p1
  predicate persistent_memory
  object sqlite_truth
claim c2:
  subject p1
  predicate projection_index
  object tokenizer_projection
claim c3:
  subject p1
  predicate benchmark_engine
  object glassbox_traces
""",
        },
    ]


def _resolve_lossless_text(config: dict[str, Any]) -> str:
    source_file = config.get("source_file")
    if source_file:
        return Path(source_file).read_text(encoding="utf-8")
    return str(config.get("text", ""))


def _build_long_context_dsl(config: dict[str, Any]) -> str:
    target = config["target"]
    filler_count = int(config.get("filler_count", 12))
    filler_claims = [
        f"""claim filler_{index}:
  subject p1
  predicate memory_note_{index}
  object filler_context_{index}
"""
        for index in range(1, filler_count + 1)
    ]
    target_claim = f"""claim {target['id']}:
  subject p1
  predicate {target['predicate']}
  object {target['object']}
"""
    if config.get("target_position") == "early":
        claim_blocks = [target_claim, *filler_claims]
    else:
        claim_blocks = [*filler_claims, target_claim]
    return "\n".join(['entity project "SEAM" as p1', *claim_blocks])


def _dataset_manifest(holdout: bool = False) -> list[dict[str, str]]:
    items = []
    paths = [LOSSLESS_FIXTURE_PATH, READABLE_FIXTURE_PATH, SURFACE_FIXTURE_PATH, LONG_CONTEXT_FIXTURE_PATH, AGENT_TASK_FIXTURE_PATH, RETRIEVAL_FIXTURE_PATH, LOSSLESS_DEMO_PATH]
    if holdout:
        paths.extend(
            [
                _holdout_fixture_path(LOSSLESS_FIXTURE_PATH),
                _holdout_fixture_path(READABLE_FIXTURE_PATH),
                _holdout_fixture_path(SURFACE_FIXTURE_PATH),
                _holdout_fixture_path(LONG_CONTEXT_FIXTURE_PATH),
                _holdout_fixture_path(AGENT_TASK_FIXTURE_PATH),
                _holdout_fixture_path(RETRIEVAL_FIXTURE_PATH),
            ]
        )
    for path in paths:
        if path.exists():
            items.append({"path": str(path), "scope": "holdout" if HOLDOUT_FIXTURE_ROOT in path.parents else "public", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return items


def _selected_suites(suite: str, holdout: bool) -> list[str]:
    if not holdout:
        return list(BENCHMARK_SUITES) if suite == "all" else [_validate_suite_name(suite)]
    if suite != "all":
        selected = _validate_suite_name(suite)
        if selected not in HOLDOUT_BENCHMARK_SUITES:
            raise ValueError(f"Benchmark suite does not have holdout fixtures: {selected}")
        fixture = _fixture_for_family(selected, holdout=True)
        if not fixture.exists():
            raise ValueError(f"Holdout fixture not found for {selected}: {fixture}")
        return [selected]
    available = [family for family in HOLDOUT_BENCHMARK_SUITES if _fixture_for_family(family, holdout=True).exists()]
    if not available:
        raise ValueError(f"No holdout fixtures found under {HOLDOUT_FIXTURE_ROOT}")
    return available


def _fixture_for_family(family: str, holdout: bool) -> Path:
    public_paths = {
        "lossless": LOSSLESS_FIXTURE_PATH,
        "readable": READABLE_FIXTURE_PATH,
        "surface": SURFACE_FIXTURE_PATH,
        "retrieval": RETRIEVAL_FIXTURE_PATH,
        "embedding": RETRIEVAL_FIXTURE_PATH,
        "long_context": LONG_CONTEXT_FIXTURE_PATH,
        "agent_tasks": AGENT_TASK_FIXTURE_PATH,
    }
    path = public_paths[family]
    return _holdout_fixture_path(path) if holdout else path


def _holdout_fixture_path(public_path: Path) -> Path:
    return HOLDOUT_FIXTURE_ROOT / public_path.name


def _validate_suite_name(suite: str) -> str:
    if suite not in BENCHMARK_SUITES:
        raise ValueError(f"Unsupported benchmark suite: {suite}")
    return suite


def _stamp_case_hash(case: dict[str, Any]) -> dict[str, Any]:
    stamped = dict(case)
    stamped["case_hash"] = _hash_payload(stamped, "case_hash")
    return stamped


def _hash_payload(payload: dict[str, Any], ignore_key: str) -> str:
    normalized = {key: value for key, value in payload.items() if key != ignore_key}
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_benchmark_payload(source: str | Path | dict[str, Any]) -> dict[str, Any]:
    if isinstance(source, dict):
        return dict(source)
    path = Path(source)
    if not path.exists():
        raise ValueError(f"Benchmark bundle not found: {source}")
    return json.loads(path.read_text(encoding="utf-8"))


def _load_gate_policy(source: str | Path | dict[str, Any] | None) -> dict[str, Any]:
    if source is None:
        return json.loads(json.dumps(DEFAULT_BENCHMARK_GATE_POLICY))
    if isinstance(source, dict):
        return json.loads(json.dumps(source))
    path = Path(source)
    if not path.exists():
        raise ValueError(f"Benchmark gate policy not found: {source}")
    return json.loads(path.read_text(encoding="utf-8"))


def _gate_check(
    scope: str,
    metric: str,
    actual: Any,
    rule: dict[str, Any],
    message: str | None = None,
) -> dict[str, Any]:
    passed = True
    failure = message or "benchmark gate rule failed"
    if "equals" in rule:
        expected = rule["equals"]
        passed = actual == expected
        failure = message or f"expected {expected!r}"
    elif "minimum" in rule:
        actual_number = _numeric_metric(actual)
        minimum = _numeric_metric(rule["minimum"])
        passed = actual_number is not None and minimum is not None and actual_number >= minimum
        failure = message or f"expected >= {rule['minimum']!r}"
    elif "maximum" in rule:
        actual_number = _numeric_metric(actual)
        maximum = _numeric_metric(rule["maximum"])
        passed = actual_number is not None and maximum is not None and actual_number <= maximum
        failure = message or f"expected <= {rule['maximum']!r}"
    else:
        passed = False
        failure = message or f"unsupported gate rule: {rule}"
    return {
        "status": "PASS" if passed else "FAIL",
        "scope": scope,
        "metric": metric,
        "actual": actual,
        "rule": dict(rule),
        "message": "" if passed else failure,
    }


def _flatten_benchmark_cases(payload: dict[str, Any]) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for family_name, family in payload.get("families", {}).items():
        for case in family.get("cases", []):
            case_id = str(case.get("case_id", "unknown"))
            flattened.append(
                {
                    "identity": f"{family_name}::{case_id}",
                    "family": family_name,
                    "case_id": case_id,
                    "case_hash": case.get("case_hash"),
                    "status": case.get("status"),
                    "metrics": dict(case.get("metrics", {})),
                }
            )
    return flattened


def _diff_case(left: dict[str, Any], right: dict[str, Any], join_key: str, join_type: str) -> dict[str, Any]:
    metric_deltas = []
    left_metrics = left.get("metrics", {})
    right_metrics = right.get("metrics", {})
    for metric in sorted(set(left_metrics) | set(right_metrics)):
        if metric not in left_metrics or metric not in right_metrics:
            continue
        delta = _metric_delta(metric, left_metrics[metric], right_metrics[metric])
        if delta is not None:
            metric_deltas.append(delta)
    return {
        "family": right["family"],
        "case_id": right["case_id"],
        "join_key": join_key,
        "join_type": join_type,
        "case_hash_a": left.get("case_hash"),
        "case_hash_b": right.get("case_hash"),
        "case_hash_changed": left.get("case_hash") != right.get("case_hash"),
        "status_a": left.get("status"),
        "status_b": right.get("status"),
        "status_delta": _status_delta(left.get("status"), right.get("status")),
        "metric_deltas": metric_deltas,
    }


def _metric_delta(metric: str, left: Any, right: Any) -> dict[str, Any] | None:
    left_number = _numeric_metric(left)
    right_number = _numeric_metric(right)
    if left_number is None or right_number is None:
        return None
    delta = right_number - left_number
    if delta == 0:
        indicator = "gray"
    elif _lower_is_better(metric):
        indicator = "green" if delta < 0 else "red"
    else:
        indicator = "green" if delta > 0 else "red"
    return {
        "metric": metric,
        "a": left,
        "b": right,
        "delta": round(delta, 6),
        "indicator": indicator,
    }


def _numeric_metric(value: Any) -> float | None:
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _lower_is_better(metric: str) -> bool:
    lowered = metric.lower()
    return any(term in lowered for term in ("error", "failure", "latency", "cost", "tokens", "bytes", "regression"))


def _status_delta(left: Any, right: Any) -> str:
    if left == right:
        return "unchanged"
    if left != "PASS" and right == "PASS":
        return "improved"
    if left == "PASS" and right != "PASS":
        return "regressed"
    return "changed"


def _status_marker(status_delta: Any) -> str:
    return {
        "improved": "[green]",
        "regressed": "[red]",
        "changed": "[yellow]",
        "unchanged": "[gray]",
    }.get(str(status_delta), "[gray]")


def _case_ref(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "family": case.get("family"),
        "case_id": case.get("case_id"),
        "case_hash": case.get("case_hash"),
        "status": case.get("status"),
    }


def _run_ref(payload: dict[str, Any]) -> dict[str, Any]:
    manifest = payload.get("manifest", {})
    return {
        "run_id": manifest.get("run_id"),
        "created_at": manifest.get("created_at"),
        "fixture_scope": manifest.get("fixture_scope", "public"),
        "executed_suites": manifest.get("executed_suites", []),
        "bundle_hash": payload.get("bundle_hash"),
    }


def _lossless_actions(result, case_id: str) -> list[str]:
    actions = []
    if not result.roundtrip_match:
        actions.append(f"{case_id}: investigate lossless roundtrip mismatch before trusting machine-language compression.")
    if not result.meets_target:
        actions.append(f"{case_id}: add stronger reversible transforms or codec ordering because token savings target was missed.")
    if any(flag.startswith("iteration_") for flag in result.flags):
        actions.append(f"{case_id}: review fluctuation log and promote stable reversible rules from the best candidate search.")
    return actions


def _quote_span_records(text: str) -> list[dict[str, Any]]:
    return [
        {
            "text": span["text"],
            "value": span["value"],
            "start": span["start"],
            "end": span["end"],
        }
        for span in _structural_quote_spans(text)
    ]


def _compressed_quote_records(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "text": str(quote["text"]),
            "value": str(quote.get("value", "")),
            "start": int(quote["start"]),
            "end": int(quote["end"]),
        }
        for quote in parsed.get("quotes", [])
    ]


def _read_rc1_text_direct(parsed: dict[str, Any]) -> str:
    chunks = {str(chunk["id"]): str(chunk["text"]) for chunk in parsed.get("chunks", [])}
    return "".join(chunks[str(item["id"])] for item in parsed.get("order", []))


def _benchmark_terms(text: str) -> list[str]:
    import re

    terms: list[str] = []
    for token in re.findall(r"[a-z0-9_:-]+", text.lower()):
        terms.append(token)
        stripped = token.strip(":-")
        if stripped and stripped != token:
            terms.append(stripped)
    return terms


def _readable_query_checks(machine_text: str, config: dict[str, Any], source_quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    query_texts = list(config.get("queries", []))
    for quote in source_quotes:
        query = str(quote["text"])
        if query not in query_texts:
            query_texts.append(query)
    checks: list[dict[str, Any]] = []
    for query in query_texts:
        result = query_readable_compressed(machine_text, str(query), limit=5)
        hits = result.to_dict()["hits"]
        expected = _expected_query_text(str(query), source_quotes)
        ok = any(_hit_satisfies_expected(hit, expected) for hit in hits)
        checks.append(
            {
                "query": str(query),
                "expected": expected,
                "ok": ok,
                "top_hits": hits[:3],
            }
        )
    return checks


def _expected_query_text(query: str, source_quotes: list[dict[str, Any]]) -> str:
    if query.startswith('"') and query.endswith('"'):
        return query
    lowered = query.lower()
    for quote in source_quotes:
        if lowered in str(quote["text"]).lower() or lowered in str(quote["value"]).lower():
            return str(quote["text"])
    return query


def _hit_satisfies_expected(hit: dict[str, Any], expected: str) -> bool:
    text = str(hit.get("text", ""))
    if expected == text or expected.lower() in text.lower():
        return True
    expected_terms = set(_benchmark_terms(expected))
    hit_terms = set(_benchmark_terms(text))
    return bool(expected_terms) and expected_terms.issubset(hit_terms)


def _readable_flags(direct_text_match: bool, rebuild_match: bool, direct_quote_match: bool, direct_query_exactness: bool, term_coverage: bool) -> list[str]:
    flags = []
    if not direct_text_match:
        flags.append("rc1_direct_text_mismatch")
    if not rebuild_match:
        flags.append("rc1_rebuild_mismatch")
    if not direct_quote_match:
        flags.append("rc1_quote_mismatch")
    if not direct_query_exactness:
        flags.append("rc1_direct_query_miss")
    if not term_coverage:
        flags.append("rc1_term_coverage_gap")
    return flags


def _readable_actions(case_id: str, direct_text_match: bool, rebuild_match: bool, direct_quote_match: bool, direct_query_exactness: bool, term_coverage: bool) -> list[str]:
    actions = []
    if not direct_text_match:
        actions.append(f"{case_id}: inspect SEAM-RC/1 CHUNK and ORDER records because direct compressed-language readback is not source-exact.")
    if not rebuild_match:
        actions.append(f"{case_id}: inspect SEAM-RC/1 ORDER and CHUNK records because exact rebuild diverged from source.")
    if not direct_quote_match:
        actions.append(f"{case_id}: inspect QUOTE record extraction because source quote spans are not preserved 1:1.")
    if not direct_query_exactness:
        actions.append(f"{case_id}: improve readable-query matching because compressed-language reads missed expected source facts.")
    if not term_coverage:
        actions.append(f"{case_id}: inspect INDEX generation because source terms are not all represented in RC/1 postings.")
    return actions


def _retrieval_flags(fixture: dict[str, Any]) -> list[str]:
    flags = []
    if not fixture["tracks"]["hybrid"]["hit"]:
        flags.append("hybrid_miss")
    if fixture["tracks"]["hybrid"]["recall_at_k"] < fixture["tracks"]["raw"]["recall_at_k"]:
        flags.append("hybrid_below_raw")
    if fixture["packs"]["context"]["traceability"] < 0.66:
        flags.append("context_traceability_low")
    return flags


def _retrieval_actions(fixture: dict[str, Any]) -> list[str]:
    actions = []
    hybrid = fixture["tracks"]["hybrid"]
    raw = fixture["tracks"]["raw"]
    if not hybrid["hit"]:
        actions.append(f"{fixture['name']}: improve structured query planning or lexical gating because hybrid retrieval missed the expected record.")
    if hybrid["recall_at_k"] < raw["recall_at_k"]:
        actions.append(f"{fixture['name']}: hybrid ranking regressed below raw search; inspect merge weights and SQL/vector balance.")
    if fixture["packs"]["context"]["traceability"] < 0.66:
        actions.append(f"{fixture['name']}: context pack traceability is weak; inspect pack provenance and citation renderers.")
    return actions


def _embedding_actions(top_record_id: str | None, expected_ids: list[str], margin: float) -> list[str]:
    actions = []
    if top_record_id not in expected_ids:
        actions.append("Embedding top-1 ranking missed the expected record; compare natural, machine, and hybrid projection text.")
    if margin < 0.05:
        actions.append("Embedding separation margin is weak; benchmark alternate embedding models or retrieval projections before promotion.")
    return actions


def _long_context_flags(expected_hit: bool, prompt_contains: bool, summary_contains: bool, prompt_tokens: int, records_tokens: int) -> list[str]:
    flags = []
    if not expected_hit:
        flags.append("anchor_miss")
    if not prompt_contains:
        flags.append("prompt_missing_signal")
    if not summary_contains:
        flags.append("summary_missing_signal")
    if prompt_tokens > records_tokens:
        flags.append("prompt_bloat")
    return flags


def _long_context_actions(expected_hit: bool, prompt_contains: bool, summary_contains: bool, prompt_tokens: int, records_tokens: int) -> list[str]:
    actions = []
    if not expected_hit:
        actions.append("Long-context retrieval missed an anchor; improve segmentation, lexical gating, or retrieval planning for large histories.")
    if not prompt_contains or not summary_contains:
        actions.append("Long-context views dropped required evidence; tighten prompt/summary renderers so critical facts survive compression.")
    if prompt_tokens > records_tokens:
        actions.append("Prompt-ready context is larger than the exact records payload; tune projection rules to reduce prompt bloat.")
    return actions


def _agent_task_flags(
    expected_hit: bool,
    prompt_contains: bool,
    summary_contains: bool,
    evidence_contains: bool,
    records_contain: bool,
    prompt_tokens: int,
    records_tokens: int,
) -> list[str]:
    flags = []
    if not expected_hit:
        flags.append("task_retrieval_miss")
    if not prompt_contains:
        flags.append("task_prompt_missing_signal")
    if not summary_contains:
        flags.append("task_summary_missing_signal")
    if not evidence_contains:
        flags.append("task_evidence_missing_citation")
    if not records_contain:
        flags.append("task_records_missing_exact_payload")
    if prompt_tokens > records_tokens:
        flags.append("task_prompt_bloat")
    return flags


def _agent_task_actions(
    expected_hit: bool,
    prompt_contains: bool,
    summary_contains: bool,
    evidence_contains: bool,
    records_contain: bool,
    prompt_tokens: int,
    records_tokens: int,
    prompt_lossless_savings: float,
) -> list[str]:
    actions = []
    if not expected_hit:
        actions.append("Agent task retrieval missed the expected record; improve retrieval plan selection for operator tasks.")
    if not (prompt_contains and summary_contains and evidence_contains and records_contain):
        actions.append("One or more agent-facing views dropped required signal; align context renderers before using them as the default agent surface.")
    if prompt_tokens > records_tokens:
        actions.append("Prompt view is more expensive than records view; tighten prompt projection and benchmark token savings again.")
    if prompt_lossless_savings < 0.10:
        actions.append("Prompt compression headroom is weak; add reversible projection rules before claiming machine-efficiency gains for agent contexts.")
    return actions

def _render_key_metrics(family_name: str, summary: dict[str, Any]) -> str:
    if family_name == "lossless":
        return f"avg_savings={float(summary.get('avg_token_savings', 0.0)):.1%}"
    if family_name == "readable":
        return (
            f"direct_text={float(summary.get('direct_text_exact_rate', 0.0)):.1%} "
            f"direct_read={float(summary.get('direct_read_equivalence_rate', 0.0)):.1%}"
        )
    if family_name == "surface":
        return (
            f"surface_exact={float(summary.get('surface_exact_rate', 0.0)):.1%} "
            f"hash={float(summary.get('payload_hash_match_rate', 0.0)):.1%}"
        )
    if family_name == "retrieval":
        nat = float(summary.get('hybrid_recall_at_k', 0.0))
        mac = float(summary.get('machine_hybrid_recall_at_k', 0.0))
        return f"hybrid_recall={nat:.1%} machine_hybrid_recall={mac:.1%}"
    if family_name == "embedding":
        return f"avg_margin={float(summary.get('avg_margin', 0.0)):.3f}"
    if family_name == "long_context":
        return f"prompt_savings={float(summary.get('avg_prompt_token_savings_vs_records', 0.0)):.1%}"
    if family_name == "persistence":
        return f"durability={float(summary.get('durability_rate', 0.0)):.1%}"
    if family_name == "agent_tasks":
        return f"task_success={float(summary.get('task_success_rate', 0.0)):.1%}"
    return "n/a"


def _ndcg_at_k(ranked_ids: list[str], expected_ids: list[str]) -> float:
    if not ranked_ids or not expected_ids:
        return 0.0
    gains = []
    for rank, record_id in enumerate(ranked_ids, start=1):
        if record_id in expected_ids:
            gains.append(1.0 / _log2(rank + 1))
    ideal = [1.0 / _log2(rank + 1) for rank in range(1, min(len(expected_ids), len(ranked_ids)) + 1)]
    ideal_dcg = sum(ideal)
    return round(sum(gains) / ideal_dcg, 6) if ideal_dcg else 0.0


def _log2(value: int) -> float:
    import math

    return math.log2(value)


def _savings_ratio(original: int, compressed: int) -> float:
    if original <= 0:
        return 0.0
    return 1.0 - (compressed / original)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _git_sha() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    return result.stdout.strip() or None


def _average(values) -> float:
    numeric = [float(value) for value in values if isinstance(value, (int, float))]
    if not numeric:
        return 0.0
    return round(sum(numeric) / len(numeric), 6)


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 6)


def _percentile(values: list[float], percentile: float) -> float:
    numeric = sorted(float(value) for value in values if isinstance(value, (int, float)))
    if not numeric:
        return 0.0
    index = int(round((len(numeric) - 1) * percentile))
    return round(numeric[index], 6)


def _unique_actions(action_groups) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for group in action_groups:
        for action in group:
            if action and action not in seen:
                seen.add(action)
                output.append(action)
    return output










def _cleanup_temp_db(base_path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(base_path) + suffix)
        if candidate.exists():
            try:
                candidate.unlink()
            except PermissionError:
                pass
