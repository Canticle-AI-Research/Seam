from __future__ import annotations

import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import TextIO

DEFAULT_PGVECTOR_PORT = "55432"
DEFAULT_CONTAINER_NAME = "seam-pgvector"
DEFAULT_SERVICE_NAME = "pgvector"


class PgVectorBootstrapError(RuntimeError):
    pass


def default_local_env_path() -> Path:
    documents = Path.home() / "Documents"
    onedrive_documents = Path.home() / "OneDrive" / "Documents"
    if onedrive_documents.exists():
        documents = onedrive_documents
    return documents / "SEAM" / "local" / ".env"


def resolve_pgvector_env_path(repo_root: Path, explicit_path: str | None = None) -> Path | None:
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path))
    if os.environ.get("SEAM_LOCAL_ENV"):
        candidates.append(Path(os.environ["SEAM_LOCAL_ENV"]))
    candidates.append(default_local_env_path())
    candidates.append(repo_root / ".env")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def build_pgvector_dsn(values: dict[str, str]) -> str:
    db = values.get("POSTGRES_DB") or "seam"
    user = values.get("POSTGRES_USER") or "seam"
    password = values.get("POSTGRES_PASSWORD")
    port = values.get("SEAM_PGVECTOR_PORT") or DEFAULT_PGVECTOR_PORT
    if not password:
        raise PgVectorBootstrapError(
            "POSTGRES_PASSWORD is required in SEAM_LOCAL_ENV or repo .env before pgvector can be launched."
        )
    parts = {
        "host": "localhost",
        "port": port,
        "dbname": db,
        "user": user,
        "password": password,
    }
    return " ".join(f"{key}={_conninfo_quote(value)}" for key, value in parts.items())


def ensure_pgvector(
    repo_root: Path,
    *,
    env_path: str | None = None,
    timeout_seconds: int = 90,
    stderr: TextIO | None = None,
) -> str:
    """Start the repo pgvector service and return a SEAM_PGVECTOR_DSN.

    All status output goes to stderr so MCP stdout remains valid JSON-RPC.
    """

    log = stderr or sys.stderr
    repo_root = repo_root.resolve()
    resolved_env_path = resolve_pgvector_env_path(repo_root, explicit_path=env_path)
    env_values = dict(os.environ)
    file_values: dict[str, str] = {}
    if resolved_env_path is not None:
        file_values = read_dotenv(resolved_env_path)
        env_values.update(file_values)
    elif not env_values.get("POSTGRES_PASSWORD"):
        raise PgVectorBootstrapError(
            "No pgvector env file found. Set SEAM_LOCAL_ENV or create a local .env with POSTGRES_PASSWORD."
        )

    for key in ("POSTGRES_DB", "POSTGRES_USER", "POSTGRES_PASSWORD", "SEAM_PGVECTOR_PORT"):
        if key in file_values and key not in os.environ:
            os.environ[key] = file_values[key]

    dsn = os.environ.get("SEAM_PGVECTOR_DSN") or build_pgvector_dsn(env_values)
    os.environ["SEAM_PGVECTOR_DSN"] = dsn

    _ensure_docker_ready(timeout_seconds=timeout_seconds, stderr=log)

    compose_cmd = ["docker", "compose"]
    if resolved_env_path is not None:
        compose_cmd.extend(["--env-file", str(resolved_env_path)])
    compose_cmd.extend(["up", "-d", DEFAULT_SERVICE_NAME])
    _log(log, "[seam-mcp] ensuring pgvector docker service is running")
    _run(compose_cmd, cwd=repo_root, env=env_values, stderr=log)

    _wait_for_pgvector(env_values, timeout_seconds=timeout_seconds, stderr=log)
    _ensure_vector_extension(env_values, stderr=log)
    return dsn


def _ensure_docker_ready(*, timeout_seconds: int, stderr: TextIO) -> None:
    deadline = time.monotonic() + timeout_seconds
    if _docker_version_ok():
        return
    _start_docker_desktop(stderr)
    while time.monotonic() < deadline:
        if _docker_version_ok():
            return
        time.sleep(2)
    raise PgVectorBootstrapError("Docker is not ready. Start Docker Desktop, then restart Gemini.")


def _docker_version_ok() -> bool:
    try:
        result = subprocess.run(["docker", "version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result.returncode == 0
    except FileNotFoundError:
        return False


def _start_docker_desktop(stderr: TextIO) -> None:
    if platform.system().lower() != "windows":
        return
    exe = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "Docker Desktop.exe"
    if not exe.exists():
        return
    _log(stderr, "[seam-mcp] Docker is not ready; starting Docker Desktop")
    subprocess.Popen([str(exe)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _wait_for_pgvector(env_values: dict[str, str], *, timeout_seconds: int, stderr: TextIO) -> None:
    deadline = time.monotonic() + timeout_seconds
    user = env_values.get("POSTGRES_USER") or "seam"
    db = env_values.get("POSTGRES_DB") or "seam"
    while time.monotonic() < deadline:
        health = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Health.Status}}", DEFAULT_CONTAINER_NAME],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        if health.returncode == 0 and health.stdout.strip() == "healthy":
            return
        ready = subprocess.run(
            ["docker", "exec", DEFAULT_CONTAINER_NAME, "pg_isready", "-U", user, "-d", db],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if ready.returncode == 0:
            return
        time.sleep(2)
    _log(stderr, "[seam-mcp] pgvector did not become healthy before timeout")
    raise PgVectorBootstrapError("pgvector docker service was not healthy in time.")


def _ensure_vector_extension(env_values: dict[str, str], *, stderr: TextIO) -> None:
    user = env_values.get("POSTGRES_USER") or "seam"
    db = env_values.get("POSTGRES_DB") or "seam"
    command = [
        "docker",
        "exec",
        DEFAULT_CONTAINER_NAME,
        "psql",
        "-U",
        user,
        "-d",
        db,
        "-c",
        "create extension if not exists vector;",
    ]
    _run(command, cwd=None, env=os.environ.copy(), stderr=stderr)


def _run(command: list[str], *, cwd: Path | None, env: dict[str, str], stderr: TextIO) -> None:
    result = subprocess.run(command, cwd=str(cwd) if cwd else None, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        if result.stderr:
            _log(stderr, result.stderr.strip())
        raise PgVectorBootstrapError(f"Command failed: {_redacted_command(command)}")


def _conninfo_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


def _redacted_command(command: list[str]) -> str:
    redacted: list[str] = []
    skip_next = False
    for part in command:
        if skip_next:
            redacted.append("<redacted>")
            skip_next = False
            continue
        if part == "-e":
            redacted.append(part)
            skip_next = True
            continue
        if part.startswith("PGPASSWORD="):
            redacted.append("PGPASSWORD=<redacted>")
            continue
        redacted.append(part)
    return " ".join(redacted)


def _log(stderr: TextIO, message: str) -> None:
    print(message, file=stderr, flush=True)
