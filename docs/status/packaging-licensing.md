# Status Stream: Packaging Licensing

> Distribution shape, licensing, and the public/private boundary

_Source of truth for current state in this area. History lives in `HISTORY.md`._

## Current implementation

The repository still builds one private full-runtime package with readable MIRL
and HS/1 source. `LICENSE`, `NOTICE`, `COMMERCIAL_LICENSE.md`, current package
metadata, the `Private :: Do Not Upload` tripwire, and the private GitHub Release
workflow remain unchanged. The full runtime currently has no PyPI publication
path. Existing Apache-2.0 and BUSL artifacts retain the grants attached to their
exact published versions.

## Approved target

SEAM Self-Host will be the complete operator-run SEAM product rather than a
reduced public substitute. SEAM Suite will combine a terminal control center
with independently openable browser dashboards for real knowledge, reasoning,
provenance, and benchmark graphs.

The intended source-available layer uses the unmodified PolyForm Shield 1.0.0
license and includes the SEAM backend, SeamSDK, Ghost as a SEAM agent, MIRL,
SEAM-HS/1, the Improvement Loop, and SEAM-specific graph and benchmark logic.
The intended Apache-2.0 layer includes `seam-client`, public contracts and
connectors, frontends, neutral graph renderers, Benchmark Glassbox presentation
and charting, public provenance formats, and deployment tooling that does not
embed protected implementation.

This is an approved design target, not a current license grant. No file,
package, release, or historical artifact is relicensed by this status update.
Implementation requires an exact module inventory, artifact manifests,
boundary tests, operator review of the resulting distribution, and legal
review. See `CONTEXT.md` and
`docs/superpowers/plans/2026-08-29-seam-product-licensing-boundary-design.md`.

## Retained push gate

`verify_public_safe.py` + `public_manifest.py` are a secret and reserved-material
push gate — they exist because a `seam.db` snapshot once leaked (HISTORY#344). They
are not split machinery and must not be removed as such.

## Do not re-litigate

Do not re-ask the product shape or collapse the client, SDK, Ghost, protected
core, TUI, browser dashboards, and managed operator surface into one ambiguous
module. Apply the approved boundary through explicit artifacts; do not infer a
license from repository location or frontend code.
