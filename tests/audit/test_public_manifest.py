"""Frozen private/public boundary in tools/release/public_manifest.py."""

from __future__ import annotations

import pytest

from tools.release.public_manifest import (
    HS1_RESERVED_FILES,
    LEGACY_PUBLIC_HEAD_AT_FREEZE,
    PUBLIC_SYNC_FROZEN,
    is_allowed_on_public_mirror,
    is_hs1_reserved_path,
    is_mirl_reserved_path,
    is_public_owned_path,
    is_public_synced_path,
    is_reserved_material_path,
)


def test_legacy_public_sync_is_frozen_at_an_exact_head() -> None:
    assert PUBLIC_SYNC_FROZEN is True
    assert len(LEGACY_PUBLIC_HEAD_AT_FREEZE) == 40


@pytest.mark.parametrize(
    "path",
    [
        "README.md",
        "LICENSE",
        "AGENTS.md",
        "pyproject.toml",
        "docs/setup.md",
        "installers/install_seam_linux.sh",
        "tools/history/new_entry.py",
        "some/brand/new/path/nobody/added/yet.md",
    ],
)
def test_no_private_path_is_synced(path: str) -> None:
    assert not is_public_synced_path(path)


@pytest.mark.parametrize(
    "path",
    [
        "SEAM_SPEC_V0.1.md",
        "docs/MIRL_V1.md",
        "seam.py",
        "seam_runtime/mirl.py",
        "seam_runtime/nl.py",
        "seam_runtime/pack.py",
        "tests/fidelity/test_compile_fidelity.py",
        "test_seam_all/test_seam.py",
        "benchmarks/fidelity/contract.py",
        "tools/h2/improvement_loop.py",
    ],
)
def test_mirl_reserved_paths_are_explicit_and_never_public_synced(path: str) -> None:
    assert is_mirl_reserved_path(path)
    assert is_reserved_material_path(path)
    assert not is_public_synced_path(path)
    assert not is_allowed_on_public_mirror(path)


@pytest.mark.parametrize("path", sorted(HS1_RESERVED_FILES))
def test_hs1_reserved_paths_are_explicit_and_never_public_synced(path: str) -> None:
    assert is_hs1_reserved_path(path)
    assert is_reserved_material_path(path)
    assert not is_mirl_reserved_path(path)
    assert not is_public_synced_path(path)
    assert not is_allowed_on_public_mirror(path)


@pytest.mark.parametrize(
    "path",
    [
        "HISTORY.md",
        "HISTORY_INDEX.md",
        "PROJECT_STATUS.md",
        "REPO_LEDGER.md",
        ".seam/streams/history/log.md",
        ".seam/cross_index.md",
    ],
)
def test_legacy_public_owned_paths_are_historical_not_synced(path: str) -> None:
    assert is_public_owned_path(path)
    assert is_allowed_on_public_mirror(path)
    assert not is_public_synced_path(path)


def test_unclassified_private_path_is_private_by_default() -> None:
    path = "docs/new-unreleased-design.md"
    assert not is_mirl_reserved_path(path)
    assert not is_hs1_reserved_path(path)
    assert not is_reserved_material_path(path)
    assert not is_public_owned_path(path)
    assert not is_public_synced_path(path)
    assert not is_allowed_on_public_mirror(path)
