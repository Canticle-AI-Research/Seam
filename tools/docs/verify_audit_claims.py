"""Audit the self-checkable claims an audit report makes about this repository.

Audit reports are written by agents, and agents are reliable where they measure
and unreliable where they summarize. HISTORY#560's report cited 94 file:line
references with zero bad line numbers and reproduced the suite count exactly,
then miscounted its own findings (claimed 15 MEDIUM, wrote 17) and misdated one
timeline row out of 559. Both defects were mechanical and neither was caught by
a human read.

This module checks the classes of claim that can be settled against something
already in the repository:

  citations  every `path:line` reference resolves and no line number is past EOF
  tally      a prose finding-count matches the findings the document itself labels
  timeline   `| #NNN | date | status |` rows agree with HISTORY.md

It deliberately does not attempt open-world facts. The same report asserted that
httpx follows redirects by default, which is false for the pinned version, and
nothing in this repository settles that. Claims about third-party behaviour stay
a human problem; see the module docstring of tools/history/recorded_fact_audit.py
for the sibling gate over recorded test counts.

Author-agnostic by design. It gates the artifact, not who produced it.

Usage:
    python -m tools.docs.verify_audit_claims                 # all of docs/audits
    python -m tools.docs.verify_audit_claims --docs a.md b.md
    python -m tools.docs.verify_audit_claims --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOC_DIR = REPO_ROOT / "docs" / "audits"
HISTORY_PATH = REPO_ROOT / "HISTORY.md"

# Directories a bare filename in a report may refer to. Reports cite basenames
# ("ci.yml", "test_run_record.py") far more often than repo-relative paths.
SEARCH_ROOTS: tuple[str, ...] = (
    "",
    "seam_runtime",
    "tools",
    "tests",
    "tests/audit",
    "test_seam_all",
    "benchmarks",
    "docs",
    ".github/workflows",
)
SKIP_DIRS: frozenset[str] = frozenset({".venv", ".git", "__pycache__", "node_modules", "build"})

CITATION_RE = re.compile(
    r"`(?P<path>[A-Za-z0-9_][A-Za-z0-9_./-]*\.(?:py|md|toml|yml|yaml|sh|ini|cfg))"
    r"(?::(?P<lines>[0-9][0-9,\-]*))?`"
)
FINDING_RE = re.compile(r"\*\*(?P<id>[A-Z]-\d+)\s+[—–-]\s+(?P<sev>[A-Z]+)\b")
LOW_ROW_RE = re.compile(r"^\|\s*(?P<id>L-\d+)\s*\|", re.M)
TIMELINE_ROW_RE = re.compile(
    r"^\|\s*#(?P<id>\d+)\s*\|\s*(?P<date>\d{4}-\d{2}-\d{2})\s*\|\s*(?P<status>[A-Za-z-]+)\s*\|",
    re.M,
)
ENTRY_RE = re.compile(
    r"^---BEGIN-ENTRY-#(?P<id>\d+)---\r?$(?P<body>.*?)^---END-ENTRY-#(?P=id)---",
    re.M | re.S,
)

NUMBER_WORDS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
}
SEVERITY_WORDS: tuple[str, ...] = ("CRITICAL", "HIGH", "MED", "MEDIUM", "LOW")
# "**fifteen MEDIUM findings**" / "3 HIGH" / "seventeen MED"
TALLY_CLAIM_RE = re.compile(
    r"\b(?P<count>\d+|" + "|".join(NUMBER_WORDS) + r")\s+\**(?P<sev>"
    + "|".join(SEVERITY_WORDS) + r")\b",
    re.I,
)


@dataclass(frozen=True)
class Issue:
    doc: str
    kind: str
    location: str
    message: str

    def render(self) -> str:
        return f"{self.doc}: [{self.kind}] {self.location}: {self.message}"


@dataclass
class DocReport:
    doc: str
    checked: dict[str, int] = field(default_factory=dict)
    issues: list[Issue] = field(default_factory=list)


def _normalize_severity(token: str) -> str:
    token = token.upper()
    return "MEDIUM" if token == "MED" else token


def _iter_repo_files() -> dict[str, list[Path]]:
    """Map basename -> paths, so a report citing a bare filename still resolves."""
    index: dict[str, list[Path]] = {}
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        index.setdefault(path.name, []).append(path)
    return index


def resolve_citation(ref: str, basename_index: dict[str, list[Path]]) -> Path | None:
    for root in SEARCH_ROOTS:
        candidate = REPO_ROOT / root / ref if root else REPO_ROOT / ref
        if candidate.is_file():
            return candidate
    matches = basename_index.get(Path(ref).name, [])
    return matches[0] if len(matches) >= 1 else None


def check_citations(text: str, doc: str, basename_index: dict[str, list[Path]]) -> tuple[int, list[Issue]]:
    """Every cited path resolves, and no cited line number is past end of file."""
    issues: list[Issue] = []
    seen: set[tuple[str, str]] = set()
    for match in CITATION_RE.finditer(text):
        ref = match.group("path")
        lines = match.group("lines") or ""
        if (ref, lines) in seen:
            continue
        seen.add((ref, lines))
        target = resolve_citation(ref, basename_index)
        if target is None:
            issues.append(Issue(doc, "citation", ref, "cited file does not exist in the repository"))
            continue
        numbers = [int(n) for n in re.findall(r"\d+", lines)]
        if not numbers:
            continue
        total = sum(1 for _ in target.open(encoding="utf-8", errors="ignore"))
        if max(numbers) > total:
            issues.append(
                Issue(
                    doc,
                    "citation",
                    f"{ref}:{lines}",
                    f"cites line {max(numbers)} but {target.relative_to(REPO_ROOT)} has {total} lines",
                )
            )
    return len(seen), issues


def check_tally(text: str, doc: str) -> tuple[dict[str, int], list[Issue]]:
    """A prose count of findings must match the findings the document labels.

    Only flags a severity when the document both labels findings of that
    severity and states a differing number for it. Silence is not an error --
    a report is free to omit a summary.
    """
    issues: list[Issue] = []
    actual: dict[str, int] = {}
    for match in FINDING_RE.finditer(text):
        actual[_normalize_severity(match.group("sev"))] = actual.get(
            _normalize_severity(match.group("sev")), 0
        ) + 1
    low_rows = len(LOW_ROW_RE.findall(text))
    if low_rows:
        actual["LOW"] = actual.get("LOW", 0) + low_rows
    if not actual:
        return actual, issues

    # Only read tally claims from the summary, i.e. the text preceding the first
    # labelled finding. Later sections carry per-subsystem breakdowns ("1 MED
    # (F-14), 5 LOW") that are partial by construction; counting those as
    # whole-document claims produces noise, not findings.
    first_finding = FINDING_RE.search(text)
    summary = text[: first_finding.start()] if first_finding else text

    claimed: dict[str, set[int]] = {}
    for match in TALLY_CLAIM_RE.finditer(summary):
        raw = match.group("count").lower()
        value = NUMBER_WORDS.get(raw, None)
        if value is None:
            try:
                value = int(raw)
            except ValueError:
                continue
        claimed.setdefault(_normalize_severity(match.group("sev")), set()).add(value)

    for severity, real in sorted(actual.items()):
        stated = claimed.get(severity)
        if not stated:
            continue
        if real not in stated:
            issues.append(
                Issue(
                    doc,
                    "tally",
                    severity,
                    f"document labels {real} {severity} finding(s) but states "
                    f"{sorted(stated)} in prose",
                )
            )
    return actual, issues


def load_history_entries() -> dict[int, tuple[str, str]]:
    if not HISTORY_PATH.exists():
        return {}
    text = HISTORY_PATH.read_text(encoding="utf-8")
    entries: dict[int, tuple[str, str]] = {}
    for match in ENTRY_RE.finditer(text):
        body = match.group("body")
        date = re.search(r"^date:\s*(\S+)", body, re.M)
        status = re.search(r"^status:\s*(\S+)", body, re.M)
        entries[int(match.group("id"))] = (
            date.group(1) if date else "",
            status.group(1) if status else "",
        )
    return entries


def check_timeline(text: str, doc: str, history: dict[int, tuple[str, str]]) -> tuple[int, list[Issue]]:
    """Timeline rows must agree with HISTORY.md on date and status, and cover ids uniquely."""
    issues: list[Issue] = []
    rows = [
        (int(m.group("id")), m.group("date"), m.group("status"))
        for m in TIMELINE_ROW_RE.finditer(text)
    ]
    if not rows:
        return 0, issues

    seen: set[int] = set()
    for entry_id, date, status in rows:
        if entry_id in seen:
            issues.append(Issue(doc, "timeline", f"#{entry_id}", "row id appears more than once"))
            continue
        seen.add(entry_id)
        if entry_id not in history:
            issues.append(
                Issue(doc, "timeline", f"#{entry_id}", "no such entry in HISTORY.md")
            )
            continue
        hist_date, hist_status = history[entry_id]
        if hist_date and not hist_date.startswith(date):
            issues.append(
                Issue(doc, "timeline", f"#{entry_id}",
                      f"row date {date} but HISTORY.md records {hist_date}")
            )
        if hist_status and hist_status != status:
            issues.append(
                Issue(doc, "timeline", f"#{entry_id}",
                      f"row status {status!r} but HISTORY.md records {hist_status!r}")
            )

    covered = sorted(seen)
    gaps = sorted(set(range(covered[0], covered[-1] + 1)) - seen)
    if gaps:
        preview = ", ".join(f"#{g}" for g in gaps[:10])
        more = f" (+{len(gaps) - 10} more)" if len(gaps) > 10 else ""
        issues.append(
            Issue(doc, "timeline", f"#{covered[0]}-#{covered[-1]}",
                  f"{len(gaps)} id(s) missing from the covered range: {preview}{more}")
        )
    return len(rows), issues


def audit_document(path: Path, history: dict[int, tuple[str, str]],
                   basename_index: dict[str, list[Path]]) -> DocReport:
    doc = str(path.relative_to(REPO_ROOT))
    text = path.read_text(encoding="utf-8")
    report = DocReport(doc=doc)

    citations, citation_issues = check_citations(text, doc, basename_index)
    tally, tally_issues = check_tally(text, doc)
    rows, timeline_issues = check_timeline(text, doc, history)

    report.checked = {
        "citations": citations,
        "findings_labelled": sum(tally.values()),
        "timeline_rows": rows,
    }
    report.issues = citation_issues + tally_issues + timeline_issues
    return report


def _changed_audit_docs(ref: str) -> list[Path]:
    """Audit documents touched relative to ref, including staged and unstaged work."""
    import subprocess

    names: set[str] = set()
    for cmd in (
        ["git", "diff", "--name-only", ref, "--", "docs/audits"],
        ["git", "diff", "--name-only", "--cached", "--", "docs/audits"],
        ["git", "diff", "--name-only", "--", "docs/audits"],
        ["git", "ls-files", "--others", "--exclude-standard", "--", "docs/audits"],
    ):
        try:
            out = subprocess.run(
                cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=False, timeout=30
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if out.returncode == 0:
            names.update(line.strip() for line in out.stdout.splitlines() if line.strip())
    return sorted({REPO_ROOT / n for n in names if n.endswith(".md")})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--docs", nargs="*", help="Specific documents (default: all of docs/audits).")
    parser.add_argument(
        "--changed-since",
        metavar="REF",
        help="Only check audit documents modified relative to REF (plus staged/unstaged). "
             "This is the gate mode: a historical audit describes a past repo state, so a "
             "citation that has since gone stale is not a defect in that document.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    if args.docs:
        paths = [Path(d) if Path(d).is_absolute() else REPO_ROOT / d for d in args.docs]
    elif args.changed_since:
        paths = _changed_audit_docs(args.changed_since)
    else:
        paths = sorted(DEFAULT_DOC_DIR.glob("*.md")) if DEFAULT_DOC_DIR.exists() else []
    paths = [p for p in paths if p.is_file() and p.name != "INDEX.md"]

    if not paths:
        print("No audit documents to check.")
        return 0

    history = load_history_entries()
    basename_index = _iter_repo_files()
    reports = [audit_document(p, history, basename_index) for p in paths]
    issues = [i for r in reports for i in r.issues]

    if args.as_json:
        print(json.dumps({
            "documents": [
                {"doc": r.doc, "checked": r.checked,
                 "issues": [i.__dict__ for i in r.issues]}
                for r in reports
            ],
            "issue_count": len(issues),
        }, indent=2))
        return 1 if issues else 0

    totals = {
        "citations": sum(r.checked.get("citations", 0) for r in reports),
        "findings": sum(r.checked.get("findings_labelled", 0) for r in reports),
        "timeline_rows": sum(r.checked.get("timeline_rows", 0) for r in reports),
    }
    print(
        f"Checked {len(paths)} audit document(s): "
        f"{totals['citations']} citations, {totals['findings']} labelled findings, "
        f"{totals['timeline_rows']} timeline rows."
    )
    if not issues:
        print("Audit claims OK")
        return 0
    print(f"\n{len(issues)} issue(s):")
    for issue in issues:
        print(f"  {issue.render()}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
