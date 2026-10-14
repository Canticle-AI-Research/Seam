"""Exact Suite permission follows reviewed bytes, never an automatic refresh."""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MODULE = "tools.release.verify_suite_manifest"
LEGAL = (
    "LICENSE", "NOTICE", "COMMERCIAL_LICENSE.md", "LICENSES/SEAM-Suite-Personal.txt",
    "LICENSES/SEAM-Suite-manifest.json", "LICENSES/BUSL-1.1.txt", "LICENSES/Apache-2.0.txt",
)
VERSION = "2.4.1rc1"
LICENSE = "LicenseRef-SEAM-Suite-Personal-1.0"


def digest(content):
    return hashlib.sha256(content).hexdigest()


def save_manifest(root, manifest):
    manifest["implementation_inventory_sha256"] = digest(
        json.dumps(manifest["files"], sort_keys=True, separators=(",", ":")).encode()
    )
    (root / LEGAL[4]).write_text(json.dumps(manifest, indent=2) + "\n")


@pytest.fixture
def candidate(tmp_path):
    (tmp_path / "LICENSES").mkdir()
    (tmp_path / "seam_runtime/webui").mkdir(parents=True)
    for path, content in {
        "seam.py": b"def main(): pass\n",
        "seam_runtime/__init__.py": b"VERSION = '2.4.1rc1'\n",
        "seam_runtime/webui/dashboard.html": b"<main>Suite</main>\n",
    }.items():
        (tmp_path / path).write_bytes(content)
    for path in LEGAL:
        (tmp_path / path).write_text("Reviewed terms: " + path + "\n")
    (tmp_path / "pyproject.toml").write_text(
        f'[project]\nname = "seam-suite"\nversion = "{VERSION}"\nlicense = "{LICENSE}"\n'
        + "license-files = " + json.dumps(LEGAL) + "\n"
    )
    files = [{"path": p, "sha256": digest((tmp_path / p).read_bytes())} for p in (
        "seam.py", "seam_runtime/__init__.py", "seam_runtime/webui/dashboard.html",
    )]
    manifest = {
        "schema": "seam-suite-license-manifest/v1", "package": "seam-suite", "version": VERSION,
        "license": LICENSE, "license_file": "SEAM-Suite-Personal.txt", "files": files,
        "implementation_source_base_commit": "a" * 40, "implementation_source_delta": [],
    }
    save_manifest(tmp_path, manifest)
    return tmp_path, manifest


def check(root, *args):
    return subprocess.run(
        [sys.executable, "-m", MODULE, "--root", str(root), *args], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )


def archive_pair(root, directory, *, mutation=None, changed_kind=None):
    directory.mkdir()
    manifest = json.loads((root / LEGAL[4]).read_text())
    members = {p["path"]: (root / p["path"]).read_bytes() for p in manifest["files"]}
    metadata = (
        f"Metadata-Version: 2.4\nName: seam-suite\nVersion: {VERSION}\nLicense-Expression: {LICENSE}\n"
        + "".join(f"License-File: {path}\n" for path in LEGAL) + "\n"
    ).encode()
    output = []
    for kind in ("wheel", "sdist"):
        impl = members.copy()
        legal = {p: (root / p).read_bytes() for p in LEGAL}
        meta = metadata
        if kind == changed_kind:
            if mutation == "stale_implementation":
                impl["seam.py"] = b"def main(): return 'unreviewed'\n"
            elif mutation == "missing_implementation":
                impl.pop("seam_runtime/__init__.py")
            elif mutation == "unexpected_implementation":
                impl["seam_runtime/extra.py"] = b"pass\n"
            elif mutation == "stale_notice":
                legal["NOTICE"] = b"Earlier terms\n"
            elif mutation == "missing_legal":
                legal.pop("LICENSES/SEAM-Suite-Personal.txt")
            elif mutation == "wrong_license":
                meta = metadata.replace(LICENSE.encode(), b"Apache-2.0")
            elif mutation == "private_sdk":
                impl["seam_sdk/__init__.py"] = b"pass\n"
            elif mutation == "config":
                impl["seam_runtime/config.toml"] = b"local = true\n"
        if kind == "wheel":
            path = directory / f"seam_suite-{VERSION}-py3-none-any.whl"
            prefix = f"seam_suite-{VERSION}.dist-info/"
            with zipfile.ZipFile(path, "w") as bundle:
                for name, content in impl.items():
                    bundle.writestr(name, content)
                for name, content in legal.items():
                    bundle.writestr(prefix + "licenses/" + name, content)
                bundle.writestr(prefix + "METADATA", meta)
        else:
            path = directory / f"seam_suite-{VERSION}.tar.gz"
            prefix = f"seam_suite-{VERSION}/"
            with tarfile.open(path, "w:gz") as bundle:
                for name, content in {**impl, **legal, "PKG-INFO": meta}.items():
                    member = tarfile.TarInfo(prefix + name)
                    member.size = len(content)
                    bundle.addfile(member, io.BytesIO(content))
        output.append(str(path))
    return output


