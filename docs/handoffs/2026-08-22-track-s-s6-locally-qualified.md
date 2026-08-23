---
handoff_id: 2026-08-22-track-s-s6-locally-qualified
supersedes: 2026-08-19-track-s-s6-in-progress
handoff_status: superseded
history: HISTORY#575
---

# Track S S6 principal tenancy — locally qualified candidate

## Publication boundary

- Worktree: `/home/terrabyte/Documents/Projects/Seam-track-s-s6`
- Branch: `track-s/s6-principal-tenancy`
- Base: exact protected `origin/main@a177852d3c819c57ddf987a170ce8974f10d3c7b`
- Candidate state at this snapshot: locally reviewed and qualified, awaiting a
  signed commit, bounded draft PR, and exact-head CI.
- S6 is not protected-main fact and is not complete. Do not begin S7 until this
  branch passes exact-head CI and merges through protected main.
- The separate `feat/tui-concept-shell` worktree is not part of this candidate.
  No TUI implementation or machine-local design source belongs in the S6 PR.

## Frozen behavior

- Principal mode resolves bearer credentials inside the process, hashes the
  stable subject into the tenant/namespace boundary, removes legacy private
  routes and generated API docs, and requires a stable public-ID key.
- Unset/zero rate-limit configuration becomes 60 requests per minute only in
  principal mode. Invalid/rotating credentials share a bounded client-address
  pre-resolver bucket; successful requests release that reservation and use a
  subject-derived bucket. Multi-worker launch refuses unless an upstream shared
  limiter is explicitly acknowledged. Legacy zero/unset behavior is unchanged.
- Recall/context register every returned opaque handle plus its canonical
  generation in the exact indexed `core-storage/3 -> core-storage/4`
  projection before responding.
- Delete resolves at most 50 handles inside the exact principal/namespace/scope,
  binds the G6 lifecycle plan to their generations, and returns content-free
  404 for foreign, forged, stale, or raced handles.
- Stale recall registration verifies the generation in the same write
  transaction and fails closed. Writes overlapping `planned`, `applying`, or
  `cleanup_pending` scoped deletion return a content-free conflict, preventing
  resumed cleanup from erasing a replacement vector.
- Runtime persist compensation restores exact public-handle rows together with
  canonical/vector-outbox state. Deletion receipt identity is stable across
  public-ID-key rotation without exposing the lifecycle operation ID.
- Static principal credentials compare UTF-8 bytes, so malformed/non-ASCII
  input cannot escape the content-free authentication boundary.

## Qualification evidence

- Expanded affected surface: 460 collected and 460 passed with strict no-skip
  after the final bounded review repairs.
- Canonical non-external suite, fresh `SEAM_DB_PATH`, ambient pgvector DSNs
  removed: 2,926 passed, 23 deselected, 2 expected xfails, and 3 passed subtests
  in 461.36 seconds.
- Live pgvector external lane, isolated pgvector 0.8.6 container: 23 passed and
  2,354 deselected in 3.25 seconds. The ephemeral container was removed.
- The first broad attempt (21 failed, 6 errors) was invalid environmental
  evidence: CLI/MCP subprocesses opened the preserved root `seam.db`, whose
  pre-candidate handle table lacks `generation`, and an inherited DSN selected a
  stopped pgvector service. Neither artifact was deleted or overwritten. The
  isolated green reruns above are the candidate evidence.
- Review repairs after the inherited cutoff: strict 64-lowercase-hex lifecycle
  generation validation; bounded principal default limiting; split storage
  state/payload reads; release of successful pre-resolver reservations; and
  UTF-8-safe static credential comparison.
- Final CodeRabbit review returned two major findings. The rollback-snapshot
  finding was valid: that snapshot is now a required keyword and every caller
  supplies it. The injected-resolver/multi-worker finding is inapplicable to
  supported `seam serve` startup, whose two launch paths use the environment
  principal adapter already covered by worker safety. A post-repair service
  rerun was rate-limited, so no service-clean claim is made.
- Manual review covered the eight untracked files omitted by the service and
  repaired two additional defects: duplicate handles now fail the documented
  unique-ID delete contract, and active delete work blocks recreation even when
  the old canonical row was separately removed.
- Whole-tree Ruff, active-Python compilation, dependency-contract verification,
  diff/audit checks, the canonical secret/session scan, and every mandated
  integrity/routing/handoff/continuity/streams/wiki gate pass locally.

## Remaining publication steps

1. Reconcile live `origin/main` and freeze the explicit candidate path list
   below. Stage only those paths; never use `git add -A`.
2. Create a signed commit, verify its signature and candidate secret scan, push
   the branch,
   and open a bounded draft PR. Keep ignored benchmark outputs, the preserved
   root database, local context handoffs, and all sibling worktree state out.
3. Observe exact-head CI and record required/advisory results. Do not mark S6
   complete, merge on behalf of the operator, or start S7 from local evidence.

## Explicit candidate paths

Use `git status --porcelain=v1 --untracked-files=all` immediately before staging
and reconcile any difference. The intended candidate is the S6 runtime/tests,
the status/threat-model/handoff documents, HISTORY#575, the one new snapshot,
and their tool-generated history index/stream/cross-index outputs. It excludes
`.context-handoffs/`, `seam.db`, `test_seam/`, caches, benchmark outputs, and
every TUI or sibling-worktree path.

## Residual deployment boundary

This candidate proves repository behavior, not a hosted topology. TLS, shared
rate limiting, identity-provider deployment, secret delivery, service
supervision, backup/restore, rollback, disaster recovery, and public release
evidence remain S10 work.
