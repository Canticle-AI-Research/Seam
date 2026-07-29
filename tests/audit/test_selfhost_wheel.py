from __future__ import annotations

import json
import tomllib
import zipfile
from pathlib import Path

import pytest

from tools.release.build_selfhost_wheel import (
    NOFOLLOW_MODULES,
    RUNTIME_SOURCE_FILES,
    SELFHOST_FILES,
    build_selfhost_wheel,
)
from tools.release.verify_selfhost_wheel import (
    SELFHOST_RESERVED_CONTENT_BUDGET,
    verify_selfhost_wheel,
)

REPO = Path(__file__).resolve().parents[2]


def _wheel(path: Path, files: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


def _clean_files() -> dict[str, bytes]:
    return {
        "seam_runtime.cpython-312-x86_64-linux-gnu.so": b"\x7fELF compiled",
        "seam_self_host-1.1.2.dist-info/licenses/LICENSES/BUSL-1.1.txt": (
            b"Business Source License 1.1"
        ),
        "seam_self_host-1.1.2.dist-info/METADATA": b"\n".join(
            (
                b"Metadata-Version: 2.4",
                b"Name: seam-self-host",
                b"Version: 1.1.2",
                b"License-Expression: BUSL-1.1",
            )
        ),
    }


def test_selfhost_metadata_is_separate_busl_package() -> None:
    project = tomllib.loads(
        (REPO / "selfhost_pkg" / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    assert project["name"] == "seam-self-host"
    assert project["version"] == "1.1.2"
    assert project["license"] == "BUSL-1.1"
    assert project["license-files"] == ["LICENSES/BUSL-1.1.txt"]
    assert project["requires-python"] == "==3.12.*"
    assert project["scripts"] == {
        "seam-self-host": "seam_runtime.selfhost:main",
        "seam-mcp": "seam_runtime.selfhost_mcp:main",
    }
    assert "Private :: Do Not Upload" not in project.get("classifiers", [])
    private_project = tomllib.loads(
        (REPO / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    assert "Private :: Do Not Upload" in private_project["classifiers"]


def test_selfhost_build_uses_explicit_sources_and_load_bearing_exclusions() -> None:
    assert SELFHOST_FILES == (Path("README.md"), Path("pyproject.toml"))
    assert Path("seam_runtime/graph_products.py") in RUNTIME_SOURCE_FILES
    assert Path("seam_runtime/context_assembly.py") in RUNTIME_SOURCE_FILES
    assert Path("seam_runtime/lifecycle.py") in RUNTIME_SOURCE_FILES
    assert Path("seam_runtime/public_api.py") in RUNTIME_SOURCE_FILES
    assert Path("seam_runtime/reasoning_patterns.py") in RUNTIME_SOURCE_FILES
    assert Path("seam_runtime/reasoning_promotion.py") in RUNTIME_SOURCE_FILES
    assert Path("seam_runtime/qualification.py") in RUNTIME_SOURCE_FILES
    assert Path("seam_runtime/conversation.py") in RUNTIME_SOURCE_FILES
    assert Path("seam_runtime/event_count_context.py") in RUNTIME_SOURCE_FILES
    assert Path("seam_runtime/tokenization.py") in RUNTIME_SOURCE_FILES
    assert Path("seam_runtime/retrieval_orchestrator/__init__.py") in RUNTIME_SOURCE_FILES
    assert Path("seam_runtime/selfhost_mcp.py") in RUNTIME_SOURCE_FILES
    assert len(NOFOLLOW_MODULES) == 18
    assert "seam_runtime.public_api" not in NOFOLLOW_MODULES
    assert "seam_runtime.conversation" not in NOFOLLOW_MODULES
    assert "seam_runtime.event_count_context" not in NOFOLLOW_MODULES
    assert "seam_runtime.tokenization" not in NOFOLLOW_MODULES
    assert "seam_runtime.retrieval_orchestrator" not in NOFOLLOW_MODULES
    assert "seam_runtime.selfhost_mcp" not in NOFOLLOW_MODULES
    # The internal tool registry describes the architecture in its tool
    # metadata and is served verbatim by tools/list, so the wheel ships the
    # opaque surface instead. See test_selfhost_mcp_surface_is_opaque.
    assert "seam_runtime.mcp" in NOFOLLOW_MODULES
    assert "seam_runtime.mcp_protocol" in NOFOLLOW_MODULES
    # Ignore dot-directories: untracked agent working state (`.ua/`) lives
    # under seam_runtime and is not runtime source the wheel would ever ship.
    assert set(RUNTIME_SOURCE_FILES) == {
        path.relative_to(REPO)
        for path in (REPO / "seam_runtime").rglob("*.py")
        if not any(part.startswith(".") for part in path.relative_to(REPO).parts)
    }


def test_selfhost_gate_accepts_clean_compiled_busl_wheel(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path / "clean.whl", _clean_files())
    assert verify_selfhost_wheel(wheel, budget={}) == ()


def test_selfhost_gate_rejects_a_similar_but_different_version(
    tmp_path: Path,
) -> None:
    files = _clean_files()
    metadata_path = "seam_self_host-1.1.2.dist-info/METADATA"
    files[metadata_path] = files[metadata_path].replace(
        b"Version: 1.1.2",
        b"Version: 1.1.20",
    )

    errors = verify_selfhost_wheel(
        _wheel(tmp_path / "wrong-version.whl", files),
        budget={},
    )

    assert any("version is not 1.1.2" in error for error in errors)


@pytest.mark.parametrize(
    "source_path",
    (
        "seam_runtime/mirl.py",
        "seam_runtime/mirl.pyc",
        "seam_runtime/mirl.pyo",
        "seam_self_host-1.1.2.data/purelib/seam_runtime/mirl.py",
        "seam_runtime.py",
    ),
)
def test_selfhost_gate_rejects_runtime_source(
    tmp_path: Path, source_path: str
) -> None:
    files = _clean_files()
    files[source_path] = b"private source"
    wheel = _wheel(tmp_path / f"source-{len(files)}.whl", files)
    errors = verify_selfhost_wheel(wheel, budget={})
    assert any("seam_runtime source" in error for error in errors)


def test_selfhost_gate_requires_busl_text_and_metadata(tmp_path: Path) -> None:
    files = _clean_files()
    del files["seam_self_host-1.1.2.dist-info/licenses/LICENSES/BUSL-1.1.txt"]
    files["seam_self_host-1.1.2.dist-info/METADATA"] = b"\n".join(
        (b"Name: seam-self-host", b"Version: 1.1.2", b"License-Expression: MIT")
    )
    wheel = _wheel(tmp_path / "missing-busl.whl", files)
    errors = verify_selfhost_wheel(wheel, budget={})
    assert any("missing licenses/LICENSES/BUSL-1.1.txt" in error for error in errors)
    assert any("does not declare BUSL-1.1" in error for error in errors)


def test_selfhost_gate_scans_contents_and_exempts_license(tmp_path: Path) -> None:
    files = _clean_files()
    files["seam_runtime.cpython-312-x86_64-linux-gnu.so"] += b"MIRL"
    files[
        "seam_self_host-1.1.2.dist-info/licenses/LICENSES/BUSL-1.1.txt"
    ] += b" MIRL MIRL"
    wheel = _wheel(tmp_path / "ratchet.whl", files)
    errors = verify_selfhost_wheel(wheel, budget={b"MIRL": 0})
    assert any("MIRL appears 1 times, budget 0" in error for error in errors)
    assert verify_selfhost_wheel(wheel, budget={b"MIRL": 1}) == ()


def test_selfhost_reserved_budget_matches_measured_baseline() -> None:
    assert SELFHOST_RESERVED_CONTENT_BUDGET[b"MIRL"] == 133
    assert SELFHOST_RESERVED_CONTENT_BUDGET[b"knowledge_graph"] == 18
    assert SELFHOST_RESERVED_CONTENT_BUDGET[b"reasoning_graph"] == 12
    assert sum(SELFHOST_RESERVED_CONTENT_BUDGET.values()) == 414


def test_selfhost_build_refuses_nonempty_output_without_deleting_it(
    tmp_path: Path,
) -> None:
    output = tmp_path / "dist"
    output.mkdir()
    sentinel = output / "operator-owned.txt"
    sentinel.write_text("preserve me", encoding="utf-8")
    with pytest.raises(ValueError, match="output directory must be empty"):
        build_selfhost_wheel(output)
    assert sentinel.read_text(encoding="utf-8") == "preserve me"


def test_selfhost_mcp_surface_is_opaque() -> None:
    """The wheel's MCP surface must not describe the runtime's internals.

    Tool metadata is served verbatim to every connected client by
    ``tools/list``, so a description naming a reserved identifier discloses the
    architecture to anyone who connects. This is the regression that shipped
    the internal registry would reintroduce.
    """
    from seam_runtime.selfhost_mcp import TOOL_METADATA, _dispatch_mcp_method

    assert set(TOOL_METADATA) == {"seam_remember", "seam_recall", "seam_context"}

    listing = json.dumps(_dispatch_mcp_method(None, "tools/list", {}))
    for marker in SELFHOST_RESERVED_CONTENT_BUDGET:
        assert marker.decode("ascii") not in listing, (
            f"MCP tools/list disclosed reserved identifier {marker!r}"
        )

    initialize = _dispatch_mcp_method(None, "initialize", {})
    assert "MIRL" not in json.dumps(initialize)


def test_selfhost_mcp_reaches_no_operation_beyond_the_public_api() -> None:
    """Every MCP tool must map onto an audited ``public_api`` operation."""
    import inspect

    from seam_runtime import public_api, selfhost_mcp

    source = inspect.getsource(selfhost_mcp._call_tool)
    assert "from .public_api import" in source
    for operation in ("remember", "recall", "context"):
        assert hasattr(public_api, operation)
