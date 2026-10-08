"""Exercise documented POSIX Bash env initialization without starting services."""

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="Windows does not provide POSIX file-mode semantics for these Bash fixtures.",
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNBOOKS = ("installers/README.md", "docs/errors.md")


def _initialize(path: str, fixture_root: Path) -> subprocess.CompletedProcess[str]:
    text = (REPO_ROOT / path).read_text(encoding="utf-8")
    blocks = re.findall(r"```bash\n(.*?)\n```", text, flags=re.DOTALL)
    matching = [block for block in blocks if ".env.example" in block]
    assert len(matching) == 1, f"{path}: expected exactly one Bash env initialization block"
    block = matching[0]
    sentinel = "# End private env initialization"
    assert block.count(sentinel) == 1, f"{path}: expected exactly one initialization sentinel"
    initialization = block.split(sentinel, 1)[0]
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


@pytest.mark.parametrize("path", RUNBOOKS)
@pytest.mark.parametrize("defect", ("missing_block", "multiple_blocks", "missing_sentinel", "duplicate_sentinel"))
def test_env_initialization_rejects_unsafe_extraction_before_execution(
    path: str, defect: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runbook = (REPO_ROOT / path).read_text(encoding="utf-8")
    blocks = re.findall(r"```bash\n(.*?)\n```", runbook, flags=re.DOTALL)
    block = next(block for block in blocks if ".env.example" in block)
    if defect == "missing_block":
        runbook = runbook.replace(".env.example", "REMOVED_TEMPLATE_MARKER")
    elif defect == "multiple_blocks":
        runbook += "\n```bash\n" + block + "\n```\n"
    elif defect == "missing_sentinel":
        runbook = runbook.replace("# End private env initialization", "REMOVED_SENTINEL")
    else:
        runbook = runbook.replace(block, block.replace("# End private env initialization", "# End private env initialization\n# End private env initialization", 1), 1)
    source = tmp_path / "runbooks"
    target = source / path
    target.parent.mkdir(parents=True)
    target.write_text(runbook, encoding="utf-8")
    monkeypatch.setitem(_initialize.__globals__, "REPO_ROOT", source)
    def forbidden_execution(*args, **kwargs):
        pytest.fail("Malformed documentation must be rejected before shell execution")
    monkeypatch.setattr(subprocess, "run", forbidden_execution)
    expected = "exactly one Bash env initialization block" if defect.endswith("blocks") or defect == "missing_block" else "exactly one initialization sentinel"
    with pytest.raises(AssertionError, match=expected):
        _initialize(path, tmp_path / "fixture")
