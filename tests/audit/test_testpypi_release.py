"""The TestPyPI publisher accepts only the reviewed protected-main candidate."""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from tools.release.testpypi_release import (
    TESTPYPI_API,
    TESTPYPI_REPOSITORY,
    discover_artifacts,
    poll_release,
    upload_artifacts,
    validate_dispatch,
    validate_download_url,
    validate_receipt,
    validate_release_metadata,
)

ROOT = Path(__file__).resolve().parents[2]
VERSION = "2.4.1rc1"
SHA = "a" * 40


def _minimal_pair(directory: Path, *, metadata_name="seam-suite", metadata_version=VERSION):
    directory.mkdir(parents=True, exist_ok=True)
    metadata = (
        f"Metadata-Version: 2.4\nName: {metadata_name}\nVersion: {metadata_version}\n\n"
    ).encode()
    wheel = directory / f"seam_suite-{VERSION}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(f"seam_suite-{VERSION}.dist-info/METADATA", metadata)
    sdist = directory / f"seam_suite-{VERSION}.tar.gz"
    root = f"seam_suite-{VERSION}"
    with tarfile.open(sdist, "w:gz") as archive:
        member = tarfile.TarInfo(f"{root}/PKG-INFO")
        member.size = len(metadata)
        archive.addfile(member, io.BytesIO(metadata))
    return wheel, sdist


def _receipt(paths, *, source_sha=SHA):
    return {
        "schema": "seam-testpypi-preparation/v1",
        "source_sha": source_sha,
        "package": "seam-suite",
        "version": VERSION,
        "manifest_sha256": "b" * 64,
        "files": [
            {
                "name": path.name,
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in paths
        ],
    }


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"package": "seam-sdk"}, "package"),
        ({"version": "2.4.1"}, "version"),
        ({"requested_sha": "a" * 39}, "commit"),
        ({"workflow_sha": "b" * 40}, "workflow"),
        ({"head_sha": "b" * 40}, "HEAD"),
        ({"remote_sha": "b" * 40}, "remote"),
        ({"ref": "refs/heads/release"}, "main"),
        ({"default_branch": "trunk"}, "main"),
    ],
)
def test_dispatch_rejects_every_identity_or_protected_main_mismatch(tmp_path, overrides, message):
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "seam-suite"\nversion = "2.4.1rc1"\n', encoding="utf-8"
    )
    values = {
        "root": tmp_path,
        "package": "seam-suite",
        "version": VERSION,
        "requested_sha": SHA,
        "workflow_sha": SHA,
        "head_sha": SHA,
        "remote_sha": SHA,
        "ref": "refs/heads/main",
        "default_branch": "main",
    }
    values.update(overrides)
    with pytest.raises(ValueError, match=message):
        validate_dispatch(**values)


@pytest.mark.parametrize("mutation", ["extra", "symlink", "traversing", "wrong_metadata"])
def test_artifact_discovery_rejects_non_exact_or_wrong_identity_sets(tmp_path, mutation):
    dist = tmp_path / "dist"
    wheel, _sdist = _minimal_pair(
        dist,
        metadata_name="seam-sdk" if mutation == "wrong_metadata" else "seam-suite",
    )
    if mutation == "extra":
        (dist / "notes.txt").write_text("unexpected", encoding="utf-8")
    elif mutation == "symlink":
        wheel.unlink()
        wheel.symlink_to(dist / "missing.whl")
    elif mutation == "traversing":
        (dist / "..evil.whl").write_bytes(b"bad")
    with pytest.raises(ValueError):
        discover_artifacts(dist, package="seam-suite", version=VERSION)


@pytest.mark.parametrize("mutation", ["duplicate", "traversing", "digest", "size", "extra"])
def test_receipt_rejects_any_membership_or_byte_mismatch(tmp_path, mutation):
    paths = _minimal_pair(tmp_path / "dist")
    receipt = _receipt(paths)
    if mutation == "duplicate":
        receipt["files"][1] = receipt["files"][0].copy()
    elif mutation == "traversing":
        receipt["files"][0]["name"] = "../escape.whl"
    elif mutation == "digest":
        receipt["files"][0]["sha256"] = "0" * 64
    elif mutation == "size":
        receipt["files"][0]["size"] += 1
    else:
        (tmp_path / "dist" / "extra.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(ValueError):
        validate_receipt(
            receipt,
            tmp_path / "dist",
            package="seam-suite",
            version=VERSION,
            source_sha=SHA,
        )


def test_upload_adapter_uses_only_fixed_endpoint_and_two_validated_paths(tmp_path):
    paths = _minimal_pair(tmp_path / "dist")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0)

    upload_artifacts(list(paths), password="test-token", runner=run)
    assert len(calls) == 1
    command, options = calls[0]
    assert command == [
        sys.executable,
        "-m",
        "twine",
        "upload",
        "--non-interactive",
        "--repository-url",
        TESTPYPI_REPOSITORY,
        str(paths[0]),
        str(paths[1]),
    ]
    assert options["check"] is True
    assert options["env"]["TWINE_USERNAME"] == "__token__"
    assert options["env"]["TWINE_PASSWORD"] == "test-token"


