# Status Stream: Packaging Licensing

> Current artifact coordinates, release constraints, and the next migration task

Product definitions live in [SEAM products](../PRODUCTS.md). Delivery order
lives in [the launch plan](../roadmap/SEAM_LAUNCH.md). Reconciliation commands
and dated observations are recorded in HISTORY#634 and the
[current handoff](../handoffs/INDEX.md).

## Current boundary

`Canticle-AI-Research/Seam` is the canonical development repository. GitHub
reports it as public at the launch baseline. Repository visibility, licensing,
package contents, and release visibility are separate properties; the old
description "private repository" must not be used as proof of access control.

The root build still declares **`seam-runtime` 2.4.0** and
`Private :: Do Not Upload`. It contains the full runtime and readable MIRL/HS/1
source. That build remains blocked from PyPI. The product naming decision does
not remove the classifier, alter license terms, or qualify a Suite artifact.

[LICENSE](../../LICENSE), [NOTICE](../../NOTICE),
[COMMERCIAL_LICENSE.md](../../COMMERCIAL_LICENSE.md), and the named license
texts remain controlling. `LICENSE` defines Distributed Runtime membership by
published file version, manifest, and conspicuous notice. The new product map
does not establish which files belong in a future distribution. Resolve that
exact boundary in L1 before changing package contents or publication controls.

## Coordinates to reconcile

| Coordinate | Baseline observation | Migration treatment |
| --- | --- | --- |
| PyPI `seam` | Unrelated Seam API SDK | Do not use as Canticle's distribution name |
| PyPI `seam-runtime` | Legacy 1.3.1 metadata | Preserve legacy-version history and audit upgrade behavior; do not upload the root build here |
| PyPI `seam-self-host` | Legacy 1.1.2 metadata; its in-tree build was retired | Inventory users and replacement path; do not recreate removed split tooling implicitly |
| PyPI `seam-client` | Public HTTP client 2.0.0 metadata | Confirm current source and owner access, then plan compatibility and any successor name |
| `Canticle-AI-Research/Seam_SDK` | Separate repository declaring `seam-sdk` 0.1.0 with a Git-pinned runtime dependency | Verify the runtime pin, supported interfaces, duplicated SDK code, and release boundary |
| GitHub release `v2.4.0` | Existing release in the canonical repository | Inspect exact assets and terms before treating it as a Suite migration input |

These are metadata observations, not fresh clean-install or artifact-content
qualification. The legacy `BlackhatShiftey/Seam_Runtime` repository lookup
returned HTTP 404 during reconciliation; that result does not establish why it
is unavailable or whether ownership can be recovered. Its links in published
metadata require a deliberate source/ownership check.

## Existing release automation

`package-release.yml` prepares a root wheel/sdist and a GitHub draft;
`publish-private-release.yml` publishes a reviewed draft through its configured
operator gate. Their names retain the historical word "private". Those names
and `Private :: Do Not Upload` do not make GitHub output private. Destination
visibility and artifact eligibility must be rechecked before dispatch.

The preparation workflow has no PyPI upload job. Keep the existing secret,
reserved-material, and artifact scanners. The retired mirror, compiled
self-host build, and API-only shim are historical implementations; they do
not define the new Suite architecture.

## Next packaging task

L1 is a migration packet and reviewed candidate build, followed by explicit
release qualification. Work through these items in order:

1. **Ownership and sources:** verify PyPI owner access, source repositories,
   current branches, existing releases, and the source of the public client.
   Resolve unavailable legacy coordinates before promising an upgrade path.
2. **Artifact map:** choose the Suite installation format and contents, the
   hosted deployment artifact if needed, the public HTTP client, and the local
   SDK. Record exact file/version membership, license notices, dependencies,
   entrypoints, imports, and destination for each. Hosted API access does not
   require publishing its server implementation to PyPI.
3. **Names and compatibility:** confirm candidate registration eligibility and
   agree versions, command/import changes, deprecation behavior, and migration
   from existing installs. Do not delete or replace legacy releases as a rename
   shortcut. Keep the product map and compatibility matrix aligned.
4. **Candidate qualification:** build outside the active source tree, inspect
   wheel/sdist or image contents, apply the appropriate artifact boundary
   checks, and test clean installation and legacy upgrades in isolation.
   Exercise real CLI, HTTP-client, and local-SDK calls for supported roles.
5. **Release controls:** reconcile GitHub destination visibility and workflow
   permissions, verify the current publisher configuration, and bind uploads
   to reviewed artifacts and exact CI evidence. Existing workflow labels are
   not proof of privacy or authorization.
6. **Documentation and release decision:** update install/upgrade instructions,
   package URLs, compatibility matrix, and release notes together. Public
   upload occurs only after applicable launch qualification and explicit
   operator authorization. Record uncompleted items as blockers.

Package names in [the product map](../PRODUCTS.md#product-names-and-artifact-names)
are candidates. PyPI lookup absence does not establish ownership or availability.
