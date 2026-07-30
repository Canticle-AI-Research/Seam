---
handoff_id: 2026-07-30-full-retrieval-ab-negative
supersedes: 2026-07-30-single-retrieval-engine
handoff_status: superseded
history: HISTORY#503
---

# Handoff: full retrieval A/B blocks the current ranking

**Date:** 2026-07-30
**Branch:** `refactor/unify-retrieval-paths`
**Legacy baseline:** detached worktree at local consolidation commit `7380b7c`
**Current base:** `origin/main` at `66efbda`
**Scope:** full provider-free LoCoMo comparison of legacy `search_ir()` against
the uncommitted canonical orchestrator path

## One-line state

Keep SEAM consolidated as one full private source package and keep one
retrieval engine as the target architecture, but do not commit, push, or land
the current fixed-RRF ranking: the full 1,542-question gate regressed both
context recall and warm latency.

## Product and license boundary

- The operator decision is unchanged: full private SEAM, including MIRL and
  HS/1, remains one readable source package.
- No license, ownership, artifact, publication, deployment, or remote state
  changed. The future public self-host remains a separate ground-up BUSL build
  with separation designed into it.
- This benchmark used no provider, answerer, judge, network, or paid call.

## Matched benchmark setup

- Standard LoCoMo runner population: all 1,542 answerable questions, all
  categories, 10 conversations, and 5,882 source turns.
- Dataset SHA-256:
  `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`.
- Dry-run fixture SHA-256:
  `405308a9159b88dd0675b798f59a3af16cdcc7061c31a6fcccc1638fe7f86d36`.
- Legacy ran from a detached worktree at `7380b7c`. The benchmark harness and
  LoCoMo adapter were verified identical between the baseline and current
  checkout.
- Legacy ingested the corpus once. Its ten checkpointed conversation databases
  were cloned for the canonical pass; the pre-query clone set matched the
  legacy set with aggregate SHA-256
  `aa6015a6d49442d52621882e08fd2ea6e1a0c06206a2a382d4790d3ee0ebf4ff`.
- Both passes used SQLite vector storage, the same cached local BGE model,
  `workers=1`, `search_top_k=100`, an 8,000-character context budget, saved
  contexts, and retained databases. Provider keys and pgvector were unset and
  Hugging Face was forced offline.
- Both passes completed all 1,542 cases with zero case execution errors.

This is the standard answerable-question runner population, not the separate
1,977-question graph-provenance population used by HISTORY#498.

## Blocking result

| metric | legacy | canonical | change |
| --- | ---: | ---: | ---: |
| overall context recall | 0.766420 | 0.755616 | -0.010804 |
| category 1, n=282 | 0.633842 | 0.618455 | -0.015387 |
| category 2, n=321 | 0.746167 | 0.740423 | -0.005743 |
| category 3, n=96 | 0.412697 | 0.367650 | -0.045046 |
| category 4, n=841 | 0.860806 | 0.853491 | -0.007316 |
| category 5, n=2 | 0.000000 | 0.000000 | 0.000000 |
| warm median retrieval | 156.4 ms | 207.2 ms | +50.8 ms |
| warm p95 retrieval | 264.1 ms | 315.7 ms | +51.6 ms |

The overall recall change is -1.41% relative. Paired outcomes were 97 improved,
153 regressed, and 1,292 unchanged. Six conversations regressed and four
improved.

Category 3 contains open-domain questions, so its context-recall change is not
a clean standalone retrieval attribution. It does not alter the all-category
blocking result.

## Context and evidence

- Every one of the 1,542 packed contexts changed; mean exact-line Jaccard was
  0.448, with a 0.440 median.
- Both paths filled exactly 8,000 characters. Legacy packed 45.49 mean source
  lines; canonical packed 39.35.
- Exact annotated evidence appeared in 1,244 legacy cases and 1,224 canonical
  cases. Seventy-four cases lost annotated evidence and 54 gained it.
- Of the 153 regressions, 35 lost annotated evidence and only two gained it.
  Of the 97 improvements, 27 gained annotated evidence and one lost it.
- Candidate count was 100 for every case in both passes.
- Mean evidence closure moved from 124.40 to 121.82, but per-case closure delta
  had only `r=0.019` correlation with recall delta. This is not explained by
  closure starvation alone.

The audit files label all 1,542 cases as judge errors because judge and answerer
were intentionally disabled. Those labels are expected audit metadata, not
benchmark execution failures.

## Attribution boundary

This A/B compares the full legacy scorer with the full canonical path. It
changes SQL/vector ranking, score-magnitude handling, reciprocal-rank fusion,
graph participation, temporal handling, filtering, and context packing
together. It therefore does **not** prove that the graph caused the regression.

A representative loss is `conv-26::q55`, “What subject have Caroline and
Melanie both painted?”, with gold answer “Sunsets.” Legacy recall was 1.0 and
kept the relevant RAW line at rank 21. Canonical recall was 0.0; that line was
outside the top 100, at vector rank 149, hybrid rank 173, and mix rank 159.
Graph participation improved its rank relative to canonical hybrid but did not
restore the legacy rank. The evidence points to combined fusion/ranking drift,
not graph-specific blame.

## Latency boundary

Warm per-query latency is comparable and regressed. Total elapsed time is not:
the legacy pass included corpus ingestion while the canonical pass reused the
cloned databases. Canonical's first query took 4.757 seconds to load local BGE;
legacy's first measured query took 328 ms because ingestion had already loaded
the model.

## Retained local evidence

Generated benchmark evidence is intentionally ignored under
`test_seam/benchmarks/retrieval-unification-full-20260730/`:

| artifact | SHA-256 |
| --- | --- |
| `legacy.json` | `6c4182b201f830e007a7bae50d6e86f773eeaee20e451065248ea23d9fdf611d` |
| `canonical.json` | `0087a1a137c732e3c0f43cb9ac3d729cb71172342e6ca4e3a3616e6190af6b61` |
| `legacy-audit.json` | `dbf44f339b68e8bc15f011fe9c2ac8f43f29ac6f5b64e18023cc85e4c94a7e1b` |
| `canonical-audit.json` | `9f58d805ac8885c6d4cd80f426b7ae3fe2d81d0179e1305ec996ec927cf9c0eb` |

The detached legacy worktree was removed after the run.

## Next move

1. Keep the one-engine architecture and do not restore split live retrieval.
2. Port the legacy RAW/BM25/weighted score semantics into the orchestrator as a
   named, versioned behavioral baseline.
3. Add per-leg trace capture and run a same-code hybrid-without-graph versus
   mix-with-graph ablation so graph lift or harm is attributable.
4. Repeat the full 1,542-question gate. Require context-recall non-regression
   and make the warm-latency tradeoff explicit before promotion.

The current branch remains uncommitted and unpushed pending that correction.
