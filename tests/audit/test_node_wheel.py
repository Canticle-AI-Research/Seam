from __future__ import annotations

import tomllib
import zipfile
from pathlib import Path

import pytest

from tools.release.build_node_wheel import (
    NODE_FILES,
    NOFOLLOW_MODULES,
    RUNTIME_SOURCE_FILES,
    build_node_wheel,
)
from tools.release.verify_node_wheel import (
    NODE_RESERVED_CONTENT_BUDGET,
    verify_node_wheel,
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
        "seam_node-2.4.0.dist-info/licenses/LICENSES/BUSL-1.1.txt": (
            b"Business Source License 1.1"
        ),
        "seam_node-2.4.0.dist-info/METADATA": b"\n".join(
            (
                b"Metadata-Version: 2.4",
                b"Name: seam-node",
                b"Version: 2.4.0",
                b"License-Expression: BUSL-1.1",
            )
        ),
    }


def test_node_metadata_is_separate_busl_package() -> None:
    project = tomllib.loads(
        (REPO / "node_pkg" / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    assert project["name"] == "seam-node"
    assert project["version"] == "2.4.0"
    assert project["license"] == "BUSL-1.1"
    assert project["license-files"] == ["LICENSES/BUSL-1.1.txt"]
    assert project["requires-python"] == "==3.12.*"
    assert project["scripts"] == {"seam-node": "seam_runtime.selfhost:main"}
    assert "Private :: Do Not Upload" not in project.get("classifiers", [])
    private_project = tomllib.loads(
        (REPO / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]
    assert "Private :: Do Not Upload" in private_project["classifiers"]


def test_node_build_uses_explicit_sources_and_load_bearing_exclusions() -> None:
    assert NODE_FILES == (Path("README.md"), Path("pyproject.toml"))
    assert Path("seam_runtime/public_api.py") in RUNTIME_SOURCE_FILES
    assert Path("seam_runtime/conversation.py") in RUNTIME_SOURCE_FILES
    assert Path("seam_runtime/event_count_context.py") in RUNTIME_SOURCE_FILES
    assert Path("seam_runtime/tokenization.py") in RUNTIME_SOURCE_FILES
    assert Path("seam_runtime/retrieval_orchestrator/__init__.py") in RUNTIME_SOURCE_FILES
    assert len(NOFOLLOW_MODULES) == 18
    assert "seam_runtime.public_api" not in NOFOLLOW_MODULES
    assert "seam_runtime.conversation" not in NOFOLLOW_MODULES
    assert "seam_runtime.event_count_context" not in NOFOLLOW_MODULES
    assert "seam_runtime.tokenization" not in NOFOLLOW_MODULES
    assert "seam_runtime.retrieval_orchestrator" not in NOFOLLOW_MODULES
    assert set(RUNTIME_SOURCE_FILES) == {
        path.relative_to(REPO)
        for path in (REPO / "seam_runtime").rglob("*.py")
    }


def test_node_gate_accepts_clean_compiled_busl_wheel(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path / "clean.whl", _clean_files())
    assert verify_node_wheel(wheel, budget={}) == ()


@pytest.mark.parametrize(
    "source_path",
    (
        "seam_runtime/mirl.py",
        "seam_runtime/mirl.pyc",
        "seam_runtime/mirl.pyo",
        "seam_node-2.4.0.data/purelib/seam_runtime/mirl.py",
        "seam_runtime.py",
    ),
)
def test_node_gate_rejects_runtime_source(
    tmp_path: Path, source_path: str
) -> None:
    files = _clean_files()
    files[source_path] = b"private source"
    wheel = _wheel(tmp_path / f"source-{len(files)}.whl", files)
    errors = verify_node_wheel(wheel, budget={})
    assert any("seam_runtime source" in error for error in errors)


def test_node_gate_requires_busl_text_and_metadata(tmp_path: Path) -> None:
    files = _clean_files()
    del files["seam_node-2.4.0.dist-info/licenses/LICENSES/BUSL-1.1.txt"]
    files["seam_node-2.4.0.dist-info/METADATA"] = b"\n".join(
        (b"Name: seam-node", b"Version: 2.4.0", b"License-Expression: MIT")
    )
    wheel = _wheel(tmp_path / "missing-busl.whl", files)
    errors = verify_node_wheel(wheel, budget={})
    assert any("missing licenses/LICENSES/BUSL-1.1.txt" in error for error in errors)
    assert any("does not declare BUSL-1.1" in error for error in errors)


def test_node_gate_scans_contents_and_exempts_license(tmp_path: Path) -> None:
    files = _clean_files()
    files["seam_runtime.cpython-312-x86_64-linux-gnu.so"] += b"MIRL"
    files[
        "seam_node-2.4.0.dist-info/licenses/LICENSES/BUSL-1.1.txt"
    ] += b" MIRL MIRL"
    wheel = _wheel(tmp_path / "ratchet.whl", files)
    errors = verify_node_wheel(wheel, budget={b"MIRL": 0})
    assert any("MIRL appears 1 times, budget 0" in error for error in errors)
    assert verify_node_wheel(wheel, budget={b"MIRL": 1}) == ()


def test_node_reserved_budget_matches_measured_baseline() -> None:
    assert NODE_RESERVED_CONTENT_BUDGET[b"MIRL"] == 133
    assert NODE_RESERVED_CONTENT_BUDGET[b"knowledge_graph"] == 18
    assert NODE_RESERVED_CONTENT_BUDGET[b"reasoning_graph"] == 12
    assert sum(NODE_RESERVED_CONTENT_BUDGET.values()) == 414


def test_node_build_refuses_nonempty_output_without_deleting_it(
    tmp_path: Path,
) -> None:
    output = tmp_path / "dist"
    output.mkdir()
    sentinel = output / "operator-owned.txt"
    sentinel.write_text("preserve me", encoding="utf-8")
    with pytest.raises(ValueError, match="output directory must be empty"):
        build_node_wheel(output)
    assert sentinel.read_text(encoding="utf-8") == "preserve me"
