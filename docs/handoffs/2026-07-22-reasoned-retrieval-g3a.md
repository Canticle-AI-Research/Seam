---
handoff_id: 2026-07-22-reasoned-retrieval-g3a
supersedes: 2026-07-22-reasoning-graph-sdk-foundation
handoff_status: superseded
history: HISTORY#462
---

# Handoff: reasoned retrieval and bounded graph fusion (R2/G3a)

**Date:** 2026-07-22
**Branch:** `agent/graph-memory-identity-foundation`
**Spend:** zero provider/paid model calls, installs, or downloads.

## One-line state

R2 is now a mature retrieval-decision foundation and G3a is a real,
provider-free bounded graph-fusion slice, but the combined knowledge/reasoning
graph is not yet product-mature: the rest of G3, G4-G7, and R3-R6 remain open.

## What changed

- `seam_runtime/reasoning_graph.py` adds one append-only
  `reasoning_retrieval` decision per retrieval and a bounded candidate ledger.
  It records the exact namespace/scope boundary, normalized query and plan,
  policy and ordered candidate-set fingerprints, backend/model identity,
  selected/rejected disposition, fixed source/reason codes, latency, and
  content hashes without storing arbitrary model reasoning.
- Finalization is fail-closed: ranks must be contiguous, the selected prefix
  and counts must agree, the pinned fusion policy must recompute, and candidate
  evidence cannot change between retrieval and persistence. Later MIRL edits or
  boundary moves remain visible through explicit integrity status rather than
  mutating the historical decision.
- `ReasoningSession.retrieve`, `retrieval`, and `retrievals` expose R2 through
  the SDK. Query, budget, hop, filter, candidate, and page limits are bounded;
  empty retrievals still create typed decisions; pagination follows the
  monotonic per-run sequence.
- G3a lets semantic fact/episode MIRL hits explicitly seed the graph leg and
  traverse current `knowledge_edges` for 0-3 hops. The implementation keeps SQL
  and graph expansion bounded, never loads a whole scope, breaks ties by stable
  record ID, and gives graph credit only when an actual in-boundary edge
  connects the candidate.
- SQLite, pgvector, and Chroma now filter namespace and scope before top-K.
  SQLite migrations backfill boundary metadata from canonical MIRL. Existing
  external pgvector rows created before the scope column cannot be inferred
  safely and need one explicit `seam index` resync for the affected
  namespace/scope; a boundary-only repair updates metadata without invoking the
  embedding model.
- Legacy orchestrator search behavior and old custom vector adapters remain
  compatible; the new R2 candidate cap applies to `decide`, not legacy
  `search`.

## Verification

- authoritative full non-external run: 1,823 selected, 1,821 passed, two
  established xfails, zero failures, and zero skips;
- live pgvector slice: 7 passed;
- direct R1/R2 collection: 38 tests (9 reasoning-graph, 29 reasoned-retrieval);
- wider graph/retrieval review slice: 92 passed;
- touched-file Ruff, compileall, and `git diff --check`: pass;
- the one-shot `tools.history.closeout` path was used for this closeout and ran
  the history/index/stream/cross-index/snapshot chain plus all five canonical
  commit gates. This verifies the earlier commit-speed repair in real use.

## Maturity judgment

- R1: implemented foundation for public, non-canonical reasoning artifacts.
- R2: implemented and mature enough to build on; its boundary, ordering,
  mutation, evidence-integrity, and migration contracts are covered.
- G3a: implemented partial G3 only. It proves bounded semantic seeding and
  current-edge traversal, not the complete hybrid retrieval stage.
- Overall graph maturity: not mature. G4 summaries/observations, G5 context
  assembly, G6 lifecycle/maintenance, G7 scale/operability, and R3-R6 remain.

## Next stages

1. Resync any existing pgvector index that predates the scope column, scoped to
   the affected namespace/scope, before relying on it for reasoned retrieval.
2. Finish G3 with entity/value/agent/symbol vector classes, calibrated or
   normalized cross-leg scoring, exact returned graph paths and episode traces,
   historical-edge semantics, and measured scale/latency gates.
3. Build R3 verification/tool outcomes, challenges, retries, contradictions,
   and supersession without erasing failed paths; then continue R4-R6 only
   behind explicit evidence and promotion policy.
4. Keep CLI, REST, MCP, and agent integrations as thin adapters over `SeamSDK`;
   do not expose reasoning SQLite tables as the integration contract.

## Guardrails

- RAW/MIRL and the knowledge graph remain canonical; the reasoning graph records
  public justification and decisions, never truth by implication.
- No hidden chain-of-thought, arbitrary provider payload, activation/logit
  capture, or automatic reasoning-to-MIRL promotion.
- Do not claim full G3 or graph maturity until the remaining measured gates
  above pass.
- No paid/provider run without operator approval.
- Preserve unrelated `.ua/`, `seam_runtime/.ua/`, `report*.png`, and
  `docs/pricing-tiers.md` files.
