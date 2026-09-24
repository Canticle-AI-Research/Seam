"""The workspace gate must catch clutter that `git status` cannot see.

Reproduced before this gate existed: with 16 stray files, a 4.4MB binary and a
dirty worktree in the tree, all eleven repo-hygiene checks passed and
`git status` printed nothing. Gitignored paths are invisible, so they
accumulate indefinitely. Ten prior incidents (HISTORY#406, #534, #555,
#567-569, #604) were each answered by adding a `.gitignore` line, which hides
the next occurrence instead of preventing it -- the accumulated one-off entries
in `.gitignore` are the record of that.

HISTORY#534 diagnosed the recurrence: the rule was ACTION_REQUIRED prose that
"nobody was gated on". These tests build real scattered trees on disk and
assert the gate fails on each shape, so the gate cannot quietly become
advisory again.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools.git import verify_workspace

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A throwaway git repo carrying the real contract and a matching ignore file."""

    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "pyproject.toml").write_text(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / ".gitignore").write_text(
        "*.db\n*.png\nvisuals/\n.playwright-mcp/\ndiag_out/\n"
        "*.egg-info/\n.seam-store-*.lock\n"
        # Mirrors the real .gitignore. Without these the credential files below
        # are not ignored, so they never reach the prune path and the
        # "--fix must not delete a key" guarantee goes untested.
        "id_rsa\nid_ed25519\nid_ecdsa\ncredentials.json\nservice_account.json\n"
        "*.pem\n*.key\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"],
        cwd=tmp_path,
        check=True,
    )
    return tmp_path


def _silence(workspace: Path, entry: str) -> None:
    """Add a .gitignore line, as every past incident's "fix" did.

    The fixture's .gitignore is contract-coherent on purpose, so a test that
    needs an undeclared ignored path must create that condition explicitly.
    """

    gitignore = workspace / ".gitignore"
    gitignore.write_text(
        gitignore.read_text(encoding="utf-8") + f"{entry}\n", encoding="utf-8"
    )
    # Commit it, as a real incident would: the point is that the line lands in
    # the repo and the clutter it hides then never shows up in git status.
    subprocess.run(["git", "add", ".gitignore"], cwd=workspace, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "ignore"],
        cwd=workspace,
        check=True,
    )


def _run(workspace: Path) -> list[verify_workspace.Finding]:
    contract = verify_workspace.load_contract(workspace)
    return verify_workspace.run_checks(contract, workspace)


def test_a_clean_workspace_passes(workspace: Path) -> None:
    """Guard against the failure assertions below passing for the wrong reason."""

    assert _run(workspace) == []


def test_the_scatter_is_invisible_to_git_status(workspace: Path) -> None:
    """Pin the premise: this clutter is exactly what no other gate can see.

    If these paths ever became visible to `git status`, the existing gates
    would cover them and this module's rationale would need revisiting.
    """

    _silence(workspace, "rogue_dump/")
    (workspace / "rogue_dump").mkdir()
    (workspace / "rogue_dump" / "a.txt").write_text("x", encoding="utf-8")
    (workspace / "scratch_scratch.db").write_text("x", encoding="utf-8")

    porcelain = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert porcelain.strip() == "", f"expected invisible clutter, git reported: {porcelain!r}"
    assert _run(workspace), "gate must see what git status cannot"


def test_undeclared_ignored_directory_fails(workspace: Path) -> None:
    _silence(workspace, "rogue_dump/")
    (workspace / "rogue_dump").mkdir()
    (workspace / "rogue_dump" / "junk.txt").write_text("junk", encoding="utf-8")

    findings = _run(workspace)
    assert any(f.path.startswith("rogue_dump") for f in findings)
    assert any("not declared" in f.problem for f in findings)


def test_declared_directory_passes(workspace: Path) -> None:
    """Declaring a path is the sanctioned escape hatch, and it must work."""

    (workspace / "diag_out").mkdir()
    (workspace / "diag_out" / "report.txt").write_text("small", encoding="utf-8")
    assert _run(workspace) == []


def test_oversized_file_in_a_sink_fails(workspace: Path) -> None:
    """The original incident's shape: a 4.5MB binary parked in visuals/.

    A total-directory budget alone does not catch this, which is why the
    per-file cap exists.
    """

    sink = workspace / "visuals"
    sink.mkdir()
    (sink / "report-generator-binary").write_bytes(b"\0" * (3 * 1024 * 1024))

    findings = _run(workspace)
    assert any("per-file cap" in f.problem for f in findings), findings


def test_small_files_in_a_sink_pass(workspace: Path) -> None:
    sink = workspace / ".playwright-mcp"
    sink.mkdir()
    for i in range(8):
        (sink / f"shot-{i}.png").write_text("screenshot", encoding="utf-8")
    assert _run(workspace) == []


def test_root_scratch_file_fails(workspace: Path) -> None:
    (workspace / "seam_scratch.db").write_text("x", encoding="utf-8")
    findings = _run(workspace)
    # Assert the root-scratch check specifically. This path is also an
    # undeclared ignored entry, so matching on the path alone would pass even
    # with the root-scratch check removed entirely.
    assert any(
        f.path == "seam_scratch.db" and "scratch file at the repository root" in f.problem
        for f in findings
    ), findings


