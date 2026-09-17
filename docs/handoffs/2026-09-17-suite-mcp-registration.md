---
handoff_id: 2026-09-17-suite-mcp-registration
supersedes: 2026-09-17-product-readiness
handoff_status: current
history: HISTORY#649
---

# Suite MCP registration preparation

The operator added MCP upload/registration to the existing packaging and
website repair. MCP ships in `seam-suite` through `seam-mcp`; the unfinished
`seam-api` product is not a dependency. The readiness definitions from
[HISTORY#648's handoff](2026-09-17-product-readiness.md) remain in force:
usable local core, unfinished Suite operator interfaces, API product not
started. The earlier package repair and its open conditions remain in
[HISTORY#647's handoff](2026-09-17-package-release-repair.md).

## Registry findings and change

The official registry returned the active legacy
`io.github.BlackhatShiftey/seam-runtime` 1.3.1 entry, whose PyPI release is yanked
with reason `broken`. The canonical organization namespace returned no Suite
entry. GitHub reported the operator's organization membership active/admin.
No registry authentication, new registration, old-entry deprecation, Python
upload, protected merge or production website deployment was performed.

`server.json` now prepares `io.github.Canticle-AI-Research/seam-suite` 2.4.1rc1
and the canonical repository URL. It supplies `--from` before the client's
inserted versioned package spec and `seam-mcp` after it, avoiding the old
duplicate executable/package arguments. README includes the required ownership
marker. The optional pgvector DSN is removed from the default registry launch;
SQLite works without that optional dependency or Docker setup.

`tools/release/verify_mcp_registry.py` checks local identity/command agreement
and, on explicit `--published`, the existing private-upload tripwire and exact
production PyPI metadata, ownership marker, non-yanked wheel/sdist identity,
file host and hashes. It never publishes. The new manual workflow requires
protected main, an explicit configured operator, a first run, and an existing
public release, then validates/publishes with a checksum-pinned official CLI
and OIDC and reads the exact record back. Workflow environment protection and
publication have not been exercised. It does not upload the Python package.

The [MCP guide](../MCP_REGISTRY.md) documents local setup, publication order,
authentication and legacy migration. Wiki, release docs, status and ledger
route to it. The website's MCP example now uses an installed absolute
`seam-mcp` path and default SQLite, without implying API-product readiness or
automatic Docker setup. Website PR #29 remains draft and needs owner browser
review; the new documentation link requires the SEAM PR to merge first.

## Verification

- `python -m pytest -q tests/audit/test_mcp_registry_release.py`: the new
  checks failed before implementation and passed after it. The root session
  state records the witnessed red/green commands, times and fingerprints.
- The combined focused run of that module, `test_mcp_stdio_smoke.py`,
  `test_mcp_tools_call_smoke.py` and `test_github_issue_release_config.py`
  passed. Collection and scoped Ruff passed. This is not a full-suite pass.
- Official `mcp-publisher` v1.8.1 `validate server.json` passed. Its
  `validate --help` dispatcher reports an unknown command despite the actual
  validation command working; do not mistake that help quirk for a missing
  validation capability or a publication result.
- Fresh wheel/sdist builds passed strict Twine checks and the artifact scanner.
  Read-only `unzip -p` confirmed the built wheel name/version and ownership
  marker. A generic Python inspection snippet was rejected by the local
  deletion guard; the read-only archive command completed the inspection.
- In an isolated `uvx --no-cache` installation using the local wheel as
  `--find-links`, the versioned registry command started, reported 2.4.1rc1,
  ingested synthetic text, searched it, and retrieved it after another process
  start. Credentials/provider settings were excluded and only an external
  disposable SQLite database was used. This qualifies the local command, not
  a PyPI installation or every client implementation.
- Website `node --test tests/downloads-release.test.js` and
  `python3 -m unittest discover -s tests -p test_package_downloads.py` passed
  after the MCP copy/configuration update. No new wording-only tests were added.

External evidence, built artifacts, package hashes, publisher checksum, local
test database, test-first records and closeout receipts live under
`/home/terrabyte/LLM-Logs/codex/releases/20260917-seam-packages/mcp/`.
The canonical continuity protocol and independent receipt must be reconciled
on the final exact head before ending the session.

## Remaining work

`--published` currently stops with `Private :: Do Not Upload`. The current
Suite contains readable reserved material and has no approved public artifact
membership or established TestPyPI publisher. Finish that review and qualify
TestPyPI installation before a production package and MCP registration. No
placeholder registry/package entry or private-SDK publication is an acceptable
substitute. The website selector still accepts stable releases only; this rc
candidate does not become a download through the new maturity wording.

The prior cumulative package receipt remains **NOT_QUALIFIED / TDD_UNPROVEN**
for its installer README and dashboard wording paths. The documentation-only
readiness delta received **QUALIFIED**, which does not clear the cumulative
package condition. Keep PR #266 and website PR #29 draft for DeepSeek. Preserve
the previously recorded audit/website-suite failures and email-worker failure;
required CI checks must be observed on the final pushed heads. No previous
green result qualifies a later head automatically.

Remove both clean task worktrees after pushing and preserving snapshots and
receipts. Leave the unrelated primary and linked worktrees untouched; their
dirty state remains recorded in the predecessor handoffs.
