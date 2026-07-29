#!/usr/bin/env python3
"""Build and runtime-prove the compiled seam-self-host cp312 manylinux wheel."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NODE_SRC = REPO / "selfhost_pkg"
DEFAULT_DIST = REPO / "dist"

MANYLINUX_IMAGE = (
    "quay.io/pypa/manylinux_2_28_x86_64@"
    "sha256:fdb9a9c223b215604dc7b6f7e8fff4b39bfea5fbaa7777a2e5544a60dfa437f8"
)
PYTHON_IMAGE = (
    "python:3.12.10-slim-bookworm@"
    "sha256:fd95fa221297a88e1cf49c55ec1828edd7c5a428187e67b5d1805692d11588db"
)
NUITKA_VERSION = "4.1.3"

SELFHOST_FILES = (
    Path("README.md"),
    Path("pyproject.toml"),
)

# Explicit source allow-list. New files are never silently added to the node
# build context; a reviewer must decide whether each belongs in the compiled
# artifact. The Dockerfile's nofollow flags remain the shipping exclusions.
RUNTIME_SOURCE_FILES = (
    Path("seam_runtime/__init__.py"),
    Path("seam_runtime/agent_memory.py"),
    Path("seam_runtime/benchmark_baseline_policy.py"),
    Path("seam_runtime/benchmark_integrity.py"),
    Path("seam_runtime/benchmarks.py"),
    Path("seam_runtime/bm25.py"),
    Path("seam_runtime/cli.py"),
    Path("seam_runtime/context_views.py"),
    Path("seam_runtime/context_assembly.py"),
    Path("seam_runtime/conversation.py"),
    Path("seam_runtime/dashboard.py"),
    Path("seam_runtime/derived_fact_context.py"),
    Path("seam_runtime/doctor.py"),
    Path("seam_runtime/dsl.py"),
    Path("seam_runtime/evals.py"),
    Path("seam_runtime/event_count_context.py"),
    Path("seam_runtime/external_memory_benchmarks.py"),
    Path("seam_runtime/graph_products.py"),
    Path("seam_runtime/graph_source_selector.py"),
    Path("seam_runtime/holographic.py"),
    Path("seam_runtime/identity_resolution.py"),
    Path("seam_runtime/improvement.py"),
    Path("seam_runtime/installer.py"),
    Path("seam_runtime/jspace.py"),
    Path("seam_runtime/knowledge_graph.py"),
    Path("seam_runtime/lifecycle.py"),
    Path("seam_runtime/lossless.py"),
    Path("seam_runtime/lx1.py"),
    Path("seam_runtime/mcp.py"),
    Path("seam_runtime/mcp_protocol.py"),
    Path("seam_runtime/mirl.py"),
    Path("seam_runtime/models.py"),
    Path("seam_runtime/multi_scope_pack.py"),
    Path("seam_runtime/multi_speaker_facts.py"),
    Path("seam_runtime/nl.py"),
    Path("seam_runtime/nl_extract.py"),
    Path("seam_runtime/pack.py"),
    Path("seam_runtime/pgvector_bootstrap.py"),
    Path("seam_runtime/pool.py"),
    Path("seam_runtime/public_api.py"),
    Path("seam_runtime/reasoning_graph.py"),
    Path("seam_runtime/reasoning_patterns.py"),
    Path("seam_runtime/reasoning_promotion.py"),
    Path("seam_runtime/qualification.py"),
    Path("seam_runtime/reconcile.py"),
    Path("seam_runtime/retrieval.py"),
    Path("seam_runtime/retrieval_orchestrator/__init__.py"),
    Path("seam_runtime/retrieval_orchestrator/adapters.py"),
    Path("seam_runtime/retrieval_orchestrator/merger.py"),
    Path("seam_runtime/retrieval_orchestrator/orchestrator.py"),
    Path("seam_runtime/retrieval_orchestrator/planner.py"),
    Path("seam_runtime/retrieval_orchestrator/types.py"),
    Path("seam_runtime/retrieval_policy.py"),
    Path("seam_runtime/retry.py"),
    Path("seam_runtime/runtime.py"),
    Path("seam_runtime/sdk.py"),
    Path("seam_runtime/second_hop_context.py"),
    Path("seam_runtime/self_improve.py"),
    Path("seam_runtime/selfhost.py"),
    Path("seam_runtime/selfhost_mcp.py"),
    Path("seam_runtime/selfhost_entitlement.py"),
    Path("seam_runtime/sentence_grounded_facts.py"),
    Path("seam_runtime/server.py"),
    Path("seam_runtime/skills/__init__.py"),
    Path("seam_runtime/skills/factory.py"),
    Path("seam_runtime/skills/skill_ir.py"),
    Path("seam_runtime/storage.py"),
    Path("seam_runtime/surface_adapters.py"),
    Path("seam_runtime/symbols.py"),
    Path("seam_runtime/temporal.py"),
    Path("seam_runtime/temporal_instance_context.py"),
    Path("seam_runtime/tokenization.py"),
    Path("seam_runtime/transpile.py"),
    Path("seam_runtime/ui/__init__.py"),
    Path("seam_runtime/ui/animations.py"),
    Path("seam_runtime/ui/bars.py"),
    Path("seam_runtime/ui/logo.py"),
    Path("seam_runtime/ui/theme.py"),
    Path("seam_runtime/vector.py"),
    Path("seam_runtime/vector_adapters.py"),
    Path("seam_runtime/verify.py"),
    Path("seam_runtime/workspace.py"),
)

NOFOLLOW_MODULES = (
    "seam_runtime.benchmark_baseline_policy",
    "seam_runtime.benchmark_integrity",
    "seam_runtime.cli",
    "seam_runtime.dashboard",
    "seam_runtime.doctor",
    "seam_runtime.external_memory_benchmarks",
    "seam_runtime.graph_source_selector",
    "seam_runtime.improvement",
    "seam_runtime.lx1",
    "seam_runtime.mcp",
    "seam_runtime.mcp_protocol",
    "seam_runtime.multi_scope_pack",
    "seam_runtime.pgvector_bootstrap",
    "seam_runtime.second_hop_context",
    "seam_runtime.self_improve",
    "seam_runtime.skills",
    "seam_runtime.temporal_instance_context",
    "seam_runtime.ui",
)

ASSEMBLE_WHEEL = r'''
from __future__ import annotations

import email.message
import shutil
import tomllib
from pathlib import Path

project = tomllib.loads(Path("/src/selfhost_pkg/pyproject.toml").read_text(encoding="utf-8"))["project"]
dist_info = Path("/wheel-root") / f"seam_self_host-{project['version']}.dist-info"
dist_info.mkdir(parents=True)
metadata = email.message.Message()
metadata["Metadata-Version"] = "2.4"
metadata["Name"] = project["name"]
metadata["Version"] = project["version"]
metadata["Summary"] = project["description"]
metadata["Requires-Python"] = project["requires-python"]
metadata["License-Expression"] = project["license"]
metadata["Description-Content-Type"] = "text/markdown"
for classifier in project["classifiers"]:
    metadata["Classifier"] = classifier
for dependency in project["dependencies"]:
    metadata["Requires-Dist"] = dependency
for label, url in project["urls"].items():
    metadata["Project-URL"] = f"{label}, {url}"
metadata["License-File"] = "LICENSES/BUSL-1.1.txt"
readme = Path("/src/selfhost_pkg/README.md").read_text(encoding="utf-8")
(dist_info / "METADATA").write_text(metadata.as_string() + "\n" + readme, encoding="utf-8")
(dist_info / "WHEEL").write_text(
    "Wheel-Version: 1.0\n"
    "Generator: seam-self-host-wheel\n"
    "Root-Is-Purelib: false\n"
    "Tag: cp312-cp312-linux_x86_64\n",
    encoding="utf-8",
)
(dist_info / "entry_points.txt").write_text(
    "[console_scripts]\n"
    "seam-self-host = seam_runtime.selfhost:main\n"
    "seam-mcp = seam_runtime.selfhost_mcp:main\n",
    encoding="utf-8",
)
license_path = dist_info / "licenses" / "LICENSES" / "BUSL-1.1.txt"
license_path.parent.mkdir(parents=True)
shutil.copy2("/src/selfhost_pkg/LICENSES/BUSL-1.1.txt", license_path)

extensions = list(Path("/compiled").glob("seam_runtime*.so"))
if len(extensions) != 1:
    raise SystemExit(f"expected one compiled seam_runtime extension, found {extensions}")
shutil.copy2(extensions[0], Path("/wheel-root") / extensions[0].name)
'''

RUNTIME_PROOF = r'''
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

TOKEN = "selfhost-wheel-proof-token-000000000000"

def request(method, path, payload=None, authenticated=True):
    body = None if payload is None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if authenticated:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = urllib.request.Request(
        f"http://127.0.0.1:8765{path}",
        data=body,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        content = response.read()
        return response.status, (json.loads(content) if content else None)

def expected_error(method, path, payload, status, authenticated=True):
    try:
        request(method, path, payload, authenticated=authenticated)
    except urllib.error.HTTPError as error:
        content = error.read()
        parsed = json.loads(content) if content else None
        if error.code != status:
            raise AssertionError(
                f"{method} {path} returned {error.code}, expected {status}: {parsed}"
            )
        return error.code, parsed, error.headers
    raise AssertionError(f"{method} {path} unexpectedly succeeded")

with tempfile.TemporaryDirectory(prefix="seam-self-host-proof-") as temporary:
    root = Path(temporary)
    database = root / "state" / "seam.db"
    env = {
        **os.environ,
        "SEAM_API_TOKEN": TOKEN,
        "SEAM_SELFHOST_RATE_LIMIT_PER_MINUTE": "1000",
    }
    for name in (
        "SEAM_SERVER_DB",
        "SEAM_DB_PATH",
        "SEAM_SELFHOST_HOST",
        "SEAM_SELFHOST_PORT",
        "SEAM_PGVECTOR_DSN",
    ):
        env.pop(name, None)
    env.pop("SEAM_SELFHOST_ENTITLEMENT_PATH", None)
    env.pop("SEAM_SELFHOST_PUBLIC_KEY_PATH", None)
    executable = shutil.which("seam-self-host")
    if executable is None:
        raise SystemExit("seam-self-host console entry point was not installed")
    mcp_executable = shutil.which("seam-mcp")
    if mcp_executable is None:
        raise SystemExit("seam-mcp console entry point was not installed")
    server = subprocess.Popen(
        [
            executable,
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
            "--db",
            str(database),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 20
        while True:
            if server.poll() is not None:
                raise RuntimeError("seam-self-host exited before becoming healthy")
            try:
                health = request("GET", "/v1/health")
                break
            except (OSError, urllib.error.URLError):
                if time.monotonic() >= deadline:
                    raise RuntimeError("seam-self-host did not become healthy")
                time.sleep(0.2)

        health_head = request("HEAD", "/v1/health")
        if health_head != (200, None):
            raise AssertionError(f"HEAD health failed: {health_head}")

        unauthorized, _, _ = expected_error(
            "POST",
            "/v1/memories",
            {"text": "unauthorized"},
            401,
            authenticated=False,
        )
        invalid_text = expected_error(
            "POST",
            "/v1/memories",
            {"text": {"not": "a string"}},
            400,
        )
        invalid_query = expected_error(
            "POST",
            "/v1/memories/recall",
            {"query": ["not", "a", "string"]},
            400,
        )
        invalid_session = expected_error(
            "POST",
            "/v1/context",
            {"query": "anything", "session_id": 42},
            400,
        )
        if invalid_text[1] != {"detail": "text must be a string"}:
            raise AssertionError(f"unexpected text validation: {invalid_text}")
        if invalid_query[1] != {"detail": "query must be a string"}:
            raise AssertionError(f"unexpected query validation: {invalid_query}")
        if invalid_session[1] != {"detail": "session_id must be a string"}:
            raise AssertionError(f"unexpected session validation: {invalid_session}")

        remembered = request(
            "POST",
            "/v1/memories",
            {
                "text": "The launch preference is cobalt.",
                "namespace": "node.proof",
                "scope": "thread",
                "session_id": "proof-session",
            },
        )
        recalled = request(
            "POST",
            "/v1/memories/recall",
            {
                "query": "launch preference",
                "namespace": "node.proof",
                "scope": "thread",
                "session_id": "proof-session",
                "limit": 5,
            },
        )
        context = request(
            "POST",
            "/v1/context",
            {
                "query": "launch preference",
                "namespace": "node.proof",
                "scope": "thread",
                "session_id": "proof-session",
                "limit": 5,
                "max_chars": 200,
            },
        )
        responses = [health, remembered, recalled, context]
        serialized = json.dumps(responses, sort_keys=True).lower()
        for marker in ("raw:", "clm:", "mirl"):
            if marker in serialized:
                raise AssertionError(f"private response marker leaked: {marker}")
        if recalled[0] != 200 or not recalled[1]["memories"]:
            raise AssertionError(f"recall did not return the remembered item: {recalled}")
        if context[0] != 200 or not context[1]["context"]:
            raise AssertionError(f"context did not return prompt-ready text: {context}")
        print("SELF-HOST WHEEL RUNTIME PROOF")
        print(f"GET /v1/health -> {health[0]} {json.dumps(health[1], sort_keys=True)}")
        print(f"HEAD /v1/health -> {health_head[0]} empty-body=yes")
        print(f"POST /v1/memories unauthenticated -> {unauthorized}")
        print("non-string text/query/session_id -> 400")
        print(f"POST /v1/memories -> {remembered[0]} accepted={remembered[1]['accepted']}")
        print(f"POST /v1/memories/recall -> {recalled[0]} memories={len(recalled[1]['memories'])}")
        print(f"POST /v1/context -> {context[0]} chars={len(context[1]['context'])}")
        print("response marker scan -> raw:=0 clm:=0 mirl=0")

        mcp_requests = (
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18"},
            },
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
        )
        mcp = subprocess.run(
            [mcp_executable],
            input="\n".join(json.dumps(item) for item in mcp_requests) + "\n",
            env={**env, "SEAM_DB_PATH": str(root / "mcp.db")},
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if mcp.returncode != 0:
            raise AssertionError(
                f"seam-mcp failed with exit {mcp.returncode}:\n{mcp.stderr}"
            )
        if "ModuleNotFoundError" in mcp.stderr:
            raise AssertionError(
                f"seam-mcp log contains ModuleNotFoundError:\n{mcp.stderr}"
            )
        mcp_responses = {
            response["id"]: response
            for response in (
                json.loads(line) for line in mcp.stdout.splitlines() if line.strip()
            )
        }
        initialized = mcp_responses[1]["result"]
        tools = mcp_responses[2]["result"]["tools"]
        tool_names = {tool["name"] for tool in tools}
        required_tools = {
            "seam_remember",
            "seam_recall",
            "seam_context",
        }
        if tool_names != required_tools:
            raise AssertionError(
                f"MCP tools/list is not the opaque surface: {tool_names}"
            )
        listing = json.dumps(tools)
        leaked = [
            marker
            for marker in (
                "MIRL",
                "IRBatch",
                "TraceGraph",
                "compile_nl",
                "holographic",
                "surface_adapter",
                "HS/1",
                "SEAM-RC",
                "SEAM-LX",
                "knowledge_graph",
                "reasoning_graph",
            )
            if marker in listing
        ]
        if leaked:
            raise AssertionError(f"MCP tools/list disclosed reserved identifiers: {leaked}")
        print(
            "MCP initialize -> "
            f"protocol={initialized['protocolVersion']} "
            f"server={initialized['serverInfo']['name']}"
        )
        print(
            "MCP tools/list -> "
            f"tools={len(tools)} opaque=yes reserved-identifier-scan=0"
        )
        print("MCP log ModuleNotFoundError scan -> 0")
    finally:
        server.terminate()
        try:
            output, _ = server.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            output, _ = server.communicate()
        if "ModuleNotFoundError" in output:
            raise AssertionError(f"server log contains ModuleNotFoundError:\n{output}")
        entitlement_line = (
            "no entitlement mounted; running unentitled under BUSL-1.1"
        )
        if entitlement_line not in output:
            raise AssertionError(
                f"server log omitted unentitled identification line:\n{output}"
            )
        print(f"server entitlement log -> {entitlement_line}")
        print("server log ModuleNotFoundError scan -> 0")
        if not database.is_file():
            raise AssertionError("CLI --db did not create the requested database")
        if os.name != "nt":
            if stat.S_IMODE(database.stat().st_mode) != 0o600:
                raise AssertionError("database mode is not 0600")
            if stat.S_IMODE(database.parent.stat().st_mode) != 0o700:
                raise AssertionError("database parent mode is not 0700")
        print("CLI --host/--port/--db -> applied")
        print("database permissions -> 0600 file / 0700 parent")
'''


def _dockerfile() -> str:
    exclusions = " \\\n".join(
        f"      --nofollow-import-to={module}" for module in NOFOLLOW_MODULES
    )
    return f"""# syntax=docker/dockerfile:1.7
