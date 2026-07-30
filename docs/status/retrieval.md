# Status Stream: Retrieval

> Retrieval engine, ranking policies, and the open ablation gate

_Source of truth for current state in this area. History lives in `HISTORY.md`._

## Status: BLOCKED on attribution

One canonical engine. `RetrievalOrchestrator` owns SQL, vector, graph, graph-node,
and explicit temporal retrieval. `SeamRuntime.retrieve()` is the canonical entry;
`search_ir()` is a compatibility result/evidence adapter over the same plan, not a
second scorer.

Ranking policies are named and selectable: `legacy-weighted/1` (pre-refactor
RAW/BM25/vector weighted scorer, kept as behavioral control) and
`reciprocal-rank-fusion/2`.

## Open gate (HISTORY#503 -> #504)

The full provider-free A/B over all 1,542 answerable LoCoMo questions falsified an
earlier 10-question parity claim:

| metric | legacy | canonical | change |
| --- | ---: | ---: | ---: |
| overall context recall | 0.766420 | 0.755616 | -0.010804 |
| category 1 (n=282) | 0.633842 | 0.618455 | -0.015387 |
| category 3 (n=96) | 0.412697 | 0.367650 | -0.045046 |
| warm median | 156.4 ms | 207.2 ms | +50.8 ms |

That A/B moved ranking, fusion, graph, temporal, filtering, and packing together,
so it proves a regression but attributes it to nothing.

**The branch `refactor/unify-retrieval-paths` must not land until this is resolved.**

## Instrumentation (landed 2026-07-30)

Per-case, per-leg traces now reach the runner via `--save-retrieval-trace`.
Traces carry plan, per-leg candidates, fusion selection/rejection, and per-leg
latency. Verified observationally inert: traced and untraced runs produce
byte-identical integrity hashes.

Retrieval **mutates** the SQLite store, so A/B arms must each start from a clone of
one pristine ingest-only snapshot (`benchmarks.external.locomo.ingest_only`).
Cloning after a scored run is a confound.

## Active

- Run `hybrid` vs `mix` over 1,542 questions with retained traces; attribute the delta.
- Rerun the `legacy-weighted` non-regression gate before promoting RRF.
- Keep validated levers in core `RetrievalFlags` so every surface benefits.
