"""Inspect distribution archives before private release or public publication."""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from tools.release.public_manifest import (
    PUBLIC_CLIENT_SAFE_PATHS,
    is_reserved_material_path,
)

_PRIVATE_MODULE_REFERENCE = re.compile(rb"\bseam_runtime\.[A-Za-z_]")
_DYNAMIC_IMPORT_MARKERS: tuple[bytes, ...] = (
    b"__import__(",
    b"import_module(",
)


def _is_thin_client_file(entry_path: str, content: bytes) -> bool:
    """Return True if a path in PUBLIC_CLIENT_SAFE_PATHS has safe content."""
    if entry_path not in PUBLIC_CLIENT_SAFE_PATHS:
        return False
    if _PRIVATE_MODULE_REFERENCE.search(content):
        return False
    return not any(marker in content for marker in _DYNAMIC_IMPORT_MARKERS)

PRIVATE_LICENSE_MARKER = b"SEAM PRIVATE REPOSITORY, MIRL, AND HS/1 RESERVED MATERIALS LICENSE"
PRIVATE_CLASSIFIER = b"Classifier: Private :: Do Not Upload"
PROPRIETARY_LICENSE_EXPRESSION = (
    b"License-Expression: LicenseRef-SEAM-Proprietary AND BUSL-1.1 AND Apache-2.0"
)


@dataclass(frozen=True)
class ArchiveEntry:
    path: str
    content: bytes


def _normalized_member(path: str, *, strip_archive_root: bool = False) -> str:
    parts = PurePosixPath(path).parts
    if not parts:
        return ""
    # PEP 517 sdists have one generated project-version directory above every
    # file. Strip it unconditionally for tar archives: a distribution named
    # ``seam_runtime`` produces a root such as ``seam_runtime-2.3.0``, so
    # guessing from the root name can hide reserved paths from the scanner.
    if strip_archive_root and len(parts) > 1:
        return str(PurePosixPath(*parts[1:]))
    return str(PurePosixPath(*parts))


def read_archive(path: Path) -> tuple[ArchiveEntry, ...]:
    entries: list[ArchiveEntry] = []
    if path.suffix == ".whl" or zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                entries.append(ArchiveEntry(_normalized_member(info.filename), archive.read(info)))
        return tuple(entries)

    if path.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                extracted = archive.extractfile(member)
                if extracted is not None:
                    entries.append(
                        ArchiveEntry(
                            _normalized_member(member.name, strip_archive_root=True),
                            extracted.read(),
                        )
                    )
        return tuple(entries)

    raise ValueError(f"unsupported distribution archive: {path}")


def _is_license_path(path: str) -> bool:
    return PurePosixPath(path).name in {"LICENSE", "LICENSE.txt", "LICENSE.md"}


def _is_metadata_path(path: str) -> bool:
    return PurePosixPath(path).name in {"METADATA", "PKG-INFO"}


def verify_archive(path: Path, *, target: str) -> tuple[str, ...]:
    entries = read_archive(path)
    errors: list[str] = []
    license_entries = [entry for entry in entries if _is_license_path(entry.path)]
    metadata = b"\n".join(entry.content for entry in entries if _is_metadata_path(entry.path))
    metadata_lines = metadata.splitlines()

    if not license_entries:
        errors.append("distribution has no license file")

    if target == "private-github":
        if not any(PRIVATE_LICENSE_MARKER in entry.content for entry in license_entries):
            errors.append("private distribution is missing the controlling proprietary license")
        if PRIVATE_CLASSIFIER not in metadata_lines:
            errors.append("private distribution metadata lacks 'Private :: Do Not Upload'")
        if PROPRIETARY_LICENSE_EXPRESSION not in metadata_lines:
            errors.append("private distribution metadata lacks the proprietary license expression")
        return tuple(errors)

    if target != "pypi":
        raise ValueError(f"unsupported target: {target}")

    is_runtime_compatibility = b"Name: seam-runtime" in metadata
    unexpected_python = (
        sorted(
            {
                entry.path
                for entry in entries
                if entry.path.endswith(".py") and entry.path not in PUBLIC_CLIENT_SAFE_PATHS
            }
        )
        if is_runtime_compatibility
        else []
    )
    if unexpected_python:
        preview = ", ".join(unexpected_python[:8])
        suffix = "" if len(unexpected_python) <= 8 else f", and {len(unexpected_python) - 8} more"
        errors.append(f"public distribution contains unexpected Python modules: {preview}{suffix}")

    reserved = sorted(
        {
            entry.path
            for entry in entries
            if is_reserved_material_path(entry.path) and not _is_thin_client_file(entry.path, entry.content)
        }
    )
    if reserved:
        preview = ", ".join(reserved[:8])
        suffix = "" if len(reserved) <= 8 else f", and {len(reserved) - 8} more"
        errors.append(f"public distribution contains MIRL or HS/1 Reserved Materials: {preview}{suffix}")

    if any(PRIVATE_LICENSE_MARKER in entry.content for entry in license_entries):
        errors.append("public distribution carries the private SEAM/MIRL/HS/1 license")
    if PRIVATE_CLASSIFIER in metadata or PROPRIETARY_LICENSE_EXPRESSION in metadata:
        errors.append("public distribution metadata identifies a private/proprietary package")

    return tuple(errors)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=("private-github", "pypi"))
    parser.add_argument("archives", nargs="+", type=Path)
    args = parser.parse_args(argv)

    failed = False
    for archive in args.archives:
        try:
            errors = verify_archive(archive, target=args.target)
        except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
            print(f"[distribution-boundary] FAIL {archive}: {exc}", file=sys.stderr)
            failed = True
            continue
        if errors:
            failed = True
            for error in errors:
                print(f"[distribution-boundary] FAIL {archive}: {error}", file=sys.stderr)
        else:
            print(f"[distribution-boundary] PASS {archive} -> {args.target}")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