ARG BUILD_IMAGE={MANYLINUX_IMAGE}
ARG PROOF_IMAGE={PYTHON_IMAGE}

FROM ${{BUILD_IMAGE}} AS build
ENV PATH=/opt/python/cp312-cp312/bin:$PATH \\
    PYTHONDONTWRITEBYTECODE=1 \\
    PYTHONUNBUFFERED=1 \\
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY selfhost_pkg/ ./selfhost_pkg/
COPY seam_runtime/ ./seam_runtime/
COPY assemble_wheel.py /assemble_wheel.py
RUN python -m pip install --no-cache-dir \\
      "rich>=14.2,<16" \\
      "tiktoken>=0.8.0,<1.0" \\
      "fastapi>=0.100,<1.0" \\
      "uvicorn[standard]>=0.23,<1.0" \\
      "python-multipart>=0.0.6,<1.0" \\
      "cryptography>=45,<50" \\
      "Nuitka=={NUITKA_VERSION}" \\
      "ordered-set>=4.1,<5" \\
      "zstandard>=0.23,<1" \\
      "auditwheel==6.7.0" \\
      "wheel==0.47.0" \\
      "twine==6.2.0"
RUN python -m nuitka \\
      --mode=module \\
      --deployment \\
      --assume-yes-for-downloads \\
      --python-flag=no_docstrings \\
      --include-package=seam_runtime \\
      --include-module=seam_runtime.public_api \\
{exclusions} \\
      --output-dir=/compiled \\
      seam_runtime
