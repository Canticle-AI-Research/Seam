"""Local fixtures for the native qualification harness, not clean-install proof."""

from __future__ import annotations

import inspect
import json
import os
import platform
import sys
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from seam_runtime import installer
from tools.ci import native_launcher_smoke as smoke


@pytest.mark.parametrize("missing", [
    "GITHUB_ACTIONS", "GITHUB_REPOSITORY", "SEAM_NATIVE_PUBLIC_REPOSITORY",
    "SEAM_NATIVE_RUNNER_ENVIRONMENT", "RUNNER_TEMP",
])
def test_clean_install_rejects_ineligible_environments(tmp_path, missing):
    env = {
        "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "Canticle-AI-Research/Seam",
        "SEAM_NATIVE_PUBLIC_REPOSITORY": "true",
        "SEAM_NATIVE_RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_TEMP": str(tmp_path),
    }
    env.pop(missing)
    with pytest.raises(RuntimeError, match="hosted public SEAM"):
        smoke.require_hosted_public_ci(env)


def test_clean_install_rejects_private_repository(tmp_path):
    env = {
        "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "Canticle-AI-Research/Seam",
        "SEAM_NATIVE_PUBLIC_REPOSITORY": "false",
        "SEAM_NATIVE_RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_TEMP": str(tmp_path),
    }
    with pytest.raises(RuntimeError, match="hosted public SEAM"):
        smoke.require_hosted_public_ci(env)


def test_installer_environment_drops_credentials_and_user_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fixture-only-never-inherited")
    monkeypatch.setenv("PIP_INDEX_URL", "https://fixture.invalid/private")
    monkeypatch.setenv("SEAM_PGVECTOR_DSN", "fixture-only-never-inherited")
    monkeypatch.setenv("PYTHONPATH", "untrusted fixture import path")
    env = smoke.isolated_environment(tmp_path)
    for name in ("OPENAI_API_KEY", "PIP_INDEX_URL", "SEAM_PGVECTOR_DSN", "PYTHONPATH"):
        assert name not in env
    assert env["PIP_CONFIG_FILE"] == os.devnull
    assert Path(env["HOME"]).is_relative_to(tmp_path)
    assert Path(env["LOCALAPPDATA"]).is_relative_to(tmp_path)


