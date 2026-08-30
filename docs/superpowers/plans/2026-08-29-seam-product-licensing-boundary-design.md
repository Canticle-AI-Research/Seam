# SEAM Product and Licensing Boundary Design

**Date:** 2026-08-29

**Status:** Operator-approved design; not yet implemented or counsel-reviewed

**Scope:** SEAM, SEAM Suite, SeamSDK, seam-client, Ghost, MIRL, SEAM-HS/1,
the Improvement Loop, browser dashboards, and benchmark surfaces

This document records the product direction approved by the operator. It is a
design contract, not a license grant. Existing releases retain the licenses
under which their exact versions were published. No source file, package, or
artifact is relicensed until the implementation plan applies the boundary,
artifact verification passes, the operator reviews the exact result, and the
required legal review is complete.

## 1. Governing direction

SEAM remains one coherent, complete memory product. The self-host edition is
not a reduced substitute for a private runtime. A self-host operator receives
the actual SEAM product capabilities needed to run and host SEAM.

The product has three licensing layers:

1. an open-source adoption and presentation layer;
2. a PolyForm Shield 1.0.0 source-available product layer; and
3. undistributed managed-service, private-evidence, credential, and operator
   material that receives no public distribution grant.

MIRL, SEAM-HS/1, and the Improvement Loop are the specially protected core.
They remain readable and source-available to licensed users but are not open
source. The source-available in-process SeamSDK and Ghost also use the
PolyForm Shield license family. Open-source clients and frontends remain
separate modules and do not make the protected backend open source.

## 2. Product ownership

| Product or module | Responsibility | Boundary |
| --- | --- | --- |
| SEAM | Durable memory, canonical knowledge, provenance, retrieval, lifecycle, and evidence | Source-available product |
| SEAM Self-Host | Complete operator-run SEAM product | Source-available distribution |
| SEAM Suite | TUI control center plus graph, provenance, and benchmark operator dashboards | Mixed distribution with explicit module licenses |
| Managed SEAM | Canticle-operated API and WebUI offering | Managed product; hosted internals are not automatically distributed |
| Ghost | Agent behavior, goals, planning, tools, and SEAM use | Source-available SEAM agent |
| SeamSDK | In-process access to full SEAM capabilities | Source-available developer interface |
| seam-client | Opaque HTTP access to the public agent interface | Open-source integration client |

Ghost is a SEAM agent, not a separate memory platform. It may be installed and
launched alongside SEAM Suite, but Ghost does not own canonical memory, MIRL,
the graph truth boundary, or benchmark evidence. Ghost and SeamSDK remain
separate modules so agent behavior, developer access, and the protected memory
language cannot be conflated.

## 3. License matrix

### 3.1 Open-source layer

The following modules are intended to use Apache License 2.0 unless an exact
artifact records another operator-approved open-source license:

- `seam-client`, the public opaque HTTP client;
- public API schemas, request and response models, compatibility contracts,
  examples, and contract tests;
- framework and protocol connectors that use documented public interfaces and
  do not copy protected implementation;
- the TUI presentation and control-center frontend;
- the WebUI application shell and reusable operator-interface frontend;
- generic two-dimensional and three-dimensional graph renderers that consume
  a neutral node-and-edge payload;
- Benchmark Glassbox presentation, real charting, result comparison, and
  public report formats;
- public provenance receipt, verification, and interchange formats;
- deployment launchers and installation tooling that do not embed protected
  implementation; and
- examples and tests limited to open interfaces.

Open-source permission includes competitive and commercial use under the
applicable license. SEAM, MIRL, Ghost, and Canticle names, marks, visual
identity, and certification claims are not granted by an open-source code
license.

### 3.2 PolyForm Shield source-available layer

The following modules are intended to use the unmodified PolyForm Shield
License 1.0.0 with the required notices and separately documented commercial
licensing path:

- the SEAM runtime and self-host backend;
- the in-process SeamSDK;
- Ghost's agent implementation;
- MIRL specifications and implementation;
- SEAM-HS/1 specifications and implementation;
- the Improvement Loop specifications and implementation;
- SEAM-specific graph projection, query, evidence, and reconciliation logic;
- SEAM-specific benchmark execution and protected evaluation logic; and
- server implementations of operator interfaces that expose full SEAM
  capability.

PolyForm Shield is source-available, not open source. It permits use,
modification, and distribution for permitted purposes while excluding products
that compete with the licensor or its affiliates. Uses outside that grant
require separate written commercial terms.

The project must use the official PolyForm Shield 1.0.0 text without editing
its terms. Product-specific scope, copyright, line-of-business, attribution,
and trademark statements belong in required notices and companion policy
documents rather than modifications to the standard license text.

### 3.3 Undistributed and separately controlled material

The following material is not part of either public source distribution merely
because it exists in a development repository:

- credentials, tokens, customer data, operator databases, and private
  configuration;
- private benchmark holdouts or datasets whose licenses prohibit
  redistribution;
- unpublished research artifacts and internal evaluation evidence;
- managed-service infrastructure, abuse controls, billing, customer
  operations, and private control-plane implementation unless expressly
  published; and
- third-party materials outside the redistribution rights granted by their
  owners.

Every such exclusion requires an artifact rule; repository location alone is
not an adequate license or release boundary.

## 4. Protected core

All original SEAM code and documentation is copyrighted when created. The term
**Protected Core** has the narrower product meaning established here: the
project gives special source-available protection to MIRL, SEAM-HS/1, and the
Improvement Loop.

### 4.1 MIRL

The MIRL boundary includes its authored specification, schemas and field
arrangement, record implementation, compilation and decompilation,
canonicalization, evidence binding, reconciliation, PACK and symbol machinery,
and MIRL-specific storage and projection logic.

