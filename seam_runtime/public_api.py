from __future__ import annotations

import hashlib
import hmac
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from .lifecycle import (
    LifecycleIdempotencyConflictError,
    LifecycleOperationPendingError,
    LifecycleStaleIncarnationError,
)
from .mirl import VALID_SCOPES, MIRLRecord, SearchCandidate
from .public_memory_handles import (
    PUBLIC_MEMORY_GENERATION_EXTENSION,
    PublicMemoryHandleStaleError,
)
from .runtime import SeamRuntime

PUBLIC_API_VERSION = "v1"
DEFAULT_NAMESPACE = "default"
DEFAULT_SCOPE = "thread"
MAX_MEMORY_TEXT_CHARS = 100_000
MAX_QUERY_CHARS = 4_096
MAX_CONTEXT_CHARS = 65_536
MAX_RECALL_LIMIT = 50
MAX_DELETE_IDS = 50

_DIMENSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MEMORY_ID_RE = re.compile(r"^mem_[0-9a-f]{24}$")
_TEXT_KEYS = ("content", "object", "summary", "label", "text")


class PublicAPIInputError(ValueError):
    """Raised when a public SDK request does not satisfy the v1 contract."""


class PublicAPINotFoundError(LookupError):
    """Raised when an opaque public resource is absent from the caller boundary."""


class PublicAPIConflictError(ValueError):
    """Raised when an idempotency key already names a different operation."""


@dataclass(frozen=True, slots=True)
class PublicPrincipal:
    """Stable caller identity supplied by an in-process authentication adapter."""

    subject: str

    def __post_init__(self) -> None:
        if not isinstance(self.subject, str) or not self.subject.strip():
            raise ValueError("principal subject must be a non-empty string")
        normalized = self.subject.strip()
        if len(normalized) > 512:
            raise ValueError("principal subject must be at most 512 characters")
        if "\0" in normalized:
            raise ValueError("principal subject must not contain NUL")
        object.__setattr__(self, "subject", normalized)


class PrincipalResolver(Protocol):
    """Authentication adapter used by the HTTP surface in principal mode."""

    def resolve_bearer(self, credential: str) -> PublicPrincipal | None:
        """Resolve a bearer credential without exposing it to the public API."""


class StaticPrincipalResolver:
    """Constant-time bearer resolver suitable for tests and injected hosting glue."""

    def __init__(self, credentials: Mapping[str, str | PublicPrincipal]) -> None:
        entries: list[tuple[bytes, PublicPrincipal]] = []
        for credential, principal in credentials.items():
            if not isinstance(credential, str) or not credential:
                raise ValueError("bearer credentials must be non-empty strings")
            resolved = (
                principal
                if isinstance(principal, PublicPrincipal)
                else PublicPrincipal(principal)
            )
            try:
                encoded_credential = credential.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ValueError("bearer credentials must be valid Unicode") from exc
            entries.append((encoded_credential, resolved))
        if not entries:
            raise ValueError("at least one principal credential is required")
        self._entries = tuple(entries)

    def resolve_bearer(self, credential: str) -> PublicPrincipal | None:
        try:
            supplied = credential.encode("utf-8")
        except UnicodeEncodeError:
            return None
        matched: PublicPrincipal | None = None
        for expected, principal in self._entries:
            if hmac.compare_digest(supplied, expected):
                matched = principal
        return matched


@dataclass(frozen=True)
class PublicMemoryQuery:
    query: str
    namespace: str
    scope: str
    session_id: str | None
    limit: int
    principal: PublicPrincipal | None

    @property
    def internal_namespace(self) -> str:
        return _internal_namespace(
            self.namespace,
            self.session_id,
            self.scope,
            principal=self.principal,
        )


def validate_memory_text(value: object) -> str:
    if value is not None and not isinstance(value, str):
        raise PublicAPIInputError("text must be a string")
    text = (value or "").strip()
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
    if not isinstance(value, str):
        raise PublicAPIInputError("agent_id must be a string")
    agent_id = value.strip()
    if not agent_id:
        return None
    if len(agent_id) > 128:
        raise PublicAPIInputError("agent_id must be at most 128 characters")
    if not _DIMENSION_RE.fullmatch(agent_id):
        raise PublicAPIInputError(
            "agent_id must use letters, numbers, dots, underscores, or hyphens"
        )
    return agent_id


def parse_memory_query(
    payload: dict[str, object],
    *,
    principal: PublicPrincipal | None = None,
) -> PublicMemoryQuery:
    raw_query = payload.get("query")
    if raw_query is not None and not isinstance(raw_query, str):
        raise PublicAPIInputError("query must be a string")
    query = (raw_query or "").strip()
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
        principal=principal,
    )


