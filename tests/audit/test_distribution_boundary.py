from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

from tools.release.verify_distribution_boundary import verify_archive

PRIVATE_LICENSE = b"SEAM PRIVATE REPOSITORY, MIRL, AND HS/1 RESERVED MATERIALS LICENSE"
PRIVATE_METADATA = b"\n".join(
    (
        b"Name: seam-runtime",
        b"Classifier: Private :: Do Not Upload",
        b"License-Expression: LicenseRef-SEAM-Proprietary AND BUSL-1.1 AND Apache-2.0",
    )
)


def _wheel(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


def _sdist(path: Path, files: dict[str, bytes], *, root: str = "sample-1.0") -> Path:
    with tarfile.open(path, "w:gz") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(f"{root}/{name}")
            info.size = len(content)
            archive.addfile(info, io.BytesIO(content))
    return path


def test_private_release_accepts_proprietary_wheel(tmp_path: Path) -> None:
    archive = _wheel(
        tmp_path / "seam_runtime-1.0-py3-none-any.whl",
        {
            "seam_runtime/mirl.py": b"reserved",
            "seam_runtime-1.0.dist-info/licenses/LICENSE": PRIVATE_LICENSE,
            "seam_runtime-1.0.dist-info/METADATA": PRIVATE_METADATA,
        },
    )
    assert verify_archive(archive, target="private-github") == ()


def test_private_release_requires_private_metadata(tmp_path: Path) -> None:
    archive = _wheel(
        tmp_path / "bad.whl",
        {
            "sample.py": b"x = 1",
            "sample.dist-info/licenses/LICENSE": PRIVATE_LICENSE,
            "sample.dist-info/METADATA": b"Name: sample",
        },
    )
    errors = verify_archive(archive, target="private-github")
    assert any("Private :: Do Not Upload" in error for error in errors)
    assert any("proprietary license expression" in error for error in errors)


def test_private_release_rejects_a_longer_license_expression(tmp_path: Path) -> None:
    archive = _wheel(
        tmp_path / "wrong-license-expression.whl",
        {
            "seam_runtime/mirl.py": b"reserved",
            "seam_runtime-1.0.dist-info/licenses/LICENSE": PRIVATE_LICENSE,
            "seam_runtime-1.0.dist-info/METADATA": (
                PRIVATE_METADATA + b" OR MIT"
            ),
        },
    )

    errors = verify_archive(archive, target="private-github")

    assert any("proprietary license expression" in error for error in errors)


def test_public_pypi_rejects_mirl_runtime_even_with_public_license(tmp_path: Path) -> None:
    archive = _sdist(
        tmp_path / "seam_runtime-2.3.0.tar.gz",
        {
            "LICENSE": b"MIT License",
            "PKG-INFO": b"Name: sample",
            "seam_runtime/mirl.py": b"reserved",
        },
        root="seam_runtime-2.3.0",
    )
    errors = verify_archive(archive, target="pypi")
    assert any("MIRL or HS/1 Reserved Materials" in error for error in errors)


def test_public_pypi_rejects_hs1_material_even_with_public_license(tmp_path: Path) -> None:
    archive = _wheel(
        tmp_path / "sample-1.0-py3-none-any.whl",
        {
            "docs/HOLOGRAPHIC_SURFACE.md": b"reserved",
            "sample.dist-info/licenses/LICENSE": b"MIT License",
            "sample.dist-info/METADATA": b"Name: sample",
        },
    )
    errors = verify_archive(archive, target="pypi")
    assert any("MIRL or HS/1 Reserved Materials" in error for error in errors)


def test_public_pypi_rejects_private_license_and_metadata(tmp_path: Path) -> None:
    archive = _wheel(
        tmp_path / "private.whl",
        {
            "client/__init__.py": b"",
            "private.dist-info/licenses/LICENSE": PRIVATE_LICENSE,
            "private.dist-info/METADATA": PRIVATE_METADATA,
        },
    )
    errors = verify_archive(archive, target="pypi")
    assert any("private SEAM/MIRL/HS/1 license" in error for error in errors)
    assert any("private/proprietary package" in error for error in errors)


def test_public_pypi_accepts_separate_clean_client_artifact(tmp_path: Path) -> None:
    archive = _wheel(
        tmp_path / "seam_client-1.0-py3-none-any.whl",
        {
            "seam_client/__init__.py": b"",
            "seam_client-1.0.dist-info/licenses/LICENSE": b"MIT License",
            "seam_client-1.0.dist-info/METADATA": b"Name: seam-client",
        },
    )
    assert verify_archive(archive, target="pypi") == ()


def test_public_pypi_accepts_fail_closed_runtime_compatibility_shim(tmp_path: Path) -> None:
    archive = _wheel(
        tmp_path / "seam_runtime-2.3.1-py3-none-any.whl",
        {
            "seam.py": b"from seam_client import SeamClient",
            "seam_runtime/__init__.py": b"from seam_client import SeamClient",
            "seam_runtime-2.3.1.dist-info/licenses/LICENSE": b"Apache License",
            "seam_runtime-2.3.1.dist-info/METADATA": b"Name: seam-runtime",
        },
    )
    assert verify_archive(archive, target="pypi") == ()


def test_public_pypi_rejects_dynamic_private_runtime_import(tmp_path: Path) -> None:
    archive = _wheel(
        tmp_path / "seam_runtime-2.3.1-py3-none-any.whl",
        {
            "seam.py": b"from seam_client import SeamClient",
            "seam_runtime/__init__.py": b'_mirl = __import__("seam_runtime.mirl")',
            "seam_runtime-2.3.1.dist-info/licenses/LICENSE": b"Apache License",
            "seam_runtime-2.3.1.dist-info/METADATA": b"Name: seam-runtime",
        },
    )
    errors = verify_archive(archive, target="pypi")
    assert any("MIRL or HS/1 Reserved Materials" in error for error in errors)


def test_public_pypi_rejects_private_module_string_without_import_syntax(tmp_path: Path) -> None:
    archive = _wheel(
        tmp_path / "seam_runtime-2.3.1-py3-none-any.whl",
        {
            "seam.py": b"from seam_client import SeamClient",
            "seam_runtime/__init__.py": b'PRIVATE_MODULE = "seam_runtime.runtime"',
            "seam_runtime-2.3.1.dist-info/licenses/LICENSE": b"Apache License",
            "seam_runtime-2.3.1.dist-info/METADATA": b"Name: seam-runtime",
        },
    )
    errors = verify_archive(archive, target="pypi")
    assert any("MIRL or HS/1 Reserved Materials" in error for error in errors)


def test_public_pypi_rejects_unexpected_python_module(tmp_path: Path) -> None:
    archive = _wheel(
        tmp_path / "seam_runtime-2.3.1-py3-none-any.whl",
        {
            "seam.py": b"from seam_client import SeamClient",
            "seam_runtime/__init__.py": b"from seam_client import SeamClient",
            "seam_runtime/helpers.py": b"VALUE = 1",
            "seam_runtime-2.3.1.dist-info/licenses/LICENSE": b"Apache License",
            "seam_runtime-2.3.1.dist-info/METADATA": b"Name: seam-runtime",
        },
    )
    errors = verify_archive(archive, target="pypi")
    assert any("unexpected Python modules" in error for error in errors)
