from __future__ import annotations

import io
import os
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest
import yaml

from tools.release.verify_private_artifacts import verify_artifacts

REPO_ROOT = Path(__file__).resolve().parents[2]
ISSUE_TEMPLATE_DIR = REPO_ROOT / ".github" / "ISSUE_TEMPLATE"
PACKAGE_RELEASE = REPO_ROOT / ".github" / "workflows" / "package-release.yml"
RELEASE_CHECKLIST = REPO_ROOT / ".github" / "RELEASE_CHECKLIST.md"
OPERATIONS_STATUS = REPO_ROOT / "docs" / "status" / "operations.md"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _write_wheel(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, mode="w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)


def _write_sdist(path: Path, members: dict[str, bytes]) -> None:
    with tarfile.open(path, mode="w:gz") as archive:
        for name, content in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))


def test_issue_forms_are_structured_and_content_safe() -> None:
    expected = {"bug.yml", "feature.yml", "release.yml", "research.yml"}
    assert expected <= {path.name for path in ISSUE_TEMPLATE_DIR.glob("*.yml")}
    allowed_labels = {"bug", "documentation", "enhancement"}
    for name in expected:
        document = yaml.safe_load((ISSUE_TEMPLATE_DIR / name).read_text(encoding="utf-8"))
        assert document["name"]
        assert document["description"]
        assert document["title"]
        assert set(document.get("labels", [])) <= allowed_labels
        fields = document["body"]
        ids = [field["id"] for field in fields if "id" in field]
        assert len(ids) == len(set(ids))
        assert any(field.get("validations", {}).get("required") for field in fields)

    config = yaml.safe_load((ISSUE_TEMPLATE_DIR / "config.yml").read_text(encoding="utf-8"))
    assert config["blank_issues_enabled"] is False
    security_link = config["contact_links"][0]
    assert security_link["url"].endswith("/security/advisories/new")

    release_form = yaml.safe_load((ISSUE_TEMPLATE_DIR / "release.yml").read_text(encoding="utf-8"))
    boundary = next(field for field in release_form["body"] if field.get("id") == "boundary")
    labels = [option["label"] for option in boundary["attributes"]["options"]]
    assert any("Before publication" in label for label in labels)
    assert not any("already reviewed" in label for label in labels)
    target = next(field for field in release_form["body"] if field.get("id") == "target")
    assert target.get("validations", {}).get("required") is not True


def test_release_notes_config_has_bounded_categories_and_catchall() -> None:
    document = yaml.safe_load((REPO_ROOT / ".github" / "release.yml").read_text(encoding="utf-8"))
    categories = document["changelog"]["categories"]
    assert {category["title"] for category in categories} >= {
        "Features",
        "Fixes",
        "Documentation",
        "Dependencies",
        "Other changes",
    }
    assert any("*" in category["labels"] for category in categories)


def test_package_release_stays_private_and_verifiable() -> None:
    raw = PACKAGE_RELEASE.read_text(encoding="utf-8")
    document = yaml.safe_load(raw)
    assert document["permissions"] == {"contents": "read"}
    assert "id-token" not in raw
    assert "pypi" not in raw.casefold()
    assert "refs/heads/${DEFAULT_BRANCH}" in raw
    assert "not exact SemVer" in raw
    assert "tools.release.verify_private_artifacts" in raw
    assert "SHA256SUMS.txt" in raw
    assert "sha256sum --check" in raw
    assert "--generate-notes" in raw
    assert "git/ref/heads/${DEFAULT_BRANCH}" in raw
    assert "COMMIT_SHA: ${{ github.sha }}" in raw
    assert "current protected-main head" in raw
    assert "prerelease: ${{ steps.version.outputs.prerelease }}" in raw
    assert "--prerelease" in raw
    assert "git/refs" in raw
    assert "--verify-tag" in raw
    publish = document["jobs"]["private-github-release"]
    assert publish["environment"] == "private-package-release"
    assert publish["permissions"] == {"contents": "write"}
    creation = next(
        step for step in publish["steps"] if step["name"] == "Create private GitHub release draft"
    )
    run = creation["run"]
    assert run.index("git/ref/heads/${DEFAULT_BRANCH}") < run.index('ref="refs/tags/v${VERSION}"')
    assert "--draft" in run
    assert "gh release edit" not in run
    assert "cleanup_failed_publication" in run
    assert "draft" in run
    checklist = RELEASE_CHECKLIST.read_text(encoding="utf-8")
    assert "Review the generated draft release notes" in checklist
    assert "manually publish the reviewed draft" in checklist