def remember(
    runtime: SeamRuntime,
    payload: dict[str, object],
    *,
    principal: PublicPrincipal | None = None,
) -> dict[str, object]:
    text = validate_memory_text(payload.get("text"))
    namespace = _validate_dimension(
        payload.get("namespace"), "namespace", DEFAULT_NAMESPACE
    )
    scope = _validate_scope(payload.get("scope"))
    session_id = _validate_optional_dimension(payload.get("session_id"), "session_id")
    agent_id = validate_agent_id(payload.get("agent_id"))
    receipt_id = f"rcpt_{uuid.uuid4().hex}"
    internal_namespace = _internal_namespace(
        namespace,
        session_id,
        scope,
        principal=principal,
    )
    batch = runtime.compile_nl(
        text,
        source_ref=f"sdk://memory/{receipt_id}",
        ns=internal_namespace,
        scope=scope,
        agent_id=agent_id,
        id_salt=internal_namespace if principal else None,
    )
    if principal is not None:
        generation = _public_memory_generation(receipt_id)
        for record in batch.records:
            record.ext[PUBLIC_MEMORY_GENERATION_EXTENSION] = generation
    try:
        runtime.persist_ir(batch)
    except LifecycleOperationPendingError as exc:
        raise PublicAPIConflictError("memory deletion is still pending") from exc
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
    *,
    principal: PublicPrincipal | None = None,
    public_id_key: bytes | None = None,
) -> dict[str, object]:
    request = parse_memory_query(payload, principal=principal)
    result = runtime.search_ir(
        query=request.query,
        ns=request.internal_namespace,
        scope=request.scope,
        budget=request.limit,
        lens="general",
    )
    memories = _public_memories(
        runtime,
        result.candidates,
        limit=request.limit,
        namespace=request.internal_namespace,
        scope=request.scope,
        principal=principal,
        public_id_key=public_id_key,
    )
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
    *,
    principal: PublicPrincipal | None = None,
    public_id_key: bytes | None = None,
) -> dict[str, object]:
    request = parse_memory_query(payload, principal=principal)
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
    memories = _public_memories(
        runtime,
        result.candidates,
        limit=request.limit,
        namespace=request.internal_namespace,
        scope=request.scope,
        principal=principal,
        public_id_key=public_id_key,
    )
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


def delete(
    runtime: SeamRuntime,
    payload: dict[str, object],
    *,
    principal: PublicPrincipal | None = None,
    public_id_key: bytes | None = None,
) -> dict[str, object]:
    """Delete opaque memory handles through the canonical lifecycle engine."""

    memory_ids = _validate_memory_ids(payload.get("memory_ids"))
    namespace = _validate_dimension(
        payload.get("namespace"), "namespace", DEFAULT_NAMESPACE
    )
    scope = _validate_scope(payload.get("scope"))
    session_id = _validate_optional_dimension(payload.get("session_id"), "session_id")
    idempotency_key = _validate_idempotency_key(payload.get("idempotency_key"))
    internal_namespace = _internal_namespace(
        namespace,
        session_id,
        scope,
        principal=principal,
    )
    tenant_id = _tenant_id(principal)
    actor = _principal_actor(principal)
    idempotency_context = _delete_idempotency_context(memory_ids)
    operation = runtime.store.lifecycle_operation_by_idempotency_key(
        tenant_id=tenant_id,
        idempotency_key=idempotency_key,
    )
    if operation is not None:
        payload_details = operation.get("payload")
        if (
            operation.get("kind") != "scoped_delete"
            or operation.get("namespace") != internal_namespace
            or operation.get("scope") != scope
            or not isinstance(payload_details, dict)
            or payload_details.get("idempotency_context") != idempotency_context
        ):
            raise PublicAPIConflictError(
                "idempotency_key already names a different deletion"
            )
        if not runtime.store.scoped_delete_retry_matches_current_incarnation(
            tenant_id=tenant_id,
            operation_id=str(operation["operation_id"]),
        ):
            raise PublicAPINotFoundError("memory not found")
    else:
        resolved_memories = _resolve_memory_ids(
            runtime,
            memory_ids,
            namespace=internal_namespace,
            scope=scope,
            principal=principal,
        )
        record_ids = [record_id for record_id, _generation in resolved_memories]
        record_generations = {
            record_id: generation for record_id, generation in resolved_memories
        }
        if len(record_generations) != len(record_ids):
            raise PublicAPIInputError("memory_ids must name distinct memories")
        try:
            operation = runtime.plan_scoped_delete(
                tenant_id=tenant_id,
                namespace=internal_namespace,
                scope=scope,
                record_ids=record_ids,
                idempotency_key=idempotency_key,
                actor=actor,
                idempotency_context=idempotency_context,
                record_generations=record_generations,
            )
        except LifecycleIdempotencyConflictError as exc:
            raise PublicAPIConflictError(
                "idempotency_key already names a different deletion"
            ) from exc
    try:
        applied = runtime.apply_scoped_delete(
            tenant_id=tenant_id,
            operation_id=str(operation["operation_id"]),
            actor=actor,
            require_current_incarnation=True,
        )
    except LifecycleStaleIncarnationError as exc:
        raise PublicAPINotFoundError("memory not found") from exc
    except Exception as exc:
        # The lifecycle engine commits canonical soft-delete + the recoverable
        # cleanup intent before calling external derived-index adapters. If an
        # adapter fails, report the bounded pending state without exposing the
        # internal operation or losing the original exception for other cases.
        try:
            pending = runtime.store.lifecycle_operation(
                tenant_id=tenant_id,
                operation_id=str(operation["operation_id"]),
            )
        except Exception:
            raise exc
        if pending["state"] == "refused":
            raise PublicAPINotFoundError("memory not found") from exc
        if pending["state"] != "cleanup_pending":
            raise
        applied = pending
    state = str(applied["state"])
    if state == "refused":
        raise PublicAPINotFoundError("memory not found")
    if state not in {"applied", "cleanup_pending"}:
        raise RuntimeError("public deletion reached an unsupported lifecycle state")
    return {
        "api_version": PUBLIC_API_VERSION,
        "accepted": True,
        "deletion_id": _opaque_delete_id(
            str(applied["operation_id"]),
            principal=principal,
        ),
        "status": "deleted" if state == "applied" else "pending",
        "namespace": namespace,
        "scope": scope,
        "session_id": session_id,
    }


