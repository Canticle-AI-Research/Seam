---
handoff_id: 2026-09-02-track-s-r1-protected-main-r2-next
supersedes: 2026-09-01-track-s-r1-locally-qualified-r2-next
handoff_status: current
history: HISTORY#630
---

# Track S R1 protected-main verified; R2 next

## Exact state

Protected `main@f8c33491205da2c8916698086604ee9850ee5860` contains D1-D4,
T1, G1, and R1 through merged PR #245. R1 candidate
`6815fe6abdb0b7165409bdd7db8bf1c768cba371` preserves positive applied
retrieval depth/context values, records the explicit boundary-only SQL gate,
uses one-based RRF with stable record-ID ties, and resolves graph semantic
seeding once across runtime, MCP, SDK, and compatibility paths.

`legacy-weighted/1` remains the versioned compatibility default. Changing that
default remains an S9 Promotion decision, not an R1 or R2 refactor.

## Verification

- Every hosted PR #245 candidate check passed before merge, including the three
  required checks and the advisory full matrix.
- The exact merge commit passed CI run `33551586780`, external-memory run
  `33551586758`, and CodeQL run `33551585858`.
- The 2026-09-02 post-merge recheck passed 34 focused R1 tests.
- The first full-suite attempt correctly failed when the configured local
  pgvector service was stopped. After starting the existing service, the full
  strict non-external selection exited 0 with the two established xfails and
  no skips.
- The first external-only attempt correctly failed the strict no-skip gate
  because `PGVECTOR_TEST_DSN` was not exported. The supported rerun bound it to
  the private local pgvector DSN and passed all 23 external tests without
  exposing credentials.

## Receipt and claim boundary

The currently available ignored orchestration ledger contains a T1 receipt but
no R1 pre-merge receipt. Because those records are local and ignored, absence
here cannot establish whether another worktree once held one. This successor
therefore requires a fresh independent post-merge exact-state release
qualification. It records current proof without claiming that the pre-merge
receipt order can be reconstructed retroactively.

R1 source is protected-main complete and exact-main verified. This does not
freeze S8: R2 Retrieval Scale and Backend Parity remains open. S9 independent
qualification and S10 reproducible release/deployment proof have not started,
and no hosted-production claim is made.

## Resume order

1. Finish this bounded continuity correction through independent release
   qualification, explicit staging, protected PR merge, and exact-main check.
2. Start R2 from the resulting protected main in a fresh isolated worktree.
   The existing remote `codex/s8-r2-spec` pointer was identical to `main@f8c3349`
   with no PR on 2026-09-02; do not treat its name as implementation evidence.
3. Bound compatibility and temporal acquisition before materialization, make
   SQLite plans namespace-selective, prove pgvector HNSW expression parity,
   pin backend ties, and add fixed-slice growth/parity cases.
4. Do not freeze S8 or begin S9 until R2 is independently green and merged.
