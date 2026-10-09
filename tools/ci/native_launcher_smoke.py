"""Native clean-install/launcher witnesses in disposable standard hosted VMs.

This is a verification harness, not an operator installer. Runtime construction
is intercepted only during selection probes, after the actual platform install.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from seam_runtime import installer

DISPATCHES = (("seam", False), ("seam", True), ("seam-benchmark", False), ("seam-dash", False), ("seam-dash", True))
EXPLICIT_NAME = "explicit with spaces ! & ^ (native) λ store.db"
QUERY = "fixture ' with spaces & | < > ^ ! rate 100%"
CAPTURE_MARKER = "SEAM_NATIVE_CAPTURE="


def require_hosted_public_ci(env: dict[str, str]) -> Path:
    if (
        env.get("GITHUB_ACTIONS") != "true"
        or env.get("GITHUB_REPOSITORY") != "Canticle-AI-Research/Seam"
        or env.get("SEAM_NATIVE_PUBLIC_REPOSITORY") != "true"
        or env.get("SEAM_NATIVE_RUNNER_ENVIRONMENT") != "github-hosted"
        or not env.get("RUNNER_TEMP")
    ):
        raise RuntimeError("Clean installation requires a standard hosted public SEAM CI job.")
    root = Path(env["RUNNER_TEMP"]).resolve()
    if not root.is_dir():
        raise RuntimeError("Clean installation requires a standard hosted public SEAM CI job with RUNNER_TEMP.")
    return root


@contextlib.contextmanager
def environment(env: dict[str, str]):
    with patch.dict(os.environ, env, clear=True):
        yield


def isolated_environment(root: Path) -> dict[str, str]:
    # Keep only OS execution essentials. Never inherit provider, GitHub, pip,
    # keychain, SSH, pgvector, client or operator configuration credentials.
    keep = ("PATH", "SystemRoot", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "LANG", "LC_ALL")
    env = {key: os.environ[key] for key in keep if key in os.environ}
    env.setdefault("PATH", os.defpath)
    paths = {
        "HOME": root / "home with spaces", "USERPROFILE": root / "home with spaces",
        "LOCALAPPDATA": root / "local app data with spaces", "APPDATA": root / "app data",
        "XDG_CONFIG_HOME": root / "config", "XDG_CACHE_HOME": root / "cache",
        "TEMP": root / "temp", "TMP": root / "temp", "TMPDIR": root / "temp",
    }
    for name, path in paths.items():
        path.mkdir(parents=True, exist_ok=True)
        env[name] = str(path)
    env.update({
        "PIP_CONFIG_FILE": os.devnull, "PIP_NO_INPUT": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
        "PY_PYTHON3": f"{sys.version_info.major}.{sys.version_info.minor}",
    })
    return env


def write_probe(root: Path) -> Path:
    probe = root / "capture imports"
    probe.mkdir(parents=True, exist_ok=True)
    # sitecustomize errors normally allow Python to continue. Exit immediately
    # on any hook failure so the unpatched runtime can never open a store.
    source = '''import hashlib, json, os, sys
from pathlib import Path
target = os.environ.get("SEAM_NATIVE_PROBE_TARGET")
if target:
    try:
        import seam
        from seam_runtime import cli, dashboard, installer
        def capture(path, dispatch=None):
            payload = {
                "target": target, "environment": os.environ.get("SEAM_DB_PATH"),
                "database": str(path), "argv": sys.argv[1:], "dispatch_argv": dispatch,
                "executable": sys.executable,
                "modules": {"seam": seam.__file__, "installer": installer.__file__},
                "installer_sha256": hashlib.sha256(Path(installer.__file__).read_bytes()).hexdigest(),
            }
            print("SEAM_NATIVE_CAPTURE=" + json.dumps(payload, sort_keys=True), flush=True)
            raise SystemExit(int(os.environ.get("SEAM_NATIVE_PROBE_EXIT", "0")))
        cli.SeamRuntime = capture
        dashboard.SeamRuntime = capture
        if target == "seam-benchmark":
            def parse(argv):
                capture(cli.build_parser().parse_args(argv).db, argv)
            seam.run_cli = parse
    except BaseException:
        sys.stderr.write("Native capture initialization failed; refusing unqualified runtime execution.\\n")
        os._exit(91)
'''
    (probe / "sitecustomize.py").write_text(source, encoding="utf-8")
    return probe


def callers() -> tuple[str, ...]:
    return ("cmd", "cmd-on", "powershell", "pwsh") if os.name == "nt" else ("posix",)


def launch(shim: Path, argv: list[str], env: dict[str, str], cwd: Path, caller: str) -> subprocess.CompletedProcess[str]:
    if caller == "posix":
        command = [str(shim), *argv]
    elif caller in {"cmd", "cmd-on"}:
        # Resolve the installed shim by PATH, as an ordinary global command.
        # Always quote arguments, including standalone shell metacharacters.
        words = [shim.name, *argv]
        encoded = [subprocess.list2cmdline([word]) for word in words]
        encoded = [word if word.startswith('"') else '"' + word + '"' for word in encoded]
        # Pass CMD's raw command line directly to CreateProcess. Applying the
        # C-runtime argv serializer to the /c payload would escape its quotes
        # using rules that CMD itself does not implement.
        command = subprocess.list2cmdline([env.get("COMSPEC", "cmd.exe")])
        mode = "on" if caller == "cmd-on" else "off"
        command += f' /d /v:{mode} /s /c "' + " ".join(encoded) + '"'
    else:
        executable = shutil.which(caller, path=env["PATH"])
        if not executable:
            raise RuntimeError(f"Required native caller missing: {caller}")
        def literal(value):
            return "'" + value.replace("'", "''") + "'"
        script = "$arguments = @(" + ",".join(literal(word) for word in argv) + ")\n"
        script += "& " + literal(shim.name) + " @arguments\nexit $LASTEXITCODE\n"
        encoded_script = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        command = [executable, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded_script]
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8", timeout=45)


def capture_case(layout: installer.InstallLayout, base_env: dict[str, str], root: Path,
                 caller: str, name: str, selected: str | None, explicit: bool, code: int = 0) -> dict:
    env = dict(base_env)
    env.pop("SEAM_DB_PATH", None)
    if selected is not None:
        env["SEAM_DB_PATH"] = selected
    env["SEAM_NATIVE_PROBE_TARGET"] = name
    env["SEAM_NATIVE_PROBE_EXIT"] = str(code)
    # CMD /v:on can expand caller-typed ! before it starts the shim. Keep that
    # boundary explicit rather than pretend the shim can undo caller parsing.
    # Inherited environment and baked target/default/diagnostic paths retain !.
    query = QUERY.replace("!", "") if caller == "cmd-on" else QUERY
    explicit_name = EXPLICIT_NAME.replace("!", "") if caller == "cmd-on" else EXPLICIT_NAME
    argv = {
        "seam": ["memory", "search", query],
        "seam-benchmark": ["run", "surface", "--output", "output with spaces.json"],
        "seam-dash": ["--snapshot", "--no-clear", "--run", query],
    }[name]
    if explicit:
        argv = ["--db", str(root / explicit_name), *argv]
    shim = layout.bin_dir / (name + ".cmd" if layout.is_windows else name)
    result = launch(shim, argv, env, root, caller)
    lines = [line[len(CAPTURE_MARKER):] for line in result.stdout.splitlines() if line.startswith(CAPTURE_MARKER)]
    assert result.returncode == code, (caller, name, result.returncode, result.stdout, result.stderr)
    assert len(lines) == 1, (caller, name, result.stdout, result.stderr)
    payload = json.loads(lines[0])
    expected = selected or str(layout.persistent_db_path)
    assert payload["target"] == name, ("target", payload)
    assert payload["environment"] == expected, ("selection", caller, name, selected, payload)
    assert payload["database"] == (str(root / explicit_name) if explicit else expected), ("selection", payload)
    assert payload["argv"] == argv, ("forwarding", caller, name, payload, argv)
    if name == "seam-benchmark":
        assert payload["dispatch_argv"] == ["benchmark", *argv], ("benchmark dispatch", payload)
    payload.update({"caller": caller, "explicit": explicit, "returncode": result.returncode,
                    "selection_state": "unset" if selected is None else "empty" if selected == "" else "nonempty"})
    return payload


def make_stale_shims(layout: installer.InstallLayout) -> dict[str, str]:
    """Synthetic older unconditional-default behavior; not historical bytes."""
    hashes = {}
    for name in ("seam", "seam-benchmark", "seam-dash"):
        path = layout.bin_dir / (name + ".cmd" if layout.is_windows else name)
        source = path.read_text(encoding="ascii" if layout.is_windows else "utf-8")
        if layout.is_windows:
            assert "if not defined SEAM_DB_PATH set " in source
            source = source.replace("if not defined SEAM_DB_PATH set ", "set ", 1)
        else:
            assert 'if [ -z "${SEAM_DB_PATH:-}" ]; then\n' in source
            source = source.replace('if [ -z "${SEAM_DB_PATH:-}" ]; then\n', "", 1)
            source = source.replace("\nfi\nexport SEAM_DB_PATH", "\nexport SEAM_DB_PATH", 1)
        path.write_text(source, encoding="ascii" if layout.is_windows else "utf-8")
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def database_snapshot(root: Path) -> dict[str, str]:
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file() and path.name.endswith((".db", ".db-wal", ".db-shm"))}


def create_fixture_store(root: Path) -> list[Path]:
    corpus = root / "owned custom corpus with spaces"
    corpus.mkdir(parents=True)
    store = corpus / "chosen.db"
    with contextlib.closing(sqlite3.connect(store)) as connection:
        with connection:
            connection.execute("CREATE TABLE qualification_sentinel(value TEXT)")
            connection.execute("INSERT INTO qualification_sentinel VALUES (?)", ("owned native fixture; retain exactly",))
    metadata = corpus / "path-record.json"
    metadata.write_text(json.dumps({"store": str(store), "fixture": "owned preservation sentinel"}) + "\n", encoding="utf-8")
    return [store, metadata]


@contextlib.contextmanager
def preserve_files(paths: list[Path], receipt: dict, stage: str):
    def snapshot():
        return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None for path in paths}
    before = snapshot()
    assert all(value is not None for value in before.values()), "missing initial owned fixture file"
    try:
        yield
    finally:
        after = snapshot()
        receipt.setdefault("preservation", {})[stage] = {"before": before, "after": after, "unchanged": before == after}
        assert after == before, ("fixture files changed", stage, before, after)


def metacharacter_layout(layout: installer.InstallLayout, root: Path) -> installer.InstallLayout:
    component = (
        "baked %literal% ! & ^ (native) paths" if layout.is_windows else
        "baked ' \" $HOME `printf altered` $(printf altered) \\ ! % & (native) paths"
    )
    special = root / component
    entries = []
    for entry in (layout.seam_entry, layout.benchmark_entry, layout.dashboard_entry):
        target = special / entry.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry, target)
        entries.append(target)
    return installer.InstallLayout(special / "repo", root, layout.venv_dir, root / "special bin", *entries,
                                   special / "state/seam.db", layout.is_windows)


def run_package_only_update(layout: installer.InstallLayout, repo: Path, env: dict[str, str], root: Path, receipt: dict) -> None:
    python = layout.venv_dir / ("Scripts/python.exe" if layout.is_windows else "bin/python")
    command = [str(python), "-m", "pip", "install", "--force-reinstall", "--no-deps", f"{repo}[dash]"]
    result = subprocess.run(command, cwd=root, env=env, text=True, encoding="utf-8", capture_output=True, timeout=600)
    receipt["package_only_update"] = {
        "operation": "forced package-only reinstall of exact checked-out version, not an index/version migration",
        "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr,
    }
    assert result.returncode == 0, ("package-only update", result.stdout, result.stderr)


def assert_installed_capture(row: dict, layout: installer.InstallLayout, source_hash: str) -> None:
    prefix = layout.venv_dir.resolve()
    assert Path(row["executable"]).absolute().is_relative_to(prefix), ("managed interpreter", row)
    for path in row["modules"].values():
        assert Path(path).resolve().is_relative_to(prefix), ("installed module", row)
    assert row["installer_sha256"] == source_hash, ("installed source identity", row)


def run_platform_install(repo: Path, env: dict[str, str], root: Path, receipt: dict, stage: str) -> None:
    script = repo / "installers" / (
        "install_seam_windows.ps1" if os.name == "nt" else
        "install_seam_macos.sh" if platform.system() == "Darwin" else "install_seam_linux.sh"
    )
    if os.name == "nt":
        command = ["powershell", "-NoProfile", "-NonInteractive", "-File", str(script)]
    else:
        command = ["sh", str(script)]
    command += ["--repo-root", str(repo), "--skip-pip-upgrade"]
    result = subprocess.run(command, cwd=root, env=env, text=True, encoding="utf-8", capture_output=True, timeout=600)
    receipt.setdefault("installs", []).append({
        "stage": stage, "entrypoint": str(script.relative_to(repo)), "returncode": result.returncode,
        "stdout": result.stdout, "stderr": result.stderr,
    })
    assert result.returncode == 0, ("platform install", stage, result.stdout, result.stderr)
    assert "SEAM installer: PASS" in result.stdout and "SEAM doctor: PASS" in result.stdout


def qualify(repo: Path, runner_temp: Path, receipt: dict) -> None:
    source_hash = hashlib.sha256((repo / "seam_runtime/installer.py").read_bytes()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="seam-native-", dir=runner_temp) as temporary:
        root = Path(temporary).resolve()
        assert root.is_relative_to(runner_temp) and root != runner_temp
        env = isolated_environment(root)
        with environment(env):
            layout = installer.detect_layout(repo)
        assert layout.install_root.is_relative_to(root)
        assert not layout.venv_dir.exists(), "clean-install target already exists"
        protected = create_fixture_store(root)
        with preserve_files(protected, receipt, "clean-install"):
            run_platform_install(repo, env, root, receipt, "clean")
        native_python = layout.venv_dir / ("Scripts/python.exe" if layout.is_windows else "bin/python")
        version = subprocess.run([str(native_python), "-c", "import json,sys;print(json.dumps(list(sys.version_info[:3])))"],
                                 env=env, cwd=root, check=True, capture_output=True, text=True)
        receipt["installed_python"] = json.loads(version.stdout)
        assert receipt["installed_python"][:2] == [sys.version_info.major, sys.version_info.minor]
        packages = subprocess.run(
            [str(native_python), "-c", "import importlib.metadata as m,json; print(json.dumps({n:m.version(n) for n in ('seam-suite','rich','tiktoken','textual')}))"],
            env=env, cwd=root, check=True, capture_output=True, text=True,
        )
        receipt["installed_packages"] = json.loads(packages.stdout)
        probe = write_probe(root)
        probe_env = dict(env, PYTHONPATH=str(probe), PATH=str(layout.bin_dir) + os.pathsep + env["PATH"])
        settings = Path(env["XDG_CONFIG_HOME"]) / "seam/seam.env"
        settings.parent.mkdir(parents=True)
        settings.write_text("SEAM_DB_PATH=persisted-must-not-displace-process.db\n", encoding="utf-8")
        choices = [None, "", "   ", "relative with spaces.db", "chosen ' $HOME ! %literal% & λ\nstore.db", str(protected[0])]
        receipt["selection_cases"] = []
        for stage in ("clean", "regenerated"):
            before = database_snapshot(root)
            for caller in callers():
                for name, explicit in DISPATCHES:
                    for choice in choices:
                        row = capture_case(layout, probe_env, root, caller, name, choice, explicit)
                        assert_installed_capture(row, layout, source_hash)
                        row["stage"] = stage
                        receipt["selection_cases"].append(row)
                for code in (0, 7, 42):
                    row = capture_case(layout, probe_env, root, caller, "seam", None, False, code)
                    assert_installed_capture(row, layout, source_hash)
                    row["stage"] = stage
                    receipt["selection_cases"].append(row)
            assert database_snapshot(root) == before, "selection probes changed disposable database files"
            if stage == "clean":
                receipt["synthetic_stale_shim_hashes"] = make_stale_shims(layout)
                for caller in callers():
                    for name in ("seam", "seam-benchmark", "seam-dash"):
                        try:
                            capture_case(layout, probe_env, root, caller, name, "chosen stale witness.db", False)
                        except AssertionError as exc:
                            assert exc.args and "selection" in str(exc.args[0]), exc
                        else:
                            raise AssertionError("synthetic stale shim did not reproduce selection override")
                shim_paths = [layout.bin_dir / (name + ".cmd" if layout.is_windows else name)
                              for name in ("seam", "seam-benchmark", "seam-dash")]
                with preserve_files([*protected, *shim_paths], receipt, "package-only-stale-shims"):
                    run_package_only_update(layout, repo, env, root, receipt)
                # The real package-only reinstall must leave obsolete global
                # launcher bytes AND the custom corpus/sentinel untouched.
                for caller in callers():
                    for name in ("seam", "seam-benchmark", "seam-dash"):
                        try:
                            capture_case(layout, probe_env, root, caller, name, "chosen stale witness.db", False)
                        except AssertionError as exc:
                            assert exc.args and "selection" in str(exc.args[0]), exc
                        else:
                            raise AssertionError("package-only update unexpectedly refreshed a stale shim")
                with preserve_files(protected, receipt, "regeneration-install"):
                    run_platform_install(repo, env, root, receipt, "regenerate")
        # Exercise baked executable/default paths containing percent signs,
        # exclamation marks, ampersands and parentheses against real installed
        # console files. The shim path itself remains an ordinary PATH command.
        special_layout = metacharacter_layout(layout, root)
        installer.write_shims(special_layout)
        special_env = dict(probe_env, PATH=str(special_layout.bin_dir) + os.pathsep + env["PATH"])
        before = database_snapshot(root)
        for caller in callers():
            for name in ("seam", "seam-benchmark", "seam-dash"):
                row = capture_case(special_layout, special_env, root, caller, name, None, False)
                assert_installed_capture(row, layout, source_hash)
                row["stage"] = "baked-metacharacter-paths"
                receipt["selection_cases"].append(row)
        assert database_snapshot(root) == before
        missing_layout = installer.InstallLayout(special_layout.repo_root, root, layout.venv_dir, root / "missing bin",
                                                root / "absent executable", layout.benchmark_entry,
                                                layout.dashboard_entry, root / "missing state/seam.db", layout.is_windows)
        installer.write_shims(missing_layout)
        missing_env = dict(env, PATH=str(missing_layout.bin_dir) + os.pathsep + env["PATH"])
        receipt["missing_target_cases"] = []
        for caller in callers():
            shim = missing_layout.bin_dir / ("seam.cmd" if layout.is_windows else "seam")
            result = launch(shim, [], missing_env, root, caller)
            assert result.returncode == 1, ("missing target", caller, result.stdout, result.stderr)
            assert "SEAM is not installed at" in result.stdout and str(missing_layout.repo_root) in result.stdout
            if not layout.is_windows:
                assert result.stdout.splitlines()[0] == f"SEAM is not installed at {missing_layout.repo_root}"
            receipt["missing_target_cases"].append({"caller": caller, "returncode": result.returncode})
        assert database_snapshot(root) == before
        receipt["source_installer_sha256"] = source_hash
        receipt["selection_probes_database_unchanged"] = True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-system", required=True, choices=("Linux", "Darwin", "Windows"))
    parser.add_argument("--expected-python", required=True)
    parser.add_argument("--expected-architecture", required=True, choices=("x64", "arm64"))
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    receipt = {
        "schema": "seam-native-launcher-qualification/1", "qualified": False,
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "git_tree": subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], text=True).strip(),
        "system": platform.system(), "release": platform.release(), "machine": platform.machine(),
        "macos_version": platform.mac_ver()[0], "windows_version": platform.win32_ver()[1],
        "runner_label": os.environ.get("SEAM_NATIVE_RUNNER_LABEL"),
        "image_os": os.environ.get("ImageOS"), "image_version": os.environ.get("ImageVersion"),
        "python": list(sys.version_info[:3]), "callers": list(callers()),
        "bounds": "Actual clean platform installation, package-only forced reinstall and regenerated managed launchers; selection runtime constructors/benchmark execution intercepted. Owned custom SQLite/path-record bytes are protected across all installs; Doctor may change its separate disposable managed state. Windows baked shim paths remain ASCII-only; Unicode selected values are transport-tested. CMD /v:on arguments avoid caller-expanded !; inherited environment and baked paths retain !. Caller-specific escaping of embedded double quotes and paired percent-variable arguments is outside these cases. No fresh-session command discovery, corpus, provider, MCP-client activation, desktop UI, WSL or other OS/Python qualification.",
    }
    try:
        runner_temp = require_hosted_public_ci(dict(os.environ))
        report = Path(args.report).resolve()
        assert report.is_relative_to(runner_temp), "report must be in disposable RUNNER_TEMP"
        assert platform.system() == args.expected_system
        assert f"{sys.version_info.major}.{sys.version_info.minor}" == args.expected_python
        architecture = {"amd64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine().lower())
        assert architecture == args.expected_architecture, ("native architecture", platform.machine())
        qualify(Path(__file__).resolve().parents[2], runner_temp, receipt)
        # qualify's TemporaryDirectory has exited successfully before any
        # success receipt is assigned or written. Report I/O is also a gate.
        receipt["qualified"] = True
        report.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        receipt["qualified"] = False
        receipt["failure"] = repr(exc)
        print(json.dumps(receipt, sort_keys=True, indent=2))
        return 1
    print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
