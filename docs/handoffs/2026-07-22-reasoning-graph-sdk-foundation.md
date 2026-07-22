---
handoff_id: 2026-07-22-reasoning-graph-sdk-foundation
supersedes: 2026-07-22-graph-memory-identity-foundation
handoff_status: current
history: HISTORY#461
---

# Handoff: parallel reasoning graph and SDK foundation (R1)

**Date:** 2026-07-22
**Branch:** `agent/graph-memory-identity-foundation`
**Spend:** zero provider/paid model calls; CodeRabbit free-tier review was rate
limited and paid overage was not enabled.

## One-line state

SEAM now has two explicit graph planes: canonical MIRL-backed knowledge and a
durable, append-only, non-canonical public reasoning graph, joined through exact
scoped references and exposed through the initial local Python SDK.

## What changed

- `seam_runtime/reasoning_graph.py` adds R1 typed nodes, edges, immutable state
  transitions, same-run edge isolation, same-namespace/scope knowledge and MIRL
  evidence validation, and guarded acceptance for conclusions.
- The schema has no arbitrary payload, chain-of-thought, activation, logits, or
  automatic-promotion field. `canonical_truth` and `automatic_promotion` are
  false in graph reads.
- `seam_runtime/sdk.py` adds `SeamSDK` and `ReasoningSession`: start/resume,
  node/link/transition/finalize/graph, plus canonical ingest and knowledge-query
  entrypoints. Run and objective creation is atomic.
- Per-run node, edge, and status sequences allocate under SQLite immediate write
  locks; concurrent SDK writers cannot race on a shared sequence.
- `docs/REASONING_GRAPH.md` defines the R1-R6 maturity path beside knowledge
  stages G1-G7. The roadmap, ledger, code layout, public README/docs, and
  fail-closed public release manifest now carry the boundary.
- HISTORY#460's graph/closeout stabilization remains the base of this slice:
  split identity decisions stay terminal, candidate pairs are SQL-bounded, PACK
  traceability uses content records, and the closeout wrapper runs all canonical
  gates with safe resume.

## Verification

- R1 audit suite: 8 tests, including a 20-writer concurrency case, append-only
  trigger checks, evidence isolation, cross-run rejection, no auto-promotion,
  SDK resume/ownership, and atomic failed-start rollback;
- 71 related graph, identity, workspace/J-lens, and history-closeout tests pass;
- public manifest and public safety audit suites pass after adding the new
  reasoning doc to the fail-closed allow-list;
- full non-external collection: 1,793 tests reached 100% with no failure markers
  and two established xfails;
- touched-file Ruff and compileall pass; final continuity gates run at closeout.

CodeRabbit could not review the uncommitted slice because the authenticated
organization's free plan was rate-limited for seven minutes and offered paid
per-file overage. No billing setting was changed. Local review found and fixed
the concurrency race, non-atomic start, and missing public-manifest entry.

## Next stages

1. R2: represent retrieval queries, candidate alternatives, ranking policy,
   selected/rejected paths, and exact retrieval evidence as reasoning artifacts.
2. G3: finish measured lexical + semantic + bounded traversal fusion, keeping
   the primary evidence lane non-displacing and the fusion trace deterministic.
3. Make future CLI, REST, MCP, and agent-framework integrations thin adapters
   over `SeamSDK`; do not expose reasoning SQLite tables as an integration API.
4. R3: add verification/tool outcomes, challenges, retries, contradictions, and
   supersession without erasing failed paths.

## Guardrails

- RAW/MIRL remain canonical truth; reasoning outcomes are never facts by
  implication.
- No hidden chain-of-thought, arbitrary model payload, raw activation, or
  automatic reasoning-to-MIRL promotion.
- Accepted conclusions require explicit support, but support is still an audit
  relationship, not proof of truth; later review/promotion remains fail-closed.
- No paid/provider run without operator approval.
- Preserve unrelated `.ua/`, `seam_runtime/.ua/`, `report*.png`, and
  `docs/pricing-tiers.md` files.
