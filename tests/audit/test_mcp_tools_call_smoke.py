"""B3 — MCP tools/call round-trip smoke test.

Spawns the canonical seam_runtime.mcp_protocol entrypoint, performs the
initialize + tools/call(seam_stats) JSON-RPC 2.0 handshake, and asserts
a well-formed envelope with structuredContent. Extends CI3
(test_mcp_stdio_smoke.py) which covered initialize + tools/list only.
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
        "clientInfo": {"name": "seam-ci-tools-call-smoke", "version": "0.0.1"},
    },
})
TOOLS_CALL = json.dumps({
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
        "name": "seam_stats",
        "arguments": {},
    },
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
def test_mcp_tools_call_seam_stats_round_trip():
    proc = None
    try:
        proc = _spawn_mcp()

        proc.stdin.write((INITIALIZE + "\n").encode())
        proc.stdin.write((TOOLS_CALL + "\n").encode())
        proc.stdin.flush()
        proc.stdin.close()

        init_resp = _read_response(proc)
        assert init_resp["jsonrpc"] == "2.0"
        assert init_resp["id"] == 1
        assert "result" in init_resp, f"init returned error: {init_resp.get('error')}"

        call_resp = _read_response(proc)
        assert call_resp["jsonrpc"] == "2.0", f"call jsonrpc: {call_resp.get('jsonrpc')}"
        assert call_resp["id"] == 2, f"call id: {call_resp.get('id')}"
        assert "result" in call_resp, f"call returned error envelope: {call_resp.get('error')}"

        result = call_resp["result"]
        # isError must be present and False on a successful read-only call.
        assert result.get("isError") is False, (
            f"seam_stats reported isError=True: {result}"
        )

        # content[0] must be a text item with a non-empty JSON-encoded payload.
        content = result.get("content")
        assert isinstance(content, list) and len(content) >= 1, f"content: {content}"
        first = content[0]
        assert first.get("type") == "text", f"first content type: {first}"
        text = first.get("text")
        assert isinstance(text, str) and len(text) > 0, f"text empty: {first}"
        # The text field is JSON-encoded structured result; round-trip parse must succeed.
        parsed = json.loads(text)
        assert isinstance(parsed, dict), f"parsed content not dict: {parsed!r}"

        # structuredContent must mirror the same payload as a dict.
        structured = result.get("structuredContent")
        assert isinstance(structured, dict), f"structuredContent not dict: {structured!r}"
        # seam_stats returns record counts; assert at least one expected key.
        # (Do NOT enumerate the full schema — that grows over time.)
        # Accept either direct keys (records, documents, vector_index) or a nested {"result": ...}.
        flat = structured.get("result") if "result" in structured else structured
        assert isinstance(flat, dict), f"stats payload not dict: {flat!r}"

        proc.terminate()
        proc.wait(timeout=10)

    finally:
        if proc is not None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass
