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


def test_readme_does_not_advertise_unpublished_public_installer_placeholders() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")

    assert "example.com/seam" not in readme
    assert "public URLs are placeholders" not in readme
    assert "Public release installer shape" not in readme


def test_readme_documents_agent_setup_prompt_for_persistent_memory() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")

    assert "## Agent Setup Prompt" in readme
    assert "Read `AGENTS.md` first" in readme
    assert "API keys, local `.env` files, and local `.conf` files are operator-owned" in readme
    assert "Settings panel" in readme
    assert "seam webui" in readme
    assert "SEAM_LOCAL_ENV" in readme
    assert "seam ingest AGENTS.md --persist" in readme
    assert "seam memory search \"current SEAM repo status\"" in readme
    assert "seam context \"current SEAM repo status\" --retrieval-mode mix --view prompt" in readme
    assert "seam-mcp --ensure-pgvector" in readme
    assert "Do not ingest secrets" in readme
    assert "Do not install `bench-judge`, `bench-mem0`, or `bench-zep`" in readme


def test_readme_documents_operator_manual_and_error_index() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")

    assert "## Operator Manual" in readme
    assert "For help beyond the quickstart" in readme
    assert "[Operator guide](docs/SEAM_OPERATOR_GUIDE.md)" in readme
    assert "[Setup guide](docs/setup.md)" in readme
    assert "[macOS guide](docs/MACOS.md)" in readme
    assert "[Task runbooks](docs/howto/README.md)" in readme
    assert "[Engineering manual](docs/engineering/README.md)" in readme
    assert "[Troubleshooting and error index](docs/errors.md)" in readme
    assert "### Error Index" in readme
    assert "`ModuleNotFoundError: No module named 'textual'`" in readme
    assert "`SEAM doctor: FAIL`" in readme
    assert "`PgVector: configured but unreachable`" in readme
    assert "`HTTP 429`" in readme


def test_errors_doc_has_error_index_for_known_failure_types() -> None:
    errors = (REPO / "docs/errors.md").read_text(encoding="utf-8")

    assert "## Error Index" in errors
    assert "[`ModuleNotFoundError: No module named 'textual'`]" in errors
    assert "[`SEAM doctor: FAIL` with missing required deps]" in errors
    assert "[`PgVector: configured but unreachable`]" in errors
    assert "[`HTTP 429` provider quota or rate limit]" in errors


def test_manifest_includes_package_assets_and_license_files() -> None:
    manifest = (REPO / "MANIFEST.in").read_text(encoding="utf-8")

    assert "include LICENSE NOTICE README.md SECURITY.md CONTRIBUTING.md COMMERCIAL_LICENSE.md" in manifest
    assert "recursive-include seam_runtime/webui *" in manifest


def test_ci_builds_and_installs_distribution_artifacts() -> None:
    workflow = (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "package-smoke:" in workflow
    assert "python -m build --wheel --sdist" in workflow
    assert "python -m pip install dist/*.whl" in workflow
