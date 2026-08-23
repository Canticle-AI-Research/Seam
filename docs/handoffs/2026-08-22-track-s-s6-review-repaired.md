---
handoff_id: 2026-08-22-track-s-s6-review-repaired
supersedes: 2026-08-22-track-s-s6-locally-qualified
handoff_status: current
history: HISTORY#577
---

# Track S S6 principal tenancy — review-repaired candidate

## Current publication boundary

- Worktree: `/home/terrabyte/Documents/Projects/Seam-track-s-s6`
- Branch: `track-s/s6-principal-tenancy`
- PR: `#223`
- Protected base at branch start: `origin/main@a177852d3c819c57ddf987a170ce8974f10d3c7b`
- The original signed PR head `41c51a4` passed required and advisory CI. A
  later exact-head Codex review found six defects. They are repaired locally;
  the repaired signed commit, push, and exact-head CI are still publication
  gates at this handoff.
- S6 remains a branch-local candidate until the repaired head merges through
  protected `main`. Do not start S7 from this handoff alone.

## Review repairs

- Public-handle registration and resolution now require an active canonical
  record, so a soft-deleted generation cannot regain deletion authority.
- A deletion idempotency key can replay its original operation only while that
  operation still describes the current absent/deleted incarnation. Re-ingest
  invalidates stale deletion authority and returns the same content-free 404
  as an unknown handle.
- Injected and environment principal startup both require an exact declared
  process-worker count. More than one worker remains refused unless the
  upstream shared-limiter acknowledgement is explicit.
- Recall/context registration and persist compensation share the runtime
  projection lock, closing the rollback-vs-registration lost-update race.
- Active-delete lookup is tenant-first and uses the lifecycle tenant/status
  index rather than scanning cross-tenant lifecycle rows.
- Principal surface hiding occurs before router matching, so private routes,
  wrong methods, and slash variants receive the same rate-limited 404. Valid
  CORS preflights for the four public data routes remain available.

## Verification

- Strict focused slice: 175 collected and 175 passed across lifecycle,
  principal authentication/rate limiting, public HTTP, persist compensation,
  and bind-safety suites.
- Ruff passed on every changed runtime and test path; `git diff --check` passed.
- The canonical working-tree secret/session scan passed with only the known
  policy-file exclusions.
- The first CodeRabbit working-tree review found two valid startup/CORS
  omissions; both were repaired. The second review returned no findings across
  the changed code and tests.
- The broader 460-test, canonical non-external, and live pgvector evidence from
  the predecessor handoff remains evidence for `41c51a4`; only exact-head CI
  can qualify the repaired commit for merge.

## Next exact steps

1. Run the required continuity closeout for HISTORY#577 and its snapshot.
2. Stage only the explicit S6 runtime, tests, status, threat-model, handoff,
   history, snapshot, and derived stream/index paths.
3. Create and verify a signed commit, run the candidate secret scan, and push
   PR #223.
4. Require `repo-hygiene`, `chroma-real-smoke`, and
   `locomo-quickstart-bil2` on that exact head before merging.
5. Restack PR #224 after S6 merges. Its branch-local HISTORY#577/#578 entries
   must be renumbered around this protected chain before it can merge.

## Residual deployment boundary

This candidate proves repository behavior, not a hosted topology. TLS, shared
rate limiting, identity-provider deployment, secret delivery, service
supervision, backup/restore, rollback, disaster recovery, and public release
evidence remain S10 work.
