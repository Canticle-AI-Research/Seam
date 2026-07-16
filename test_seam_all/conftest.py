from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Per-test isolated SQLite path under tmp_path; auto-cleaned."""
    return tmp_path / "seam_test.db"


@pytest.fixture
def seam_runtime(tmp_db_path: Path):
    """SeamRuntime bound to a tmp DB. Yields the runtime; closes on teardown."""
    from seam import SeamRuntime
    rt = SeamRuntime(db_path=str(tmp_db_path))
    try:
        yield rt
    finally:
        rt.close()


@pytest.fixture
def isolated_env(monkeypatch, tmp_path):
    """Strips SEAM_* env vars so tests don't inherit operator state."""
    for key in list(os.environ):
        if key.startswith("SEAM_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("SEAM_BENCH_OUT_DIR", str(tmp_path / "bench"))
    return tmp_path
