---
handoff_id: 2026-07-22-graph-source-raw-lane
supersedes: 2026-07-22-fact-free-auxiliary-raw-ablation
handoff_status: current
history: HISTORY#453
---

# Handoff: query-conditioned graph -> source-RAW lane (default-off infra)

**For:** the next agent running the provider-free held-out measurement and, if
it wins, refining concept seeding.
**Date:** 2026-07-22
**Branch:** `agent/graph-source-raw-lane` (built on the operator commit
`e9ab8d3`; PR-ready after closeout, not yet pushed).
**Spend:** zero provider/paid calls. Local ingest + graph projection only.

## One-line state

The graph -> source-RAW infrastructure slice is **built, hermetically tested,
and end-to-end verified against the real knowledge-graph projection**, default
off. It is a mechanism + wiring deliverable; the provider-free held-out
evidence/displacement **measurement has not been run yet** and no benchmark or
promotion claim is made.

## What landed

- **`seam_runtime/graph_source_selector.py`** — a pure, read-only,
  query-conditioned selector. Given a query it finds lexically-matched *concept*
  seed nodes, follows current in-scope `knowledge_edges` incident to them through
  `knowledge_edge_episodes` -> `knowledge_episodes.source_record_id`, and returns
  the exact source RAW ids that clear a **multi-node agreement** bar, with a full
  auditable trace (`GraphSourceSelection`: agreement, covered_tokens, seed_ids,
  edge_ids, score, and per-`GraphSourcePath` seed/edge/episode/source). It
  **invents no source text** — ids and provenance only.
  - *Current-state / scope filtering:* excludes contradicted/superseded/
    deprecated/deleted_soft/refuted/stale and expired edges and episodes, and
    filters ns/scope on both, so cross-scope and non-current evidence never
    corroborate.
  - *Agreement is token-coverage, not raw node count:* `agreement` counts the
    number of **distinct query tokens** independently corroborated by seed nodes
    reaching the RAW. This was the key correctness fix (see the verification
    finding below): one real-world concept represented by several nodes cannot
    inflate agreement, and a single content-bearing node cannot cover multiple
    tokens (entity/relation/event/state seeds match on their id, only the short
    concept kinds value/agent/symbol match on label).
- **Facade wiring** in `benchmarks/external/mem0_harness/seam_mem0_server.py`:
  default-off policy `graph-source-raw/1` (env `SEAM_GRAPH_SOURCE_RAW_POLICY`,
  CLI `--graph-source-raw-policy`). `_apply_graph_source_raw_policy` runs primary
  RAW once, calls `_search_graph_source_raw` to independently select at most 3
  corroborated source RAW rows (min agreement 2), then folds them into a
  `compose_non_displacing_raw_pack` (HISTORY#452). It is a **standalone lane**:
  it does not stack second-hop/count/temporal/graph-fill/fact splicers, graph
  candidates never enter or perturb primary ranking, and it fails closed to the
  exact primary object when there is no novel corroborated RAW. Off path is
  object-identical.
- **Tests:** `tests/audit/test_graph_source_selector.py` (15, hermetic in-memory
  graph: two independent paths select one RAW; single noisy adjacency rejected;
  one concept across multiple nodes does not inflate; content-bearing kinds do
  not seed; contradicted/superseded/expired/cross-scope excluded; deterministic
  ties; exact source id; no text field; limit/min_agreement/tokenize). Facade
  on/off/no-rows/unknown-policy cases in `tests/audit/test_seam_mem0_server.py`.

## Verification (the real-projection finding that shaped the design)

A real end-to-end smoke (3 turns ingested through the facade, no derived facts)
exposed that the deterministic graph projection **embeds the originating RAW
turn text in concept-node labels** and represents one concept as several nodes
(entity + value + claim). Naive lexical seed-matching therefore over-counted
same-turn nodes and would have degraded "multi-node agreement" into plain token
presence. The fix — token-coverage agreement plus id-based matching for
content-embedding kinds — was verified on the same real store:

- `"Alice Bob"` -> agreement 2, covered tokens {alice, bob} (genuine two-term
  corroboration);
- `"Carol"` (one concept, entity + value nodes) -> **rejected** (agreement 1);
- `"coffee tea"` -> agreement 2, covered tokens {coffee, tea}.

The composer also correctly declined to pack when the selected source RAW was
already present in the primary results (non-novel -> exact fallback).

## Honest boundary / known limitation

Concept seeding is still lexical over an imperfect projection: entity labels
embed content and objects become opaque-id `value` nodes, so agreement is a
useful-but-approximate proxy for "distinct query concepts corroborate this RAW."
Whether that proxy adds real evidence beyond lexical RAW retrieval is exactly
what the held-out measurement must decide. A cleaner long-term fix is a
projection-side concept label/index, not more lexical heuristics.

## Next steps

1. **Provider-free held-out measurement.** Pick a fresh LoCoMo scope NOT used to
   tune anything (not the adaptive 130). Ingest it through the facade (plain, no
   derived facts), record predict-only retrieval with `SEAM_GRAPH_SOURCE_RAW_POLICY`
   off (baseline) and `graph-source-raw/1` (candidate), then run
   `preflight_displacement_audit`. Gate: >= 1 net miss gold gain and zero
   sentinel loss before any promotion or paid judge. This is the promotion gate;
   do not quote the tuning smoke as evidence.
2. If it wins, consider deduping concepts by canonical identity and/or a
   projection-side concept index; then productize into core `RetrievalFlags`
   (per "productize to core, not the benchmark").
3. If it is flat, park it default-off with the honest negative and return to the
   next architectural lever.

## Guardrails (retained)

- Default-off; no live promotion, cloud ingest, answerer, judge, or paid call
  without fresh operator approval. No installs/downloads.
- No Claude/agent attribution in commits or docs.
- Operator-owned `.ua/`, `seam_runtime/.ua/`, and the `report*.png` files remain
  untouched and excluded.

## Closeout verification

Affected slice 64/64 (`test_graph_source_selector.py` 15,
`test_seam_mem0_server.py` 33, `test_multi_scope_pack.py` 16). Full `pytest
tests/` result recorded in HISTORY#453. Ruff/compileall clean on touched files.
No provider call, no paid work, no push.
