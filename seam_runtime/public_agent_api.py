"""Opaque public agent-turn lifecycle over the private SEAM SDK.

This module is an HTTP boundary adapter, not a second memory engine.  Every
operation delegates to :mod:`seam_runtime.sdk`; callers receive only bounded
text and opaque handles, never MIRL records, graph rows, or retrieval internals.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Sequence

from .mirl import SearchCandidate
from .public_api import (
    PUBLIC_API_VERSION,
    PublicAPIConflictError,
    PublicAPIInputError,
    PublicAPINotFoundError,
    PublicPrincipal,
    _public_memories,
    _public_memory_generation,
    parse_memory_query,
    validate_agent_id,
)
from .public_memory_handles import PUBLIC_MEMORY_GENERATION_EXTENSION
from .runtime import SeamRuntime
from .sdk import ReasoningSession, SeamSDK

MAX_ATTEMPTS = 64
MAX_TURN_VERIFICATIONS = 64
MAX_TOOL_RESULT_CHARS = 200_000
MAX_TURN_TEXT_CHARS = 100_000
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_TURN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$")
MEMORY_ADMISSION_DECISIONS = frozenset({"admit", "reject", "review"})
MEMORY_ADMISSION_KINDS = frozenset(
    {
        "conversation",
        "decision",
        "event",
        "none",
        "preference",
        "procedure",
        "project_fact",
        "task_state",
    }
)


def begin_turn(
    runtime: SeamRuntime,
    payload: dict[str, object],
    *,
    principal: PublicPrincipal | None = None,
    public_id_key: bytes | None = None,
) -> dict[str, object]:
    """Open and record one bounded retrieval before an agent executes."""

    request = parse_memory_query(payload, principal=principal)
    graph_hops = _bounded_int(payload.get("graph_hops", 2), "graph_hops", 0, 3)
    agent_id = validate_agent_id(payload.get("agent_id"))
    model = _optional_text(payload.get("model"), "model", maximum=256)
    provider = _optional_text(payload.get("provider"), "provider", maximum=128)

    session = SeamSDK(runtime=runtime).start_reasoning(
        request.query,
        ns=request.internal_namespace,
        scope=request.scope,
        agent_id=agent_id,
        model=model,
        provider=provider,
        recommend_patterns=False,
    )
    retrieved = session.retrieve(
        request.query,
        budget=request.limit,
        mode="mix",
        graph_hops=graph_hops,
        graph_include_history=request.view == "history",
    )
    memories = _public_memories(
        runtime,
        [
            SearchCandidate(
                record=candidate.record,
                score=candidate.score,
                reasons=list(candidate.reasons),
            )
            for candidate in retrieved.result.selected
        ],
        limit=request.limit,
        namespace=request.internal_namespace,
        scope=request.scope,
        principal=principal,
        public_id_key=public_id_key,
        register_handles=request.view == "current",
    )
    return {
        "api_version": PUBLIC_API_VERSION,
        "turn_id": session.run_id,
        "namespace": request.namespace,
        "scope": request.scope,
        "session_id": request.session_id,
        "workspace": request.workspace,
        "project": request.project,
        "view": request.view,
        "memories": memories,
    }


def record_actions(
    runtime: SeamRuntime,
    payload: dict[str, object],
    *,
    principal: PublicPrincipal | None = None,
) -> dict[str, object]:
    """Record bounded tool decisions and content-free verification results."""

    with runtime._persist_projection_lock:
        return _record_actions_locked(runtime, payload, principal=principal)


def _record_actions_locked(
    runtime: SeamRuntime,
    payload: dict[str, object],
    *,
    principal: PublicPrincipal | None,
) -> dict[str, object]:

    session = _authorized_session(runtime, payload, principal=principal)
    if _terminal_outcome(session) is not None:
        raise PublicAPIConflictError("turn is already finalized")
    attempts = payload.get("attempts")
    if not isinstance(attempts, list):
        raise PublicAPIInputError("attempts must be a list")
    if len(attempts) > MAX_ATTEMPTS:
        raise PublicAPIInputError(f"attempts must contain at most {MAX_ATTEMPTS} items")
    existing_verifications = session.verifications(limit=MAX_TURN_VERIFICATIONS)
    if len(existing_verifications) + len(attempts) > MAX_TURN_VERIFICATIONS:
        raise PublicAPIConflictError(
            f"turns support at most {MAX_TURN_VERIFICATIONS} tool verifications"
        )

    verification_ids: list[str] = []
    passed_ids: list[str] = []
    for attempt in attempts:
        if not isinstance(attempt, dict):
            raise PublicAPIInputError("each attempt must be an object")
        name = _required_name(attempt.get("name"), "attempt name")
        request = _required_text(attempt.get("request"), "attempt request", maximum=500)
        output = _optional_raw_text(
            attempt.get("output"),
            "attempt output",
            maximum=MAX_TOOL_RESULT_CHARS,
        )
        ok = attempt.get("ok", True)
        if not isinstance(ok, bool):
            raise PublicAPIInputError("attempt ok must be a boolean")
        exit_code = _optional_int(attempt.get("exit_code"), "attempt exit_code")
        duration_ms = _optional_number(
            attempt.get("duration_ms"), "attempt duration_ms", minimum=0.0
        )

        decision = session.add_node(
            "decision",
            f"{name}: {request}"[:500],
            operation=name,
        )
        verification = session.verify(
            str(decision["node_id"]),
            check_kind="tool",
            check_ref=name,
            verdict="passed" if ok else "failed",
            summary=f"{name} {'completed' if ok else 'failed'}"[:500],
            result=output,
            exit_code=exit_code,
            duration_ms=duration_ms,
        )
        verification_id = str(verification["verification_id"])
        verification_ids.append(verification_id)
        if ok:
            passed_ids.append(verification_id)

    return {
        "api_version": PUBLIC_API_VERSION,
        "turn_id": session.run_id,
        "verification_ids": verification_ids,
        "passed_verification_ids": passed_ids,
    }


def complete_turn(
    runtime: SeamRuntime,
    payload: dict[str, object],
    *,
    principal: PublicPrincipal | None = None,
) -> dict[str, object]:
    """Persist a completed exchange and accept its supported outcome."""

    with runtime._persist_projection_lock:
        return _complete_turn_locked(runtime, payload, principal=principal)


def _complete_turn_locked(
    runtime: SeamRuntime,
    payload: dict[str, object],
    *,
    principal: PublicPrincipal | None,
) -> dict[str, object]:

    session = _authorized_session(runtime, payload, principal=principal)
    terminal = _terminal_outcome(session)
    if terminal is not None:
        if terminal.get("status") != "accepted":
            raise PublicAPIConflictError("turn is already finalized as failed")
        knowledge_refs = terminal.get("knowledge_refs") or []
        stored_count = len(knowledge_refs) if isinstance(knowledge_refs, list) else 0
        return _completion_receipt(
            session.run_id,
            stored_count=stored_count,
            replayed=True,
            admission=_stored_memory_admission(session),
        )

    user_input = _required_text(
        payload.get("user_input"), "user_input", maximum=MAX_TURN_TEXT_CHARS
    )
    assistant_output = _required_text(
        payload.get("assistant_output"),
        "assistant_output",
        maximum=MAX_TURN_TEXT_CHARS,
    )
    admission = _parse_memory_admission(payload.get("memory_admission"))
    admission_node = session.add_node(
        "decision",
        _memory_admission_summary(admission),
        operation="memory_admission",
    )
    source_digest = hashlib.sha256(
        f"public-agent-turn/1\0{session.run_id}".encode("utf-8")
    ).hexdigest()[:24]
    receipt_id = _agent_receipt_id(session.run_id)
    knowledge_refs: tuple[str, ...] = ()
    if admission["decision"] == "admit":
        batch = runtime.compile_nl(
            f"User: {user_input}\nGhost: {assistant_output}",
            source_ref=f"sdk://agent-turn/{source_digest}",
            ns=session.ns,
            scope=session.scope,
            agent_id=session.agent_id if isinstance(session.agent_id, str) else None,
            id_salt=session.ns if principal is not None else None,
        )
        if principal is not None:
            generation = _public_memory_generation(receipt_id)
            for record in batch.records:
                record.ext[PUBLIC_MEMORY_GENERATION_EXTENSION] = generation
        report = runtime.persist_ir(batch)
        knowledge_refs = tuple(str(record_id) for record_id in report.stored_ids)
    evidence_refs = _selected_evidence_refs(session)
    passed_ids = tuple(
        str(item["verification_id"])
        for item in session.verifications(limit=MAX_TURN_VERIFICATIONS)
        if item.get("verdict") == "passed"
    )
    if passed_ids:
        session.finalize_verified(
            "Ghost completed the user turn with verified actions.",
            verification_ids=passed_ids,
            evidence_refs=evidence_refs,
            knowledge_refs=knowledge_refs,
            supporting_node_ids=(str(admission_node["node_id"]),),
        )
    else:
        session.finalize(
            "Ghost completed the user turn.",
            evidence_refs=evidence_refs,
            knowledge_refs=knowledge_refs,
            supporting_node_ids=(str(admission_node["node_id"]),),
        )
    return _completion_receipt(
        session.run_id,
        stored_count=len(knowledge_refs),
        replayed=False,
        admission=admission,
    )


def fail_turn(
    runtime: SeamRuntime,
    payload: dict[str, object],
    *,
    principal: PublicPrincipal | None = None,
) -> dict[str, object]:
    """Reject a failed turn without compiling it into durable memory."""

    with runtime._persist_projection_lock:
        return _fail_turn_locked(runtime, payload, principal=principal)


def _fail_turn_locked(
    runtime: SeamRuntime,
    payload: dict[str, object],
    *,
    principal: PublicPrincipal | None,
) -> dict[str, object]:

    session = _authorized_session(runtime, payload, principal=principal)
    terminal = _terminal_outcome(session)
    if terminal is not None:
        return {
            "api_version": PUBLIC_API_VERSION,
            "turn_id": session.run_id,
            "status": str(terminal.get("status") or "unknown"),
            "replayed": True,
        }
    error_type = _required_name(payload.get("error_type"), "error_type")
    outcome = session.add_node(
        "outcome",
        f"Ghost did not complete the turn ({error_type}).",
    )
    session.transition(
        str(outcome["node_id"]),
        "rejected",
        reason="public agent turn failed",
    )
    return {
        "api_version": PUBLIC_API_VERSION,
        "turn_id": session.run_id,
        "status": "rejected",
        "replayed": False,
    }


def _authorized_session(
    runtime: SeamRuntime,
    payload: dict[str, object],
    *,
    principal: PublicPrincipal | None,
) -> ReasoningSession:
    turn_id = _required_text(payload.get("turn_id"), "turn_id", maximum=128)
    if not _TURN_ID_RE.fullmatch(turn_id):
        raise PublicAPIInputError("turn_id is not a valid opaque turn handle")
    request = parse_memory_query(
        {**payload, "query": payload.get("query") or "authorize turn"},
        principal=principal,
    )
    try:
        session = SeamSDK(runtime=runtime).reasoning(turn_id)
    except (KeyError, ValueError) as exc:
        raise PublicAPINotFoundError("turn not found") from exc
    if session.ns != request.internal_namespace or session.scope != request.scope:
        raise PublicAPINotFoundError("turn not found")
    return session


def _selected_evidence_refs(session: ReasoningSession) -> tuple[str, ...]:
    selected: list[str] = []
    for retrieval in session.retrievals(limit=8, include_candidates=True):
        for candidate in retrieval.get("candidates") or []:
            if isinstance(candidate, dict) and candidate.get("selected"):
                record_id = str(candidate.get("record_id") or "")
                if record_id and record_id not in selected:
                    selected.append(record_id)
    return tuple(selected)


def _terminal_outcome(session: ReasoningSession) -> dict[str, object] | None:
    graph = session.graph()
    outcomes = [
        node
        for node in graph.get("nodes") or []
        if isinstance(node, dict)
        and node.get("kind") == "outcome"
        and node.get("status") in {"accepted", "rejected"}
    ]
    return outcomes[-1] if outcomes else None


def _completion_receipt(
    turn_id: str,
    *,
    stored_count: int,
    replayed: bool,
    admission: dict[str, str],
) -> dict[str, object]:
    return {
        "api_version": PUBLIC_API_VERSION,
        "turn_id": turn_id,
        "accepted": True,
        "receipt_id": _agent_receipt_id(turn_id),
        "memory_count": stored_count,
        "memory_admission": admission,
        "replayed": replayed,
    }


def _parse_memory_admission(value: object) -> dict[str, str]:
    if value is None:
        return {
            "decision": "admit",
            "kind": "conversation",
            "reason_code": "legacy_auto",
        }
    if not isinstance(value, dict):
        raise PublicAPIInputError("memory_admission must be an object")
    unknown = set(value) - {"decision", "kind", "reason_code"}
    if unknown:
        raise PublicAPIInputError(
            "memory_admission contains unsupported fields: "
            + ", ".join(sorted(unknown))
        )
    decision = _required_name(value.get("decision"), "memory_admission decision").lower()
    kind = _required_name(value.get("kind"), "memory_admission kind").lower()
    reason_code = _required_name(
        value.get("reason_code"), "memory_admission reason_code"
    ).lower()
    if decision not in MEMORY_ADMISSION_DECISIONS:
        raise PublicAPIInputError(
            "memory_admission decision must be admit, reject, or review"
        )
    if kind not in MEMORY_ADMISSION_KINDS:
        raise PublicAPIInputError(
            "memory_admission kind must be conversation, decision, event, none, "
            "preference, procedure, project_fact, or task_state"
        )
    if decision == "admit" and kind == "none":
        raise PublicAPIInputError("admitted memory must have a durable kind")
    if decision != "admit" and kind != "none":
        raise PublicAPIInputError("rejected or review memory must use kind none")
    return {"decision": decision, "kind": kind, "reason_code": reason_code}


def _memory_admission_summary(admission: dict[str, str]) -> str:
    return "memory_admission:{decision}:{kind}:{reason_code}".format(**admission)


def _stored_memory_admission(session: ReasoningSession) -> dict[str, str]:
    decisions = [
        node
        for node in session.graph().get("nodes") or []
        if isinstance(node, dict)
        and node.get("kind") == "decision"
        and node.get("operation") == "memory_admission"
    ]
    if not decisions:
        return {
            "decision": "admit",
            "kind": "conversation",
            "reason_code": "legacy_auto",
        }
    summary = str(decisions[-1].get("summary") or "")
    parts = summary.split(":", 3)
    if len(parts) != 4 or parts[0] != "memory_admission":
        raise RuntimeError("stored memory admission decision is malformed")
    return {"decision": parts[1], "kind": parts[2], "reason_code": parts[3]}


def _required_name(value: object, name: str) -> str:
    text = _required_text(value, name, maximum=128)
    if not _NAME_RE.fullmatch(text):
        raise PublicAPIInputError(
            f"{name} must use letters, numbers, dots, underscores, or hyphens"
        )
    return text


def _required_text(value: object, name: str, *, maximum: int) -> str:
    if not isinstance(value, str):
        raise PublicAPIInputError(f"{name} must be a string")
    text = value.strip()
    if not text:
        raise PublicAPIInputError(f"{name} is required")
    if len(text) > maximum:
        raise PublicAPIInputError(f"{name} must be at most {maximum} characters")
    return text


def _optional_text(value: object, name: str, *, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PublicAPIInputError(f"{name} must be a string")
    text = value.strip()
    if not text:
        return None
    if len(text) > maximum:
        raise PublicAPIInputError(f"{name} must be at most {maximum} characters")
    return text


def _optional_raw_text(value: object, name: str, *, maximum: int) -> str | None:
    """Validate text while preserving the exact bytes represented by the caller."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise PublicAPIInputError(f"{name} must be a string")
    if len(value) > maximum:
        raise PublicAPIInputError(f"{name} must be at most {maximum} characters")
    return value


def _agent_receipt_id(turn_id: str) -> str:
    digest = hashlib.sha256(f"public-agent-receipt/1\0{turn_id}".encode()).hexdigest()
    return f"rcpt_{digest[:24]}"


def _bounded_int(
    value: object, name: str, minimum: int, maximum: int
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PublicAPIInputError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise PublicAPIInputError(f"{name} must be between {minimum} and {maximum}")
    return value


def _optional_int(value: object, name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise PublicAPIInputError(f"{name} must be an integer")
    return value


def _optional_number(
    value: object, name: str, *, minimum: float
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PublicAPIInputError(f"{name} must be a number")
    resolved = float(value)
    if not math.isfinite(resolved) or resolved < minimum:
        raise PublicAPIInputError(f"{name} must be at least {minimum}")
    return resolved


__all__: Sequence[str] = (
    "begin_turn",
    "complete_turn",
    "fail_turn",
    "record_actions",
)
