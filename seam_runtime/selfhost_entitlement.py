"""Offline signed entitlement verification for the compiled self-host edition."""

from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENTITLEMENT_SCHEMA = "seam-selfhost-entitlement/v1"
ENTITLEMENT_PRODUCT = "seam-selfhost-mirl"
REQUIRED_FEATURE = "opaque-v1"


class EntitlementError(RuntimeError):
    """Raised when a self-host entitlement is absent, invalid, or expired."""


@dataclass(frozen=True)
class VerifiedEntitlement:
    entitlement_id: str
    customer_id: str
    issued_at: datetime
    not_before: datetime
    expires_at: datetime
    features: tuple[str, ...]


def canonical_entitlement_payload(payload: dict[str, Any]) -> bytes:
    """Return the exact canonical bytes covered by the Ed25519 signature."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def verify_entitlement(
    entitlement_path: str | Path,
    public_key_path: str | Path,
    *,
    now: datetime | None = None,
    enforce_validity_window: bool = True,
) -> VerifiedEntitlement:
    """Verify an offline Ed25519 entitlement and return bounded public claims.

    ``enforce_validity_window`` separates cryptographic validity from temporal
    validity. Signature, schema, and product checks always apply. Callers that
    treat an entitlement as an identity badge rather than a licence gate pass
    ``False`` so a lapsed but genuine entitlement is returned and can be reported
    as inactive, instead of being indistinguishable from a forged one.
    """
    try:
        envelope = json.loads(Path(entitlement_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EntitlementError("entitlement file is unavailable or invalid JSON") from exc
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "signature"}:
        raise EntitlementError("entitlement envelope must contain only payload and signature")
    payload = envelope["payload"]
    if not isinstance(payload, dict):
        raise EntitlementError("entitlement payload must be an object")

    signature = _decode_signature(envelope["signature"])
    public_key = _load_public_key(public_key_path)
    try:
        public_key.verify(signature, canonical_entitlement_payload(payload))
    except Exception as exc:  # InvalidSignature is intentionally normalized at this boundary.
        raise EntitlementError("entitlement signature verification failed") from exc

    required_keys = {
        "schema",
        "product",
        "entitlement_id",
        "customer_id",
        "issued_at",
        "not_before",
        "expires_at",
        "features",
    }
    if set(payload) != required_keys:
        raise EntitlementError("entitlement payload fields do not match schema v1")
    if payload["schema"] != ENTITLEMENT_SCHEMA:
        raise EntitlementError("unsupported entitlement schema")
    if payload["product"] != ENTITLEMENT_PRODUCT:
        raise EntitlementError("entitlement is for a different product")

    entitlement_id = _bounded_identifier(payload["entitlement_id"], "entitlement_id")
    customer_id = _bounded_identifier(payload["customer_id"], "customer_id")
    issued_at = _parse_utc(payload["issued_at"], "issued_at")
    not_before = _parse_utc(payload["not_before"], "not_before")
    expires_at = _parse_utc(payload["expires_at"], "expires_at")
    if issued_at > not_before:
        raise EntitlementError("issued_at must not be later than not_before")
    if expires_at <= not_before:
        raise EntitlementError("expires_at must be later than not_before")

    raw_features = payload["features"]
    if not isinstance(raw_features, list) or not raw_features:
        raise EntitlementError("features must be a non-empty list")
    features = tuple(_bounded_identifier(value, "feature") for value in raw_features)
    if len(set(features)) != len(features):
        raise EntitlementError("features must not contain duplicates")
    if REQUIRED_FEATURE not in features:
        raise EntitlementError(f"entitlement does not grant required feature {REQUIRED_FEATURE}")

    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise EntitlementError("verification time must be timezone-aware")
    current = current.astimezone(timezone.utc)
    if enforce_validity_window:
        if current < not_before:
            raise EntitlementError("entitlement is not active yet")
        if current >= expires_at:
            raise EntitlementError("entitlement has expired")

    return VerifiedEntitlement(
        entitlement_id=entitlement_id,
        customer_id=customer_id,
        issued_at=issued_at,
        not_before=not_before,
        expires_at=expires_at,
        features=features,
    )


def _load_public_key(path: str | Path) -> Any:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise EntitlementError("cryptography is required for entitlement verification") from exc
    try:
        loaded = serialization.load_pem_public_key(Path(path).read_bytes())
    except (OSError, ValueError, TypeError) as exc:
        raise EntitlementError("entitlement public key is unavailable or invalid") from exc
    if not isinstance(loaded, Ed25519PublicKey):
        raise EntitlementError("entitlement public key must be Ed25519")
    return loaded


def _decode_signature(value: object) -> bytes:
    if not isinstance(value, str) or not value:
        raise EntitlementError("entitlement signature must be base64url text")
    try:
        signature = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error) as exc:
        raise EntitlementError("entitlement signature is not valid base64url") from exc
    if len(signature) != 64:
        raise EntitlementError("entitlement signature must be 64 bytes")
    return signature


def _bounded_identifier(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise EntitlementError(f"{name} must be text")
    resolved = value.strip()
    if resolved != value:
        raise EntitlementError(f"{name} must not have leading or trailing whitespace")
    if not resolved or len(resolved) > 128:
        raise EntitlementError(f"{name} must be between 1 and 128 characters")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in resolved):
        raise EntitlementError(f"{name} contains control characters")
    return resolved


def _parse_utc(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise EntitlementError(f"{name} must be an RFC 3339 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise EntitlementError(f"{name} must be an RFC 3339 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise EntitlementError(f"{name} must be UTC")
    return parsed.astimezone(timezone.utc)
