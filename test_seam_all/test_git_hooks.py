from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_pre_commit_refuses_when_python_missing(tmp_path: Path) -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required for the pre-commit hook smoke test")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for command in ("git", "grep"):
        source = shutil.which(command)
        assert source is not None, f"{command} is required for this test"
        (bin_dir / command).symlink_to(source)

    env = os.environ.copy()
    env["PATH"] = str(bin_dir)

    result = subprocess.run(
        [bash, "tools/git-hooks/pre-commit"],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 1
    assert "python not found" in result.stderr.lower()
