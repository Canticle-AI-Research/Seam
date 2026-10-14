from __future__ import annotations

import gzip
import hashlib
import io
import os
import shutil
import stat
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
PUBLISH_RELEASE = REPO_ROOT / ".github" / "workflows" / "publish-private-release.yml"
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
    assert "tools.release.release_version" in raw
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
    assert "Publish reviewed private release" in checklist
    assert "Do not publish the draft directly" in checklist

    follow_up_raw = PUBLISH_RELEASE.read_text(encoding="utf-8")
    follow_up = yaml.safe_load(follow_up_raw)
    assert follow_up["permissions"] == {"actions": "read", "contents": "read"}
    publish_job = follow_up["jobs"]["publish-reviewed-draft"]
    authorize_job = follow_up["jobs"]["authorize-publisher"]
    assert authorize_job["permissions"] == {}
    assert "PRIVATE_RELEASE_APPROVER" in follow_up_raw
    assert "TRIGGERING_ACTOR" in follow_up_raw
    assert "RUN_ATTEMPT" in follow_up_raw
    assert "Publication workflow reruns are forbidden" in follow_up_raw
    assert "Only the configured private release operator" in follow_up_raw
    assert publish_job["needs"] == "authorize-publisher"
    assert publish_job["environment"] == "private-package-release"
    assert publish_job["permissions"] == {"actions": "read", "contents": "write"}
    assert "git/ref/tags/v${VERSION}" in follow_up_raw
    assert "EXPECTED_SHA" in follow_up_raw
    assert "EXPECTED_RUN_ID" in follow_up_raw
    assert "actions/runs/${EXPECTED_RUN_ID}" in follow_up_raw
    assert 'run_path}' in follow_up_raw
    assert 'run_sha}' in follow_up_raw
    assert 'gh run download "${EXPECTED_RUN_ID}"' in follow_up_raw
    assert "prepared-assets" in follow_up_raw
    assert "trusted preparation-run artifact bytes" in follow_up_raw
    assert "EXPECTED_NOTES_SHA256" in follow_up_raw
    assert "IMMUTABILITY_CONFIRMED" in follow_up_raw
    assert '${EXPECTED_SHA,,}' in follow_up_raw
    assert '.object.type == "commit"' in follow_up_raw
    assert "current protected-main head" in follow_up_raw
    assert "gh release download" in follow_up_raw
    assert "sha256sum --status --check" in follow_up_raw
    assert "tools.release.verify_private_artifacts" in follow_up_raw
    assert "--expected-name seam-suite" in follow_up_raw
    assert "SHA256SUMS.txt must cover exactly" in follow_up_raw
    assert "final_main_sha" in follow_up_raw
    assert "sha256sum --status --check" in follow_up_raw
    assert ".prerelease" in follow_up_raw
    assert "release_title" in follow_up_raw
    assert '"SEAM ${VERSION}"' in follow_up_raw
    assert '"release-title"' in follow_up_raw
    assert 'export RELEASE_TITLE="${release_title}"' in follow_up_raw
    assert ".immutable" in follow_up_raw
    assert "include_binary=True" in follow_up_raw
    assert "gh release edit" in follow_up_raw
    assert "tools.release.release_version" in follow_up_raw
    assert "pypi" not in follow_up_raw.casefold()
    assert "seam-tui --help" in raw
    assert "seam-dash --help" in raw
    assert 'python -I "$repo_root/tests/package/smoke_installed_suite.py"' in raw
    assert '"${wheel}[server,pgvector]"' not in raw
    assert '"seam-client==2.0.0"' not in raw


def test_repository_tests_declare_yaml_directly() -> None:
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lint = project["project"]["optional-dependencies"]["lint"]
    assert any(requirement.casefold().startswith("pyyaml") for requirement in lint)
    assert any(requirement.casefold().startswith("packaging") for requirement in lint)
    assert "PyYAML" in CI_WORKFLOW.read_text(encoding="utf-8")


