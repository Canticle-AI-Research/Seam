"""Own an ephemeral pgvector CI database through the approved local daemon."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

IMAGE = "pgvector/pgvector:0.8.7-pg18-trixie"
ENDPOINT = "unix:///var/run/docker.sock"
LABEL = "io.canticle.seam.pgvector-fixture"
OWNER_LABEL = "io.canticle.seam.pgvector-owner"
PREFIX = "seam-ci-pgvector-"
SCHEMA = "seam-pgvector-ci-fixture/1"
PARENT = "/var/lib/postgresql"
SELECTORS = ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH")
CONTAINER_FORMAT = (
    '{"id":{{json .Id}},"name":{{json .Name}},"labels":{{json .Config.Labels}},'
    '"image_id":{{json .Image}},"mounts":{{json .Mounts}},"ports":{{json .NetworkSettings.Ports}},'
    '"status":{{json .State.Status}},"health":{{if .State.Health}}{{json .State.Health.Status}}{{else}}null{{end}}}'
)
IMAGE_FORMAT = (
    '{"id":{{json .Id}},"digests":{{json .RepoDigests}},'
    '"volumes":{{json .Config.Volumes}},"env":{{json .Config.Env}}}'
)


class FixtureError(RuntimeError):
    """Content-free diagnostic; never includes credentials or raw Docker output."""


def docker_environment(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    for key in SELECTORS:
        env.pop(key, None)
    if extra:
        env.update(extra)
    return env


def docker(*args: str, timeout: float = 30, missing_ok: bool = False,
           extra: dict[str, str] | None = None) -> str | None:
    try:
        result = subprocess.run(
            ["docker", "--host=" + ENDPOINT, *args], env=docker_environment(extra),
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise FixtureError(f"Docker {args[0]} unavailable or timed out") from None
    if result.returncode:
        if missing_ok and any(s in result.stderr.casefold() for s in ("no such object", "no such container")):
            return None
        raise FixtureError(f"Docker {args[0]} failed (exit {result.returncode})")
    if len(result.stdout) > 65536:
        raise FixtureError("Docker metadata exceeds the bounded response size")
    return result.stdout.strip()


def probe() -> str:
    try:
        version = docker("version", "--format", "{{.Server.APIVersion}}", timeout=15)
        if not version or not re.fullmatch(r"\d+\.\d+", version):
            raise FixtureError("invalid daemon version response")
    except FixtureError:
        raise FixtureError("approved local Docker daemon unavailable; no service or tests started") from None
    return version


def _private_directory(path: Path) -> None:
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise FixtureError("fixture state must not use symlink paths")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise FixtureError("fixture state directory must be owned and private (0700)")


def _atomic_state(path: Path, data: dict) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".pgvector-state-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _lock_path(path: Path) -> Path:
    return path.with_name(path.name + ".lock")


def _reserve(path: Path) -> None:
    _private_directory(path.parent)
    if path.exists() or path.is_symlink():
        raise FixtureError("fixture state already exists; refusing overwrite")
    try:
        descriptor = os.open(_lock_path(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
    except FileExistsError:
        raise FixtureError("fixture state is already reserved") from None


def _read_state(path: Path) -> dict | None:
    if path.is_symlink():
        raise FixtureError("fixture state must not be a symlink")
    if not path.exists():
        return None
    _private_directory(path.parent)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
        raise FixtureError("fixture state must be an owned private regular file (0600)")
    if info.st_size > 16384:
        raise FixtureError("fixture state exceeds the bounded size")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise FixtureError("invalid fixture state schema")
    owner = data.get("owner")
    if not isinstance(owner, str) or not re.fullmatch(r"[0-9a-f]{32}", owner):
        raise FixtureError("invalid fixture ownership state")
    if data.get("name") != PREFIX + owner[:16] or data.get("image") != IMAGE:
        raise FixtureError("invalid fixture name/image identity")
    if not isinstance(data.get("password"), str) or not re.fullmatch(r"[0-9a-f]{48}", data["password"]):
        raise FixtureError("invalid private fixture credential state")
    identifier = data.get("id")
    if identifier is not None and (not isinstance(identifier, str) or not re.fullmatch(r"[0-9a-f]{64}", identifier)):
        raise FixtureError("invalid fixture container identity")
    return data


def _inspect(identifier: str, timeout: float = 30) -> dict | None:
    response = docker("inspect", "--format", CONTAINER_FORMAT, identifier, missing_ok=True, timeout=timeout)
    return json.loads(response) if response is not None else None


def _ownership(data: dict, actual: dict) -> None:
    if (
        actual.get("name") != "/" + data["name"]
        or actual.get("labels", {}).get(LABEL) != "true"
        or actual.get("labels", {}).get(OWNER_LABEL) != data["owner"]
        or (data.get("id") is not None and actual.get("id") != data["id"])
        or actual.get("image_id") != data.get("image_id")
    ):
        raise FixtureError("fixture ownership/identity mismatch; no container removed or reused")


def _mounts_and_port(actual: dict) -> int:
    mounts = actual.get("mounts", [])
    if any(m.get("Type") == "volume" for m in mounts) or not any(
        m.get("Type") == "tmpfs" and m.get("Destination") == PARENT for m in mounts
    ):
        raise FixtureError("unexpected fixture mount; declared PG18 parent must be tmpfs without volumes")
    bindings = actual.get("ports", {}).get("5432/tcp")
    if not isinstance(bindings, list) or len(bindings) != 1 or bindings[0].get("HostIp") != "127.0.0.1":
        raise FixtureError("fixture database must have exactly one loopback port binding")
    port = int(bindings[0]["HostPort"])
    if not 1 <= port <= 65535:
        raise FixtureError("invalid fixture port")
    return port


def _release(path: Path) -> None:
    path.unlink(missing_ok=True)
    _lock_path(path).unlink(missing_ok=True)
    try:
        path.parent.rmdir()
    except OSError:
        pass


def stop(path: Path) -> None:
    data = _read_state(path)
    if data is None:
        print("Owned pgvector fixture never started; cleanup unnecessary.")
        return
    probe()
    actual = _inspect(data.get("id") or data["name"])
    if actual is not None:
        _ownership(data, actual)
        # -v can remove only this newly created owned container's anonymous
        # volumes, including a partial start. No host-wide volume prune.
        docker("rm", "--force", "--volumes", actual["id"])
        if _inspect(actual["id"]) is not None:
            raise FixtureError("owned fixture removal could not be verified")
    remaining = docker("ps", "--all", "--quiet", "--filter", "label=" + OWNER_LABEL + "=" + data["owner"])
    if remaining:
        raise FixtureError("unexpected remaining owned fixture; private state retained")
    _release(path)
    print("Owned pgvector fixture removed; private state removed; no operator resources touched.")


def public_metadata(data: dict, actual: dict) -> dict:
    return {
        "container_id": data["id"], "container_name": data["name"], "server_api": data["server_api"],
        "image": IMAGE, "image_id": data["image_id"], "image_digest": data["image_digest"],
        "extension_version": data["extension_version"], "postgres_version": data["postgres_version"],
        "port": data["port"], "mounts": [{"type": m.get("Type"), "destination": m.get("Destination")}
                                        for m in actual["mounts"]],
    }


def start(path: Path, timeout_seconds: float = 90) -> None:
    if path.exists() or path.is_symlink() or _lock_path(path).exists():
        raise FixtureError("fixture state already exists; refusing overwrite")
    server_api = probe()
    docker("pull", IMAGE, timeout=180)
    image = json.loads(docker("image", "inspect", "--format", IMAGE_FORMAT, IMAGE))
    if set(image.get("volumes") or {}) != {PARENT}:
        raise FixtureError("unexpected image volume declaration; refusing unbounded volume allocation")
    image_id = image.get("id")
    digests = image.get("digests")
    if not isinstance(image_id, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) or not digests:
        raise FixtureError("image identity/digest unavailable")
    owner = uuid.uuid4().hex
    data = {
        "schema": SCHEMA, "owner": owner, "name": PREFIX + owner[:16], "id": None,
        "password": secrets.token_hex(24), "image": IMAGE, "image_id": image_id,
        "image_digest": digests[0], "server_api": server_api, "phase": "allocated",
    }
    _reserve(path)
    try:
        _atomic_state(path, data)
        identifier = docker(
            "create", "--name", data["name"], "--label", LABEL + "=true", "--label", OWNER_LABEL + "=" + owner,
            "--env", "POSTGRES_DB=seam_ci", "--env", "POSTGRES_USER=seam_ci", "--env", "POSTGRES_PASSWORD",
            "--publish", "127.0.0.1::5432",
            "--mount", "type=tmpfs,destination=/var/lib/postgresql,tmpfs-size=536870912",
            "--health-cmd", "pg_isready -U seam_ci -d seam_ci", "--health-interval", "1s",
            "--health-timeout", "3s", "--health-start-period", "2s", "--health-retries", "30",
            image_id, extra={"POSTGRES_PASSWORD": data["password"]},
        )
        if not identifier or not re.fullmatch(r"[0-9a-f]{64}", identifier):
            raise FixtureError("invalid created fixture identity")
        data["id"] = identifier
        _atomic_state(path, data)
        docker("start", identifier)
        deadline = time.monotonic() + timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FixtureError("PostgreSQL readiness timed out")
            try:
                actual = _inspect(identifier, timeout=min(30, remaining))
            except FixtureError:
                if time.monotonic() >= deadline:
                    raise FixtureError("PostgreSQL readiness timed out") from None
                raise
            if time.monotonic() >= deadline:
                raise FixtureError("PostgreSQL readiness timed out")
            if actual is None:
                raise FixtureError("owned fixture disappeared before readiness")
            _ownership(data, actual)
            if actual.get("status") in {"dead", "exited"}:
                raise FixtureError("owned PostgreSQL fixture stopped before readiness")
            if actual.get("health") == "healthy" and actual.get("status") == "running":
                break
            if time.monotonic() >= deadline:
                raise FixtureError("PostgreSQL readiness timed out")
            time.sleep(min(0.25, max(0, deadline - time.monotonic())))
        data["port"] = _mounts_and_port(actual)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FixtureError("PostgreSQL readiness timed out")
        try:
            response = docker(
                "exec", identifier, "psql", "--username", "seam_ci", "--dbname", "seam_ci", "--tuples-only",
                "--no-align", "--set", "ON_ERROR_STOP=1", "--command",
                "CREATE EXTENSION IF NOT EXISTS vector; SELECT extversion FROM pg_extension WHERE extname='vector'; SHOW server_version;",
                timeout=min(30, remaining),
            )
        except FixtureError:
            if time.monotonic() >= deadline:
                raise FixtureError("PostgreSQL readiness timed out") from None
            raise
        if time.monotonic() >= deadline:
            raise FixtureError("PostgreSQL readiness timed out")
        lines = [line.strip() for line in response.splitlines() if line.strip()]
        if len(lines) < 2 or lines[-2] != "0.8.7" or not lines[-1].startswith("18."):
            raise FixtureError("actual PostgreSQL/pgvector version does not match reviewed image")
        data.update(phase="ready", extension_version=lines[-2], postgres_version=lines[-1])
        _atomic_state(path, data)
        print(json.dumps(public_metadata(data, actual), sort_keys=True))
    except BaseException:
        try:
            stop(path)
        except Exception:
            # Keep private recovery state if identity/daemon failure prevents
            # safe cleanup. Never substitute a broad prune or guessed name.
            print("Owned fixture cleanup incomplete; private recovery state retained.", file=sys.stderr)
        raise


def run(path: Path, command: list[str]) -> int:
    data = _read_state(path)
    if data is None or data.get("phase") != "ready":
        raise FixtureError("owned fixture is not ready; no tests started")
    probe()
    actual = _inspect(data["id"])
    if actual is None:
        raise FixtureError("owned fixture unavailable; no tests started")
    _ownership(data, actual)
    if actual.get("health") != "healthy" or actual.get("status") != "running" or _mounts_and_port(actual) != data["port"]:
        raise FixtureError("owned fixture lost readiness; no tests started")
    if not command:
        raise FixtureError("fixture run requires a test command")
    password = data["password"]
    env = os.environ.copy()
    dsn = f"host=127.0.0.1 port={data['port']} dbname=seam_ci user=seam_ci password={password}"
    env.update(PGVECTOR_TEST_DSN=dsn, SEAM_PGVECTOR_DSN=dsn, PGPASSWORD=password)
    env["SEAM_STRICT_NO_SKIP"] = "1"
    # Parent/runner environment stays untouched and no secret-bearing value is
    # written to GITHUB_ENV. Capture before emission to scrub exception output.
    result = subprocess.run(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    print(result.stdout.decode("utf-8", errors="replace").replace(password, "<redacted>"), end="")
    return result.returncode


def _timeout(value: str) -> float:
    parsed = float(value)
    if not 0 < parsed <= 300:
        raise argparse.ArgumentTypeError("timeout must be positive and at most 300 seconds")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for action in ("start", "run", "stop"):
        sub = subparsers.add_parser(action)
        sub.add_argument("--state", type=Path, required=True)
        if action == "start":
            sub.add_argument("--timeout-seconds", type=_timeout, default=90)
        if action == "run":
            sub.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        if args.action == "start":
            start(args.state, args.timeout_seconds)
        elif args.action == "stop":
            stop(args.state)
        else:
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            return run(args.state, command)
    except (FixtureError, OSError, ValueError, KeyError, TypeError) as exc:
        # Generic parser/I/O errors may include sensitive input. Only our
        # deliberately content-free diagnostics are safe to publish.
        message = str(exc) if isinstance(exc, FixtureError) else "invalid fixture state or operation"
        print(f"pgvector fixture failed: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
