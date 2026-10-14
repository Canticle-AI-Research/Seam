"""Fail-closed preparation, upload, and public verification for SEAM TestPyPI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from packaging.utils import canonicalize_name

from tools.release.release_version import validate_release_version
from tools.release.verify_private_artifacts import verify_artifacts
from tools.release.verify_suite_manifest import Source, verify_archives, verify_source

PACKAGE = "seam-suite"
DEFAULT_BRANCH = "main"
_FULL_SHA = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SAFE_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]*")
TESTPYPI_REPOSITORY = "https://test.pypi.org/legacy/"
TESTPYPI_API = "https://test.pypi.org/pypi"
TESTPYPI_FILE_HOST = "test-files.pythonhosted.org"
RECEIPT_SCHEMA = "seam-testpypi-preparation/v1"


def validate_dispatch(
    *,
    root: Path,
    package: str,
    version: str,
    requested_sha: str,
    workflow_sha: str,
    head_sha: str,
    remote_sha: str,
    ref: str,
    default_branch: str,
) -> None:
    """Bind a dispatch to the exact canonical package at current protected main."""
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    if package != PACKAGE or canonicalize_name(str(project.get("name", ""))) != PACKAGE:
        raise ValueError("package must be exactly seam-suite")
    validate_release_version(version, project_version=project.get("version"))
    if not _FULL_SHA.fullmatch(requested_sha):
        raise ValueError("commit SHA must be one full lowercase hexadecimal commit")
    if workflow_sha != requested_sha:
        raise ValueError("workflow SHA does not match the requested commit")
    if head_sha != requested_sha:
        raise ValueError("checked-out HEAD does not match the requested commit")
    if default_branch != DEFAULT_BRANCH or ref != "refs/heads/main":
        raise ValueError("TestPyPI publication must run from main")
    if remote_sha != requested_sha:
        raise ValueError("remote main moved from the requested commit")


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def _safe_regular_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"artifact is not a regular file: {path.name}")
    if (
        not _SAFE_FILENAME.fullmatch(path.name)
        or path.name in {".", ".."}
        or ".." in path.name
        or "/" in path.name
        or "\\" in path.name
    ):
        raise ValueError(f"unsafe artifact filename: {path.name}")


def discover_artifacts(dist: Path, *, package: str, version: str) -> tuple[Path, Path]:
    """Return one exact regular wheel and sdist after identity and archive checks."""
    if package != PACKAGE:
        raise ValueError("package must be exactly seam-suite")
    validate_release_version(version)
    if dist.is_symlink() or not dist.is_dir():
        raise ValueError("artifact directory is missing or is a symlink")
    paths = sorted(dist.iterdir(), key=lambda path: path.name)
    if len(paths) != 2:
        raise ValueError("artifact directory must contain exactly one wheel and one sdist")
    for path in paths:
        _safe_regular_file(path)
    wheels = [path for path in paths if path.name.endswith(".whl")]
    sdists = [path for path in paths if path.name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("artifact directory must contain exactly one wheel and one sdist")
    ordered = [wheels[0], sdists[0]]
    findings = verify_artifacts(ordered, expected_name=package, expected_version=version)
    if findings:
        raise ValueError("artifact verification failed: " + "; ".join(findings))
    return wheels[0], sdists[0]


def _manifest_digest(root: Path) -> str:
    return _digest(root / "LICENSES/SEAM-Suite-manifest.json")


def prepare_receipt(
    *, root: Path, dist: Path, package: str, version: str, source_sha: str
) -> tuple[dict[str, object], tuple[Path, Path]]:
    if not _FULL_SHA.fullmatch(source_sha):
        raise ValueError("source commit must be one full lowercase hexadecimal SHA")
    paths = discover_artifacts(dist, package=package, version=version)
    source = Source(root, False)
    source_version, hashes = verify_source(source)
    if source_version != version:
        raise ValueError("Suite source version does not match requested version")
    verify_archives(source, list(paths), version, hashes)
    receipt: dict[str, object] = {
        "schema": RECEIPT_SCHEMA,
        "source_sha": source_sha,
        "package": package,
        "version": version,
        "manifest_sha256": _manifest_digest(root),
        "files": [
            {"name": path.name, "size": path.stat().st_size, "sha256": _digest(path)}
            for path in paths
        ],
    }
    return receipt, paths


def _write_receipt(path: Path, receipt: dict[str, object]) -> str:
    if path.exists() or path.is_symlink():
        raise ValueError("receipt path must not already exist")
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(content)
    return hashlib.sha256(content).hexdigest()


def load_receipt(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("preparation receipt is missing or is a symlink")
    try:
        receipt = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError):
        raise ValueError("preparation receipt is not valid JSON") from None
    if not isinstance(receipt, dict):
        raise ValueError("preparation receipt must be a JSON object")
    return receipt


def verify_receipt_digest(path: Path, expected: str) -> None:
    if not _SHA256.fullmatch(expected):
        raise ValueError("preparation receipt digest must be one lowercase SHA256")
    if path.is_symlink() or not path.is_file() or _digest(path) != expected:
        raise ValueError("preparation receipt digest mismatch")


def validate_receipt(
    receipt: dict[str, object],
    dist: Path,
    *,
    package: str,
    version: str,
    source_sha: str,
    manifest_sha256: str | None = None,
) -> tuple[Path, Path]:
    expected_keys = {"schema", "source_sha", "package", "version", "manifest_sha256", "files"}
    if set(receipt) != expected_keys or receipt.get("schema") != RECEIPT_SCHEMA:
        raise ValueError("invalid preparation receipt schema")
    if receipt.get("package") != package or package != PACKAGE:
        raise ValueError("preparation receipt package mismatch")
    if receipt.get("version") != version:
        raise ValueError("preparation receipt version mismatch")
    if receipt.get("source_sha") != source_sha or not _FULL_SHA.fullmatch(source_sha):
        raise ValueError("preparation receipt source commit mismatch")
    recorded_manifest = receipt.get("manifest_sha256")
    if not isinstance(recorded_manifest, str) or not _SHA256.fullmatch(recorded_manifest):
        raise ValueError("invalid preparation manifest digest")
    if manifest_sha256 is not None and recorded_manifest != manifest_sha256:
        raise ValueError("preparation manifest digest mismatch")
    entries = receipt.get("files")
    if not isinstance(entries, list) or len(entries) != 2:
        raise ValueError("preparation receipt must name exactly two files")
    names: set[str] = set()
    by_name: dict[str, dict[str, object]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"name", "size", "sha256"}:
            raise ValueError("invalid preparation receipt file entry")
        name, size, sha256 = entry["name"], entry["size"], entry["sha256"]
        if (
            not isinstance(name, str)
            or not _SAFE_FILENAME.fullmatch(name)
            or ".." in name
            or name in names
        ):
            raise ValueError("unsafe or duplicate preparation receipt filename")
        if not isinstance(size, int) or isinstance(size, bool) or size < 1:
            raise ValueError("invalid preparation receipt file size")
        if not isinstance(sha256, str) or not _SHA256.fullmatch(sha256):
            raise ValueError("invalid preparation receipt file digest")
        names.add(name)
        by_name[name] = entry
    if dist.is_symlink() or not dist.is_dir():
        raise ValueError("artifact directory is missing or is a symlink")
    actual = sorted(dist.iterdir(), key=lambda path: path.name)
    if {path.name for path in actual} != names or len(actual) != 2:
        raise ValueError("artifact directory membership differs from preparation receipt")
    for path in actual:
        _safe_regular_file(path)
        entry = by_name[path.name]
        if path.stat().st_size != entry["size"] or _digest(path) != entry["sha256"]:
            raise ValueError(f"artifact bytes differ from preparation receipt: {path.name}")
    wheels = [path for path in actual if path.name.endswith(".whl")]
    sdists = [path for path in actual if path.name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("receipt must cover exactly one wheel and one sdist")
    return wheels[0], sdists[0]


def validate_prepared(
    *,
    root: Path,
    dist: Path,
    receipt_path: Path,
    receipt_sha256: str,
    package: str,
    version: str,
    source_sha: str,
) -> tuple[dict[str, object], tuple[Path, Path]]:
    verify_receipt_digest(receipt_path, receipt_sha256)
    receipt = load_receipt(receipt_path)
    paths = validate_receipt(
        receipt,
        dist,
        package=package,
        version=version,
        source_sha=source_sha,
        manifest_sha256=_manifest_digest(root),
    )
    verified_paths = discover_artifacts(dist, package=package, version=version)
    source = Source(root, False)
    source_version, hashes = verify_source(source)
    if source_version != version:
        raise ValueError("Suite source version does not match requested version")
    verify_archives(source, list(verified_paths), version, hashes)
    return receipt, paths


def check_artifacts(paths: list[Path], *, runner=subprocess.run) -> None:
    command = [sys.executable, "-m", "twine", "check", "--strict", *(str(path) for path in paths)]
    runner(command, check=True)


def upload_artifacts(
    paths: list[Path], *, password: str, runner=subprocess.run
) -> None:
    if not password:
        raise ValueError("TEST_PYPI secret is missing")
    if len(paths) != 2:
        raise ValueError("upload requires exactly two validated artifact paths")
    for path in paths:
        _safe_regular_file(path)
    env = os.environ.copy()
    env.update({"TWINE_USERNAME": "__token__", "TWINE_PASSWORD": password})
    command = [
        sys.executable,
        "-m",
        "twine",
        "upload",
        "--non-interactive",
        "--repository-url",
        TESTPYPI_REPOSITORY,
        *(str(path) for path in paths),
    ]
    try:
        runner(command, check=True, env=env)
    except subprocess.CalledProcessError:
        raise ValueError(
            "TestPyPI upload failed; remote state may be partial and requires operator review"
        ) from None


def github_main_sha(repository: str) -> str:
    """Read protected-main through authenticated GitHub API immediately before upload."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("unsafe GitHub repository identity")
    if not os.environ.get("GH_TOKEN"):
        raise ValueError("GitHub read token is missing")
    try:
        output = subprocess.check_output(
            ["gh", "api", f"repos/{repository}/git/ref/heads/main", "--jq", ".object.sha"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        raise ValueError("could not recheck current GitHub main") from None
    sha = output.strip()
    if not _FULL_SHA.fullmatch(sha):
        raise ValueError("GitHub main response was not one exact commit")
    return sha


def _allowed_test_url(url: str) -> urllib.parse.SplitResult:
    parsed = urllib.parse.urlsplit(url)
    decoded_path = urllib.parse.unquote(parsed.path)
    if (
        parsed.scheme != "https"
        or parsed.hostname != TESTPYPI_FILE_HOST
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not decoded_path.startswith("/packages/")
        or any(part in {"", ".", ".."} for part in decoded_path.split("/")[2:])
        or urllib.parse.quote(decoded_path, safe="/._+-") != parsed.path
    ):
        raise ValueError("TestPyPI file URL is not an approved HTTPS artifact URL")
    return parsed


def validate_download_url(url: str, filename: str) -> None:
    _safe_regular_filename(filename)
    parsed = _allowed_test_url(url)
    if Path(urllib.parse.unquote(parsed.path)).name != filename:
        raise ValueError("TestPyPI file URL does not match its artifact filename")


def _safe_regular_filename(filename: str) -> None:
    if not _SAFE_FILENAME.fullmatch(filename) or ".." in filename or filename in {".", ".."}:
        raise ValueError("unsafe artifact filename")


def validate_release_metadata(
    payload: object, receipt: dict[str, object]
) -> list[dict[str, object]]:
    if not isinstance(payload, dict):
        raise ValueError("TestPyPI metadata is not an object")
    package, version = receipt.get("package"), receipt.get("version")
    info, files = payload.get("info"), payload.get("urls")
    if (
        not isinstance(info, dict)
        or info.get("name") != package
        or info.get("version") != version
        or not isinstance(files, list)
    ):
        raise ValueError("TestPyPI metadata identity conflict")
    expected_entries = receipt.get("files")
    if not isinstance(expected_entries, list):
        raise ValueError("TestPyPI release metadata is incomplete")
    expected = {entry["name"]: entry for entry in expected_entries if isinstance(entry, dict) and "name" in entry}
    if len(files) != 2 or len(expected) != 2:
        raise ValueError("TestPyPI release is partial or has unexpected files")
    found: set[str] = set()
    validated: list[dict[str, object]] = []
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("TestPyPI release file metadata is invalid")
        name = entry.get("filename")
        if not isinstance(name, str) or name in found or name not in expected:
            raise ValueError("TestPyPI release file membership conflict")
        expected_entry = expected[name]
        digests = entry.get("digests")
        if (
            not isinstance(digests, dict)
            or digests.get("sha256") != expected_entry.get("sha256")
            or entry.get("size") != expected_entry.get("size")
        ):
            raise ValueError("TestPyPI release file hash or size conflict")
        url = entry.get("url")
        if not isinstance(url, str):
            raise ValueError("TestPyPI release file URL is missing")
        validate_download_url(url, name)
        found.add(name)
        validated.append(entry)
    if found != set(expected):
        raise ValueError("TestPyPI release is partial")
    return sorted(validated, key=lambda entry: str(entry["filename"]))


def _fetch_json(url: str) -> object:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        if response.status != 200:
            raise ValueError(f"TestPyPI metadata returned HTTP {response.status}")
        return json.loads(response.read(2 * 1024 * 1024 + 1))


def poll_release(
    receipt: dict[str, object],
    *,
    fetch_json: Callable[[str], object] = _fetch_json,
    attempts: int = 12,
    delay: float = 10,
    sleeper: Callable[[float], None] = time.sleep,
) -> list[dict[str, object]]:
    if attempts < 1 or attempts > 30 or delay < 0 or delay > 60:
        raise ValueError("invalid TestPyPI polling bounds")
    url = f"{TESTPYPI_API}/{PACKAGE}/{receipt.get('version')}/json"
    last_error = "metadata unavailable"
    for attempt in range(1, attempts + 1):
        try:
            return validate_release_metadata(fetch_json(url), receipt)
        except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as exc:
            last_error = str(exc)
        if attempt < attempts:
            sleeper(delay)
    raise ValueError(f"TestPyPI readback failed after {attempts} attempts: {last_error}")


class RestrictedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects outside the exact TestPyPI artifact host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        _allowed_test_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_release_files(
    entries: list[dict[str, object]], destination: Path, *, opener=None
) -> tuple[Path, Path]:
    if destination.exists() or destination.is_symlink():
        raise ValueError("readback directory must not already exist")
    destination.mkdir(parents=True)
    client = opener or urllib.request.build_opener(RestrictedRedirectHandler())
    downloaded: list[Path] = []
    for entry in entries:
        name, url, size, sha256 = (
            entry["filename"], entry["url"], entry["size"], entry["digests"]["sha256"]
        )
        validate_download_url(str(url), str(name))
        request = urllib.request.Request(str(url), headers={"Accept": "application/octet-stream"})
        with client.open(request, timeout=30) as response:
            validate_download_url(response.geturl(), str(name))
            content = response.read(int(size) + 1)
        if len(content) != size or hashlib.sha256(content).hexdigest() != sha256:
            raise ValueError(f"downloaded TestPyPI bytes do not match metadata: {name}")
        path = destination / str(name)
        path.write_bytes(content)
        downloaded.append(path)
    wheels = [path for path in downloaded if path.name.endswith(".whl")]
    sdists = [path for path in downloaded if path.name.endswith(".tar.gz")]
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("TestPyPI readback did not produce one wheel and one sdist")
    return wheels[0], sdists[0]


def _add_identity_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--requested-sha", required=True)
    parser.add_argument("--workflow-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--remote-sha", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--default-branch", required=True)


def _identity_from_args(args) -> dict[str, object]:
    return {
        "root": args.root,
        "package": args.package,
        "version": args.version,
        "requested_sha": args.requested_sha,
        "workflow_sha": args.workflow_sha,
        "head_sha": args.head_sha,
        "remote_sha": args.remote_sha,
        "ref": args.ref,
        "default_branch": args.default_branch,
    }


def _append_outputs(values: dict[str, str]) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if output_path:
        with Path(output_path).open("a", encoding="utf-8") as output:
            for key, value in values.items():
                print(f"{key}={value}", file=output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    boundary = subparsers.add_parser("prepare-boundary")
    _add_identity_arguments(boundary)
    prepare = subparsers.add_parser("prepare")
    _add_identity_arguments(prepare)
    prepare.add_argument("--dist", type=Path, required=True)
    prepare.add_argument("--receipt", type=Path, required=True)
    validate = subparsers.add_parser("validate")
    _add_identity_arguments(validate)
    validate.add_argument("--dist", type=Path, required=True)
    validate.add_argument("--receipt", type=Path, required=True)
    validate.add_argument("--receipt-sha256", required=True)
    upload = subparsers.add_parser("upload")
    _add_identity_arguments(upload)
    upload.add_argument("--dist", type=Path, required=True)
    upload.add_argument("--receipt", type=Path, required=True)
    upload.add_argument("--receipt-sha256", required=True)
    upload.add_argument("--artifact-digest", required=True)
    upload.add_argument("--repository", required=True)
    readback = subparsers.add_parser("readback")
    readback.add_argument("--receipt", type=Path, required=True)
    readback.add_argument("--receipt-sha256", required=True)
    readback.add_argument("--destination", type=Path, required=True)
    readback.add_argument("--package", required=True)
    readback.add_argument("--version", required=True)
    readback.add_argument("--source-sha", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in {"prepare-boundary", "prepare", "validate", "upload"}:
            validate_dispatch(**_identity_from_args(args))
        if args.command == "prepare-boundary":
            print("Dispatch is bound to the exact current protected-main commit and Suite version.")
        elif args.command == "prepare":
            receipt, paths = prepare_receipt(
                root=args.root,
                dist=args.dist,
                package=args.package,
                version=args.version,
                source_sha=args.requested_sha,
            )
            check_artifacts(list(paths))
            receipt_sha = _write_receipt(args.receipt, receipt)
            _append_outputs(
                {"wheel": paths[0].name, "sdist": paths[1].name, "receipt_sha256": receipt_sha}
            )
            print(f"Prepared exact {args.package} {args.version} wheel and sdist; receipt {receipt_sha}.")
        elif args.command == "validate":
            validate_prepared(
                root=args.root,
                dist=args.dist,
                receipt_path=args.receipt,
                receipt_sha256=args.receipt_sha256,
                package=args.package,
                version=args.version,
                source_sha=args.requested_sha,
            )
            print("Downloaded preparation artifact matches source, receipt, hashes, and membership.")
        elif args.command == "upload":
            if not _SHA256.fullmatch(args.artifact_digest):
                raise ValueError("artifact transfer digest must be one lowercase SHA256")
            password = os.environ.get("TWINE_PASSWORD", "")
            if not password:
                raise ValueError("TEST_PYPI secret is missing")
            _receipt, paths = validate_prepared(
                root=args.root,
                dist=args.dist,
                receipt_path=args.receipt,
                receipt_sha256=args.receipt_sha256,
                package=args.package,
                version=args.version,
                source_sha=args.requested_sha,
            )
            final_remote_sha = github_main_sha(args.repository)
            if final_remote_sha != args.requested_sha:
                raise ValueError("remote main moved after artifact validation; upload refused")
            upload_artifacts(list(paths), password=password)
            print(f"Uploaded exactly two validated files to {TESTPYPI_REPOSITORY}")
        elif args.command == "readback":
            if args.package != PACKAGE:
                raise ValueError("package must be exactly seam-suite")
            validate_release_version(args.version)
            verify_receipt_digest(args.receipt, args.receipt_sha256)
            receipt = load_receipt(args.receipt)
            if receipt.get("package") != args.package or receipt.get("version") != args.version:
                raise ValueError("readback receipt identity mismatch")
            if receipt.get("source_sha") != args.source_sha:
                raise ValueError("readback receipt source commit mismatch")
            entries = poll_release(receipt)
            paths = download_release_files(entries, args.destination)
            validate_receipt(
                receipt,
                args.destination,
                package=args.package,
                version=args.version,
                source_sha=args.source_sha,
            )
            _append_outputs({"wheel": paths[0].name, "sdist": paths[1].name})
            print("TestPyPI metadata and downloaded wheel/sdist hashes match the preparation receipt.")
    except (KeyError, OSError, TypeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"TestPyPI release check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

