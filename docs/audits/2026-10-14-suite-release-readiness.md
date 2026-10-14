# Suite release-candidate readiness

[Report registry](INDEX.md) · [Release flow](../RELEASE_FLOW.md)

Recorded by HISTORY#667, with exact-closeout correction at HISTORY#668, from protected-main base
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

## Exact-closeout correction

The first exact-state request received an immutable NOT_QUALIFIED verdict:
the prefix classifier treated installer README documentation as executable code,
and queued cycle references omitted the two shell gates. The source classifier
now excludes plain Markdown/reStructuredText while retaining real scripts and
code as TDD-governed. Regression tests exercise the actual SessionEnd CLI and
mixed documentation/script changes. Historical requests remain readable under
their exact original stricter classification without rewriting or upgrading
their verdicts; executable omissions still fail. The witnessed original shell
gate-presence/parity cycle is recorded with its actual implementation paths.
No package, license or reviewed archive bytes change in this correction.

The extended `tests/` run completed with failures in unchanged branding browser
exports and tokenizer-dependent cost-report tests. It is not a full-suite pass;
these environment-dependent results are retained alongside the successful
supported runtime and installed-package checks. Required pushed-head checks
and a successor exact-state receipt remain mandatory.

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

- `docs/audits/evidence/2026-10-14-suite-release/verification.json` — SHA-256: `b6ecb435b0b30e89424585b6ea13377760117b82330767ca94aec830d8ac8d9d`

This bounded record identifies exact external archive hashes, red/green
fingerprints, scoped installed checks, branch preservation and registry
observations. Raw console logs and environments remain outside source.

## Integration and public deployment closeout

HISTORY#669 records Suite PR #288 merged at `6c6ecd13490c9b675a77f246573491824313343c`
and website PR #33 deployed at `a7be46329cd430d38c95961edbc820dacd65b5a0`.
All three required checks, package CI, five native-launcher jobs, registry-plan
and CodeQL passed on reviewed head `706d62f4d3dca6293c7ef380124af21342a08633`.
The independently qualified successor receipt supersedes the immutable first
non-qualified request. No package inputs change in this documentation closeout.

Fresh live responses match eleven reviewed HTML pages plus pricing/download
scripts. Production Pages and email-worker checks passed. Fourteen obsolete
remote branches were removed with preservation/disposition proof; PR #266 is
closed and old objects remain reachable through its pull-request ref. Unique
website planning work remains intentionally retained. TestPyPI access, upload
and fresh downloaded installation remain open; no production release or full
product acceptance is claimed. Advisory PostgreSQL CI failed before tests
because the runner's Docker daemon socket was unavailable.

- `docs/audits/evidence/2026-10-14-suite-release/integration.json` — SHA-256: `d6cffac52db84461925e5ecd8f846cec01bc0573ea6c1b25abf6702caa2e452e`
