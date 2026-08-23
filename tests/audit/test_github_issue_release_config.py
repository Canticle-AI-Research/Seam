from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import yaml

from tools.release.verify_private_artifacts import verify_artifacts

REPO_ROOT = Path(__file__).resolve().parents[2]
ISSUE_TEMPLATE_DIR = REPO_ROOT / ".github" / "ISSUE_TEMPLATE"
PACKAGE_RELEASE = REPO_ROOT / ".github" / "workflows" / "package-release.yml"


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
    assert "RELEASE_SHA: ${{ github.sha }}" in raw
    assert "current protected-main head" in raw
    publish = document["jobs"]["private-github-release"]
    assert publish["environment"] == "private-package-release"
    assert publish["permissions"] == {"contents": "write"}


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
            "C:/credentials.json": b"placeholder\n",
        },
    )
    _write_sdist(sdist, {"seam_runtime-2.5.0/README.md": b"private runtime\n"})

    findings = verify_artifacts([wheel, sdist])

    for name in ("credentials.json", "secrets.txt", ".env.production"):
        assert any(name in finding and "credential_path" in finding for finding in findings)
    assert any("C:/credentials.json" in finding and "unsafe_member_path" in finding for finding in findings)


def test_private_artifact_verifier_rejects_nested_archives(tmp_path: Path) -> None:
    wheel = tmp_path / "seam_runtime-2.5.0-py3-none-any.whl"
    sdist = tmp_path / "seam_runtime-2.5.0.tar.gz"
    _write_wheel(wheel, {"seam_runtime/webui/assets.zip": b"uninspected archive"})
    _write_sdist(sdist, {"seam_runtime-2.5.0/README.md": b"private runtime\n"})

    findings = verify_artifacts([wheel, sdist])

    assert any("assets.zip" in finding and "nested_archive" in finding for finding in findings)


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
