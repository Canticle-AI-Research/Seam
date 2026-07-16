"""Audit hard-coded pytest count claims in active docs and latest history."""
from __future__ import annotations

import ast
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from tools.history.history_lib import HISTORY_PATH, parse_entries, read_history_bytes

CLAIM_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b(?:existing\s+)?tests?\s+pass(?:ed)?\s*\((?P<count>\d+)(?P<plus>\+)?\)", re.I),
    re.compile(r"\b(?P<count>\d+)(?P<plus>\+)?\s+(?:existing\s+)?tests?\s+pass(?:ed)?\b", re.I),
    re.compile(r"\bpassed with (?P<count>\d+) passed\b", re.I),
    re.compile(r"\bcollected (?P<count>\d+) tests?\b", re.I),
    re.compile(r"\b(?P<count>\d+)/(?P=count)\b"),
)

DEFAULT_DOC_PATHS: tuple[str, ...] = (
    "PROJECT_STATUS.md",
    "ROADMAP.md",
    "docs/setup.md",
    "docs/howto/README.md",
    "docs/roadmap",
)


@dataclass(frozen=True)
class CountFactRecord:
    value: int
    scope: tuple[str, ...]
    location: str
    sequence: int


def count_static_tests(paths: list[Path]) -> int:
    """Count pytest/unittest-style test functions under paths without importing code."""
    total = 0
    for path in _iter_test_files(paths):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                total += 1
    return total


def audit_test_count_claims(
    repo_root: Path,
    *,
    doc_paths: list[Path] | None = None,
    history_path: Path | None = None,
    latest_history_only: bool = True,
) -> list[str]:
    """Return issues for stale or ambiguous hard-coded pytest count claims."""
    repo_root = repo_root.resolve()
    if doc_paths is None:
        doc_paths = _default_doc_paths(repo_root)
    issues: list[str] = []
    for path in doc_paths:
        issues.extend(_audit_text_path(repo_root, path))

    if latest_history_only:
        history = history_path or repo_root / "HISTORY.md"
        issues.extend(_audit_latest_history_entry(repo_root, history))
    return issues


def collect_test_count_facts(
    repo_root: Path,
    text: str,
    *,
    source: Path | str,
    line_offset: int = 0,
    sequence: int = 0,
    require_explicit_pytest_line: bool = False,
) -> list[CountFactRecord]:
    """Extract scoped test-count facts from text."""
    repo_root = repo_root.resolve()
    facts: list[CountFactRecord] = []
    source_label = str(source)
    try:
        source_path = Path(source)
        if source_path.is_absolute():
            source_label = str(source_path.relative_to(repo_root))
    except ValueError:
        pass
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        claim_line = _pytest_claim_segment(line) if require_explicit_pytest_line else line
        matches = list(_claim_matches(claim_line))
        if not matches and idx + 1 < len(lines) and _could_be_split_claim(line, lines[idx + 1]):
            split_line = f"{line} {lines[idx + 1]}"
            claim_line = _pytest_claim_segment(split_line) if require_explicit_pytest_line else split_line
            matches = list(_claim_matches(claim_line))
        if require_explicit_pytest_line and matches and not _explicit_pytest_claim_line(line):
            continue
        for match in matches:
            if not _is_pytest_count_match(match, claim_line):
                continue
            context = "\n".join(lines[max(0, idx - 24) : idx] + [_line_through_match(claim_line, match)])
            scoped_paths = _pytest_paths_from_context(repo_root, context)
            if not scoped_paths:
                continue
            command_scope = _pytest_command_scope_from_context(repo_root, context)
            facts.append(
                CountFactRecord(
                    value=int(match.group("count")),
                    scope=command_scope
                    or tuple(str(path.relative_to(repo_root.resolve())) for path in scoped_paths),
                    location=f"{source_label}:{line_offset + idx + 1}",
                    sequence=sequence,
                )
            )
    return facts


def _default_doc_paths(repo_root: Path) -> list[Path]:
    paths: list[Path] = []
    for rel in DEFAULT_DOC_PATHS:
        path = repo_root / rel
        if path.is_dir():
            paths.extend(sorted(path.glob("*.md")))
        elif path.exists():
            paths.append(path)
    return paths


def _audit_latest_history_entry(repo_root: Path, history_path: Path) -> list[str]:
    try:
        if history_path == HISTORY_PATH:
            data = read_history_bytes(history_path)
        else:
            data = history_path.read_bytes()
        entries = parse_entries(data) if data else []
    except (OSError, ValueError):
        return []
    if not entries:
        return []
    return _audit_text(repo_root, history_path, entries[-1].body, line_offset=entries[-1].line_start)


def _audit_text_path(repo_root: Path, path: Path) -> list[str]:
    path = (repo_root / path).resolve() if not path.is_absolute() else path.resolve()
    if not path.exists() or not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return _audit_text(repo_root, path, text)


