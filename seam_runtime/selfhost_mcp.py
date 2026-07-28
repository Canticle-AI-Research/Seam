"""Opaque MCP stdio entrypoint for the proprietary compiled self-host edition.

This is the MCP counterpart to the opaque ``/v1`` surface in ``selfhost.py`` and
exists for the same reason: the internal tool registry in ``mcp.py`` describes
the runtime's internal architecture in its tool metadata, and that metadata is
served verbatim to every connected client by ``tools/list``. A self-host build
must not disclose it, so this module defines its own product-language tool
vocabulary and is compiled in place of ``mcp`` and ``mcp_protocol``.

The three tools map one-to-one onto the audited public operations in
``public_api``. No operation is reachable here that is not already reachable
over ``/v1``, and responses carry user-facing text plus opaque receipts and ids.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Iterator, TextIO

from .runtime import SeamRuntime

SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
DEFAULT_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]

JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603

DEFAULT_DB_PATH = Path("/var/lib/seam/seam.db")

_DEFAULT_MCP_MAX_LINE_BYTES = 5_000_000

MAX_MCP_LINE_BYTES: int = int(
    os.environ.get("SEAM_MCP_MAX_LINE_BYTES", str(_DEFAULT_MCP_MAX_LINE_BYTES))
)

_OVERSIZED_LINE = object()

_QUERY_PROPERTIES: dict[str, object] = {
    "query": {
        "type": "string",
        "required": True,
        "description": "What to look for.",
    },
    "namespace": {
        "type": "string",
        "description": "Optional grouping for unrelated sets of memories.",
    },
    "scope": {
        "type": "string",
        "description": "Optional visibility scope for the memories to consider.",
    },
    "session_id": {
        "type": "string",
        "description": "Optional session identifier to keep memories separated.",
    },
    "limit": {
        "type": "integer",
        "default": 5,
        "description": "Maximum number of memories to return.",
    },
}

TOOL_METADATA: dict[str, dict[str, object]] = {
    "seam_remember": {
        "description": "Store a memory so it can be recalled in a later conversation.",
        "input_schema": {
            "text": {
                "type": "string",
                "required": True,
                "description": "The text to remember.",
            },
            "namespace": _QUERY_PROPERTIES["namespace"],
            "scope": _QUERY_PROPERTIES["scope"],
            "session_id": _QUERY_PROPERTIES["session_id"],
            "agent_id": {
                "type": "string",
                "description": "Optional identifier for the agent storing the memory.",
            },
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
    },
    "seam_recall": {
        "description": "Recall stored memories relevant to a query.",
        "input_schema": dict(_QUERY_PROPERTIES),
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
    "seam_context": {
        "description": "Build a prompt-ready context block from stored memories.",
        "input_schema": {
            **_QUERY_PROPERTIES,
            "max_chars": {
                "type": "integer",
                "default": 8000,
                "description": "Maximum size of the returned context block.",
            },
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
}


class JsonRpcError(Exception):
    def __init__(self, code: int, message: str, data: object | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def _read_capped_lines(stream: TextIO, max_bytes: int) -> Iterator[str | object]:
    """Yield lines from *stream*, substituting ``_OVERSIZED_LINE`` for any
    line whose UTF-8 byte length exceeds *max_bytes*.

    For streams backed by a binary buffer (``sys.stdin``) the read is genuinely
    bounded via ``readline(max_bytes + 1)`` so that an oversized line never
    occupies memory in full.
    """
    binary = getattr(stream, "buffer", None)
    if binary is not None:
        yield from _read_capped_binary_lines(binary, max_bytes)
    else:
        for line in stream:
            if not line:
                return
            if len(line.encode("utf-8")) > max_bytes:
                yield _OVERSIZED_LINE
                continue
            yield line


def _read_capped_binary_lines(binary: object, max_bytes: int) -> Iterator[str | object]:
    readline = getattr(binary, "readline")
    if readline is None:
        return
    while True:
        chunk: bytes = readline(max_bytes + 1)
        if not chunk:
            return
        if len(chunk) > max_bytes or not chunk.endswith(b"\n"):
            # Drain the rest of this physical line in bounded chunks.
            while True:
                tail: bytes = readline(8192)
                if not tail or tail.endswith(b"\n"):
                    break
            yield _OVERSIZED_LINE
            continue
        yield chunk.decode("utf-8")


def run_selfhost_mcp_server(
    runtime: SeamRuntime,
    input_stream: TextIO | None = None,
    output_stream: TextIO | None = None,
) -> None:
    """Run an MCP stdio server exposing only the opaque memory tools."""

    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stdout
    for raw_line in _read_capped_lines(input_stream, MAX_MCP_LINE_BYTES):
        if raw_line is _OVERSIZED_LINE:
            _write_jsonrpc(
                output_stream,
                _error_response(
                    None,
                    JSONRPC_INVALID_REQUEST,
                    "Invalid Request",
                    {"reason": "request too large"},
                ),
            )
            continue
        line = raw_line
        if not line.strip():
            continue
        for response in _handle_jsonrpc_line(runtime, line):
            if response is not None:
                _write_jsonrpc(output_stream, response)


def _handle_jsonrpc_line(runtime: SeamRuntime, line: str) -> list[dict[str, object] | None]:
    try:
        message = json.loads(line)
    except json.JSONDecodeError:
        return [_error_response(None, JSONRPC_PARSE_ERROR, "Parse error")]

    if isinstance(message, list):
        if not message:
            return [_error_response(None, JSONRPC_INVALID_REQUEST, "Invalid Request")]
        return [_handle_jsonrpc_message(runtime, item) for item in message]
    return [_handle_jsonrpc_message(runtime, message)]


def _handle_jsonrpc_message(runtime: SeamRuntime, message: object) -> dict[str, object] | None:
    if not isinstance(message, dict):
        return _error_response(None, JSONRPC_INVALID_REQUEST, "Invalid Request")
    request_id = message.get("id")
    method = message.get("method")
    if message.get("jsonrpc") != "2.0" or not isinstance(method, str):
        return _error_response(request_id, JSONRPC_INVALID_REQUEST, "Invalid Request")

    # JSON-RPC notifications do not receive responses.
    if request_id is None:
        return None

    try:
        result = _dispatch_mcp_method(runtime, method, message.get("params") or {})
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except JsonRpcError as exc:
        return _error_response(request_id, exc.code, exc.message, exc.data)
    except Exception:  # pragma: no cover - defensive protocol boundary
        traceback.print_exc(file=sys.stderr)
        return _error_response(request_id, JSONRPC_INTERNAL_ERROR, "Internal error")


def _dispatch_mcp_method(runtime: SeamRuntime, method: str, params: object) -> dict[str, object]:
    if method == "initialize":
        if not isinstance(params, dict):
            raise JsonRpcError(JSONRPC_INVALID_PARAMS, "initialize params must be an object")
        requested_version = str(params.get("protocolVersion") or "")
        protocol_version = (
            requested_version
            if requested_version in SUPPORTED_PROTOCOL_VERSIONS
            else DEFAULT_PROTOCOL_VERSION
        )
        return {
            "protocolVersion": protocol_version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {
                "name": "seam",
                "title": "SEAM Memory",
                "version": "v1",
            },
            "instructions": (
                "Use SEAM to store memories and recall them later, and to build "
                "prompt-ready context from what has been stored."
            ),
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {
            "tools": [
                _mcp_tool_definition(name, metadata)
                for name, metadata in TOOL_METADATA.items()
            ]
        }
    if method == "tools/call":
        if not isinstance(params, dict):
            raise JsonRpcError(JSONRPC_INVALID_PARAMS, "tools/call params must be an object")
        name = str(params.get("name") or "")
        if name not in TOOL_METADATA:
            raise JsonRpcError(JSONRPC_INVALID_PARAMS, f"Unknown tool: {name!r}")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            raise JsonRpcError(JSONRPC_INVALID_PARAMS, "tools/call arguments must be an object")
        return _call_tool(runtime, name, arguments)
    raise JsonRpcError(JSONRPC_METHOD_NOT_FOUND, f"Method not found: {method}")


def _call_tool(runtime: SeamRuntime, name: str, arguments: dict[str, object]) -> dict[str, object]:
    from .public_api import PublicAPIInputError, context, recall, remember

    operations = {
        "seam_remember": remember,
        "seam_recall": recall,
        "seam_context": context,
    }
    try:
        result = operations[name](runtime, arguments)
    except PublicAPIInputError as exc:
        return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    except Exception:
        traceback.print_exc(file=sys.stderr)
        return {
            "content": [{"type": "text", "text": "Internal tool execution error"}],
            "isError": True,
        }
    return {
        "content": [{"type": "text", "text": json.dumps(result, indent=2, sort_keys=True)}],
        "structuredContent": result,
        "isError": False,
    }


def _mcp_tool_definition(name: str, metadata: dict[str, object]) -> dict[str, object]:
    title = " ".join(part.capitalize() for part in name.removeprefix("seam_").split("_"))
    return {
        "name": name,
        "title": f"SEAM {title}",
        "description": str(metadata.get("description") or ""),
        "inputSchema": _mcp_input_schema(metadata.get("input_schema")),
        "annotations": metadata.get("annotations") or {},
    }


def _mcp_input_schema(input_schema: object) -> dict[str, object]:
    if not isinstance(input_schema, dict) or not input_schema:
        return {"type": "object", "properties": {}, "additionalProperties": False}
    properties: dict[str, object] = {}
    required: list[str] = []
    for key, spec in input_schema.items():
        if not isinstance(spec, dict):
            continue
        if spec.get("required") is True:
            required.append(str(key))
        properties[str(key)] = _mcp_property_schema(spec)
    schema: dict[str, object] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def _mcp_property_schema(spec: dict[str, object]) -> dict[str, object]:
    schema: dict[str, object] = {"type": str(spec.get("type") or "string")}
    for key in ("description", "default", "minimum", "maximum", "pattern", "enum"):
        if key in spec:
            schema[key] = spec[key]
    return schema


def _error_response(
    request_id: object, code: int, message: str, data: object | None = None
) -> dict[str, object]:
    error: dict[str, object] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _write_jsonrpc(output_stream: TextIO, payload: dict[str, object]) -> None:
    output_stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    output_stream.flush()


def _default_db_path() -> str:
    return os.environ.get("SEAM_SERVER_DB", str(DEFAULT_DB_PATH))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the SEAM memory MCP stdio server")
    parser.add_argument("--db", default=_default_db_path(), help="Database path")
    args = parser.parse_args(argv)
    run_selfhost_mcp_server(SeamRuntime(Path(args.db)))


if __name__ == "__main__":  # pragma: no cover
    main()
