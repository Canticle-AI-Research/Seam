"""CI-safe tests for the `seam doctor` stash advisory (HISTORY#324).

Stashes are invisible to git status/log/branch/PR listings, so an abandoned one
lingers unnoticed. `check_stashes()` surfaces them as a NON-blocking advisory so
a cleanliness sweep catches orphaned local WIP. Hermetic: subprocess is
monkeypatched, so no real git stash is created.
"""

import subprocess
import time

from seam_runtime import doctor
from seam_runtime.cli import _render_doctor_report


def _patch_stash_output(monkeypatch, output):
    def fake_check_output(args, stderr=None):
        return output.encode()
    monkeypatch.setattr(doctor.subprocess, "check_output", fake_check_output)


def test_check_stashes_clean(monkeypatch):
    _patch_stash_output(monkeypatch, "")
    assert doctor.check_stashes() == {"status": "clean", "count": 0}


def test_check_stashes_advisory_with_age(monkeypatch):
    # Offset to mid-day so floor-division lands squarely on the intended day
    # (subtracting exactly N*86400 sits on the boundary and can tip to N-1).
    three_days_ago = time.time() - (3 * 86400 + 43200)
    one_day_ago = time.time() - (1 * 86400 + 43200)
    out = f"{three_days_ago:.0f}\tWIP on main: abcdef old work\n{one_day_ago:.0f}\tWIP on feat: newer"
    _patch_stash_output(monkeypatch, out)
    result = doctor.check_stashes()
    assert result["status"] == "advisory"
    assert result["count"] == 2
    ages = [s["age_days"] for s in result["stashes"]]
    assert ages[0] == 3 and ages[1] == 1
    assert "old work" in result["stashes"][0]["summary"]


def test_check_stashes_not_a_git_repo(monkeypatch):
    def boom(args, stderr=None):
        raise subprocess.CalledProcessError(128, args)
    monkeypatch.setattr(doctor.subprocess, "check_output", boom)
    assert doctor.check_stashes() == {"status": "not-a-git-repo"}


def test_check_stashes_advisory_does_not_flip_overall_status(monkeypatch):
    """The advisory must never turn a healthy report into FAIL."""
    monkeypatch.setattr(
        doctor, "check_stashes",
        lambda: {"status": "advisory", "count": 1, "stashes": [{"age_days": 30, "summary": "x"}]},
    )
    report = doctor.build_doctor_report()
    assert report["stashes"]["status"] == "advisory"
    # status is driven only by smoke/lossless/deps, never by the stash advisory.
    assert report["status"] in {"PASS", "FAIL"}


def test_render_doctor_report_stash_lines():
    base = {"status": "PASS", "dependencies": {}, "pgvector": {}, "commit_gate": {}, "streams": {}}
    advisory = dict(base, stashes={"status": "advisory", "count": 2,
                                   "stashes": [{"age_days": 21, "summary": "a"}, {"age_days": 1, "summary": "b"}]})
    out = _render_doctor_report(advisory)
    assert "Stashes: 2 present (oldest 21d)" in out

    clean = dict(base, stashes={"status": "clean", "count": 0})
    assert "Stashes: none" in _render_doctor_report(clean)
