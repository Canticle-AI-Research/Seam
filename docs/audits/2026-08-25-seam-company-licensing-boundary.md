# SEAM company licensing boundary

**Date:** 2026-08-25

**Scope:** canonical private SEAM repository, adjacent public/client and
source-distributed product boundaries, historical grants, package metadata,
and pre-company ownership records

**Baseline:** protected `main@bc6b927`; branch-local preservation is recorded
by `HISTORY#612`

**Status:** superseded, unmerged draft preserved for provenance; not legal
advice and not a substitute for jurisdiction-specific counsel

> This draft does not represent current SEAM product direction. It was
> superseded before publication by the operator-approved 2026-08-29 boundary,
> which applies PolyForm Shield to the complete source-available SEAM product,
> SeamSDK, Ghost, MIRL, SEAM-HS/1, and the Improvement Loop. Do not merge or use
> this document as a license grant.

## Outcome

SEAM now records one prospective three-lane product structure:

| Lane | Exact surface | Prospective terms |
| --- | --- | --- |
| open edge | thin clients, public schemas, protocols, and examples after an artifact review | Apache-2.0 |
| source-available product | separately authored and separately shipped SEAM SDK and SEAM Node repositories | PolyForm Shield 1.0.0, with optional commercial alternatives |
| proprietary core and service | this canonical runtime, MIRL, HS/1, private research and benchmarks, planned SEAM-U assets, and hosted control-plane internals | proprietary / All Rights Reserved or separately negotiated terms |

PolyForm Shield is intentionally absent from this canonical repository and its
package metadata. A broad source-use grant in this tree would reach readable
MIRL, HS/1, research, benchmarks, and release machinery that the product
architecture keeps private. Shield belongs only in the independently reviewed
SDK/Node repository and the exact artifacts shipped from it.

BUSL is no longer a prospective SEAM license. Exact versions already published
under BUSL-1.1 retain the grant shipped with those versions. The last
parameterized text was copied unchanged to
`LICENSES/HISTORICAL/BUSL-1.1.txt`; its registry label distinguishes the copy as
historical evidence while the original tracked file remains preserved. Exact
Apache-2.0 versions also retain their existing rights.

## Repository and artifact findings

- Root `LICENSE` reserves the canonical repository, MIRL, HS/1, private
  research, and planned SEAM-U material. It makes no current BUSL or PolyForm
  grant.
- `NOTICE`, `COMMERCIAL_LICENSE.md`, `CONTRIBUTING.md`, and `TRADEMARKS.md`
  agree on ownership, contribution, adjacent-product, historical-grant, and
  brand boundaries.
- `pyproject.toml` keeps `Private :: Do Not Upload`, removes BUSL from the
  active license expression, and packages only the current proprietary notice,
  commercial notice, and required Apache legacy text.
- The built wheel contains no BUSL license text. Its metadata reports
  `LicenseRef-SEAM-Proprietary AND Apache-2.0` and includes no PolyForm grant.
- Active status, roadmap, security, pricing, protection, release, layout, and
  repository-ledger documents route future SDK/Node products to a separate
  Shielded artifact and describe BUSL only as historical.
- Static audit tests make accidental reintroduction of an active root BUSL or
  PolyForm grant, loss of the historical record, or package-metadata drift a
  test failure.

## Historical grant preservation

This change is prospective. It does not revoke, narrow, relicense, or rewrite
any exact artifact already received under Apache-2.0, BUSL-1.1, or another
valid license. A recipient's rights continue to follow that artifact's own
version, manifest, notices, and publication record. The move of the BUSL text
inside this repository is classification of evidence, not withdrawal of an
existing grant.

## Ownership and company-readiness boundary

Nicholas Thomas remains the named owner/licensor until a written assignment or
other legally sufficient transfer creates a different chain of title. The
repository does not claim that a future company already exists or owns these
assets. `docs/legal/COMPANY_IP_READINESS.md` records the founder inventory,
assignment schedule, contributor, trademark, account-control, data/model, and
counsel work still required.

The repository license and this audit are operational controls drafted for
counsel review. They do not determine entity formation, tax, employment,
privacy, export, patent, trademark registration, consumer, or other
jurisdiction-specific obligations.

## Verification checklist

- Focused license-boundary and wiki-navigation audit tests: passed.
- Ruff over the new audit test: passed.
- Documentation navigation: passed; all active documents reachable.
- Package build and wheel metadata/member inspection: passed; no historical
  BUSL text in the wheel.
- Repository diff whitespace check: passed.
- Canonical non-external suite, protected-main publication, and legal
  qualification were not completed. Branch-local preservation is recorded in
  `HISTORY#612`; there is no pull request publishing this audit.

## Residual actions

1. Have qualified counsel review the actual license texts, PolyForm
   line-of-business application, historical grants, contribution terms, and
   trademark policy before external release or customer reliance.
2. Form the company and execute a written founder-to-company IP assignment with
   an asset schedule; update notices prospectively only after that transfer.
3. Inspect each adjacent repository and its complete release artifact before
   applying Apache-2.0 or PolyForm Shield; shared product names do not prove a
   clean code boundary.
4. Establish model/data provenance and an explicit weights-access policy before
   training or distributing SEAM-U.
5. Keep signed assignments, board/member approvals, and contributor agreements
   in the corporate record system, not this source repository.

## Repository evidence

- `LICENSE`
- `NOTICE`
- `COMMERCIAL_LICENSE.md`
- `CONTRIBUTING.md`
- `TRADEMARKS.md`
- `LICENSES/README.md`
- `LICENSES/HISTORICAL/BUSL-1.1.txt`
- `pyproject.toml`
- `docs/legal/LICENSING_ARCHITECTURE.md`
- `docs/legal/COMPANY_IP_READINESS.md`
- `tests/audit/test_licensing_boundary.py`

## Evidence manifest

Raw artifacts: none
