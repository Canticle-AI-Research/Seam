# SEAM Docs Index

This folder is the active operator and engineering documentation surface.

## Active Docs

- `setup.md` - copy/paste setup, dashboard chat model configuration, and supported platform commands.
- `errors.md` - current troubleshooting playbook.
- `howto/README.md` - short task runbooks.
- `engineering/README.md` - SEAM engineering architecture and change-control manual (architecture, security, change/test/incident SOPs, epistemic calibration, verification matrix, templates) plus the `seam-engineer` routing skill.
- `CODE_LAYOUT.md` - active code, experimental code, generated code, and inactive code boundaries.
- `DATA_ROUTING.md` - logical data routes, topic ledgers, context packs, and corruption-defense checks.
- `SOP_MODEL_INTEGRATION.md` - current model integration procedure.
- `RAG_ARCHITECTURE.md` - current graph/vector/mix retrieval and agent bridge architecture.
- `MIRL_V1.md` - current MIRL reference and readable lossless compression contract.
- `HOLOGRAPHIC_SURFACE.md` - SEAM-HS/1 visual memory surface architecture.
- `SOP_HOLOGRAPHIC_SURFACE.md` - operator workflow for encoding, verifying, querying, and importing surfaces.
- `RETRIEVAL_EVAL_V1.md` - current retrieval evaluation reference.
- `SYMBOL_NURSERY.md` - current symbol staging notes.

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
