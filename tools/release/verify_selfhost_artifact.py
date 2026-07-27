"""Fail closed when a compiled self-host image archive leaks source or secrets."""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

SOURCE_SUFFIXES = (".py", ".pyc", ".pyo", ".ipynb", ".c", ".h", ".cpp")
FORBIDDEN_PATH_PARTS = (
    "/docs/",
    "/tests/",
    "/benchmarks/",
    "/tools/",
    "SEAM_SPEC",
    "MIRL_V1",
    "HOLOGRAPHIC_SURFACE",
)
FORBIDDEN_RUNTIME_PATHS = (
    "bin/sh",
    "usr/bin/apt",
    "usr/bin/apt-get",
    "usr/local/bin/python",
    "usr/local/bin/pip",
)
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"\bgh[oprsu]_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"https?://(?:chatgpt|claude|gemini)\\.[^\s\"']+/(?:share|thread|chat)/", re.IGNORECASE),
)
REQUIRED_PATHS = {
    "opt/seam/app/seam-selfhost",
    "opt/seam/app/libgcc_s.so.1",
    "opt/seam/app/libz.so.1",
    "opt/seam/entitlement-public-key.pem",
    "licenses/SEAM-LICENSE",
}


@dataclass(frozen=True)
class ImageArchive:
    config: dict[str, object]
    layers: tuple[bytes, ...]


def verify_archive(path: Path) -> tuple[str, ...]:
    image = _read_image_archive(path)
    errors: list[str] = []
    members: dict[str, bytes] = {}
    for layer_bytes in image.layers:
        with tarfile.open(fileobj=io.BytesIO(layer_bytes), mode="r:*") as layer:
            for member in layer.getmembers():
                normalized = str(PurePosixPath(member.name)).lstrip("./")
                if member.isfile():
                    extracted = layer.extractfile(member)
                    if extracted is not None:
                        members[normalized] = extracted.read()

    member_names = set(members)
    missing = sorted(REQUIRED_PATHS - member_names)
    if missing:
        errors.append(f"required runtime paths are missing: {', '.join(missing)}")
    for name, content in sorted(members.items()):
        lowered = name.lower()
        if lowered.endswith(SOURCE_SUFFIXES):
            errors.append(f"source-like file is present: {name}")
        if any(part.lower() in f"/{lowered}" for part in FORBIDDEN_PATH_PARTS):
            errors.append(f"private source/document path is present: {name}")
        if name in FORBIDDEN_RUNTIME_PATHS:
            errors.append(f"mutable runtime tool is present: {name}")
        patterns = SECRET_PATTERNS[1:] if content.startswith(b"\x7fELF") else SECRET_PATTERNS
        for pattern in patterns:
            if pattern.search(content):
                errors.append(f"secret-shaped content is present: {name}")
                break

    config = image.config.get("config", {})
    if not isinstance(config, dict):
        errors.append("image config is missing")
        return tuple(errors)
    if config.get("User") not in {"65532", "65532:65532"}:
        errors.append("image must run as uid 65532")
    if config.get("Entrypoint") != ["/opt/seam/app/seam-selfhost"]:
        errors.append("image entrypoint is not the compiled self-host executable")
    if config.get("WorkingDir") != "/var/lib/seam":
        errors.append("image working directory must be the data volume")
    if image.config.get("os") != "linux" or image.config.get("architecture") != "amd64":
        errors.append("image platform must be linux/amd64")
    labels = config.get("Labels", {})
    if not isinstance(labels, dict) or labels.get("com.seam.edition") != "compiled-self-host":
        errors.append("compiled self-host edition label is missing")
    serialized_config = json.dumps(image.config, sort_keys=True).encode()
    if any(pattern.search(serialized_config) for pattern in SECRET_PATTERNS):
        errors.append("secret-shaped content is present in image configuration")
    return tuple(dict.fromkeys(errors))


def _read_image_archive(path: Path) -> ImageArchive:
    with tarfile.open(path, "r:*") as archive:
        names = {member.name for member in archive.getmembers()}
        if "manifest.json" in names:
            manifest = json.loads(_read_member(archive, "manifest.json"))
            if not isinstance(manifest, list) or len(manifest) != 1:
                raise ValueError("Docker archive must contain exactly one image")
            item = manifest[0]
            config = json.loads(_read_member(archive, item["Config"]))
            layers = tuple(_read_member(archive, name) for name in item["Layers"])
            return ImageArchive(config=config, layers=layers)

        index = json.loads(_read_member(archive, "index.json"))
        manifests = [
            descriptor
            for descriptor in index.get("manifests", [])
            if not _is_attestation_descriptor(descriptor)
        ]
        if len(manifests) != 1:
            raise ValueError("OCI archive must contain exactly one runnable image manifest")
        manifest = _read_blob_json(archive, manifests[0]["digest"])
        config = _read_blob_json(archive, manifest["config"]["digest"])
        layers = tuple(_read_blob(archive, layer["digest"]) for layer in manifest["layers"])
        return ImageArchive(config=config, layers=layers)


def _read_blob_json(archive: tarfile.TarFile, digest: str) -> dict[str, object]:
    return json.loads(_read_blob(archive, digest))


def _is_attestation_descriptor(descriptor: dict[str, object]) -> bool:
    annotations = descriptor.get("annotations", {})
    platform = descriptor.get("platform", {})
    if isinstance(annotations, dict) and annotations.get("vnd.docker.reference.type") == "attestation-manifest":
        return True
    return isinstance(platform, dict) and platform.get("architecture") == "unknown"


def _read_blob(archive: tarfile.TarFile, digest: str) -> bytes:
    algorithm, value = digest.split(":", 1)
    if algorithm != "sha256":
        raise ValueError(f"unsupported OCI digest algorithm: {algorithm}")
    return _read_member(archive, f"blobs/{algorithm}/{value}")


def _read_member(archive: tarfile.TarFile, name: str) -> bytes:
    member = archive.getmember(name)
    extracted = archive.extractfile(member)
    if extracted is None:
        raise ValueError(f"archive member is not a file: {name}")
    return extracted.read()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args(argv)
    try:
        errors = verify_archive(args.archive)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, tarfile.TarError) as exc:
        print(f"[selfhost-artifact] FAIL {args.archive}: {exc}", file=sys.stderr)
        return 1
    if errors:
        for error in errors:
            print(f"[selfhost-artifact] FAIL {args.archive}: {error}", file=sys.stderr)
        return 1
    print(f"[selfhost-artifact] PASS {args.archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
