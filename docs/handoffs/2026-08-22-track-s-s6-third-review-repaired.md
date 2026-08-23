---
handoff_id: 2026-08-22-track-s-s6-third-review-repaired
supersedes: 2026-08-22-track-s-s6-second-review-repaired
handoff_status: superseded
history: HISTORY#579
---

# Track S S6 principal tenancy — third review-repaired candidate

## Current publication boundary

- Worktree: `/home/terrabyte/Documents/Projects/Seam-track-s-s6`
- Branch: `track-s/s6-principal-tenancy`
- PR: `#223`
- Signed head `82849ab` passed all three required checks plus package,
  pgvector, and registry-plan lanes. Its exact-head Codex review then found one
  P1 and three P2 defects, so it was not merged.
- All four Codex findings and two subsequent CodeRabbit lock-hardening findings
  are repaired locally. A fourth signed head, push, exact-head checks, final
  review, and protected-main merge remain.
- S6 is still branch-local. S7 must not start from this handoff alone.

## Third review repairs

- Canonical SQLite write/projection/compensation, scoped-delete planning/apply,
  and public-handle publication now share a reentrant cross-process file lock
  keyed to the resolved store path. A deletion in another worker can no longer
  complete inside a failed writer's compensation window and be resurrected.
- The lock lives beside the canonical store under the store directory's trust
  boundary, not shared `/tmp`; the narrow `.seam-runtime-*.lock` pattern is
  ignored. POSIX and Windows acquisition use nonblocking retries with a shared
  60-second deadline and a content-free timeout error rather than waiting
  forever.
- Every public delete apply requires the in-transaction incarnation check, even
  when a first-time planner raced and returned an already-existing operation.
- The credential-invocation limiter refuses new fingerprints when its bounded
  key map is full instead of evicting an active reservation.
- Principal POST middleware reserves the client/authentication budget before
  framework body parsing. The endpoint guard reuses that reservation, releases
  it after successful authentication, and releases it when the credential
  budget itself rejects a request.

## Verification

- Four minimal Codex regressions and two lock-hardening regressions were red on
  their predecessor implementation and green after repair.
- Strict focused slice: 185 collected and 185 passed across lifecycle,
  principal authentication/rate limiting, public HTTP, persist compensation,
  and bind-safety suites.
- Changed-path Ruff passed. CodeRabbit's two final major findings were the lock
  placement and bounded-acquisition issues above; both exact regressions pass.
- Required continuity closeout, signed commit, candidate secret scan, push,
  exact-head CI, and final GitHub review remain publication gates.

## Next exact steps

1. Append HISTORY#579, rebuild derived history/stream state, write the snapshot,
   and run every mandated closeout gate.
2. Stage only the explicit S6 code, tests, `.gitignore`, status, audit, handoff,
   history, and derived continuity paths; create and verify a signed commit.
3. Run the candidate secret scan, push PR #223, and request exact-head review.
4. Require `repo-hygiene`, `chroma-real-smoke`, and
   `locomo-quickstart-bil2` on that exact head before merging.
5. Restack PR #224 after S6 merges. Its branch-local HISTORY#577/#578 entries
   must be renumbered to follow this protected chain before it can merge.

## Residual deployment boundary

This candidate proves repository behavior, not a hosted topology. TLS, an
upstream shared request limiter, identity-provider deployment, secret delivery,
service supervision, backup/restore, rollback, disaster recovery, and public
release evidence remain S10 work.