RUN mkdir -p /wheel-root /prewheel /out \\
    && python /assemble_wheel.py \\
    && ! find /wheel-root -type f \\( -name '*.py' -o -name '*.pyc' -o -name '*.pyo' \\) -print -quit | grep -q . \\
    && python -m wheel pack --dest-dir /prewheel /wheel-root \\
    && python -m auditwheel show /prewheel/*.whl \\
    && python -m auditwheel repair --only-plat --plat manylinux_2_28_x86_64 --wheel-dir /out /prewheel/*.whl \\
    && test "$(find /out -maxdepth 1 -name '*.whl' | wc -l)" -eq 1 \\
    && python -m twine check /out/*.whl

FROM ${{PROOF_IMAGE}} AS proof
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY --from=build /out/*.whl /wheel/
COPY runtime_proof.py /runtime_proof.py
RUN python -m pip install --no-cache-dir /wheel/*.whl \\
    && cd /tmp \\
    && python /runtime_proof.py \\
    && touch /proof-passed

FROM scratch AS export
COPY --from=build /out/ /
COPY --from=proof /proof-passed /proof/proof-passed
"""


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _run(command: list[str], *, cwd: Path) -> None:
    completed = subprocess.run(command, cwd=cwd, check=False)
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command)}"
        )


def build_selfhost_wheel(outdir: Path) -> tuple[Path, ...]:
    """Build one verified cp312 manylinux wheel into an initially empty directory."""
    outdir = outdir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    if any(outdir.iterdir()):
        raise ValueError(f"output directory must be empty: {outdir}")

    with tempfile.TemporaryDirectory(prefix="seam-self-host-build-") as temporary:
        root = Path(temporary)
        context = root / "context"
        result = root / "result"
        context.mkdir()
        result.mkdir()

        for relative in SELFHOST_FILES:
            _copy_file(NODE_SRC / relative, context / "selfhost_pkg" / relative)
        _copy_file(
            REPO / "LICENSES" / "BUSL-1.1.txt",
            context / "selfhost_pkg" / "LICENSES" / "BUSL-1.1.txt",
        )
        for relative in RUNTIME_SOURCE_FILES:
            _copy_file(REPO / relative, context / relative)
        (context / "assemble_wheel.py").write_text(
            ASSEMBLE_WHEEL, encoding="utf-8"
        )
        (context / "runtime_proof.py").write_text(
            RUNTIME_PROOF, encoding="utf-8"
        )
        (context / "Dockerfile").write_text(_dockerfile(), encoding="utf-8")

        print("[selfhost-wheel] building locally; no upload or registry push is performed")
        _run(
            [
                "docker",
                "buildx",
                "build",
                "--platform",
                "linux/amd64",
                "--progress",
                "plain",
                "--target",
                "export",
                "--output",
                f"type=local,dest={result}",
                "--file",
                str(context / "Dockerfile"),
                str(context),
            ],
            cwd=REPO,
        )
        built = tuple(result.glob("*.whl"))
        if len(built) != 1:
            raise RuntimeError(f"expected one wheel, found: {built}")
        wheel = built[0]
        if not wheel.name.endswith("cp312-cp312-manylinux_2_28_x86_64.whl"):
            raise RuntimeError(f"unexpected wheel tag: {wheel.name}")
        if not (result / "proof" / "proof-passed").is_file():
            raise RuntimeError("clean-container runtime proof did not complete")
        _run(
            [
                sys.executable,
                "-m",
                "tools.release.verify_selfhost_wheel",
                str(wheel),
            ],
            cwd=REPO,
        )
        destination = outdir / wheel.name
        shutil.copy2(wheel, destination)
        return (destination,)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_DIST)
    args = parser.parse_args(argv)
    try:
        artifacts = build_selfhost_wheel(args.outdir)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"node wheel build failed: {exc}", file=sys.stderr)
        return 1
    for artifact in artifacts:
        print(f"  -> {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
