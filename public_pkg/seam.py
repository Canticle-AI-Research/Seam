#!/usr/bin/env python3
"""
SEAM CLI v2.3.0

The public CLI.  Connect to a SEAM server via ``SEAM_SERVER_URL`` or run
``seam status`` to check your configuration.
"""

from __future__ import annotations

import os
import sys


def _server_url() -> str:
    return os.environ.get("SEAM_SERVER_URL", "").strip().rstrip("/")


def cmd_status() -> int:
    """Print the current client configuration."""
    url = _server_url()
    print("SEAM CLI v2.3.0")
    print(f"  Server:  {url or '(not set — export SEAM_SERVER_URL)'}")
    print(f"  API ver: v1")
    if url:
        print(f"  Health:  (run 'seam health' to check)")
    else:
        print()
        print("Set SEAM_SERVER_URL to connect to a SEAM server.")
        print("Example:  export SEAM_SERVER_URL=https://your-server:8787")
    return 0


def cmd_health() -> int:
    """Ping the SEAM server health endpoint."""
    url = _server_url()
    if not url:
        print("SEAM_SERVER_URL is not set.", file=sys.stderr)
        return 1
    try:
        import urllib.request
        import json

        req = urllib.request.Request(f"{url}/v1/health")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            print(f"Server:  {url}")
            print(f"Status:  {data.get('status', 'unknown')}")
            print(f"Version: {data.get('version', 'unknown')}")
            return 0
    except Exception as exc:
        print(f"Health check failed: {exc}", file=sys.stderr)
        return 1


def main() -> None:
    if len(sys.argv) < 2:
        cmd_status()
        sys.exit(0)

    cmd = sys.argv[1].lower()
    if cmd in ("status",):
        sys.exit(cmd_status())
    elif cmd in ("health",):
        sys.exit(cmd_health())
    elif cmd in ("--help", "-h", "help"):
        print("usage: seam [status|health]")
        print()
        print("SEAM CLI  v2.3.0  — public client")
        print("Connect to a SEAM server by setting SEAM_SERVER_URL.")
        sys.exit(0)
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print("Try: seam status  |  seam health  |  seam --help", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
