---
handoff_id: 2026-07-30-single-retrieval-engine
supersedes: 2026-07-29-semantic-retrieval-and-promotion-gate
handoff_status: superseded
history: HISTORY#502
---

# Handoff: one full private SEAM, one retrieval engine

**Date:** 2026-07-30
**Branch:** `refactor/unify-retrieval-paths`
**Base:** local consolidation commit `7380b7c` over `origin/main` at `66efbda`
**Scope:** restore one live retrieval path after the single-package
consolidation, without changing licenses or publishing

## One-line state

The full private SEAM runtime is one readable codebase again, and every live
retrieval surface now reaches `RetrievalOrchestrator`; the future public
self-host remains a separate ground-up BUSL build whose separation will be
architectural rather than retrofitted into this runtime.

## Product and license boundary

- MIRL and HS/1 remain readable parts of the one private `seam-runtime`
  codebase.
- `LICENSE`, `NOTICE`, `COMMERCIAL_LICENSE.md`, and `LICENSES/` are unchanged
  from `origin/main`.
- Published artifacts retain their existing licenses and availability. Nothing
  was published, deployed, removed remotely, or relicensed here.
- The retained BUSL parameters are for the future public self-host. That
  product is built separately from the ground up; this private runtime is not
  split again to create it.

## Retrieval architecture

- `SeamRuntime.retrieve()` is the canonical local entry point over
  `RetrievalOrchestrator`.
- The orchestrator owns structured SQL, semantic vector, graph-node semantic,
  graph traversal, and explicit temporal legs under fixed
  `reciprocal-rank-fusion/2`.
- `search_ir()` remains for compatibility, but only converts canonical
  candidates into the longstanding `SearchResult` shape and loads their
  boundary-scoped evidence. It has no scorer.
- RAW inclusion, lens metadata, namespace/scope boundaries, temporal
  window/reference, current versus historical views, applied retrieval flags,
  graph semantic seeding, and evidence closure now cross the same plan.
- CLI, MCP, REST, opaque `/v1`, dashboard, SDK, LoCoMo, self-improvement probes,
  and server answer paths already called `search_ir()` and therefore converge
  without separate call-site rewrites.
- MIRL-backed HS/1 query/context paths now create an ephemeral runtime with an
  in-memory vector projection and invoke the same engine.
- The pure `retrieval.search_batch()` function remains only for explicitly
  named component/representation evaluation tracks. It is not a live runtime
  path.

## Measured compatibility gate

The free LoCoMo quickstart ran both paths against the exact same retained
database, with judge and answerer disabled and provider keys unset.

| metric | legacy path | canonical path |
| --- | ---: | ---: |
| overall context recall | 0.963333 | 0.963333 |
| category 1 recall | 0.971429 | 0.971429 |
| category 2 recall | 0.944444 | 0.944444 |

All ten cases matched individually. Canonical steady-state retrieval measured
about 79-88 ms per query. The first query measured 5.9 seconds because it
loaded the local BGE weights once; that initialization boundary is not hidden
inside the steady-state number.

## Verification

- Focused consolidation, temporal, graph-bound, derived-fact, retrieval-flag,
  improvement-loop, LoCoMo adapter, and HS/1 surface tests passed.
- Changed-file Ruff and `git diff --check` passed.
- CodeRabbit review findings were validated individually. Explicit candidate
  budget validation, mixed temporal-awareness rejection, and historical
  temporal filtering were fixed and regression-tested. Suggestions that would
  permit cross-boundary evidence or change the established `search_top_k`
  override were rejected.
- The authoritative full live-pgvector result is recorded by HISTORY#502 and
  the canonical closeout gates.
- No paid provider, answerer, or judge ran.

## Remaining boundary

The worktree is intentionally uncommitted and unpushed pending owner review.
The next product phase is not another internal split: land this one-engine
private baseline, then design and build the public self-host separately under
the retained BUSL parameters with its public/private seam explicit from its
first module.
