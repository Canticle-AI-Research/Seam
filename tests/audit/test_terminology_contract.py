"""Terminology is enforced through the same public CLIs as local/CI gates."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _write(root, relative, text):
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _cli(root, module="verify_terminology", *extra):
    return subprocess.run(
        [sys.executable, "-m", "tools.docs." + module, "--root", str(root), *extra],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )


@pytest.mark.parametrize("acronym,expansion", [
    ("SEAM", "Surface Encoded Agent Memory"),
    ("MIRL", "Machine Intermediate Representation Language"),
])
@pytest.mark.parametrize("verb", ["means", "stands for", "expands to"])
def test_correct_expansion_followed_by_prose_is_accepted(tmp_path, acronym, expansion, verb):
    _write(tmp_path, "README.md", f"{acronym} {verb} {expansion} and preserves provenance.\n")
    result = _cli(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("text", [
    "SEAM means Semantic Encoded Agent Memory.",
    "MIRL expands to Memory Intermediate Representation Language.",
    "Semantic Encoded Agent Memory (SEAM) is incorrect.",
    "Memory Intermediate Representation Language (MIRL) is incorrect.",
    "SEAM means Surface Encoded Agent Memory System.",
    "MIRL means Machine Intermediate Representation Language Engine.",
    "Extended Surface Encoded Agent Memory (SEAM) is the system.",
    "Parallel Machine Intermediate Representation Language (MIRL) is the representation.",
])
def test_competing_expansion_fails_closed(tmp_path, text):
    _write(tmp_path, "README.md", text)
    result = _cli(tmp_path)
    assert result.returncode == 1
    assert "competing" in result.stdout and "expansion" in result.stdout


@pytest.mark.parametrize("text", [
    "SEAM Suite (`seam-client`)", "SEAM Client (`seam-sdk`)",
    "SEAM SDK (`seam-suite`)", "SEAM Suite is the Distributed Runtime.",
])
def test_product_alias_collision_fails_closed(tmp_path, text):
    _write(tmp_path, "docs/README.md", text)
    result = _cli(tmp_path)
    assert result.returncode == 1
    assert "product-name collision" in result.stdout


def test_inactive_and_non_authority_material_is_excluded(tmp_path):
    wrong = "SEAM means Semantic Encoded Agent Memory."
    for relative in ("HISTORY.md", "docs/archive/old.md", "docs/audits/old.md",
                     "docs/handoffs/old.md", "docs/roadmap/plan.md", "build/generated.md",
                     ".worktrees/copy/README.md"):
        _write(tmp_path, relative, wrong)
    assert _cli(tmp_path).returncode == 0


def test_checkout_missing_glossary_fails_closed(tmp_path):
    _write(tmp_path, "SEAM_SPEC_V0.1.md", "# Governing contract\n")
    result = _cli(tmp_path)
    assert result.returncode == 1
    assert "required canonical glossary is missing" in result.stdout


@pytest.mark.parametrize("relative", ["README.md", "docs/TERMINOLOGY.md"])
def test_authority_symlink_cannot_read_outside_checkout(tmp_path, relative):
    outside = tmp_path / "outside.md"
    outside.write_text("SEAM means Semantic Encoded Agent Memory.", encoding="utf-8")
    root = tmp_path / "repo"
    link = root / relative
    link.parent.mkdir(parents=True)
    link.symlink_to(outside)
    result = _cli(root)
    assert result.returncode == 1
    assert "unsafe terminology authority" in result.stdout
    assert "competing" not in result.stdout


def test_wiki_cli_rejects_wrong_terminology(tmp_path):
    _write(tmp_path, "docs/README.md", "# Wiki\nSEAM means Semantic Encoded Agent Memory.\n")
    _write(tmp_path, "tools/docs/verify_terminology.py", "# Checker is part of this fixture.\n")
    result = _cli(tmp_path, "verify_wiki")
    assert result.returncode == 1
    assert "competing SEAM expansion" in result.stdout


def test_wiki_cli_accepts_canonical_expansion_with_trailing_prose(tmp_path):
    _write(tmp_path, "docs/README.md", "# Wiki\nSEAM means Surface Encoded Agent Memory and preserves provenance.\n")
    _write(tmp_path, "tools/docs/verify_terminology.py", "# Checker is part of this fixture.\n")
    result = _cli(tmp_path, "verify_wiki")
    assert result.returncode == 0, result.stdout + result.stderr


def test_wiki_requires_checker_in_real_checkout(tmp_path):
    _write(tmp_path, "docs/README.md", "# Wiki\n")
    _write(tmp_path, "SEAM_SPEC_V0.1.md", "# Governing contract\n")
    result = _cli(tmp_path, "verify_wiki")
    assert result.returncode == 1
    assert "terminology verifier is missing" in result.stdout


def test_staged_wrong_expansion_cannot_be_hidden_by_working_copy_fix(tmp_path):
    for relative in ("tools/docs/__init__.py", "tools/docs/verify_wiki.py",
                     "tools/docs/verify_terminology.py"):
        _write(tmp_path, relative, (ROOT / relative).read_text(encoding="utf-8"))
    _write(tmp_path, "docs/README.md", "# Wiki\nSEAM means Semantic Encoded Agent Memory.\n")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "docs", "tools"], cwd=tmp_path, check=True)
    _write(tmp_path, "docs/README.md", "# Wiki\nSEAM means Surface Encoded Agent Memory and preserves provenance.\n")
    assert _cli(tmp_path, "verify_wiki").returncode == 0
    staged = _cli(tmp_path, "verify_wiki", "--staged")
    assert staged.returncode == 1
    assert "competing SEAM expansion" in staged.stdout


@pytest.mark.parametrize("acronym,expansion", [
    ("SEAM", "Surface Encoded Agent Memory"),
    ("MIRL", "Machine Intermediate Representation Language"),
])
@pytest.mark.parametrize("prefix", ["", "The ", "A ", "An "])
def test_before_expansion_accepts_ordinary_sentence_prefix(tmp_path, acronym, expansion, prefix):
    _write(tmp_path, "README.md", f"{prefix}{expansion} ({acronym}) preserves provenance.\n")
    result = _cli(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