### 4.2 SEAM-HS/1

The HS/1 boundary includes its authored specification and container
expression, encoding and decoding, packing, hashing, verification, repair,
surface query, and HS/1-specific rendering or storage implementation.

### 4.3 Improvement Loop

The Improvement Loop boundary includes SEAM-specific machinery that proposes,
evaluates, promotes, rejects, reverses, or learns changes to representations,
symbols, compression, retrieval policy, graph policy, or other SEAM operating
policy from evidence. It does not include generic progress indicators, chart
libraries, public result formats, or an external benchmark's independently
licensed runner.

The protected-core designation applies to original expression and licensed
implementation. It does not assert copyright ownership over abstract ideas,
facts, systems, methods of operation, mathematical relationships, or short
names.

## 5. Interfaces and information flow

SEAM uses two interfaces with different consumers:

- The **Public Agent Interface** is stable, opaque, and suitable for external
  agents. The Apache-2.0 `seam-client` consumes it. It does not expose MIRL,
  HS/1, protected Improvement Loop internals, storage paths, private ranking
  policy, or administrative authority.
- The **Operator Interface** supports authenticated administration, graphs,
  provenance, benchmarks, lifecycle operations, and runtime control. SEAM
  Suite and the managed WebUI consume it. Its server implementation is part of
  the source-available SEAM product even when a frontend consuming it is open
  source.

An interface definition may be open source while the implementation behind it
is source-available. A frontend license never changes the license of data,
algorithms, or server implementation received through that interface.

## 6. SEAM Suite composition

SEAM Suite is the self-host operator experience:

- **TUI Control Center:** health, configuration, ingestion, jobs, agent status,
  and launch controls for browser dashboards;
- **Graph Dashboard:** independently openable knowledge, reasoning, and
  provenance views backed by real graph data;
- **Benchmark Glassbox:** free or local runs, explicitly approval-gated paid
  runs, progress, real interactive graphs, results, comparisons, and exact
  evidence; and
- **Ghost integration:** registration, status, and activity for Ghost as a
  SEAM agent without absorbing Ghost into the SEAM memory implementation.

The TUI does not attempt to render the browser graph product. Terminal ASCII is
available only for textual explanations or deliberately requested terminal
summaries. Benchmark trends and graph exploration use real browser-rendered
visualizations.

The TUI, public WebUI frontend, graph renderer, and Benchmark Glassbox frontend
may be open-source modules inside a distribution whose SEAM backend is
PolyForm Shield. Every build must preserve the module-level license boundary
in source archives, binary metadata, notices, and generated software bills of
materials.

## 7. Historical license continuity

This design does not retract or replace an existing license grant:

- exact Legacy Apache-2.0 versions remain Apache-2.0;
- exact published BUSL versions remain governed by their published BUSL terms
  and Change Dates;
- exact published `seam-client` versions retain Apache-2.0; and
- no unpublished or later version inherits a historical license merely through
  filename, ancestry, interface, or purpose.

The implementation must inventory every previously published package and
version before changing current package metadata. Historical artifacts may be
deprecated or superseded, but their granted rights cannot be revoked.

## 8. Artifact and repository rules

The approved model requires separation by construction:

1. Every distributed module has one declared license expression that matches
   its actual contents.
2. Mixed distributions include the complete applicable license and notice set
   and identify which module each license governs.
3. Each source file carries the correct SPDX identifier or approved notice.
4. Build manifests enumerate every shipped file and its license class.
5. Artifact verification rejects protected files from open-source packages and
   rejects missing or contradictory license metadata.
6. The public client cannot import or dynamically recover source-available
   runtime modules.
7. Open-source graph and benchmark frontends consume neutral, versioned
   payloads rather than importing MIRL or Improvement Loop implementation.
8. Third-party dependencies, datasets, fonts, icons, graph libraries, and chart
   libraries retain their own terms and appear in the artifact inventory.
9. Branding and trademark permissions remain separate from software licenses.
10. No release or publication occurs until the operator approves the exact
    artifact and legal review confirms the intended grant.

## 9. Roadmap consequences

The roadmap must record a licensing-and-artifact stage before SEAM Suite
implementation:

1. replace the contradictory proprietary/BUSL/Apache package expression with
   module-specific licensing and manifests;
2. preserve one complete SEAM behavioral product while separating its
   distributable modules cleanly;
3. identify the open-source frontend, client, connector, and verification
   modules;
4. apply PolyForm Shield to the source-available SEAM, SeamSDK, Ghost, MIRL,
   HS/1, and Improvement Loop modules;
5. establish the Public Agent Interface and Operator Interface as distinct
   contracts;
6. supersede roadmap work that assigns ASCII graphs to the TUI;
7. build real graph views and benchmark charts in browser surfaces;
8. preserve free or local benchmark execution and explicit authorization for
   every paid run; and
9. gate every release on license inventory, artifact-boundary verification,
   continuity verification, operator review, and legal review.

This licensing stage changes documentation, packaging, and release policy. It
does not itself prove that SEAM Suite, a public self-host artifact, or a managed
operator surface has been implemented, published, deployed, or legally
qualified.

## 10. Acceptance criteria for implementation planning

Implementation planning may begin after the operator confirms that this
written design expresses the approved direction. The plan must then produce:

- an exact module and repository inventory;
- proposed final license and notice text without modifying standard license
  terms;
- an explicit migration for current package metadata and historical packages;
- artifact manifests and automated boundary tests;
- roadmap, status, ledger, glossary, and public documentation updates;
- no changes to unrelated TUI or licensing worktrees;
- a counsel-review checkpoint before publication; and
- a publication plan that treats local, committed, merged, released, and
  deployed states as distinct.