def _validate_dimension(value: object, name: str, default: str) -> str:
    if value is None:
        resolved = default
    elif not isinstance(value, str):
        raise PublicAPIInputError(f"{name} must be a string")
    else:
        resolved = value.strip()
    if not resolved:
        raise PublicAPIInputError(f"{name} must be non-empty")
    if len(resolved) > 128:
        raise PublicAPIInputError(f"{name} must be at most 128 characters")
    if not resolved[0].isalnum() or not resolved[0].isascii():
        raise PublicAPIInputError(f"{name} must start with a letter or number")
    if not _DIMENSION_RE.fullmatch(resolved):
        raise PublicAPIInputError(
            f"{name} must use letters, numbers, dots, underscores, or hyphens"
        )
    return resolved


def _validate_optional_dimension(value: object, name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PublicAPIInputError(f"{name} must be a string")
    resolved = value.strip()
    if not resolved:
        return None
    return _validate_dimension(resolved, name, resolved)


def _validate_scope(value: object) -> str:
    if value is None:
        resolved = DEFAULT_SCOPE
    elif not isinstance(value, str):
        raise PublicAPIInputError("scope must be a string")
    else:
        resolved = value.strip()
    if resolved not in VALID_SCOPES:
        allowed = ", ".join(sorted(VALID_SCOPES))
        raise PublicAPIInputError(f"scope must be one of: {allowed}")
    return resolved


def _validate_memory_ids(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PublicAPIInputError("memory_ids must be a list")
    if not value:
        raise PublicAPIInputError("memory_ids must contain at least one id")
    if len(value) > MAX_DELETE_IDS:
        raise PublicAPIInputError(
            f"memory_ids must contain at most {MAX_DELETE_IDS} ids"
        )
    resolved: list[str] = []
    for memory_id in value:
        if not isinstance(memory_id, str) or not _MEMORY_ID_RE.fullmatch(memory_id):
            raise PublicAPIInputError("memory_ids must contain opaque mem_ ids")
        if memory_id in resolved:
            raise PublicAPIInputError("memory_ids must contain unique ids")
        resolved.append(memory_id)
    return tuple(resolved)


def _validate_idempotency_key(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PublicAPIInputError("idempotency_key is required")
    resolved = value.strip()
    if len(resolved) > 128:
        raise PublicAPIInputError("idempotency_key must be at most 128 characters")
    if not _DIMENSION_RE.fullmatch(resolved):
        raise PublicAPIInputError(
            "idempotency_key must use letters, numbers, dots, underscores, or hyphens"
        )
    return resolved


def _tenant_id(principal: PublicPrincipal | None) -> str:
    if principal is None:
        return "sdk"
    digest = hashlib.sha256(principal.subject.encode("utf-8")).hexdigest()
    return f"principal:{digest}"


def _principal_actor(principal: PublicPrincipal | None) -> str:
    if principal is None:
        return "public-api"
    return f"public-api:{hashlib.sha256(principal.subject.encode('utf-8')).hexdigest()}"


def _internal_namespace(
    namespace: str,
    session_id: str | None,
    scope: str,
    *,
    principal: PublicPrincipal | None = None,
) -> str:
    if principal is None:
        resolved = f"sdk.{namespace}"
        if session_id:
            digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
            resolved = f"{resolved}.session-{digest}"
        return resolved

    # Canonical JSON binds every caller-selectable boundary dimension without
    # delimiter ambiguity. The full digest keeps the internal namespace bounded
    # while preserving a 256-bit collision barrier; caller labels remain echoed
    # separately in public responses.
    boundary_material = json.dumps(
        {
            "contract": "principal-memory-boundary/1",
            "namespace": namespace,
            "scope": scope,
            "session_id": session_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    boundary_digest = hashlib.sha256(boundary_material).hexdigest()
    return f"{_tenant_id(principal)}.sdk.boundary-{boundary_digest}"


def _public_memories(
    runtime: SeamRuntime,
    candidates: list[SearchCandidate],
    *,
    limit: int,
    namespace: str,
    scope: str,
    principal: PublicPrincipal | None = None,
    public_id_key: bytes | None = None,
) -> list[dict[str, object]]:
    memories: list[dict[str, object]] = []
    handles: dict[str, tuple[str, str]] = {}
    seen_text: set[str] = set()
    for candidate in candidates:
        text = _candidate_text(candidate)
        if not text or text in seen_text:
            continue
        seen_text.add(text)
        generation = candidate.record.ext.get(
            PUBLIC_MEMORY_GENERATION_EXTENSION
        )
        memory_id = _opaque_memory_id(
            candidate.record.id,
            principal=principal,
            public_id_key=public_id_key,
            generation=generation,
        )
        if principal is not None:
            if not isinstance(generation, str):
                raise RuntimeError(
                    "principal memory record is missing its generation"
                )
            handles[memory_id] = (candidate.record.id, generation)
        memories.append(
            {
                "id": memory_id,
                "text": text,
                "score": round(float(candidate.score), 6),
                "created_at": candidate.record.created_at,
            }
        )
        if len(memories) >= limit:
            break
    if principal is not None:
        try:
            runtime.register_public_memory_handles(
                tenant_id=_tenant_id(principal),
                namespace=namespace,
                scope=scope,
                handles=handles,
            )
        except PublicMemoryHandleStaleError as exc:
            raise PublicAPIConflictError(
                "memory changed during recall; retry"
            ) from exc
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


def _resolve_memory_ids(
    runtime: SeamRuntime,
    memory_ids: tuple[str, ...],
    *,
    namespace: str,
    scope: str,
    principal: PublicPrincipal | None,
) -> list[tuple[str, str]]:
    resolved = runtime.store.resolve_public_memory_handles(
        tenant_id=_tenant_id(principal),
        namespace=namespace,
        scope=scope,
        handle_ids=memory_ids,
    )
    if set(resolved) != set(memory_ids):
        raise PublicAPINotFoundError("memory not found")
    return [resolved[memory_id] for memory_id in memory_ids]


def _opaque_memory_id(
    record_id: str,
    *,
    principal: PublicPrincipal | None = None,
    public_id_key: bytes | None = None,
    generation: object = None,
) -> str:
    if principal is None:
        # Preserve the public v1 self-host handle byte-for-byte.
        material = f"seam-public-memory-v1\0{record_id}".encode("utf-8")
        digest = hashlib.sha256(material).hexdigest()[:24]
    else:
        if not isinstance(generation, str) or not generation.strip():
            raise RuntimeError("principal memory record is missing its generation")
        material = json.dumps(
            {
                "contract": "principal-memory-handle/1",
                "generation": generation,
                "record_id": record_id,
                "tenant_id": _tenant_id(principal),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hmac.new(
            _required_public_id_key(public_id_key),
            material,
            hashlib.sha256,
        ).hexdigest()[:24]
    return f"mem_{digest}"


def _public_memory_generation(receipt_id: str) -> str:
    material = json.dumps(
        {
            "contract": "principal-memory-generation/1",
            "receipt_id": receipt_id,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _delete_idempotency_context(memory_ids: tuple[str, ...]) -> str:
    material = json.dumps(
        {
            "contract": "principal-delete-idempotency/1",
            "memory_ids": sorted(memory_ids),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _opaque_delete_id(
    operation_id: str,
    *,
    principal: PublicPrincipal | None,
) -> str:
    material = f"seam-public-delete-v1\0{_tenant_id(principal)}\0{operation_id}".encode(
        "utf-8"
    )
    if principal is None:
        digest = hashlib.sha256(material).hexdigest()[:24]
    else:
        # A deletion receipt is not a capability. Hash the already-opaque,
        # tenant-bound lifecycle identity so retries remain stable across public
        # handle-key rotation without exposing the internal operation id.
        digest = hashlib.sha256(material).hexdigest()[:24]
    return f"del_{digest}"


def _required_public_id_key(public_id_key: bytes | None) -> bytes:
    if not isinstance(public_id_key, bytes) or len(public_id_key) < 32:
        raise RuntimeError(
            "principal mode requires a stable public ID key of at least 32 bytes"
        )
    return public_id_key
