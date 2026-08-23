"""Fail closed on unsafe or secret-bearing private release archives.

The private runtime is intentionally distributable only as an access-scoped
GitHub Release. This verifier checks the built wheel and sdist before upload:
archive members must be regular, relative, unique paths; credential-shaped
paths are forbidden; and text members use SEAM's canonical content-free secret
scanner. Reports never echo matched content.
"""

from __future__ import annotations

import argparse
import re
import stat
import tarfile
import unicodedata
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath, PureWindowsPath

from packaging.utils import (
    InvalidSdistFilename,
    InvalidWheelFilename,
    canonicalize_name,
    canonicalize_version,
    parse_sdist_filename,
    parse_wheel_filename,
)

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
_DENIED_FILENAME_WORDS = frozenset(
    {
        "access_token",
        "accesstoken",
        "auth",
        "authentication",
        "id_token",
        "idtoken",
        "oauth",
        "refresh_token",
        "refreshtoken",
        "token",
        "tokens",
    }
)
_DENIED_COLLAPSED_FILENAME_SUFFIXES = (
    "accesstoken",
    "authtoken",
    "idtoken",
    "oauthtoken",
    "refreshtoken",
    "token",
    "tokens",
)
_SAFE_TOKEN_CODE_STEMS = frozenset({"tokenization", "tokenizer", "tokenizers"})
_WINDOWS_RESERVED_BASENAMES = frozenset(
    {"aux", "clock$", "con", "nul", "prn"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
)
_WINDOWS_FORBIDDEN_CHARACTERS = frozenset('<>:"|?*')
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


def _validate_member_path(
    archive: Path, raw_name: str, seen: set[str], member_ref: str
) -> str | None:
    if PureWindowsPath(raw_name).drive:
        return f"{archive.name}:{member_ref}: unsafe_member_path"
    normalized = raw_name.replace("\\", "/")
    member = PurePosixPath(normalized)
    if not normalized or not member.parts or member.is_absolute() or ".." in member.parts:
        return f"{archive.name}:{member_ref}: unsafe_member_path"
    if any(part.endswith((".", " ")) for part in member.parts):
        return f"{archive.name}:{member_ref}: unsafe_member_path"
    if any(any(ord(char) < 32 for char in part) for part in member.parts):
        return f"{archive.name}:{member_ref}: unsafe_member_path"
    if any(any(char in _WINDOWS_FORBIDDEN_CHARACTERS for char in part) for part in member.parts):
        return f"{archive.name}:{member_ref}: unsafe_member_path"
    if any(
        part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_BASENAMES
        for part in member.parts
    ):
        return f"{archive.name}:{member_ref}: unsafe_member_path"
    canonical = member.as_posix()
    canonical_key = unicodedata.normalize("NFC", canonical).casefold()
    if canonical_key in seen:
        return f"{archive.name}:{member_ref}: duplicate_member"
    seen.add(canonical_key)
    lowered_parts = tuple(part.casefold() for part in member.parts)
    if any(part in _DENIED_NAMES for part in lowered_parts):
        return f"{archive.name}:{member_ref}: credential_path"
    if any(marker in lowered_parts[-1] for marker in _DENIED_FILENAME_MARKERS):
        return f"{archive.name}:{member_ref}: credential_path"
    filename_words = frozenset(re.findall(r"[a-z0-9]+", lowered_parts[-1]))
    filename_stem = lowered_parts[-1].rsplit(".", 1)[0]
    collapsed_stem = "".join(re.findall(r"[a-z0-9]+", filename_stem))
    if (
        filename_words & _DENIED_FILENAME_WORDS
        or collapsed_stem.startswith("oauth") and collapsed_stem[5:].isdigit()
        or collapsed_stem.endswith(_DENIED_COLLAPSED_FILENAME_SUFFIXES)
        or collapsed_stem.startswith(("oauth", "token"))
        and collapsed_stem not in _SAFE_TOKEN_CODE_STEMS
    ):
        return f"{archive.name}:{member_ref}: credential_path"
    if any(part in {"secrets", "credentials"} for part in lowered_parts[:-1]):
        return f"{archive.name}:{member_ref}: credential_directory"
    if member.suffix.casefold() in _DENIED_SUFFIXES:
        return f"{archive.name}:{member_ref}: credential_or_database_suffix"
    return None


def _scan_member(archive: Path, member_ref: str, content: bytes) -> list[str]:
    return [
        f"{archive.name}:{finding.path}:{finding.line}: {finding.kind}"
        for finding in scan_bytes(member_ref, content, include_binary=True)
    ]


def _scan_container_bytes(path: Path) -> list[str]:
    findings: list[str] = []
    overlap = b""
    chunk_number = 0
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(MAX_SCAN_BYTES - len(overlap)):
                chunk_number += 1
                content = overlap + chunk
                findings.extend(_scan_member(path, f"container[{chunk_number}]", content))
                overlap = content[-4096:]
    except OSError:
        findings.append(f"{path.name}: unreadable_artifact_container")
    return findings


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


def _content_gate(
    archive: Path, name: str, member_ref: str, size: int, header: bytes
) -> list[str] | None:
    suffix = Path(name).suffix.casefold()
    if suffix in _NESTED_ARCHIVE_SUFFIXES or _has_archive_magic(header):
        return [f"{archive.name}:{member_ref}:0: nested_archive"]
    if size > MAX_SCAN_BYTES:
        return [f"{archive.name}:{member_ref}:0: scan_size_limit"]
    return None


def _scan_wheel(path: Path) -> list[str]:
    findings = _scan_container_bytes(path)
    seen: set[str] = set()
    try:
        with zipfile.ZipFile(path) as archive:
            for ordinal, info in enumerate(archive.infolist(), start=1):
                member_ref = f"member[{ordinal}]"
                path_finding = _validate_member_path(path, info.filename, seen, member_ref)
                if path_finding:
                    findings.append(path_finding)
                    continue
                mode = (info.external_attr >> 16) & 0o170000
                if mode == stat.S_IFLNK:
                    findings.append(f"{path.name}:{member_ref}: symbolic_link")
                    continue
                if info.is_dir():
                    continue
                if mode not in {0, stat.S_IFREG}:
                    findings.append(f"{path.name}:{member_ref}: non_regular_member")
                    continue
                try:
                    with archive.open(info) as stream:
                        header = stream.read(512)
                        content_gate = _content_gate(
                            path, info.filename, member_ref, info.file_size, header
                        )
                        if content_gate is not None:
                            findings.extend(content_gate)
                            continue
                        findings.extend(_scan_member(path, member_ref, header + stream.read()))
                except (EOFError, OSError, RuntimeError, zipfile.BadZipFile):
                    findings.append(f"{path.name}:{member_ref}: unreadable_member")
    except (OSError, zipfile.BadZipFile) as exc:
        findings.append(f"{path.name}: invalid_wheel:{type(exc).__name__}")
    return findings


def _scan_sdist(path: Path) -> list[str]:
    findings = _scan_container_bytes(path)
    seen: set[str] = set()
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            for ordinal, info in enumerate(archive.getmembers(), start=1):
                member_ref = f"member[{ordinal}]"
                path_finding = _validate_member_path(path, info.name, seen, member_ref)
                if path_finding:
                    findings.append(path_finding)
                    continue
                if info.isdir():
                    continue
                if not info.isfile():
                    findings.append(f"{path.name}:{member_ref}: non_regular_member")
                    continue
                try:
                    stream = archive.extractfile(info)
                except (EOFError, OSError, RuntimeError, tarfile.TarError):
                    findings.append(f"{path.name}:{member_ref}: unreadable_member")
                    continue
                if stream is None:
                    findings.append(f"{path.name}:{member_ref}: unreadable_member")
                    continue
                header = stream.read(512)
                content_gate = _content_gate(path, info.name, member_ref, info.size, header)
                if content_gate is not None:
                    findings.extend(content_gate)
                    continue
                findings.extend(_scan_member(path, member_ref, header + stream.read()))
    except (OSError, tarfile.TarError) as exc:
        findings.append(f"{path.name}: invalid_sdist:{type(exc).__name__}")
    return findings


def _metadata_identity(content: bytes) -> tuple[str, str] | None:
    message = BytesParser(policy=policy.default).parsebytes(content, headersonly=True)
    names = message.get_all("Name", [])
    versions = message.get_all("Version", [])
    if len(names) != 1 or len(versions) != 1:
        return None
    return names[0], versions[0]


def _scan_wheel_identity(path: Path, expected_name: str, expected_version: str) -> list[str]:
    findings: list[str] = []
    try:
        name, version, _build, _tags = parse_wheel_filename(path.name)
        if canonicalize_name(name) != canonicalize_name(expected_name):
            findings.append(f"{path.name}: artifact_name_mismatch")
        if canonicalize_version(str(version)) != canonicalize_version(expected_version):
            findings.append(f"{path.name}: artifact_version_mismatch")
        wheel_parts = path.name.removesuffix(".whl").split("-")
        expected_metadata_path = f"{wheel_parts[0]}-{wheel_parts[1]}.dist-info/METADATA"
        with zipfile.ZipFile(path) as archive:
            metadata_members = [
                info
                for info in archive.infolist()
                if info.filename == expected_metadata_path
            ]
            if len(metadata_members) != 1:
                return [*findings, f"{path.name}: expected_one_metadata_member"]
            with archive.open(metadata_members[0]) as stream:
                content = stream.read(MAX_SCAN_BYTES + 1)
    except (EOFError, InvalidWheelFilename, OSError, RuntimeError, zipfile.BadZipFile):
        return [*findings, f"{path.name}: unreadable_artifact_identity"]
    if len(content) > MAX_SCAN_BYTES:
        return [*findings, f"{path.name}: artifact_metadata_size_limit"]
    identity = _metadata_identity(content)
    if identity is None:
        return [*findings, f"{path.name}: invalid_artifact_metadata"]
    metadata_name, metadata_version = identity
    if canonicalize_name(metadata_name) != canonicalize_name(expected_name):
        findings.append(f"{path.name}: metadata_name_mismatch")
    if canonicalize_version(metadata_version) != canonicalize_version(expected_version):
        findings.append(f"{path.name}: metadata_version_mismatch")
    return findings


def _scan_sdist_identity(path: Path, expected_name: str, expected_version: str) -> list[str]:
    findings: list[str] = []
    try:
        name, version = parse_sdist_filename(path.name)
        if canonicalize_name(name) != canonicalize_name(expected_name):
            findings.append(f"{path.name}: artifact_name_mismatch")
        if canonicalize_version(str(version)) != canonicalize_version(expected_version):
            findings.append(f"{path.name}: artifact_version_mismatch")
        with tarfile.open(path, mode="r:gz") as archive:
            metadata_members = [
                info
                for info in archive.getmembers()
                if info.isfile()
                and len(PurePosixPath(info.name).parts) == 2
                and PurePosixPath(info.name).name == "PKG-INFO"
            ]
            if len(metadata_members) != 1:
                return [*findings, f"{path.name}: expected_one_metadata_member"]
            stream = archive.extractfile(metadata_members[0])
            if stream is None:
                return [*findings, f"{path.name}: unreadable_artifact_identity"]
            content = stream.read(MAX_SCAN_BYTES + 1)
    except (EOFError, InvalidSdistFilename, OSError, RuntimeError, tarfile.TarError):
        return [*findings, f"{path.name}: unreadable_artifact_identity"]
    if len(content) > MAX_SCAN_BYTES:
        return [*findings, f"{path.name}: artifact_metadata_size_limit"]
    identity = _metadata_identity(content)
    if identity is None:
        return [*findings, f"{path.name}: invalid_artifact_metadata"]
    metadata_name, metadata_version = identity
    if canonicalize_name(metadata_name) != canonicalize_name(expected_name):
        findings.append(f"{path.name}: metadata_name_mismatch")
    if canonicalize_version(metadata_version) != canonicalize_version(expected_version):
        findings.append(f"{path.name}: metadata_version_mismatch")
    return findings


def verify_artifacts(
    paths: list[Path], *, expected_name: str | None = None, expected_version: str | None = None
) -> list[str]:
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
        if expected_name is not None and expected_version is not None:
            findings.extend(_scan_wheel_identity(path, expected_name, expected_version))
    for path in sdists:
        findings.extend(_scan_sdist(path))
        if expected_name is not None and expected_version is not None:
            findings.extend(_scan_sdist_identity(path, expected_name, expected_version))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-name")
    parser.add_argument("--expected-version")
    parser.add_argument("artifacts", nargs="+", type=Path)
    args = parser.parse_args(argv)
    if (args.expected_name is None) != (args.expected_version is None):
        parser.error("--expected-name and --expected-version must be provided together")
    missing = [path for path in args.artifacts if not path.is_file()]
    if missing:
        for path in missing:
            print(f"{path}: missing_artifact")
        return 1
    findings = verify_artifacts(
        args.artifacts,
        expected_name=args.expected_name,
        expected_version=args.expected_version,
    )
    if findings:
        print(f"Private artifact verification FAILED with {len(findings)} finding(s):")
        for finding in findings:
            print(f"  {finding}")
        return 1
    print("Private artifact verification OK: one wheel and one sdist are path-safe and secret-scan clean")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
