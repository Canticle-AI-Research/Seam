---
handoff_id: 2026-09-08-package-names-testpypi-candidate
supersedes: 2026-09-07-s8-protected-main-suite-next
handoff_status: current
history: HISTORY#642
---

# Package names prepared; TestPyPI upload blocked

## Scope and current candidate

The operator selected `seam-suite` for self-hosted TUI, benchmark glassbox and
browser graph dashboard; SEAM Client for the paid API and all-in-one WebUI;
and private `seam-sdk` for paying users. Existing `seam-client` remains the
Python HTTP client. Production PyPI must remain untouched until TestPyPI
qualification and a separate production decision.

This branch starts at protected `db2bca7`. Root metadata and lock identify
`seam-suite` 2.4.1rc1; existing imports, commands, dependencies, licenses and
private-upload guard remain. MCP reports installed Suite metadata with legacy
runtime fallback. GitHub release artifact expectations match the new name,
while their existing SemVer version gate still rejects this PEP 440 candidate.
This records a source candidate, not a merged or uploaded distribution.

## Verification

`.venv/bin/python -m pytest tests/audit/test_mcp_stdio_smoke.py
 tests/audit/test_github_issue_release_config.py -q` passed 47 cases after four
new metadata-handshake failures established the red phase. Independent code
assurance reran the same selection successfully. `uv lock --check --offline`,
scoped Ruff, and diff checks passed. The README's initial new-name VCS command
against old main was caught by docs review and replaced with checkout-local
installation instructions.

`uv build --out-dir /workspace/scratch/191c1eb6d024/suite-build` produced the
wheel and sdist. Strict Twine metadata checks and the existing private-artifact
scanner passed for both exact files. SHA-256 values:

- `seam_suite-2.4.1rc1-py3-none-any.whl`:
  `238c4678e49ac339538fe7bdecefe2f69b96089f211970eeb007e92cd5644262`
- `seam_suite-2.4.1rc1.tar.gz`:
  `b02a2424703f9dfadcce96fdd6261546b90b9101ed5f9c45075402c52d94e9f2`

The exact wheel with `[server,dash]` installed into a fresh external Python
3.12 environment. `uv pip check` passed. From outside the source tree, installed
metadata and MCP version were 2.4.1rc1; CLI, dashboard, server and benchmark
help passed. Separate CLI processes remembered and retrieved a unique test
fact from an isolated database. This is local packaging smoke evidence, not
full Suite UI acceptance, a legacy upgrade test, or hosted qualification.

## Blockers and next action

Follow [TestPyPI procedure](../TESTPYPI.md). No TestPyPI token, user publishing
configuration or authenticated browser session was present; no login or upload
was attempted. Root retains `Private :: Do Not Upload` because exact public
Suite membership/notices remain unresolved in L1. TestPyPI is public; changing
the destination cannot waive that boundary. Private SDK source was not copied
or uploaded. Source/owner recovery for the public client remains separate.

First review the named candidate and its exact archive membership, resolve
Suite public eligibility, and configure narrowly scoped TestPyPI publishing
access. Rebuild/reverify if approved membership or metadata changes; use the
explicit test endpoint and exact approved hashes. Do not dispatch existing
production/GitHub release workflows or delete old releases.

S8 remains complete at its existing baseline. S9/S10 and operator acceptance
remain open; no benchmark score or runtime retrieval behavior changed. The
older user-owned laptop worktrees described by the predecessor remain outside
this fresh checkout. No laptop database or credentials were accessed.
