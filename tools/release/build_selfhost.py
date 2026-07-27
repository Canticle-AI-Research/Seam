"""Build the proprietary compiled self-host image locally without publishing it."""

from __future__ import annotations

import argparse
import base64
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO / "selfhost" / "Dockerfile"


def validate_public_key(path: Path) -> bytes:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise RuntimeError("cryptography is required to validate the entitlement public key") from exc
    try:
        content = path.read_bytes()
        loaded = serialization.load_pem_public_key(content)
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("entitlement public key is unavailable or invalid") from exc
    if not isinstance(loaded, Ed25519PublicKey):
        raise RuntimeError("entitlement public key must be Ed25519")
    return content


def build_command(*, tag: str, public_key: bytes, progress: str) -> list[str]:
    return [
        "docker",
        "buildx",
        "build",
        "--load",
        "--platform",
        "linux/amd64",
        "--progress",
        progress,
        "--tag",
        tag,
        "--build-arg",
        f"SEAM_ENTITLEMENT_PUBLIC_KEY_B64={base64.b64encode(public_key).decode('ascii')}",
        "--file",
        str(DOCKERFILE),
        str(REPO),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="seam-selfhost:local")
    parser.add_argument("--public-key", required=True, type=Path)
    parser.add_argument("--progress", choices=("auto", "plain", "tty", "rawjson"), default="plain")
    parser.add_argument(
        "--print-command",
        action="store_true",
        help="validate inputs and print a redacted command without building",
    )
    args = parser.parse_args(argv)

    public_key = validate_public_key(args.public_key)
    command = build_command(tag=args.tag, public_key=public_key, progress=args.progress)
    if args.print_command:
        redacted = [
            "<public-key-b64>" if item.startswith("SEAM_ENTITLEMENT_PUBLIC_KEY_B64=") else item
            for item in command
        ]
        print(" ".join(redacted))
        return 0

    if os.environ.get("DOCKER_BUILDKIT", "1").strip() == "0":
        print("[selfhost-build] BuildKit is required", file=sys.stderr)
        return 2
    print(f"[selfhost-build] building {args.tag} locally; no registry push is performed")
    completed = subprocess.run(command, cwd=REPO, check=False)
    if completed.returncode:
        return completed.returncode
    print(f"[selfhost-build] built local image {args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
