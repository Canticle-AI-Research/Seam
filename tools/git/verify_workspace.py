"""Fail on untracked clutter that `git status` cannot see.

Gitignored paths are invisible to `git status`, so they accumulate forever and
every existing gate reports green while the tree fills with stray artifacts.
That is not hypothetical: with 16 stray files, a 4.4MB binary and a dirty
worktree present, all eleven repo-hygiene checks passed and `git status` was
empty. Ten prior hygiene incidents (HISTORY#406, #534, #555, #567-569, #604)
were each answered by adding a `.gitignore` line, which hides the next
occurrence rather than preventing it.

HISTORY#534 named the reason this keeps recurring: the rule was ACTION_REQUIRED
prose that "nobody was gated on". HISTORY.md is immaculate because gates
enforce it. This module gates the working tree the same way.

`[tool.seam.workspace-contract]` in pyproject.toml is the checked authority for
what may exist untracked. Anything ignored and present at the repository root
that is not declared there fails, as does a sink over budget, a stray scratch
file at the root, a dirty or stale worktree, or too many worktrees at once.

Every finding names the exact path and the exact command that clears it,
because a gate people cannot act on quickly is a gate they will disable.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_KEY = "workspace-contract"
SCHEMA = "seam-workspace-contract/1"


@dataclass(frozen=True)
class Finding:
    path: str
    problem: str
    remedy: str

    def render(self) -> str:
        return f"  {self.path}\n      {self.problem}\n      fix: {self.remedy}"


def load_contract(repo_root: Path = REPO_ROOT) -> dict:
    data = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))
    contract = data["tool"]["seam"][CONTRACT_KEY]
    if contract.get("schema") != SCHEMA:
        raise ValueError(f"unsupported workspace contract schema: {contract.get('schema')!r}")
    return contract


def _git(*args: str, cwd: Path = REPO_ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=False
    ).stdout


def _is_ignored(path: Path, repo_root: Path) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "-q", str(path)],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _dir_size_mb(path: Path, ceiling_mb: float) -> float:
    """Sum sizes, stopping early once the ceiling is exceeded.

    Walking a sink that has grown to gigabytes must not itself be the thing
    that makes the gate slow enough to disable.
    """
    ceiling_bytes = ceiling_mb * 1024 * 1024
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                continue
            if total > ceiling_bytes:
                return total / (1024 * 1024)
    return total / (1024 * 1024)


def check_gitignore_coverage(contract: dict, repo_root: Path) -> list[Finding]:
    """A new .gitignore line must come with a disposition in the contract.

    This is the exact regression that produced ten incidents: someone hits
    stray output, silences it in .gitignore, and the clutter becomes permanent
    and invisible. Silencing a path now requires saying what it is.
    """

    declared = set(contract["allowed-ignored-roots"]) | set(contract["sink-roots"])
    handled = list(contract["forbidden-root-globs"]) + list(contract["forbidden-if-present"])
    findings: list[Finding] = []
    for raw in (repo_root / ".gitignore").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "!")):
            continue
        root = line.lstrip("/").rstrip("/")
        # Only a single-segment entry can create a stray top-level entry, which
        # is what this contract governs. A nested rule such as
        # `seam_runtime/config.toml` or `benchmarks/fixtures/holdout/*.json`
        # scopes a file inside an already-tracked directory; taking its first
        # segment would wrongly accuse `seam_runtime` and `benchmarks` of being
        # stray roots. Suffix and wildcard rules match files anywhere.
        if "/" in root or "*" in root or root.startswith("."):
            continue
        if root in declared or any(fnmatch(root, pattern) for pattern in handled):
            continue
        findings.append(
            Finding(
                path=f".gitignore -> {root}",
                problem=(
                    "silenced in .gitignore with no disposition in "
                    "[tool.seam.workspace-contract]"
                ),
                remedy=(
                    f"declare {root} in allowed-ignored-roots, sink-roots, "
                    "forbidden-root-globs or forbidden-if-present"
                ),
            )
        )
    return findings


def check_forbidden(contract: dict, repo_root: Path) -> list[Finding]:
    """Credential material must never sit in the tree, declared or not."""

    patterns = contract["forbidden-if-present"]
    findings: list[Finding] = []
    for entry in sorted(repo_root.iterdir()):
        if any(fnmatch(entry.name, pattern) for pattern in patterns):
            findings.append(
                Finding(
                    path=entry.name,
                    problem=(
                        "credential material in the working tree; gitignored, so "
                        "nothing else reports it"
                    ),
                    remedy=(
                        f"delete or redact {entry.name} now and rotate the credential. "
                        "Do NOT add it to the workspace contract."
                    ),
                )
            )
    return findings


def check_ignored_roots(contract: dict, repo_root: Path) -> list[Finding]:
    """Every ignored entry at the repo root must be declared in the contract."""

    declared = list(contract["allowed-ignored-roots"]) + list(contract["sink-roots"])
    findings: list[Finding] = []
    for entry in sorted(repo_root.iterdir()):
        if entry.name == ".git" or any(fnmatch(entry.name, d) for d in declared):
            continue
        if not _is_ignored(entry, repo_root):
            continue
        findings.append(
            Finding(
                path=f"{entry.name}{'/' if entry.is_dir() else ''}",
                problem=(
                    "ignored by .gitignore but not declared in "
                    "[tool.seam.workspace-contract]; invisible to git status"
                ),
                remedy=(
                    f"rm -rf {entry.name}  --  or declare it in "
                    "allowed-ignored-roots / sink-roots with a stated purpose"
                ),
            )
        )
    return findings


def check_sink_budgets(contract: dict, repo_root: Path) -> list[Finding]:
    budget = float(contract["max-sink-mb"])
    file_budget = float(contract["max-sink-file-mb"])
    findings: list[Finding] = []
    for name in sorted(contract["sink-roots"]):
        sink = repo_root / name
        if not sink.is_dir():
            continue
        size = _dir_size_mb(sink, budget)
        if size > budget:
            findings.append(
                Finding(
                    path=f"{name}/",
                    problem=f"disposable sink is {size:.1f}MB, over the {budget:.0f}MB budget",
                    remedy=f"rm -rf {name}/*  (contents are regenerable by definition)",
                )
            )
        for oversized in _oversized_files(sink, file_budget):
            findings.append(
                Finding(
                    path=str(oversized.relative_to(repo_root)),
                    problem=(
                        f"{oversized.stat().st_size / (1024 * 1024):.1f}MB single file in a "
                        f"disposable sink, over the {file_budget:.0f}MB per-file cap"
                    ),
                    remedy=f"rm {oversized.relative_to(repo_root)}  (regenerate it when needed)",
                )
            )
    return findings


def _oversized_files(sink: Path, cap_mb: float):
    cap = cap_mb * 1024 * 1024
    for root, _dirs, files in os.walk(sink, followlinks=False):
        for name in files:
            candidate = Path(root) / name
            try:
                if candidate.lstat().st_size > cap:
                    yield candidate
            except OSError:
                continue


def check_root_scratch(contract: dict, repo_root: Path) -> list[Finding]:
    globs = contract["forbidden-root-globs"]
    tracked = {
        line for line in _git("ls-files", "--", ".").splitlines() if "/" not in line
    }
    findings: list[Finding] = []
    for entry in sorted(repo_root.iterdir()):
        if entry.is_dir() or entry.name in tracked:
            continue
        if any(fnmatch(entry.name, pattern) for pattern in globs):
            findings.append(
                Finding(
                    path=entry.name,
                    problem="scratch file at the repository root (AGENTS.md forbids these)",
                    remedy=f"rm {entry.name}  --  or move it under test_seam/",
                )
            )
    return findings


def _worktrees(repo_root: Path) -> list[tuple[Path, str]]:
    """Return (path, branch) for every worktree except the primary one."""

    out = _git("worktree", "list", "--porcelain", cwd=repo_root)
    entries: list[tuple[Path, str]] = []
    path: Path | None = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree ") :])
        elif line.startswith("branch ") and path is not None:
            entries.append((path, line[len("branch ") :].removeprefix("refs/heads/")))
            path = None
    return [(p, b) for p, b in entries if p.resolve() != repo_root.resolve()]


def check_worktrees(contract: dict, repo_root: Path) -> list[Finding]:
    worktrees = _worktrees(repo_root)
    findings: list[Finding] = []

    limit = int(contract["max-worktrees"])
    if len(worktrees) > limit:
        findings.append(
            Finding(
                path=f"{len(worktrees)} linked worktrees",
                problem=f"more than the {limit} allowed at once",
                remedy="git worktree list, then git worktree remove <path> for finished work",
            )
        )

    for path, branch in worktrees:
        if not path.exists():
            findings.append(
                Finding(
                    path=str(path),
                    problem="worktree registered but missing from disk",
                    remedy="git worktree prune",
                )
            )
            continue
        if _git("status", "--porcelain", cwd=path).strip():
            findings.append(
                Finding(
                    path=str(path),
                    problem=f"worktree on '{branch}' has uncommitted changes",
                    remedy=(
                        f"commit and push from {path}, or "
                        f"git worktree remove --force {path} to abandon it"
                    ),
                )
            )
    return findings


def _prunable(contract: dict, repo_root: Path) -> list[Path]:
    """Paths --fix may delete: undeclared ignored roots, over-budget sink contents,
    and root scratch files. Never a worktree, which may hold unpushed work."""

    forbidden = {f.path for f in check_forbidden(contract, repo_root)}
    targets: list[Path] = []
    for finding in check_ignored_roots(contract, repo_root) + check_root_scratch(
        contract, repo_root
    ):
        if finding.path in forbidden:
            # Deleting a key without the operator noticing would hide the fact
            # that it needs rotating. Report it; let a human act.
            continue
        candidate = repo_root / finding.path.rstrip("/")
        if candidate not in targets:
            targets.append(candidate)
    for finding in check_sink_budgets(contract, repo_root):
        # A sink finding is either the sink itself (over total budget, so prune
        # its contents) or a single oversized file inside it (prune just that).
        target = repo_root / finding.path.rstrip("/")
        if target.is_dir():
            targets.extend(target.iterdir())
        else:
            targets.append(target)
    return targets


def run_checks(contract: dict, repo_root: Path) -> list[Finding]:
    """Collect findings, reporting each path once.

    A root scratch file is usually also an undeclared ignored entry, and
    printing the same path twice with two different remedies trains people to
    skim the output instead of reading it.
    """

    ordered = (
        check_forbidden(contract, repo_root)
        + check_root_scratch(contract, repo_root)
        + check_ignored_roots(contract, repo_root)
        + check_sink_budgets(contract, repo_root)
        + check_worktrees(contract, repo_root)
        + check_gitignore_coverage(contract, repo_root)
    )
    seen: set[str] = set()
    deduped: list[Finding] = []
    for finding in ordered:
        key = finding.path.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    return deduped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--fix",
        action="store_true",
        help="delete undeclared artifacts and over-budget sink contents (never a worktree)",
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    contract = load_contract(repo_root)

    if args.fix:
        for target in _prunable(contract, repo_root):
            if target.is_dir():
                shutil.rmtree(target, ignore_errors=True)
            else:
                target.unlink(missing_ok=True)
            print(f"removed {target.relative_to(repo_root)}")

    findings = run_checks(contract, repo_root)
    if not findings:
        print("Workspace hygiene OK")
        return 0

    print("Workspace hygiene FAILED -- untracked clutter git status cannot see:\n")
    for finding in findings:
        print(finding.render())
    print(
        "\nThese paths are gitignored, so nothing else in the gate suite sees them."
        "\nRun `python -m tools.git.verify_workspace --fix` to clear what is safely"
        "\nremovable; worktrees are always left for you to resolve by hand."
    )
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
