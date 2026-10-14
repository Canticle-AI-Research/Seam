# Suite release-candidate readiness

[Report registry](INDEX.md) · [Release flow](../RELEASE_FLOW.md)

Recorded by HISTORY#667, from protected-main base
`607ac3089c58bfc033d9442762c40505f0ab8d2b`. This is installation and release
preparation for the first-launch Suite, not full operator-product acceptance.
It carries useful remaining package/release/MCP work from PR #266 without
importing its colliding history or superseded licensing texts.

## Supported installation and release behavior

Plain `seam-suite` now includes TUI, HTTP client, and server dependencies.
Compatible `dash` and `server` extras remain; Chroma, neural embeddings,
additional vector backends, and benchmark providers stay opt-in. Doctor checks
the actual default dependency contract and accepts both supported multipart
import namespaces. Dashboard repair guidance supports a reviewed checkout
before an index release exists.

Release workflows and artifact identity use canonical three-component Python
versions, including `2.4.1rc1`, rejecting aliases, epochs, local versions, and
mismatches. Existing operator, protected-head, checksum, and artifact controls
remain. CI verifies separately installed wheel and sdist. Neither GitHub
release workflow uploads to a package index.

The MCP manifest now names the current Suite under the canonical organization,
with a versioned stdio launcher and matching README ownership marker. Preflight
requires a real matching production PyPI release before registry publication.
Preparing metadata does not register the server.

## Exact membership and TestPyPI boundary

Only dependency reporting and dashboard repair text change runtime bytes.
The manifest keeps the same reviewed implementation membership, refreshes those
two hashes, and records source base plus explicit old/new delta and exact
inventory digest. Historical license files and personal-use terms are unchanged;
the paid SDK is absent. Independent source and installed-package review supports
the owner's instruction to complete the TestPyPI-first candidate. The
private-upload tripwire is then removed in reviewed metadata, and the actual
archives are rebuilt and reverified. Earlier private-classifier archives remain
local and must not be substituted for the final files.

`tools.release.verify_suite_manifest` checks source, staged bytes, and exact
archives. It rejects unsafe/private members, source hash drift, mismatched
archive membership and stale legal documents without changing permission.
Required hygiene and matching unsuppressed local gates enforce source parity;
package CI checks the archives. This makes future drift a failing check.

Final external wheel and sdist independently contain the manifest's exact
implementation and all seven source-identical legal documents. Both fresh
installations pass eight smoke tests: entrypoints, dependency/Doctor status,
TUI mount, packaged HTTP assets, authenticated HTTP write/recall and token
denial, CLI persistence/provenance across processes, and actual MCP
initialize/list/ingest/search/restart. Dependency consistency, strict Twine
validation, archive scanning, and lock verification pass. Exact commands,
times, fingerprints, source changes and artifact hashes are in the evidence
record below.

The initial broader runtime run lacked optional sentence-transformers and
retained two assertions for the former dependency list. Those assertions are
updated for the intended default contract; embedding dependencies and the exact
pinned model are provisioned outside source; the complete `test_seam_all/`
non-external rerun exits zero. No failed run is
treated as a benchmark success. Required CI and exact-state independent
qualification must still pass on the pushed candidate before protected merge.

No TestPyPI credentials are configured in this environment. Repository secret
inventory access also returns an integration-level 403; GitHub access is not
TestPyPI project ownership. Registry lookups return 404 for Suite on PyPI,
TestPyPI and the new MCP namespace. No test upload, production upload, paid
provider call, or live registration is claimed. Publishing access and fresh
downloaded-install verification remain concrete next steps. Full browser
graph/glassbox and hosted-product acceptance remain explicit known gaps in
[surface status](../status/surfaces.md).

## Branch cleanup

The owner authorized removing branches no longer needed. An independent audit
distinguished real main reachability and verified squash-patch preservation
from a merely closed PR. Root rechecked live tips, open PRs and ownership, then
deleted the following branches with per-ref exact-SHA leases and verified their
absence:

| Repository | Deleted completed branch |
| --- | --- |
| Seam | `codex/s8-r2-spec` |
| Seam | `hackerone` |
| Cantlicle | `agent/canticle-mfa-rls` |
| Cantlicle | `agent/canticle-totp-mfa` |
| Cantlicle | `agent/google-ai-pro-feed-ad` |
| Cantlicle | `agent/publish-free-broad-profile` |
| Cantlicle | `agent/research-page-redesign` |
| Cantlicle | `agent/work-about-profile-redesign` |
| Cantlicle | `docs/documentation-expansion-20261002` |
| Cantlicle | `docs/seam-subscription-workspace` |
| Cantlicle | `fix/suite-license-copy-20261014` |

Unique/open work and preservation branches remain intact. The scanner now marks
unique CLOSED and MERGED PR branches for REVIEW instead of treating PR state
as deletion proof. PR #266's useful functionality is being superseded by this
reviewed successor; close/delete its branch only after protected integration
and an explicit disposition of its older proposal/history. Website PR #29's
remaining downloads work is being reconciled separately, with deployment and
live verification still distinct. The manual GitHub About reminder remains
assigned and pinned as issue #287.

## Evidence manifest

- `docs/audits/evidence/2026-10-14-suite-release/verification.json` — SHA-256: `d3b3cabd70bb08af910d1b38c889e6b43c43f4c8ad4f47481b668ba1526858d2`

This bounded record identifies exact external archive hashes, red/green
fingerprints, scoped installed checks, branch preservation and registry
observations. Raw console logs and environments remain outside source.
