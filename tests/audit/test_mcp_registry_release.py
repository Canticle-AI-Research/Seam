"""Registration must resolve to the reviewed Suite, never the legacy package."""

import copy
import json
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NAME = "io.github.Canticle-AI-Research/seam-suite"
MARKER = f"<!-- mcp-name: {NAME} -->"


@pytest.fixture
def manifest():
    return {
        "$schema": "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json",
        "name": NAME,
        "version": "2.4.1rc1",
        "repository": {"url": "https://github.com/Canticle-AI-Research/Seam", "source": "github"},
        "packages": [{
            "registryType": "pypi",
            "identifier": "seam-suite",
            "version": "2.4.1rc1",
            "runtimeHint": "uvx",
            "runtimeArguments": [
                {"type": "named", "name": "--default-index", "value": "https://pypi.org/simple"},
                {"type": "positional", "value": "--from"},
            ],
            "packageArguments": [{"type": "positional", "value": "seam-mcp"}],
            "transport": {"type": "stdio"},
        }],
    }


@pytest.fixture
def project():
    return {
        "name": "seam-suite", "version": "2.4.1rc1", "classifiers": [],
        "scripts": {"seam-mcp": "seam_runtime.mcp_protocol:main"},
    }


@pytest.fixture
def published():
    return {
        "info": {"name": "seam-suite", "version": "2.4.1rc1", "description": MARKER},
        "urls": [
            {"filename": "seam_suite-2.4.1rc1-py3-none-any.whl", "packagetype": "bdist_wheel",
             "url": "https://files.pythonhosted.org/packages/suite.whl", "yanked": False,
             "digests": {"sha256": "a" * 64}},
            {"filename": "seam_suite-2.4.1rc1.tar.gz", "packagetype": "sdist",
             "url": "https://files.pythonhosted.org/packages/suite.tar.gz", "yanked": False,
             "digests": {"sha256": "b" * 64}},
        ],
    }


def test_repository_manifest_tracks_installable_suite():
    from tools.release.verify_mcp_registry import validate_manifest

    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    manifest = json.loads((ROOT / "server.json").read_text())
    assert validate_manifest(project, manifest, (ROOT / "README.md").read_text()) == project["version"]


def test_local_candidate_validation_does_not_authorize_publication(project, manifest):
    from tools.release.verify_mcp_registry import validate_manifest

    project["classifiers"] = ["Private :: Do Not Upload"]
    assert validate_manifest(project, manifest, MARKER) == "2.4.1rc1"


@pytest.mark.parametrize("change", ["name", "repository", "version", "package", "package_version",
                                         "transport", "runtime", "arguments", "extra_package", "remote",
                                         "registry_base", "entrypoint", "marker", "requested_version"])
def test_manifest_rejects_wrong_install_identity(project, manifest, change):
    from tools.release.verify_mcp_registry import validate_manifest

    readme, requested = MARKER, "2.4.1rc1"
    package = manifest["packages"][0]
    if change == "name":
        manifest["name"] = "io.github.BlackhatShiftey/seam-runtime"
    elif change == "repository":
        manifest["repository"]["url"] = "https://github.com/BlackhatShiftey/Seam_Runtime"
    elif change == "version":
        manifest["version"] = "2.4.0"
    elif change == "package":
        package["identifier"] = "seam-api"
    elif change == "package_version":
        package["version"] = "latest"
    elif change == "transport":
        package["transport"] = {"type": "streamable-http"}
    elif change == "runtime":
        package["runtimeHint"] = "python"
    elif change == "arguments":
        package["runtimeArguments"].append({"type": "positional", "value": "seam-mcp"})
    elif change == "extra_package":
        manifest["packages"].append(copy.deepcopy(package))
    elif change == "remote":
        manifest["remotes"] = [{"type": "streamable-http", "url": "https://example.com/mcp"}]
    elif change == "registry_base":
        package["registryBaseUrl"] = "https://test.pypi.org"
    elif change == "entrypoint":
        project["scripts"]["seam-mcp"] = "missing:main"
    elif change == "marker":
        readme = "No ownership marker"
    elif change == "requested_version":
        requested = "2.4.0"
    with pytest.raises(ValueError):
        validate_manifest(project, manifest, readme, expected_version=requested)


def test_public_release_accepts_exact_non_yanked_artifacts(manifest, published):
    from tools.release.verify_mcp_registry import validate_pypi_release

    validate_pypi_release(manifest, published)


@pytest.mark.parametrize("change", ["name", "version", "marker", "yanked", "no_wheel", "no_sdist",
                                         "filename", "digest", "host", "empty", "wrong_type"])
def test_public_release_rejects_unusable_or_unowned_artifacts(manifest, published, change):
    from tools.release.verify_mcp_registry import validate_pypi_release

    if change in {"name", "version"}:
        published["info"][change] = "wrong"
    elif change == "marker":
        published["info"]["description"] = "<!-- mcp-name: io.github.someone/another-server -->"
    elif change == "yanked":
        published["urls"][0]["yanked"] = True
    elif change == "no_wheel":
        published["urls"] = published["urls"][1:]
    elif change == "no_sdist":
        published["urls"] = published["urls"][:1]
    elif change == "filename":
        published["urls"][0]["filename"] = "seam_runtime-1.3.1-py3-none-any.whl"
    elif change == "digest":
        published["urls"][0]["digests"]["sha256"] = "not-a-hash"
    elif change == "host":
        published["urls"][0]["url"] = "https://example.com/suite.whl"
    elif change == "empty":
        published["urls"] = []
    elif change == "wrong_type":
        published["urls"][0] = None
    with pytest.raises(ValueError):
        validate_pypi_release(manifest, published)


def test_private_candidate_stops_before_any_registry_request(monkeypatch, project, manifest):
    from tools.release import verify_mcp_registry

    project["classifiers"] = ["Private :: Do Not Upload"]

    def unexpected_network(*args, **kwargs):
        pytest.fail("Private candidate reached a registry request")

    monkeypatch.setattr(verify_mcp_registry, "urlopen", unexpected_network)
    with pytest.raises(ValueError, match="Private :: Do Not Upload"):
        verify_mcp_registry.verify_published(project, manifest)


def test_registry_workflow_requires_manual_protected_head_and_approver():
    import yaml

    workflow = yaml.safe_load((ROOT / ".github/workflows/mcp-registry.yml").read_text())
    # PyYAML's YAML 1.1 parser treats unquoted 'on' as True.
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"workflow_dispatch"}
    job = workflow["jobs"]["publish"]
    guard = job["if"]
    for required in ("refs/heads/main", "MCP_REGISTRY_APPROVER", "github.actor", "github.triggering_actor",
                     "github.run_attempt"):
        assert required in guard
    assert job["permissions"] == {"contents": "read", "id-token": "write"}
    steps = "\n".join(step.get("run", "") for step in job["steps"])
    assert steps.index("tools.release.verify_mcp_registry") < steps.index("login github-oidc")
    assert steps.index("validate server.json") < steps.index("publish server.json")
    assert "--published" in steps
    assert "git rev-parse origin/main" in steps