def _release_environment(tmp_path: Path, *, project_version: str, requested: str) -> dict[str, str]:
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "seam-suite"\nversion = {project_version!r}\n',
        encoding="utf-8",
    )
    output = tmp_path / "github-output.txt"
    env = os.environ.copy()
    env.update({
        "GITHUB_OUTPUT": str(output),
        "REQUESTED_VERSION": requested,
        "PYTHONPATH": str(REPO_ROOT),
        "PATH": os.pathsep.join([str(Path(sys.executable).parent), env.get("PATH", "")]),
    })
    return env


def _run_bash(script: str, *, cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required for release workflow boundary tests")
    return subprocess.run(
        [bash, "-eu", "-o", "pipefail", "-c", script],
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _run_version_step(tmp_path: Path, *, project_version: str, requested: str) -> subprocess.CompletedProcess[str]:
    document = yaml.safe_load(PACKAGE_RELEASE.read_text(encoding="utf-8"))
    step = next(step for step in document["jobs"]["build"]["steps"] if step.get("id") == "version")
    env = _release_environment(tmp_path, project_version=project_version, requested=requested)
    return _run_bash(step["run"], cwd=tmp_path, env=env)


def _run_publish_validation(
    tmp_path: Path, *, project_version: str, requested: str, draft_prerelease: bool = False
) -> subprocess.CompletedProcess[str]:
    document = yaml.safe_load(PUBLISH_RELEASE.read_text(encoding="utf-8"))
    step = next(
        step for step in document["jobs"]["publish-reviewed-draft"]["steps"]
        if step["name"] == "Reverify reviewed draft and publish"
    )
    # Run the real version, provenance and draft-classification gates. Stop at
    # artifact downloads: this harness never reaches a publication command.
    script = step["run"].split("mkdir prepared-assets draft-assets", 1)[0]
    stub = tmp_path / "gh-stub.py"
    stub.write_text(
        "import os, sys\n"
        "args = sys.argv[1:]\n"
        "query = args[-1]\n"
        "if args[0] == 'api' and '/actions/runs/' in args[1]:\n"
        "    print('\\t'.join(['.github/workflows/package-release.yml', 'workflow_dispatch', "
        "'completed', 'success', 'main', os.environ['EXPECTED_SHA']]))\n"
        "elif args[0] == 'api' and '/git/ref/' in args[1]:\n"
        "    print(os.environ['EXPECTED_SHA'])\n"
        "elif query == '.isDraft':\n"
        "    print('true')\n"
        "elif query == '.prerelease':\n"
        "    print(os.environ['DRAFT_PRERELEASE'])\n"
        "elif query == '.name':\n"
        "    print('SEAM ' + os.environ['VERSION'])\n"
        "elif args[0] == 'api' and '/releases/tags/' in args[1]:\n"
        "    print('{}')\n"
        "else:\n"
        "    raise SystemExit('unexpected GitHub operation in validation test')\n",
        encoding="utf-8",
    )
    script = 'gh() { python "$GH_STUB" "$@"; }\n' + script
    env = _release_environment(tmp_path, project_version=project_version, requested=requested)
    env.update({
        "VERSION": requested,
        "EXPECTED_SHA": "a" * 40,
        "WORKFLOW_SHA": "a" * 40,
        "EXPECTED_MANIFEST_SHA256": "b" * 64,
        "EXPECTED_NOTES_SHA256": "c" * 64,
        "EXPECTED_RUN_ID": "123",
        "IMMUTABILITY_CONFIRMED": "true",
        "DEFAULT_BRANCH": "main",
        "GITHUB_REPOSITORY": "example/seam",
        "DRAFT_PRERELEASE": str(draft_prerelease).lower(),
        "GH_STUB": str(stub),
    })
    return _run_bash(script, cwd=tmp_path, env=env)


@pytest.mark.parametrize("stage", ["preparation", "publication"])
@pytest.mark.parametrize(
    "requested",
    [
        " 2.4.0", "2.4.0 ", "v2.4.0", "2.4", "02.4.0", "2.4.0.0",
        "2.4.0-rc.1", "2.4.0RC1", "2.4.0rc01", "2.4.0alpha1",
        "1!2.4.0", "2.4.0+build.1", "not-a-version", "2.4.0post1",
    ],
)
def test_release_rejects_noncanonical_python_versions(
    tmp_path: Path, stage: str, requested: str
) -> None:
    runner = _run_version_step if stage == "preparation" else _run_publish_validation
    result = runner(tmp_path, project_version=requested, requested=requested)

    assert result.returncode != 0
    assert "canonical public PEP 440" in result.stderr


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("2.5.0", False), ("2.4.1rc1", True), ("2.5.0a1", True),
        ("2.5.0b2", True), ("2.5.0.dev1", True), ("2.5.0.post1", False),
        ("2.5.0rc1.dev2", True), ("2.5.0.post1.dev2", True),
    ],
)
@pytest.mark.parametrize("stage", ["preparation", "publication"])
def test_release_classifies_canonical_python_versions(
    tmp_path: Path, stage: str, version: str, expected: bool
) -> None:
    if stage == "preparation":
        result = _run_version_step(tmp_path, project_version=version, requested=version)
    else:
        result = _run_publish_validation(
            tmp_path, project_version=version, requested=version, draft_prerelease=expected
        )

    assert result.returncode == 0, result.stderr
    if stage == "preparation":
        assert (tmp_path / "github-output.txt").read_text(encoding="utf-8").splitlines() == [
            f"version={version}", f"prerelease={str(expected).lower()}",
        ]


