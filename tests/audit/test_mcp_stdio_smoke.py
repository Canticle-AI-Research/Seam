"""CI3 — MCP stdio JSON-RPC handshake smoke test.

Verifies the seam_runtime.mcp_protocol entrypoint responds to initialize and
tools/list per JSON-RPC 2.0. Subprocess isolation catches import/entrypoint
regressions unit tests miss.
"""

import json
import select
import subprocess
import sys

import pytest

INITIALIZE = json.dumps({
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "seam-ci-smoke", "version": "0.0.1"},
    },
})
TOOLS_LIST = json.dumps({
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {},
})


def _spawn_mcp():
    return subprocess.Popen(
        [sys.executable, "-m", "seam_runtime.mcp_protocol"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _read_response(proc, timeout: float = 5.0):
    ready, _, _ = select.select([proc.stdout], [], [], timeout)
    if not ready:
        pytest.fail(f"MCP subprocess did not emit a response within {timeout:.1f}s")
    line = proc.stdout.readline()
    if not line:
        stderr = ""
        if proc.poll() is not None:
            stderr = proc.stderr.read().decode(errors="replace")
        pytest.fail(f"MCP subprocess stdout closed before response; stderr={stderr!r}")
    return json.loads(line)


@pytest.mark.skipif(sys.platform == "win32", reason=(
    "Subprocess pipe handshake timing is unreliable on Windows-runner Python; "
    "revisit if a Windows MCP regression appears"
))
def test_mcp_stdio_handshake():
    proc = None
    try:
        proc = _spawn_mcp()

        proc.stdin.write((INITIALIZE + "\n").encode())
        proc.stdin.write((TOOLS_LIST + "\n").encode())
        proc.stdin.flush()
        proc.stdin.close()

        init_resp = _read_response(proc)

        assert init_resp["jsonrpc"] == "2.0", (
            f"init jsonrpc: {init_resp.get('jsonrpc')}"
        )
        assert init_resp["id"] == 1, f"init id: {init_resp.get('id')}"
        assert "result" in init_resp, (
            f"init error: {init_resp.get('error')}"
        )
        result = init_resp["result"]
        assert isinstance(result["protocolVersion"], str), (
            f"protocolVersion: {result.get('protocolVersion')}"
        )
        assert len(result["protocolVersion"]) > 0, "protocolVersion empty"
        assert isinstance(result["capabilities"], dict)
        assert isinstance(result["serverInfo"]["name"], str)
        assert len(result["serverInfo"]["name"]) > 0, "serverInfo.name empty"

        tools_resp = _read_response(proc)

        assert tools_resp["jsonrpc"] == "2.0", (
            f"tools jsonrpc: {tools_resp.get('jsonrpc')}"
        )
        assert tools_resp["id"] == 2, f"tools id: {tools_resp.get('id')}"
        assert "result" in tools_resp, (
            f"tools error: {tools_resp.get('error')}"
        )
        tools = tools_resp["result"]["tools"]
        assert isinstance(tools, list)
        assert len(tools) >= 1, f"Expected >=1 tools, got {len(tools)}"

        for tool in tools:
            assert isinstance(tool["name"], str), f"tool name not str: {tool}"
            assert isinstance(tool["description"], str), f"tool desc not str: {tool}"
            assert isinstance(tool["inputSchema"], dict), f"tool schema not dict: {tool}"

        seam_tools = [t for t in tools if t["name"].startswith("seam_")]
        assert len(seam_tools) >= 1, (
            f"No seam_*-prefixed tool found among {[t['name'] for t in tools]}"
        )

        proc.terminate()
        proc.wait(timeout=10)

    finally:
        if proc is not None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
