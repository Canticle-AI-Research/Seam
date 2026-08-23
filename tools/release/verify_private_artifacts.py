"""Fail closed on unsafe or secret-bearing private release archives.

The private runtime is intentionally distributable only as an access-scoped
GitHub Release. This verifier checks the built wheel and sdist before upload:
archive members must be regular, relative, unique paths; credential-shaped
paths are forbidden; and text members use SEAM's canonical content-free secret
scanner. Reports never echo matched content.
"""

from __future__ import annotations

import argparse
import stat
import tarfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from tools.security.secret_scan import MAX_SCAN_BYTES, scan_bytes

_DENIED_NAMES = frozenset(
    {
        ".env",
        "credentials",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
    }
)
_DENIED_SUFFIXES = frozenset({".db", ".key", ".p12", ".pem", ".pfx", ".sqlite", ".sqlite3"})
_DENIED_FILENAME_MARKERS = (".env", "credential", "dotenv", "passwd", "password", "secret")
_NESTED_ARCHIVE_SUFFIXES = frozenset(
    {
        ".7z",
        ".br",
        ".bz2",
        ".egg",
        ".gz",
        ".lz4",
        ".rar",
        ".tar",
        ".tgz",
        ".txz",
        ".whl",
        ".xz",
        ".zip",
        ".zst",
        ".zstd",
    }
)


def _validate_member_path(archive: Path, raw_name: str, seen: set[str]) -> str | None:
    if PureWindowsPath(raw_name).drive:
        return f"{archive.name}:{raw_name}: unsafe_member_path"
    normalized = raw_name.replace("\\", "/")
    member = PurePosixPath(normalized)
    if not normalized or not member.parts or member.is_absolute() or ".." in member.parts:
        return f"{archive.name}:{raw_name}: unsafe_member_path"
    if any(part.endswith((".", " ")) for part in member.parts):
        return f"{archive.name}:{raw_name}: unsafe_member_path"
    canonical = member.as_posix()
    canonical_key = unicodedata.normalize("NFC", canonical).casefold()
    if canonical_key in seen:
        return f"{archive.name}:{canonical}: duplicate_member"
    seen.add(canonical_key)
    lowered_parts = tuple(part.casefold() for part in member.parts)
    if any(part in _DENIED_NAMES for part in lowered_parts):
        return f"{archive.name}:{canonical}: credential_path"
    if any(marker in lowered_parts[-1] for marker in _DENIED_FILENAME_MARKERS):
        return f"{archive.name}:{canonical}: credential_path"
    if any(part in {"secrets", "credentials"} for part in lowered_parts[:-1]):
        return f"{archive.name}:{canonical}: credential_directory"
    if member.suffix.casefold() in _DENIED_SUFFIXES:
        return f"{archive.name}:{canonical}: credential_or_database_suffix"
    return None


def _scan_member(archive: Path, name: str, content: bytes) -> list[str]:
    return [
        f"{archive.name}:{finding.path}:{finding.line}: {finding.kind}"
        for finding in scan_bytes(name, content, include_binary=True)
    ]


def _has_archive_magic(header: bytes) -> bool:
    return (
        header.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"))
        or header.startswith(b"\x1f\x8b")
        or header.startswith(b"BZh")
        or header.startswith(b"\xfd7zXZ\x00")
        or header.startswith(b"7z\xbc\xaf'\x1c")
        or header.startswith(b"Rar!\x1a\x07")
        or header.startswith(b"\x28\xb5\x2f\xfd")
        or header.startswith(b"\x04\x22\x4d\x18")
        or len(header) >= 4
        and 0x50 <= header[0] <= 0x5F
        and header[1:4] == b"\x2a\x4d\x18"
        or len(header) >= 262
        and header[257:262] == b"ustar"
    )


def _content_gate(archive: Path, name: str, size: int, header: bytes) -> list[str] | None:
    suffix = Path(name).suffix.casefold()
    if suffix in _NESTED_ARCHIVE_SUFFIXES or _has_archive_magic(header):
        return [f"{archive.name}:{name}:0: nested_archive"]
    if size > MAX_SCAN_BYTES:
        return [f"{archive.name}:{name}:0: scan_size_limit"]
    return None


def _scan_wheel(path: Path) -> list[str]:
    findings: list[str] = []
    seen: set[str] = set()
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                path_finding = _validate_member_path(path, info.filename, seen)
                if path_finding:
                    findings.append(path_finding)
                    continue
                mode = (info.external_attr >> 16) & 0o170000
                if mode == stat.S_IFLNK:
                    findings.append(f"{path.name}:{info.filename}: symbolic_link")
                    continue
                if info.is_dir():
                    continue
                if mode not in {0, stat.S_IFREG}:
                    findings.append(f"{path.name}:{info.filename}: non_regular_member")
                    continue
                with archive.open(info) as stream:
                    header = stream.read(512)
                    content_gate = _content_gate(path, info.filename, info.file_size, header)
                    if content_gate is not None:
                        findings.extend(content_gate)
                        continue
                    findings.extend(_scan_member(path, info.filename, header + stream.read()))
    except (OSError, zipfile.BadZipFile) as exc:
        findings.append(f"{path.name}: invalid_wheel:{type(exc).__name__}")
    return findings


def _scan_sdist(path: Path) -> list[str]:
    findings: list[str] = []
    seen: set[str] = set()
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            for info in archive.getmembers():
                path_finding = _validate_member_path(path, info.name, seen)
                if path_finding:
                    findings.append(path_finding)
                    continue
                if info.isdir():
                    continue
                if not info.isfile():
                    findings.append(f"{path.name}:{info.name}: non_regular_member")
                    continue
                stream = archive.extractfile(info)
                if stream is None:
                    findings.append(f"{path.name}:{info.name}: unreadable_member")
                    continue
                header = stream.read(512)
                content_gate = _content_gate(path, info.name, info.size, header)
                if content_gate is not None:
                    findings.extend(content_gate)
                    continue
                findings.extend(_scan_member(path, info.name, header + stream.read()))
    except (OSError, tarfile.TarError) as exc:
        findings.append(f"{path.name}: invalid_sdist:{type(exc).__name__}")
    return findings


def verify_artifacts(paths: list[Path]) -> list[str]:
    findings: list[str] = []
    wheels = [path for path in paths if path.name.endswith(".whl")]
    sdists = [path for path in paths if path.name.endswith(".tar.gz")]
    unsupported = [path for path in paths if path not in wheels and path not in sdists]
    if len(wheels) != 1:
        findings.append(f"artifact_set: expected_one_wheel_got_{len(wheels)}")
    if len(sdists) != 1:
        findings.append(f"artifact_set: expected_one_sdist_got_{len(sdists)}")
    for path in unsupported:
        findings.append(f"{path.name}: unsupported_artifact")
    for path in wheels:
        findings.extend(_scan_wheel(path))
    for path in sdists:
        findings.extend(_scan_sdist(path))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args(argv)
    missing = [path for path in args.artifacts if not path.is_file()]
    if missing:
        for path in missing:
            print(f"{path}: missing_artifact")
        return 1
    findings = verify_artifacts(args.artifacts)
    if findings:
        print(f"Private artifact verification FAILED with {len(findings)} finding(s):")
        for finding in findings:
            print(f"  {finding}")
        return 1
    print("Private artifact verification OK: one wheel and one sdist are path-safe and secret-scan clean")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
