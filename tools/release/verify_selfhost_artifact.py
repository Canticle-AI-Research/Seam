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
    "licenses/BUSL-1.1.txt",
}

# Reserved identifiers that survive compilation into the shipped payload.
#
# Native compilation removes source bodies but preserves module names, qualified
# function names, class names, and literal strings. A measured build leaked
# `compile_nl.<locals>.add_claim`, `seam_runtime/reasoning_graph.py`, and
# `create table if not exists knowledge_graph_meta (` verbatim. Path-only checks
# cannot see any of that, so the payload is scanned by content.
#
# This is a RATCHET, not a zero-tolerance gate. Zero is unreachable while the
# engine itself is compiled in: `MIRL`, `MIRLRecord`, and `IRBatch` name the code
# doing the work, and excluding those modules would remove the product. A gate
# that can never pass would simply be switched off, so instead the measured
# exposure is pinned and any INCREASE fails. Lower these numbers as symbol
# mangling lands; never raise them to make a build pass.
#
# Baseline measured 2026-07-28 against seam-selfhost built from this Dockerfile
# (76,516,816-byte binary, 417 total occurrences). The unnarrowed build that
# preceded it measured 525, so the module exclusions bought a 20% reduction.
#
# 2026-07-28, knowledge_graph 17 -> 18 (total 418): G3 (HISTORY#478-479) added
# seam_runtime/retrieval_orchestrator/, which imports knowledge_graph. Diffing the
# binaries showed exactly one new string, the module path
# `seam_runtime.knowledge_graph`, and no other marker moved. That is a module
# reference from real new code, not additional design detail, so the ratchet was
# raised by one with this reason rather than silently widened.
RESERVED_CONTENT_BUDGET: dict[bytes, int] = {
    b"MIRL": 134,
    b"MIRLRecord": 120,
    b"IRBatch": 63,
    b"TraceGraph": 11,
    b"compile_nl": 10,
    b"holographic": 11,
    b"surface_adapter": 6,
    b"HS/1": 15,
    b"SEAM-RC": 13,
    b"SEAM-LX": 4,
    b"knowledge_graph": 18,
    b"reasoning_graph": 13,
}

# The license texts legitimately name MIRL and HS/1; that is their purpose.
CONTENT_SCAN_EXEMPT_PREFIXES: tuple[str, ...] = ("licenses/",)


@dataclass(frozen=True)
class ImageArchive:
    config: dict[str, object]
    layers: tuple[bytes, ...]


def verify_archive(
    path: Path,
    *,
    budget: dict[bytes, int] | None = None,
) -> tuple[str, ...]:
    """Verify a self-host image archive.

    ``budget`` caps how many times each reserved identifier may appear across the
    non-license payload. It defaults to the measured production baseline; tests
    pass a tighter one.
    """
    budget = RESERVED_CONTENT_BUDGET if budget is None else budget
    image = _read_image_archive(path)
    errors: list[str] = []
    observed: dict[bytes, int] = {}
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
        if not name.startswith(CONTENT_SCAN_EXEMPT_PREFIXES):
            for marker in budget:
                occurrences = content.count(marker)
                if occurrences:
                    observed[marker] = observed.get(marker, 0) + occurrences

    for marker, allowed in sorted(budget.items()):
        seen = observed.get(marker, 0)
        if seen > allowed:
            errors.append(
                f"reserved identifier exposure increased: {marker.decode()} "
                f"appears {seen} times, budget {allowed}"
            )

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
