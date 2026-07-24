#!/usr/bin/env python3
"""Build the thin public seam-runtime package from public_pkg/.

Usage:
    python tools/release/build_public.py

Produces dist/seam_runtime-*.whl and dist/seam_runtime-*.tar.gz
built from the public-safe source tree only.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
PUBLIC_SRC = REPO / "public_pkg"
DIST = REPO / "dist"
BUILD_DIR = REPO / "build" / "public_release"

# -- pyproject.toml for the PUBLIC package --------------------------------
PUBLIC_PYPROJECT = """\
[build-system]
requires = ["setuptools>=77.0.3", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "seam-runtime"
version = "2.3.1"
description = "SEAM memory runtime — public client"
readme = "README.md"
license = "Apache-2.0"
requires-python = ">=3.11"
classifiers = [
    "Development Status :: 5 - Production/Stable",
    "Intended Audience :: Developers",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]
keywords = ["ai", "agents", "memory", "mcp", "rag"]
dependencies = [
    "seam-client>=0.1.0",
    "rich>=14.2,<16",
    "tiktoken>=0.8.0,<1.0",
]

[project.urls]
Homepage = "https://github.com/BlackhatShiftey/Seam"
Repository = "https://github.com/BlackhatShiftey/Seam"
Issues = "https://github.com/BlackhatShiftey/Seam/issues"

[project.optional-dependencies]
server = ["fastapi>=0.100,<1.0", "uvicorn[standard]>=0.23,<1.0", "python-multipart>=0.0.6,<1.0"]

[project.scripts]
seam = "seam:main"

[tool.setuptools]
py-modules = ["seam"]

[tool.setuptools.packages.find]
where = ["."]
include = ["seam_runtime"]

[tool.setuptools.package-data]
seam_runtime = []
"""


def main() -> int:
    # Clean
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True)

    # Copy public source files directly into BUILD_DIR
    for item in PUBLIC_SRC.iterdir():
        dest = BUILD_DIR / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)

    # Copy README for package metadata
    readme = REPO / "README.md"
    if readme.exists():
        shutil.copy2(readme, BUILD_DIR / "README.md")

    # Use Apache-2.0 license (not the private SEAM/MIRL/HS/1 license)
    apache_license = REPO / "LICENSES" / "Apache-2.0.txt"
    if apache_license.exists():
        shutil.copy2(apache_license, BUILD_DIR / "LICENSE")
    else:
        # Fallback: write a minimal Apache-2.0 SPDX header
        (BUILD_DIR / "LICENSE").write_text(
            "Apache License, Version 2.0\n"
            "https://www.apache.org/licenses/LICENSE-2.0\n",
            encoding="utf-8",
        )

    # Write the public pyproject.toml
    (BUILD_DIR / "pyproject.toml").write_text(PUBLIC_PYPROJECT, encoding="utf-8")

    print("=== Public package source tree ===")
    for f in sorted(BUILD_DIR.rglob("*")):
        if f.is_file() and "__pycache__" not in str(f) and "egg-info" not in str(f):
            print(f"  {f.relative_to(BUILD_DIR)}")
    print()

    # Build
    print("=== Building distributions ===")
    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--sdist", "--outdir", str(DIST)],
        cwd=BUILD_DIR,
        capture_output=True,
        text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        return result.returncode

    # Move dist files to repo dist/
    for f in (BUILD_DIR / "dist").glob("*"):
        dest = DIST / f.name
        shutil.copy2(f, dest)
        print(f"  -> {dest}")

    # Clean build dir
    shutil.rmtree(BUILD_DIR)
    print("\nDone. Public distributions in dist/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
