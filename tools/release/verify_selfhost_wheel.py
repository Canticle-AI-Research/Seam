"""Fail closed when a seam-self-host wheel violates the compiled BUSL boundary."""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath

SOURCE_SUFFIXES = (".py", ".pyc", ".pyo")
BUSL_LICENSE_PATH = "licenses/LICENSES/BUSL-1.1.txt"
BUSL_LICENSE_MARKER = b"Business Source License 1.1"
NODE_NAME = b"Name: seam-self-host"
SELFHOST_VERSION = b"Version: 1.0.0"
BUSL_EXPRESSION = b"License-Expression: BUSL-1.1"
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(rb"\bgh[oprsu]_[A-Za-z0-9]{30,}\b"),
    re.compile(
        rb"https?://(?:chatgpt|claude|gemini)\.[^\s\"']+/(?:share|thread|chat)/",
        re.IGNORECASE,
    ),
)

# Baseline measured 2026-07-28 against the real cp312-manylinux_2_28_x86_64
# seam-self-host 1.0.0 wheel; unchanged 414-occurrence baseline carried
# forward from the seam-node 2.4.0 measurement at HISTORY#483.
# HISTORY#480 measured the one added ``seam_runtime.knowledge_graph`` module
# path introduced by the retrieval orchestrator; the node wheel carries the
# same compiled source and therefore inherits that single attributable count.
# This is a ratchet, not a zero-tolerance gate: native compilation retains
# identifiers needed by the engine. Lower counts when protection improves;
# never raise them merely to make a build pass.
SELFHOST_RESERVED_CONTENT_BUDGET: dict[bytes, int] = {
    b"MIRL": 133,
    b"MIRLRecord": 120,
    b"IRBatch": 63,
    b"TraceGraph": 11,
    b"compile_nl": 10,
    b"holographic": 10,
    b"surface_adapter": 5,
    b"HS/1": 15,
    b"SEAM-RC": 13,
    b"SEAM-LX": 4,
    b"knowledge_graph": 18,
    b"reasoning_graph": 12,
}


def _is_license_path(path: str) -> bool:
    return f"/{BUSL_LICENSE_PATH}" in f"/{path}"


def _is_runtime_source(path: str) -> bool:
    normalized = PurePosixPath(path)
    name = normalized.name
    if not name.endswith(SOURCE_SUFFIXES):
        return False
    return "seam_runtime" in normalized.parts or name.startswith("seam_runtime.")


def measure_reserved_content(
    path: Path,
    *,
    markers: tuple[bytes, ...] | None = None,
) -> dict[bytes, int]:
    """Count reserved identifiers in wheel file contents, excluding licenses."""
    selected = tuple(SELFHOST_RESERVED_CONTENT_BUDGET) if markers is None else markers
    observed = dict.fromkeys(selected, 0)
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if info.is_dir() or _is_license_path(info.filename):
                continue
            content = archive.read(info)
            for marker in selected:
                observed[marker] += content.count(marker)
    return observed


def verify_selfhost_wheel(
    path: Path,
    *,
    budget: dict[bytes, int] | None = None,
) -> tuple[str, ...]:
    """Return every selfhost-wheel boundary violation."""
    selected_budget = SELFHOST_RESERVED_CONTENT_BUDGET if budget is None else budget
    errors: list[str] = []
    try:
        with zipfile.ZipFile(path) as archive:
            files = {
                info.filename: archive.read(info)
                for info in archive.infolist()
                if not info.is_dir()
            }
    except (OSError, zipfile.BadZipFile) as exc:
        return (f"wheel is unreadable: {exc}",)

    runtime_sources = sorted(name for name in files if _is_runtime_source(name))
    if runtime_sources:
        errors.append(f"wheel contains seam_runtime source: {', '.join(runtime_sources)}")

    extensions = sorted(
        name
        for name in files
        if PurePosixPath(name).name.startswith("seam_runtime.")
        and name.endswith((".so", ".pyd"))
    )
    if len(extensions) != 1:
        errors.append(
            "wheel must contain exactly one compiled seam_runtime extension, "
            f"found {len(extensions)}"
        )

    license_entries = [
        content for name, content in files.items() if _is_license_path(name)
    ]
    if not license_entries:
        errors.append(f"wheel is missing {BUSL_LICENSE_PATH}")
    elif not any(BUSL_LICENSE_MARKER in content for content in license_entries):
        errors.append("wheel BUSL license file does not contain the BUSL-1.1 text")

    metadata_entries = [
        content
        for name, content in files.items()
        if PurePosixPath(name).name == "METADATA"
    ]
    if len(metadata_entries) != 1:
        errors.append("wheel must contain exactly one METADATA file")
        metadata = b""
    else:
        metadata = metadata_entries[0]
    if NODE_NAME not in metadata:
        errors.append("wheel metadata name is not seam-self-host")
    if SELFHOST_VERSION not in metadata:
        errors.append("wheel metadata version is not 1.0.0")
    if BUSL_EXPRESSION not in metadata:
        errors.append("wheel metadata does not declare BUSL-1.1")

    for name, content in sorted(files.items()):
        if _is_license_path(name):
            continue
        if any(pattern.search(content) for pattern in SECRET_PATTERNS):
            errors.append(f"secret-shaped content is present: {name}")

    observed = measure_reserved_content(path, markers=tuple(selected_budget))
    for marker, allowed in sorted(selected_budget.items()):
        seen = observed[marker]
        if seen > allowed:
            errors.append(
                f"reserved identifier exposure increased: {marker.decode()} "
                f"appears {seen} times, budget {allowed}"
            )
    return tuple(dict.fromkeys(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheels", nargs="+", type=Path)
    args = parser.parse_args(argv)

    failed = False
    for wheel in args.wheels:
        errors = verify_selfhost_wheel(wheel)
        if errors:
            failed = True
            for error in errors:
                print(f"[selfhost-wheel] FAIL {wheel}: {error}", file=sys.stderr)
        else:
            print(f"[selfhost-wheel] PASS {wheel}")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
