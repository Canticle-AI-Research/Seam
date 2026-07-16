from __future__ import annotations

import json
import os
import re
import sys
import traceback
from pathlib import Path
from typing import TextIO

from .doctor import build_doctor_report
from .holographic import context_surface, decode_surface, query_surface, verify_surface
from .runtime import SeamRuntime

# Backwards-compatible name->description map. The ready line still emits this
# under the "tools" key so existing JSONL clients keep working.
TOOL_DESCRIPTIONS = {
    "seam_memory_search": "Return compact progressive-disclosure memory search results.",
    "seam_memory_get": "Return full MIRL records for selected ids.",
    "seam_ingest": "Compile and persist text into SEAM memory.",
    "seam_knowledge_graph": "Search and traverse SEAM's self-building temporal knowledge graph.",
    "seam_knowledge_node": "Open one graph-backed knowledge page with facts, backlinks, agents, and sources.",
    "seam_stats": "Return SQLite store stats (record counts, vector index size, document totals).",
    "seam_documents": "List recent persisted document_status rows (source_ref, hash, indexed state).",
    "seam_context": "Search and pack a prompt-ready context payload for a query (mirrors `seam context`).",
    "seam_doctor": "Run the SEAM install/runtime smoke check (mirrors `seam doctor`); pgvector error strings are redacted.",
    "seam_surface_list": "List stored SEAM-HS/1 surface library entries (mirrors `seam surface list`).",
    "seam_surface_show": "Show one stored SEAM-HS/1 surface library entry by `hs:<id>` ref (mirrors `seam surface show`).",
    "seam_surface_query": "Query embedded MIRL or SEAM-RC/1 directly inside a registered HS/1 surface by `hs:<id>` (mirrors `seam surface query`).",
    "seam_surface_decode": "Decode the embedded payload of a registered HS/1 surface by `hs:<id>` and return its metadata + truncated text view.",
    "seam_surface_verify": "Verify a registered HS/1 surface by `hs:<id>`: check hash integrity and return PASS/FAIL with error details.",
    "seam_surface_context": "Extract a prompt-ready context pack directly from a registered HS/1 surface PNG by `hs:<id>` without restoring the source document.",
    "seam_index_status": "Report vector index staleness: compare stored MIRL records against embedded vector hashes and return missing/stale records.",
    "seam_retrieve": "Run full retrieval (vector, graph, hybrid, or mix) and return ranked results with optional trace.",
    "seam_benchmark_latest": "Return the most recent persisted benchmark run summaries for agent triage.",
}


