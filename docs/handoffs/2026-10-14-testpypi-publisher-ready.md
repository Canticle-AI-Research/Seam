---
handoff_id: 2026-10-14-testpypi-publisher-ready
supersedes: 2026-10-14-branch-recovery-closeout
handoff_status: superseded
history: HISTORY#676
---

# TestPyPI publisher qualified; protected admission and upload next

The operator configured the GitHub Actions secret `TEST_PYPI` and authorized
TestPyPI publication. Licensing is finished in PR #286. Branch recovery
closeout PR #305 is merged at df1c66d; its remaining recovery lanes and baseline
conditions remain as recorded in the [predecessor](2026-10-14-branch-recovery-closeout.md).

The dedicated [publisher](../../.github/workflows/publish-testpypi.yml) accepts
only an exact current protected-main Suite name/version/SHA. It rebuilds and
checks exact wheel/sdist manifest membership, scans source and archives, binds
an independently transferred receipt hash, and exposes the token only to its
TestPyPI upload step. Public JSON readback checks exact filenames, sizes and
SHA256; restricted downloads feed fresh wheel/source installs with dependencies
from explicit trusted PyPI. See [operator instructions](../TESTPYPI.md).

Independent successor review passes after receipt-binding, version-endpoint
schema and final-main verification repairs; initial findings are preserved in
local review evidence. The witnessed publisher red/green cycle is recorded in
bounded session state. `pytest tests/audit/test_testpypi_release.py
 tests/audit/test_suite_manifest_drift.py -q` passes 73 cases; the publisher suite
contains 33 cases. Both explicit local artifacts pass strict Twine, manifest
and archive scans, eight `tests/package/smoke_installed_suite.py` cases per
format, and `uv pip check`. These are preparation results, not an upload claim.

Next: signed scoped commit, protected PR required checks and independent
SessionEnd qualification, merge, then dispatch `publish-testpypi.yml` for
`seam-suite` version `2.4.1rc1` at the full merged-main SHA. Record the actual
Actions run, public registry hashes and fresh downloaded-install results.
Stop on a name/version collision or failed upload/readback; do not replace
existing files. Production PyPI, private SDK, paid providers and licensing
changes are outside this authorization. Embedding batching R2/issue #292 is
the next runtime recovery after this publishing task.
