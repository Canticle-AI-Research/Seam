---
handoff_id: 2026-07-23-g3-rank-fusion-scale-qualification
supersedes: 2026-07-23-g3-paths-historical-view
handoff_status: current
history: HISTORY#467
---

# Handoff: G3 rank-normalized fusion and scale qualification

**Date:** 2026-07-23
**Branch:** `agent/g3-historical-view` (continued from pushed commit `f7632e1`)
**Spend:** zero provider, paid-model, install, or download actions.

## One-line state

G3 remains partial, but its cross-leg ranking and synthetic scale gates are now
fixed: new retrievals use versioned reciprocal-rank fusion, and a provider-free
2,048-node fixture qualifies five query shapes for evidence, path, isolation,
determinism, cross-leg behavior, and latency.

## What changed

- `reciprocal-rank-fusion/2` replaces raw cross-domain addition. Within each
  leg, duplicate record hits keep their best raw score; deterministic rank
  contributes `1 / (60 + rank)`; the fused score is the sum of contributions;
  record ID breaks final ties.
- Raw leg scores stay in `LegHit` traces. `RetrievalCandidate.sources` and new
  R2 rows carry exact normalized contributions, while `source_ranks` makes the
  live trace explicit. R2 validation rejects contributions that do not encode a
  legal rank and recomputes the pinned fused score and order.
- `tools.graph_retrieval_qualification` builds an isolated temporary SQLite
  graph and covers structured filter, lexical 1-hop, lexical 3-hop, historical
  3-hop, and semantic-seeded mixed retrieval. The tool makes no network or
  provider calls and leaves no corpus artifact in the working tree.
- The active retrieval-orchestrator README, graph/reasoning docs, roadmap
  maturity boundary, stable ledger, and public-core manifest now match the
  runtime contract.

## Qualification evidence

Command:

```text
.venv/bin/python -m tools.graph_retrieval_qualification \
  --nodes 2048 --repeats 5 --max-latency-ms 250
```

Result: all five shapes passed on 2,048 nodes, 2,047 edges, and 4,096 total
records. Observed p95 latency was 7.714 ms structured, 17.939 ms 1-hop,
30.013 ms 3-hop, 25.985 ms historical 3-hop, and 43.262 ms mixed
semantic-seeded. These are local provider-free fixture measurements, not a
real-corpus quality or backend-scale claim.

## Verification

- Focused collection: 108 tests across reasoning retrieval, qualification,
  public manifest, and knowledge graph; all 108 passed.
- `pytest tests/ -m "not external"`: 1,420 collected, 1,418 passed, two
  established xfails, zero failures or unexplained skips.
- `pytest test_seam_all/test_seam.py`: 189 passed.
- Touched-file Ruff, compileall, `git diff --check`, public-manifest checks,
  and secret/private-session-URL scans pass.
- CodeRabbit CLI 0.7.0 accepted the staged uncommitted diff twice but emitted
  only connection/setup/analysis status events and no findings summary. Treat
  the external review as unavailable, not as a zero-finding result.

## What remains

- Semantic vectors for entity, value, agent, and symbol graph nodes.
- Real-corpus retrieval quality qualification and backend-specific scale
  evidence before calling G3 complete.
- G4-G7 and R3-R6 remain open.

## Next stage

Design and implement the versioned graph-node vector projection for
entity/value/agent/symbol nodes. Keep it derived from canonical MIRL/graph
state, namespace/scope-prefiltered, explicit-reindex migrated, and provider-free
by default. Then measure the completed G3 mechanism on a predeclared real corpus
without blending that result into G7 competitor claims.

## Guardrails

- No provider or paid work without explicit operator approval.
- Preserve unrelated `.ua/`, pricing documents, architecture-audit, and
  `report*.png` artifacts.
- Keep CLI/REST/MCP adapters thin over the SDK; do not expose reasoning SQLite
  tables as an integration contract.
