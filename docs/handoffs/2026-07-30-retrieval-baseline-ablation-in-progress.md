---
handoff_id: 2026-07-30-retrieval-baseline-ablation-in-progress
supersedes: 2026-07-30-full-retrieval-ab-negative
handoff_status: superseded
history: HISTORY#504
---

# Handoff: retrieval behavioral baseline and graph ablation are in progress

**Date:** 2026-07-30
**Branch:** `refactor/unify-retrieval-paths`
**Base:** local consolidation commit `7380b7c`; `origin/main` is currently
`66efbda`
**Scope:** repair the ranking-attribution boundary after the full provider-free
one-engine A/B regression

## One-line state

Keep the one-engine architecture, but do not commit, push, or land it: the
prior full 1,542-question gate remains a recall and warm-latency regression.
The former RAW/BM25/vector weighted scorer is now a named
`legacy-weighted/1` behavior inside `RetrievalOrchestrator`, giving the graph
experiment an exact same-runtime control.

## Implemented local checkpoint

- `RetrievalPlan` records an explicit ranking policy. The canonical engine
  supports `legacy-weighted/1` and `reciprocal-rank-fusion/2`.
- `LegacyWeightedAdapter` executes the old whole-corpus candidate, vector,
  RAW/BM25, temporal, and weighted-fusion semantics through an orchestrator
  plan. Its output retains the historical stable ordering rather than being
  re-fused through RRF.
- `SeamRuntime.search_ir()` remains a compatibility result/evidence adapter,
  but now asks the canonical engine for `legacy-weighted/1`; it is no longer a
  second public scoring entry point.
- The LoCoMo adapter and CLI expose `--retrieval-mode legacy-weighted|hybrid|mix`.
  `hybrid` and `mix` use the same adapter, corpus, context closure, and
  candidate budget, so their difference isolates graph-leg participation from
  the prior broad legacy-versus-canonical confound.
- Trace output names the selected policy and carries per-leg candidates and
  latencies. Persisting full per-case trace artifacts in the full runner is
  still required before interpreting the ablation.

## Verification performed

- `legacy-weighted/1` exactly matched the component scorer's ordered IDs and
  scores in a direct RAW/BM25/vector regression test.
- Focused retrieval, temporal, LoCoMo adapter/event, and dataset-routing tests:
  68 passed, zero failures.
- Offline, provider-key-cleared quickstart smoke, all with the same
  8,000-character and top-100 configuration:

| arm | context recall | warm median | warm p95 |
| --- | ---: | ---: | ---: |
| `legacy-weighted` | 0.963333 | 151.9 ms | 157.3 ms |
| `hybrid` | 0.963333 | 69.1 ms | 69.9 ms |
| `mix` | 0.963333 | 87.1 ms | 111.6 ms |

The smoke has ten fixtures only. It proves wiring, not non-regression or graph
lift. No provider, answerer, judge, network, or paid call ran.

## Exact next step

1. Add retained per-case, per-leg trace artifacts to the full-run output.
2. Run `hybrid` versus `mix` over all 1,542 answerable questions against
   byte-identical pre-query SQLite/vector databases, local cached BGE, one
   worker, top-100 candidates, and an 8,000-character budget.
3. Compare recall, exact evidence inclusion, candidate/rank deltas, and warm
   latency. Only then rerun the full legacy-weighted non-regression gate.

Until those gates pass, the branch remains local-only and the one-engine RRF
ranking is not promotable.
