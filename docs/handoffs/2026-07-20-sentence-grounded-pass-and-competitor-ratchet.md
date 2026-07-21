---
handoff_id: 2026-07-20-sentence-grounded-pass-and-competitor-ratchet
supersedes: 2026-07-20-derived-facts-clause-scope-and-sentence-grounded-next
handoff_status: current
history: HISTORY#439
---

# Handoff: sentence-grounded representation passed free gate; run displacement audit next

- **Date:** 2026-07-20
- **Branch:** `agent/roadmap-zep-after-benchmarks` (draft PR #153)
- **Pushed:** NO. This slice is committed locally only; operator push remains gated.
- **Spend:** $0. Local Ollama and local BGE only; no provider or judge call.

## One-line state

`sentence-grounded-clm/1` is implemented end to end and passed its shared-code
free representation gate. It is still default-off and is **not yet a score
win**. The next ratchet is a full free matched-harness predict-only comparison
that measures evidence presence and displacement before any paid microgate.

## What the competitor audit established

The durable audit is
`docs/audits/2026-07-20-memory-competitor-ratchet.md`. Do not compare headline
scores without their reader, judge, query count, retrieval mode, and context
budget. The transferable finding is narrower:

- Mem0 wins with first-class extracted facts and multi-signal search.
- Hindsight separates world, experience, observation, and opinion memories,
  then searches vector, keyword, graph, and temporal indexes.
- Zep/Graphiti's strongest result manually composes edges, nodes, episodes,
  summaries, and observations; its one-call auto-search result is materially
  lower, isolating composition/routing as leverage.
- Cognee supports the graph-plus-vector/query-routing direction but does not
  publish a full directly comparable current LoCoMo result.

SEAM already owns the generic hybrid retrieval substrate. The missing layer is
better representations searched and packed in reserved scopes, starting with
auditable sentence-grounded facts.

## What landed

- `seam_runtime/sentence_grounded_facts.py`: shared schema, prompt,
  fingerprint, validator, and strict-local Ollama extractor. The model returns
  a paraphrase plus an integer evidence-sentence index; SEAM attaches the exact
  source sentence, offsets, and hash.
- `sentence-grounded-clm/1`: default-off compiler/retrieval policy with
  speaker-canonical facts, RAW preservation, exact provenance, owner-scoped
  cache binding, safe number/negation/speaker guards, and deterministic IDs.
- Retrieval revalidates the source slice/hash, fact hash, sentence bounds,
  canonical speaker, and safety contract before serving the record. The vector
  representation embeds the paraphrase; source evidence remains first in the
  packed context and the existing 20% derived-fact prefix ceiling remains.
- `preflight_sentence_grounded_facts.py`: imports the same runtime code used by
  production; the free gate is not a parallel benchmark-only implementation.

## Exact free gate

Full #429 cat1/cat3 matched-run miss set, local `qwen2.5-7b-1m:latest` and
local BGE:

- 63 misses; 61 with candidate turns; 127 unique candidate turns.
- 229 model fact items; 228 bound to canonical evidence; 199 passed safety.
- 51/63 misses reached by a validated fact.
- 46/63 had a fact closer to the question than the RAW gold turn.
- Binding precision 0.9956; safety acceptance 0.8690.
- Mean wording-closure +0.1138; mean fact/evidence cosine 0.7147.
- All five predeclared thresholds passed. No paid call.

The model is not perfectly deterministic at temperature zero, but repeat runs
held reach/closure stable; safety acceptance moved from 0.9031 to 0.8690.

## Verification

- Real configure -> owner-scoped cache -> compile -> MIRL validation smoke:
  one call, one valid sentence fact, frozen 64-character model fingerprint.
- Affected focused suites: 147 passed before the final facade integration test;
  the final integration slice added four more passing tests.
- Full strict non-external `tests/ -m 'not external'`: exit 0, zero skips, two
  established xfails.
- External pgvector suite with the live local service: 10 passed, zero skips.
- Touched-file Ruff and `git diff --check`: clean. Repo-wide Ruff still reports
  two pre-existing import-order findings in
  `tests/audit/test_pgvector_real_adapter.py`; this slice did not modify them.

## Next ratchet

1. Start a clean candidate facade with `sentence-grounded-clm/1` and run the
   pinned upstream Mem0 harness in **predict-only** mode over cat1+cat3.
2. Compare baseline and candidate for gold-evidence presence, derived-fact
   placement, source-before-fact ordering, pack displacement, and a sentinel
   set of previously correct cases. This remains free.
3. Only if the displacement gate is clean, request operator approval for a
   paired paid microgate. Promote only at net +2 or better across 378 cat1+cat3
   questions (+0.53 points) with zero sentinel losses.
4. Next architectural rung after a positive score gate: reserved multi-scope
   packing, then evidence-backed observations/entity summaries and a
   query-shape router. Do not jump straight to blind multi-query expansion.

Unrelated local `report*.png` files are operator-owned and excluded from this
slice.
