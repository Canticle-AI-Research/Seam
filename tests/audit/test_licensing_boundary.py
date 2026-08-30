"""Credential-free checks for SEAM's repository and product license boundary.

These tests verify repository consistency. They do not interpret a license,
establish ownership, or replace legal review.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_private_root_license_has_no_current_source_available_grant() -> None:
    license_text = _read("LICENSE")

    assert license_text.startswith(
        "SEAM PRIVATE REPOSITORY, MIRL, HS/1, AND RESEARCH MATERIALS LICENSE\n"
    )
    assert "Version 3.0" in license_text
    assert "THIS IS A PROPRIETARY LICENSE" in license_text
    assert "No new BUSL grant is made by this repository" in license_text
    assert "PolyForm Shield License 1.0.0\n\n<https://" not in license_text


def test_package_metadata_is_private_and_excludes_historical_busl() -> None:
    project = tomllib.loads(_read("pyproject.toml"))["project"]

    assert project["license"] == "LicenseRef-SEAM-Proprietary AND Apache-2.0"
    assert set(project["license-files"]) == {
        "LICENSE",
        "NOTICE",
        "COMMERCIAL_LICENSE.md",
        "LICENSES/Apache-2.0.txt",
    }
    assert "Private :: Do Not Upload" in project["classifiers"]
    assert "BUSL" not in project["license"]
    assert "PolyForm" not in project["license"]


def test_busl_is_preserved_as_historical_evidence_without_deletion() -> None:
    original = ROOT / "LICENSES/BUSL-1.1.txt"
    historical = ROOT / "LICENSES/HISTORICAL/BUSL-1.1.txt"

    assert original.is_file()
    assert historical.is_file()
    assert historical.read_bytes() == original.read_bytes()
    assert historical.read_text(encoding="utf-8").startswith(
        "License text copyright (c) 2020 MariaDB Corporation Ab"
    )
    registry = _read("LICENSES/README.md")
    assert "historical evidence" in registry
    assert "does not relicense later" in registry


def test_three_lane_product_matrix_is_consistent() -> None:
    architecture = _read("docs/legal/LICENSING_ARCHITECTURE.md")
    notice = _read("NOTICE")

    for term in (
        "Apache-2.0",
        "PolyForm Shield 1.0.0",
        "proprietary / All Rights Reserved",
        "SEAM-U",
    ):
        assert term in architecture
        assert term in notice
    assert "PolyForm Shield is not applied to this repository" in _read(
        "COMMERCIAL_LICENSE.md"
    )


def test_pre_company_ownership_contribution_and_brand_boundaries() -> None:
    license_text = _read("LICENSE")
    contributing = _read("CONTRIBUTING.md")
    trademarks = _read("TRADEMARKS.md")
    readiness = _read("docs/legal/COMPANY_IP_READINESS.md")

    assert "Project Owner is Nicholas Thomas" in license_text
    assert "written" in license_text and "assignment" in license_text
    assert "not accepting unsolicited external pull requests" in contributing
    assert "modified forks" in trademarks
    assert "founder-to-company IP assignment" in readiness


def test_active_status_does_not_route_future_products_to_busl() -> None:
    for path in (
        "README.md",
        "COMMERCIAL_LICENSE.md",
        "docs/status/packaging-licensing.md",
        "docs/legal/LICENSING_ARCHITECTURE.md",
        "docs/roadmap/COMPETITIVE_ROADMAP.md",
    ):
        text = _read(path)
        assert "LICENSES/BUSL-1.1.txt" not in text
        assert "future edition under BUSL" not in text
