"""tools/release/sync_public_mirror.py against real throwaway git repos.

Exercises the actual git plumbing (temp index, write-tree, commit-tree)
rather than mocking it, since the zero-byte-tempfile bug this script hit
during development ("index file smaller than expected") only shows up
against a real git process.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from tools.release import sync_public_mirror as sync_mod
from tools.release.sync_public_mirror import build_public_tree, _ls_tree, _rev_parse


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout.strip()


@pytest.fixture()
def private_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "private"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    return repo


def _write(repo: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        _git(repo, "add", name)


def _commit(repo: Path, files: dict[str, str], message: str) -> str:
    _write(repo, files)
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def test_build_public_tree_filters_to_allow_list(private_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sync_mod,
        "is_public_synced_path",
        lambda path: path in {"README.md", "seam_runtime/mcp.py"},
    )
    monkeypatch.setattr(sync_mod, "is_public_owned_path", lambda path: False)

    _commit(
        private_repo,
        {
            "README.md": "public readme\n",
            "seam_runtime/mcp.py": "print('hi')\n",
            "HISTORY.md": "private internal incident log\n",
            "docs/audits/secret-research.md": "competitive analysis\n",
        },
        "initial",
    )

    new_tree_sha, mirror_tip = build_public_tree(private_repo, "main")
    assert mirror_tip is None  # no seam-runtime remote configured in this throwaway repo

    paths = {path for _mode, _type, _sha, path in _ls_tree(private_repo, new_tree_sha)}
    assert paths == {"README.md", "seam_runtime/mcp.py"}


def test_build_public_tree_preserves_owned_paths_from_existing_mirror(
    private_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A path already present on the mirror (simulated via a second remote
    repo) and marked owned must be carried over unchanged, never replaced by
    whatever that path currently looks like on the private side."""
    mirror_repo = tmp_path / "mirror"
    mirror_repo.mkdir()
    _git(mirror_repo, "init", "-q", "--bare")

    # Seed the "mirror" with its own independent HISTORY.md via a throwaway worktree.
    seed_repo = tmp_path / "seed"
    seed_repo.mkdir()
    _git(seed_repo, "init", "-q")
    _git(seed_repo, "config", "user.email", "test@example.com")
    _git(seed_repo, "config", "user.name", "Test")
    _commit(seed_repo, {"HISTORY.md": "public repo's OWN independent history\n"}, "seed")
    _git(seed_repo, "remote", "add", "seam-runtime", str(mirror_repo))
    _git(seed_repo, "push", "seam-runtime", "main:main")

    _git(private_repo, "remote", "add", "seam-runtime", str(mirror_repo))
    _commit(
        private_repo,
        {
            "README.md": "public readme\n",
            "HISTORY.md": "PRIVATE internal incident log -- must NOT reach the mirror\n",
        },
        "initial",
    )
    _git(private_repo, "fetch", "seam-runtime")

    monkeypatch.setattr(sync_mod, "is_public_synced_path", lambda path: path == "README.md")
    monkeypatch.setattr(sync_mod, "is_public_owned_path", lambda path: path == "HISTORY.md")
    monkeypatch.setattr(sync_mod, "_seed_dir", lambda: tmp_path / "empty_seed_dir")

    new_tree_sha, mirror_tip = build_public_tree(private_repo, "main")
    assert mirror_tip is not None

    entries = {path: sha for _mode, _type, sha, path in _ls_tree(private_repo, new_tree_sha)}
    assert entries.keys() == {"README.md", "HISTORY.md"}

    history_blob = subprocess.run(
        ["git", "-C", str(private_repo), "cat-file", "-p", entries["HISTORY.md"]],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "OWN independent history" in history_blob
    assert "PRIVATE internal incident log" not in history_blob


def test_build_public_tree_seeds_owned_path_on_first_sync(
    private_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the mirror doesn't exist yet (no seam-runtime remote/ref), an
    owned path with a seed template must be created from that template."""
    _commit(private_repo, {"README.md": "public readme\n"}, "initial")

    seed_dir = private_repo.parent / "seed_templates"
    (seed_dir / "HISTORY.md").parent.mkdir(parents=True, exist_ok=True)
    (seed_dir / "HISTORY.md").write_text("fresh public-repo seed\n")

    monkeypatch.setattr(sync_mod, "is_public_synced_path", lambda path: path == "README.md")
    monkeypatch.setattr(sync_mod, "is_public_owned_path", lambda path: path == "HISTORY.md")
    monkeypatch.setattr(sync_mod, "_seed_dir", lambda: seed_dir)

    new_tree_sha, mirror_tip = build_public_tree(private_repo, "main")
    assert mirror_tip is None

    entries = {path: sha for _mode, _type, sha, path in _ls_tree(private_repo, new_tree_sha)}
    assert entries.keys() == {"README.md", "HISTORY.md"}
    history_blob = subprocess.run(
        ["git", "-C", str(private_repo), "cat-file", "-p", entries["HISTORY.md"]],
        capture_output=True, text=True, check=True,
    ).stdout
    assert history_blob == "fresh public-repo seed\n"
