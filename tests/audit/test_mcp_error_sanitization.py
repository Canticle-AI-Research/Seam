"""Lane B -- MCP Secret Hygiene tests.

Verify that MCP error responses redact internal details while preserving
intentional validation messages.
"""

import json
import select
import subprocess
import sys

import pytest

# ---------------------------------------------------------------------------
# Test 1: malformed JSON via subprocess -- error must not leak raw input
# ---------------------------------------------------------------------------

@pytest.mark.skipif(sys.platform == "win32", reason=(
    "Subprocess pipe handshake timing is unreliable on Windows-runner Python"
))
def test_mcp_malformed_json_error_does_not_leak_input():
    """Send malformed JSON to the MCP stdio server; the parse error must not
    include the raw input text."""
    proc = None
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "seam_runtime.mcp_protocol"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        # Malformed input that should not appear in any error response.
        malformed = '{"jsonrpc": "2.0" "id": 1'  # missing comma between fields
        proc.stdin.write((malformed + "\n").encode())
        proc.stdin.flush()
        proc.stdin.close()

        ready, _, _ = select.select([proc.stdout], [], [], 5.0)
        if not ready:
            pytest.fail("MCP subprocess did not emit a parse-error response within 5s")
        line = proc.stdout.readline()
        assert line, "MCP subprocess stdout closed before parse-error response"
        response = json.loads(line)

        # The error must not contain the raw input string.
        error_serialized = json.dumps(response)
        assert malformed not in error_serialized, (
            f"Parse error leaked raw input text:\n{error_serialized}"
        )
        # Confirm we got an actual error response.
        assert "error" in response, f"Expected error envelope, got: {response}"
        assert response["error"]["code"] == -32700, (
            f"Expected parse error code -32700, got: {response['error']}"
        )
    finally:
        if proc is not None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Test 2: unexpected exception in dispatch_tool is redacted
# ---------------------------------------------------------------------------

def test_mcp_call_tool_redacts_unexpected_exception():
    """When dispatch_tool raises something other than ValueError/KeyError,
    the error text must be a generic message, not the exception string."""
    import seam_runtime.mcp_protocol as mcp_protocol

    original_dispatch = mcp_protocol.dispatch_tool

    def _raising_dispatch(_runtime, _request):
        raise RuntimeError("SECRET: database password is hunter2")

    mcp_protocol.dispatch_tool = _raising_dispatch
    try:
        result = mcp_protocol._call_tool(None, "seam_stats", {})
        assert result["isError"] is True
        error_text = result["content"][0]["text"]
        assert error_text == "Internal tool execution error", (
            f"Expected redacted message, got: {error_text!r}"
        )
        assert "SECRET" not in error_text
        assert "hunter2" not in error_text
        assert "RuntimeError" not in error_text
    finally:
        mcp_protocol.dispatch_tool = original_dispatch


# ---------------------------------------------------------------------------
# Test 3: ValueError messages ARE preserved (they are intentional validation)
# ---------------------------------------------------------------------------

def test_mcp_call_tool_preserves_valueerror():
    """ValueError raised by dispatch_tool (e.g. missing required field) must
    be preserved in the error response so callers can fix their arguments."""
    import seam_runtime.mcp_protocol as mcp_protocol

    # seam_memory_search requires "query" -- omitting it triggers ValueError.
    result = mcp_protocol._call_tool(None, "seam_memory_search", {})
    assert result["isError"] is True
    error_text = result["content"][0]["text"]
    assert "query is required" in error_text, (
        f"Expected validation message in error, got: {error_text!r}"
    )


def test_mcp_call_tool_preserves_keyerror():
    """KeyError raised intentionally (e.g. missing surface ref) must be
    preserved in the error response."""
    import seam_runtime.mcp_protocol as mcp_protocol
    from seam_runtime.runtime import SeamRuntime

    runtime = SeamRuntime(":memory:")
    # seam_surface_show with a missing hs ref triggers KeyError from the store.
    result = mcp_protocol._call_tool(runtime, "seam_surface_show",
                                     {"surface_ref": "hs:deadbeef00000000"})
    assert result["isError"] is True
    error_text = result["content"][0]["text"]
    # KeyError message mentions the ref.
    assert "deadbeef" in error_text or "hs:deadbeef" in error_text, (
        f"Expected KeyError detail preserved, got: {error_text!r}"
    )
