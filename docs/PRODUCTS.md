# SEAM products and names

[Back to the SEAM Wiki](README.md)

**SEAM means Surface Encoded Agent Memory.** This is the current product name;
the RAW/MIRL/PACK/LENS behavior remains governed by the
[SEAM specification](../SEAM_SPEC_V0.1.md) and [MIRL contract](MIRL_V1.md).
The launch direction is recorded in HISTORY#634; names and TestPyPI-first
publication were updated by the operator in HISTORY#642. HISTORY#647 replaces
the hosted "SEAM Client" product label with **SEAM API (`seam-api`)**.
HISTORY#648 records the operator's readiness clarification and intended local
API/WebUI installation.

## Product family

These definitions describe the intended launch products. They do not assert
that a package, complete interface, or hosted service is available today.

| Name | Role | Included experience |
| --- | --- | --- |
| SEAM Suite (`seam-suite`) | Self-hosted SEAM operated on the user's infrastructure | Product Core, TUI, browser graph dashboard, knowledge database inspection, and benchmark glassbox |
| SEAM API (`seam-api`) | Planned local installation for the public API surface and WebUI | Shared runtime, API server, API client dependencies, and browser interface; a hosted service is a separate deployment |
| SEAM SDK (`seam-sdk`) | Private developer SDK with access for paying users | Private runtime integration; customer delivery and supported versions require qualification |
| Python HTTP client (`seam-client`) | Separate Python client for the public API | Transport and opaque public models; distinct from the private paid SDK |

The Suite TUI handles terminal operation, status, and workflow controls. The
rich graph experience runs in a browser and can open independently. A terminal
approximation does not satisfy the browser design's acceptance criteria.

“SEAM WebUI” names the browser component of SEAM API; it is not a fourth
product. The existing `seam-client` Python distribution remains a transport
library, distinct from the planned API/WebUI installation. Its installation
does not provide a local server, the WebUI, or hosted service access. The planned
`seam-api` install will supply the local server and served browser interface.

The paid SDK access boundary was clarified by the operator in HISTORY#635.
Further paid capabilities remain unspecified. This product decision does not
change existing license texts or establish an entitlement implementation.

## Current readiness

| Component | Current state |
| --- | --- |
| Self-hosted SEAM core | Usable for local operation; this is the operator's plug-and-play core milestone, not a claim that every planned capability is finished |
| Suite operator surfaces | TUI, browser graph dashboard, and benchmark glassbox remain in development; the full Suite is early access |
| SEAM API product | Planned; product development has not started and there is no product download |
| New PyPI distributions | Publication is separately gated; usable source and installed startup checks do not establish registry availability |

Existing REST routes, the legacy HTTP client, and a browser prototype are
building blocks. They do not establish a finished API/WebUI product. The
[surface status](status/surfaces.md) retains implementation-level evidence;
the [release flow](RELEASE_FLOW.md) separates product maturity, package
availability, and the proposed API setup.

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
| Local API server, client support, and WebUI | `seam-api` | Planned installation shape; implementation and exact public artifact membership remain to be designed |
| Legacy Python HTTP client for SEAM API | `seam-client` | Existing published Python client; preserve existing `seam_client` imports during migration |
| Private paid Python SDK | `seam-sdk` (private delivery only) | Private `Seam_SDK` repository already declares this distribution name |

The root distribution candidate is `seam-suite` 2.4.1rc1. Existing `seam` and
`seam_runtime` imports and console commands remain unchanged. Install in a
fresh environment rather than co-installing overlapping legacy distributions.
The new name does not qualify the current source bundle for public upload.
Suite installs its TUI and browser-server dependencies by default. Optional
model, vector, and benchmark-provider dependencies remain opt-in. A package
smoke proves installation and startup; full graph/glassbox workflow acceptance
remains a separate product requirement.

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
