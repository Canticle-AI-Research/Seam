# SEAM Documentation Map

[Back to the SEAM Wiki](README.md)

This is the progressive-disclosure inventory for SEAM documentation. Start
with a task route, enter a collection only when needed, and open an individual
page only for the claim or procedure it owns. The map indexes existing sources
of truth; it does not restate their volatile contents.

Authority and evidence labels are defined by the
[engineering manual](engineering/README.md#authority-order). In particular,
authored roadmaps and prompts are not implementation evidence.

## Level 1 — task routes

| Task | Primary route |
| --- | --- |
| Understand the product contract | [SEAM specification](../SEAM_SPEC_V0.1.md) → [MIRL v1](MIRL_V1.md) |
| Understand product and licensing terms | [SEAM product language](../CONTEXT.md) → [Product and licensing boundary design](superpowers/plans/2026-08-29-seam-product-licensing-boundary-design.md) → [Packaging/licensing status](status/packaging-licensing.md) |
| Install, configure, or operate SEAM | [Operator guide](SEAM_OPERATOR_GUIDE.md) → [Setup](setup.md) → [How-to runbooks](howto/README.md) → [Errors](errors.md) |
| Understand system architecture | [Engineering architecture](engineering/01_ARCHITECTURE.md) → [RAG architecture](RAG_ARCHITECTURE.md) |
| Change or verify code | [Engineering manual](engineering/README.md) → [Verification matrix](engineering/VERIFICATION_MATRIX.md) |
| Determine current state | [Status streams](status/index.md) → [Project-status headline router](../PROJECT_STATUS.md) → [Current handoff](handoffs/INDEX.md) |
| Explore plans | [Derived roadmap state](../.seam/streams/roadmap/state.md) → [Roadmap collection](roadmap/README.md) |
| File or find a SEAM report | [Reports and evidence](REPORTS_AND_EVIDENCE.md) → [Audit registry](audits/INDEX.md) → [History index](../HISTORY_INDEX.md) |
| Inspect evidence and chronology | [History index](../HISTORY_INDEX.md) → [Reports and evidence](REPORTS_AND_EVIDENCE.md) → [Progress tables](progress_tables/README.md) |
| Research retrieval and benchmarks | [Knowledgebase](kb/README.md) → [Benchmark SOP](BENCHMARK_SOP.md) → [Retrieval evaluation](RETRIEVAL_EVAL_V1.md) |
| Work with branding and surfaces | [Branding hub](../branding/README.md) → [Identity kit](../branding/kit/README.md) → [Cosmic UI kit](../branding/canticle-cosmic-kit/README.md) |

## Level 2 — collection indexes

The wiki reaches each collection through the entrypoint below. Complete
collection indexes expose their pages recursively; when a legacy entrypoint
renders page names as code instead of links, Level 3 supplies the direct links.

| Collection | Index | Authority / use |
| --- | --- | --- |
| Engineering manual and templates | [Engineering](engineering/README.md) | Stable architecture and change-control procedures; it routes into the complete templates index. |
| Current-state streams | [Status](status/index.md) | Current state by concern; chronology belongs in history. |
| Authored plans | [Roadmaps](roadmap/README.md) | Planned direction only, never implementation evidence. |
| Standard operating procedures | [SOP index](SOP_INDEX.md) | Procedures and bounded task packets; verify present applicability before execution. |
| Reusable execution prompts | [Prompt library](prompts/README.md) | Inputs for agents, not evidence that work ran. |
| Stable routed facts | [Topic ledgers](ledgers/README.md) | Durable facts by route; chronological changes remain in history. |
| Recorded audits | [Audit registry](audits/INDEX.md) | Dated findings and measurements with their own scope and evidence boundary. |
| Recovery state | [Handoff registry](handoffs/INDEX.md) | One current handoff head plus a validated historical supersession chain. |
| Retrieval research | [Knowledgebase](kb/README.md) | Memory-system research, evaluation traps, and measured internal learnings. |
| Operator runbooks | [How-to runbooks](howto/README.md) | Command-first daily workflows. |
| Derived human tables | [Progress tables](progress_tables/README.md) | Summaries that cite history; history remains authoritative. |

## Level 3 — standalone active references

### Product and representation contracts

- [SEAM product language](../CONTEXT.md) — stable product and licensing
  glossary.
- [Product and licensing boundary design](superpowers/plans/2026-08-29-seam-product-licensing-boundary-design.md)
  — approved target separation; not an implemented license grant.
- [MIRL v1](MIRL_V1.md) — canonical memory IR and readable-lossless contract.
- [Holographic Surface](HOLOGRAPHIC_SURFACE.md) — SEAM-HS/1 architecture.
- [Symbol Nursery](SYMBOL_NURSERY.md) — symbol staging and evaluation notes.

The repository-root [SEAM specification](../SEAM_SPEC_V0.1.md) governs product
behavior together with MIRL v1.

### Operator and integration references

- [SEAM Operator Guide](SEAM_OPERATOR_GUIDE.md)
- [Setup](setup.md)
- [Troubleshooting and errors](errors.md)
- [macOS](MACOS.md)
- [Local pgvector](PGVECTOR_LOCAL.md)
- [Public SDK API](PUBLIC_SDK_API.md)

### Architecture, storage, and repository policy

- [Code layout](CODE_LAYOUT.md)
- [Data routing](DATA_ROUTING.md)
- [RAG architecture](RAG_ARCHITECTURE.md)
- [Knowledge graph](KNOWLEDGE_GRAPH.md)
- [Reasoning graph](REASONING_GRAPH.md)
- [Improvement experiments](IMPROVEMENT_EXPERIMENTS.md)
- [SQLite migrations](SQLITE_MIGRATIONS.md)
- [Protection model](PROTECTION_MODEL.md)
- [Engineering log](ENGINEERING_LOG.md) — append-only historical and
  operational lessons, not current status or policy.

### Benchmark and evaluation references

- [Reports and evidence](REPORTS_AND_EVIDENCE.md) — canonical filing and
  artifact-routing rules for every new human-readable SEAM report.
- [Benchmark SOP](BENCHMARK_SOP.md)
- [Benchmark run records](BENCHMARK_RUN_RECORDS.md)
- [Retrieval evaluation v1](RETRIEVAL_EVAL_V1.md)

### Retrieval knowledgebase pages

The [knowledgebase home](kb/README.md) explains how these research notes are
maintained. Its page names are rendered as code, so the wiki links every page
directly here as well:

- [Benchmark traps](kb/eval-methodology/benchmark-traps.md)
- [LoCoMo / Mem0 harness](kb/eval-methodology/locomo-mem0-harness.md)
- [LangMem, Letta, and Cognee](kb/memory-systems/langmem-letta-cognee.md)
- [Mem0](kb/memory-systems/mem0.md)
- [SEAM positioning](kb/memory-systems/seam-positioning.md)
- [Zep / Graphiti](kb/memory-systems/zep-graphiti.md)
- [Derived facts and grounded CLM](kb/seam-internals/derived-facts-grounded-clm.md)
- [Lever graveyard](kb/seam-internals/lever-graveyard.md)

### Commercial drafts

- [Pricing tiers](pricing-tiers.md)
- [Pricing terms and conditions](pricing-terms.md)

### Navigation and planning support

- [SEAM Wiki home](README.md)
- [This documentation map](DOCUMENTATION_MAP.md)
- [SOP index](SOP_INDEX.md)
- [Advisor/executor planning artifact](superpowers/plans/2026-05-22-advisor-executor-loop.md) — a plan artifact, not implementation evidence.

## Historical and non-current material

The following paths are deliberately retained for provenance. They are
**historical/non-current** and must not be used as present operator
instructions or implementation proof:

- `docs/archive/**` — enter only through the [documentation archive notice](archive/README.md).
- `docs/status_archive/**` — the [pre-stream project-status snapshot](status_archive/2026-07-30-project-status-full.md) is historical; current state starts at the [status index](status/index.md).
- [SELF_HOST_SECURITY.md](SELF_HOST_SECURITY.md) — historical threat model for the retired compiled self-host distribution split.
- [SOP_SEAM_SELF_HOST_WHEEL.md](SOP_SEAM_SELF_HOST_WHEEL.md) — historical SOP for that retired split; **do not execute it**.

If historical prose becomes useful again, rewrite the current portion into an
active authoritative page and retain a pointer to its history instead of
reviving stale instructions wholesale.
