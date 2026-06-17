from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

from .installer import default_runtime_db_path
from .lossless import benchmark_text_lossless
from .runtime import SeamRuntime


def check_pgvector(dsn: str | None) -> dict[str, object]:
    if not dsn:
        return {"configured": False}
    try:
        import psycopg
        conn = psycopg.connect(dsn)
        conn.close()
        return {"configured": True, "reachable": True}
    except Exception as exc:
        return {"configured": True, "reachable": False, "error": str(exc)}


def _import_streams_verify_all():
    """Import the repo-local ``tools.streams.verify_streams.verify_all``.

    The ``seam`` console-script entry point does not put the source-checkout
    root on ``sys.path``, so ``tools/`` (a sibling of the ``seam_runtime/``
    package that is intentionally not shipped in the wheel) is not importable by
    default. When running from an editable/source install, add the repo root to
    ``sys.path`` so ``seam doctor`` can reach streams tooling without the caller
    exporting ``PYTHONPATH``. A genuine wheel install has no sibling ``tools/``,
    so this stays a no-op and the caller reports ``unavailable``.
    """
    try:
        from tools.streams.verify_streams import verify_all
        return verify_all
    except ModuleNotFoundError:
        repo_root = Path(__file__).resolve().parent.parent
        if (repo_root / "tools" / "streams" / "verify_streams.py").is_file():
            if str(repo_root) not in sys.path:
                sys.path.insert(0, str(repo_root))
            from tools.streams.verify_streams import verify_all
            return verify_all
        raise


def check_streams() -> dict[str, object]:
    try:
        verify_all = _import_streams_verify_all()
    except Exception as exc:
        return {"status": "unavailable", "error": str(exc)}
    try:
        errors = verify_all()
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
    if errors:
        return {"status": "FAIL", "errors": errors}
    return {"status": "PASS"}


def check_commit_gate() -> dict[str, object]:
    try:
        repo_root = Path(subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], stderr=subprocess.DEVNULL
        ).decode().strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {"status": "not-a-git-repo"}
    source = repo_root / "tools" / "git-hooks" / "pre-commit"
    installed = repo_root / ".git" / "hooks" / "pre-commit"
    if not source.is_file():
        return {"status": "source-missing", "source": str(source)}
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    if not installed.exists():
        return {"status": "not-installed", "install_cmd": "bash tools/git-hooks/install.sh"}
    if installed.is_symlink():
        target = os.readlink(installed)
        if target.endswith("tools/git-hooks/pre-commit"):
            return {"status": "PASS", "mode": "symlink", "source_sha": source_sha}
        return {"status": "drift", "mode": "symlink", "target": target,
                "install_cmd": "bash tools/git-hooks/install.sh --force"}
    try:
        body = installed.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"status": "unreadable", "path": str(installed)}
    marker = f"# CANONICAL_SHA: {source_sha}"
    if marker in body:
        return {"status": "PASS", "mode": "copy", "source_sha": source_sha}
    return {"status": "drift", "mode": "copy",
            "install_cmd": "bash tools/git-hooks/install.sh --force",
            "source_sha": source_sha}


def check_stashes() -> dict[str, object]:
    """Advisory: surface git stashes. Stashes are invisible to ``git status``,
    ``git log``, and branch/PR listings, so an abandoned one (e.g. an agent
    stashing to clear a tree mid-context-switch and never restoring it) lingers
    unnoticed - more likely in a multi-agent repo. Never blocks; informational
    so an "is everything clean?" sweep catches orphaned local WIP."""
    try:
        out = subprocess.check_output(
            ["git", "stash", "list", "--format=%ct%x09%gs"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {"status": "not-a-git-repo"}
    if not out:
        return {"status": "clean", "count": 0}
    import time as _time
    now = _time.time()
    stashes: list[dict[str, object]] = []
    for line in out.splitlines():
        ts, _, summary = line.partition("\t")
        try:
            age_days = int((now - float(ts)) // 86400)
        except ValueError:
            age_days = None
        stashes.append({"age_days": age_days, "summary": summary})
    return {"status": "advisory", "count": len(stashes), "stashes": stashes}


def build_doctor_report() -> dict[str, object]:
    runtime = SeamRuntime(":memory:")
    batch = runtime.compile_nl("SEAM doctor smoke test for durable local memory.")
    smoke_ok = bool(batch.records)
    lossless_result = benchmark_text_lossless(
        "\n".join(["SEAM preserves exact context while compressing token usage for lossless recovery."] * 12),
        min_token_savings=0.30,
    )
    pgvector_dsn = os.environ.get("SEAM_PGVECTOR_DSN")
    dependencies = {
        "rich": find_spec("rich") is not None,
        "chromadb": find_spec("chromadb") is not None,
        "tiktoken": find_spec("tiktoken") is not None,
        "psycopg": find_spec("psycopg") is not None,
        "sentence_transformers": find_spec("sentence_transformers") is not None,
    }
    required_dependencies = ["rich", "chromadb", "tiktoken"]
    missing_required = [name for name in required_dependencies if not dependencies.get(name)]
    deps_ok = not missing_required
    status = "PASS" if smoke_ok and lossless_result.roundtrip_match and deps_ok else "FAIL"
    return {
        "status": status,
        "python": sys.version.split()[0],
        "db_mode": "in-memory",
        "default_db_path": default_runtime_db_path(),
        "smoke_compile": {
            "status": "PASS" if smoke_ok else "FAIL",
            "record_count": len(batch.records),
        },
        "lossless": {
            "status": "PASS" if lossless_result.roundtrip_match else "FAIL",
            "token_estimator": lossless_result.artifact.token_estimator,
            "token_savings_ratio": round(lossless_result.artifact.token_savings_ratio, 6),
        },
        "pgvector": check_pgvector(pgvector_dsn),
        "commit_gate": check_commit_gate(),
        "streams": check_streams(),
        "stashes": check_stashes(),
        "dependencies": dependencies,
        "required_dependencies": required_dependencies,
        "missing_required_dependencies": missing_required,
    }
