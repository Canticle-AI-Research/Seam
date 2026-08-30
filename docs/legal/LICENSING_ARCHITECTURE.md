# SEAM licensing architecture

**Decision state:** approved engineering architecture; counsel review and
founder-to-company assignment remain pending.

SEAM uses an open-edge/source-available-product/proprietary-core structure. A
license belongs to a concrete repository and artifact, not merely to a product
name or interface.

```text
applications and integrations
        │
        ├─ Apache-2.0 thin clients, schemas, protocols, examples
        │       no MIRL/runtime/model implementation
        │
        ├─ PolyForm Shield 1.0.0 runnable product repositories
        │       SEAM SDK and SEAM Node source distributions
        │       use/change/share except competing products
        │
        └─ authenticated or licensed product boundary
                │
                ├─ proprietary SEAM runtime and MIRL compiler
                ├─ proprietary HS/1 and provenance internals
                ├─ proprietary planned SEAM-U model/data system
                └─ proprietary cloud identity, billing, fleet and recovery
```

## Placement matrix

| Surface | Current evidence | License boundary |
| --- | --- | --- |
| canonical SEAM repository/runtime | implemented private package | proprietary / All Rights Reserved |
| MIRL and HS/1 specifications and implementation | implemented private materials | proprietary / All Rights Reserved |
| planned SEAM-U weights/training/data/inference | no qualified model artifact recorded here | proprietary model boundary |
| thin `seam-client` HTTP SDK | separate published client | Apache-2.0 |
| public API schemas, examples, connectors | partial/separate | Apache-2.0 after artifact inspection |
| source-distributed SEAM SDK | separate repository | PolyForm Shield 1.0.0 plus commercial alternatives |
| source-distributed SEAM Node | separate scaffold/product | PolyForm Shield 1.0.0 plus commercial alternatives |
| hosted control plane and customer operations | service, not a source grant | proprietary commercial/service terms |
| names, logos, mascots and trade dress | separate brand assets | trademark policy and copyright reservation |

## Why Shield is not the root license

PolyForm Shield grants broad rights to use, modify, and distribute software for
noncompeting purposes. That is appropriate when operators need the product
source. It is not appropriate for the canonical repository because this tree
contains the readable MIRL runtime, HS/1, private research, benchmarks,
release controls, and other material Canticle does not intend to distribute.

Merely storing a PolyForm license in this package or adding it to package
metadata could create an ambiguous grant. The Shield text therefore lives only
in each separately reviewed SDK/Node product repository and shipped artifact.

## Historical grants

Later policy cannot revoke rights already granted. Exact Apache-2.0 versions
and exact BUSL-1.1 artifacts retain their shipped terms. The old BUSL text is
stored at `LICENSES/HISTORICAL/BUSL-1.1.txt` as evidence, not as a current or
future grant. There is no automatic migration of a historical BUSL artifact to
PolyForm Shield.

## Artifact rule

Before any source leaves this repository:

1. define the receiving product repository and its license;
2. use an allowlist rather than a denylist;
3. scan for MIRL/HS/1/SEAM-U implementation, private prompts, benchmarks,
   records, secrets, and history;
4. inspect the actual wheel, sdist, image, schema bundle, or documentation
   archive;
5. verify package metadata and included license/notice files; and
6. record exact commit, artifact hash, review, release, and deployment states
   separately.

## Commercial licensing

The copyright owner may offer separately negotiated competing-use, OEM,
redistribution, enterprise self-host, warranty, indemnity, support, or private
fork rights. Outside contributions require inbound terms that preserve the
ability to grant those rights.

PolyForm Shield is source-available, not OSI open source. Do not call Shielded
products open source, and do not describe this private repository as
source-available.
