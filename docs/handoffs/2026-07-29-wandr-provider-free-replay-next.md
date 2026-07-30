---
handoff_id: 2026-07-29-wandr-provider-free-replay-next
supersedes: 2026-07-29-g5-g7-r6-provider-free-qualification
handoff_status: superseded
history: HISTORY#497
---

# Handoff: graph lanes implemented; provider-free WANDR replay is next

**Date:** 2026-07-29
**Branch:** `agent/wandr-replay-handoff`
**Base:** `origin/main` at `6d2c15bb16a00667c69862c4ab18ecd879924743`
**Scope:** canonical graph closeout and the next provider-free qualification route

## One-line state

Knowledge stages G1-G7 and reasoning stages R1-R6 are structurally implemented
through their provider-free qualification boundary; the next implementation is
a non-official, zero-network WANDR replay adapter, not a paid or competitive
benchmark run.

## Canonical completed state

- PR #185 merged G4 graph products and the R5 reviewed-promotion bridge at
  `6225937aad95414cef92fd86d07af6c78831b8ec`.
- PR #186 merged G5 deterministic context assembly, G6 lifecycle/recovery, and
  provider-free G7/R6 qualification at
  `6d2c15bb16a00667c69862c4ab18ecd879924743`.
- The knowledge graph remains a versioned projection of canonical RAW/MIRL. It
  includes scoped identity, temporal and provenance structure, semantic node
  and fact/episode vectors, deterministic hybrid traversal/fusion, append-only
  G4 products, deterministic G5 PACK assembly, and G6 lifecycle recovery.
- The reasoning graph stores public typed justification structure and
  `reasoning-pattern/1` recipes: controlled node kinds, operations, edge
  relations, and verification kinds. It stores no hidden chain-of-thought,
  provider payloads, raw model internals, or conclusions.
- R5 is the only bridge from a verified reasoning outcome into canonical MIRL.
  A separate proposal, review, and explicit apply step is required; reasoning
  never auto-promotes into knowledge.

## Honest qualification boundary

The corrected matched-budget provider-free G7 ablation scored native SEAM and
event-only at `1.0` versus `1.0`, with zero graph-incremental evidence hits,
three concurrent completions, one recovered interruption, zero failures, and
zero provider calls. This proves structural parity and recovery under the
frozen micro-suite. It does **not** prove incremental graph lift and does not
authorize a competitive claim.

Matched Mem0 and Zep scoreboards remain null and paid-gated. Do not execute
their provider-backed lanes without a new explicit operator approval.

## Next implementation: zero-network WANDR replay adapter

Use the local WANDR checkout at `/home/terrabyte/BEAM/wandr` only as a source
for a fixed replay corpus and workload shape. Do not run its official fetch or
evaluation path: that path is networked and paid.

Build one non-official replay adapter covering:

1. the existing smoke workload;
2. one representative hierarchy task;
3. isolated SEAM namespaces and scopes;
4. deterministic source, episode, task, and request IDs;
5. a fixed checked-in or hash-pinned replay corpus with no live fetch;
6. explicit provider-call, network-call, and cost counters fixed at zero;
7. matched context/result budgets for native SEAM and event-only lanes;
8. exact graph-incremental evidence attribution plus entity canonicalization,
   provenance, deduplication, PACK assembly, and batch-recovery checks.

The first acceptance gate is provider-free mechanism evidence: deterministic
replay, boundary isolation, exact provenance, successful recovery, and an
honest SEAM-versus-event-only ablation. A parity result is valid. Any claim of
incremental graph value requires at least one attributable gain with no
contract regression; do not infer lift from graph activity alone.

## Preserved boundaries

- Review is required before any reasoning output becomes MIRL knowledge.
- RAW/MIRL remains canonical; graph products, context PACKs, lifecycle indexes,
  reasoning patterns, and qualification reports remain derived or audit planes.
- Public `seam-client` and the opaque `/v1` boundary remain unchanged.
- No paid provider, live WANDR fetch, package publication, deployment, or
  DigitalOcean mutation belongs in the replay-adapter round.
- Preserve unrelated `.ua/`, `seam_runtime/.ua/`, `dist/`, and report PNG files.

## Resume prompt

> Resume SEAM from
> `docs/handoffs/2026-07-29-wandr-provider-free-replay-next.md`. Implement the
> non-official zero-network WANDR replay adapter over smoke plus one
> representative hierarchy task. Preserve matched budgets, deterministic IDs,
> exact provenance and graph-attribution counters, and zero provider/network
> calls or spend. Treat parity as parity; do not claim incremental graph lift
> unless the replay produces attributable gains without contract regression.
