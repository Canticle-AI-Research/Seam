#!/usr/bin/env python3
"""Maintain bounded root-session context and red/green evidence for closeout."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.agents.session_end_closeout import SessionEndError, validate_session_state

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_ROOT = REPO_ROOT / ".seam" / "orchestration" / "sessions"
SESSION_ID_ENV = "CODEX_SESSION_ID"
MAX_STATE_BYTES = 256 * 1024
SENSITIVE = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"https?://(?:chatgpt\.com/share|claude\.ai/share)/\S+", re.I),
)


class SessionStateError(RuntimeError):
    """Session state is absent, unsafe, or structurally invalid."""


def _session_id() -> str:
    raw = os.environ.get(SESSION_ID_ENV, "")
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", raw).strip("._")
    if not cleaned:
        raise SessionStateError(f"{SESSION_ID_ENV} is missing or invalid")
    return cleaned[:180]


def _check_text(value: str) -> str:
    if any(pattern.search(value) for pattern in SENSITIVE):
        raise SessionStateError("session state contains secret-shaped or private-link content")
    return value


def _head(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SessionStateError("repo root does not have a resolvable Git HEAD")
    return result.stdout.strip()


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    try:
        validate_session_state(value, expected_session_id=str(value.get("session_id") or ""))
    except SessionEndError as exc:
        raise SessionStateError(str(exc)) from exc
    encoded = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(encoded) > MAX_STATE_BYTES:
        raise SessionStateError("session state exceeds the 256 KiB bound")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_bytes(encoded)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def _load(path: Path, session_id: str) -> dict[str, Any]:
    if not path.is_file():
        raise SessionStateError("initialize the root session state before recording TDD")
    if path.stat().st_size > MAX_STATE_BYTES:
        raise SessionStateError("session state exceeds the 256 KiB bound")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != "seam-agent-session-state/v1":
        raise SessionStateError("session state has an unsupported schema")
    if value.get("session_id") != session_id:
        raise SessionStateError("session state identity mismatch")
    return value


def _phase(command: str, exit_code: int, fingerprint: str, observed_at: str | None) -> dict[str, Any]:
    return {
        "command": _check_text(command),
        "exit_code": exit_code,
        "observed_at": observed_at or datetime.now(timezone.utc).isoformat(),
        "fingerprint": _check_text(fingerprint),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Maintain bounded SEAM root-session state.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create the state record for this Codex session.")
    init.add_argument("--objective", required=True)
    init.add_argument("--plan", action="append", default=[])
    init.add_argument("--constraint", action="append", default=[])
    init.add_argument("--affected-test", action="append", default=[])
    init.add_argument("--replace", action="store_true")

    tdd = subparsers.add_parser("record-tdd", help="Append one witnessed red/green cycle.")
    tdd.add_argument("--behavior", required=True)
    tdd.add_argument("--test-ref", action="append", required=True)
    tdd.add_argument("--implementation-ref", action="append", required=True)
    tdd.add_argument("--red-command", required=True)
    tdd.add_argument("--red-exit", required=True, type=int)
    tdd.add_argument("--red-fingerprint", required=True)
    tdd.add_argument("--red-at")
    tdd.add_argument("--green-command", required=True)
    tdd.add_argument("--green-exit", required=True, type=int)
    tdd.add_argument("--green-fingerprint", required=True)
    tdd.add_argument("--green-at")
    return parser


def _run(args: argparse.Namespace) -> Path:
    session_id = _session_id()
    repo_root = args.repo_root.resolve(strict=True)
    state_root = args.state_root.resolve()
    path = state_root / f"{session_id}.json"
    if args.command == "init":
        if path.exists() and not args.replace:
            raise SessionStateError("session state already exists; use --replace deliberately")
        state = {
            "schema": "seam-agent-session-state/v1",
            "session_id": session_id,
            "base_sha": _head(repo_root),
            "objective": _check_text(args.objective),
            "plan": [_check_text(value) for value in args.plan],
            "constraints": [_check_text(value) for value in args.constraint],
            "affected_tests": [_check_text(value) for value in args.affected_test],
            "tdd_cycles": [],
        }
    else:
        state = _load(path, session_id)
        if args.red_exit == 0:
            raise SessionStateError("red phase must have a non-zero exit code")
        if args.green_exit != 0:
            raise SessionStateError("green phase must have a zero exit code")
        state["tdd_cycles"].append(
            {
                "behavior": _check_text(args.behavior),
                "test_refs": [_check_text(value) for value in args.test_ref],
                "implementation_refs": [
                    _check_text(value) for value in args.implementation_ref
                ],
                "red": _phase(
                    args.red_command,
                    args.red_exit,
                    args.red_fingerprint,
                    args.red_at,
                ),
                "green": _phase(
                    args.green_command,
                    args.green_exit,
                    args.green_fingerprint,
                    args.green_at,
                ),
            }
        )
    _atomic_write(path, state)
    return path


def main(argv: list[str] | None = None) -> int:
    try:
        path = _run(_parser().parse_args(argv))
    except (OSError, ValueError, json.JSONDecodeError, SessionStateError) as exc:
        print(f"SEAM session state failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
