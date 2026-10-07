"""Exercise documented env initialization in disposable files, without services."""

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNBOOKS = ("installers/README.md", "docs/errors.md")


def _initialize(path: str, fixture_root: Path) -> subprocess.CompletedProcess[str]:
    text = (REPO_ROOT / path).read_text(encoding="utf-8")
    blocks = re.findall(r"```bash\n(.*?)\n```", text, flags=re.DOTALL)
    block = next(block for block in blocks if ".env.example" in block and "docker compose" in block)
    initialization = block.split("docker compose", 1)[0]
    # Replace only the home-path binding; preserve the documented shell logic.
    # HOME itself is never changed, and no service/runtime command is executed.
    initialization = initialization.replace("$HOME", "$SEAM_RUNBOOK_TEST_ROOT")
    assert "$HOME" not in initialization
    env = dict(os.environ, SEAM_RUNBOOK_TEST_ROOT=str(fixture_root))
    return subprocess.run(
        ["bash", "-c", initialization], cwd=fixture_root, env=env,
        capture_output=True, text=True, check=False,
    )


@pytest.mark.parametrize("path", RUNBOOKS)
def test_env_initialization_creates_private_template_copy(path: str, tmp_path: Path) -> None:
    template = b"EXAMPLE_SETTING=placeholder\n"
    (tmp_path / ".env.example").write_bytes(template)
    result = _initialize(path, tmp_path)
    target = tmp_path / ".config/seam/.env"
    assert result.returncode == 0, result.stderr
    assert target.read_bytes() == template
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


@pytest.mark.parametrize("path", RUNBOOKS)
def test_env_initialization_preserves_existing_operator_values(path: str, tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("EXAMPLE_SETTING=placeholder\n")
    target = tmp_path / ".config/seam/.env"
    target.parent.mkdir(parents=True)
    existing = b"EXAMPLE_SETTING=operator-chosen\nEXTRA_SETTING=retained\n"
    target.write_bytes(existing)
    target.chmod(0o640)
    result = _initialize(path, tmp_path)
    assert result.returncode == 0, result.stderr
    assert target.read_bytes() == existing
    assert stat.S_IMODE(target.stat().st_mode) == 0o640


@pytest.mark.parametrize("path", RUNBOOKS)
def test_env_initialization_stops_when_template_is_missing(path: str, tmp_path: Path) -> None:
    result = _initialize(path, tmp_path)
    assert result.returncode != 0
    assert not (tmp_path / ".config/seam/.env").exists()


@pytest.mark.parametrize("path", RUNBOOKS)
def test_env_initialization_rejects_a_directory_destination(path: str, tmp_path: Path) -> None:
    (tmp_path / ".env.example").write_text("EXAMPLE_SETTING=placeholder\n")
    target = tmp_path / ".config/seam/.env"
    target.mkdir(parents=True)
    result = _initialize(path, tmp_path)
    assert result.returncode != 0
    assert target.is_dir()
    assert list(target.iterdir()) == []
