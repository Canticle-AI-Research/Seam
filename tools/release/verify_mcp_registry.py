"""Read-only checks for Suite MCP metadata and its production PyPI prerequisite."""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen

from packaging.utils import canonicalize_name, parse_sdist_filename, parse_wheel_filename

from tools.release.release_version import validate_release_version

SERVER_NAME = "io.github.Canticle-AI-Research/seam-suite"
OWNERSHIP_MARKER = f"<!-- mcp-name: {SERVER_NAME} -->"
REPOSITORY = {"url": "https://github.com/Canticle-AI-Research/Seam", "source": "github"}
RUNTIME_ARGUMENTS = [
    {"type": "named", "name": "--default-index", "value": "https://pypi.org/simple"},
    {"type": "positional", "value": "--from"},
]


def validate_manifest(
    project: dict, manifest: dict, readme: str, *, expected_version: str | None = None,
) -> str:
    """Bind registry identity and command construction to this Suite release.

    Clients append the package identifier/version after runtimeArguments, then
    packageArguments. --from consumes that package spec; seam-mcp is the actual
    console command. Omitting registryBaseUrl prevents an inserted --index-url
    from splitting --from and its operand (including in VS Code).
    """
    version = project.get("version")
    if not isinstance(version, str):
        raise ValueError("project version is missing")
    validate_release_version(expected_version or version, project_version=version)
    if project.get("name") != "seam-suite":
        raise ValueError("MCP must be supplied by seam-suite")
    if project.get("scripts", {}).get("seam-mcp") != "seam_runtime.mcp_protocol:main":
        raise ValueError("Suite must install the seam-mcp entrypoint")
    if manifest.get("name") != SERVER_NAME or manifest.get("repository") != REPOSITORY:
        raise ValueError("registry namespace or repository does not match Suite ownership")
    if manifest.get("version") != version or manifest.get("remotes"):
        raise ValueError("manifest must describe this version of the local Suite")
    markers = re.findall(r"<!--\s*mcp-name:\s*(\S+)\s*-->", readme)
    if markers != [SERVER_NAME]:
        raise ValueError("README must contain exactly the Suite MCP ownership marker")
    packages = manifest.get("packages")
    if not isinstance(packages, list) or len(packages) != 1 or not isinstance(packages[0], dict):
        raise ValueError("manifest must contain exactly one Suite PyPI package")
    package = packages[0]
    expected = {
        "registryType": "pypi", "identifier": "seam-suite", "version": version,
        "runtimeHint": "uvx", "runtimeArguments": RUNTIME_ARGUMENTS,
        "packageArguments": [{"type": "positional", "value": "seam-mcp"}],
        "transport": {"type": "stdio"},
    }
    if any(package.get(key) != value for key, value in expected.items()) or "registryBaseUrl" in package:
        raise ValueError("package identity or uvx launch arguments do not match the reviewed Suite command")
    return version


def validate_pypi_release(manifest: dict, metadata: dict) -> None:
    """Require the exact release, ownership marker and usable wheel/sdist pair.

    This verifies publication metadata, not artifact eligibility, signatures or
    installation. The separate TestPyPI and exact-artifact qualification remain
    prerequisites; a registry registration does not replace them.
    """
    if not isinstance(metadata, dict):
        raise ValueError("PyPI metadata must be an object")
    info = metadata.get("info")
    version = manifest["version"]
    if not isinstance(info, dict) or info.get("name") != "seam-suite" or info.get("version") != version:
        raise ValueError("PyPI package identity does not match the manifest")
    if OWNERSHIP_MARKER not in (info.get("description") or ""):
        raise ValueError("published PyPI description lacks the Suite MCP ownership marker")
    files = metadata.get("urls")
    if not isinstance(files, list) or not files:
        raise ValueError("PyPI has no files for this Suite version")
    kinds = set()
    for item in files:
        if not isinstance(item, dict) or item.get("yanked") is not False:
            raise ValueError("PyPI files must be non-yanked release artifacts")
        filename, kind = item.get("filename"), item.get("packagetype")
        if not isinstance(filename, str):
            raise ValueError("PyPI artifact filename is missing")
        if kind == "bdist_wheel":
            name, parsed_version, _, _ = parse_wheel_filename(filename)
        elif kind == "sdist":
            name, parsed_version = parse_sdist_filename(filename)
        else:
            raise ValueError("unexpected artifact type in PyPI release")
        if canonicalize_name(name) != "seam-suite" or str(parsed_version) != version:
            raise ValueError("PyPI artifact filename does not match the Suite version")
        url = urlsplit(item.get("url") or "")
        if url.scheme != "https" or url.netloc != "files.pythonhosted.org":
            raise ValueError("PyPI artifact URL must use the official HTTPS file host")
        digest = (item.get("digests") or {}).get("sha256", "")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("PyPI artifact SHA-256 is missing or malformed")
        kinds.add(kind)
    if kinds != {"bdist_wheel", "sdist"}:
        raise ValueError("Suite publication must include both wheel and sdist")


def verify_published(project: dict, manifest: dict) -> None:
    if "Private :: Do Not Upload" in project.get("classifiers", []):
        raise ValueError("Private :: Do Not Upload is still set; finish the public artifact review before registration")
    version = manifest["version"]
    # Validate before forming a URL even when this function is called directly.
    validate_release_version(version, project_version=project.get("version"))
    url = f"https://pypi.org/pypi/seam-suite/{version}/json"
    with urlopen(url, timeout=20) as response:
        raw = response.read(4 * 1024 * 1024 + 1)
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("PyPI metadata exceeds the verification size limit")
    validate_pypi_release(manifest, json.loads(raw))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--expected-version")
    parser.add_argument("--published", action="store_true", help="Also require the exact public PyPI release")
    args = parser.parse_args(argv)
    try:
        project = tomllib.loads((args.root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        manifest = json.loads((args.root / "server.json").read_text(encoding="utf-8"))
        readme = (args.root / "README.md").read_text(encoding="utf-8")
        version = validate_manifest(project, manifest, readme, expected_version=args.expected_version)
        if args.published:
            verify_published(project, manifest)
    except (OSError, ValueError, KeyError, TypeError, URLError) as exc:
        print(f"MCP registration check failed: {exc}", file=sys.stderr)
        return 1
    print(f"Suite MCP {version}: {'public PyPI prerequisite verified' if args.published else 'local metadata verified'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