def _audit_text(repo_root: Path, path: Path, text: str, *, line_offset: int = 0) -> list[str]:
    repo_root = repo_root.resolve()
    path = (repo_root / path).resolve() if not path.is_absolute() else path.resolve()
    issues: list[str] = []
    lines = text.splitlines()
    for idx, line in enumerate(lines):
        claim_line = line
        matches = list(_claim_matches(claim_line))
        if not matches and idx + 1 < len(lines) and _could_be_split_claim(line, lines[idx + 1]):
            claim_line = f"{line} {lines[idx + 1]}"
            matches = list(_claim_matches(claim_line))
        for match in matches:
            if not _is_pytest_count_match(match, claim_line):
                continue
            count = int(match.group("count"))
            context = "\n".join(lines[max(0, idx - 24) : idx] + [_line_through_match(claim_line, match)])
            scoped_paths = _pytest_paths_from_context(repo_root, context)
            location = f"{path.relative_to(repo_root)}:{line_offset + idx + 1}"
            if not scoped_paths:
                issues.append(f"{location}: test count claim {count} lacks pytest path scope")
                continue
            actual = count_static_tests(scoped_paths)
            if actual != count:
                rel_paths = ", ".join(str(p.resolve().relative_to(repo_root)) for p in scoped_paths)
                issues.append(
                    f"{location}: scoped pytest claim claims {count}, "
                    f"but actual static count is {actual} for {rel_paths}"
                )
    return issues


def _claim_matches(line: str):
    for pattern in CLAIM_PATTERNS:
        for match in pattern.finditer(line):
            yield match


def _is_pytest_count_match(match: re.Match[str], line: str) -> bool:
    raw = match.group(0)
    if "/" in raw and "pytest" not in _claim_sentence(line, match).lower():
        return False
    return True


def _line_through_match(line: str, match: re.Match[str]) -> str:
    return line[: match.end()]


def _claim_sentence(line: str, match: re.Match[str]) -> str:
    start = match.start()
    end = match.end()
    left = max(line.rfind(". ", 0, start), line.rfind("; ", 0, start))
    right_candidates = [pos for pos in (line.find(". ", end), line.find("; ", end)) if pos >= 0]
    right = min(right_candidates) if right_candidates else len(line)
    return line[left + 2 : right]


def _could_be_split_claim(line: str, next_line: str) -> bool:
    joined = f"{line} {next_line}".lower()
    return bool(re.search(r"\d", line)) and "test" in joined


def _pytest_paths_from_context(repo_root: Path, context: str) -> list[Path]:
    paths: list[Path] = []
    for raw_line in reversed(context.splitlines()):
        if "pytest" not in raw_line:
            continue
        for token in _tokens_after_pytest(raw_line):
            candidate = token.strip("\"'`").replace("\\", "/")
            if not candidate or candidate.startswith("-"):
                continue
            path = (repo_root / candidate).resolve()
            try:
                path.relative_to(repo_root.resolve())
            except ValueError:
                continue
            if path.exists():
                paths.append(path)
        if paths:
            return _dedupe(paths)
    return []


def _pytest_command_scope_from_context(repo_root: Path, context: str) -> tuple[str, ...]:
    for raw_line in reversed(context.splitlines()):
        if "pytest" not in raw_line:
            continue
        scope: list[str] = []
        for token in _tokens_after_pytest(raw_line):
            normalized = token.strip("\"'`").replace("\\", "/")
            lower = normalized.lower()
            if lower in {"passed", "pass", "failed", "returned", "with", "collected"}:
                break
            if not normalized:
                continue
            path = (repo_root / normalized).resolve()
            try:
                rel = str(path.relative_to(repo_root.resolve()))
            except ValueError:
                rel = normalized
            scope.append(rel)
        if scope:
            return tuple(scope)
    return ()


def _explicit_pytest_claim_line(line: str) -> bool:
    lower = line.lower()
    return "pytest" in lower or "passed with" in lower or "collected" in lower


def _pytest_claim_segment(line: str) -> str:
    lower = line.lower()
    idx = lower.find("pytest")
    if idx < 0:
        return line
    segment = line[idx:]
    for marker in (". `python ", ". python ", "; `python ", "; python "):
        marker_idx = segment.find(marker)
        if marker_idx > 0:
            return segment[:marker_idx]
    return segment


def _tokens_after_pytest(line: str) -> list[str]:
    try:
        tokens = shlex.split(line, posix=False)
    except ValueError:
        tokens = line.split()
    for idx, token in enumerate(tokens):
        if token.endswith("pytest") or token == "pytest":
            return tokens[idx + 1 :]
    return []


def _iter_test_files(paths: list[Path]):
    for path in paths:
        if path.is_file() and path.name.startswith("test") and path.suffix == ".py":
            yield path
        elif path.is_dir():
            yield from sorted(p for p in path.rglob("test*.py") if p.is_file())


def _dedupe(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out
