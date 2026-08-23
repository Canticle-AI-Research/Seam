"""Shared tenant-to-namespace ownership invariant."""

from __future__ import annotations

import re

_PRINCIPAL_NAMESPACE_RE = re.compile(
    r"^(?P<tenant>principal:[0-9a-f]{64})(?:$|[.:])"
)


def tenant_owns_namespace(tenant_id: str, namespace: str) -> bool:
    """Return whether ``namespace`` belongs to the exact tenant prefix."""

    return (
        namespace == tenant_id
        or namespace.startswith(f"{tenant_id}.")
        or namespace.startswith(f"{tenant_id}:")
    )


def is_principal_namespace(namespace: str) -> bool:
    """Return whether a namespace is owned by S6's hashed principal format."""

    return bool(_PRINCIPAL_NAMESPACE_RE.match(namespace))


def principal_tenant_id(namespace: str) -> str | None:
    """Return the exact hashed tenant prefix for an S6 principal namespace."""

    match = _PRINCIPAL_NAMESPACE_RE.match(namespace)
    return match.group("tenant") if match is not None else None