@pytest.mark.parametrize(
    "url",
    [
        "http://test-files.pythonhosted.org/packages/a.whl",
        "https://files.pythonhosted.org/packages/a.whl",
        "https://test-files.pythonhosted.org.evil.invalid/packages/a.whl",
        "https://test-files.pythonhosted.org/packages/../a.whl",
        "https://user@test-files.pythonhosted.org/packages/a.whl",
        "https://test-files.pythonhosted.org/packages/a.whl?token=secret",
    ],
)
def test_download_url_rejects_non_testpypi_hosts_or_ambiguous_paths(url):
    with pytest.raises(ValueError):
        validate_download_url(url, "a.whl")


def test_metadata_requires_exact_version_and_both_receipted_hashes(tmp_path):
    paths = _minimal_pair(tmp_path / "dist")
    receipt = _receipt(paths)
    releases = []
    for entry in receipt["files"]:
        releases.append(
            {
                "filename": entry["name"],
                "digests": {"sha256": entry["sha256"]},
                "size": entry["size"],
                "url": f"https://test-files.pythonhosted.org/packages/{entry['name']}",
            }
        )
    payload = {"info": {"name": "seam-suite", "version": VERSION}, "urls": releases}
    assert len(validate_release_metadata(payload, receipt)) == 2
    for broken in (
        {**payload, "info": {"name": "seam-sdk", "version": VERSION}},
        {**payload, "urls": releases[:1]},
        {**payload, "urls": [{**releases[0], "digests": {"sha256": "0" * 64}}, releases[1]]},
        {**payload, "urls": [{**releases[0], "url": "https://evil.invalid/x"}, releases[1]]},
    ):
        with pytest.raises(ValueError):
            validate_release_metadata(broken, receipt)


def test_metadata_poll_is_bounded_and_reports_partial_upload(tmp_path):
    paths = _minimal_pair(tmp_path / "dist")
    receipt = _receipt(paths)
    partial = {
        "info": {"name": "seam-suite", "version": VERSION},
        "urls": [],
    }
    attempts = []

    def fetch(url):
        attempts.append(url)
        return partial

    with pytest.raises(ValueError, match="after 3 attempts"):
        poll_release(receipt, fetch_json=fetch, attempts=3, delay=0, sleeper=lambda _delay: None)
    assert attempts == [f"{TESTPYPI_API}/seam-suite/{VERSION}/json"] * 3


def test_cli_failures_never_reach_twine(tmp_path):
    marker = tmp_path / "twine-called"
    fake_modules = tmp_path / "fake-modules"
    (fake_modules / "twine").mkdir(parents=True)
    (fake_modules / "twine" / "__init__.py").write_text("", encoding="utf-8")
    (fake_modules / "twine" / "__main__.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n", encoding="utf-8"
    )
    base = [
        sys.executable,
        "-m",
        "tools.release.testpypi_release",
        "upload",
        "--root",
        str(ROOT),
        "--dist",
        str(tmp_path / "missing-dist"),
        "--receipt",
        str(tmp_path / "missing-receipt.json"),
        "--receipt-sha256",
        "d" * 64,
        "--package",
        "seam-suite",
        "--version",
        VERSION,
        "--requested-sha",
        SHA,
        "--workflow-sha",
        SHA,
        "--head-sha",
        SHA,
        "--remote-sha",
        SHA,
        "--ref",
        "refs/heads/main",
        "--default-branch",
        "main",
        "--artifact-digest",
        "c" * 64,
        "--repository",
        "Canticle-AI-Research/SEAM",
    ]
    env = {**os.environ, "PYTHONPATH": f"{fake_modules}:{ROOT}"}
    env.pop("TWINE_PASSWORD", None)
    missing_secret = subprocess.run(base, cwd=ROOT, env=env, capture_output=True, text=True)
    assert missing_secret.returncode != 0
    assert not marker.exists()
    env["TWINE_PASSWORD"] = "local-fixture-token"
    stale = base.copy()
    stale[stale.index("--remote-sha") + 1] = "b" * 40
    stale_remote = subprocess.run(stale, cwd=ROOT, env=env, capture_output=True, text=True)
    assert stale_remote.returncode != 0
    assert not marker.exists()


def _upload_arguments(tmp_path, *, receipt_sha="d" * 64):
    return [
        "upload",
        "--root",
        str(ROOT),
        "--dist",
        str(tmp_path / "dist"),
        "--receipt",
        str(tmp_path / "receipt.json"),
        "--receipt-sha256",
        receipt_sha,
        "--package",
        "seam-suite",
        "--version",
        VERSION,
        "--requested-sha",
        SHA,
        "--workflow-sha",
        SHA,
        "--head-sha",
        SHA,
        "--remote-sha",
        SHA,
        "--ref",
        "refs/heads/main",
        "--default-branch",
        "main",
        "--artifact-digest",
        "c" * 64,
        "--repository",
        "Canticle-AI-Research/SEAM",
    ]