def test_repository_tests_declare_yaml_directly() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lint = project["project"]["optional-dependencies"]["lint"]
    assert any(requirement.casefold().startswith("pyyaml") for requirement in lint)
    assert "PyYAML" in CI_WORKFLOW.read_text(encoding="utf-8")


def _run_version_step(tmp_path: Path, *, project_version: str, requested: str) -> subprocess.CompletedProcess[str]:
    document = yaml.safe_load(PACKAGE_RELEASE.read_text(encoding="utf-8"))
    step = next(step for step in document["jobs"]["build"]["steps"] if step.get("id") == "version")
    script = step["run"].removeprefix("python - <<'PY'\n").removesuffix("PY\n")
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "seam-runtime"\nversion = "{project_version}"\n',
        encoding="utf-8",
    )
    output = tmp_path / "github-output.txt"
    env = os.environ.copy()
    env.update({"GITHUB_OUTPUT": str(output), "REQUESTED_VERSION": requested})
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize("requested", [" 2.4.0", "2.4.0 "])
def test_package_release_rejects_semver_whitespace(tmp_path: Path, requested: str) -> None:
    result = _run_version_step(tmp_path, project_version="2.4.0", requested=requested)

    assert result.returncode != 0


@pytest.mark.parametrize(
    ("version", "expected"),
    [("2.5.0", "prerelease=false"), ("2.5.0-rc.1", "prerelease=true")],
)
def test_package_release_classifies_semver_prereleases(
    tmp_path: Path, version: str, expected: str
) -> None:
    result = _run_version_step(tmp_path, project_version=version, requested=version)

    assert result.returncode == 0, result.stderr
    assert expected in (tmp_path / "github-output.txt").read_text(encoding="utf-8")