# Structured tool metadata: input schema + annotations. Emitted on the ready
# line alongside TOOL_DESCRIPTIONS for clients that want richer info. Per
# MCP best practices, annotations are hints for the agent (not security gates).
TOOL_METADATA = {
    "seam_memory_search": {
        "description": TOOL_DESCRIPTIONS["seam_memory_search"],
        "input_schema": {
            "query": {"type": "string", "required": True, "description": "Search text."},
            "scope": {"type": "string", "required": False, "description": "Optional scope filter (e.g. 'thread', 'project')."},
            "budget": {"type": "integer", "required": False, "default": 5, "minimum": 1, "maximum": 200, "description": "Max number of compact index hits."},
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    "seam_memory_get": {
        "description": TOOL_DESCRIPTIONS["seam_memory_get"],
        "input_schema": {
            "ids": {"type": "array<string> or comma-string", "required": True, "description": "Record ids returned by seam_memory_search."},
            "timeline": {"type": "boolean", "required": False, "default": False, "description": "Include neighbor-event timeline context."},
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    "seam_ingest": {
        "description": TOOL_DESCRIPTIONS["seam_ingest"],
        "input_schema": {
            "text": {"type": "string", "required": True, "description": "Raw natural-language text to compile + persist."},
            "source_ref": {"type": "string", "required": False, "default": "agent://input", "description": "Stable source identifier for document_status."},
            "agent_id": {"type": "string", "required": False, "description": "Identity of the contributing agent; defaults to SEAM_AGENT when set."},
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    "seam_knowledge_graph": {
        "description": TOOL_DESCRIPTIONS["seam_knowledge_graph"],
        "input_schema": {
            "query": {"type": "string", "required": False, "description": "Optional node, fact, or source search text."},
            "root_id": {"type": "string", "required": False, "description": "Optional node id to traverse from."},
            "agent_id": {"type": "string", "required": False, "description": "Restrict results to knowledge contributed by this agent."},
            "namespace": {"type": "string", "required": False},
            "scope": {"type": "string", "required": False},
            "kinds": {"type": "string", "required": False, "description": "Comma-separated node kinds."},
            "include_history": {"type": "boolean", "required": False, "default": False},
            "at": {"type": "string", "required": False, "description": "ISO-8601 knowledge-time horizon."},
            "limit": {"type": "integer", "required": False, "default": 100, "minimum": 1, "maximum": 1000},
            "hops": {"type": "integer", "required": False, "default": 2, "minimum": 0, "maximum": 5},
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    "seam_knowledge_node": {
        "description": TOOL_DESCRIPTIONS["seam_knowledge_node"],
        "input_schema": {
            "node_id": {"type": "string", "required": True, "description": "Knowledge node id returned by seam_knowledge_graph."},
            "include_history": {"type": "boolean", "required": False, "default": True},
            "at": {"type": "string", "required": False, "description": "ISO-8601 knowledge-time horizon."},
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    "seam_stats": {
        "description": TOOL_DESCRIPTIONS["seam_stats"],
        "input_schema": {},
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    "seam_documents": {
        "description": TOOL_DESCRIPTIONS["seam_documents"],
        "input_schema": {
            "limit": {"type": "integer", "required": False, "default": 20, "minimum": 1, "maximum": 200, "description": "Max number of recent documents to return."},
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    "seam_context": {
        "description": TOOL_DESCRIPTIONS["seam_context"],
        "input_schema": {
            "query": {"type": "string", "required": True, "description": "Question or topic to retrieve context for."},
            "scope": {"type": "string", "required": False},
            "budget": {"type": "integer", "required": False, "default": 5, "minimum": 1, "maximum": 200, "description": "Max search candidates considered."},
            "pack_budget": {"type": "integer", "required": False, "default": 512, "minimum": 1, "maximum": 65536, "description": "Token budget for the prompt-ready pack."},
            "lens": {"type": "string", "required": False, "default": "rag", "description": "Pack lens label."},
            "mode": {"type": "string", "required": False, "default": "context", "description": "Pack mode: 'context' (default), 'narrative', or 'exact'."},
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    "seam_doctor": {
        "description": TOOL_DESCRIPTIONS["seam_doctor"],
        "input_schema": {},
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    },
    "seam_surface_list": {
        "description": TOOL_DESCRIPTIONS["seam_surface_list"],
        "input_schema": {
            "limit": {"type": "integer", "required": False, "default": 20, "minimum": 1, "maximum": 200},
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    "seam_surface_show": {
        "description": TOOL_DESCRIPTIONS["seam_surface_show"],
        "input_schema": {
            "surface_ref": {"type": "string", "required": True, "pattern": "^hs:[0-9a-f]+$", "description": "Canonical 'hs:<hex>' surface id from seam_surface_list."},
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    "seam_surface_query": {
        "description": TOOL_DESCRIPTIONS["seam_surface_query"],
        "input_schema": {
            "surface_ref": {"type": "string", "required": True, "pattern": "^hs:[0-9a-f]+$"},
            "query": {"type": "string", "required": True},
            "limit": {"type": "integer", "required": False, "default": 5, "minimum": 1, "maximum": 50},
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    "seam_surface_decode": {
        "description": TOOL_DESCRIPTIONS["seam_surface_decode"],
        "input_schema": {
            "surface_ref": {"type": "string", "required": True, "pattern": "^hs:[0-9a-f]+$"},
            "truncate_text": {"type": "integer", "required": False, "default": 4096, "minimum": 0, "maximum": 65536, "description": "Max chars of decoded text to return; 0 returns metadata only."},
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    "seam_benchmark_latest": {
        "description": TOOL_DESCRIPTIONS["seam_benchmark_latest"],
        "input_schema": {
            "limit": {"type": "integer", "required": False, "default": 1, "minimum": 1, "maximum": 50},
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    "seam_surface_verify": {
        "description": TOOL_DESCRIPTIONS["seam_surface_verify"],
        "input_schema": {
            "surface_ref": {"type": "string", "required": True, "pattern": "^hs:[0-9a-f]+$", "description": "Canonical 'hs:<hex>' surface id from seam_surface_list."},
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    "seam_surface_context": {
        "description": TOOL_DESCRIPTIONS["seam_surface_context"],
        "input_schema": {
            "surface_ref": {"type": "string", "required": True, "pattern": "^hs:[0-9a-f]+$"},
            "query": {"type": "string", "required": True, "description": "Question or topic to build context around."},
            "budget": {"type": "integer", "required": False, "default": 1200, "minimum": 1, "maximum": 65536, "description": "Token budget for prompt-ready context."},
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    "seam_index_status": {
        "description": TOOL_DESCRIPTIONS["seam_index_status"],
        "input_schema": {
            "scope": {"type": "string", "required": False, "description": "Optional scope filter."},
            "limit": {"type": "integer", "required": False, "default": 100, "minimum": 1, "maximum": 500, "description": "Max stale records to return before truncating."},
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    },
    "seam_retrieve": {
        "description": TOOL_DESCRIPTIONS["seam_retrieve"],
        "input_schema": {
            "query": {"type": "string", "required": True, "description": "Search query."},
            "scope": {"type": "string", "required": False, "description": "Optional scope filter."},
            "budget": {"type": "integer", "required": False, "default": 5, "minimum": 1, "maximum": 50, "description": "Max ranked candidates returned."},
            "mode": {"type": "string", "required": False, "default": "hybrid", "enum": ["vector", "graph", "hybrid", "mix"], "description": "Retrieval mode: vector (semantic only), graph (relationship traversal), hybrid (vector+sql), mix (all three)."},
            "include_trace": {"type": "boolean", "required": False, "default": False, "description": "Include per-leg hit traces for debugging."},
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
}


_HS_REF_PATTERN = re.compile(r"^hs:[0-9a-f]+$")
_PACK_MODES = {"context", "exact", "narrative"}
_TEXT_PAYLOAD_FORMATS = {"MIRL", "SEAM-RC/1"}


def run_stdio_bridge(runtime: SeamRuntime, input_stream: TextIO | None = None, output_stream: TextIO | None = None) -> None:
    input_stream = input_stream or sys.stdin
    output_stream = output_stream or sys.stdout
    _write(output_stream, {"type": "ready", "tools": TOOL_DESCRIPTIONS, "tool_metadata": TOOL_METADATA})
    for line in input_stream:
        if not line.strip():
            continue
        try:
            request = json.loads(line)
            response = dispatch_tool(runtime, request)
        except Exception:  # pragma: no cover - defensive bridge boundary
            traceback.print_exc(file=sys.stderr)
            response = {"type": "error", "error": "Internal error processing MCP request"}
        _write(output_stream, response)


def dispatch_tool(runtime: SeamRuntime, request: dict[str, object]) -> dict[str, object]:
    name = str(request.get("tool") or request.get("name") or "")
    arguments = request.get("arguments") or {}
    if not isinstance(arguments, dict):
        raise ValueError("arguments must be an object")
    if name == "seam_memory_search":
        query = _required_text(arguments.get("query"), field="query", tool=name)
        budget = _bounded_int(arguments.get("budget"), default=5, low=1, high=200)
        scope = arguments.get("scope")
        return {"type": "result", "tool": name, "result": runtime.memory_search(query, scope=str(scope) if scope else None, budget=budget)}
    if name == "seam_memory_get":
        record_ids = _coerced_record_ids(arguments.get("ids") or arguments.get("record_ids"))
        return {"type": "result", "tool": name, "result": runtime.memory_get(record_ids, include_timeline=bool(arguments.get("timeline")))}
    if name == "seam_ingest":
        text = _required_text(arguments.get("text"), field="text", tool=name)
        source_ref = str(arguments.get("source_ref") or "agent://input")
        agent_id = str(arguments.get("agent_id") or "").strip() or None
        return {"type": "result", "tool": name, "result": runtime.ingest_text(text, source_ref=source_ref, agent_id=agent_id, persist=True).to_dict()}
    if name == "seam_knowledge_graph":
        kinds = str(arguments.get("kinds") or "")
        result = runtime.store.knowledge_graph(
            query=str(arguments.get("query") or "") or None,
            root_id=str(arguments.get("root_id") or "") or None,
            agent_id=str(arguments.get("agent_id") or "") or None,
            namespace=str(arguments.get("namespace") or "") or None,
            scope=str(arguments.get("scope") or "") or None,
            kinds=[item.strip() for item in kinds.split(",") if item.strip()] or None,
            include_history=bool(arguments.get("include_history", False)),
            at=str(arguments.get("at") or "") or None,
            limit=_bounded_int(arguments.get("limit"), default=100, low=1, high=1000),
            hops=_bounded_int(arguments.get("hops"), default=2, low=0, high=5),
        )
        return {"type": "result", "tool": name, "result": result}
    if name == "seam_knowledge_node":
        node_id = _required_text(arguments.get("node_id"), field="node_id", tool=name)
        result = runtime.store.knowledge_node(
            node_id,
            include_history=bool(arguments.get("include_history", True)),
            at=str(arguments.get("at") or "") or None,
        )
        return {"type": "result", "tool": name, "result": result}
    if name == "seam_stats":
        return {"type": "result", "tool": name, "result": runtime.store.get_stats()}
    if name == "seam_documents":
        limit = _bounded_int(arguments.get("limit"), default=20, low=1, high=200)
        rows = runtime.store.list_document_status(limit=limit)
        return {"type": "result", "tool": name, "result": _paginated(rows, key="documents", limit=limit)}
    if name == "seam_context":
        query = _required_text(arguments.get("query"), field="query", tool=name)
        scope_arg = arguments.get("scope")
        budget = _bounded_int(arguments.get("budget"), default=5, low=1, high=200)
        pack_budget = _bounded_int(arguments.get("pack_budget"), default=512, low=1, high=65536)
        lens = str(arguments.get("lens") or "rag")
        mode = _validated_pack_mode(arguments.get("mode"))
        search_result = runtime.search_ir(
            query=query,
            scope=str(scope_arg) if isinstance(scope_arg, str) and scope_arg else None,
            budget=budget,
            lens=str(arguments.get("search_lens") or "general"),
        )
        record_ids = [candidate.record.id for candidate in search_result.candidates]
        pack = runtime.pack_ir(
            record_ids=record_ids,
            lens=lens,
            budget=pack_budget,
            mode=mode,
            persist=False,
        )
        return {
            "type": "result",
            "tool": name,
            "result": {
                "query": query,
                "candidates": search_result.to_dict()["candidates"],
                "pack": pack.to_dict(),
            },
        }
    if name == "seam_doctor":
        return {"type": "result", "tool": name, "result": _redact_doctor_report(build_doctor_report())}
    if name == "seam_surface_list":
        limit = _bounded_int(arguments.get("limit"), default=20, low=1, high=200)
        rows = runtime.store.list_surface_artifacts(limit=limit)
        return {"type": "result", "tool": name, "result": _paginated(rows, key="surfaces", limit=limit)}
    if name == "seam_surface_show":
        surface_ref = _validated_hs_ref(arguments.get("surface_ref") or arguments.get("ref"))
        try:
            row = runtime.store.read_surface_artifact(surface_ref)
        except KeyError:
            raise KeyError(f"No registered surface for ref '{surface_ref}'. Use seam_surface_list to discover registered surfaces.")
        return {"type": "result", "tool": name, "result": row}
    if name == "seam_surface_query":
        surface_ref = _validated_hs_ref(arguments.get("surface_ref") or arguments.get("ref"))
        query = _required_text(arguments.get("query"), field="query", tool=name)
        limit = _bounded_int(arguments.get("limit"), default=5, low=1, high=50)
        artifact_path = _resolve_registered_surface_path(runtime, surface_ref)
        result = query_surface(artifact_path, query=query, limit=limit)
        return {"type": "result", "tool": name, "result": result.to_dict()}
    if name == "seam_surface_decode":
        surface_ref = _validated_hs_ref(arguments.get("surface_ref") or arguments.get("ref"))
        truncate_text = _bounded_int(arguments.get("truncate_text"), default=4096, low=0, high=65536)
        artifact_path = _resolve_registered_surface_path(runtime, surface_ref)
        payload = decode_surface(artifact_path)
        result = payload.to_dict(include_payload=False)
        if truncate_text > 0 and payload.payload_format in _TEXT_PAYLOAD_FORMATS:
            try:
                text = payload.text
            except UnicodeDecodeError:
                result["payload_text"] = None
                result["payload_text_truncated"] = False
                result["payload_text_error"] = "payload bytes are not valid UTF-8"
            else:
                result["payload_text"] = text[:truncate_text]
                result["payload_text_truncated"] = len(text) > truncate_text
        else:
            result["payload_text"] = None
            result["payload_text_truncated"] = False
        return {"type": "result", "tool": name, "result": result}
    if name == "seam_benchmark_latest":
        limit = _bounded_int(arguments.get("limit"), default=1, low=1, high=50)
        rows = runtime.list_benchmark_runs(limit=limit)
        return {"type": "result", "tool": name, "result": _paginated(rows, key="runs", limit=limit)}
    if name == "seam_surface_verify":
        surface_ref = _validated_hs_ref(arguments.get("surface_ref") or arguments.get("ref"))
        artifact_path = _resolve_registered_surface_path(runtime, surface_ref)
        result = verify_surface(artifact_path)
        return {"type": "result", "tool": name, "result": result.to_dict()}
    if name == "seam_surface_context":
        surface_ref = _validated_hs_ref(arguments.get("surface_ref") or arguments.get("ref"))
        query = _required_text(arguments.get("query"), field="query", tool=name)
        budget = _bounded_int(arguments.get("budget"), default=1200, low=1, high=65536)
        artifact_path = _resolve_registered_surface_path(runtime, surface_ref)
        result = context_surface(artifact_path, query=query, budget=budget)
        return {"type": "result", "tool": name, "result": result}
    if name == "seam_index_status":
        scope_arg = arguments.get("scope")
        limit = _bounded_int(arguments.get("limit"), default=100, low=1, high=500)
        batch = runtime.store.load_ir(scope=str(scope_arg) if isinstance(scope_arg, str) and scope_arg else None)
        indexable_count = sum(1 for record in batch.records if record.kind.value in {"CLM", "STA", "EVT", "REL"})
        stale_rows: list[dict[str, object]] = []
        inspector = getattr(runtime.vector_adapter, "stale_records", None)
        if inspector is not None:
            stale_rows = inspector(batch.records)
        stale_slice = stale_rows[:limit] if len(stale_rows) > limit else stale_rows
        return {
            "type": "result",
            "tool": name,
            "result": {
                "total_records": len(batch.records),
                "indexable_records": indexable_count,
                "stale_count": len(stale_rows),
                "stale_records": stale_slice,
                "stale_truncated": len(stale_rows) > limit,
            },
        }
    if name == "seam_retrieve":
        try:
            from seam_runtime.retrieval_orchestrator import RetrievalOrchestrator
        except ImportError:
            return {"type": "error", "tool": name, "error": "Retrieval orchestrator not available (seam_runtime.retrieval_orchestrator import failed)"}

        query = _required_text(arguments.get("query"), field="query", tool=name)
        scope_arg = arguments.get("scope")
        budget = _bounded_int(arguments.get("budget"), default=5, low=1, high=50)
        mode = str(arguments.get("mode") or "hybrid").strip()
        if mode not in {"vector", "graph", "hybrid", "mix"}:
            raise ValueError("mode must be one of ['vector', 'graph', 'hybrid', 'mix']")
        include_trace = bool(arguments.get("include_trace"))
        orchestrator = RetrievalOrchestrator(runtime)
        result = orchestrator.search(
            query=query,
            scope=str(scope_arg) if isinstance(scope_arg, str) and scope_arg else None,
            budget=budget,
            include_trace=include_trace,
            mode=mode,
        )
        return {"type": "result", "tool": name, "result": result.to_dict()}
    raise ValueError(f"Unknown SEAM MCP tool: {name!r}")


def _bounded_int(value: object, *, default: int, low: int, high: int) -> int:
    if value is None or value == "":
        return default
    try:
        coerced = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"expected integer in [{low}, {high}], got {value!r}") from exc
    return max(low, min(coerced, high))


def _required_text(value: object, *, field: str, tool: str) -> str:
    text = str(value or "")
    if not text.strip():
        raise ValueError(f"{field} is required for {tool}")
    return text if field == "text" else text.strip()


def _coerced_record_ids(value: object) -> list[str]:
    if isinstance(value, str):
        record_ids = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, list):
        record_ids = [str(item).strip() for item in value if str(item).strip()]
    else:
        record_ids = []
    if not record_ids:
        raise ValueError("ids are required for seam_memory_get")
    return record_ids


def _validated_pack_mode(value: object) -> str:
    mode = str(value or "context").strip()
    if mode not in _PACK_MODES:
        raise ValueError(f"mode must be one of {sorted(_PACK_MODES)}")
    return mode


def _paginated(rows: list[dict[str, object]], *, key: str, limit: int) -> dict[str, object]:
    return {
        key: rows,
        "count": len(rows),
        "limit": limit,
        "has_more": len(rows) >= limit,
    }


def _validated_hs_ref(value: object) -> str:
    ref = str(value or "").strip()
    if not ref:
        raise ValueError("surface_ref is required; canonical form is 'hs:<hex>' (use seam_surface_list to discover refs).")
    if not _HS_REF_PATTERN.match(ref):
        raise ValueError(
            f"Invalid surface_ref {ref!r}; canonical form is 'hs:<hex>'. "
            "MCP tools only accept canonical ids; file paths are rejected. Use seam_surface_list to discover registered surfaces."
        )
    return ref


def _resolve_registered_surface_path(runtime: SeamRuntime, surface_ref: str) -> Path:
    try:
        row = runtime.store.read_surface_artifact(surface_ref)
    except KeyError:
        raise KeyError(f"No registered surface for ref '{surface_ref}'. Use seam_surface_list to discover registered surfaces.")
    artifact_path = Path(str(row.get("artifact_path") or ""))
    if not artifact_path or not artifact_path.exists():
        raise FileNotFoundError(
            f"Surface '{surface_ref}' is registered but its artifact file is missing or unreadable. "
            "Use the SEAM CLI 'seam surface repair <ref>' to restore the redundant copy from source."
        )
    resolved = artifact_path.resolve(strict=False)
    allowed_root = Path(
        os.environ.get("SEAM_SURFACE_ROOT", Path(runtime.store.path).parent)
    ).resolve()
    try:
        resolved.relative_to(allowed_root)
    except ValueError:
        raise PermissionError(
            f"Surface artifact path {resolved} is outside the allowed root {allowed_root}. "
            "Set SEAM_SURFACE_ROOT to expand the allowed root if intentional."
        )
    return artifact_path


def _redact_doctor_report(report: dict[str, object]) -> dict[str, object]:
    safe = dict(report)
    pgvector = safe.get("pgvector")
    if isinstance(pgvector, dict) and "error" in pgvector:
        scrubbed = {key: value for key, value in pgvector.items() if key != "error"}
        scrubbed["error_redacted"] = True
        safe["pgvector"] = scrubbed
    return safe


def _write(output_stream: TextIO, payload: dict[str, object]) -> None:
    output_stream.write(json.dumps(payload, sort_keys=True) + "\n")
    output_stream.flush()


_EXTRA_DESCRIPTIONS = set(TOOL_DESCRIPTIONS) - set(TOOL_METADATA)
_EXTRA_METADATA = set(TOOL_METADATA) - set(TOOL_DESCRIPTIONS)
if _EXTRA_DESCRIPTIONS or _EXTRA_METADATA:
    import warnings
    _MISMATCH_MSG = (
        "SEAM MCP tool registry mismatch: "
        + (f"TOOL_DESCRIPTIONS keys missing from TOOL_METADATA: {sorted(_EXTRA_DESCRIPTIONS)}. " if _EXTRA_DESCRIPTIONS else "")
        + (f"TOOL_METADATA keys missing from TOOL_DESCRIPTIONS: {sorted(_EXTRA_METADATA)}." if _EXTRA_METADATA else "")
    ).rstrip()
    warnings.warn(_MISMATCH_MSG, RuntimeWarning, stacklevel=2)
