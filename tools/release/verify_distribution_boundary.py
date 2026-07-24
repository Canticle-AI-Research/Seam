"""Inspect distribution archives before private release or public publication."""

from __future__ import annotations

import argparse
import sys
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from tools.release.public_manifest import (
    PUBLIC_CLIENT_SAFE_PATHS,
    is_reserved_material_path,
)

# Imports that indicate a file contains MIRL/HS/1 reserved material.
# The thin public client files must NOT import from these.
_MIRL_HS1_IMPORT_MARKERS: tuple[bytes, ...] = (
    b"from .mirl import",
    b"from .runtime import",
    b"from .sdk import",
    b"from .holographic import",
    b"from .lossless import",
    b"from .pack import",
    b"from .storage import",
    b"from .vector import",
    b"from .graph",
    b"from .retrieval import",
    b"from .reconcile import",
    b"from .surface_adapters import",
    b"from .knowledge_graph import",
    b"from .reasoning_graph import",
    b"from seam_runtime.mirl",
    b"from seam_runtime.runtime",
    b"from seam_runtime.holographic",
    b"from seam_runtime.lossless",
    b"from seam_runtime.pack",
    b"from seam_runtime.storage",
    b"from seam_runtime.sdk",
    b"from seam_runtime.retrieval",
    b"from seam_runtime.vector",
    b"from seam_runtime.cli",
    b"from seam_runtime.dashboard",
    b"from seam_runtime.server",
    b"from seam_runtime.surface_adapters",
    b"from seam_runtime.knowledge_graph",
    b"from seam_runtime.reasoning_graph",
)


def _is_thin_client_file(entry_path: str, content: bytes) -> bool:
    """Return True if a path in PUBLIC_CLIENT_SAFE_PATHS has safe content."""
    if entry_path not in PUBLIC_CLIENT_SAFE_PATHS:
        return False
    # Check that the file does NOT import any MIRL/HS/1 internals.
    return not any(marker in content for marker in _MIRL_HS1_IMPORT_MARKERS)

PRIVATE_LICENSE_MARKER = b"SEAM PRIVATE REPOSITORY, MIRL, AND HS/1 RESERVED MATERIALS LICENSE"
PRIVATE_CLASSIFIER = b"Classifier: Private :: Do Not Upload"
PROPRIETARY_LICENSE_EXPRESSION = b"License-Expression: LicenseRef-SEAM-Proprietary AND Apache-2.0"


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

    if not license_entries:
        errors.append("distribution has no license file")

    if target == "private-github":
        if not any(PRIVATE_LICENSE_MARKER in entry.content for entry in license_entries):
            errors.append("private distribution is missing the controlling proprietary license")
        if PRIVATE_CLASSIFIER not in metadata:
            errors.append("private distribution metadata lacks 'Private :: Do Not Upload'")
        if PROPRIETARY_LICENSE_EXPRESSION not in metadata:
            errors.append("private distribution metadata lacks the proprietary license expression")
        return tuple(errors)

    if target != "pypi":
        raise ValueError(f"unsupported target: {target}")

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
