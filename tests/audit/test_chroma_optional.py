"""chromadb must stay an OPT-IN-ONLY extra - never a forced dependency.

chromadb 1.0.0-1.5.9 carries an UNPATCHED critical advisory (GHSA-f4j7-r4q5-qw2c,
pre-auth code injection in the Chroma server). SEAM uses only the embedded
PersistentClient (lazy-imported in ``ChromaSemanticAdapter._client``) and
defaults to the SQLite vector adapter, so chromadb must NOT be pulled by any
default/convenience path: not in core ``dependencies``, not in ``requirements.txt``
(used by the installers/bootstrap), and not in ``all-extras``. It lives ONLY in
the explicit ``chroma`` extra (`seam[chroma]`). These tests guard that.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

from seam_runtime import doctor

_REPO = Path(__file__).resolve().parents[2]
_PYPROJECT = _REPO / "pyproject.toml"
_REQUIREMENTS = _REPO / "requirements.txt"


def _document() -> dict:
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))


def _project() -> dict:
    return _document()["project"]


def _dependency_name(requirement: str) -> str:
    match = re.match(r"\s*([A-Za-z0-9_.-]+)", requirement)
    assert match is not None
    return match.group(1).lower().replace("-", "_")


def _canonical_doctor_dependencies() -> list[str]:
    document = _document()
    runtime_source = document["tool"]["seam"]["dependency-contract"]["runtime-source"]
    value: object = document
    for key in runtime_source.split("."):
        assert isinstance(value, dict)
        value = value[key]
    assert isinstance(value, list)
    return [_dependency_name(str(requirement)) for requirement in value]


def test_chromadb_not_in_core_dependencies():
    assert not any("chromadb" in dep for dep in _project()["dependencies"])


def test_chromadb_not_in_requirements_txt():
    # requirements.txt is what the installers/bootstrap pip-install; it must not
    # force a vulnerable chromadb (GHSA-f4j7-r4q5-qw2c).
    assert "chromadb" not in _REQUIREMENTS.read_text(encoding="utf-8")


def test_chromadb_only_in_the_explicit_chroma_extra():
    extras = _project()["optional-dependencies"]
    assert any("chromadb" in dep for dep in extras["chroma"])
    # NOT pulled by the convenience "everything" extra (unpatched critical advisory)
    assert not any("chromadb" in dep for dep in extras["all-extras"])


def test_doctor_follows_core_dependency_contract_when_chromadb_is_absent(monkeypatch):
    canonical_required = _canonical_doctor_dependencies()
    assert canonical_required == ["rich", "tiktoken"]

    class _Runtime:
        def __init__(self, _db_path: str):
            pass

        def compile_nl(self, _text: str) -> SimpleNamespace:
            return SimpleNamespace(records=[object()])

    lossless_result = SimpleNamespace(
        roundtrip_match=True,
        artifact=SimpleNamespace(token_estimator="test", token_savings_ratio=0.5),
    )
    monkeypatch.setattr(doctor, "SeamRuntime", _Runtime)
    monkeypatch.setattr(doctor, "benchmark_text_lossless", lambda *_args, **_kwargs: lossless_result)
    monkeypatch.setattr(doctor, "find_spec", lambda name: None if name == "chromadb" else object())
    monkeypatch.setattr(doctor, "check_pgvector", lambda _dsn: {"configured": False})
    monkeypatch.setattr(doctor, "check_commit_gate", lambda: {"status": "PASS"})
    monkeypatch.setattr(doctor, "check_streams", lambda: {"status": "PASS"})
    monkeypatch.setattr(doctor, "check_stashes", lambda: {"status": "clean", "count": 0})

    report = doctor.build_doctor_report()

    assert report["required_dependencies"] == canonical_required
    assert report["dependencies"]["chromadb"] is False
    assert "chromadb" not in report["required_dependencies"]
    assert report["missing_required_dependencies"] == []
    assert report["status"] == "PASS"


def test_real_doctor_runtime_passes_with_chromadb_import_blocked():
    script = r'''
import importlib.abc
import sys

class BlockChroma(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "chromadb" or fullname.startswith("chromadb."):
            raise ModuleNotFoundError("chromadb blocked by core-install smoke")
        return None

sys.meta_path.insert(0, BlockChroma())

from seam_runtime.doctor import build_doctor_report

report = build_doctor_report()
assert report["status"] == "PASS", report
assert report["dependencies"]["chromadb"] is False, report
assert report["required_dependencies"] == ["rich", "tiktoken"], report
assert report["missing_required_dependencies"] == [], report
'''
    env = os.environ.copy()
    env["PYTHONPATH"] = str(_REPO)
    env.pop("SEAM_PGVECTOR_DSN", None)
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_REPO,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
