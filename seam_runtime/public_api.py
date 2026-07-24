from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass

from .mirl import VALID_SCOPES, MIRLRecord, SearchCandidate
from .runtime import SeamRuntime

PUBLIC_API_VERSION = "v1"
DEFAULT_NAMESPACE = "default"
DEFAULT_SCOPE = "thread"
MAX_MEMORY_TEXT_CHARS = 100_000
MAX_QUERY_CHARS = 4_096
MAX_CONTEXT_CHARS = 65_536
MAX_RECALL_LIMIT = 50

_DIMENSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TEXT_KEYS = ("content", "object", "summary", "label", "text")


class PublicAPIInputError(ValueError):
    """Raised when a public SDK request does not satisfy the v1 contract."""


@dataclass(frozen=True)
class PublicMemoryQuery:
    query: str
    namespace: str
    scope: str
    session_id: str | None
    limit: int

    @property
    def internal_namespace(self) -> str:
        return _internal_namespace(self.namespace, self.session_id)


def validate_memory_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        raise PublicAPIInputError("text is required")
    if len(text) > MAX_MEMORY_TEXT_CHARS:
        raise PublicAPIInputError(
            f"text exceeds {MAX_MEMORY_TEXT_CHARS} characters"
        )
    return text


def validate_agent_id(value: object) -> str | None:
    if value is None:
        return None
    agent_id = str(value).strip()
    if not agent_id:
        return None
    if not _DIMENSION_RE.fullmatch(agent_id):
        raise PublicAPIInputError(
            "agent_id must use letters, numbers, dots, underscores, or hyphens"
        )
    return agent_id


def parse_memory_query(payload: dict[str, object]) -> PublicMemoryQuery:
    query = str(payload.get("query") or "").strip()
    if not query:
        raise PublicAPIInputError("query is required")
    if len(query) > MAX_QUERY_CHARS:
        raise PublicAPIInputError(f"query exceeds {MAX_QUERY_CHARS} characters")
    namespace = _validate_dimension(
        payload.get("namespace"), "namespace", DEFAULT_NAMESPACE
    )
    scope = _validate_scope(payload.get("scope"))
    session_id = _validate_optional_dimension(payload.get("session_id"), "session_id")
    raw_limit = payload.get("limit", 5)
    if isinstance(raw_limit, bool):
        raise PublicAPIInputError("limit must be an integer")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError) as exc:
        raise PublicAPIInputError("limit must be an integer") from exc
    if not 1 <= limit <= MAX_RECALL_LIMIT:
        raise PublicAPIInputError(
            f"limit must be between 1 and {MAX_RECALL_LIMIT}"
        )
    return PublicMemoryQuery(
        query=query,
        namespace=namespace,
        scope=scope,
        session_id=session_id,
        limit=limit,
    )


def remember(
    runtime: SeamRuntime,
    payload: dict[str, object],
) -> dict[str, object]:
    text = validate_memory_text(payload.get("text"))
    namespace = _validate_dimension(
        payload.get("namespace"), "namespace", DEFAULT_NAMESPACE
    )
    scope = _validate_scope(payload.get("scope"))
    session_id = _validate_optional_dimension(payload.get("session_id"), "session_id")
    agent_id = validate_agent_id(payload.get("agent_id"))
    receipt_id = f"rcpt_{uuid.uuid4().hex}"
    batch = runtime.compile_nl(
        text,
        source_ref=f"sdk://memory/{receipt_id}",
        ns=_internal_namespace(namespace, session_id),
        scope=scope,
        agent_id=agent_id,
    )
    runtime.persist_ir(batch)
    return {
        "api_version": PUBLIC_API_VERSION,
        "accepted": True,
        "receipt_id": receipt_id,
        "memory_count": 1,
        "namespace": namespace,
        "scope": scope,
        "session_id": session_id,
    }


def recall(
    runtime: SeamRuntime,
    payload: dict[str, object],
) -> dict[str, object]:
    request = parse_memory_query(payload)
    result = runtime.search_ir(
        query=request.query,
        ns=request.internal_namespace,
        scope=request.scope,
        budget=request.limit,
        lens="general",
    )
    memories = _public_memories(result.candidates, limit=request.limit)
    return {
        "api_version": PUBLIC_API_VERSION,
        "query": request.query,
        "namespace": request.namespace,
        "scope": request.scope,
        "session_id": request.session_id,
        "memories": memories,
    }


