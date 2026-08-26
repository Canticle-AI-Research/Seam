"""Quick audit of the most recent HISTORY.md entry.

Focused checks that the repo-wide verify gates do not cover, applied only to
the latest entry: controlled topic vocabulary, ISO date that does not predate
its predecessor, and a supersedes value that resolves to an earlier entry.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tools.history.history_lib import Entry

# Controlled topic vocabulary from AGENTS.md "Topic Vocabulary".
TOPIC_VOCABULARY = frozenset(
    {
        "agent", "alias", "animation", "atomicity", "audit", "beam",
        "benchmark", "bugfix", "bundle", "chat", "chroma", "ci",
        "classification", "codec", "command", "commonmark", "comparator",
        "compile", "compiler", "compress", "concepts", "config", "continuity",
        "correction", "dashboard", "demo", "defect", "diff", "docker",
        "docs", "doctor", "experience", "extras", "fixture", "git-hooks",
        "gold-standard", "graph", "gates", "handoff", "harden", "history",
        "holdout", "installer", "integrity", "json", "judge", "keyboard",
        "lexical", "linux", "locking", "locomo", "longmemeval", "lx1",
        "macos", "mcp", "memory", "mirl", "models", "multi-agent",
        "navigation", "naming", "nl", "operator", "pack", "parity",
        "persist", "pgvector", "plan", "prompt", "protocol", "provenance",
        "quality", "rank", "readme", "reconcile", "registry", "retrieval",
        "retry", "roadmap", "roots", "roundtrip", "salvage", "sbert",
        "scripts", "search", "security", "session", "skills", "snapshot",
        "status", "storage", "streams", "surface", "test", "tests",
        "textual", "tokenizer", "trust", "tui", "vector", "verify", "webui",
        "wiki", "windows", "worktree", "wsl2",
    }
)


@dataclass(frozen=True)
class LatestEntryIssue:
    kind: str  # "topic" | "date" | "supersedes"
    message: str

    def format(self) -> str:
        return f"{self.kind}: {self.message}"


def _parse_entry_date(value: str) -> datetime | None:
    """Parse an entry date (ISO 8601; entries use '...Z' UTC timestamps)."""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def audit_latest_entry(entries: list[Entry]) -> list[LatestEntryIssue]:
    """Audit only the most recent entry in a parsed HISTORY.md entry list."""
    if not entries:
        return [LatestEntryIssue("history", "no entries to audit")]
    latest = entries[-1]
    issues: list[LatestEntryIssue] = []

    unknown = [t for t in latest.topics if t not in TOPIC_VOCABULARY]
    if unknown:
        issues.append(
            LatestEntryIssue(
                "topic",
                f"Entry #{latest.id:03d} uses out-of-vocabulary topics: "
                f"{', '.join(unknown)}",
            )
        )

    latest_dt = _parse_entry_date(latest.date)
    if latest_dt is None:
        issues.append(
            LatestEntryIssue(
                "date",
                f"Entry #{latest.id:03d} has non-ISO date {latest.date!r}",
            )
        )
    elif len(entries) >= 2:
        predecessor = entries[-2]
        predecessor_dt = _parse_entry_date(predecessor.date)
        if predecessor_dt is not None and latest_dt < predecessor_dt:
            issues.append(
                LatestEntryIssue(
                    "date",
                    f"Entry #{latest.id:03d} date {latest.date} predates "
                    f"predecessor #{predecessor.id:03d} date {predecessor.date}",
                )
            )

    supersedes = latest.supersedes.strip()
    if supersedes.lower() != "none":
        try:
            target = int(supersedes.lstrip("#"))
        except ValueError:
            issues.append(
                LatestEntryIssue(
                    "supersedes",
                    f"Entry #{latest.id:03d} supersedes {supersedes!r} "
                    f"is not an entry id",
                )
            )
        else:
            if target >= latest.id:
                issues.append(
                    LatestEntryIssue(
                        "supersedes",
                        f"Entry #{latest.id:03d} supersedes #{target:03d}, "
                        f"which is not an earlier entry",
                    )
                )
            elif target not in {e.id for e in entries}:
                issues.append(
                    LatestEntryIssue(
                        "supersedes",
                        f"Entry #{latest.id:03d} supersedes missing entry #{target:03d}",
                    )
                )

    return issues


if __name__ == "__main__":
    import sys

    from tools.history.history_lib import parse_entries, read_history_bytes

    data = read_history_bytes()
    try:
        entries = parse_entries(data) if data else []
    except ValueError as exc:
        print(f"Latest-entry audit FAILED: parse error: {exc}")
        sys.exit(1)
    issues = audit_latest_entry(entries)
    if issues:
        print("Latest-entry audit FAILED:")
        for issue in issues:
            print(f"  - {issue.format()}")
        sys.exit(1)
    print(f"Latest entry #{entries[-1].id:03d} audit OK")
    sys.exit(0)