def test_cli_accepts_reviewed_source_without_writing(candidate):
    root, _ = candidate
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result = check(root)
    assert result.returncode == 0, result.stderr
    assert "source verified" in result.stdout
    assert before == {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


@pytest.mark.parametrize("mutation", ["stale", "missing", "unexpected", "symlink"])
def test_cli_rejects_source_drift(candidate, mutation):
    root, _ = candidate
    path = root / "seam.py"
    if mutation == "stale":
        path.write_text("# changed implementation\n")
    elif mutation == "missing":
        path.unlink()
    elif mutation == "unexpected":
        (root / "seam_runtime/new.py").write_text("pass\n")
    else:
        path.unlink()
        path.symlink_to(root / "NOTICE")
    result = check(root)
    assert result.returncode == 1
    assert "Suite manifest check failed" in result.stderr


@pytest.mark.parametrize("path", [
    "seam_runtime/con.py", "seam_runtime/seam_sdk.py", "seam_runtime/private/config.toml",
])
def test_even_declared_members_cannot_expand_into_unsafe_sdk_or_local_config(candidate, path):
    root, manifest = candidate
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# fixture implementation\n")
    manifest["files"].append({"path": path, "sha256": digest(target.read_bytes())})
    save_manifest(root, manifest)
    result = check(root)
    assert result.returncode == 1
    assert "Suite manifest check failed" in result.stderr


@pytest.mark.parametrize("mutation", [
    "duplicate", "unsafe", "backslash", "private_sdk", "config", "digest", "missing_digest",
    "package", "version", "license", "license_file", "delta", "schema",
])
def test_cli_rejects_inconsistent_or_ineligible_manifest(candidate, mutation):
    root, manifest = candidate
    if mutation == "duplicate":
        manifest["files"].append(manifest["files"][0].copy())
    elif mutation in {"unsafe", "backslash", "private_sdk", "config"}:
        manifest["files"][0]["path"] = {
            "unsafe": "../seam.py", "backslash": "seam_runtime\\new.py",
            "private_sdk": "seam_runtime/seam_sdk/__init__.py", "config": "seam_runtime/config.toml",
        }[mutation]
    elif mutation == "delta":
        manifest["implementation_source_delta"] = [{"path": "seam.py", "old_sha256": "b" * 64, "sha256": "c" * 64}]
    elif mutation not in {"digest", "missing_digest"}:
        manifest[mutation] = "wrong"
    save_manifest(root, manifest)
    if mutation in {"digest", "missing_digest"}:
        if mutation == "digest":
            manifest["implementation_inventory_sha256"] = "0" * 64
        else:
            del manifest["implementation_inventory_sha256"]
        (root / LEGAL[4]).write_text(json.dumps(manifest))
    result = check(root)
    assert result.returncode == 1
    assert "Suite manifest check failed" in result.stderr


def test_cli_accepts_exact_reviewed_archives(candidate, tmp_path):
    root, _ = candidate
    paths = archive_pair(root, tmp_path / "dist")
    result = check(root, *paths)
    assert result.returncode == 0, result.stderr
    assert "wheel/sdist verified" in result.stdout


@pytest.mark.parametrize("kind", ["wheel", "sdist"])
@pytest.mark.parametrize("mutation", [
    "stale_implementation", "missing_implementation", "unexpected_implementation",
    "stale_notice", "missing_legal", "wrong_license", "private_sdk", "config",
])
def test_cli_rejects_unreviewed_packaged_bytes(candidate, tmp_path, kind, mutation):
    root, _ = candidate
    paths = archive_pair(root, tmp_path / "dist", mutation=mutation, changed_kind=kind)
    result = check(root, *paths)
    assert result.returncode == 1
    assert "Suite manifest check failed" in result.stderr


def test_commit_check_reads_staged_bytes_without_unstaged_repairs_masking_drift(candidate):
    root, _ = candidate
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "seam.py").write_text("# stale staged implementation\n")
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    (root / "seam.py").write_text("def main(): pass\n")
    assert check(root).returncode == 0
    result = check(root, "--staged")
    assert result.returncode == 1
    assert "Suite manifest check failed" in result.stderr


def test_manifest_guard_is_unsuppressed_in_required_ci_and_local_gates():
    from tests.audit.test_local_gates_match_ci import _script_gate_invocations
    from tools.history.closeout import PREFLIGHT_GATES

    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["repo-hygiene"]
    matches = [s for s in job["steps"] if MODULE in s.get("run", "")]
    assert "if" not in job
    assert len(matches) == 1
    assert matches[0]["run"] == f"python -m {MODULE}"
    assert "if" not in matches[0] and not matches[0].get("continue-on-error", False)
    assert ("verify_suite_manifest", (MODULE,)) in PREFLIGHT_GATES
    for path, args in (
        ("tools/claude/preflight_protocol.sh", ()), ("tools/git-hooks/pre-commit", ("--staged",)),
    ):
        calls = [c for c in _script_gate_invocations((ROOT / path).read_text()) if c.module == MODULE]
        assert len(calls) == 1 and calls[0].aborts and calls[0].args == args
    package = workflow["jobs"]["package-smoke"]
    checks = [s for s in package["steps"] if MODULE in s.get("run", "")]
    assert len(checks) == 1
    assert "if" not in checks[0] and not checks[0].get("continue-on-error", False)
    assert "dist/*.whl dist/*.tar.gz" in checks[0]["run"]
