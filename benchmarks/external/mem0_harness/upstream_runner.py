"""Run SEAM through the pinned upstream ``mem0ai/memory-benchmarks`` contract.

LongMemEval and BEAM have benchmark-specific ingestion, prompts, and scoring.
SEAM's in-repo parsers are structural validators; competitive execution must
use the audited upstream harness against :mod:`seam_mem0_server` so we do not
silently substitute LoCoMo's generic scorer for either benchmark's contract.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

PINNED_HARNESS_REVISION = "4b61c5d31b9c668a12b4f5e78064248a02c82d2b"
_MODULES = {
    "longmemeval": "benchmarks.longmemeval.run",
    "beam": "benchmarks.beam.run",
}


@dataclass(frozen=True)
class UpstreamHarnessPlan:
    benchmark: str
    harness_root: str
    harness_revision: str
    python: str
    command: tuple[str, ...]
    ready: bool
    issues: tuple[str, ...]
    paid: bool
    requires_download: bool = False

    def to_dict(self) -> dict:
        return {
            "benchmark": self.benchmark,
            "harness_root": self.harness_root,
            "harness_revision": self.harness_revision,
            "expected_revision": PINNED_HARNESS_REVISION,
            "python": self.python,
            "command": list(self.command),
            "ready": self.ready,
            "issues": list(self.issues),
            "paid": self.paid,
            "requires_download": self.requires_download,
            "runnable_without_download": self.ready and not self.requires_download,
        }


def _git_revision(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"harness root is not a readable git checkout: {root}") from exc


def _git_is_clean(root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0 and not result.stdout.strip()


def _harness_python(root: Path) -> Path:
    candidate = root / ".venv" / "bin" / "python"
    if not candidate.is_file():
        raise ValueError(
            f"pinned harness environment is missing: {candidate}; "
            "create an isolated venv in the harness checkout"
        )
    return candidate


def _is_loopback_url(value: str) -> bool:
    parsed = urlparse(value)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        and parsed.port is not None
    )


def _module_path(root: Path, benchmark: str) -> Path:
    module = _MODULES[benchmark]
    return root.joinpath(*module.split(".")).with_suffix(".py")


def _python_can_import(python: Path, module: str, *, cwd: Path) -> bool:
    result = subprocess.run(
        [str(python), "-c", f"import {module}"],
        cwd=cwd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def build_upstream_command(
    *,
    benchmark: str,
    python: str,
    project_name: str,
    mem0_host: str,
    predict_only: bool,
    top_k: int,
    top_k_cutoffs: str,
    workers: int,
    output_dir: str,
    answerer_model: str,
    judge_model: str,
    provider: str,
    judge_provider: str | None = None,
    dataset_path: str | None = None,
    dataset_cache_dir: str | None = None,
    per_type: int | None = None,
    chat_size: str | None = None,
    conversations: str | None = None,
) -> tuple[str, ...]:
    """Build an argv-only command; no shell interpolation or credentials."""

    if benchmark not in _MODULES:
        raise ValueError(f"unsupported upstream benchmark: {benchmark!r}")
    if not project_name.strip():
        raise ValueError("project_name must not be empty")
    if not _is_loopback_url(mem0_host):
        raise ValueError("mem0_host must be an explicit loopback URL with a port")
    if top_k <= 0 or workers <= 0:
        raise ValueError("top_k and workers must be positive")
    try:
        cutoffs = tuple(int(value.strip()) for value in top_k_cutoffs.split(","))
    except ValueError as exc:
        raise ValueError("top_k_cutoffs must be comma-separated integers") from exc
    if not cutoffs or any(value <= 0 or value > top_k for value in cutoffs):
        raise ValueError("top_k_cutoffs must be positive and no greater than top_k")
    if not output_dir.strip():
        raise ValueError("output_dir must not be empty")
    if not answerer_model.strip() or not judge_model.strip():
        raise ValueError("answerer_model and judge_model must not be empty")
    if provider not in {"openai", "anthropic", "azure"}:
        raise ValueError(f"unsupported provider: {provider!r}")
    if judge_provider not in {None, "openai", "anthropic", "azure"}:
        raise ValueError(f"unsupported judge_provider: {judge_provider!r}")

    command = [
        python,
        "-m",
        _MODULES[benchmark],
        "--project-name",
        project_name,
        "--backend",
        "oss",
        "--mem0-host",
        mem0_host,
        "--top-k",
        str(top_k),
        "--top-k-cutoffs",
        top_k_cutoffs,
        "--max-workers",
        str(workers),
        "--output-dir",
        output_dir,
        "--answerer-model",
        answerer_model,
        "--judge-model",
        judge_model,
        "--provider",
        provider,
    ]
    if judge_provider:
        command.extend(["--judge-provider", judge_provider])
    if predict_only:
        command.append("--predict-only")

    if benchmark == "longmemeval":
        if not dataset_path:
            raise ValueError("LongMemEval upstream execution requires dataset_path")
        command.extend(["--dataset-path", dataset_path])
        if per_type is None:
            command.append("--all-questions")
        else:
            if per_type <= 0:
                raise ValueError("per_type must be positive")
            command.extend(["--per-type", str(per_type)])
    else:
        normalized_size = (chat_size or "1M").upper()
        if normalized_size not in {"100K", "500K", "1M", "10M"}:
            raise ValueError(f"unsupported BEAM chat size: {chat_size!r}")
        command.extend(["--chat-sizes", normalized_size])
        if conversations:
            command.extend(["--conversations", conversations])
        if dataset_cache_dir:
            command.extend(["--dataset-cache-dir", dataset_cache_dir])

    return tuple(command)


def plan_upstream_run(
    *,
    benchmark: str,
    harness_root: str,
    project_name: str,
    mem0_host: str,
    predict_only: bool,
    top_k: int,
    top_k_cutoffs: str,
    workers: int,
    output_dir: str,
    answerer_model: str,
    judge_model: str,
    provider: str,
    judge_provider: str | None = None,
    dataset_path: str | None = None,
    dataset_cache_dir: str | None = None,
    per_type: int | None = None,
    chat_size: str | None = None,
    conversations: str | None = None,
) -> UpstreamHarnessPlan:
    root = Path(harness_root).resolve()
    revision = _git_revision(root)
    python = _harness_python(root)
    issues: list[str] = []
    if revision != PINNED_HARNESS_REVISION:
        issues.append(
            f"harness revision mismatch: expected {PINNED_HARNESS_REVISION}, got {revision}"
        )
    if not _git_is_clean(root):
        issues.append("upstream harness checkout has tracked or untracked changes")
    if not _module_path(root, benchmark).is_file():
        issues.append(f"upstream module missing for {benchmark}")
    if benchmark == "beam" and not _python_can_import(python, "datasets", cwd=root):
        issues.append(
            "BEAM harness dependency missing in its isolated venv: datasets"
        )
    if benchmark == "longmemeval":
        path = Path(dataset_path or "")
        if not dataset_path or not path.is_file():
            issues.append("LongMemEval dataset_path is missing or is not a file")

    requires_download = False
    if benchmark == "beam":
        normalized_size = (chat_size or "1M").upper()
        cache_path = Path(dataset_cache_dir or "") / f"beam_{normalized_size}.json"
        requires_download = not cache_path.is_file()

    command = build_upstream_command(
        benchmark=benchmark,
        python=str(python),
        project_name=project_name,
        mem0_host=mem0_host,
        predict_only=predict_only,
        top_k=top_k,
        top_k_cutoffs=top_k_cutoffs,
        workers=workers,
        output_dir=output_dir,
        answerer_model=answerer_model,
        judge_model=judge_model,
        provider=provider,
        judge_provider=judge_provider,
        dataset_path=dataset_path,
        dataset_cache_dir=dataset_cache_dir,
        per_type=per_type,
        chat_size=chat_size,
        conversations=conversations,
    )
    return UpstreamHarnessPlan(
        benchmark=benchmark,
        harness_root=str(root),
        harness_revision=revision,
        python=str(python),
        command=command,
        ready=not issues,
        issues=tuple(issues),
        paid=not predict_only,
        requires_download=requires_download,
    )


def execute_upstream_plan(
    plan: UpstreamHarnessPlan,
    *,
    allow_paid: bool,
    allow_beam_10m: bool = False,
    allow_download: bool = False,
) -> int:
    if not plan.ready:
        raise RuntimeError("upstream harness is not ready: " + "; ".join(plan.issues))
    if plan.paid and not allow_paid:
        raise RuntimeError(
            "answerer/judge execution is provider-paid; rerun with --allow-paid "
            "only after explicit operator approval"
        )
    if plan.requires_download and not allow_download:
        raise RuntimeError(
            "BEAM cache is missing and upstream execution would download a large "
            "dataset; rerun with --allow-download only after explicit operator approval"
        )
    if (
        plan.benchmark == "beam"
        and "--chat-sizes" in plan.command
        and plan.command[plan.command.index("--chat-sizes") + 1] == "10M"
        and not allow_beam_10m
    ):
        raise RuntimeError("BEAM-10M is deferred; explicit --allow-10m is required")
    completed = subprocess.run(
        list(plan.command),
        cwd=plan.harness_root,
        check=False,
    )
    return completed.returncode


def render_plan(plan: UpstreamHarnessPlan) -> str:
    return json.dumps(plan.to_dict(), indent=2, sort_keys=True)
