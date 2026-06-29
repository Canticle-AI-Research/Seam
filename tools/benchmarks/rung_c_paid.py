from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from benchmarks.external.common.dataset import load_locomo_cases


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET = REPO_ROOT / "benchmarks" / "external" / "locomo" / "data" / "locomo10.json"
DEFAULT_SLICE_DIR = REPO_ROOT / "test_seam" / "locomo" / "rung_c"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "benchmarks" / "runs" / "locomo"


def write_scope_slice(dataset_path: Path, slice_path: Path, *, scope_count: int) -> dict[str, int]:
    """Write a LoCoMo JSON slice containing the first N conversation samples."""
    if scope_count < 1:
        raise ValueError("scope_count must be >= 1")
    raw = json.loads(Path(dataset_path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("LoCoMo dataset root must be a JSON list")
    if len(raw) < scope_count:
        raise ValueError(f"requested {scope_count} scopes but dataset has {len(raw)}")

    selected = raw[:scope_count]
    slice_path.parent.mkdir(parents=True, exist_ok=True)
    slice_path.write_text(json.dumps(selected, indent=2), encoding="utf-8")
    return {
        "scope_count": len(selected),
        "case_count": len(load_locomo_cases(slice_path)),
    }


def build_plan(
    *,
    dataset_path: Path,
    slice_path: Path,
    output_dir: Path,
    adapters: Iterable[str],
    answerer_model: str = "gpt-4o-mini",
    judge_model: str = "gpt-4o-mini",
    mem0_search_limit: int | None = None,
    benchmark_dry_run: bool = False,
) -> dict:
    """Build the exact commands for the rung-C SEAM-broad vs mem0 diagnostic."""
    adapter_list = tuple(adapters)
    output_dir.mkdir(parents=True, exist_ok=True)

    commands: dict[str, list[str]] = {}
    for adapter in adapter_list:
        cmd = [
            sys.executable,
            "-m",
            "benchmarks.external.locomo.run",
            "--dataset-path",
            str(slice_path),
            "--adapter",
            adapter,
            "--answerer",
            "openai",
            "--answerer-model",
            answerer_model,
            "--judge",
            "openai",
            "--judge-model",
            judge_model,
            "--output",
            str(output_dir / f"rungc_{adapter}.json"),
        ]
        if adapter == "seam":
            cmd.extend(
                [
                    "--search-top-k",
                    "300",
                    "--context-budget",
                    "60000",
                ]
            )
        if adapter == "mem0" and mem0_search_limit is not None:
            cmd.extend(["--mem0-search-limit", str(mem0_search_limit)])
        if benchmark_dry_run:
            cmd.append("--dry-run")
        commands[adapter] = cmd

    return {
        "dataset_path": str(dataset_path),
        "slice_path": str(slice_path),
        "output_dir": str(output_dir),
        "commands": commands,
        "paid_required": not benchmark_dry_run,
        "operator_gate": "Actual provider execution requires --execute --confirm-paid.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.execute and not args.confirm_paid and not args.benchmark_dry_run:
        parser.error("--execute requires --confirm-paid unless --benchmark-dry-run is set")

    dataset_path = Path(args.dataset_path).expanduser()
    output_dir = Path(args.output_dir).expanduser()
    slice_path = (
        Path(args.slice_path).expanduser()
        if args.slice_path
        else DEFAULT_SLICE_DIR / f"locomo_first_{args.scopes}_scopes.json"
    )
    adapters = ("seam", "mem0") if args.adapter == "both" else (args.adapter,)

    slice_summary = write_scope_slice(dataset_path, slice_path, scope_count=args.scopes)
    plan = build_plan(
        dataset_path=dataset_path,
        slice_path=slice_path,
        output_dir=output_dir,
        adapters=adapters,
        answerer_model=args.answerer_model,
        judge_model=args.judge_model,
        mem0_search_limit=args.mem0_search_limit,
        benchmark_dry_run=args.benchmark_dry_run,
    )
    report = {
        "rung": "C",
        "benchmark": "locomo",
        "adapter": args.adapter,
        "execute": bool(args.execute),
        "confirm_paid": bool(args.confirm_paid),
        "slice": slice_summary,
        **plan,
    }

    if not args.execute:
        _emit_report(report, json_output=args.json)
        return 0

    results = {}
    env = os.environ.copy()
    for adapter, cmd in plan["commands"].items():
        completed = subprocess.run(cmd, cwd=REPO_ROOT, env=env, check=False)
        results[adapter] = completed.returncode
        if completed.returncode != 0:
            report["execution_results"] = results
            _emit_report(report, json_output=args.json)
            return completed.returncode

    report["execution_results"] = results
    _emit_report(report, json_output=args.json)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan or execute the operator-gated LoCoMo rung-C SEAM-vs-mem0 run."
    )
    parser.add_argument("--dataset-path", default=str(DEFAULT_DATASET), help="LoCoMo JSON dataset path")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR), help="Directory for rung-C reports")
    parser.add_argument("--slice-path", default=None, help="Optional path for the generated first-N-scope slice")
    parser.add_argument("--scopes", type=int, default=5, help="Number of leading LoCoMo conversation scopes")
    parser.add_argument("--adapter", choices=["both", "seam", "mem0"], default="both")
    parser.add_argument("--answerer-model", default="gpt-4o-mini")
    parser.add_argument("--judge-model", default="gpt-4o-mini")
    parser.add_argument("--mem0-search-limit", type=int, default=None)
    parser.add_argument(
        "--benchmark-dry-run",
        action="store_true",
        help="Execute benchmark runner dry-runs only; this does not construct paid providers.",
    )
    parser.add_argument("--execute", action="store_true", help="Run the generated command(s)")
    parser.add_argument("--confirm-paid", action="store_true", help="Required for paid provider execution")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return parser


def _emit_report(report: dict, *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(report, indent=2))
        return

    print(f"Rung C plan: {report['slice']['scope_count']} scopes / {report['slice']['case_count']} cases")
    print(f"Slice: {report['slice_path']}")
    print(f"Output dir: {report['output_dir']}")
    for adapter, cmd in report["commands"].items():
        print(f"\n[{adapter}]")
        print(" ".join(cmd))
    if not report["execute"]:
        print("\nPlan only. Add --execute --confirm-paid to run paid provider calls.")


if __name__ == "__main__":
    raise SystemExit(main())
