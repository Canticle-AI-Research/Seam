"""Issue one offline signed self-host entitlement from an operator-held key."""

from __future__ import annotations

import argparse
import base64
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from seam_runtime.selfhost_entitlement import (
    ENTITLEMENT_PRODUCT,
    ENTITLEMENT_SCHEMA,
    REQUIRED_FEATURE,
    canonical_entitlement_payload,
)


def load_private_key(path: Path, passphrase_path: Path | None) -> Any:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError as exc:
        raise RuntimeError("cryptography is required to sign an entitlement") from exc
    password = None
    if passphrase_path is not None:
        try:
            password = passphrase_path.read_bytes().rstrip(b"\r\n")
        except OSError as exc:
            raise RuntimeError("private-key passphrase file is unavailable") from exc
        if not password:
            raise RuntimeError("private-key passphrase file is empty")
    try:
        key_mode = stat.S_IMODE(path.stat().st_mode)
        if os.name == "posix" and key_mode & 0o077:
            raise RuntimeError("private signing key permissions must not allow group or other access")
        key = serialization.load_pem_private_key(path.read_bytes(), password=password)
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("private signing key is unavailable or invalid") from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise RuntimeError("private signing key must be Ed25519")
    return key


def make_envelope(
    private_key: Any,
    *,
    entitlement_id: str,
    customer_id: str,
    issued_at: str,
    not_before: str,
    expires_at: str,
) -> dict[str, object]:
    _validate_identifier(entitlement_id, "entitlement_id")
    _validate_identifier(customer_id, "customer_id")
    issued = _parse_utc(issued_at, "issued_at")
    active = _parse_utc(not_before, "not_before")
    expires = _parse_utc(expires_at, "expires_at")
    if issued > active:
        raise RuntimeError("issued_at must not be later than not_before")
    if expires <= active:
        raise RuntimeError("expires_at must be later than not_before")
    payload: dict[str, object] = {
        "schema": ENTITLEMENT_SCHEMA,
        "product": ENTITLEMENT_PRODUCT,
        "entitlement_id": entitlement_id,
        "customer_id": customer_id,
        "issued_at": issued_at,
        "not_before": not_before,
        "expires_at": expires_at,
        "features": [REQUIRED_FEATURE],
    }
    signature = private_key.sign(canonical_entitlement_payload(payload))
    return {
        "payload": payload,
        "signature": base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii"),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_identifier(value: str, name: str) -> None:
    if value != value.strip():
        raise RuntimeError(f"{name} must not have leading or trailing whitespace")
    if not value or len(value) > 128:
        raise RuntimeError(f"{name} must be between 1 and 128 characters")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise RuntimeError(f"{name} contains control characters")


def _parse_utc(value: str, name: str) -> datetime:
    if not value.endswith("Z"):
        raise RuntimeError(f"{name} must be an RFC 3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an RFC 3339 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise RuntimeError(f"{name} must be UTC")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--private-key-passphrase-file", type=Path)
    parser.add_argument("--entitlement-id", required=True)
    parser.add_argument("--customer-id", required=True)
    parser.add_argument("--issued-at", default=None)
    parser.add_argument("--not-before", default=None)
    parser.add_argument("--expires-at", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    timestamp = args.issued_at or _utc_now()
    not_before = args.not_before or timestamp
    try:
        private_key = load_private_key(
            args.private_key,
            args.private_key_passphrase_file,
        )
        envelope = make_envelope(
            private_key,
            entitlement_id=args.entitlement_id,
            customer_id=args.customer_id,
            issued_at=timestamp,
            not_before=not_before,
            expires_at=args.expires_at,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            args.output,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(envelope, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"[selfhost-entitlement] FAIL: {exc}", file=sys.stderr)
        return 1
    print(f"[selfhost-entitlement] wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
