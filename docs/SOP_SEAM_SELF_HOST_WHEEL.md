# Historical SOP: compiled `seam-self-host` wheel

> **SUPERSEDED — DO NOT EXECUTE.**

Owner: Codex. Originally written by Claude, 2026-07-28. Retired 2026-08-01;
reclassified as a non-executable historical record 2026-08-25.

## Current rule

This document is not a build or release route. The compiled
`seam-self-host` distribution, its BUSL release path, and the retrofitted
public/private package split were removed. Their source paths, build drivers,
artifact gates, and workflows no longer exist.

The canonical `seam-runtime` package is the only package definition in this
repository. It contains readable MIRL and HS/1 implementation, remains private,
and retains `Private :: Do Not Upload`. Do not recreate a public or
source-available distribution from this tree.

Any future source-distributed SEAM SDK or SEAM Node must be authored in a
separate repository with an architectural source boundary, its own PolyForm
Shield 1.0.0 text and metadata, an allowlisted artifact manifest, complete
secret/reserved-material inspection, and written owner approval. Its exact
features and release procedure are not defined by this retired SOP.

## Historical outcome

The former design proposed compiling private runtime modules into extension
objects, packaging them as `seam-self-host`, and shipping the artifact under
BUSL-1.1. That approach was retired because compilation was an obfuscation
boundary rather than a clean product boundary. Exact artifacts already
published under BUSL retain their shipped terms; their last parameterized text
is preserved at `LICENSES/HISTORICAL/BUSL-1.1.txt`.

Historical engineering lessons retained from the experiment:

- hiding source in compiled objects is not the same as separating products;
- release artifacts require content inspection, not successful-build inference;
- allowlists fail closed more safely than path denylists;
- runtime smoke tests must exercise remember and recall, not only health;
- package metadata and shipped license texts must agree; and
- a successful feasibility spike never authorizes publication.

The chronological detail, measurements, and prior decisions remain in the
indexed HISTORY chain. This tombstone intentionally omits executable commands
so it cannot be mistaken for a current BUSL release procedure.

## Current routes

- Canonical package and repository policy: `REPO_LEDGER.md`
- Current distribution state: `docs/status/packaging-licensing.md`
- Product/license placement: `docs/legal/LICENSING_ARCHITECTURE.md`
- Future company checklist: `docs/legal/COMPANY_IP_READINESS.md`
- Release procedures that are actually active: `docs/SOP_INDEX.md`
