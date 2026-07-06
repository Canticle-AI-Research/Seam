from __future__ import annotations

import argparse
import json
from pathlib import Path

from seam_runtime.external_memory_benchmarks import (
    benchmark_plan,
    render_external_memory_plan_pretty,
    render_external_memory_report_pretty,
    run_external_memory_benchmarks,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run SEAM external memory benchmark registry commands")
    parser.add_argument("--scope", default="required", help="required, all, or a single benchmark id")
    parser.add_argument("--strict", action="store_true", help="Fail when required runners are not configured")
    parser.add_argument("--plan", action="store_true", help="Only print the benchmark runner plan")
    parser.add_argument("--output", help="Write JSON plan/report to this path")
    parser.add_argument("--format", choices=["pretty", "json"], default="pretty")
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.plan:
        payload = benchmark_plan(scope=args.scope)
        text = json.dumps(payload, indent=2) if args.format == "json" else render_external_memory_plan_pretty(payload)
        exit_code = 0
    else:
        payload = run_external_memory_benchmarks(scope=args.scope, strict=args.strict, timeout_seconds=args.timeout_seconds)
        text = json.dumps(payload, indent=2) if args.format == "json" else render_external_memory_report_pretty(payload)
        exit_code = 1 if payload.get("status") == "FAIL" else 0
    if args.output:
        Path(args.output).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(text)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
