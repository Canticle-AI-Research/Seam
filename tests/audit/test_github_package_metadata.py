from __future__ import annotations

from pathlib import Path
import tomllib


REPO = Path(__file__).resolve().parents[2]
GITHUB_DIRECT_URL = "seam-runtime @ git+https://github.com/BlackhatShiftey/Seam_Runtime.git@main"
GITHUB_SERVER_DASH_URL = "seam-runtime[server,dash] @ git+https://github.com/BlackhatShiftey/Seam_Runtime.git@main"


def test_pyproject_points_at_public_runtime_repo() -> None:
    pyproject = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["name"] == "seam-runtime"
    assert pyproject["project"]["urls"]["Repository"] == "https://github.com/BlackhatShiftey/Seam_Runtime"
    assert pyproject["project"]["urls"]["Issues"] == "https://github.com/BlackhatShiftey/Seam_Runtime/issues"


def test_readme_documents_github_pip_install() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")

    assert GITHUB_DIRECT_URL in readme
    assert GITHUB_SERVER_DASH_URL in readme


def test_manifest_includes_package_assets_and_license_files() -> None:
    manifest = (REPO / "MANIFEST.in").read_text(encoding="utf-8")

    assert "include LICENSE NOTICE README.md SECURITY.md CONTRIBUTING.md COMMERCIAL_LICENSE.md" in manifest
    assert "recursive-include seam_runtime/webui *" in manifest


def test_ci_builds_and_installs_distribution_artifacts() -> None:
    workflow = (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "package-smoke:" in workflow
    assert "python -m build --wheel --sdist" in workflow
    assert "python -m pip install dist/*.whl" in workflow
