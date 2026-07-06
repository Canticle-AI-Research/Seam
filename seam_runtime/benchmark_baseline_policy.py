"""CI baseline-source policy for ``seam bench gate``.

Picks the most recent benchmark run reachable from the merge-base of HEAD
and origin/main, excluding any path under ``benchmarks/runs/holdout/``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

BENCHMARK_RUNS_DIR = Path("benchmarks") / "runs"
HOLDOUT_PREFIX = str(BENCHMARK_RUNS_DIR / "holdout")


def resolve_baseline(
    repo_root: Path | None = None,
    current_run: Path | None = None,
) -> Path | None:
    """Return the best baseline bundle path, or None for a first-run.

    Policy:
    1. Find the merge-base of HEAD and origin/main.
    2. List all JSON files under ``benchmarks/runs/``, newest first.
    3. Exclude any path under ``benchmarks/runs/holdout/``.
    4. Exclude *current_run* itself when provided.
    5. Return the first run whose git SHA is reachable from the merge-base.

    Returns None when no baseline exists — the caller treats this as
    "first run" (no regression check, exit 0 with a note).
    """
    root = repo_root or _git_root()
    if root is None:
        return None

    merge_base = _merge_base(root)
    if merge_base is None:
        return None

    runs_dir = root / BENCHMARK_RUNS_DIR
    if not runs_dir.is_dir():
        return None

    candidates = sorted(
        runs_dir.glob("**/*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    for candidate in candidates:
        if _is_holdout_run(candidate, root):
            continue
        if current_run is not None and candidate.resolve() == current_run.resolve():
            continue
        sha = _bundle_git_sha(candidate)
        if sha is None:
            continue
        if _is_reachable(root, sha, merge_base):
            return candidate

    return None


def _is_holdout_run(path: Path, repo_root: Path) -> bool:
    try:
        relative = path.resolve().relative_to((repo_root / BENCHMARK_RUNS_DIR).resolve())
    except ValueError:
        return False
    return bool(relative.parts) and relative.parts[0] == "holdout"


def _git_root() -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return None
    return Path(result.stdout.strip()) if result.returncode == 0 else None


def _merge_base(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "merge-base", "HEAD", "origin/main"],
            capture_output=True, text=True, timeout=10, cwd=str(repo_root),
        )
    except Exception:
        return None
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else None


def _bundle_git_sha(path: Path) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(payload, dict):
        manifest = payload.get("manifest") or {}
        return manifest.get("git_sha") or None
    return None


def _is_reachable(repo_root: Path, sha: str, merge_base: str) -> bool:
    """True if *sha* is an ancestor of *merge_base* (i.e. reachable from it)."""
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", sha, merge_base],
            capture_output=True, timeout=10, cwd=str(repo_root),
        )
    except Exception:
        return False
    return result.returncode == 0
