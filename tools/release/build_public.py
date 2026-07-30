#!/usr/bin/env python3
"""Build the thin public seam-runtime package from public_pkg/.

Usage:
    python tools/release/build_public.py --outdir <empty-directory>

Produces a seam_runtime wheel and sdist
built from the public-safe source tree only.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
PUBLIC_SRC = REPO / "public_pkg"
DEFAULT_DIST = REPO / "dist"
PUBLIC_FILES = (
    Path("README.md"),
    Path("pyproject.toml"),
    Path("seam.py"),
    Path("seam_runtime/__init__.py"),
)


def _run(command: list[str], *, cwd: Path) -> None:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    if result.stdout:
        print(result.stdout)
    if result.returncode:
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(command)}")


def build_public(outdir: Path) -> tuple[Path, ...]:
    """Build and check the public wheel/sdist in an initially empty directory."""
    outdir = outdir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    if any(outdir.iterdir()):
        raise ValueError(f"output directory must be empty: {outdir}")

    with tempfile.TemporaryDirectory(prefix="seam-public-build-") as temporary:
        build_dir = Path(temporary)
        for relative in PUBLIC_FILES:
            source = PUBLIC_SRC / relative
            destination = build_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

        shutil.copy2(REPO / "LICENSES" / "Apache-2.0.txt", build_dir / "LICENSE")

        print("=== Public package source tree ===")
        for path in sorted(build_dir.rglob("*")):
            if path.is_file():
                print(f"  {path.relative_to(build_dir)}")

        _run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--sdist",
                "--outdir",
                str(outdir),
            ],
            cwd=build_dir,
        )

    artifacts = tuple(sorted(outdir.iterdir()))
    _run(
        [sys.executable, "-m", "twine", "check", *(str(path) for path in artifacts)],
        cwd=REPO,
    )
    return artifacts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_DIST)
    args = parser.parse_args(argv)
    try:
        artifacts = build_public(args.outdir)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"public build failed: {exc}", file=sys.stderr)
        return 1
    for artifact in artifacts:
        print(f"  -> {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