@pytest.mark.parametrize("stage", ["preparation", "publication"])
def test_release_requires_exact_project_version(tmp_path: Path, stage: str) -> None:
    runner = _run_version_step if stage == "preparation" else _run_publish_validation
    result = runner(tmp_path, project_version="2.4.1rc1", requested="2.4.1")

    assert result.returncode != 0
    assert "does not match" in result.stderr


@pytest.mark.parametrize(("version", "draft_prerelease"), [("2.4.1", True), ("2.4.1rc1", False)])
def test_publication_refuses_changed_prerelease_classification(
    tmp_path: Path, version: str, draft_prerelease: bool
) -> None:
    result = _run_publish_validation(
        tmp_path, project_version=version, requested=version, draft_prerelease=draft_prerelease
    )

    assert result.returncode != 0
    assert "prerelease classification changed" in result.stderr


def test_private_artifact_verifier_accepts_one_clean_wheel_and_sdist(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_suite-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_suite-2.5.0.tar.gz"
    _write_wheel(wheel, {"seam_runtime/__init__.py": b"VERSION = '2.5.0'\n"})
    _write_sdist(sdist, {"seam_suite-2.5.0/README.md": b"private runtime\n"})
    assert verify_artifacts([wheel, sdist]) == []


@pytest.mark.parametrize("version", ["2.5.0", "2.4.1rc1"])
def test_private_artifact_verifier_binds_distribution_identity(tmp_path: Path, version: str) -> None:
    wheel = tmp_path / f"seam_suite-{version}-py3-none-any.whl"
    sdist = tmp_path / f"seam_suite-{version}.tar.gz"
    metadata = f"Metadata-Version: 2.4\nName: seam-suite\nVersion: {version}\n\n".encode()
    _write_wheel(
        wheel,
        {
            "seam_runtime/__init__.py": b"",
            f"seam_suite-{version}.dist-info/METADATA": metadata,
        },
    )
    _write_sdist(
        sdist,
        {
            f"seam_suite-{version}/PKG-INFO": metadata,
            f"seam_suite-{version}/README.md": b"private runtime\n",
        },
    )

    assert verify_artifacts(
        [wheel, sdist], expected_name="seam-suite", expected_version=version
    ) == []
    findings = verify_artifacts(
        [wheel, sdist], expected_name="seam-suite", expected_version="2.6.0"
    )
    assert sum("version_mismatch" in finding for finding in findings) == 4


@pytest.mark.parametrize(("expected", "alias"), [("2.5.0", "2.5"), ("2.4.1rc1", "2.4.1RC01")])
@pytest.mark.parametrize("alias_location", ["filename", "metadata"])
def test_private_artifact_verifier_rejects_version_aliases(
    tmp_path: Path, expected: str, alias: str, alias_location: str
) -> None:
    filename_version = alias if alias_location == "filename" else expected
    metadata_version = alias if alias_location == "metadata" else expected
    wheel = tmp_path / f"seam_suite-{filename_version}-py3-none-any.whl"
    sdist = tmp_path / f"seam_suite-{filename_version}.tar.gz"
    metadata = f"Metadata-Version: 2.4\nName: seam-suite\nVersion: {metadata_version}\n\n".encode()
    _write_wheel(wheel, {f"seam_suite-{filename_version}.dist-info/METADATA": metadata})
    _write_sdist(sdist, {f"seam_suite-{filename_version}/PKG-INFO": metadata})

    findings = verify_artifacts([wheel, sdist], expected_name="seam-suite", expected_version=expected)

    prefix = "artifact" if alias_location == "filename" else "metadata"
    assert sum(f"{prefix}_version_mismatch" in finding for finding in findings) == 2


@pytest.mark.parametrize(
    ("expected", "artifact_version", "accepted"),
    [
        ("2.5.0", "2.5.0", True), ("2.4.1rc1", "2.4.1rc1", True),
        ("2.5.0", "2.5", False), ("2.4.1rc1", "2.4.1RC01", False),
    ],
)
def test_publication_binds_exact_artifact_version(
    tmp_path: Path, expected: str, artifact_version: str, accepted: bool
) -> None:
    document = yaml.safe_load(PUBLISH_RELEASE.read_text(encoding="utf-8"))
    step = next(
        step for step in document["jobs"]["publish-reviewed-draft"]["steps"]
        if step["name"] == "Reverify reviewed draft and publish"
    )
    scripts = [part.split("\nPY", 1)[0] for part in step["run"].split("python - <<'PY'\n")[1:]]
    script = next(script for script in scripts if 'Path("prepared-assets")' in script)
    for directory_name in ("prepared-assets", "draft-assets"):
        directory = tmp_path / directory_name
        directory.mkdir()
        members = {
            f"seam_suite-{artifact_version}-py3-none-any.whl": b"wheel fixture",
            f"seam_suite-{artifact_version}.tar.gz": b"sdist fixture",
        }
        for name, content in members.items():
            (directory / name).write_bytes(content)
        (directory / "SHA256SUMS.txt").write_text(
            "".join(f"{hashlib.sha256(content).hexdigest()}  {name}\n" for name, content in members.items()),
            encoding="utf-8",
        )
    env = _release_environment(tmp_path, project_version=expected, requested=expected)
    env["VERSION"] = expected
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True, check=False,
    )

    if accepted:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
        assert "Unexpected draft artifact identity" in result.stderr


