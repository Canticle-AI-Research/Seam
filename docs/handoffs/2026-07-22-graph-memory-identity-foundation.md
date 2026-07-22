---
handoff_id: 2026-07-22-graph-memory-identity-foundation
supersedes: 2026-07-22-graph-source-raw-lane
handoff_status: current
history: HISTORY#454
---

# Handoff: graph-memory identity foundation (G1)

**Date:** 2026-07-22
**Branch:** `agent/graph-memory-identity-foundation`
**Spend:** zero provider/paid calls; local SQLite projection and tests only.

## One-line state

Track R is now graph-first, and G1 is complete: SEAM has a versioned scoped
concept-term/alias index, episode-grounded extracted entities, and
concept-aware graph-to-source paths over exact RAW evidence.

## What changed

- `knowledge-graph/5` adds rebuildable `knowledge_node_terms` rows carrying
  canonical terms, explicit aliases, tokens, scope, and source-record
  provenance. Sentence-like values and assertion/source labels are excluded.
- `compile_nl` attaches its compile provenance record to every extracted ENT,
  making episode/entity mention lineage explicit in MIRL and the graph.
- `select_graph_source_raw` seeds only from indexed concepts and follows both
  semantic edges and `knowledge_node_episodes` mention paths to exact RAW ids.
  Agreement is maximum one-to-one concept/token matching, with explicit
  `matched_pairs`; duplicate nodes cannot reuse one query token, and one long
  concept label can contribute only once.
- `query_graph` resolves indexed alias/token matches in addition to its existing
  graph search fields. Graph stats expose term and alias counts.
- Track R and `docs/roadmap/GRAPH_MEMORY_MATURITY.md` now define a G1-G7
  graph-first build: identity index, reversible resolution, hybrid path search,
  graph products, context assembly, lifecycle/scale, then qualification.

## Verification

- affected collection: 200 tests across graph selector/projection/deep graph,
  trust/ratchet, workspace, facade, PACK, compiler/coreference, and extraction;
  all 200 passed;
- full `tests/`: 1,327 collected, exit 0, two established xfails, zero skips,
  with downloads forced offline and the existing healthy local pgvector service;
- touched-file Ruff, compileall, and `git diff --check` clean;
- CodeRabbit found four minor issues (negative LIMIT guard, alias fixture kind,
  blank terms, embedded-period literals); all were fixed and its second pass
  returned zero findings;
- real projector smoke: alias `IBM` indexed; sentence-like value terms absent;
  `Alice Bob` selected the exact RAW with agreement 2 through edge + mention
  paths.

## Next graph stage: G2 reversible identity resolution

Build an append-only identity-decision layer, not another destructive exact
label merge:

1. generate alias/coreference candidates with evidence and confidence;
2. represent `canonical_of` / merge decisions explicitly while retaining both
   original entity records;
3. support conflict, reject, undo, and split transitions;
4. make graph search expand approved identity groups while preserving the exact
   contributing node and episode path;
5. gate namespace/scope isolation, determinism, backfill, and deletion behavior
   before G3 semantic + lexical + path fusion.

No benchmark win or Zep-parity claim is attached to G1. Benchmarks qualify
completed stages; they no longer gate building missing graph substrate.

## Guardrails

- RAW/MIRL remain canonical truth; the graph and term index remain rebuildable
  projections.
- No silent merge, invented alias, cross-scope identity, or evidence-free
  summary/observation.
- Operator-owned `.ua/`, `seam_runtime/.ua/`, and `report*.png` files remain
  untouched and excluded.
