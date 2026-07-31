---
handoff_id: 2026-07-31-embedding-preflight-relation-gate
supersedes: 2026-07-30-semantic-graph-admission-qualified
handoff_status: current
history: HISTORY#507
---

# Handoff: embedding preflight and relation qualification gate

**Date:** 2026-07-31
**Branch:** `fix/semantic-graph-admission`
**PR:** #189 (draft)
**Scope:** LoCoMo embedding integrity and provider-free semantic-relation
qualification

## One-line state

LoCoMo now fails before work begins unless its exact offline embedding contract
is operational, and semantic extraction has a strict provider-free admission
gate. The tracked 419-turn corpus fails with zero relations, so adaptive depth
and relation/triplet scoring remain ineligible.

## Decision

Do not build eGoT adaptive depth or TREK relation/triplet scoring yet. The next
authorized model-bound action is one isolated extraction/re-ingest followed by
this gate and its human precision review. Ollama and every cloud extractor
remain untouched until the operator explicitly clears that boundary.

The operator-reported 7 relations over 30 turns remains useful as a lead, not a
qualification result. It is below the 30-relation floor and has no pinned
corpus, extractor configuration, sample, or label bundle in the repository.

## Embedding integrity

- Every scored SEAM LoCoMo run and ingest-only snapshot executes one real
  embedding in the parent before workers, checkpoints, ingestion, or cases.
- The contract pins `BAAI/bge-small-en-v1.5` revision
  `5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`, 384 dimensions, the runtime
  normalization contract, local-files-only mode, and finite nonzero output.
- Lazy constructor/import/cache failures are fatal before any case can be
  converted into a normal-looking zero score.
- Partial checkpoints retain the content-free receipt and its digest. Final
  result bundles bind that receipt to the existing report integrity hash under
  `seam-locomo-run-contract/1`; ingest-only bundles bind it to the corpus
  digest.
- `--keep-db` verifies every indexable canonical record has an exact
  current-render vector for the pinned model and rejects malformed,
  non-numeric, wrong-length, nonfinite, all-zero, missing, stale, or
  same-boundary orphan vector rows.
- Required CI keys its cache by the exact revision, provisions that snapshot,
  then switches Hugging Face and Transformers offline for the benchmark.

## Extraction qualification

`tools.relation_extraction_qualification` is read-only and cannot compile text
or call an extractor, embedding service, judge, answerer, or scorer. It
requires an independently pinned expected RAW-turn count and identity digest,
then reports:

- persisted `REL`, canonically admitted REL-backed edges, and exact-backtrace
  relations separately;
- `REL -> SPAN/raw_spans -> RAW/raw_docs`, `REL -> PROV -> RAW`, and
  edge-episode-to-the-same-RAW/hash convergence;
- exactly one extractor configuration, relation-bearing turn coverage,
  predicate count, unique entity pairs, undirected distinct-neighbor max/p95/p99
  degree, and parallel-edge multiplicity;
- incremental undirected two-hop pairs and the subset whose two edges
  backtrace to distinct RAW turns;
- a deterministic predicate/hub-stratified, content-bearing review template
  whose completed labels are hash-bound to the content-free report.

Substrate qualification requires at least 30 admitted relations, at least
10 percent RAW-turn coverage, 100 percent admission and exact backtrace, the
predeclared hub bound, one extractor configuration, 0.90 sampled point
precision, and a 0.80 Wilson lower bound. `scorer_eligible` is separate and
also requires at least two predicates plus an incremental cross-turn two-hop
path.

## Measured evidence

- Real offline embedding probe: passed in 5.1 seconds with the exact revision,
  384 finite/nonzero dimensions, and no network/provider call.
- Real one-case LoCoMo smoke: completed in 7.0 seconds, archived normally, and
  reproduced the `seam-locomo-run-contract/1` hash exactly. Artifact:
  `/mnt/data/seam-embedding-preflight-smoke.0dWa8Z/`.
- Read-only legacy replay: expected and observed RAW turns both 419 with
  matching identity digest; persisted/admitted/exact-backtrace relations were
  0/0/0; `status=failed`; `scorer_eligible=false`. The snapshot predates graph
  projection tables, which is a named failed check rather than a crash.
  Content-free report:
  `/mnt/data/legacy-419-relation-qualification.json`.
- No artifact for the reported 7/30 gemma result was found in the tracked
  repository, so it was not relabeled as verified evidence.

## Verification

- Strict provider-free audit: 1,449 passed, 0 failed, 0 skipped; 23 external
  tests intentionally deselected; 1,472 total collected.
- Focused embedding, vector, qualifier, LoCoMo, multi-speaker, and MIRL
  extraction suites passed after every repair.
- Changed Python files pass Ruff and `py_compile`; `git diff --check` passes.
- Candidate-file secret/private-session scan found zero matches.
- CodeRabbit review found ten initial items; the valid vector-overflow,
  durability, CI, documentation, and exact-claim assertions were repaired.
  Its second pass found one cleanup-path issue, also repaired and regression
  tested. A third pass was rate-limited, so local audit evidence is the final
  verification boundary for that last one-line repair.
- No Ollama process, endpoint, model, configuration, or corpus was inspected,
  contacted, stopped, or modified.

## Exact next step

1. Land this bounded guard and qualifier through PR #189.
2. Keep extraction and Ollama paused.
3. After explicit operator clearance, build one isolated corpus with a pinned
   extractor configuration and run the provider-free qualifier plus human
   sample review.
4. Only when both `passed=true` and `scorer_eligible=true`, implement adaptive
   depth and query-aware triple/path scoring, then require an attributable
   category-1 holdout gain over `hybrid`.
