---
handoff_id: 2026-07-29-g3-r4-self-improving-graphs
supersedes: 2026-07-29-stable-packages-live
handoff_status: current
history: HISTORY#494
---

# Handoff: G3 and R4 self-improving graph loops complete

**Date:** 2026-07-29
**Branch:** `feat/self-improving-graphs`
**Scope:** G3 hybrid knowledge-graph search and R4 reasoning-pattern retrieval

## One-line state

G3 and R4 are implemented and qualified as real closed feedback loops: the
knowledge graph can measure, propose, approve, apply, observe, and revert graph
retrieval policy, while the reasoning graph learns content-free structural
recipes from verified outcomes and strengthens or weakens them from verified
reuse results.

## G3 completion boundary

- Versioned semantic vectors cover entity, value, agent, and symbol nodes.
- Graph-node semantic hits are a distinct `graph_node` source in
  `reciprocal-rank-fusion/2`, resolve to exact scoped MIRL backing records, and
  persist their own R2 latency.
- Only nodes whose backing record satisfies every active retrieval filter may
  seed traversal.
- Graph-aware scorers alone can propose bounded semantic seed/score-floor
  policy. Required integrity, trust, temporal, provenance, category, aggregate,
  and disjoint holdout gates fail closed.
- Passing proposals still require explicit H2 operator approval. Applied flags
  change later SDK, CLI, MCP, REST, and runtime graph searches; the existing
  revert path restores the prior policy. The repository default remains off;
  qualification evidence is not silent promotion.
- The 2,048-node synthetic qualification passed all five query shapes. Pinned
  LoCoMo with cached `BAAI/bge-small-en-v1.5` selected 4 seeds: development
  recall rose from 0.7436 to 0.9231 and disjoint holdout from 0.7222 to 0.8889.
  Candidates with 8, 16, and 32 seeds were rejected for motif regression.

## R4 completion boundary

- A verified accepted outcome attempts to distill one append-only
  `reasoning-pattern/1` structural recipe.
- Recipes contain node kinds, controlled operations, edge relations, and check
  kinds only. They exclude summaries, conclusions, raw tool output, provider
  payloads, and hidden chain-of-thought.
- Retrieval requires same namespace/scope, compatible task or operation,
  freshness, minimum observed trust, a still-accepted source outcome, current
  passed verification attempts, current knowledge references, and unchanged
  MIRL evidence fingerprints.
- Pattern use is explicit. A later verified accepted outcome records successful
  reuse; explicit rejection records failure. Append-only success/failure counts
  change future ranking and eligibility without rewriting the source pattern.
- Feedback is run-owned, cross-run mutation is rejected, and no outcome or
  pattern promotes itself into MIRL.

## Verification

- `pytest tests/ -q` with the live pgvector test DSN: exit 0, 1,565 tests
  collected, zero skips, and only the two established `compile_nl` xfails.
- Changed-file Ruff, compileall, `git diff --check`, and collection/import
  checks passed.
- Synthetic G3 qualification: passed, worst sampled p95 76.64 ms against the
  5,000 ms bound.
- Pinned LoCoMo/BGE qualification: passed, provider calls 0, node-vector
  coverage 1.0, `graph_node` trace rate 1.0.
- Three CodeRabbit review cycles produced 16 findings; all valid findings were
  fixed and regression-tested. A final post-fix rerun was unavailable because
  the free review quota was exhausted.
- Repository-wide Ruff remains outside this branch's evidence because it scans
  preserved unrelated untracked `.ua` trash files and two untouched pgvector
  test import blocks; every staged Python file passes Ruff.

## Next

Push the branch, open a draft PR, and merge only after required protected checks
pass. Do not reopen G3 or R4 unless CI or review finds a contract defect. G4
graph products, R5 reviewed promotion, and later scale/qualification stages
remain distinct future milestones.
