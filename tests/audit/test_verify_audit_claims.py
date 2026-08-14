"""Regressions for the audit-report claim gate.

The gate exists because HISTORY#560's report was accurate where it measured and
wrong where it summarized: it miscounted its own MEDIUM findings (15 claimed, 17
labelled), cited a line past the end of a 13-line test file, and misdated one
timeline row out of 559. Each test below pins one of those real defects plus the
false-positive shape that the first cut of the gate produced.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from tools.docs.verify_audit_claims import (
    check_citations,
    check_tally,
    check_timeline,
    resolve_citation,
)


@pytest.fixture()
def basename_index() -> dict[str, list[Path]]:
    from tools.docs.verify_audit_claims import _iter_repo_files

    return _iter_repo_files()


def test_citation_past_eof_is_reported(tmp_path: Path, basename_index):
    """The real HISTORY#560 defect: `test_webui_chat_memory_controls.py:6-14` on a 13-line file."""
    target = Path("tests/audit/test_verify_audit_claims.py")
    total = sum(1 for _ in (Path(__file__)).open(encoding="utf-8"))
    text = f"see `{target.name}:1-{total + 500}` for detail"
    _, issues = check_citations(text, "d.md", basename_index)
    assert len(issues) == 1
    assert issues[0].kind == "citation"
    assert "has" in issues[0].message


def test_citation_in_range_is_clean(basename_index):
    text = "see `test_verify_audit_claims.py:1-5` for detail"
    count, issues = check_citations(text, "d.md", basename_index)
    assert count == 1
    assert issues == []


def test_missing_cited_file_is_reported(basename_index):
    text = "see `no_such_module_xyzzy.py:3` for detail"
    _, issues = check_citations(text, "d.md", basename_index)
    assert len(issues) == 1
    assert "does not exist" in issues[0].message


def test_tally_mismatch_is_reported():
    """15 claimed vs 17 labelled -- the exact HISTORY#560 arithmetic error."""
    text = "The audit found **fifteen MEDIUM findings** overall.\n\n" + "\n".join(
        f"**F-{n} — MED · thing{n}**\nbody" for n in range(1, 18)
    )
    actual, issues = check_tally(text, "d.md")
    assert actual["MEDIUM"] == 17
    assert len(issues) == 1
    assert "17 MEDIUM" in issues[0].message


def test_tally_agreement_is_clean():
    text = "The audit found **three MEDIUM findings**.\n\n" + "\n".join(
        f"**F-{n} — MED · thing{n}**\nbody" for n in range(1, 4)
    )
    _, issues = check_tally(text, "d.md")
    assert issues == []


def test_per_subsystem_breakdown_is_not_a_whole_document_claim():
    """Guards the first cut's false positive: dashboard rows are partial by construction."""
    text = (
        "Summary paragraph with no global count.\n\n"
        + "\n".join(f"**F-{n} — MED · thing{n}**\nbody" for n in range(1, 18))
        + "\n\nCore storage   good — 1 MED (F-10), 3 LOW\n"
        "Retrieval      needs work — 5 MED, 2 LOW\n"
    )
    _, issues = check_tally(text, "d.md")
    assert issues == []


def test_timeline_date_mismatch_is_reported():
    """The real #405 defect: row says 2026-07-17, HISTORY records 2026-07-16T23:08:58Z."""
    history = {405: ("2026-07-16T23:08:58Z", "done")}
    text = "| # | date | status | summary |\n| #405 | 2026-07-17 | done | thing |"
    rows, issues = check_timeline(text, "d.md", history)
    assert rows == 1
    assert len(issues) == 1
    assert "2026-07-16T23:08:58Z" in issues[0].message


def test_timeline_matching_row_is_clean():
    history = {405: ("2026-07-16T23:08:58Z", "done")}
    text = "| #405 | 2026-07-16 | done | thing |"
    _, issues = check_timeline(text, "d.md", history)
    assert issues == []


def test_timeline_status_mismatch_is_reported():
    history = {12: ("2026-04-17T00:00:00Z", "done")}
    text = "| #12 | 2026-04-17 | deferred | thing |"
    _, issues = check_timeline(text, "d.md", history)
    assert len(issues) == 1
    assert "status" in issues[0].message


def test_timeline_duplicate_and_gap_are_reported():
    history = {n: ("2026-04-17T00:00:00Z", "done") for n in (1, 2, 3)}
    text = "| #1 | 2026-04-17 | done | a |\n| #1 | 2026-04-17 | done | a |\n| #3 | 2026-04-17 | done | c |"
    _, issues = check_timeline(text, "d.md", history)
    kinds = " ".join(i.message for i in issues)
    assert "more than once" in kinds
    assert "missing" in kinds


def test_timeline_entry_absent_from_history_is_reported():
    text = "| #9999 | 2026-04-17 | done | ghost |"
    _, issues = check_timeline(text, "d.md", {1: ("2026-04-17T00:00:00Z", "done")})
    assert len(issues) == 1
    assert "no such entry" in issues[0].message


def test_documents_without_findings_or_timeline_are_clean(basename_index):
    text = "A prose note with no findings, no rows, and no citations."
    assert check_tally(text, "d.md") == ({}, [])
    assert check_timeline(text, "d.md", {}) == (0, [])
    assert check_citations(text, "d.md", basename_index) == (0, [])


def test_resolve_citation_finds_repo_relative_and_bare_names(basename_index):
    assert resolve_citation("tools/docs/verify_audit_claims.py", basename_index) is not None
    assert resolve_citation("verify_audit_claims.py", basename_index) is not None
    assert resolve_citation("definitely_not_here_xyzzy.py", basename_index) is None