def test_upload_cli_refuses_substituted_receipt_or_artifact_before_uploader(tmp_path, monkeypatch):
    from tools.release.testpypi_release import main

    paths = _minimal_pair(tmp_path / "dist")
    receipt = _receipt(paths)
    receipt["manifest_sha256"] = hashlib.sha256(
        (ROOT / "LICENSES/SEAM-Suite-manifest.json").read_bytes()
    ).hexdigest()
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    trusted_receipt_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
    monkeypatch.setenv("TWINE_PASSWORD", "local-fixture-token")

    for mutation in ("receipt", "artifact"):
        if mutation == "receipt":
            receipt_path.write_text(json.dumps({**receipt, "source_sha": "b" * 40}) + "\n", encoding="utf-8")
        else:
            receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
            paths[0].write_bytes(paths[0].read_bytes() + b"substituted")
        with patch("tools.release.testpypi_release.upload_artifacts") as uploader:
            assert main(_upload_arguments(tmp_path, receipt_sha=trusted_receipt_sha)) == 1
            uploader.assert_not_called()
        if mutation == "artifact":
            break


def test_upload_cli_rechecks_authenticated_github_main_immediately_before_uploader(tmp_path, monkeypatch):
    from tools.release.testpypi_release import main

    paths = _minimal_pair(tmp_path / "dist")
    monkeypatch.setenv("TWINE_PASSWORD", "local-fixture-token")
    with (
        patch("tools.release.testpypi_release.validate_prepared", return_value=({}, paths)),
        patch("tools.release.testpypi_release.github_main_sha", return_value="b" * 40) as main_sha,
        patch("tools.release.testpypi_release.upload_artifacts") as uploader,
    ):
        assert main(_upload_arguments(tmp_path)) == 1
    main_sha.assert_called_once_with("Canticle-AI-Research/SEAM")
    uploader.assert_not_called()


def test_readback_binds_raw_receipt_bytes_before_network(tmp_path):
    from tools.release.testpypi_release import main

    receipt = tmp_path / "receipt.json"
    receipt.write_text(json.dumps({"schema": "substituted"}), encoding="utf-8")
    with patch("tools.release.testpypi_release.poll_release") as poller:
        result = main(
            [
                "readback",
                "--receipt",
                str(receipt),
                "--receipt-sha256",
                "0" * 64,
                "--destination",
                str(tmp_path / "readback"),
                "--package",
                "seam-suite",
                "--version",
                VERSION,
                "--source-sha",
                SHA,
            ]
        )
    assert result == 1
    poller.assert_not_called()


def test_redirect_handler_rejects_cross_host_redirect_before_following():
    from tools.release.testpypi_release import RestrictedRedirectHandler

    handler = RestrictedRedirectHandler()
    request = type("Request", (), {})()
    with pytest.raises(ValueError, match="approved HTTPS"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://evil.invalid/packages/seam_suite.whl",
        )


def test_workflow_keeps_credentials_step_scoped_and_runs_all_guards():
    workflow_path = ROOT / ".github/workflows/publish-testpypi.yml"
    text = workflow_path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert set(workflow[True]["workflow_dispatch"]["inputs"]) == {"package", "version", "commit_sha"}
    prepare = workflow["jobs"]["prepare"]
    publish = workflow["jobs"]["publish-and-verify"]
    assert publish["needs"] == "prepare"
    assert "secrets.TEST_PYPI" not in json.dumps({key: workflow.get(key) for key in ("env", "permissions")})
    credential_steps = [step for step in publish["steps"] if "TWINE_PASSWORD" in step.get("env", {})]
    assert len(credential_steps) == 1
    assert credential_steps[0]["env"]["TWINE_PASSWORD"] == "${{ secrets.TEST_PYPI }}"
    assert text.count("${{ secrets.TEST_PYPI }}") == 1
    assert "markdown-it-py>=4.0,<5.0" in text
    assert "git fetch" not in text and "git ls-remote" not in text
    assert text.count("GH_TOKEN: ${{ github.token }}") == 3
    assert text.count("${{ needs.prepare.outputs.receipt_sha256 }}") == 2
    assert text.count("--receipt-sha256") == 2
    assert "${{ needs.prepare.outputs.artifact_digest }}" in text
    checkout_steps = [
        step for job in workflow["jobs"].values() for step in job["steps"] if step.get("uses") == "actions/checkout@v4"
    ]
    assert checkout_steps and all(step["with"]["persist-credentials"] is False for step in checkout_steps)
    prepare_commands = "\n".join(str(step.get("run", "")) for step in prepare["steps"])
    for command in (
        "tools.history.verify_integrity",
        "tools.history.verify_routing",
        "tools.history.verify_handoffs",
        "tools.history.verify_continuity",
        "tools.streams.verify_streams",
        "tools.docs.verify_wiki",
    ):
        assert command in prepare_commands
    assert "--skip-existing" not in text and "dist/*" not in text


def test_required_repo_hygiene_runs_publisher_regression_once():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    commands = [step.get("run", "") for step in workflow["jobs"]["repo-hygiene"]["steps"]]
    assert commands.count("python -m pytest tests/audit/test_testpypi_release.py -q") == 1

