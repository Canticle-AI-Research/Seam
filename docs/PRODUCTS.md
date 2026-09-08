# SEAM products and names

[Back to the SEAM Wiki](README.md)

**SEAM means Surface Encoded Agent Memory.** This is the current product name;
the RAW/MIRL/PACK/LENS behavior remains governed by the
[SEAM specification](../SEAM_SPEC_V0.1.md) and [MIRL contract](MIRL_V1.md).
The launch direction is recorded in HISTORY#634; names and TestPyPI-first
publication were updated by the operator in HISTORY#642.

## Product family

These definitions describe the intended launch products. They do not assert
that a package, complete interface, or hosted service is available today.

| Name | Role | Included experience |
| --- | --- | --- |
| SEAM Suite (`seam-suite`) | Self-hosted SEAM operated on the user's infrastructure | Product Core, TUI, browser graph dashboard, knowledge database inspection, and benchmark glassbox |
| SEAM Client | Paid hosted API and its all-in-one WebUI dashboard | Supported API contract, customer access and isolation, usage controls, and integrated operator dashboard |
| SEAM SDK (`seam-sdk`) | Private developer SDK with access for paying users | Private runtime integration; customer delivery and supported versions require qualification |
| Python HTTP client (`seam-client`) | Separate Python client for the public API | Transport and opaque public models; distinct from the private paid SDK |

The Suite TUI handles terminal operation, status, and workflow controls. The
rich graph experience runs in a browser and can open independently. A terminal
approximation does not satisfy the browser design's acceptance criteria.

“SEAM WebUI” names the browser component of SEAM Client; it is not a fourth
product. The existing `seam-client` Python distribution remains a transport
library, distinct from the hosted dashboard. Its installation does not grant
service access. The browser UI is delivered by the service, not by that wheel.

The paid SDK access boundary was clarified by the operator in HISTORY#635.
Further paid capabilities remain unspecified. This product decision does not
change existing license texts or establish an entitlement implementation.

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

The operator-selected names replace the earlier `canticle-seam-*` proposals.
Product names, Python distributions, and service deployments are separate:

| Artifact role | Selected name | Existing coordinate to reconcile |
| --- | --- | --- |
| Suite installation/distribution | `seam-suite` | Renamed root candidate, formerly `seam-runtime`; retired `seam-self-host` artifacts require explicit migration |
| Hosted API and dashboard | SEAM Client | Existing server and WebUI; no separate public server package is required |
| Python HTTP client for SEAM Client | `seam-client` | Existing published Python client; keep `seam_client` imports and compatibility |
| Private paid Python SDK | `seam-sdk` (private delivery only) | Private `Seam_SDK` repository already declares this distribution name |

The root distribution candidate is `seam-suite` 2.4.1rc1. Existing `seam` and
`seam_runtime` imports and console commands remain unchanged. Install in a
fresh environment rather than co-installing overlapping legacy distributions.
The new name does not qualify the current source bundle for public upload.

**TestPyPI first:** use [the testing procedure](TESTPYPI.md) before any
production publication. TestPyPI is public, has independent accounts and
project ownership, and does not reserve a production name. Neither public
registry receives the private paid SDK. Existing releases remain intact.

Current distribution facts and the next packaging task live in
[packaging status](status/packaging-licensing.md). The ordered acceptance
checklist lives in the [launch plan](roadmap/SEAM_LAUNCH.md). Existing
[LICENSE](../LICENSE), [NOTICE](../NOTICE), and
[commercial terms](../COMMERCIAL_LICENSE.md) control rights; this product map
does not change them.
