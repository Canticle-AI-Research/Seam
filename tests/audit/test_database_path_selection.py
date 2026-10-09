"""Launcher selection contracts; targets only print parser results, never open a DB."""

from __future__ import annotations

import inspect
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from markdown_it import MarkdownIt

from seam_runtime import config, mcp_protocol
from seam_runtime.cli import build_parser
from seam_runtime.installer import (
    InstallLayout,
    default_runtime_db_path,
    render_posix_shim,
    render_windows_cmd_shim,
    write_shims,
)

DOC_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = Path(inspect.getfile(build_parser)).resolve().parents[1]
NAMES = ("seam", "seam-benchmark", "seam-dash")
SPECIAL = "chosen ' \" $HOME `printf changed` $(printf changed) \\ & ! % λ store.db"


def _probe(path: Path, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from seam_runtime.cli import build_parser\n"
        "args = build_parser().parse_args(sys.argv[1:])\n"
        f"print(json.dumps({{'target': {name!r}, 'env': os.environ.get('SEAM_DB_PATH'), "
        "'db': args.db, 'argv': sys.argv[1:]}))\n",
        encoding="utf-8",
    )
    path.chmod(0o700)


def _environment(selected: str | None) -> dict[str, str]:
    env = {
        "PATH": os.defpath,
        "PYTHONPATH": str(SOURCE_ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    if selected is not None:
        env["SEAM_DB_PATH"] = selected
    return env


def _layout(root: Path, windows: bool = False) -> InstallLayout:
    runtime = root / "runtime with spaces"
    return InstallLayout(
        repo_root=root / "repo", install_root=root, venv_dir=runtime,
        bin_dir=root / "bin with spaces",
        seam_entry=runtime / "seam", benchmark_entry=runtime / "seam-benchmark",
        dashboard_entry=runtime / "seam-dash",
        persistent_db_path=root / "managed state" / "seam.db", is_windows=windows,
    )


@pytest.mark.parametrize("selected", [None, "", "chosen store.db", "   "])
def test_direct_default_resolver(selected, monkeypatch):
    monkeypatch.delenv("SEAM_DB_PATH", raising=False)
    if selected is not None:
        monkeypatch.setenv("SEAM_DB_PATH", selected)
    assert default_runtime_db_path() == (selected or "seam.db")


@pytest.mark.parametrize("selected", [None, "", "chosen store.db"])
@pytest.mark.parametrize("explicit", [None, "explicit store.db"])
def test_main_cli_explicit_database_wins(selected, explicit, monkeypatch):
    monkeypatch.delenv("SEAM_DB_PATH", raising=False)
    if selected is not None:
        monkeypatch.setenv("SEAM_DB_PATH", selected)
    argv = ["memory", "search", "fixture"]
    if explicit is not None:
        argv = ["--db", explicit, *argv]
    assert build_parser().parse_args(argv).db == (explicit or selected or "seam.db")


def test_main_cli_requires_db_before_subcommand():
    with pytest.raises(SystemExit) as error:
        build_parser().parse_args(["memory", "search", "fixture", "--db", "chosen.db"])
    assert error.value.code == 2


@pytest.mark.parametrize("selected", [None, "", "chosen store.db"])
@pytest.mark.parametrize("explicit", [None, "explicit store.db"])
def test_direct_mcp_precedence_without_runtime_store(selected, explicit, monkeypatch):
    observed = []
    monkeypatch.delenv("SEAM_DB_PATH", raising=False)
    if selected is not None:
        monkeypatch.setenv("SEAM_DB_PATH", selected)
    monkeypatch.setattr(mcp_protocol, "SeamRuntime", lambda path: observed.append(str(path)))
    monkeypatch.setattr(mcp_protocol, "run_mcp_server", lambda runtime: None)
    mcp_protocol.main([] if explicit is None else ["--db", explicit])
    assert observed == [explicit or selected or "seam.db"]


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("selected", [None, "", SPECIAL])
@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.skipif(os.name == "nt", reason="POSIX launcher fixtures are unavailable on Windows.")
def test_written_posix_launchers_preserve_choice_default_and_arguments(tmp_path, name, selected, explicit):
    layout = _layout(tmp_path)
    for entry, label in zip((layout.seam_entry, layout.benchmark_entry, layout.dashboard_entry), NAMES):
        _probe(entry, label)
    paths = write_shims(layout)
    assert [path.name for path in paths] == list(NAMES)
    assert sorted(path.name for path in layout.bin_dir.iterdir()) == sorted(NAMES)
    assert not layout.persistent_db_path.exists()
    argv = ["memory", "search", "fixture ' with spaces"]
    explicit_path = str(tmp_path / SPECIAL)
    if explicit:
        argv = ["--db", explicit_path, *argv]
    result = subprocess.run(
        [str(layout.bin_dir / name), *argv], env=_environment(selected),
        capture_output=True, text=True, timeout=30, check=True,
    )
    payload = json.loads(result.stdout)
    expected = selected or str(layout.persistent_db_path)
    assert payload == {
        "target": name, "env": expected,
        "db": explicit_path if explicit else expected, "argv": argv,
    }
    assert not any(tmp_path.rglob("*.db"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX launcher fixtures are unavailable on Windows.")
def test_posix_rendered_default_and_target_are_literal_data(tmp_path):
    target = tmp_path / (SPECIAL + ".probe")
    _probe(target, "literal target")
    default = tmp_path / ("managed " + SPECIAL)
    shim = tmp_path / "shim"
    shim.write_text(render_posix_shim(target, tmp_path / SPECIAL, SPECIAL, default))
    shim.chmod(0o700)
    result = subprocess.run(
        [str(shim), "memory", "search", "fixture"], env=_environment(None),
        capture_output=True, text=True, timeout=30, check=True,
    )
    payload = json.loads(result.stdout)
    assert payload["env"] == str(default)
    assert payload["db"] == str(default)
    assert payload["target"] == "literal target"
    assert not any(tmp_path.rglob("*.db"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX launcher fixtures are unavailable on Windows.")
def test_posix_missing_target_reports_literal_hint_and_fails(tmp_path):
    shim = tmp_path / "shim"
    repo = tmp_path / SPECIAL
    shim.write_text(render_posix_shim(tmp_path / "absent", repo, SPECIAL, tmp_path / "seam.db"))
    shim.chmod(0o700)
    result = subprocess.run(
        [str(shim)], env=_environment(None), capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 1
    assert result.stdout.splitlines() == [f"SEAM is not installed at {repo}", f"Run: {SPECIAL}"]
    assert not any(tmp_path.rglob("*.db"))


def test_windows_renderer_guards_default_and_quotes_literal_paths():
    shim = render_windows_cmd_shim(
        Path(r"C:\chosen path %value% !literal! & files\seam.exe"),
        Path(r"C:\repo path %value% !literal! & files"),
        r'powershell -File "C:\repo path %value% !literal! & files\install.ps1"',
        Path(r"C:\managed path %value% !literal! & files\seam.db"),
    )
    lines = shim.splitlines()
    guard = 'if not defined SEAM_DB_PATH set "SEAM_DB_PATH=C:\\managed path %%value%% !literal! & files\\seam.db"'
    assert guard in lines
    assert lines.index("setlocal DisableDelayedExpansion") < lines.index(guard)
    assert lines.index(guard) < lines.index('"%SEAM_EXE%" %*')
    assert 'set "SEAM_EXE=C:\\chosen path %%value%% !literal! & files\\seam.exe"' in lines
    assert "exit /b %ERRORLEVEL%" in lines


def test_windows_writer_retains_exact_three_targets(tmp_path):
    layout = _layout(tmp_path, windows=True)
    paths = write_shims(layout)
    assert [path.name for path in paths] == [name + ".cmd" for name in NAMES]
    for path, entry in zip(paths, (layout.seam_entry, layout.benchmark_entry, layout.dashboard_entry)):
        assert f'set "SEAM_EXE={entry}"' in path.read_text(encoding="ascii")
        assert 'if not defined SEAM_DB_PATH set "SEAM_DB_PATH=' in path.read_text(encoding="ascii")
    assert not layout.persistent_db_path.exists()


@pytest.mark.parametrize("selected", [None, "", "chosen store.db"])
def test_persisted_settings_do_not_overwrite_process_choice(tmp_path, selected):
    settings = tmp_path / "settings.env"
    settings.write_text("SEAM_DB_PATH=persisted store.db\n")
    env = {} if selected is None else {"SEAM_DB_PATH": selected}
    config.apply_persisted_to_environ(environ=env, path=settings)
    assert env["SEAM_DB_PATH"] == ("persisted store.db" if selected is None else selected)


@pytest.mark.parametrize("selected", [None, "", "chosen store.db"])
def test_benchmark_alias_keeps_the_environment_default(selected, monkeypatch):
    import seam

    observed = []
    monkeypatch.delenv("SEAM_DB_PATH", raising=False)
    if selected is not None:
        monkeypatch.setenv("SEAM_DB_PATH", selected)

    def capture(argv):
        args = build_parser().parse_args(argv)
        observed.append((argv, args.db))
        return 0

    monkeypatch.setattr(seam, "run_cli", capture)
    monkeypatch.setattr(sys, "argv", ["seam-benchmark"])
    assert seam.benchmark_main() is None
    assert observed == [(["benchmark", "run"], selected or "seam.db")]


@pytest.mark.parametrize("explicit", [None, "explicit store.db"])
def test_dashboard_parser_keeps_environment_and_explicit_precedence(explicit, monkeypatch):
    from seam_runtime import dashboard

    observed = []
    monkeypatch.setenv("SEAM_DB_PATH", "chosen store.db")
    monkeypatch.setattr(dashboard.config, "apply_persisted_to_environ", lambda: [])

    class CapturedPath(Exception):
        pass

    def capture(path):
        observed.append(path)
        raise CapturedPath

    monkeypatch.setattr(dashboard, "SeamRuntime", capture)
    argv = ["--snapshot"]
    if explicit is not None:
        argv = ["--db", explicit, *argv]
    with pytest.raises(CapturedPath):
        dashboard.main(argv)
    assert observed == [explicit or "chosen store.db"]


def test_operator_documentation_describes_precedence_and_update_boundary():
    text = (DOC_ROOT / "docs/SEAM_OPERATOR_GUIDE.md").read_text()
    normalized = " ".join(text.split())
    assert "### Database path selection" in text
    assert "preserve a nonempty inherited `SEAM_DB_PATH`" in normalized
    assert "Unset or empty" in normalized
    assert "before the subcommand" in normalized
    assert "`python seam.py`" in text
    assert "`seam.db` in the current working directory" in normalized
    assert "already installed shims" in normalized
    assert "does not report a supplied `--db`" in normalized


def test_macos_mcp_uses_existing_console_entry_point():
    text = (DOC_ROOT / "docs/MACOS.md").read_text()
    configs = [
        json.loads(token.content) for token in MarkdownIt("commonmark").parse(text)
        if token.type == "fence" and token.info.strip() == "json"
    ]
    cfg = next(item for item in configs if str(item.get("command", "")).endswith("seam-mcp"))
    assert cfg["command"] == "/Users/<you>/Library/Application Support/SEAM/runtime/bin/seam-mcp"
    assert cfg["env"]["SEAM_DB_PATH"] == "/Users/<you>/Library/Application Support/SEAM/state/seam.db"
    assert cfg["args"] == []


@pytest.mark.parametrize("path,link", [
    ("README.md", "docs/SEAM_OPERATOR_GUIDE.md#database-path-selection"),
    ("docs/setup.md", "SEAM_OPERATOR_GUIDE.md#database-path-selection"),
    ("docs/howto/README.md", "../SEAM_OPERATOR_GUIDE.md#database-path-selection"),
    ("installers/README.md", "../docs/SEAM_OPERATOR_GUIDE.md#database-path-selection"),
])
def test_operator_routes_link_to_selection_contract(path, link):
    assert link in (DOC_ROOT / path).read_text()


def test_current_documents_do_not_promise_future_discovery_or_repair():
    text = (DOC_ROOT / "docs/SEAM_OPERATOR_GUIDE.md").read_text()
    assert not re.search(r"Doctor (?:automatically )?(?:finds|relocates|moves|repairs) (?:your |the )?database", text)
