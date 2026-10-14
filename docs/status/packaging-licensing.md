# Status Stream: Packaging Licensing

> Current artifact coordinates, release constraints, and the next migration task

Product definitions live in [SEAM products](../PRODUCTS.md). Delivery order
lives in [the launch plan](../roadmap/SEAM_LAUNCH.md). Reconciliation commands
and dated observations are recorded in HISTORY#634 and the
[current handoff](../handoffs/INDEX.md).

## Licensing reconciliation

The owner decision recorded on PR #266 is carried onto current main by
HISTORY#665: Suite remains proprietary with free personal, noncommercial
self-hosting under [the personal license](../../LICENSES/SEAM-Suite-Personal.txt)
and [exact membership manifest](../../LICENSES/SEAM-Suite-manifest.json).
Business, employment, client and organizational use require a separate written
agreement through licensing@canticle.cc, including internal operation and
unpaid business evaluation. Embedded MIRL/HS/1 operations are allowed to run
the authorized Suite; independent reuse, modification and redistribution are
reserved. The separate paid SDK is excluded.

This is the current Suite's first-launch licensing task. Historical license
files remain unchanged; no rollback or user-migration project is included.
Third-party and any independently applicable rights remain intact. See
[the reconciliation report](../audits/2026-10-14-licensing-reconciliation.md)
for the current-source and archive verification.

Licensing is a focused successor of [PR #266](https://github.com/Canticle-AI-Research/Seam/pull/266).
Its dependency/release/MCP changes and cumulative package-qualification condition
remain separate. Independent source and installed-package review supports the
owner-authorized TestPyPI candidate; its private-upload classifier is removed
in this reviewed preparation. Publisher access, exact rebuilt-file qualification,
TestPyPI verification, production authorization and operator-product acceptance
remain separate gates. An exact reviewed license manifest resolves this candidate's membership;
it does not qualify a future changed artifact automatically.

## Current naming candidate

HISTORY#642 selects `seam-suite` for self-hosted Suite, SEAM Client for the
paid API plus its WebUI, and `seam-sdk` for private paid delivery. Existing
`seam-client` remains the Python HTTP client, not a dashboard distribution.
The root candidate is `seam-suite` 2.4.1rc1; imports and commands retain their
existing names. This is a source change, not a published package.

The operator requires **TestPyPI first**. Follow [the procedure](../TESTPYPI.md);
production publication and deletion of legacy releases are excluded. TestPyPI
access and release qualification remain unresolved. No private SDK
source may be included in either public index.

## L1 preparation evidence

The [L1 migration packet](../audits/2026-09-06-l1-packaging-migration.md)
records exact artifact/member hashes, the source/ownership map, scoped installed
package evidence, and release blockers (HISTORY#635). Documentation baseline
PR #250 is merged at `7c08104` (HISTORY#636). This packet records scoped preparation evidence; it does not qualify a package
release.

**SEAM SDK is private, with access for paying users.** Its customer delivery
is separate from the public HTTP client and is not automatically included in
Suite. The private SDK currently pins an older runtime and has two retrieval
contract differences requiring a separate private compatibility change.

Local runtime/SDK candidates built and passed archive scanning; the installed
HTTP-client subset, explicit-seeding SDK probes, existing SDK reasoning tests,
and one synthetic legacy-runtime data upgrade passed. These scoped results do
not qualify a new package name, full SDK parity, arbitrary upgrades, release
rights, or hosted service. Ownership/source recovery, exact Suite membership,
a fresh successor version, paid delivery, and compiled self-host migration
remain explicit blockers in the packet. R2/S8 is now complete through PR #254; operator-product acceptance remains next.

## Current boundary

`Canticle-AI-Research/Seam` is the canonical development repository. GitHub
reports it as public at the launch baseline. Repository visibility, licensing,
package contents, and release visibility are separate properties; the old
description "private repository" must not be used as proof of access control.

The renamed root candidate declares **`seam-suite` 2.4.1rc1** and
an early-access development classifier. It contains the reviewed Suite runtime
and readable MIRL/HS/1 source with the paid SDK excluded. Independent source and
installed-package review precedes removal of the private-upload tripwire; the
rebuilt files still require exact qualification and TestPyPI publisher access.
Section 7B identifies this candidate's exact personal-use membership; the
package rename itself did not grant those rights. Release workflows validate the exact canonical Python
version, including this prerelease, while retaining their operator and
artifact gates. They do not upload to a package index. The default installation
now includes terminal and HTTP/browser dependencies; compatible `dash` and
`server` aliases remain. See [the release flow](../RELEASE_FLOW.md).

[LICENSE](../../LICENSE), [NOTICE](../../NOTICE),
[COMMERCIAL_LICENSE.md](../../COMMERCIAL_LICENSE.md), and the named license
texts remain controlling. Section 7B and the Suite manifest identify the exact
personal-use implementation; section 7A retains the historical Distributed
Runtime membership requirements. Refresh and review exact membership when
package contents change. Product names and repository visibility do not do so.

## Coordinates to reconcile

| Coordinate | Baseline observation | Migration treatment |
| --- | --- | --- |
| PyPI `seam` | Unrelated Seam API SDK | Do not use as Canticle's distribution name |
| PyPI `seam-runtime` | Legacy 1.3.1 metadata | Leave existing releases intact; do not upload the Suite build here |
| PyPI `seam-self-host` | Legacy 1.1.2 metadata; its in-tree build was retired | Leave existing releases intact; do not recreate removed split tooling |
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

1. **Ownership and sources:** verify Suite's TestPyPI publisher access and
   current source. This is first-launch Suite preparation; historical packages
   and the separate public HTTP client are outside its migration scope.
2. **Artifact map:** choose the Suite installation format and contents, the
   hosted deployment artifact if needed, the public HTTP client, and the local
   SDK. Record exact file/version membership, license notices, dependencies,
   entrypoints, imports, and destination for each. Hosted API access does not
   require publishing its server implementation to PyPI.
3. **Names and compatibility:** verify candidate registration eligibility and
   the selected version, commands, imports, and supported install environment.
   Leave historical releases intact. Keep product definitions aligned.
4. **Candidate qualification:** build outside the active source tree, inspect
   wheel/sdist or image contents, apply the appropriate artifact boundary
   checks, and test clean installation and restart persistence in isolation.
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
