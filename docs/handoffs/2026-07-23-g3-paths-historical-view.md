---
handoff_id: 2026-07-23-g3-paths-historical-view
supersedes: 2026-07-22-reasoned-retrieval-g3a
handoff_status: current
history: HISTORY#466
---

# Handoff: G3 exact paths and historical graph view

**Date:** 2026-07-23
**Branch:** `agent/g3-historical-view` (from `origin/main` at `ec614a7`)
**Spend:** zero provider, paid-model, install, or download actions.

## One-line state

G3 remains partial. This increment closes two provenance/temporal gaps from
G3a: graph hits reached at hop >=1 return exact deterministic paths with their
visible episode backtraces, and retrieval can traverse the graph at a requested
time or across history using the same validity semantics as the knowledge-graph
surface.

## What changed

- `GraphPathHop`, `LegHit.path`, and `RetrievalCandidate.graph_path` expose a
  deterministic shortest edge chain without changing ranking; non-graph legs
  remain path-free.
- `SQLiteGraphAdapter` records the deterministic parent edge during each
  bounded traversal, reconstructs paths after the search, and resolves backing
  episodes in one query scoped to the selected graph time view.
- `graph_at` and `graph_include_history` flow through the planner,
  orchestrator, and `ReasoningSession.retrieve`. The append-only retrieval
  decision stores them via an additive database migration, so a historical
  decision remains auditable as the exact time-view request that produced it.
- Node, edge, and episode filtering reuses `knowledge_graph.py`'s current,
  history, and point-in-time predicates. Candidate expansion remains bounded;
  input ids are chunked only to respect SQLite's parameter limit.

## What this does not change

- No score, rank, fusion-policy, vector-index, PACK, or persisted candidate
  ledger ordering change.
- No new canonical truth or graph product: RAW/MIRL and the knowledge graph
  remain canonical, and paths are read-only provenance.
- This is not full G3 or graph maturity. Semantic vectors for entity/value/
  agent/symbol nodes, calibrated cross-leg fusion, and corpus-scale latency and
  quality qualification remain. G4-G7 and R3-R6 remain open.

## Verification

- Direct graph/reasoning/provenance slice: 93 passed with no skips.
- `pytest tests/ -m "not external"`: 1,411 passed, 23 external tests
  deselected, and two established xfails; zero failures or skips.
- Touched-file Ruff, compileall, and `git diff --check` pass.

## Next stage

Implement a fixed, versioned calibrated or rank-normalized cross-leg fusion
policy, then add bounded corpus-scale query-shape/latency qualification. Do not
claim G3 complete until those remaining gates pass.

## Guardrails

- No provider or paid work without explicit operator approval.
- Preserve unrelated `.ua/`, pricing documents, and `report*.png` artifacts.
- Keep CLI/REST/MCP adapters thin over the SDK; do not expose reasoning SQLite
  tables as an integration contract.
