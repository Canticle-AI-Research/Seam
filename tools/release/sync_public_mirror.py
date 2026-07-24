"""Disabled legacy public-mirror tooling.

The ``BlackhatShiftey/Seam_Runtime`` repository is a frozen legacy Apache-2.0
release. The private SEAM repository and MIRL or HS/1 Reserved Materials must
not be synchronized to it. This module retains a recognizable command path so old
automation fails with an explicit policy error instead of silently publishing.

A future public client or SDK must use a separate repository, artifact,
manifest, dependency boundary, and license after legal review.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from tools.release.public_manifest import is_public_owned_path, is_public_synced_path

PUBLIC_REMOTE = "seam-runtime"
SEED_DIR_NAME = "public_seed"


class PublicMirrorFrozenError(RuntimeError):
    """Raised whenever legacy mirror construction is attempted."""


FROZEN_MESSAGE = (
    "The legacy Seam_Runtime public mirror is frozen. "
    "MIRL, HS/1, and the private runtime may not be synchronized from this repository."
)


def _git(repo_root: Path, args: list[str], *, env: dict[str, str] | None = None, input_text: str | None = None) -> str:
    # Bytes in/out, not text=True: `update-index --index-info`'s payload is a
    # strict \n-delimited format, and subprocess's text-mode stdin write
    # translates '\n' to os.linesep -- '\r\n' on Windows -- which corrupts it.
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        env=env,
        input=input_text.encode("utf-8") if input_text is not None else None,
        check=True,
    )
    return result.stdout.decode("utf-8").strip()


def _rev_parse(repo_root: Path, ref: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "--verify", "--quiet", ref],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() or None


def _ls_tree(repo_root: Path, commit_sha: str) -> list[tuple[str, str, str, str]]:
    """Return (mode, type, blob_sha, path) for every blob in commit_sha's tree."""
    out = _git(repo_root, ["ls-tree", "-r", "-z", "--full-tree", commit_sha])
    entries: list[tuple[str, str, str, str]] = []
    for line in out.split("\0"):
        if not line:
            continue
        meta, path = line.split("\t", 1)
        mode, obj_type, sha = meta.split(" ")
        if obj_type == "blob":
            entries.append((mode, obj_type, sha, path))
    return entries


def _seed_dir() -> Path:
    return Path(__file__).resolve().parent / SEED_DIR_NAME


def build_public_tree(repo_root: Path, private_ref: str = "main") -> tuple[str, str | None]:
    """Refuse construction of a new legacy-public tree."""
    del repo_root, private_ref
    raise PublicMirrorFrozenError(FROZEN_MESSAGE)


def _build_public_tree_retired(repo_root: Path, private_ref: str = "main") -> tuple[str, str | None]:
    """Retired implementation retained only for code-history readability."""
    private_sha = _rev_parse(repo_root, private_ref)
    if not private_sha:
        raise SystemExit(f"Cannot resolve private ref {private_ref!r}")

    mirror_tip = _rev_parse(repo_root, f"{PUBLIC_REMOTE}/main")
    mirror_paths: dict[str, tuple[str, str]] = {}  # path -> (mode, blob_sha)
    if mirror_tip:
        for mode, _type, sha, path in _ls_tree(repo_root, mirror_tip):
            mirror_paths[path] = (mode, sha)

    index_lines: list[str] = []

    for mode, _type, sha, path in _ls_tree(repo_root, private_sha):
        if is_public_synced_path(path):
            index_lines.append(f"{mode} {sha}\t{path}")

    seed_dir = _seed_dir()
    for path in sorted(
        {p for p in (list(mirror_paths) + _owned_seed_paths(seed_dir)) if is_public_owned_path(p)}
    ):
        if path in mirror_paths:
            mode, sha = mirror_paths[path]
        else:
            seed_file = seed_dir / path
            if not seed_file.is_file():
                continue
            sha = _git(repo_root, ["hash-object", "-w", str(seed_file)])
            mode = "100644"
        index_lines.append(f"{mode} {sha}\t{path}")

    with tempfile.NamedTemporaryFile(prefix="seam-public-sync-", delete=False) as tmp_index:
        tmp_index_path = tmp_index.name
    # git's index parser rejects a pre-existing zero-byte file ("index file
    # smaller than expected"); it must not exist so `update-index` starts fresh.
    Path(tmp_index_path).unlink()
    try:
        import os

        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = tmp_index_path
        _git(
            repo_root,
            ["update-index", "--index-info"],
            env=env,
            input_text="\n".join(index_lines) + "\n",
        )
        new_tree_sha = _git(repo_root, ["write-tree"], env=env)
    finally:
        Path(tmp_index_path).unlink(missing_ok=True)

    return new_tree_sha, mirror_tip


def _owned_seed_paths(seed_dir: Path) -> list[str]:
    if not seed_dir.is_dir():
        return []
    return [str(p.relative_to(seed_dir)) for p in seed_dir.rglob("*") if p.is_file()]


def build_public_commit(repo_root: Path, private_ref: str, message: str) -> tuple[str, str | None]:
    new_tree_sha, mirror_tip = build_public_tree(repo_root, private_ref)
    commit_args = ["commit-tree", new_tree_sha, "-m", message]
    if mirror_tip:
        commit_args += ["-p", mirror_tip]
    new_commit_sha = _git(repo_root, commit_args)
    return new_commit_sha, mirror_tip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="Private Seam repo root (default: cwd)")
    parser.add_argument("--ref", default="main", help="Private ref to sync from (default: main)")
    parser.add_argument("--message", default=None, help="Commit message for the sync commit")
    parser.add_argument("--push", action="store_true", help="Actually push the new commit to the mirror's main branch. Default: dry-run only.")
    parser.add_argument("--no-fetch", action="store_true", help="Skip fetching the seam-runtime remote first")
    args = parser.parse_args(argv)

    del args
    print(FROZEN_MESSAGE, file=sys.stderr)
    print(
        "Create a separately reviewed public client/SDK artifact instead of "
        "reactivating this mirror.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
