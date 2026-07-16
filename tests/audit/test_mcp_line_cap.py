"""P3 Fix 8 — MCP stdin line-size cap (genuinely bounded read)."""
from __future__ import annotations

import io
import json
import os
from unittest import mock

from seam_runtime.mcp_protocol import (
    _OVERSIZED_LINE,
    MAX_MCP_LINE_BYTES,
    _read_capped_lines,
    run_mcp_server,
)
from seam_runtime.runtime import SeamRuntime


def test_normal_line_passes_through() -> None:
    stream = io.StringIO('{"jsonrpc":"2.0","method":"ping","id":1}\n')
    lines = list(_read_capped_lines(stream, MAX_MCP_LINE_BYTES))
    assert len(lines) == 1
    assert lines[0] == '{"jsonrpc":"2.0","method":"ping","id":1}\n'


def test_oversized_line_returns_sentinel() -> None:
    payload = "x" * (MAX_MCP_LINE_BYTES + 100)
    stream = io.StringIO(payload + "\n")
    lines = list(_read_capped_lines(stream, MAX_MCP_LINE_BYTES))
    assert len(lines) == 1
    assert lines[0] is _OVERSIZED_LINE


def test_oversized_line_produces_error_response() -> None:
    payload = "x" * (MAX_MCP_LINE_BYTES + 100)
    input_stream = io.StringIO(payload + "\n")
    output_stream = io.StringIO()
    runtime = SeamRuntime(":memory:")

    run_mcp_server(runtime, input_stream=input_stream, output_stream=output_stream)
    output = output_stream.getvalue()
    assert output
    response = json.loads(output)
    assert response["error"]["code"] == -32600
    assert response["error"]["data"]["reason"] == "request too large"


def test_legitimate_payload_not_oversized() -> None:
    """A payload whose content happens to contain the old string sentinel
    must not be treated as oversized."""
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "id": 1,
            "params": {
                "name": "seam_memory_search",
                "arguments": {"query": "__SEAM_MCP_OVERSIZED_LINE__"},
            },
        }
    )
    # payload should be well under the default 5 MiB cap
    assert len(payload.encode("utf-8")) < MAX_MCP_LINE_BYTES
    stream = io.StringIO(payload + "\n")
    lines = list(_read_capped_lines(stream, MAX_MCP_LINE_BYTES))
    assert len(lines) == 1
    assert lines[0] == payload + "\n"
    assert lines[0] is not _OVERSIZED_LINE


def test_env_override_increases_cap() -> None:
    """SEAM_MCP_MAX_LINE_BYTES=20000000 allows 10 MiB line."""
    with mock.patch.dict(os.environ, {"SEAM_MCP_MAX_LINE_BYTES": "20000000"}):
        import importlib

        import seam_runtime.mcp_protocol as mcp_mod

        importlib.reload(mcp_mod)
        cap = mcp_mod.MAX_MCP_LINE_BYTES
        assert cap == 20000000

        payload = "x" * 10_000_000
        stream = io.StringIO(payload + "\n")
        lines = list(mcp_mod._read_capped_lines(stream, cap))
        assert len(lines) == 1
        assert lines[0] == payload + "\n"
