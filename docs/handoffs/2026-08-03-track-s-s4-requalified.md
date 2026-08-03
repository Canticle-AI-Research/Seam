---
handoff_id: 2026-08-03-track-s-s4-requalified
supersedes: 2026-08-03-track-s-s3-requalified
handoff_status: current
history: HISTORY#530
---

# Track S S4 requalified on merged S3 ancestry

**Date:** 2026-08-03

**Branch:** `agent/track-s-s4-prep`

**Base:** protected `main@9bd40cb`; S3 merged through PR #194

**Publication:** rebuilt PR #195 candidate; its old head and checks are stale

## Current state

S4 replaces punctuation heuristics with closed reference contracts. IR edges
persist independently typed endpoints plus a normalized contributor ledger, so
rewriting one canonical record removes only its support and shared triples live
until their final canonical supporter disappears.

The exact `core-storage/1 -> /2` and `knowledge-graph/5 -> /6` transitions
consume canonical truth in deterministic 500-row batches. They preserve S3's
truthful `/5` resume point, emit digest-only invalid-row diagnostics, restore
lifecycle/document/identity truth, and remove phantom nodes plus orphan vectors
inside the migration transaction. RAW attribution is invariant to batch
boundaries, and ordinary boundary-only writes retain vector reuse. Canonical
payloads are revalidated on current-store reopen; a hard delete refuses
atomically if any surviving record still requires its target. The same closed
descriptor owns all eight reconciliation pointers and seven explicit facet
positions, while malformed reserved virtual-reference metadata is never
durable.

## Exit-gate evidence

- Timestamps, URLs, and arbitrary colon-bearing values remain literals unless
  an explicit field contract and exact canonical membership resolve them.
- Same-batch, stored, required, optional, and explicit virtual references have
  deterministic typed behavior; both edge endpoints participate in integrity
  cleanup.
- Entity reconciliation remaps every supported required pointer and optional
  facet without rewriting arbitrary literal payload. Duplicate batch IDs and
  canonical kind changes refuse before graph mutation.
- Current-store reopen scans canonical payloads in bounded batches. Missing
  required endpoints and malformed reserved virtual metadata fail read-only;
  deletion refuses byte-stable unless every dependent source is deleted in the
  same operation.
- CLM and REL rewrites preserve unrelated and independently shared support,
  remove stale final-owner triples, and remain correct after migration/reopen.
- Invalid/mismatched private-looking canonical IDs roll migration back, never
  appear raw in exceptions or logs, and are represented only by SHA-256.
- Bounded full-versus-batched migration produces equivalent graph tables,
  batch-independent provenance attribution, zero resurrection, and no
  searchable orphan vector. Soft-delete batches perform one final identity-
  ledger revalidation rather than rescanning the ledger after every batch.
- Already-current stores refuse contributor rows whose canonical source or
  derived edge is absent without changing database bytes. Edge-type conflict
  validation uses 300-triple queries capped at 900 SQLite variables, and both
  intra- and cross-batch conflicts roll the whole migration step back.
- The committed candidate passes the whole provider-free suite
  (`test_seam_all/ tools/history/test_history_tools.py tools/streams/ tests/
  -m "not external"`): 2,400 passed, 23 deselected, 2 xfailed, 3 subtests
  passed, zero skips, zero failures. `tests/audit` alone collects 1,842
  non-external cases. The authoring session's "1,738 non-external audit tests"
  predates its own final test additions and does not reproduce on this tree.
- The 23 external cases were run against the live local pgvector service with
  the exact five-file command the CI lane uses, not deselected: 30 passed,
  zero skips.
- Ruff, Python compilation, diff hygiene, and the content-free candidate
  secret/session scan pass.

## Honest boundaries

- Repeated independent exact-diff review found and closed redundant per-batch
  identity-ledger validation, incomplete current-store contributor/payload
  validation, per-edge migration queries, duplicate-ID ambiguity, incomplete
  reference-position remapping, generic/missing required endpoints, stale RAW
  attribution, dangling hard deletes, divergent pointer/facet contracts, and
  bypassable reserved metadata validation. The final clean review rerun plus
  required, pgvector, package, and advisory full-suite checks remain the
  publication gate.
- The authoring session verified `tests/audit` but not `test_seam_all/`, and
  left one legacy regression there:
  `test_runtime_persist_reports_ids_when_sqlite_rollback_fails` patched
  `store.persist_ir` to fail on its second call and asserted canonical ids
  appear in the manual-recovery error. The restore path is now
  `store.restore_ir_after_failed_projection`, and the diagnostics are
  deliberately content-free. The recovery session repointed the patch and
  inverted the assertion to `assertNotIn`, renaming it
  `test_runtime_persist_flags_manual_recovery_without_ids_when_restore_fails`.
  The runtime was not changed to satisfy it.
- No paid provider, competitive retrieval-score benchmark, artifact publish,
  deploy, or release ran.
- This closes S4 reference integrity; it does not complete S5-S10, prove a
  Mem0/Zep/Cognee win, establish 100% canonical memory, or eliminate external
  model hallucinations.

## Exact next move

HISTORY#530 is written and the candidate is committed on
`agent/track-s-s4-prep`. Replace PR #195's stale remote head with
an exact force-with-lease, mark it ready, and merge only after every required
and advisory exact-head gate plus review is green. Then refresh protected-main
evidence and begin S5 from the merged S4 substrate.