def test_private_artifact_verifier_accepts_one_clean_wheel_and_sdist(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_runtime-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_runtime-2.5.0.tar.gz"
    _write_wheel(wheel, {"seam_runtime/__init__.py": b"VERSION = '2.5.0'\n"})
    _write_sdist(sdist, {"seam_runtime-2.5.0/README.md": b"private runtime\n"})
    assert verify_artifacts([wheel, sdist]) == []


def test_private_artifact_verifier_rejects_secret_and_unsafe_paths(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_runtime-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_runtime-2.5.0.tar.gz"
    secret = ("sk-" + "proj-" + "a" * 24).encode()
    _write_wheel(wheel, {"seam_runtime/config.py": b"TOKEN = b'" + secret + b"'\n"})
    _write_sdist(sdist, {"../credentials.txt": b"not allowed\n"})
    findings = verify_artifacts([wheel, sdist])
    assert any("api_key" in finding for finding in findings)
    assert any("unsafe_member_path" in finding for finding in findings)


def test_private_artifact_verifier_scans_bounded_binary_members(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_runtime-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_runtime-2.5.0.tar.gz"
    secret = ("sk-" + "proj-" + "b" * 24).encode()
    _write_wheel(
        wheel,
        {"seam_runtime/webui/leak.png": b"\x89PNG\r\n\x1a\nmetadata=" + secret},
    )
    _write_sdist(sdist, {"seam_runtime-2.5.0/README.md": b"private runtime\n"})

    findings = verify_artifacts([wheel, sdist])

    assert any("leak.png" in finding and "api_key" in finding for finding in findings)


def test_private_artifact_verifier_rejects_credential_prefixed_and_drive_paths(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "seam_runtime-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_runtime-2.5.0.tar.gz"
    _write_wheel(
        wheel,
        {
            "seam_runtime/credentials.json": b"placeholder\n",
            "seam_runtime/secrets.txt": b"placeholder\n",
            "seam_runtime/.env.production": b"placeholder\n",
            "seam_runtime/client_secret.json": b'{"client_secret":"ordinary-password"}\n',
            "seam_runtime/passwords.json": b'{"password":"ordinary-password"}\n',
            "C:/credentials.json": b"placeholder\n",
        },
    )
    _write_sdist(sdist, {"seam_runtime-2.5.0/README.md": b"private runtime\n"})

    findings = verify_artifacts([wheel, sdist])

    for name in (
        "credentials.json",
        "secrets.txt",
        ".env.production",
        "client_secret.json",
        "passwords.json",
    ):
        assert any(name in finding and "credential_path" in finding for finding in findings)
    assert any("C:/credentials.json" in finding and "unsafe_member_path" in finding for finding in findings)


def test_private_artifact_verifier_rejects_nested_archives(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_runtime-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_runtime-2.5.0.tar.gz"
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, mode="w") as archive:
        archive.writestr(".env", b"PASSWORD=ordinary-password\n")
    _write_wheel(
        wheel,
        {
            "seam_runtime/webui/assets.zip": b"uninspected archive",
            "seam_runtime/webui/assets.jar": nested.getvalue(),
            "seam_runtime/webui/payload.bin": nested.getvalue(),
            "seam_runtime/webui/payload.zst": b"\x28\xb5\x2f\xfdcompressed",
            "seam_runtime/webui/compressed.bin": b"\x28\xb5\x2f\xfdcompressed",
        },
    )
    _write_sdist(sdist, {"seam_runtime-2.5.0/README.md": b"private runtime\n"})

    findings = verify_artifacts([wheel, sdist])

    for name in ("assets.zip", "assets.jar", "payload.bin", "payload.zst", "compressed.bin"):
        assert any(name in finding and "nested_archive" in finding for finding in findings)


def test_private_artifact_verifier_rejects_casefolded_duplicate_paths(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_runtime-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_runtime-2.5.0.tar.gz"
    _write_wheel(
        wheel,
        {
            "seam_runtime/config.py": b"LOWER = True\n",
            "seam_runtime/CONFIG.py": b"UPPER = True\n",
        },
    )
    _write_sdist(sdist, {"seam_runtime-2.5.0/README.md": b"private runtime\n"})

    findings = verify_artifacts([wheel, sdist])

    assert any("CONFIG.py" in finding and "duplicate_member" in finding for finding in findings)


@pytest.mark.parametrize("unsafe_name", ["config.py.", "config.py "])
def test_private_artifact_verifier_rejects_windows_trimmed_paths(
    tmp_path: Path, unsafe_name: str
) -> None:
    wheel = tmp_path / "seam_runtime-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_runtime-2.5.0.tar.gz"
    _write_wheel(
        wheel,
        {
            "seam_runtime/config.py": b"SAFE = True\n",
            f"seam_runtime/{unsafe_name}": b"COLLISION = True\n",
        },
    )
    _write_sdist(sdist, {"seam_runtime-2.5.0/README.md": b"private runtime\n"})

    findings = verify_artifacts([wheel, sdist])

    assert any(unsafe_name in finding and "unsafe_member_path" in finding for finding in findings)


def test_operations_status_records_merged_s6() -> None:
    raw = OPERATIONS_STATUS.read_text(encoding="utf-8")
    assert "S6 (principal tenancy and opaque deletion) is published" in raw
    assert "Fourth-head CI/final review and merge remain" not in raw

    for path in (
        REPO_ROOT / "REPO_LEDGER.md",
        REPO_ROOT / "docs" / "status" / "retrieval.md",
        REPO_ROOT / "docs" / "status" / "surfaces.md",
    ):
        assert "unpublished s6" not in path.read_text(encoding="utf-8").casefold()


def test_private_artifact_verifier_rejects_non_regular_sdist_members(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_runtime-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_runtime-2.5.0.tar.gz"
    _write_wheel(wheel, {"seam_runtime/__init__.py": b""})
    with tarfile.open(sdist, mode="w:gz") as archive:
        link = tarfile.TarInfo("seam_runtime-2.5.0/latest")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        archive.addfile(link)
    assert any("non_regular_member" in finding for finding in verify_artifacts([wheel, sdist]))
