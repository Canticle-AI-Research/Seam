"""Shared tenant-to-namespace ownership invariant."""

from __future__ import annotations

import re

_PRINCIPAL_NAMESPACE_RE = re.compile(r"^principal:[0-9a-f]{64}(?:$|[.:])")


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
