# SEAM products and names

[Back to the SEAM Wiki](README.md)

**SEAM means Surface Encoded Agent Memory.** This is the current product name;
the RAW/MIRL/PACK/LENS behavior remains governed by the
[SEAM specification](../SEAM_SPEC_V0.1.md) and [MIRL contract](MIRL_V1.md).
The launch direction is recorded in HISTORY#634.

## Product family

These definitions describe the intended launch products. They do not assert
that a package, complete interface, or hosted service is available today.

| Name | Role | Included experience |
| --- | --- | --- |
| Canticle SEAM Suite | Self-hosted SEAM operated on the user's infrastructure | Product Core, TUI, browser graph dashboard, knowledge database inspection, and benchmark glassbox |
| Canticle SEAM API | Paid hosted SEAM service | Supported API contract, customer access and isolation, usage controls, and service operations |
| SEAM WebUI | Operator surface for SEAM API | Integrated customer dashboard using authorized service APIs, styled with Canticle components |
| SEAM SDK | Developer integration family | Explicitly distinguished HTTP client and local runtime SDK; supported versions and capabilities must be documented separately |

The Suite TUI handles terminal operation, status, and workflow controls. The
rich graph experience runs in a browser and can open independently. A terminal
approximation does not satisfy the browser design's acceptance criteria.

## Suite graph dashboard

The overview uses the requested **diamond graph in constellation view**. Each
section below must also load independently, with its own selection, filters,
loading, empty, unavailable, and error states.

| Section | What an operator can inspect | Acceptance boundary |
| --- | --- | --- |
| Knowledge graph | Entities, claims, relationships, lifecycle and temporal state | Every displayed relationship resolves to admissible source evidence |
| Reasoning graph | Recorded decisions, supporting evidence, checks, disagreements, and outcomes | Structured recorded activity; inferred relationships and verification status are explicit |
| Knowledge database | Canonical records, source anchors, scope, versions, corrections and lifecycle history | Record inspection and history remain distinct from current-read eligibility |
| Benchmark glassbox | Saved runs, configuration, per-case results, executed retrieval paths, failures and comparisons | Every result identifies its evidence bundle; missing or unrun measurements stay explicit |

Graph selections link to source records and evidence. Database inspection is
a record view over canonical storage, not a newly invented graph or parallel
source of truth. Derived projections remain rebuildable.

Reuse the intended browser design and the canonical
[Canticle identity kit](../branding/kit/README.md) and
[cosmic UI components](../branding/canticle-cosmic-kit/README.md). Confirm the
reference artifact before implementation, then review real desktop/mobile
renders and interactions. Styling alone does not establish completion.

## Shared interfaces, explicit deployment boundaries

Suite and WebUI should share applicable visual components, navigation, and
interaction conventions. Data adapters, permissions, and packaged content
must preserve their different deployment boundaries.

All consumers delegate to the existing runtime contracts. The public HTTP
client does not become a local-runtime SDK by renaming it, and the local SDK
does not become safe to distribute merely because its API resembles the
public one. The hosted operator surface needs a deliberately specified,
customer-authorized inspection contract; it must not expose private runtime
routes to make a graph view work.

## Product names and artifact names

Product names above are the agreed direction. Artifact names below are
**candidates**, pending the packaging migration checklist:

| Artifact role | Candidate name | Existing coordinate to reconcile |
| --- | --- | --- |
| Suite installation/distribution | `canticle-seam-suite` | Root `seam-runtime`; retired `seam-self-host` artifacts |
| Hosted service deployment artifact, if separately packaged | `canticle-seam-api` | Existing service in the runtime repository; no public PyPI requirement |
| Public Python HTTP client | `canticle-seam-client` | Published `seam-client` |
| Local Python runtime SDK | `canticle-seam-sdk` | Separate `Seam_SDK` repository declaring `seam-sdk` |

Do not rename imports, commands, package metadata, repositories, or published
artifacts through prose changes. Choose those migration details together,
with clean-install and upgrade evidence. A missing PyPI project is not a name
reservation or a guarantee of registration.

Current distribution facts and the next packaging task live in
[packaging status](status/packaging-licensing.md). The ordered acceptance
checklist lives in the [launch plan](roadmap/SEAM_LAUNCH.md). Existing
[LICENSE](../LICENSE), [NOTICE](../NOTICE), and
[commercial terms](../COMMERCIAL_LICENSE.md) control rights; this product map
does not change them.
