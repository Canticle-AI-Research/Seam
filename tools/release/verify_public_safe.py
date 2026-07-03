"""Deny-list gate for pushes that carry private-repo content to a public remote.

`Seam` (private) mirrors curated state to the `Seam_Runtime` public repo via a
`seam-runtime` git remote (see REPO_LEDGER.md). Today nothing filters what
goes public except a human noticing something in the diff before pushing --
the same failure mode that let a `seam.db` snapshot leak into the Cantlicle
repo's history. This module is the deterministic replacement: it inspects
every object newly reachable by a push (not just the tip tree, so content
introduced and later removed within the same push is still caught) and
blocks on path or content patterns that must never leave the private repo.

Two severities:
  - BLOCK: high-confidence secret/credential shapes and disallowed paths.
    Any BLOCK finding fails the gate (exit 1).
  - WARN: lower-confidence generic patterns (e.g. `password =`). Printed but
    does not fail the gate, to keep false-positive noise from making the
    gate something people route around.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ZERO_SHA = "0" * 40

# Paths that must never reach the public remote, regardless of content.
DENY_PATH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(^|/)\.env(\.(?!example$)[^/]+)?$"),
    re.compile(r"\.(db|sqlite|sqlite3)$"),
    re.compile(r"(^|/)(\.claude|\.opencode|\.agents)/"),
    re.compile(r"(^|/)id_(rsa|dsa|ecdsa|ed25519)(\.pub)?$"),
    re.compile(r"\.(pem|key|p12|pfx)$"),
    re.compile(r"(^|/)secrets/"),
    re.compile(r"(^|/)credentials(\.[^/]+)?$"),
)

# High-confidence secret shapes. Any hit blocks the push.
BLOCK_CONTENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    re.compile(r"sk-ant-[A-Za-z0-9\-]{20,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"-----BEGIN (RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----"),
    # 4+ char password requirement mirrors tools/history/verify_continuity.py's
    # dsn_password pattern so placeholder DSNs (e.g. "postgres://user:pw@host")
    # used as UI/doc examples don't trip this at push time when they already
    # pass the repo's own commit-time secret scanner.
    re.compile(r"postgres(?:ql)?://[^:/\s]+:[^@/\s]{4,}@"),
    re.compile(r"claude\.ai/(chat|share)/[a-zA-Z0-9-]+"),
    re.compile(r"console\.anthropic\.com/[^\s\"')]*session[^\s\"')]*"),
)

# Lower-confidence generic patterns. Reported but non-blocking.
WARN_CONTENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"password\s*=\s*['\"][^'\"]{4,}['\"]", re.IGNORECASE),
    re.compile(r"\btoken\s*=\s*['\"][^'\"]{8,}['\"]", re.IGNORECASE),
)

# Skip content scanning for these; path rules alone still apply. Content
# scanning binary formats produces noise, not signal.
BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".woff", ".woff2",
    ".ttf", ".eot", ".pdf", ".zip", ".gz", ".tar", ".whl", ".pyc",
}

MAX_CONTENT_SCAN_BYTES = 2_000_000


@dataclass(frozen=True)
class Finding:
    severity: str  # "BLOCK" or "WARN"
    path: str
    reason: str


@dataclass(frozen=True)
class ScanResult:
    findings: tuple[Finding, ...]

    @property
    def blocking(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == "BLOCK")

    @property
    def ok(self) -> bool:
        return not self.blocking


def _run(args: list[str], repo_root: Path) -> str:
    result = subprocess.run(
        args, cwd=repo_root, capture_output=True, text=False, check=True
    )
    return result.stdout.decode("utf-8", errors="replace")


def _new_blobs(old_sha: str, new_sha: str, repo_root: Path) -> list[tuple[str, str]]:
    """Return (blob_sha, path) pairs for every blob newly reachable by the push."""
    if old_sha == ZERO_SHA or not old_sha:
        rev_args = [new_sha]
    else:
        rev_args = [new_sha, f"--not", old_sha]
    out = _run(
        ["git", "rev-list", "--objects", *rev_args],
        repo_root,
    )
    pairs: list[tuple[str, str]] = []
    for line in out.splitlines():
        if not line.strip():
            continue
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue  # commit/tree lines with no path, or root tree
        sha, path = parts
        pairs.append((sha, path))
    return pairs


def _blob_type(sha: str, repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "cat-file", "-t", sha],
        cwd=repo_root, capture_output=True, text=True, check=False,
    )
    return result.stdout.strip()


def _blob_size(sha: str, repo_root: Path) -> int:
    result = subprocess.run(
        ["git", "cat-file", "-s", sha],
        cwd=repo_root, capture_output=True, text=True, check=False,
    )
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def _blob_content(sha: str, repo_root: Path) -> bytes:
    result = subprocess.run(
        ["git", "cat-file", "-p", sha],
        cwd=repo_root, capture_output=True, check=False,
    )
    return result.stdout


def scan_blob(path: str, content: bytes | None) -> list[Finding]:
    """Pure scan of a single (path, content) pair. `content` may be None to
    skip content scanning (path-only check)."""
    findings: list[Finding] = []
    for pattern in DENY_PATH_PATTERNS:
        if pattern.search(path):
            findings.append(Finding("BLOCK", path, f"disallowed path ({pattern.pattern})"))
            break  # path-blocked paths are not content-scanned

    if findings or content is None:
        return findings

    ext = Path(path).suffix.lower()
    if ext in BINARY_EXTENSIONS or len(content) > MAX_CONTENT_SCAN_BYTES:
        return findings

    text = content.decode("utf-8", errors="ignore")
    for pattern in BLOCK_CONTENT_PATTERNS:
        if pattern.search(text):
            findings.append(Finding("BLOCK", path, f"secret-shaped content ({pattern.pattern})"))
    for pattern in WARN_CONTENT_PATTERNS:
        if pattern.search(text):
            findings.append(Finding("WARN", path, f"generic credential-shaped content ({pattern.pattern})"))
    return findings


def scan_push(old_sha: str, new_sha: str, repo_root: Path) -> ScanResult:
    findings: list[Finding] = []
    for blob_sha, path in _new_blobs(old_sha, new_sha, repo_root):
        if _blob_type(blob_sha, repo_root) != "blob":
            continue
        path_findings = scan_blob(path, None)
        if path_findings:
            findings.extend(path_findings)
            continue
        if _blob_size(blob_sha, repo_root) > MAX_CONTENT_SCAN_BYTES:
            continue
        content = _blob_content(blob_sha, repo_root)
        findings.extend(scan_blob(path, content))
    return ScanResult(tuple(findings))


def format_report(result: ScanResult) -> str:
    if not result.findings:
        return "[verify_public_safe] clean: no disallowed paths or secret-shaped content in this push."
    lines = []
    for finding in result.findings:
        lines.append(f"  [{finding.severity}] {finding.path}: {finding.reason}")
    header = (
        f"[verify_public_safe] {len(result.blocking)} blocking finding(s), "
        f"{len(result.findings) - len(result.blocking)} warning(s):"
    )
    return "\n".join([header, *lines])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--old", required=True, help="Old (remote-side) SHA, or all-zeros for a new ref")
    parser.add_argument("--new", required=True, help="New (local-side) SHA being pushed")
    parser.add_argument("--repo-root", default=".", help="Repository root (default: cwd)")
    args = parser.parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    result = scan_push(args.old, args.new, repo_root)
    print(format_report(result), file=sys.stderr)
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