def test_workflow_has_explicit_free_public_native_route_and_exact_head():
    root = Path(__file__).resolve().parents[2]
    data = yaml.load((root / ".github/workflows/native-launchers.yml").read_text(), Loader=yaml.BaseLoader)
    job = data["jobs"]["native-launchers"]
    assert "github.event.repository.private == false" in job["if"]
    assert "head.repo.full_name == github.repository" in job["if"]
    matrix = job["strategy"]["matrix"]["include"]
    assert {(x["system"], x["architecture"]) for x in matrix} == {
        ("Linux", "x64"), ("Windows", "x64"), ("Darwin", "x64"), ("Darwin", "arm64"),
    }
    assert {x["python"] for x in matrix} == {"3.11", "3.12"}
    assert not any("large" in x["label"] for x in matrix)
    checkout = next(x for x in job["steps"] if x.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["ref"] == "${{ github.event.pull_request.head.sha || github.sha }}"
    assert checkout["with"]["persist-credentials"] == "false"
    assert not any("actions/upload-artifact" in x.get("uses", "") or "actions/cache" in x.get("uses", "")
                   for x in job["steps"])
    assert set(data["jobs"]) == {"native-launchers"}
    assert "self-hosted" not in json.dumps(data) and "seam-box" not in json.dumps(data)


@pytest.fixture
def fake_hosted_context(tmp_path, monkeypatch):
    for key, value in {
        "GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "Canticle-AI-Research/Seam",
        "SEAM_NATIVE_PUBLIC_REPOSITORY": "true",
        "SEAM_NATIVE_RUNNER_ENVIRONMENT": "github-hosted", "RUNNER_TEMP": str(tmp_path),
    }.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(smoke.subprocess, "check_output", lambda *args, **kwargs: "fixture-identity\n")
    machine = platform.machine().lower()
    arch = "arm64" if machine in {"arm64", "aarch64"} else "x64"
    report = tmp_path / "receipt.json"
    return ["--expected-system", platform.system(), "--expected-python", f"{sys.version_info.major}.{sys.version_info.minor}",
            "--expected-architecture", arch, "--report", str(report)], report


def test_failure_after_provisional_success_clears_qualification(fake_hosted_context, monkeypatch, capsys):
    argv, report = fake_hosted_context
    def cleanup_failure(repo, runner_temp, receipt):
        receipt["qualified"] = True
        raise PermissionError("fixture cleanup failure")
    monkeypatch.setattr(smoke, "qualify", cleanup_failure)
    assert smoke.main(argv) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["qualified"] is False and "cleanup failure" in payload["failure"]
    assert not report.exists()


def test_report_write_failure_clears_qualification(fake_hosted_context, monkeypatch, capsys):
    argv, report = fake_hosted_context
    monkeypatch.setattr(smoke, "qualify", lambda repo, runner_temp, receipt: None)
    original = Path.write_text
    def fail_report(path, *args, **kwargs):
        if path == report:
            raise PermissionError("fixture report failure")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", fail_report)
    assert smoke.main(argv) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["qualified"] is False and "report failure" in payload["failure"]


@pytest.mark.parametrize("change", ["modify", "delete"])
def test_fixture_preservation_detects_store_changes(tmp_path, change):
    files = smoke.create_fixture_store(tmp_path)
    receipt = {}
    with pytest.raises(AssertionError, match="fixture files changed"):
        with smoke.preserve_files(files, receipt, "regenerate"):
            if change == "modify":
                files[0].write_bytes(b"fixture corruption")
            else:
                files[0].unlink()
    assert receipt["preservation"]["regenerate"]["unchanged"] is False


def test_fixture_preservation_records_unchanged_store_and_launcher(tmp_path):
    files = smoke.create_fixture_store(tmp_path)
    shim = tmp_path / "stale shim"
    shim.write_text("fixture stale bytes")
    receipt = {}
    with smoke.preserve_files([*files, shim], receipt, "package-only"):
        pass
    evidence = receipt["preservation"]["package-only"]
    assert evidence["unchanged"] is True and evidence["before"] == evidence["after"]


def test_native_cmd_delayed_expansion_mode_is_real_caller(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setattr(smoke.subprocess, "run", lambda command, **kwargs: captured.append(command))
    smoke.launch(tmp_path / "seam.cmd", ["memory", "search", "fixture"],
                 {"COMSPEC": r"C:\Windows\System32\cmd.exe", "PATH": os.defpath}, tmp_path, "cmd-on")
    assert " /v:on /s /c " in captured[0]


@pytest.fixture
def local_targets(tmp_path):
    """Execute real entrypoints through disposable targets with no DB opens."""
    source = Path(inspect.getfile(installer)).resolve().parents[1]
    env = smoke.isolated_environment(tmp_path)
    with smoke.environment(env):
        layout = installer.detect_layout(source)
    layout.seam_entry.parent.mkdir(parents=True)
    for entry, body in (
        (layout.seam_entry, "from seam import main\nmain()\n"),
        (layout.benchmark_entry, "from seam import benchmark_main\nbenchmark_main()\n"),
        (layout.dashboard_entry, "from seam_runtime.dashboard import main\nmain()\n"),
    ):
        entry.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        entry.chmod(0o700)
    installer.write_shims(layout)
    probe = smoke.write_probe(tmp_path)
    env["PYTHONPATH"] = os.pathsep.join((str(probe), str(source)))
    env["PATH"] = str(layout.bin_dir) + os.pathsep + env["PATH"]
    return layout, env


@pytest.mark.skipif(os.name == "nt", reason="Local POSIX target fixtures do not generate Windows PE executables.")
@pytest.mark.parametrize("name,explicit", smoke.DISPATCHES)
@pytest.mark.parametrize("choice", [None, "", "   ", "chosen ' $HOME ! %literal% λ\nstore.db"])
def test_capture_cases_execute_real_posix_entrypoints(local_targets, tmp_path, name, explicit, choice):
    layout, env = local_targets
    row = smoke.capture_case(layout, env, tmp_path, "posix", name, choice, explicit)
    assert row["environment"] == (choice or str(layout.persistent_db_path))
    assert row["database"] == (str(tmp_path / smoke.EXPLICIT_NAME) if explicit else row["environment"])
    assert not list(tmp_path.rglob("*.db"))


@pytest.mark.skipif(os.name == "nt", reason="Local POSIX target fixtures do not generate Windows PE executables.")
def test_stale_shims_reproduce_override_and_writer_regenerates(local_targets, tmp_path):
    layout, env = local_targets
    smoke.make_stale_shims(layout)
    selected = "chosen fixture.db"
    with pytest.raises(AssertionError, match="selection"):
        smoke.capture_case(layout, env, tmp_path, "posix", "seam", selected, False)
    installer.write_shims(layout)
    row = smoke.capture_case(layout, env, tmp_path, "posix", "seam", selected, False)
    assert row["database"] == selected


@pytest.mark.skipif(os.name == "nt", reason="Local POSIX target fixtures do not generate Windows PE executables.")
@pytest.mark.parametrize("code", [0, 7, 42])
def test_capture_exit_status_propagates(local_targets, tmp_path, code):
    layout, env = local_targets
    row = smoke.capture_case(layout, env, tmp_path, "posix", "seam", None, False, code=code)
    assert row["returncode"] == code


@pytest.mark.skipif(os.name == "nt", reason="Local POSIX target fixtures do not generate Windows PE executables.")
@pytest.mark.parametrize("name", ["seam", "seam-benchmark", "seam-dash"])
def test_baked_posix_executable_and_default_are_literal(local_targets, tmp_path, name):
    layout, env = local_targets
    special = smoke.metacharacter_layout(layout, tmp_path)
    installer.write_shims(special)
    env = dict(env, PATH=str(special.bin_dir) + os.pathsep + env["PATH"])
    row = smoke.capture_case(special, env, tmp_path, "posix", name, None, False)
    assert row["database"] == str(special.persistent_db_path)
    assert all(token in str(special.persistent_db_path) for token in ("'", '"', "$HOME", "`printf", "$(printf"))
    assert not list(tmp_path.rglob("*.db"))


@pytest.mark.skipif(os.name == "nt", reason="Local POSIX target fixtures do not generate Windows PE executables.")
def test_baked_posix_missing_diagnostic_is_literal(local_targets, tmp_path):
    layout, env = local_targets
    special = smoke.metacharacter_layout(layout, tmp_path)
    missing = replace(special, seam_entry=tmp_path / "absent target")
    installer.write_shims(missing)
    result = smoke.launch(missing.bin_dir / "seam", [], env, tmp_path, "posix")
    assert result.returncode == 1
    assert result.stdout.splitlines()[0] == f"SEAM is not installed at {missing.repo_root}"
    assert str(missing.repo_root) in result.stdout.splitlines()[1]
