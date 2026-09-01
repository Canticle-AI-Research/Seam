#!/usr/bin/env python3
"""Enforce the bounded context lifecycle for Codex-only orchestration."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

CHECKPOINT_PERCENT = 45.0
COMPACT_PERCENT = 65.0
HANDOFF_PERCENT = 82.0
MAX_COMPACTIONS = 2
MAX_STATE_BYTES = 256 * 1024
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_ROOT = REPO_ROOT / ".seam" / "orchestration" / "context"
DEFAULT_HANDOFF_ROOT = REPO_ROOT / ".context-handoffs"
SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,180}$")
SENSITIVE = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"https?://(?:chatgpt\.com/share|claude\.ai/share)/\S+", re.I),
)
STATE_FIELDS = {
    "schema",
    "session_id",
    "compactions_completed",
    "highest_usage_percent",
    "checkpoint_path",
    "handoff_path",
    "last_action",
}
VALID_ACTIONS = {
    "CONTINUE",
    "CHECKPOINT_NOW",
    "COMPACT_AT_MILESTONE",
    "COMPACT_NOW",
    "COMPACTION_RECORDED",
    "HANDOFF_REQUIRED",
}
CHECKPOINT_FIELDS = {
    "schema",
    "session_id",
    "observed_at",
    "usage_percent",
    "compactions_completed",
    "summary",
    "next_step",
}


class ContextGuardianError(RuntimeError):
    """Context usage or persisted lifecycle state is invalid."""


class Decision(TypedDict):
    action: str
    usage_percent: float
    compactions_completed: int


def decide(
    *,
    used_tokens: int,
    context_limit: int,
    compactions_completed: int,
    at_coherent_milestone: bool,
) -> Decision:
    """Return the next mandatory lifecycle action for exact observed usage."""

    if isinstance(used_tokens, bool) or not isinstance(used_tokens, int):
        raise ContextGuardianError("used_tokens must be an integer")
    if isinstance(context_limit, bool) or not isinstance(context_limit, int):
        raise ContextGuardianError("context_limit must be an integer")
    if context_limit <= 0 or used_tokens < 0 or used_tokens > context_limit:
        raise ContextGuardianError("context usage is outside the valid range")
    if (
        isinstance(compactions_completed, bool)
        or not isinstance(compactions_completed, int)
        or not 0 <= compactions_completed <= MAX_COMPACTIONS
    ):
        raise ContextGuardianError("compactions_completed is outside the valid range")
    if not isinstance(at_coherent_milestone, bool):
        raise ContextGuardianError("at_coherent_milestone must be a boolean")

    usage_percent = used_tokens / context_limit * 100.0
    if usage_percent >= HANDOFF_PERCENT or compactions_completed >= MAX_COMPACTIONS:
        action = "HANDOFF_REQUIRED"
    elif usage_percent >= COMPACT_PERCENT:
        action = "COMPACT_NOW" if at_coherent_milestone else "COMPACT_AT_MILESTONE"
    elif usage_percent >= CHECKPOINT_PERCENT:
        action = "CHECKPOINT_NOW"
    else:
        action = "CONTINUE"
    return {
        "action": action,
        "usage_percent": usage_percent,
        "compactions_completed": compactions_completed,
    }


def _session_id(value: str) -> str:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ContextGuardianError("session_id is unsafe")
    return value


def _safe_text(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 4000:
        raise ContextGuardianError(f"{label} is empty or exceeds its bound")
    if "\n" in value or "\r" in value or any(pattern.search(value) for pattern in SENSITIVE):
        raise ContextGuardianError(f"{label} contains sensitive or multiline content")
    return value.strip()


def _atomic_write(path: Path, encoded: bytes) -> None:
    if len(encoded) > MAX_STATE_BYTES:
        raise ContextGuardianError("context guardian artifact exceeds 256 KiB")
    if os.path.lexists(path.parent) and (
        path.parent.is_symlink() or not path.parent.is_dir()
    ):
        raise ContextGuardianError(
            "context guardian artifact directory must be a real directory"
        )
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink() or path.parent.resolve() != path.parent:
        raise ContextGuardianError(
            "context guardian artifact directory escapes its state root"
        )
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _state_path(state_root: Path, session_id: str) -> Path:
    return state_root.resolve() / f"{_session_id(session_id)}.json"


def _expected_checkpoint_path(state_root: Path, session_id: str) -> Path:
    return state_root.resolve() / "checkpoints" / f"{session_id}.json"


def _expected_handoff_path(handoff_root: Path, session_id: str) -> Path:
    return handoff_root.resolve() / f"context-handoff-{session_id}.md"


def _load_checkpoint(state_root: Path, session_id: str) -> dict[str, Any]:
    path = _expected_checkpoint_path(state_root, session_id)
    if (
        not os.path.lexists(path.parent)
        or path.parent.is_symlink()
        or not path.parent.is_dir()
        or path.parent.resolve() != path.parent
    ):
        raise ContextGuardianError(
            "context checkpoint directory must be a real local directory"
        )
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > MAX_STATE_BYTES:
            raise ContextGuardianError("context checkpoint must be a bounded regular file")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextGuardianError("context checkpoint is missing or unreadable") from exc
    if (
        not isinstance(value, dict)
        or set(value) != CHECKPOINT_FIELDS
        or value.get("schema") != "seam-context-checkpoint/v1"
        or value.get("session_id") != session_id
    ):
        raise ContextGuardianError("context checkpoint does not match its contract")
    usage = value.get("usage_percent")
    if isinstance(usage, bool) or not isinstance(usage, (int, float)) or not 0 <= usage <= 100:
        raise ContextGuardianError("context checkpoint usage is invalid")
    compactions = value.get("compactions_completed")
    if (
        isinstance(compactions, bool)
        or not isinstance(compactions, int)
        or not 0 <= compactions <= MAX_COMPACTIONS
    ):
        raise ContextGuardianError("context checkpoint compaction count is invalid")
    observed_at = _safe_text(value.get("observed_at"), label="checkpoint timestamp")
    try:
        timestamp = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContextGuardianError("context checkpoint timestamp is invalid") from exc
    if timestamp.tzinfo is None:
        raise ContextGuardianError("context checkpoint timestamp must include a timezone")
    summary = value.get("summary")
    if not isinstance(summary, list) or not 1 <= len(summary) <= 32:
        raise ContextGuardianError("context checkpoint summary is invalid")
    for item in summary:
        _safe_text(item, label="checkpoint summary")
    _safe_text(value.get("next_step"), label="checkpoint next_step")
    return value


def _load_state(
    state_root: Path,
    session_id: str,
    *,
    handoff_root: Path | None = None,
) -> dict[str, Any]:
    path = _state_path(state_root, session_id)
    if not path.exists():
        return {
            "schema": "seam-context-guardian-state/v1",
            "session_id": session_id,
            "compactions_completed": 0,
            "highest_usage_percent": 0.0,
            "checkpoint_path": None,
            "handoff_path": None,
            "last_action": "CONTINUE",
        }
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise ContextGuardianError(
                "context guardian state must be a regular file"
            )
        if metadata.st_size > MAX_STATE_BYTES:
            raise ContextGuardianError("context guardian state exceeds 256 KiB")
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContextGuardianError("context guardian state is unreadable") from exc
    if (
        not isinstance(state, dict)
        or set(state) != STATE_FIELDS
        or state.get("schema") != "seam-context-guardian-state/v1"
        or state.get("session_id") != session_id
    ):
        raise ContextGuardianError("context guardian state does not match its contract")
    compactions = state.get("compactions_completed")
    if isinstance(compactions, bool) or not isinstance(compactions, int) or not 0 <= compactions <= 2:
        raise ContextGuardianError("context guardian compaction state is invalid")
    usage = state.get("highest_usage_percent")
    if isinstance(usage, bool) or not isinstance(usage, (int, float)) or not 0 <= usage <= 100:
        raise ContextGuardianError("context guardian usage state is invalid")
    if state.get("last_action") not in VALID_ACTIONS:
        raise ContextGuardianError("context guardian last_action is invalid")
    checkpoint_path = state.get("checkpoint_path")
    expected_checkpoint = _expected_checkpoint_path(state_root, session_id)
    if checkpoint_path is not None and checkpoint_path != str(expected_checkpoint):
        raise ContextGuardianError("context guardian checkpoint path is invalid")
    if compactions and checkpoint_path is None:
        raise ContextGuardianError("context guardian compactions lack a checkpoint")
    if checkpoint_path is not None:
        _load_checkpoint(state_root, session_id)
    handoff_path = state.get("handoff_path")
    if handoff_path is not None:
        if handoff_root is None or handoff_path != str(
            _expected_handoff_path(handoff_root, session_id)
        ):
            raise ContextGuardianError("context guardian handoff path is invalid")
    return state


def _write_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_write(
        path,
        (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def _store_state(state_root: Path, state: dict[str, Any]) -> None:
    _write_json(_state_path(state_root, state["session_id"]), state)


def _render_handoff(checkpoint: dict[str, Any]) -> bytes:
    summary = "\n".join(f"- {item}" for item in checkpoint["summary"])
    text = (
        "# SEAM context successor handoff\n\n"
        f"Session: `{checkpoint['session_id']}`  \n"
        f"Observed: `{checkpoint['observed_at']}`  \n"
        f"Context usage: `{checkpoint['usage_percent']:.2f}%`  \n"
        f"Compactions completed: `{checkpoint['compactions_completed']}/2`\n\n"
        "## Durable checkpoint\n\n"
        f"{summary}\n\n"
        "## Resume first\n\n"
        f"{checkpoint['next_step']}\n"
    )
    return text.encode("utf-8")


def observe(
    *,
    session_id: str,
    used_tokens: int,
    context_limit: int,
    at_coherent_milestone: bool,
    summary: list[str],
    next_step: str,
    state_root: Path = DEFAULT_STATE_ROOT,
    handoff_root: Path = DEFAULT_HANDOFF_ROOT,
) -> dict[str, Any]:
    """Persist the checkpoint and handoff artifacts required by current usage."""

    session_id = _session_id(session_id)
    if not isinstance(summary, list) or not 1 <= len(summary) <= 32:
        raise ContextGuardianError("summary must contain between one and 32 items")
    safe_summary = [_safe_text(item, label="summary") for item in summary]
    safe_next_step = _safe_text(next_step, label="next_step")
    state = _load_state(state_root, session_id, handoff_root=handoff_root)
    decision = decide(
        used_tokens=used_tokens,
        context_limit=context_limit,
        compactions_completed=state["compactions_completed"],
        at_coherent_milestone=at_coherent_milestone,
    )
    now = datetime.now(timezone.utc).isoformat()
    state["highest_usage_percent"] = max(
        float(state["highest_usage_percent"]), decision["usage_percent"]
    )
    state["last_action"] = decision["action"]
    result: dict[str, Any] = dict(decision)
    if decision["action"] != "CONTINUE":
        checkpoint_path = _expected_checkpoint_path(state_root, session_id)
        checkpoint = {
            "schema": "seam-context-checkpoint/v1",
            "session_id": session_id,
            "observed_at": now,
            "usage_percent": decision["usage_percent"],
            "compactions_completed": state["compactions_completed"],
            "summary": safe_summary,
            "next_step": safe_next_step,
        }
        _write_json(checkpoint_path, checkpoint)
        state["checkpoint_path"] = str(checkpoint_path)
        result["checkpoint_path"] = str(checkpoint_path)
        if decision["action"] == "HANDOFF_REQUIRED":
            handoff_path = _expected_handoff_path(handoff_root, session_id)
            _atomic_write(handoff_path, _render_handoff(checkpoint))
            state["handoff_path"] = str(handoff_path)
            result["handoff_path"] = str(handoff_path)
    _store_state(state_root, state)
    return result


def record_compaction(
    *,
    session_id: str,
    state_root: Path = DEFAULT_STATE_ROOT,
    handoff_root: Path = DEFAULT_HANDOFF_ROOT,
) -> dict[str, Any]:
    """Record one completed compaction and enforce the two-compaction ceiling."""

    session_id = _session_id(session_id)
    state = _load_state(state_root, session_id, handoff_root=handoff_root)
    if state["compactions_completed"] >= MAX_COMPACTIONS:
        raise ContextGuardianError("two compactions already completed; handoff is required")
    if state["last_action"] != "COMPACT_NOW":
        raise ContextGuardianError("COMPACT_NOW is required before recording compaction")
    checkpoint = _load_checkpoint(state_root, session_id)
    state["compactions_completed"] += 1
    action = (
        "HANDOFF_REQUIRED"
        if state["compactions_completed"] >= MAX_COMPACTIONS
        else "COMPACTION_RECORDED"
    )
    state["last_action"] = action
    result = {
        "action": action,
        "compactions_completed": state["compactions_completed"],
    }
    if action == "HANDOFF_REQUIRED":
        checkpoint["compactions_completed"] = state["compactions_completed"]
        _write_json(_expected_checkpoint_path(state_root, session_id), checkpoint)
        handoff_path = _expected_handoff_path(handoff_root, session_id)
        _atomic_write(handoff_path, _render_handoff(checkpoint))
        state["handoff_path"] = str(handoff_path)
        result["handoff_path"] = str(handoff_path)
    _store_state(state_root, state)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Enforce SEAM's bounded Codex context lifecycle."
    )
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--handoff-root", type=Path, default=DEFAULT_HANDOFF_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    observe_parser = commands.add_parser(
        "observe", help="Evaluate usage and update required durable artifacts."
    )
    observe_parser.add_argument("--used-tokens", required=True, type=int)
    observe_parser.add_argument("--context-limit", required=True, type=int)
    observe_parser.add_argument("--at-coherent-milestone", action="store_true")
    observe_parser.add_argument("--summary", action="append", required=True)
    observe_parser.add_argument("--next-step", required=True)
    commands.add_parser(
        "record-compaction", help="Record one completed context compaction."
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the context lifecycle boundary and print its machine-readable action."""

    args = _parser().parse_args(argv)
    try:
        if args.command == "observe":
            result = observe(
                session_id=args.session_id,
                used_tokens=args.used_tokens,
                context_limit=args.context_limit,
                at_coherent_milestone=args.at_coherent_milestone,
                summary=args.summary,
                next_step=args.next_step,
                state_root=args.state_root,
                handoff_root=args.handoff_root,
            )
        else:
            result = record_compaction(
                session_id=args.session_id,
                state_root=args.state_root,
                handoff_root=args.handoff_root,
            )
    except (ContextGuardianError, OSError, ValueError) as exc:
        print(f"context guardian failed closed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
