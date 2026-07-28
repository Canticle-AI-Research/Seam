#!/usr/bin/env python3
"""Build and runtime-prove the compiled seam-node cp312 manylinux wheel."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
NODE_SRC = REPO / "node_pkg"
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

NODE_FILES = (
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
    Path("seam_runtime/conversation.py"),
    Path("seam_runtime/dashboard.py"),
    Path("seam_runtime/derived_fact_context.py"),
    Path("seam_runtime/doctor.py"),
    Path("seam_runtime/dsl.py"),
    Path("seam_runtime/evals.py"),
    Path("seam_runtime/event_count_context.py"),
    Path("seam_runtime/external_memory_benchmarks.py"),
    Path("seam_runtime/graph_source_selector.py"),
    Path("seam_runtime/holographic.py"),
    Path("seam_runtime/identity_resolution.py"),
    Path("seam_runtime/improvement.py"),
    Path("seam_runtime/installer.py"),
    Path("seam_runtime/jspace.py"),
    Path("seam_runtime/knowledge_graph.py"),
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
    "seam_runtime.external_memory_benchmarks",
    "seam_runtime.graph_source_selector",
    "seam_runtime.improvement",
    "seam_runtime.lx1",
    "seam_runtime.multi_scope_pack",
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

project = tomllib.loads(Path("/src/node_pkg/pyproject.toml").read_text(encoding="utf-8"))["project"]
dist_info = Path("/wheel-root/seam_node-2.4.0.dist-info")
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
readme = Path("/src/node_pkg/README.md").read_text(encoding="utf-8")
(dist_info / "METADATA").write_text(metadata.as_string() + "\n" + readme, encoding="utf-8")
(dist_info / "WHEEL").write_text(
    "Wheel-Version: 1.0\n"
    "Generator: seam-node-wheel\n"
    "Root-Is-Purelib: false\n"
    "Tag: cp312-cp312-linux_x86_64\n",
    encoding="utf-8",
)
(dist_info / "entry_points.txt").write_text(
    "[console_scripts]\n"
    "seam-node = seam_runtime.selfhost:main\n"
    "seam-mcp = seam_runtime.mcp_protocol:main\n",
    encoding="utf-8",
)
license_path = dist_info / "licenses" / "LICENSES" / "BUSL-1.1.txt"
license_path.parent.mkdir(parents=True)
shutil.copy2("/src/node_pkg/LICENSES/BUSL-1.1.txt", license_path)

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
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

TOKEN = "node-wheel-proof-token-000000000000"

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
        return response.status, json.loads(response.read())

with tempfile.TemporaryDirectory(prefix="seam-node-proof-") as temporary:
    root = Path(temporary)
    env = {
        **os.environ,
        "SEAM_API_TOKEN": TOKEN,
        "SEAM_SERVER_DB": str(root / "seam.db"),
        "SEAM_SELFHOST_HOST": "127.0.0.1",
        "SEAM_SELFHOST_PORT": "8765",
    }
    env.pop("SEAM_SELFHOST_ENTITLEMENT_PATH", None)
    env.pop("SEAM_SELFHOST_PUBLIC_KEY_PATH", None)
    executable = shutil.which("seam-node")
    if executable is None:
        raise SystemExit("seam-node console entry point was not installed")
    mcp_executable = shutil.which("seam-mcp")
    if mcp_executable is None:
        raise SystemExit("seam-mcp console entry point was not installed")
    server = subprocess.Popen(
        [executable],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        deadline = time.monotonic() + 20
        while True:
            if server.poll() is not None:
                raise RuntimeError("seam-node exited before becoming healthy")
            try:
                health = request("GET", "/v1/health")
                break
            except (OSError, urllib.error.URLError):
                if time.monotonic() >= deadline:
                    raise RuntimeError("seam-node did not become healthy")
                time.sleep(0.2)

        try:
            request("POST", "/v1/memories", {"text": "unauthorized"}, authenticated=False)
        except urllib.error.HTTPError as exc:
            unauthorized = exc.code
        else:
            raise AssertionError("unauthenticated memory write unexpectedly succeeded")

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
        print("NODE WHEEL RUNTIME PROOF")
        print(f"GET /v1/health -> {health[0]} {json.dumps(health[1], sort_keys=True)}")
        print(f"POST /v1/memories unauthenticated -> {unauthorized}")
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
            [mcp_executable, "--db", str(root / "mcp.db")],
            input="\n".join(json.dumps(item) for item in mcp_requests) + "\n",
            env=env,
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
            "seam_memory_search",
            "seam_ingest",
            "seam_context",
            "seam_retrieve",
        }
        if not required_tools <= tool_names:
            raise AssertionError(
                f"MCP tools/list omitted required tools: {required_tools - tool_names}"
            )
        print(
            "MCP initialize -> "
            f"protocol={initialized['protocolVersion']} "
            f"server={initialized['serverInfo']['name']}"
        )
        print(
            "MCP tools/list -> "
            f"tools={len(tools)} required={len(required_tools)}"
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
COPY node_pkg/ ./node_pkg/
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


def build_node_wheel(outdir: Path) -> tuple[Path, ...]:
    """Build one verified cp312 manylinux wheel into an initially empty directory."""
    outdir = outdir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    if any(outdir.iterdir()):
        raise ValueError(f"output directory must be empty: {outdir}")

    with tempfile.TemporaryDirectory(prefix="seam-node-build-") as temporary:
        root = Path(temporary)
        context = root / "context"
        result = root / "result"
        context.mkdir()
        result.mkdir()

        for relative in NODE_FILES:
            _copy_file(NODE_SRC / relative, context / "node_pkg" / relative)
        _copy_file(
            REPO / "LICENSES" / "BUSL-1.1.txt",
            context / "node_pkg" / "LICENSES" / "BUSL-1.1.txt",
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

        print("[node-wheel] building locally; no upload or registry push is performed")
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
                "tools.release.verify_node_wheel",
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
        artifacts = build_node_wheel(args.outdir)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"node wheel build failed: {exc}", file=sys.stderr)
        return 1
    for artifact in artifacts:
        print(f"  -> {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
