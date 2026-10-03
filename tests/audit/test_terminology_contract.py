from __future__ import annotations

from pathlib import Path

import pytest

from tools.docs.verify_terminology import verify
from tools.docs.verify_wiki import _verify_terminology


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


@pytest.mark.parametrize("verb", ["means", "expands to"])
def test_competing_mirl_expansion_fails_closed(tmp_path, verb):
    _write(
        tmp_path,
        "README.md",
        f"MIRL {verb} Memory Intermediate Representation Language.\n",
    )

    errors = verify(tmp_path)

    assert any("competing MIRL expansion" in error for error in errors)


@pytest.mark.parametrize(
    "collision",
    [
        "SEAM Suite (`seam-client`)",
        "SEAM Client (`seam-sdk`)",
        "SEAM SDK (`seam-suite`)",
        "SEAM Suite is the Distributed Runtime.",
    ],
)
def test_core_product_name_collisions_fail_closed(tmp_path, collision):
    _write(tmp_path, "docs/README.md", f"# Documentation\n\n{collision}\n")

    errors = verify(tmp_path)

    assert any("product-name collision" in error for error in errors)


def test_non_authority_and_inactive_paths_are_not_scanned(tmp_path):
    competing = "MIRL means Memory Intermediate Representation Language.\n"
    _write(tmp_path, "HISTORY.md", competing)
    _write(tmp_path, "docs/archive/old.md", competing)
    _write(tmp_path, "build/generated.md", competing)
    _write(tmp_path, ".worktrees/copy/README.md", competing)

    assert verify(tmp_path) == []


def test_seam_checkout_requires_the_canonical_glossary(tmp_path):
    _write(tmp_path, "SEAM_SPEC_V0.1.md", "# SEAM v0.1\n")

    errors = verify(tmp_path)

    assert "required canonical glossary is missing: docs/TERMINOLOGY.md" in errors


@pytest.mark.parametrize(
    "relative",
    [
        "README.md",
        "REPO_LEDGER.md",
        "docs/MIRL_V1.md",
        "docs/TERMINOLOGY.md",
    ],
)
def test_real_seam_checkout_requires_exact_mirl_expansion_in_each_core_doc(
    tmp_path,
    relative,
):
    exact = "MIRL: Machine Intermediate Representation Language, SEAM's canonical memory IR.\n"
    _write(tmp_path, "SEAM_SPEC_V0.1.md", "# SEAM v0.1\n")
    for core_relative in (
        "README.md",
        "REPO_LEDGER.md",
        "docs/MIRL_V1.md",
        "docs/TERMINOLOGY.md",
    ):
        _write(tmp_path, core_relative, exact)
    _write(tmp_path, relative, "MIRL is the canonical memory IR.\n")

    errors = verify(tmp_path)

    assert any(relative in error and "missing exact MIRL expansion" in error for error in errors)


def test_managed_mcp_docs_use_cli_db_override_not_shim_environment():
    root = Path(__file__).resolve().parents[2]
    macos = (root / "docs/MACOS.md").read_text(encoding="utf-8")
    macos_mcp = macos.split("## MCP (", 1)[1].split("## Fresh clone", 1)[0]
    operator = (root / "docs/SEAM_OPERATOR_GUIDE.md").read_text(encoding="utf-8")
    operator_mcp = operator.split("### MCP stdio bridge", 1)[1].split("## 6.", 1)[0]

    assert '"args": ["mcp", "stdio"]' in macos_mcp
    assert (
        '"args": ["--db", "/Users/<you>/path/to/custom/seam.db", "mcp", "stdio"]'
        in macos_mcp
    )
    assert '"SEAM_DB_PATH"' not in macos_mcp
    assert '["mcp", "stdio"]' in operator_mcp
    assert (
        '["--db", "/path/to/custom/seam.db", "mcp", "stdio"]'
        in operator_mcp
    )
    assert "SEAM_DB_PATH" not in operator_mcp


def test_wiki_terminology_integration_rejects_competing_seam_expansion(tmp_path):
    exact_mirl = (
        "MIRL: Machine Intermediate Representation Language, "
        "SEAM's canonical memory IR.\n"
    )
    _write(
        tmp_path,
        "SEAM_SPEC_V0.1.md",
        "SEAM means Semantic Encoded Agent Memory.\n",
    )
    for relative in (
        "README.md",
        "REPO_LEDGER.md",
        "docs/MIRL_V1.md",
        "docs/TERMINOLOGY.md",
    ):
        _write(tmp_path, relative, exact_mirl)
    _write(
        tmp_path,
        "tools/docs/verify_terminology.py",
        "# Placeholder proving the wiki integration is enabled for this fixture.\n",
    )

    errors = _verify_terminology(tmp_path)

    assert any("competing SEAM expansion" in error for error in errors)


def test_current_repository_satisfies_terminology_contract():
    root = Path(__file__).resolve().parents[2]

    assert verify(root) == []
