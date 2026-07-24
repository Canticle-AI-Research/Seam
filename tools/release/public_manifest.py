"""Frozen legacy-public boundary for the private SEAM repository.

The public ``BlackhatShiftey/Seam_Runtime`` repository contains versions that
were intentionally published under Apache-2.0. Those exact versions keep that
license. As of 2026-07-24, however, the private repository is no longer a
source for automatic public synchronization: MIRL, HS/1, and the runtime that
implements them are reserved proprietary materials.

There is deliberately no synced-path allow-list. A future public client or SDK
must define a new artifact, dependency boundary, manifest, and license after
legal review. It must not reactivate this legacy whole-runtime mirror.
"""

from __future__ import annotations

LEGACY_PUBLIC_REPOSITORY = "https://github.com/BlackhatShiftey/Seam_Runtime"
LEGACY_PUBLIC_HEAD_AT_FREEZE = "0f4b40aab7fda643ce776e597f0b430faa465ca8"
PUBLIC_SYNC_FROZEN = True

# These paths identify obvious MIRL and HS/1 expression plus implementation,
# evaluation, and integration surfaces coupled to them. The private repository
# is private-by-default beyond these lists; they exist so safety reports can
# distinguish a reserved-material violation from an ordinary non-public path.
MIRL_RESERVED_FILES: frozenset[str] = frozenset(
    {
        "SEAM_SPEC_V0.1.md",
        "docs/MIRL_V1.md",
        "docs/RAG_ARCHITECTURE.md",
        "seam.py",
    }
)

HS1_RESERVED_FILES: frozenset[str] = frozenset(
    {
        "docs/HOLOGRAPHIC_SURFACE.md",
        "seam_runtime/holographic.py",
        "seam_runtime/surface_adapters.py",
    }
)

MIRL_RESERVED_DIR_PREFIXES: tuple[str, ...] = (
    "seam_runtime/",
    "tests/",
    "test_seam_all/",
    "benchmarks/",
    "tools/h2/",
)

# These paths belong to the legacy public repository's independent history.
# They are not synced from private SEAM. Retaining this classifier lets audit
# tools reason about the legacy repository without treating private copies as
# publication sources.
PUBLIC_OWNED_PATHS: frozenset[str] = frozenset(
    {
        "PROJECT_STATUS.md",
        "REPO_LEDGER.md",
        "HISTORY.md",
        "HISTORY_INDEX.md",
    }
)
PUBLIC_OWNED_DIR_PREFIXES: tuple[str, ...] = (".seam/",)


def is_mirl_reserved_path(path: str) -> bool:
    """Return whether ``path`` is an explicit MIRL reserved-material surface."""
    if path in HS1_RESERVED_FILES:
        return False
    if path in MIRL_RESERVED_FILES:
        return True
    return any(path.startswith(prefix) for prefix in MIRL_RESERVED_DIR_PREFIXES)


def is_hs1_reserved_path(path: str) -> bool:
    """Return whether ``path`` is an explicit HS/1 reserved-material surface."""
    return path in HS1_RESERVED_FILES


def is_reserved_material_path(path: str) -> bool:
    """Return whether ``path`` is an explicit MIRL or HS/1 reserved surface."""
    return is_mirl_reserved_path(path) or is_hs1_reserved_path(path)


def is_public_synced_path(path: str) -> bool:
    """No private-repository path is eligible for legacy mirror synchronization."""
    del path
    return False


def is_public_owned_path(path: str) -> bool:
    """Identify bookkeeping owned independently by the legacy public repo."""
    if path in PUBLIC_OWNED_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in PUBLIC_OWNED_DIR_PREFIXES)


def is_allowed_on_public_mirror(path: str) -> bool:
    """Only legacy-public-owned bookkeeping is recognizable as public state.

    This is not permission to push it: the pre-push hook and sync command freeze
    every update to the legacy mirror. It exists for historical audit only.
    """
    return is_public_owned_path(path)
