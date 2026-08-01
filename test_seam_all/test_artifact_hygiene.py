"""Guard: test fixtures must not strand SQLite sidecar files.

HISTORY#282 established the rule - a transient runtime must be CLOSED before its
database is deleted, because SQLite only drops the ``-wal``/``-shm`` sidecars on a
clean close. Linux happily unlinks an open file, so a missed close is invisible
there and only surfaces on the Windows leg as WinError 32.

Two suites never adopted the rule and leaked for months:

* ``SeamTests`` -> 7,051 orphaned pairs under ``test_seam/`` (858 MB)
* ``PgVectorAdapterTests`` -> 118 orphaned files at the REPO ROOT (5.5 MB)

Both were invisible because ``.gitignore`` carries a blanket ``*.db-wal`` /
``*.db-shm``, so ``git status`` never reported them. HISTORY#322 relocated the
files that had already accumulated but did not change the code that creates
them, so they came straight back - the fix expired because nothing checked it.

These tests are that check. They exercise the REAL fixtures rather than
re-implementing the cleanup, so they fail if a future edit drops the close.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

# Import the MODULE, not the TestCase classes. Binding `SeamTests` into this
# module's namespace makes pytest collect that whole suite a second time here
# (189 extra tests per run), so the fixtures are reached via attribute access.
from test_seam_all import test_seam as _suite

REPO_ROOT = Path(__file__).resolve().parent.parent

# Every directory a suite has ever written a transient SQLite database into,
# paired with the basename prefix that suite uses.
ARTIFACT_GLOBS: tuple[tuple[Path, str], ...] = (
    (REPO_ROOT, "test_seam_*.db*"),
    (REPO_ROOT, "test_pgvector_*.db*"),
    (REPO_ROOT / "test_seam", "test_seam_*.db*"),
    (REPO_ROOT / "test_seam", "test_pgvector_*.db*"),
    # Where HISTORY#322 said pgvector output belongs, and where it now goes.
    (REPO_ROOT / "test_seam" / "pgvector", "test_pgvector_*.db*"),
)


def _artifacts() -> set[Path]:
    """Every transient test database artifact currently on disk."""
    found: set[Path] = set()
    for directory, pattern in ARTIFACT_GLOBS:
        if directory.is_dir():
            found.update(path.resolve() for path in directory.glob(pattern))
    return found


def _run_fixture_lifecycle(case: unittest.TestCase, body) -> None:
    """Drive setUp/body/tearDown and registered cleanups like unittest."""
    try:
        case.setUp()
    except BaseException:
        case.doCleanups()
        raise
    try:
        try:
            body(case)
        finally:
            case.tearDown()
    finally:
        case.doCleanups()


class ArtifactHygieneTests(unittest.TestCase):
    """A fixture that opens a runtime must leave nothing behind."""

    def _assert_no_new_artifacts(self, case: unittest.TestCase, body) -> None:
        before = _artifacts()
        _run_fixture_lifecycle(case, body)
        leaked = sorted(path.name for path in _artifacts() - before)
        self.assertEqual(
            leaked,
            [],
            "fixture stranded SQLite artifacts - the runtime was not closed "
            "before its database was deleted (HISTORY#282). Leaked: "
            f"{leaked}",
        )

    def test_seam_tests_fixture_strands_nothing(self) -> None:
        # Writing is what forces SQLite to materialise the -wal/-shm pair; a
        # fixture that only opens a connection would pass vacuously.
        def body(case) -> None:
            runtime = case.make_runtime(case.db_path)
            runtime.persist_ir(
                runtime.compile_nl("Artifact hygiene guard writes one claim.")
            )

        self._assert_no_new_artifacts(
            _suite.SeamTests("test_exact_pack_round_trips"), body
        )

    def test_fixture_lifecycle_runs_cleanups_on_success_and_failure(self) -> None:
        events: list[str] = []

        class SuccessfulCase(unittest.TestCase):
            def setUp(self) -> None:
                self.addCleanup(events.append, "success-cleanup")

            def tearDown(self) -> None:
                events.append("success-teardown")

        _run_fixture_lifecycle(
            SuccessfulCase(), lambda case: events.append("success-body")
        )
        self.assertEqual(
            events,
            ["success-body", "success-teardown", "success-cleanup"],
        )

        events.clear()

        class FailingSetupCase(unittest.TestCase):
            def setUp(self) -> None:
                self.addCleanup(events.append, "setup-failure-cleanup")
                raise RuntimeError("setUp failed")

        with self.assertRaisesRegex(RuntimeError, "setUp failed"):
            _run_fixture_lifecycle(FailingSetupCase(), lambda case: None)
        self.assertEqual(events, ["setup-failure-cleanup"])

        events.clear()

        class FailingTearDownCase(unittest.TestCase):
            def setUp(self) -> None:
                self.addCleanup(events.append, "teardown-failure-cleanup")

            def tearDown(self) -> None:
                raise RuntimeError("tearDown failed")

        with self.assertRaisesRegex(RuntimeError, "tearDown failed"):
            _run_fixture_lifecycle(FailingTearDownCase(), lambda case: None)
        self.assertEqual(events, ["teardown-failure-cleanup"])

    def test_pgvector_tests_fixture_strands_nothing(self) -> None:
        def body(case) -> None:
            runtime = case.make_runtime(case.db_path)
            runtime.persist_ir(
                runtime.compile_nl("Artifact hygiene guard writes one claim.")
            )

        self._assert_no_new_artifacts(
            _suite.PgVectorAdapterTests("test_pgvector_adapter_indexes_records"), body
        )

    def test_working_tree_carries_no_stray_artifacts(self) -> None:
        """The accumulated-junk check.

        Catches artifacts left by any path the two fixture tests above do not
        cover - a benchmark runner, a crashed process, a new suite. Scoped to the
        transient ``test_seam_*`` / ``test_pgvector_*`` prefixes so it never
        objects to a deliberately retained database.
        """
        stray = sorted(path.name for path in _artifacts())
        self.assertEqual(
            stray,
            [],
            f"{len(stray)} stray test database artifact(s) on disk. These are "
            "hidden from `git status` by the blanket *.db-wal / *.db-shm ignore "
            "rules, so they accumulate silently. Delete them and fix whatever "
            f"fixture stranded them. First 10: {stray[:10]}",
        )

    def test_shipped_python_carries_no_windows_user_profile_path(self) -> None:
        pattern = re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+\\", re.IGNORECASE)
        shipped_python = [REPO_ROOT / "seam.py", *sorted((REPO_ROOT / "seam_runtime").rglob("*.py"))]
        leaked = [
            path.relative_to(REPO_ROOT).as_posix()
            for path in shipped_python
            if pattern.search(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(
            leaked,
            [],
            "shipped Python contains an absolute Windows user-profile path",
        )


if __name__ == "__main__":
    unittest.main()
