"""Check exact Suite implementation membership without changing its permission."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tomllib
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath, PureWindowsPath

from tools.release.release_version import validate_release_version
from tools.release.verify_private_artifacts import _validate_member_path, verify_artifacts

LICENSE_ID = "LicenseRef-SEAM-Suite-Personal-1.0"
MANIFEST_PATH = "LICENSES/SEAM-Suite-manifest.json"
LEGAL_PATHS = (
    "LICENSE", "NOTICE", "COMMERCIAL_LICENSE.md", "LICENSES/SEAM-Suite-Personal.txt",
    MANIFEST_PATH, "LICENSES/BUSL-1.1.txt", "LICENSES/Apache-2.0.txt",
)


def _hex(value: object, length: int) -> bool:
    return isinstance(value, str) and re.fullmatch(rf"[0-9a-f]{{{length}}}", value) is not None


def _safe_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or PureWindowsPath(value).drive:
        raise ValueError("invalid member path")
    path = PurePosixPath(value)
    if path.is_absolute() or str(path) != value or any(
        part in {".", ".."} or ":" in part or any(ord(c) < 32 for c in part) for part in path.parts
    ):
        raise ValueError("unsafe member path")
    return value


def _ignored(path: str) -> bool:
    parts = PurePosixPath(path).parts
    return "__pycache__" in parts or path.endswith((".pyc", ".pyo")) or path == "seam_runtime/config.toml"


def _private_sdk(path: str) -> bool:
    return any(PurePosixPath(part).stem.casefold() in {"seam_sdk", "seam-sdk"} for part in PurePosixPath(path).parts)


def _implementation_path(path: object, seen: set[str] | None = None) -> str:
    path = _safe_path(path)
    if _validate_member_path(Path(MANIFEST_PATH), path, set() if seen is None else seen, "implementation"):
        raise ValueError("unsafe, duplicate or credential-shaped implementation path")
    if (
        (path != "seam.py" and not path.startswith("seam_runtime/")) or _ignored(path)
        or _private_sdk(path) or PurePosixPath(path).name.casefold() == "config.toml"
    ):
        raise ValueError("manifest contains a non-Suite, private SDK, cache or local configuration path")
    return path


class Source:
    """Read working files or the exact Git index; neither mode writes anything."""

    def __init__(self, root: Path, staged: bool):
        self.root = root.resolve()
        self.modes: dict[str, str] | None = None
        if staged:
            try:
                top = subprocess.check_output(["git", "-C", str(self.root), "rev-parse", "--show-toplevel"])
                if Path(os.fsdecode(top).strip()).resolve() != self.root:
                    raise ValueError("--staged requires the repository root")
                raw = subprocess.check_output([
                    "git", "-C", str(self.root), "ls-files", "--stage", "-z", "--",
                    "seam.py", "seam_runtime", "pyproject.toml", *LEGAL_PATHS,
                ])
            except subprocess.CalledProcessError:
                raise ValueError("cannot read the repository index") from None
            self.modes = {}
            for entry in raw.split(b"\0"):
                if not entry:
                    continue
                header, name = entry.split(b"\t", 1)
                mode, _oid, stage = header.decode().split()
                if stage != "0":
                    raise ValueError("unresolved index entries")
                self.modes[os.fsdecode(name)] = mode

    def read(self, path: str) -> bytes:
        _safe_path(path)
        if self.modes is not None:
            if self.modes.get(path) not in {"100644", "100755"}:
                raise ValueError(f"missing or non-regular staged file: {path}")
            try:
                return subprocess.check_output(["git", "-C", str(self.root), "show", ":" + path])
            except subprocess.CalledProcessError:
                raise ValueError(f"cannot read staged file: {path}") from None
        current = self.root
        for part in PurePosixPath(path).parts:
            current /= part
            if current.is_symlink():
                raise ValueError(f"symlink source path: {path}")
        if not current.is_file():
            raise ValueError(f"missing or non-regular source file: {path}")
        return current.read_bytes()

    def inventory(self) -> set[str]:
        if self.modes is not None:
            paths = [p for p in self.modes if p == "seam.py" or p.startswith("seam_runtime/")]
        else:
            paths = ["seam.py"]

            def fail(error):
                raise error

            runtime = self.root / "seam_runtime"
            if runtime.is_symlink():
                raise ValueError("symlink source directory: seam_runtime")
            for directory, dirs, files in os.walk(runtime, followlinks=False, onerror=fail):
                dirs[:] = [d for d in dirs if d != "__pycache__"]
                for d in dirs:
                    if (Path(directory) / d).is_symlink():
                        raise ValueError("symlink implementation directory")
                paths.extend((Path(directory) / f).relative_to(self.root).as_posix() for f in files)
        seen: set[str] = set()
        return {_implementation_path(p, seen) for p in paths if not _ignored(p)}


def verify_source(source: Source) -> tuple[str, dict[str, str]]:
    project = tomllib.loads(source.read("pyproject.toml").decode())["project"]
    if not isinstance(project, dict):
        raise ValueError("invalid project identity")
    manifest = json.loads(source.read(MANIFEST_PATH))
    if not isinstance(manifest, dict) or manifest.get("schema") != "seam-suite-license-manifest/v1":
        raise ValueError("unsupported Suite manifest schema")
    version = project.get("version")
    if not isinstance(version, str):
        raise ValueError("missing project version")
    validate_release_version(version)
    if project.get("name") != "seam-suite" or manifest.get("package") != "seam-suite":
        raise ValueError("Suite package identity mismatch")
    if manifest.get("version") != version or project.get("license") != LICENSE_ID or manifest.get("license") != LICENSE_ID:
        raise ValueError("Suite version or license identity mismatch")
    if manifest.get("license_file") != "SEAM-Suite-Personal.txt" or project.get("license-files") != list(LEGAL_PATHS):
        raise ValueError("Suite legal document identity mismatch")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("missing Suite implementation inventory")
    hashes = {}
    seen_paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            raise ValueError("invalid implementation inventory entry")
        path = _implementation_path(entry["path"], seen_paths)
        if path in hashes or not _hex(entry["sha256"], 64):
            raise ValueError("duplicate member or invalid implementation SHA-256")
        hashes[path] = entry["sha256"]
    inventory_digest = hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if manifest.get("implementation_inventory_sha256") != inventory_digest:
        raise ValueError("implementation inventory digest mismatch or missing")
    base = manifest.get("implementation_source_base_commit", manifest.get("implementation_source_commit"))
    if not _hex(base, 40):
        raise ValueError("missing implementation source provenance")
    delta = manifest.get("implementation_source_delta", [])
    if not isinstance(delta, list):
        raise ValueError("invalid implementation source delta")
    seen = set()
    for entry in delta:
        if not isinstance(entry, dict) or set(entry) != {"path", "old_sha256", "sha256"}:
            raise ValueError("invalid implementation delta entry")
        path = _implementation_path(entry["path"])
        if path in seen or not _hex(entry["old_sha256"], 64) or entry["sha256"] != hashes.get(path):
            raise ValueError("implementation delta is inconsistent with membership")
        seen.add(path)
    if source.inventory() != set(hashes):
        raise ValueError("source implementation membership mismatch (missing or unexpected member)")
    for path, expected in hashes.items():
        if hashlib.sha256(source.read(path)).hexdigest() != expected:
            raise ValueError(f"implementation hash mismatch: {path}")
    for path in LEGAL_PATHS:
        source.read(path)
    return version, hashes


def verify_archives(source: Source, paths: list[Path], version: str, hashes: dict[str, str]) -> None:
    findings = verify_artifacts(paths, expected_name="seam-suite", expected_version=version)
    if findings:
        raise ValueError("archive safety/identity verification failed: " + "; ".join(findings))
    for path in paths:
        if path.name.endswith(".whl"):
            with zipfile.ZipFile(path) as archive:
                contents = {m.filename: archive.read(m) for m in archive.infolist() if not m.is_dir()}
            prefix = f"seam_suite-{version}.dist-info/"
            metadata_path, legal_prefix = prefix + "METADATA", prefix + "licenses/"
        else:
            with tarfile.open(path, "r:gz") as archive:
                prefix = path.name.removesuffix(".tar.gz") + "/"
                contents = {m.name.removeprefix(prefix): archive.extractfile(m).read() for m in archive.getmembers() if m.isfile()}
            metadata_path, legal_prefix = "PKG-INFO", ""
        implementation = {}
        for name, content in contents.items():
            _safe_path(name)
            parts = PurePosixPath(name).parts
            if _private_sdk(name) or name == "seam_runtime/config.toml":
                raise ValueError(f"private SDK/local configuration in archive: {path.name}")
            if name == "seam.py" or name.startswith("seam_runtime/"):
                implementation[_implementation_path(name)] = hashlib.sha256(content).hexdigest()
            elif "seam_runtime" in parts or PurePosixPath(name).name == "seam.py":
                raise ValueError(f"unexpected implementation location: {path.name}")
        if implementation != hashes:
            raise ValueError(f"archive implementation membership/hash mismatch: {path.name}")
        for name in LEGAL_PATHS:
            if contents.get(legal_prefix + name) != source.read(name):
                raise ValueError(f"missing or stale legal document in {path.name}: {name}")
        metadata = BytesParser().parsebytes(contents[metadata_path])
        if (
            metadata.get_all("Name") != ["seam-suite"] or metadata.get_all("Version") != [version]
            or metadata.get_all("License-Expression") != [LICENSE_ID]
            or sorted(metadata.get_all("License-File", [])) != sorted(LEGAL_PATHS)
        ):
            raise ValueError(f"archive legal metadata mismatch: {path.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--staged", action="store_true", help="Check exact staged implementation and legal files")
    parser.add_argument("artifacts", nargs="*", type=Path, help="Optional exact wheel and sdist pair")
    args = parser.parse_args(argv)
    if args.staged and args.artifacts:
        parser.error("archive checks require current source, not the staged index")
    try:
        source = Source(args.root, args.staged)
        version, hashes = verify_source(source)
        if args.artifacts:
            verify_archives(source, args.artifacts, version, hashes)
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"Suite manifest check failed: {exc}", file=sys.stderr)
        return 1
    detail = "source and wheel/sdist verified" if args.artifacts else "source verified"
    print(f"Suite manifest {version}: {detail}; {len(hashes)} exact implementation files. No permission changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
