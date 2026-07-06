"""Build and push a curated public-core snapshot to the `seam-runtime` mirror.

Replaces the old `git push seam-runtime main:main` (a full-history, full-tree
mirror gated only by `verify_public_safe.py`'s deny-list secret scanner).
HISTORY#355 found that denylist-only gate had let internal bookkeeping
(`HISTORY.md`, `.seam/`, `docs/audits/`, etc.) sync to the public repo since
day one, because a deny-list fails *open* -- anything not secret-shaped ships.

This script is fail-*closed*: only paths matching `public_manifest.py`'s
allow-list are ever copied to the mirror. It builds ONE new commit on top of
the mirror's current tip (fast-forward; past mirror commits are left exactly
as they are -- a retroactive history purge was explicitly considered and
deferred, see HISTORY#355) whose tree is:

  1. every `is_public_synced_path` path, copied verbatim from private main's
     current committed tree, plus
  2. every `is_public_owned_path` path (the public repo's own independent
     `HISTORY.md`/`PROJECT_STATUS.md`/`REPO_LEDGER.md`/`HISTORY_INDEX.md`/
     `.seam/`), carried over unchanged from whatever the mirror already has --
     or, the first time the mirror has none of them yet, seeded once from
     `tools/release/public_seed/`.

No working tree or local index is touched; everything happens via git
plumbing (a throwaway `GIT_INDEX_FILE`) against the existing object
databases. Nothing is pushed unless `--push` is passed; the default is to
print the new commit and a diffstat against the mirror's current tip for
review.
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


def _git(repo_root: Path, args: list[str], *, env: dict[str, str] | None = None, input_text: str | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        env=env,
        input=input_text,
        check=True,
    )
    return result.stdout.strip()


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
    """Build the curated public tree object. Returns (new_tree_sha, mirror_tip_sha_or_None)."""
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

    repo_root = Path(args.repo_root).resolve()
    if not args.no_fetch:
        _git(repo_root, ["fetch", PUBLIC_REMOTE])

    private_sha = _rev_parse(repo_root, args.ref)
    message = args.message or f"Sync public core from private {args.ref}@{private_sha[:12] if private_sha else '?'}"

    new_commit_sha, mirror_tip = build_public_commit(repo_root, args.ref, message)

    print(f"Private ref:  {args.ref} @ {private_sha}")
    print(f"Mirror tip:   {mirror_tip or '(no existing main -- first sync)'}")
    print(f"New commit:   {new_commit_sha}")
    if mirror_tip:
        diffstat = _git(repo_root, ["diff", "--stat", mirror_tip, new_commit_sha])
        print("--- diffstat vs current mirror tip ---")
        print(diffstat if diffstat else "(no changes)")

    if args.push:
        _git(repo_root, ["push", PUBLIC_REMOTE, f"{new_commit_sha}:main"])
        print(f"Pushed {new_commit_sha} to {PUBLIC_REMOTE}/main")
    else:
        print("Dry run only (pass --push to actually push).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