@pytest.mark.parametrize(
    "name", ["seam.db", "seam_suite.egg-info", ".seam-store-abc123.lock"]
)
def test_legitimate_generated_names_are_not_flagged(workspace: Path, name: str) -> None:
    """False positives are how a gate earns a reputation for crying wolf.

    These carry generated names and are matched by contract globs, not exact
    entries; each was a real false positive caught by running the gate.
    """

    target = workspace / name
    if name.endswith(".egg-info"):
        target.mkdir()
        (target / "PKG-INFO").write_text("meta", encoding="utf-8")
    else:
        target.write_text("x", encoding="utf-8")
    assert _run(workspace) == [], f"{name} should be permitted by a contract glob"


def test_each_path_is_reported_once(workspace: Path) -> None:
    """A root scratch file is also an undeclared ignored entry.

    Printing one path twice with two different remedies trains people to skim
    the gate's output, which is how a gate stops being read.
    """

    (workspace / "seam_scratch.db").write_text("x", encoding="utf-8")
    paths = [f.path.rstrip("/") for f in _run(workspace)]
    assert len(paths) == len(set(paths)), paths


def test_dirty_worktree_fails(workspace: Path, tmp_path: Path) -> None:
    linked = tmp_path / "linked-wt"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(linked), "-b", "tmp/experiment"],
        cwd=workspace,
        check=True,
    )
    (linked / "UNCOMMITTED.md").write_text("in progress", encoding="utf-8")

    findings = _run(workspace)
    assert any("uncommitted changes" in f.problem for f in findings), findings


def test_fix_removes_artifacts_but_never_a_worktree(workspace: Path, tmp_path: Path) -> None:
    """--fix must never be able to destroy unpushed work.

    Artifacts are regenerable; a worktree may hold the only copy of something.
    """

    _silence(workspace, "rogue_dump/")
    (workspace / "rogue_dump").mkdir()
    (workspace / "rogue_dump" / "junk.txt").write_text("junk", encoding="utf-8")
    linked = tmp_path / "linked-wt"
    subprocess.run(
        ["git", "worktree", "add", "-q", str(linked), "-b", "tmp/experiment"],
        cwd=workspace,
        check=True,
    )
    precious = linked / "UNPUSHED.md"
    precious.write_text("the only copy", encoding="utf-8")

    verify_workspace.main(["--fix", "--repo-root", str(workspace)])

    assert not (workspace / "rogue_dump").exists(), "artifact should be pruned"
    assert precious.read_text(encoding="utf-8") == "the only copy", "worktree must survive --fix"


def test_exit_code_is_nonzero_so_the_hook_actually_blocks(workspace: Path) -> None:
    """An advisory gate is the failure mode this replaces; the exit code is the gate."""

    _silence(workspace, "rogue_dump/")
    (workspace / "rogue_dump").mkdir()
    (workspace / "rogue_dump" / "junk.txt").write_text("junk", encoding="utf-8")
    assert verify_workspace.main(["--repo-root", str(workspace)]) == 1


def test_every_gitignore_root_is_accounted_for_in_the_contract() -> None:
    """The real .gitignore must be fully dispositioned."""

    contract = verify_workspace.load_contract(REPO_ROOT)
    findings = verify_workspace.check_gitignore_coverage(contract, REPO_ROOT)
    assert findings == [], [f.path for f in findings]


def test_silencing_a_path_without_declaring_it_fails(workspace: Path) -> None:
    """The ten-incident regression, asserted directly.

    Adding a .gitignore line is how every past incident was "fixed". Doing that
    without saying what the path is must now fail.
    """

    _silence(workspace, "newly_silenced_dump/")
    contract = verify_workspace.load_contract(workspace)
    findings = verify_workspace.check_gitignore_coverage(contract, workspace)

    assert any("newly_silenced_dump" in f.path for f in findings), findings
    assert any("no disposition" in f.problem for f in findings)


def test_gate_runs_from_the_repository_root_without_error() -> None:
    """The real tree must pass, or the gate blocks every commit on day one."""

    result = subprocess.run(
        [sys.executable, "-m", "tools.git.verify_workspace"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("name", ["id_rsa", "credentials.json", "server.pem"])
def test_credential_material_is_reported_as_a_security_problem(
    workspace: Path, name: str
) -> None:
    """"Declare it in the contract" is catastrophic advice for a private key.

    These paths are gitignored, so nothing else in the suite mentions them.
    The remedy must say delete and rotate, never declare.
    """

    # Contents are irrelevant: the gate checks that the file exists at all.
    # A real PEM header here would trip the repo's own secret scanner.
    (workspace / name).write_text("placeholder", encoding="utf-8")
    findings = [f for f in _run(workspace) if f.path == name]

    assert findings, f"{name} was not reported at all"
    assert any("credential material" in f.problem for f in findings)
    remedy = findings[0].remedy
    assert "rotate" in remedy and "Do NOT add it" in remedy, remedy


def test_fix_never_deletes_credential_material(workspace: Path) -> None:
    """Silently deleting a key hides that it still needs rotating."""

    key = workspace / "id_rsa"
    key.write_text("placeholder", encoding="utf-8")

    exit_code = verify_workspace.main(["--fix", "--repo-root", str(workspace)])

    assert key.exists(), "--fix must leave credential material for a human to rotate"
    assert exit_code == 1, "the gate must still fail while the key is present"
