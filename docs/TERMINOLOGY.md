# SEAM terminology

[Back to the SEAM Wiki](README.md)

This is the canonical naming glossary for active SEAM documentation. It defines
names and boundaries; the [SEAM specification](../SEAM_SPEC_V0.1.md) and
[MIRL v1 contract](MIRL_V1.md) remain governing for behavior.

## Organization and system

- **Canticle Research** is an independent research organization working on AI
  safety, emergence, memory, fine-tuning, models, agents, and their
  interactions. Its research is broader than SEAM. Software and published
  artifacts use the license attached to each layer; “Canticle Research” is not
  the name of one software package or one blanket software license.
- **SEAM** expands to **Surface Encoded Agent Memory**. It is the machine-first
  memory system defined by the governing specification, not a generic name for
  every Canticle project or product.
- **MIRL** expands to **Machine Intermediate Representation Language**. MIRL is
  the canonical memory intermediate representation inside SEAM.

## Representation layers and formats

- **`RAW`** is verbatim source material. It preserves evidence and provenance;
  it is not the prompt-optimized representation.
- **`IR`** is the canonical semantic intermediate representation and the main
  SEAM language. MIRL is SEAM's current canonical memory IR contract.
- **`PACK`** is a dense retrieval and context-window form derived from `IR`.
  Context and narrative packs do not become durable truth.
- **`LENS`** is a task-specific projection over memory that retains references
  to `IR`; it is a view, not a parallel source of truth.
- **`SEAM-RC/1`** is the runtime-readable lossless text-compression format. It
  supports direct machine-language reads and exact text reconstruction.
- **`SEAM-LX/1`** is the machine-oriented exact reconstruction and integrity
  envelope. It is verify/decode material, not the queryable working document.
- **`SEAM-HS/1`** is the Holographic Surface lossless PNG container for MIRL,
  `SEAM-RC/1`, `SEAM-LX/1`, or raw bytes. It carries a payload; it is neither a
  compression claim nor canonical truth by itself.

## Data and graphs

- **Canonical and derived data:** SQLite is the canonical durable store for
  SEAM records and lifecycle truth. Search indexes, vector indexes, graph
  projections, PACK output, LENS views, and surface-library projections are
  derived and rebuildable. A portable surface may preserve an exact payload,
  but it does not replace the canonical store.
- **Knowledge graph:** the self-building, versioned SQLite projection of
  canonical MIRL entities, claims, relations, lifecycle state, and evidence.
  It is rebuilt from canonical records and is not a separately authored truth
  store.
- **Reasoning graph:** the structured record of decisions, retrieval activity,
  supporting evidence, checks, disagreements, and outcomes. It records
  inspectable operational reasoning; it is not hidden model state and does not
  promote itself into MIRL.

## Products, packages, and licensed subset

- **SEAM Suite** is the intended self-hosted product. Its selected distribution
  name is `seam-suite`. The Suite is proprietary: free individual personal,
  noncommercial self-hosting is governed by [the personal license](../LICENSES/SEAM-Suite-Personal.txt)
  and its exact manifest. Business and organizational use, including unpaid
  business evaluation, requires a separate written agreement with
  licensing@canticle.cc. The grant does not cover independent MIRL/HS1 reuse,
  modification, redistribution, or hosted offerings; the paid SDK stays separate.
- **SEAM Client** is the intended paid hosted API and all-in-one WebUI product.
  Hosted availability is a separate status claim; the name does not assert that
  the service is live.
- **`seam-client`** is the separate public Python HTTP client for SEAM Client.
  Installing it neither installs SEAM Suite nor grants hosted access.
- **`seam-sdk`** is the private paid SDK. It is distinct from the public
  `seam-client` package.
- **Distributed Runtime** identifies exact earlier versions qualifying under
  the historical BUSL terms; see [LICENSE section 7A](../LICENSE). It does not
  name the current Suite personal grant or create an entitlement to later
  versions. It is not a synonym for the repository, SEAM Suite, SEAM Client,
  or all SEAM material. The current personal grant has no automatic open-source
  conversion, and users retain their own data.

For launch status, packaging state, and implementation evidence, follow the
[product map](PRODUCTS.md), current status streams, and named tests rather than
inferring availability from a canonical name.
