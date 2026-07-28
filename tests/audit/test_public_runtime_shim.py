from __future__ import annotations

import importlib.util
import subprocess
import sys
import tomllib
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.release.build_public import PUBLIC_FILES, build_public

REPO = Path(__file__).resolve().parents[2]
PUBLIC_PACKAGE = REPO / "public_pkg"

_CLIENT_EXPORTS = (
    "APIError",
    "AgentMemory",
    "AsyncAgentMemory",
    "AsyncSeamClient",
    "AuthenticationError",
    "ConnectionError",
    "ContextResult",
    "Health",
    "Memory",
    "RateLimitError",
    "RecallResult",
    "RememberReceipt",
    "SeamClient",
    "SeamError",
)


def _fake_seam_client(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    module = types.ModuleType("seam_client")
    module.DEFAULT_BASE_URL = "http://127.0.0.1:8765"
    for name in _CLIENT_EXPORTS:
        setattr(module, name, type(name, (), {}))
    monkeypatch.setitem(sys.modules, "seam_client", module)
    return module


def _load(path: Path, name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_shim_reexports_real_client_types(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _fake_seam_client(monkeypatch)
    shim = _load(PUBLIC_PACKAGE / "seam_runtime" / "__init__.py", "public_runtime_shim")

    assert shim.SeamClient is client.SeamClient
    assert shim.ConnectionError is client.ConnectionError
    assert shim.APIError is client.APIError
    assert shim.has_client() is True
    assert shim.has_full_runtime() is False
    assert shim.__path__ == []


def test_cli_health_uses_public_api_version(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli = _load(PUBLIC_PACKAGE / "seam.py", "public_seam_cli")

    class Client:
        def health(self) -> SimpleNamespace:
            return SimpleNamespace(status="ok", api_version="v1")

    monkeypatch.setattr(cli, "_get_client", Client)
    assert cli.cmd_health() == 0
    assert capsys.readouterr().out == "status:  ok\napi_version: v1\n"


def test_cli_status_reports_healthy_public_api(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli = _load(PUBLIC_PACKAGE / "seam.py", "public_seam_status_cli")

    class Client:
        def health(self) -> SimpleNamespace:
            return SimpleNamespace(status="ok", api_version="v1")

    monkeypatch.setenv("SEAM_SERVER_URL", "http://127.0.0.1:8765")
    monkeypatch.delenv("SEAM_BASE_URL", raising=False)
    monkeypatch.setattr(cli, "_get_client", Client)

    assert cli.cmd_status() == 0
    output = capsys.readouterr().out
    assert "Health:   ok" in output
    assert "API ver:  v1" in output
    assert "unreachable" not in output


def test_stale_private_submodule_is_inaccessible(tmp_path: Path) -> None:
    package = tmp_path / "seam_runtime"
    package.mkdir()
    (package / "__init__.py").write_text(
        (PUBLIC_PACKAGE / "seam_runtime" / "__init__.py").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (package / "mirl.py").write_text("STALE_PRIVATE_MODULE = True\n", encoding="utf-8")

    exports = "\n".join(f"{name} = type({name!r}, (), {{}})" for name in _CLIENT_EXPORTS)
    (tmp_path / "seam_client.py").write_text(
        f"DEFAULT_BASE_URL = 'http://127.0.0.1:8765'\n{exports}\n",
        encoding="utf-8",
    )
    script = f"""
import importlib
import sys
sys.path.insert(0, {str(tmp_path)!r})
import seam_runtime
assert seam_runtime.has_full_runtime() is False
try:
    importlib.import_module("seam_runtime.mirl")
except ModuleNotFoundError:
    pass
else:
    raise AssertionError("stale private submodule remained importable")
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_public_metadata_is_minimal_and_independent() -> None:
    project = tomllib.loads((PUBLIC_PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert project["name"] == "seam-runtime"
    assert project["version"] == "2.3.1"
    assert project["requires-python"] == ">=3.10"
    assert project["dependencies"] == ["seam-client>=0.1.0,<0.2"]
    assert "Development Status :: 3 - Alpha" in project["classifiers"]
    assert "optional-dependencies" not in project
    assert "Seam_Runtime" in project["urls"]["Repository"]


def test_public_build_copies_only_explicit_sources() -> None:
    assert PUBLIC_FILES == (
        Path("README.md"),
        Path("pyproject.toml"),
        Path("seam.py"),
        Path("seam_runtime/__init__.py"),
    )


def test_public_build_refuses_nonempty_output_without_deleting_it(tmp_path: Path) -> None:
    output = tmp_path / "dist"
    output.mkdir()
    sentinel = output / "operator-owned.txt"
    sentinel.write_text("preserve me", encoding="utf-8")

    with pytest.raises(ValueError, match="output directory must be empty"):
        build_public(output)

    assert sentinel.read_text(encoding="utf-8") == "preserve me"
