---
handoff_id: 2026-08-22-track-s-s6-second-review-repaired
supersedes: 2026-08-22-track-s-s6-review-repaired
handoff_status: superseded
history: HISTORY#578
---

# Track S S6 principal tenancy — second review-repaired candidate

## Current publication boundary

- Worktree: `/home/terrabyte/Documents/Projects/Seam-track-s-s6`
- Branch: `track-s/s6-principal-tenancy`
- PR: `#223`
- Signed repair head `921cfd0` passed all three required checks plus package,
  pgvector, and registry-plan lanes. Its advisory matrix was still running when
  an exact-head Codex re-review found four additional P2 defects, so it was not
  merged.
- All four defects reproduce deterministically and are repaired locally. A
  third signed head, push, exact-head checks, and protected-main merge remain.
- S6 is still branch-local. S7 must not start from this handoff alone.

## Second review repairs

- Failed projection rollback restores its prior public-handle snapshot while
  preserving concurrent rows that still match the restored active canonical
  boundary and generation. A spawned-process regression proves this across the
  process-local lock boundary; transient-generation rows are not preserved.
- Public deletion retries recheck their generation inside the lifecycle
  transaction before the `applied` fast path. Re-ingest between the earlier
  HTTP check and apply therefore returns the same content-free 404 as an
  unknown handle.
- Principal route matching uses the ASGI routed path with `root_path` removed,
  preserving health and public data routes behind a mounted/reverse-proxy
  prefix without reopening private paths.
- A credential-fingerprint resolver budget now remains consumed after
  successful authentication. It complements the released client/IP rotation
  reservation and the stable subject budget, bounding repeated resolver calls
  without blocking different principals behind one client address.

## Verification

- Four minimal regressions were red on `921cfd0` and green after the fixes.
- Strict focused slice: 179 collected and 179 passed across lifecycle,
  principal authentication/rate limiting, public HTTP, persist compensation,
  and bind-safety suites.
- Changed-path Ruff passed. CodeRabbit found one valid minor cleanup issue in
  the spawned-process test; the failure path now always reaps the process and
  writer thread, and the regression plus Ruff pass after that repair.
- Required continuity closeout, signed commit, candidate secret scan, push,
  exact-head CI, and final review remain publication gates for this successor.

## Next exact steps

1. Append HISTORY#578, rebuild derived history/stream state, write the snapshot,
   and run every mandated closeout gate.
2. Stage only the explicit S6 code, tests, status, audit, handoff, history, and
   derived continuity paths; create and verify a signed commit.
3. Run the candidate secret scan, push PR #223, and request exact-head review.
4. Require `repo-hygiene`, `chroma-real-smoke`, and
   `locomo-quickstart-bil2` on that exact head before merging.
5. Restack PR #224 after S6 merges. Its branch-local HISTORY#577/#578 entries
   must be renumbered after this protected chain before it can merge.

## Residual deployment boundary

This candidate proves repository behavior, not a hosted topology. TLS, shared
rate limiting, identity-provider deployment, secret delivery, service
supervision, backup/restore, rollback, disaster recovery, and public release
evidence remain S10 work.
