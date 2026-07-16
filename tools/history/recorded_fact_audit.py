"""Audit checkable recorded facts in active docs and latest history."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from tools.history.history_lib import HISTORY_PATH, Entry, parse_entries, read_history_bytes
from tools.history.test_count_audit import CountFactRecord, audit_test_count_claims, collect_test_count_facts

HANDOFF_RE = re.compile(r"\bLatest continuity handoff is [`']?HISTORY#(?P<id>\d+)[`']?", re.I)


@dataclass(frozen=True)
class RecordedFactIssue:
    kind: str
    location: str
    message: str

    def format(self) -> str:
        return f"{self.kind}: {self.location}: {self.message}"


def audit_recorded_facts(
    repo_root: Path,
    *,
    history_path: Path | None = None,
    doc_paths: list[Path] | None = None,
) -> list[RecordedFactIssue]:
    """Audit all currently checkable recorded-fact types.

    Continuity already verifies entry hashes, index freshness, supersedes links,
    snapshots, routing references, and secret/session-link hygiene. This module
    covers additional factual claims written in active docs or the latest log.
    """
    repo_root = repo_root.resolve()
    history = history_path or repo_root / "HISTORY.md"
    history = (repo_root / history).resolve() if not history.is_absolute() else history.resolve()
    latest = _latest_entry(history)
    issues: list[RecordedFactIssue] = []

    issues.extend(
        _wrap_test_count_issues(
            audit_test_count_claims(
                repo_root,
                doc_paths=doc_paths,
                history_path=history,
                latest_history_only=True,
            )
        )
    )
    if latest is not None:
        issues.extend(_audit_handoff_pointers(repo_root, latest.id, doc_paths))
        issues.extend(_audit_latest_entry_refs(repo_root, latest))
        issues.extend(_audit_test_count_precedence(repo_root, history))
    return issues


def _latest_entry(history_path: Path) -> Entry | None:
    try:
        data = read_history_bytes(history_path) if history_path == HISTORY_PATH else history_path.read_bytes()
        entries = parse_entries(data) if data else []
    except (OSError, ValueError):
        return None
    return entries[-1] if entries else None


def _wrap_test_count_issues(raw_issues: list[str]) -> list[RecordedFactIssue]:
    issues: list[RecordedFactIssue] = []
    for raw in raw_issues:
        location, _, message = raw.partition(": ")
        issues.append(RecordedFactIssue("test-count", location, message or raw))
    return issues


def _audit_handoff_pointers(
    repo_root: Path,
    latest_id: int,
    doc_paths: list[Path] | None,
) -> list[RecordedFactIssue]:
    paths = doc_paths if doc_paths is not None else [repo_root / "PROJECT_STATUS.md"]
    issues: list[RecordedFactIssue] = []
    for path in paths:
        path = (repo_root / path).resolve() if not path.is_absolute() else path.resolve()
        if not path.exists() or not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line_no, line in enumerate(lines, 1):
            match = HANDOFF_RE.search(line)
            if not match:
                continue
            claimed = int(match.group("id"))
            if claimed != latest_id:
                issues.append(
                    RecordedFactIssue(
                        "handoff",
                        f"{path.relative_to(repo_root.resolve())}:{line_no}",
                        f"claims HISTORY#{claimed:03d}, but latest HISTORY#{latest_id:03d}",
                    )
                )
    return issues


def _audit_latest_entry_refs(repo_root: Path, latest: Entry) -> list[RecordedFactIssue]:
    issues: list[RecordedFactIssue] = []
    repo_root = repo_root.resolve()
    for ref in _entry_ref_paths(latest.refs):
        path = repo_root / ref
        if not path.exists():
            issues.append(
                RecordedFactIssue(
                    "history-ref",
                    f"HISTORY#{latest.id:03d}",
                    f"latest entry refs missing path {ref}",
                )
            )
    return issues


def _entry_ref_paths(refs: str) -> list[str]:
    if refs.strip().lower() == "none":
        return []
    out: list[str] = []
    for raw in refs.split(","):
        ref = raw.strip()
        if not ref:
            continue
        if ref.startswith(("http://", "https://", "HISTORY#")):
            continue
        if "/" in ref or "." in Path(ref).name:
            out.append(ref)
    return out


def _audit_test_count_precedence(repo_root: Path, history_path: Path) -> list[RecordedFactIssue]:
    entries = _entries(history_path)
    facts: list[CountFactRecord] = []
    for entry in entries:
        facts.extend(
            collect_test_count_facts(
                repo_root,
                entry.body,
                source=f"HISTORY#{entry.id:03d}",
                line_offset=entry.line_start,
                sequence=entry.id,
                require_explicit_pytest_line=True,
            )
        )

    issues: list[RecordedFactIssue] = []
    latest_by_scope: dict[tuple[str, ...], CountFactRecord] = {}
    for fact in sorted(facts, key=lambda item: item.sequence):
        previous = latest_by_scope.get(fact.scope)
        if previous and fact.value < previous.value:
            scope = ", ".join(fact.scope)
            issues.append(
                RecordedFactIssue(
                    "test-count-precedence",
                    fact.location,
                    (
                        f"same pytest scope dropped from {previous.value} to {fact.value} "
                        f"after {previous.location}; scope: {scope}"
                    ),
                )
            )
        latest_by_scope[fact.scope] = fact
    return issues


def _entries(history_path: Path) -> list[Entry]:
    try:
        data = read_history_bytes(history_path) if history_path == HISTORY_PATH else history_path.read_bytes()
        return parse_entries(data) if data else []
    except (OSError, ValueError):
        return []
