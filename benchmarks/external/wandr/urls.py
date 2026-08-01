"""Shared URL identity rules for the provider-free WANDR replay lane."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

_TRACKING_PREFIXES = ("utm_",)
_TRACKING_NAMES = frozenset({"ref", "fbclid", "gclid", "mc_cid", "mc_eid"})


def _is_tracking_parameter(name: str) -> bool:
    normalized = name.casefold()
    return normalized in _TRACKING_NAMES or any(
        normalized.startswith(prefix) for prefix in _TRACKING_PREFIXES
    )


def canonical_url(url: str) -> str:
    """Canonicalize one source URL into its replay identity.

    Only declared tracking parameter names are stripped. In particular, ``ref``
    is exact: application parameters such as ``refine`` and ``refresh`` remain
    part of the source identity.
    """

    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    kept = [
        pair
        for pair in parts.query.split("&")
        if pair and not _is_tracking_parameter(pair.split("=", 1)[0])
    ]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((scheme, netloc, path, "&".join(sorted(kept)), ""))
