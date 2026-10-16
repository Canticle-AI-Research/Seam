from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "tests@example.invalid")
    _git(repo, "config", "user.name", "SEAM tests")
    hooks = repo / "tools" / "git-hooks"
    hooks.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "tools/git-hooks/install.sh", hooks / "install.sh")
    for name in ("pre-commit", "pre-push"):
        (hooks / name).write_text(
            "#!/usr/bin/env bash\n# SEAM_HOOK_PROTOCOL: 1\n"
            "printf 'cwd=%s args=%s input=' \"$PWD\" \"$*\"\ncat\nexit \"${TEST_EXIT:-0}\"\n"
        )
        (hooks / name).chmod(0o644)
    (repo / "README.md").write_text("base\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "base")
    return repo


def _install(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "tools/git-hooks/install.sh", *args], cwd=repo,
        capture_output=True, text=True, timeout=10,
    )


def test_install_from_linked_worktree_survives_its_removal_and_uses_invoking_checkout(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-qb", "install-hooks", str(linked))
    source_mode = (linked / "tools/git-hooks/pre-push").stat().st_mode & 0o777

    installed = _install(linked)

    assert installed.returncode == 0, installed.stderr
    common = Path(_git(repo, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = repo / common
    dispatcher = common / "hooks" / "pre-push"
    assert dispatcher.is_file() and not dispatcher.is_symlink()
    assert (linked / "tools/git-hooks/pre-push").stat().st_mode & 0o777 == source_mode
    _git(repo, "worktree", "remove", "--force", str(linked))

    run = subprocess.run(
        [str(dispatcher), "origin", "git@example.invalid:repo"], cwd=repo,
        input="refs/heads/main old refs/heads/main new\n", capture_output=True, text=True,
    )

    assert run.returncode == 0
    assert f"cwd={repo}" in run.stdout
    assert "args=origin git@example.invalid:repo" in run.stdout
    assert "input=refs/heads/main old refs/heads/main new" in run.stdout


def test_dispatcher_fails_closed_when_source_is_changed_or_protocol_is_missing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert _install(repo).returncode == 0
    hook = Path(_git(repo, "rev-parse", "--git-common-dir")) / "hooks" / "pre-commit"
    (repo / "tools/git-hooks/pre-commit").write_text("#!/bin/sh\nexit 0\n")

    result = subprocess.run([str(hook)], cwd=repo, capture_output=True, text=True)

    assert result.returncode != 0
    assert "stale or unsupported" in result.stderr


def test_install_refuses_custom_hooks_path_and_unknown_hook_without_replace(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "config", "core.hooksPath", ".custom-hooks")
    assert _install(repo).returncode != 0
    _git(repo, "config", "--unset", "core.hooksPath")
    common = Path(_git(repo, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = repo / common
    hooks = common / "hooks"
    hooks.mkdir(exist_ok=True)
    (hooks / "pre-push").write_text("#!/usr/bin/env bash\n# SEAM_HOOK_DISPATCHER: 1\nexit 0\n")

    refused = _install(repo)
    replaced = _install(repo, "--replace")

    assert refused.returncode != 0
    assert "unknown existing hook" in refused.stderr
    assert replaced.returncode == 0
    assert list(hooks.glob("pre-push.bak.*"))


def test_install_refuses_external_symlink_with_canonical_suffix(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    common = Path(_git(repo, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = repo / common
    hooks = common / "hooks"
    hooks.mkdir(exist_ok=True)
    external = tmp_path / "external" / "tools" / "git-hooks"
    external.mkdir(parents=True)
    (external / "pre-push").write_text("#!/bin/sh\nexit 0\n")
    (hooks / "pre-push").symlink_to(external / "pre-push")

    result = _install(repo)

    assert result.returncode != 0
    assert "unknown existing hook" in result.stderr
    assert (hooks / "pre-push").is_symlink()
    assert not list(hooks.glob("pre-push.bak.*"))


def test_dispatcher_preserves_source_exit_status(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert _install(repo).returncode == 0
    hook = Path(_git(repo, "rev-parse", "--git-common-dir")) / "hooks" / "pre-commit"
    env = os.environ.copy()
    env["TEST_EXIT"] = "23"

    result = subprocess.run([str(hook)], cwd=repo, env=env)

    assert result.returncode == 23


def test_pre_push_refuses_lifecycle_repo_override_that_mismatches_remote(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _git(repo, "remote", "add", "origin", "git@github.com:Canticle-AI-Research/Seam.git")
    fake_python = tmp_path / "python"
    calls = tmp_path / "calls.log"
    fake_python.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$HOOK_CALLS\"\nexit 0\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "HOOK_CALLS": str(calls),
            "SEAM_ALLOW_UNSIGNED_PUSH": "1",
            "SEAM_GITHUB_REPOSITORY": "example/empty",
            "SEAM_HOOK_PYTHON": str(fake_python),
        }
    )
    head = _git(repo, "rev-parse", "HEAD")

    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "tools/git-hooks/pre-push"),
            "origin",
            "git@github.com:Canticle-AI-Research/Seam.git",
        ],
        cwd=repo,
        env=env,
        input=f"refs/heads/main {head} refs/heads/main {'0' * 40}\n",
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 1
    assert "does not match target remote" in result.stderr
    assert "tools.ci.pr_lifecycle" not in calls.read_text(encoding="utf-8")
