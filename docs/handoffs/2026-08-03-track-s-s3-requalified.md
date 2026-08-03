---
handoff_id: 2026-08-03-track-s-s3-requalified
supersedes: 2026-08-03-audit-repairs-merged
handoff_status: superseded
history: HISTORY#529
---

# Track S S3 requalified on current main ancestry

**Date:** 2026-08-03

**Branch:** `feat/track-s-s3-durable-supersession`

**Base:** protected `main@fa72c0c`

**Publication:** rebuilt draft PR #194; protected `main` does not yet contain S3

## Current state

S3 supplies the exact transactional `knowledge-graph/4 -> /5` transition.
Disposable topology is rebuilt from canonical MIRL, MIRL lifecycle state, and
durable `document_status` supersession. The separate identity-merge judgement
ledger is preserved and revalidated.

## Exit-gate evidence

- A known-good KG/4 store applies exactly one registered transition, advances
  both markers, preserves current/full-history/point-in-time views and shared
  live edges, and reports zero superseded-to-live resurrections.
- Injected failure, newer or missing markers, missing identity ledgers, and
  invalid canonical document identifiers leave all relevant table hashes
  unchanged. Invalid identifiers are represented in logs only by SHA-256.
- The rebuilt candidate passed 83/83 focused graph/migration tests and all
  1,630 selected non-external audit tests; 23 external tests were deliberately
  deselected for the live pgvector CI lane.
- Ruff, Python compilation, diff hygiene, and the canonical candidate
  secret/session scan passed. CodeRabbit's silent-skip finding was repaired by
  fail-closed rollback plus content-free diagnostics.

## Honest boundaries

- Exact-head GitHub required, pgvector, package, and advisory full-suite checks
  have not yet rerun on the rebuilt head.
- No paid provider, retrieval-score benchmark, artifact publish, deploy, or
  release ran.
- S4 owns the downstream KG/5-to-KG/6 typed-reference transition. Rebuild S4
  only after S3 merges and preserve the exact KG/4-to-KG/5-to-KG/6 chain.

## Exact next move

Publish the rebuilt #194 head with force-with-lease, mark it ready, obtain a
fresh review, and merge only after every exact-head required and advisory check
is green.
