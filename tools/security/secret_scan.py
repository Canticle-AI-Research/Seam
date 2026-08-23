"""Canonical content-free secret and private-session scanner for SEAM.

The same pattern contract serves working-tree continuity checks, CI hygiene,
release gates, and pre-push commit-range scans. Reports contain only path,
line, and finding kind; matched content is never echoed.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ZERO_SHA = "0" * 40
MAX_SCAN_BYTES = 2_000_000
OVERSIZE_ALLOWLIST_SHA256 = {
    # Canonical LoCoMo source pinned by the adjacent manifest and restore gate.
    "benchmarks/external/locomo/data/locomo10.json": (
        "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
    ),
}
BINARY_EXTENSIONS = frozenset(
    {
        ".eot",
        ".gif",
        ".gz",
        ".ico",
        ".jpeg",
        ".jpg",
        ".pdf",
        ".png",
        ".pyd",
        ".pyc",
        ".so",
        ".tar",
        ".ttf",
        ".whl",
        ".woff",
        ".woff2",
        ".zip",
    }
)

SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "provider_session_url",
        re.compile(
            r"https?://[^\s\)\]\}>\"']*(?:claude\.ai|chatgpt\.com|chat\.openai\.com|cursor\.com|/share/|session(?:=|/)|thread(?:=|/))[^\s\)\]\}>\"']*",
            re.IGNORECASE,
        ),
    ),
    (
        "api_key",
        re.compile(
            r"\b(?:sk-proj-|sk-or-v1-|sk-ant-|sk-)[A-Za-z0-9_-]{16,}\b"
            r"|\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{20,}\b"
            r"|github_pat_[A-Za-z0-9_]{20,}"
            r"|\bAIza[0-9A-Za-z_-]{20,}\b"
            r"|\bAKIA[0-9A-Z]{16}\b"
        ),
    ),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    (
        "dsn_password",
        re.compile(
            r"(?i)\b(?:postgres|postgresql|mysql|mongodb|redis)://[^\s:@/]+:[^\s:@/]{4,}@"
        ),
    ),
)


@dataclass(frozen=True)
class SecretFinding:
    path: str
    line: int
    kind: str

    def format(self) -> str:
        return f"{self.path}:{self.line}: {self.kind}"


@dataclass(frozen=True)
class ScanSummary:
    findings: tuple[SecretFinding, ...]
    skipped: tuple[tuple[str, str], ...] = ()


def _scan_bytes_summary(path: str, content: bytes) -> ScanSummary:
    if Path(path).suffix.lower() in BINARY_EXTENSIONS:
        return ScanSummary((), ((path, "binary_extension"),))
    if len(content) > MAX_SCAN_BYTES:
        expected_hash = OVERSIZE_ALLOWLIST_SHA256.get(path)
        if expected_hash and hashlib.sha256(content).hexdigest() == expected_hash:
            return ScanSummary((), ((path, "hash_pinned_oversize"),))
        return ScanSummary((SecretFinding(path=path, line=0, kind="scan_size_limit"),))
    if b"\0" in content[:4096]:
        return ScanSummary(_find_secret_patterns(path, content), ((path, "binary_nul"),))
    return ScanSummary(_find_secret_patterns(path, content))


def _find_secret_patterns(path: str, content: bytes) -> tuple[SecretFinding, ...]:
    texts = [content.decode("utf-8", errors="replace")]
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        texts.append(content.decode("utf-16", errors="replace"))
    if b"\0" in content:
        texts.extend(
            (
                content.decode("utf-16-le", errors="replace"),
                content.decode("utf-16-be", errors="replace"),
            )
        )
    findings: list[SecretFinding] = []
    seen: set[tuple[int, str]] = set()
    for text in dict.fromkeys(texts):
        for line_number, line in enumerate(text.splitlines(), start=1):
            for kind, pattern in SECRET_PATTERNS:
                identity = (line_number, kind)
                if identity not in seen and pattern.search(line):
                    findings.append(SecretFinding(path=path, line=line_number, kind=kind))
                    seen.add(identity)
    return tuple(findings)


def scan_bytes(
    path: str, content: bytes, *, include_binary: bool = False
) -> tuple[SecretFinding, ...]:
    """Scan one bounded payload, optionally ignoring binary policy exclusions."""

    if include_binary:
        if len(content) > MAX_SCAN_BYTES:
            return (SecretFinding(path=path, line=0, kind="scan_size_limit"),)
        return _find_secret_patterns(path, content)
    return _scan_bytes_summary(path, content).findings


def _run(repo_root: Path, *args: str) -> bytes:
    return subprocess.run(
        [*args],
        cwd=repo_root,
        capture_output=True,
        check=True,
    ).stdout


def _repository_paths(repo_root: Path) -> tuple[str, ...]:
    output = _run(
        repo_root,
        "git",
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
    )
    return tuple(
        item.decode("utf-8", errors="surrogateescape")
        for item in output.split(b"\0")
        if item
    )


def scan_worktree_summary(repo_root: Path) -> ScanSummary:
    findings: list[SecretFinding] = []
    skipped: list[tuple[str, str]] = []
    for relative in _repository_paths(repo_root):
        path = repo_root / relative
        if not path.is_file():
            continue
        try:
            content = path.read_bytes()
        except OSError:
            skipped.append((relative, "unreadable"))
            continue
        summary = _scan_bytes_summary(relative, content)
        findings.extend(summary.findings)
        skipped.extend(summary.skipped)
    return ScanSummary(tuple(findings), tuple(skipped))


def scan_worktree(repo_root: Path) -> tuple[SecretFinding, ...]:
    return scan_worktree_summary(repo_root).findings


def _new_blobs(
    old_sha: str,
    new_sha: str,
    repo_root: Path,
    *,
    remote: str | None = None,
) -> tuple[tuple[str, str], ...]:
    if not new_sha or new_sha == ZERO_SHA:
        return ()
    if not old_sha or old_sha == ZERO_SHA:
        rev_args = [new_sha]
        if remote:
            rev_args.extend(["--not", f"--remotes={remote}"])
    else:
        rev_args = [new_sha, "--not", old_sha]
    output = _run(repo_root, "git", "rev-list", "--objects", *rev_args)
    pairs: list[tuple[str, str]] = []
    for raw_line in output.splitlines():
        parts = raw_line.decode("utf-8", errors="replace").split(" ", 1)
        if len(parts) == 2:
            pairs.append((parts[0], parts[1]))
    return tuple(pairs)


def scan_git_range_summary(
    old_sha: str,
    new_sha: str,
    repo_root: Path,
    *,
    remote: str | None = None,
) -> ScanSummary:
    """Scan every new blob in ``old_sha..new_sha``, including deleted-at-tip blobs."""

    findings: list[SecretFinding] = []
    skipped: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for blob_sha, path in _new_blobs(old_sha, new_sha, repo_root, remote=remote):
        identity = (blob_sha, path)
        if identity in seen:
            continue
        seen.add(identity)
        object_type = _run(repo_root, "git", "cat-file", "-t", blob_sha).strip()
        if object_type != b"blob":
            continue
        size_raw = _run(repo_root, "git", "cat-file", "-s", blob_sha).strip()
        try:
            size = int(size_raw)
        except ValueError:
            skipped.append((path, "invalid_size"))
            continue
        if size > MAX_SCAN_BYTES:
            findings.append(SecretFinding(path=path, line=0, kind="scan_size_limit"))
            continue
        summary = _scan_bytes_summary(
            path, _run(repo_root, "git", "cat-file", "-p", blob_sha)
        )
        findings.extend(summary.findings)
        skipped.extend(summary.skipped)
    return ScanSummary(tuple(findings), tuple(skipped))


def scan_git_range(
    old_sha: str,
    new_sha: str,
    repo_root: Path,
    *,
    remote: str | None = None,
) -> tuple[SecretFinding, ...]:
    return scan_git_range_summary(
        old_sha, new_sha, repo_root, remote=remote
    ).findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--working-tree", action="store_true")
    mode.add_argument("--range", nargs=2, metavar=("OLD_SHA", "NEW_SHA"))
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--remote", help="Remote name whose existing refs are excluded for a new ref")
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    summary = (
        scan_worktree_summary(repo_root)
        if args.working_tree
        else scan_git_range_summary(
            args.range[0], args.range[1], repo_root, remote=args.remote
        )
    )
    if summary.findings:
        print(f"Secret/session scan FAILED with {len(summary.findings)} finding(s):", file=sys.stderr)
        for finding in summary.findings:
            print(f"  {finding.format()}", file=sys.stderr)
        return 1
    if summary.skipped:
        print(
            f"Secret/session scan OK; {len(summary.skipped)} policy-excluded path(s):"
        )
        for path, reason in summary.skipped:
            print(f"  {path}: {reason}")
    else:
        print("Secret/session scan OK")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
