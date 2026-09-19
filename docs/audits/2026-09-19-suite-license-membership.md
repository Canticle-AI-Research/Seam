# Suite license and artifact membership review

[Report registry](INDEX.md) · [Packaging status](../status/packaging-licensing.md)

Decision record: HISTORY#650. Inspected SEAM PR #266 at
`9f0bfae2609d7ec587bb8375274ab7e4e63495ea`, based on protected main
`66fd3f93081712871ff827e756026c3e73c71790`. This documentation review continues
the [L1 review](2026-09-06-l1-packaging-migration.md). It grants no new rights.

## Exact candidate

The candidate is not established as wholly Apache-2.0 or as a qualified BUSL
distribution. [LICENSE](../../LICENSE) defines Distributed Runtime membership
through exact versions published by the owner, a distribution manifest, and
conspicuous BUSL notices. Public visibility and aggregate package metadata do
not establish membership.

The saved wheel and sdist each contain 109 runtime members, scoped to
`seam.py` and `seam_runtime/**`. All match the inspected PR source bytes.
Searching each member's first 2,048 bytes for `BUSL-1.1` or
`Business Source License` returns no matches. This bounded probe neither
excludes every possible notice nor classifies legacy rights. Complete archive
counts are 119 wheel members and 128 sdist members. Both include the five
declared license documents.

The [per-member map](evidence/2026-09-19-suite-license/members.json) records
paths, lengths, hashes, source equality and notice observations. Inspection
used Python `zipfile`/`tarfile` regular-member reads without extraction or
execution; no artifacts were rebuilt.

## Membership matrix

| Material | Controlling evidence | Disposition |
| --- | --- | --- |
| Candidate runtime, including `mirl.py`, `pack.py`, `sdk.py` and surface implementation | Exact member map; LICENSE definitions and section 7A | All 109 rows remain owner-review-required; no new distribution rights inferred |
| Distributed Runtime expressly published and identified under BUSL | LICENSE section 7A and `LICENSES/BUSL-1.1.txt` | Preserve the grant for qualifying versions; do not automatically extend it to this candidate |
| Unchanged legacy Apache materials | LICENSE section 7; exact historical publication | Preserve existing rights; individual candidate-file ancestry was not established here |
| Separate public HTTP client | L1's inspected `seam-client` 2.0.0 artifact | Preserve its separate Apache identity; client terms do not license Suite |
| Separate paid SDK | L1 private repository/artifact boundary | Private delivery only; no automatic Suite inclusion or PyPI/TestPyPI upload |
| Specifications, research, history and other reserved material | LICENSE definitions and scope | Remain reserved absent a separate grant |
| Third-party material and branding | LICENSE sections 8 and 10 | Retain applicable terms; no blanket Suite grant overrides them |

Bundled `seam_runtime.sdk` is distinct from separately packaged paid
`seam_sdk`. No private SDK source was read or copied during this review.

## Standard license text discrepancy

The repository's [BUSL text](../../LICENSES/BUSL-1.1.txt) ends after the
warranty disclaimer. The [SPDX BUSL-1.1 text at revision
31ba1a50](https://github.com/spdx/license-list-data/blob/31ba1a50e5397e00a304dbadc76531740e89ee48/text/BUSL-1.1.txt)
continues with MariaDB's permission to use the text/name and licensor
covenants, including restrictions on changing the standard text outside its
allowed parameters. Those closing sections are absent locally. The local
copyright line also differs from that reference.

This is a textual discrepancy to resolve before describing the file as the
complete standard BUSL-1.1 text, not a conclusion about enforceability.
No controlling text or Additional Use Grant was changed. A repair must retain
the owner's selected parameters, separately review compatibility with the
standard license, and avoid silently relicensing candidate files.

## Copy corrections and owner decision

README now scopes free self-hosting to material covered by the Distributed
Runtime grant and links this candidate review. Status and handoff distinguish
the grant from unresolved candidate membership. The bundled license documents,
aggregate metadata and `Private :: Do Not Upload` remain unchanged.
Install/release/TestPyPI/MCP docs already retain the artifact-review gate.

Website PR #29 at inspected head
`0f278b2cd83cc820ccb4ce11b2059527dacea1fd` still had `APACHE-2.0 CORE` badges
and subscription docs describing the runtime as open source. Neutral product
copy is the appropriate repair while membership is unresolved; historical
release claims remain separate. Website delivery evidence belongs to that PR.

The owner decision is concrete: identify which exact candidate runtime files,
if any, should be published under the existing BUSL grant, or retain the
candidate as proprietary with separately specified delivery permissions.
Adding notices to all 109 files would implement that rights decision, not
merely fix metadata. A licensing review request does not itself make that
choice. No runtime refactor or package split was needed for this map.

Then repair the standard-text discrepancy, apply approved membership/notices,
align metadata and public copy, rebuild and verify fresh artifacts, and
qualify the chosen delivery route. TestPyPI is public. The selected
PyPI-backed MCP route still requires an eligible published package.

## Verification and exclusions

Live GitHub inspection found both PRs open and draft at the inspected heads.
PR #266 has no base drift from current main. Required `chroma-real-smoke`
failed; `repo-hygiene` and `locomo-quickstart-bil2` were cancelled.
No complete PR qualification, owner approval, upload, registration, merge or
deployment is claimed. Earlier cumulative `NOT_QUALIFIED / TDD_UNPROVEN`
conditions remain open. Documentation verification is recorded in HISTORY#650.
No runtime tests or paid calls were needed for archive inspection and copy.

The primary checkout's existing audit/history/stream/handoff edits, untracked
`.codex/`, `.disposable/`, `.seam/orchestration/`, audit/handoff files,
cross-index archive and `error.log` remain excluded. Other linked worktrees
were untouched. Review used an isolated PR checkout with no available snapshot;
startup therefore used the index and bounded HISTORY#649 context pack.

## Evidence manifest

| Raw artifact | SHA-256 |
| --- | --- |
| `docs/audits/evidence/2026-09-19-suite-license/members.json` | `a36eac9f9719a39ec5fdbd70103b3da189dd35538f5e8f6ff6309414492b98b8` |
| `/home/terrabyte/LLM-Logs/codex/releases/20260917-seam-packages/mcp/artifacts/seam_suite-2.4.1rc1-py3-none-any.whl` | `0a94189a3570347719fa2ddc3b7b957d16585896a27fba518a731376f74d4434` |
| `/home/terrabyte/LLM-Logs/codex/releases/20260917-seam-packages/mcp/artifacts/seam_suite-2.4.1rc1.tar.gz` | `6b184f0c14d65a127ce374806e626304d55c252960dccb77850345f6bbd18eb1` |
