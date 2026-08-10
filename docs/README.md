# SEAM Docs Index

This folder is the active operator and engineering documentation surface.

## Active Docs

- `SEAM_OPERATOR_GUIDE.md` - operator manual for day-to-day commands, doctor checks, benchmark posture, and failure triage (Windows, macOS, Linux).
- `MACOS.md` - macOS install paths, directory layout, Docker/pgvector, MCP, and troubleshooting.
- `setup.md` - copy/paste setup, dashboard chat model configuration, and supported platform commands.
- `errors.md` - current troubleshooting playbook and error index by symptom/error type.
- `howto/README.md` - short task runbooks.
- `engineering/README.md` - SEAM engineering architecture and change-control manual (architecture, security, change/test/incident SOPs, epistemic calibration, verification matrix, templates) plus the `seam-engineer` routing skill.
- `CODE_LAYOUT.md` - active code, experimental code, generated code, and inactive code boundaries.
- `DATA_ROUTING.md` - logical data routes, topic ledgers, context packs, and corruption-defense checks.
- `handoffs/INDEX.md` - canonical latest handoff pointer and validated
  supersession chain; read its current document during normal startup.
- `SOP_MODEL_INTEGRATION.md` - current model integration procedure.
- `RAG_ARCHITECTURE.md` - current graph/vector/mix retrieval and agent bridge architecture.
- `KNOWLEDGE_GRAPH.md` - self-building all-agent knowledge graph, temporal/provenance model, dashboard, CLI, REST, and MCP surfaces.
- `REASONING_GRAPH.md` - parallel append-only public reasoning graph, its knowledge/evidence boundary, initial Python SDK, and R1-R6 maturity path.
- `IMPROVEMENT_EXPERIMENTS.md` - H2 bounded experiment contract, durable evidence ledger, operator approval boundary, and production scaling path.
- `roadmap/GRAPH_MEMORY_MATURITY.md` - graph-first target architecture and the staged G1-G7 path from identity indexing through hybrid retrieval, context assembly, lifecycle, scale, and qualification.
- `MIRL_V1.md` - current MIRL reference and readable lossless compression contract.
- `HOLOGRAPHIC_SURFACE.md` - SEAM-HS/1 visual memory surface architecture.
- `SOP_HOLOGRAPHIC_SURFACE.md` - operator workflow for encoding, verifying, querying, and importing surfaces.
- `RETRIEVAL_EVAL_V1.md` - current retrieval evaluation reference.
- `SYMBOL_NURSERY.md` - current symbol staging notes.

## Audits

- `audits/INDEX.md` - registry of recorded audits, newest first. Whole-repo
  audits are a repeatable series; the latest one records current open findings
  with file:line evidence and the verification checklist behind each. Read it
  before concluding a defect is new.

## Superseded, retained in place

These are **not** current instructions. Each carries a SUPERSEDED banner and
names deleted modules; they are kept where they are, rather than under
`archive/`, because they are deliberate design input for the future public
edition. Do not execute their steps.

- `SELF_HOST_SECURITY.md` - compiled self-host threat model and entitlement
  boundary from the retired distribution split.
- `SOP_SEAM_SELF_HOST_WHEEL.md` - SOP for a `seam-self-host` PyPI wheel that
  was never built; the split it depends on was retired.

## Archive

- `archive/` holds inactive docs, old handoffs, and historical coding artifacts that should not be treated as current instructions.
- Archived docs are kept for traceability, not as the source of truth for current setup or runtime behavior.
- When a doc is superseded, move it under `archive/` and leave the active replacement linked from this index or `README.md`.

## Source Of Truth

- Current operator setup starts in `setup.md`.
- Current troubleshooting starts in `errors.md`.
- Durable coding history lives in `../HISTORY.md` and `../HISTORY_INDEX.md`.
- Stable repo decisions live in `../REPO_LEDGER.md`.
- Current code layout lives in `CODE_LAYOUT.md`.
- Current data routing and topic-ledger policy lives in `DATA_ROUTING.md`.
- Current tracked recovery state starts at `handoffs/INDEX.md`.
