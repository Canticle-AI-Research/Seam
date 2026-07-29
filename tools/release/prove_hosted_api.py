#!/usr/bin/env python3
"""Prove an installed private SEAM server with the released public client."""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_health(
    process: subprocess.Popen[str],
    base_url: str,
    log_path: Path,
    *,
    timeout: float,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = _log_tail(log_path)
            raise RuntimeError(
                "seam-server exited before becoming ready"
                + (f":\n{output[-2000:]}" if output else "")
            )
        request = urllib.request.Request(f"{base_url}/v1/health", method="HEAD")
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                if response.status == 200 and response.read() == b"":
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.1)
    raise RuntimeError("seam-server did not become ready before the timeout")


def _log_tail(path: Path, max_chars: int = 2_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-max_chars:]
    except OSError:
        return ""


def prove_hosted_api(
    *,
    server_command: str = "seam-server",
    timeout: float = 20.0,
    use_pgvector_env: bool = False,
) -> None:
    executable = shutil.which(server_command)
    if executable is None:
        raise RuntimeError(f"{server_command} is not installed")

    try:
        from seam_client import SeamClient
    except ImportError as exc:
        raise RuntimeError("seam-client is not installed") from exc

    port = _free_loopback_port()
    base_url = f"http://127.0.0.1:{port}"
    token = "hosted-release-proof-token-0000000000"

    with tempfile.TemporaryDirectory(prefix="seam-hosted-api-proof-") as temporary:
        root = Path(temporary)
        database = root / "state" / "seam.db"
        log_path = root / "server.log"
        environment = {
            **os.environ,
            "SEAM_API_TOKEN": token,
            "SEAM_API_RATE_LIMIT": "10000",
            "SEAM_SERVER_DB": str(database),
        }
        if use_pgvector_env:
            if not str(environment.get("SEAM_PGVECTOR_DSN") or "").strip():
                raise RuntimeError(
                    "--use-pgvector-env requires SEAM_PGVECTOR_DSN to be set"
                )
        else:
            environment.pop("SEAM_PGVECTOR_DSN", None)
        environment.pop("SEAM_EMBEDDING_PROVIDER", None)
        with log_path.open("w", encoding="utf-8") as server_log:
            process = subprocess.Popen(
                [
                    executable,
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--db",
                    str(database),
                ],
                cwd=root,
                env=environment,
                stdout=server_log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                _wait_for_health(
                    process,
                    base_url,
                    log_path,
                    timeout=timeout,
                )
                with SeamClient(
                    base_url=base_url,
                    api_key=token,
                    timeout=5,
                ) as client:
                    health = client.health()
                    if health.status != "ok" or health.api_version != "v1":
                        raise RuntimeError(f"unexpected health response: {health!r}")

                    text = "The hosted API release proof remembers cobalt."
                    receipt = client.remember(
                        text,
                        namespace="release-proof",
                        scope="thread",
                        session_id="installed-artifact",
                        agent_id="release-check",
                    )
                    if not receipt.accepted or receipt.memory_count < 1:
                        raise RuntimeError(f"remember failed: {receipt!r}")

                    recall = client.recall(
                        "Which color does the release proof remember?",
                        namespace="release-proof",
                        scope="thread",
                        session_id="installed-artifact",
                        limit=5,
                    )
                    if not recall.memories or text not in {
                        memory.text for memory in recall.memories
                    }:
                        raise RuntimeError(f"recall failed: {recall!r}")

                    context = client.context(
                        "release proof color",
                        namespace="release-proof",
                        scope="thread",
                        session_id="installed-artifact",
                        limit=5,
                        max_chars=1000,
                    )
                    if text not in context.context:
                        raise RuntimeError(f"context failed: {context!r}")
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)

        if not database.is_file():
            raise RuntimeError("hosted API proof did not create its database")
        if os.name != "nt" and stat.S_IMODE(database.stat().st_mode) != 0o600:
            raise RuntimeError("hosted API database permissions are not 0600")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-command", default="seam-server")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument(
        "--use-pgvector-env",
        action="store_true",
        help="Preserve SEAM_PGVECTOR_DSN and prove the configured live service",
    )
    args = parser.parse_args(argv)
    prove_hosted_api(
        server_command=args.server_command,
        timeout=max(1.0, args.timeout),
        use_pgvector_env=args.use_pgvector_env,
    )
    print("hosted API installed-artifact proof: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
