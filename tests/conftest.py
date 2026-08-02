"""Shared pytest fixtures for the SEAM test suite.

Ambient ``SEAM_PGVECTOR_DSN`` isolation: an operator shell that exports the
pgvector DSN (the documented local dev setup) otherwise leaks into every
persist-path test, which then routes to the optional Docker pgvector backend
and fails with a raw ``connection refused`` when that container is down. Tests
that genuinely exercise the real adapter opt in with ``@pytest.mark.external``
and self-gate via ``skipif``; everything else must run on the default SQLite
vector backend so local runs are deterministic and match CI (which sets no DSN).
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_ambient_pgvector_dsn(request, monkeypatch):
    """Route non-``external`` tests to SQLite by hiding any ambient pgvector DSN."""
    if request.node.get_closest_marker("external") is None:
        monkeypatch.delenv("SEAM_PGVECTOR_DSN", raising=False)


# --- strict no-skip enforcement ----------------------------------------------
#
# A skip must never silently mean "this test never ran". A skip is allowed ONLY
# when it is genuinely unavoidable in the current environment - the wrong OS, a
# deliberately-absent optional extra, or a checkout without origin/main. Every
# such reason is enumerated below WITH its justification. Any other skip
# (notably a service-gated test whose service simply was not started, e.g.
# ``PGVECTOR_TEST_DSN not set``) fails the session.
#
# Service-gated tests carry ``@pytest.mark.external`` and are DESELECTED with
# ``-m "not external"`` in jobs without that service, and RUN (with the DSN set)
# in the job that provides it - so they never reach the skip path silently.
#
# Default ON; opt out for ad-hoc local runs with ``SEAM_STRICT_NO_SKIP=0``.
_ALLOWED_SKIP_SUBSTRINGS = (
    "Linux",          # Linux-only behavior tests (run on the Linux CI leg)
    "Windows",        # Windows-flaky subprocess tests (skipped on the Windows leg)
    "win32",
    "fastapi server extra is not installed",  # optional [server] extra absent
    "bash is required",                       # pre-commit hook smoke needs bash
    "cannot determine merge-base",            # shallow checkout without origin/main
)

_observed_skips: list[tuple[str, str]] = []


def _strict_no_skip_enabled() -> bool:
    return os.environ.get("SEAM_STRICT_NO_SKIP", "1").strip().lower() not in {"0", "false", "no", "off"}


def _skip_is_allowed(reason: str) -> bool:
    return any(sub in reason for sub in _ALLOWED_SKIP_SUBSTRINGS)


def pytest_runtest_logreport(report):
    # xfail (expected failure) also reports as "skipped" but is a deliberate
    # outcome, not a test that silently never ran - leave it alone.
    if report.skipped and not hasattr(report, "wasxfail"):
        # report.longrepr for a skip is (path, lineno, "Skipped: <reason>")
        reason = ""
        longrepr = getattr(report, "longrepr", None)
        if isinstance(longrepr, tuple) and len(longrepr) == 3:
            reason = str(longrepr[2])
        else:
            reason = str(longrepr)
        _observed_skips.append((report.nodeid, reason))


def pytest_sessionfinish(session, exitstatus):
    if not _strict_no_skip_enabled():
        # Disabling enforcement must never be silent: an unannounced opt-out
        # looks identical to a clean run, so a CI lane (or an agent) that
        # inherits SEAM_STRICT_NO_SKIP=0 would report green while tests were
        # quietly not running.
        unexplained = [(nid, r) for nid, r in _observed_skips if not _skip_is_allowed(r)]
        if unexplained:
            reporter = session.config.pluginmanager.get_plugin("terminalreporter")
            if reporter is not None:
                reporter.write_sep(
                    "=",
                    f"STRICT NO-SKIP DISABLED (SEAM_STRICT_NO_SKIP=0): "
                    f"{len(unexplained)} unexplained skip(s) NOT enforced",
                    yellow=True,
                )
                for nodeid, reason in unexplained:
                    reporter.write_line(f"  SKIPPED {nodeid}: {reason}")
        return
    offenders = [(nid, r) for nid, r in _observed_skips if not _skip_is_allowed(r)]
    if not offenders:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_sep("=", "STRICT NO-SKIP: unexplained skips (start the service or mark @external)", red=True)
        for nodeid, reason in offenders:
            reporter.write_line(f"  SKIPPED {nodeid}: {reason}")
        reporter.write_line("  Set SEAM_STRICT_NO_SKIP=0 only for ad-hoc local runs; CI must not skip these.")
    session.exitstatus = 1