def context(
    runtime: SeamRuntime,
    payload: dict[str, object],
) -> dict[str, object]:
    request = parse_memory_query(payload)
    raw_max_chars = payload.get("max_chars", 8_000)
    if isinstance(raw_max_chars, bool):
        raise PublicAPIInputError("max_chars must be an integer")
    try:
        max_chars = int(raw_max_chars)
    except (TypeError, ValueError) as exc:
        raise PublicAPIInputError("max_chars must be an integer") from exc
    if not 1 <= max_chars <= MAX_CONTEXT_CHARS:
        raise PublicAPIInputError(
            f"max_chars must be between 1 and {MAX_CONTEXT_CHARS}"
        )

    result = runtime.search_ir(
        query=request.query,
        ns=request.internal_namespace,
        scope=request.scope,
        budget=request.limit,
        lens="general",
    )
    memories = _public_memories(result.candidates, limit=request.limit)
    lines: list[str] = []
    used = 0
    for memory in memories:
        line = f"- {memory['text']}"
        separator = "\n" if lines else ""
        remaining = max_chars - used - len(separator)
        if remaining <= 0:
            break
        if len(line) > remaining:
            line = line[:remaining].rstrip()
        if line:
            lines.append(line)
            used += len(separator) + len(line)
        if used >= max_chars:
            break
    return {
        "api_version": PUBLIC_API_VERSION,
        "query": request.query,
        "namespace": request.namespace,
        "scope": request.scope,
        "session_id": request.session_id,
        "context": "\n".join(lines),
        "memories": memories,
    }


def _validate_dimension(value: object, name: str, default: str) -> str:
    resolved = default if value is None else str(value).strip()
    if not resolved:
        raise PublicAPIInputError(f"{name} must be non-empty")
    if not _DIMENSION_RE.fullmatch(resolved):
        raise PublicAPIInputError(
            f"{name} must use letters, numbers, dots, underscores, or hyphens"
        )
    return resolved


def _validate_optional_dimension(value: object, name: str) -> str | None:
    if value is None:
        return None
    resolved = str(value).strip()
    if not resolved:
        return None
    return _validate_dimension(resolved, name, resolved)


def _validate_scope(value: object) -> str:
    resolved = DEFAULT_SCOPE if value is None else str(value).strip()
    if resolved not in VALID_SCOPES:
        allowed = ", ".join(sorted(VALID_SCOPES))
        raise PublicAPIInputError(f"scope must be one of: {allowed}")
    return resolved


def _internal_namespace(namespace: str, session_id: str | None) -> str:
    resolved = f"sdk.{namespace}"
    if session_id:
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
        resolved = f"{resolved}.session-{digest}"
    return resolved


def _public_memories(
    candidates: list[SearchCandidate],
    *,
    limit: int,
) -> list[dict[str, object]]:
    memories: list[dict[str, object]] = []
    seen_text: set[str] = set()
    for candidate in candidates:
        text = _candidate_text(candidate)
        if not text or text in seen_text:
            continue
        seen_text.add(text)
        memories.append(
            {
                "id": _opaque_memory_id(candidate.record.id),
                "text": text,
                "score": round(float(candidate.score), 6),
                "created_at": candidate.record.created_at,
            }
        )
        if len(memories) >= limit:
            break
    return memories


def _candidate_text(candidate: SearchCandidate) -> str:
    records = [candidate.record, *candidate.evidence]
    for record in records:
        text = _record_text(record)
        if text:
            return text
    return ""


def _record_text(record: MIRLRecord) -> str:
    for key in _TEXT_KEYS:
        value = record.attrs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:4_000]
    return ""


def _opaque_memory_id(record_id: str) -> str:
    digest = hashlib.sha256(
        f"seam-public-memory-v1\0{record_id}".encode("utf-8")
    ).hexdigest()[:24]
    return f"mem_{digest}"