def test_private_artifact_verifier_binds_wheel_metadata_directory(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_suite-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_suite-2.5.0.tar.gz"
    metadata = b"Metadata-Version: 2.4\nName: seam-suite\nVersion: 2.5.0\n\n"
    _write_wheel(wheel, {"other-1.0.dist-info/METADATA": metadata})
    _write_sdist(sdist, {"seam_suite-2.5.0/PKG-INFO": metadata})

    findings = verify_artifacts(
        [wheel, sdist], expected_name="seam-suite", expected_version="2.5.0"
    )

    assert any("expected_one_metadata_member" in finding for finding in findings)


def test_private_artifact_verifier_binds_sdist_root_directory(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_suite-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_suite-2.5.0.tar.gz"
    metadata = b"Metadata-Version: 2.4\nName: seam-suite\nVersion: 2.5.0\n\n"
    _write_wheel(
        wheel,
        {"seam_suite-2.5.0.dist-info/METADATA": metadata},
    )
    _write_sdist(
        sdist,
        {
            "other-project/PKG-INFO": metadata,
            "other-project/README.md": b"misleading root\n",
        },
    )

    findings = verify_artifacts(
        [wheel, sdist], expected_name="seam-suite", expected_version="2.5.0"
    )

    assert any("sdist_root_mismatch" in finding for finding in findings)
    assert any("expected_one_metadata_member" in finding for finding in findings)


def test_private_artifact_verifier_rejects_payload_bearing_zip_directory(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_suite-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_suite-2.5.0.tar.gz"
    secret = ("sk-" + "proj-" + "9" * 24).encode()
    with zipfile.ZipFile(wheel, mode="w") as archive:
        directory = zipfile.ZipInfo("seam_runtime/")
        directory.external_attr = (stat.S_IFDIR | 0o755) << 16
        archive.writestr(directory, secret, compress_type=zipfile.ZIP_DEFLATED)
    _write_sdist(sdist, {"seam_suite-2.5.0/README.md": b"private runtime\n"})

    findings = verify_artifacts([wheel, sdist])

    assert any("payload_directory_member" in finding for finding in findings)
    assert secret.decode() not in "\n".join(findings)


def test_private_artifact_verifier_rejects_payload_bearing_tar_directory(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_suite-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_suite-2.5.0.tar.gz"
    _write_wheel(wheel, {"seam_runtime/__init__.py": b""})
    with tarfile.open(sdist, mode="w:gz") as archive:
        directory = tarfile.TarInfo("seam_suite-2.5.0/")
        directory.type = tarfile.DIRTYPE
        directory.size = 7
        archive.addfile(directory, io.BytesIO(b"payload"))

    findings = verify_artifacts([wheel, sdist])

    assert any("payload_directory_member" in finding for finding in findings)


def test_private_artifact_verifier_rejects_secret_and_unsafe_paths(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_suite-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_suite-2.5.0.tar.gz"
    secret = ("sk-" + "proj-" + "a" * 24).encode()
    _write_wheel(wheel, {"seam_runtime/config.py": b"TOKEN = b'" + secret + b"'\n"})
    _write_sdist(sdist, {"../credentials.txt": b"not allowed\n"})
    findings = verify_artifacts([wheel, sdist])
    assert any("api_key" in finding for finding in findings)
    assert any("unsafe_member_path" in finding for finding in findings)


def test_private_artifact_verifier_scans_secret_patterns_in_member_paths(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_suite-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_suite-2.5.0.tar.gz"
    secret = "sk-" + "proj-" + "8" * 24
    _write_wheel(wheel, {"seam_runtime/__init__.py": b""})
    _write_sdist(
        sdist,
        {f"seam_suite-2.5.0/{secret}.txt": b"clean payload\n"},
    )

    findings = verify_artifacts([wheel, sdist])

    assert any("secret_in_member_path" in finding for finding in findings)
    assert secret not in "\n".join(findings)


def test_private_artifact_verifier_scans_bounded_binary_members(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_suite-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_suite-2.5.0.tar.gz"
    secret = ("sk-" + "proj-" + "b" * 24).encode()
    _write_wheel(
        wheel,
        {"seam_runtime/webui/leak.png": b"\x89PNG\r\n\x1a\nmetadata=" + secret},
    )
    _write_sdist(sdist, {"seam_suite-2.5.0/README.md": b"private runtime\n"})

    findings = verify_artifacts([wheel, sdist])

    assert any("api_key" in finding for finding in findings)


@pytest.mark.parametrize("encoding", ["utf-16-le", "utf-16-be"])
def test_private_artifact_verifier_scans_utf16_members(
    tmp_path: Path, encoding: str
) -> None:
    wheel = tmp_path / "seam_suite-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_suite-2.5.0.tar.gz"
    secret = "sk-" + "proj-" + "d" * 24
    _write_wheel(wheel, {"seam_runtime/settings.txt": secret.encode(encoding)})
    _write_sdist(sdist, {"seam_suite-2.5.0/README.md": b"private runtime\n"})

    assert any("api_key" in finding for finding in verify_artifacts([wheel, sdist]))


def test_private_artifact_verifier_scans_unreferenced_container_bytes(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_suite-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_suite-2.5.0.tar.gz"
    secret = ("sk-" + "proj-" + "f" * 24).encode()
    _write_wheel(wheel, {"seam_runtime/__init__.py": b""})
    with wheel.open("ab") as stream:
        stream.write(secret)
    _write_sdist(sdist, {"seam_suite-2.5.0/README.md": b"private runtime\n"})

    assert any("api_key" in finding for finding in verify_artifacts([wheel, sdist]))


def test_private_artifact_verifier_scans_unreferenced_decompressed_sdist_bytes(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "seam_suite-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_suite-2.5.0.tar.gz"
    secret = ("sk-" + "proj-" + "7" * 24).encode()
    _write_wheel(wheel, {"seam_runtime/__init__.py": b""})
    raw_tar = io.BytesIO()
    with tarfile.open(fileobj=raw_tar, mode="w") as archive:
        content = b"private runtime\n"
        info = tarfile.TarInfo("seam_suite-2.5.0/README.md")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    sdist.write_bytes(gzip.compress(raw_tar.getvalue() + secret))

    assert any("api_key" in finding for finding in verify_artifacts([wheel, sdist]))


def test_private_artifact_verifier_rejects_credential_prefixed_and_drive_paths(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "seam_suite-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_suite-2.5.0.tar.gz"
    _write_wheel(
        wheel,
        {
            "seam_runtime/credentials.json": b"placeholder\n",
            "seam_runtime/secrets.txt": b"placeholder\n",
            "seam_runtime/.env.production": b"placeholder\n",
            "seam_runtime/client_secret.json": b'{"client_secret":"ordinary-password"}\n',
            "seam_runtime/passwords.json": b'{"password":"ordinary-password"}\n',
            "seam_runtime/token.json": b'{"access_token":"ordinary-password-value"}\n',
            "seam_runtime/auth.json": b'{"auth":"ordinary-password-value"}\n',
            "seam_runtime/oauth2.json": b'{"access_token":"ordinary-password-value"}\n',
            "seam_runtime/authtoken.json": b'{"access_token":"ordinary-password-value"}\n',
            "seam_runtime/tokenstore.json": b'{"access_token":"ordinary-password-value"}\n',
            "seam_runtime/oauthcache.json": b'{"access_token":"ordinary-password-value"}\n',
            "C:/credentials.json": b"placeholder\n",
        },
    )
    _write_sdist(sdist, {"seam_suite-2.5.0/README.md": b"private runtime\n"})

    findings = verify_artifacts([wheel, sdist])

    assert sum("credential_path" in finding for finding in findings) >= 11
    assert any("unsafe_member_path" in finding for finding in findings)


def test_private_artifact_verifier_rejects_nested_archives(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_suite-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_suite-2.5.0.tar.gz"
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
    _write_sdist(sdist, {"seam_suite-2.5.0/README.md": b"private runtime\n"})

    findings = verify_artifacts([wheel, sdist])

    assert sum("nested_archive" in finding for finding in findings) == 5


def test_private_artifact_verifier_rejects_casefolded_duplicate_paths(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_suite-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_suite-2.5.0.tar.gz"
    _write_wheel(
        wheel,
        {
            "seam_runtime/config.py": b"LOWER = True\n",
            "seam_runtime/CONFIG.py": b"UPPER = True\n",
        },
    )
    _write_sdist(sdist, {"seam_suite-2.5.0/README.md": b"private runtime\n"})

    findings = verify_artifacts([wheel, sdist])

    assert any("duplicate_member" in finding for finding in findings)


@pytest.mark.parametrize("unsafe_name", ["config.py.", "config.py "])
def test_private_artifact_verifier_rejects_windows_trimmed_paths(
    tmp_path: Path, unsafe_name: str
) -> None:
    wheel = tmp_path / "seam_suite-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_suite-2.5.0.tar.gz"
    _write_wheel(
        wheel,
        {
            "seam_runtime/config.py": b"SAFE = True\n",
            f"seam_runtime/{unsafe_name}": b"COLLISION = True\n",
        },
    )
    _write_sdist(sdist, {"seam_suite-2.5.0/README.md": b"private runtime\n"})

    findings = verify_artifacts([wheel, sdist])

    assert any("unsafe_member_path" in finding for finding in findings)


@pytest.mark.parametrize("reserved_name", ["CON.py", "aux.txt", "COM1.js", "lpt9"])
def test_private_artifact_verifier_rejects_windows_device_names(
    tmp_path: Path, reserved_name: str
) -> None:
    wheel = tmp_path / "seam_suite-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_suite-2.5.0.tar.gz"
    _write_wheel(wheel, {f"seam_runtime/{reserved_name}": b"unsafe\n"})
    _write_sdist(sdist, {"seam_suite-2.5.0/README.md": b"private runtime\n"})

    assert any("unsafe_member_path" in finding for finding in verify_artifacts([wheel, sdist]))


@pytest.mark.parametrize("invalid_character", ["<", ">", ":", '"', "|", "?", "*"])
def test_private_artifact_verifier_rejects_windows_invalid_characters(
    tmp_path: Path, invalid_character: str
) -> None:
    wheel = tmp_path / "seam_suite-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_suite-2.5.0.tar.gz"
    _write_wheel(
        wheel,
        {f"seam_runtime/webui/foo{invalid_character}.txt": b"unsafe\n"},
    )
    _write_sdist(sdist, {"seam_suite-2.5.0/README.md": b"private runtime\n"})

    assert any("unsafe_member_path" in finding for finding in verify_artifacts([wheel, sdist]))


def test_private_artifact_verifier_rejects_windows_control_characters(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_suite-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_suite-2.5.0.tar.gz"
    _write_wheel(wheel, {"seam_runtime/foo\x01.txt": b"unsafe\n"})
    _write_sdist(sdist, {"seam_suite-2.5.0/README.md": b"private runtime\n"})

    assert any("unsafe_member_path" in finding for finding in verify_artifacts([wheel, sdist]))


def test_private_artifact_verifier_redacts_member_names(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_suite-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_suite-2.5.0.tar.gz"
    leaked = "sk-" + "proj-" + "c" * 24
    _write_wheel(
        wheel,
        {f"seam_runtime/client_secret_{leaked}.json": b"placeholder\n"},
    )
    _write_sdist(sdist, {"seam_suite-2.5.0/README.md": b"private runtime\n"})

    findings = verify_artifacts([wheel, sdist])

    assert findings
    assert leaked not in "\n".join(findings)
    assert any("member[" in finding for finding in findings)


def test_private_artifact_verifier_redacts_archive_read_failures(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_suite-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_suite-2.5.0.tar.gz"
    leaked = "private-filename-do-not-echo"
    _write_wheel(wheel, {f"seam_runtime/{leaked}.txt": b"placeholder\n"})
    content = bytearray(wheel.read_bytes())
    local_header = content.index(b"PK\x03\x04")
    central_header = content.index(b"PK\x01\x02")
    content[local_header + 6 : local_header + 8] = (1).to_bytes(2, "little")
    content[central_header + 8 : central_header + 10] = (1).to_bytes(2, "little")
    wheel.write_bytes(content)
    _write_sdist(sdist, {"seam_suite-2.5.0/README.md": b"private runtime\n"})

    findings = verify_artifacts([wheel, sdist])

    assert any("unreadable_member" in finding for finding in findings)
    assert leaked not in "\n".join(findings)


def test_operations_status_records_merged_s6() -> None:
    raw = OPERATIONS_STATUS.read_text(encoding="utf-8")
    assert "S6 (principal tenancy and opaque deletion) is published" in raw
    assert "Fourth-head CI/final review and merge remain" not in raw

    for path in (
        REPO_ROOT / "REPO_LEDGER.md",
        REPO_ROOT / "docs" / "status" / "retrieval.md",
        REPO_ROOT / "docs" / "status" / "surfaces.md",
    ):
        status = path.read_text(encoding="utf-8").casefold()
        assert "unpublished s6" not in status
        assert "the fourth head still needs exact-head ci" not in status


def test_private_artifact_verifier_rejects_non_regular_sdist_members(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_suite-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_suite-2.5.0.tar.gz"
    _write_wheel(wheel, {"seam_runtime/__init__.py": b""})
    with tarfile.open(sdist, mode="w:gz") as archive:
        link = tarfile.TarInfo("seam_suite-2.5.0/latest")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../outside"
        archive.addfile(link)
    assert any("non_regular_member" in finding for finding in verify_artifacts([wheel, sdist]))
