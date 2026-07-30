#!/usr/bin/env python3
"""
SEAM CLI v2.3.1

The public CLI for the SEAM agent memory runtime.
Connect to a SEAM server via ``SEAM_SERVER_URL`` or ``SEAM_BASE_URL``.
Set ``SEAM_API_TOKEN`` for authenticated access.

Commands:
    seam status                  Show server connection status
    seam remember <text>         Store a memory
    seam recall <query>          Search memories
    seam context <query>         Get prompt-ready context
    seam health                  Ping the server
"""

from __future__ import annotations

import os
import sys


def _get_client():
    """Create a SeamClient from environment, or print error and exit."""
    try:
        from seam_client import SeamClient
    except ImportError:
        print("seam-client is not installed. Run: pip install seam-client", file=sys.stderr)
        sys.exit(1)

    base_url = os.environ.get("SEAM_SERVER_URL") or os.environ.get("SEAM_BASE_URL") or ""
    api_token = os.environ.get("SEAM_API_TOKEN")

    if not base_url:
        print("SEAM_SERVER_URL is not set.", file=sys.stderr)
        print("Example:  export SEAM_SERVER_URL=https://your-server:8787", file=sys.stderr)
        sys.exit(1)

    return SeamClient(base_url=base_url, api_key=api_token)


def cmd_status() -> int:
    """Print client configuration and server health."""
    base_url = os.environ.get("SEAM_SERVER_URL") or os.environ.get("SEAM_BASE_URL") or ""
    api_token = os.environ.get("SEAM_API_TOKEN")

    print("SEAM CLI v2.3.1")
    print(f"  Server:   {base_url or '(not set)'}")
    print(f"  Auth:     {'token set' if api_token else '(none — set SEAM_API_TOKEN)'}")
    print("  API ver:  v1")
    print()

    if not base_url:
        print("Set SEAM_SERVER_URL to connect to a SEAM server.")
        print("Example:  export SEAM_SERVER_URL=https://your-server:8787")
        return 1

    try:
        client = _get_client()
        h = client.health()
        print(f"  Health:   {h.status}")
        print(f"  API ver:  {h.api_version}")
        return 0
    except Exception as exc:
        print(f"  Health:   unreachable — {exc}")
        return 1


def cmd_health() -> int:
    """Ping the server health endpoint."""
    try:
        client = _get_client()
        h = client.health()
        print(f"status:  {h.status}")
        print(f"api_version: {h.api_version}")
        return 0
    except Exception as exc:
        print(f"Health check failed: {exc}", file=sys.stderr)
        return 1


def cmd_remember(text: str) -> int:
    """Store a memory."""
    client = _get_client()
    try:
        receipt = client.remember(text)
        print(f"accepted:  {receipt.accepted}")
        print(f"receipt:   {receipt.receipt_id}")
        print(f"memories:  {receipt.memory_count}")
        return 0
    except Exception as exc:
        print(f"remember failed: {exc}", file=sys.stderr)
        return 1


def cmd_recall(query: str) -> int:
    """Search memories."""
    client = _get_client()
    try:
        result = client.recall(query)
        if not result.memories:
            print("(no memories found)")
            return 0
        for i, mem in enumerate(result.memories, 1):
            print(f"  [{i}] {mem.text[:120]}")
            print(f"      score: {mem.score:.3f}  id: {mem.id}")
        return 0
    except Exception as exc:
        print(f"recall failed: {exc}", file=sys.stderr)
        return 1


def cmd_context(query: str) -> int:
    """Get prompt-ready context."""
    client = _get_client()
    try:
        result = client.context(query)
        print(result.context)
        return 0
    except Exception as exc:
        print(f"context failed: {exc}", file=sys.stderr)
        return 1


_HELP = """\
SEAM CLI  v2.3.1

usage: seam <command> [args]

commands:
    status                  Show connection + server health
    health                  Ping the server health endpoint
    remember <text>         Store a text memory
    recall <query>          Search stored memories
    context <query>         Get prompt-ready context string

environment:
    SEAM_SERVER_URL         URL of your SEAM server (required)
    SEAM_API_TOKEN          Bearer token for authenticated servers

example:
    export SEAM_SERVER_URL=https://seam.example.com
    export SEAM_API_TOKEN=<api-token>
    seam status
    seam remember "The user prefers dark mode"
    seam recall "UI preferences"
"""


def main() -> None:
    if len(sys.argv) < 2:
        cmd_status()
        sys.exit(0)

    cmd = sys.argv[1].lower()
    rest = " ".join(sys.argv[2:])

    if cmd in ("--help", "-h", "help"):
        print(_HELP)
        sys.exit(0)
    elif cmd == "status":
        sys.exit(cmd_status())
    elif cmd == "health":
        sys.exit(cmd_health())
    elif cmd == "remember":
        if not rest:
            print("usage: seam remember <text>", file=sys.stderr)
            sys.exit(1)
        sys.exit(cmd_remember(rest))
    elif cmd == "recall":
        if not rest:
            print("usage: seam recall <query>", file=sys.stderr)
            sys.exit(1)
        sys.exit(cmd_recall(rest))
    elif cmd == "context":
        if not rest:
            print("usage: seam context <query>", file=sys.stderr)
            sys.exit(1)
        sys.exit(cmd_context(rest))
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print("Try: seam --help", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
