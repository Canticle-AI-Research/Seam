---
handoff_id: 2026-08-19-track-s-s6-in-progress
supersedes: 2026-08-18-track-s-deployment-readiness
handoff_status: superseded
history: HISTORY#574
---

# Track S S6 principal tenancy — in-progress recovery handoff

## Exact workspace state

- Worktree: `/home/terrabyte/Documents/Projects/Seam-track-s-s6`
- Branch: `track-s/s6-principal-tenancy`
- Base and `origin/main` at start: `a177852d3c819c57ddf987a170ce8974f10d3c7b`
- Publication: no S6 commit, push, PR, merge, release, or hosted deployment.
- Status: uncommitted implementation candidate. It is deliberately red while
  the generation-bound handle contract is being finished; S6 is not complete.
- Separate TUI work remains in
  `/home/terrabyte/Documents/Projects/Seam-tui-concept-shell` on
  `feat/tui-concept-shell@54bc01a`. Do not fold that branch or its machine-local
  source paths into the S6 PR.

The local context handoff with the same recovery boundary is
`.context-handoffs/context-handoff-20260819T094752Z.md`.

## What is implemented but still provisional

- Optional in-process bearer-to-principal resolution, hashed tenant/boundary
  derivation, principal/scoped/session isolation, principal-only opaque delete,
  and private-route/WebUI removal in principal mode.
- Dual bounded authentication limiting: pre-resolver attempts are consumed
  atomically by client address; valid principals use a stable subject-derived
  key. Legacy token-only behavior remains on its prior authorization-key path.
- Registered `core-storage/3 -> core-storage/4` migration and exact fail-closed
  handle schema checks, including unique-index/trigger rejection and pre-backup
  target-table collision refusal.
- Shared tenant ownership helper, principal-only canonical boundary
  immutability, canonical JSON compiler salting, and no-principal compatibility
  regressions.
- Populated `/3 -> /4` preservation coverage across canonical, raw,
  provenance, typed-edge, and knowledge-graph rows.

## Current cutoff: do not claim green

Sol's adversarial generation review found four related correctness boundaries:

1. A handle resolved before another request deletes/re-adds the same canonical
   record can otherwise delete the replacement incarnation.
2. A recall snapshot can otherwise register its stale handle after a replacement
   incarnation commits.
3. Re-adding while an earlier delete is `cleanup_pending` lets recovery erase
   the replacement external vector by reused canonical record ID.
4. Vector-index failure compensation restored canonical/vector rows but not
   handle rows; deletion receipts also changed across public-ID-key rotation.

The cutoff refactor has begun:

- `public_memory_handle` now has a `generation` column; registration and
  resolution are being changed to bind `(record_id, generation)`.
- lifecycle plans accept generation preconditions and apply checks them inside
  the canonical delete transaction.
- storage now blocks writes that overlap an active scoped delete and preserves
  an existing generation for duplicate live remembers.

The refactor is not mechanically complete. In particular:

- `tests/audit/test_public_memory_handle_schema.py` still passes bare record-ID
  strings where registration now expects `(record_id, generation)` and its
  replacement-table fixtures lack the generation column.
- runtime write compensation still needs exact snapshot/restore of handle rows.
- deletion receipts still need stable identity across public-ID-key rotation.
- concurrency regressions for stale resolution, stale registration, pending
  cleanup, compensation, and key rotation still need to be added and made green.
- the threat-model delta and public SDK contract predate these findings and must
  be reconciled only after the behavior freezes.

## Last verification

- Collect-only plus Python compilation passed for the touched runtime and 305
  tests across public API, handle schema, auth limiting, lifecycle, migration,
  and typed-reference modules.
- The migration slice had passed after narrowing pre-backup validation to the
  registered strict target and compatible experiment-ledger state.
- The current focused run intentionally stops red at
  `test_public_memory_handle_schema.py` because the test fixture still supplies
  a bare record ID; this is the first reproduction command below.
- Earlier green public/lifecycle results were invalidated by the subsequent
  race refactor and are not completion evidence.
- No live pgvector lane, full non-external suite, exact-head CI, continuity
  closeout, or final external review has run on this cutoff state.

## Resume in this exact order

1. Reproduce the cutoff:
   `/home/terrabyte/Documents/Projects/Seam/.venv/bin/python -m pytest -x -q tests/audit/test_public_memory_handle_schema.py tests/audit/test_public_api_v1_http.py -k 'principal or handle or reingest or delete'`.
2. Finish generation-column plumbing and update the exact-schema/row fixtures.
   Registration must verify the current canonical payload generation under the
   same write transaction, so a stale recall fails closed.
3. Propagate lifecycle generation preconditions through public API, runtime,
   and storage; add the resolve-then-replace race proving the old operation
   refuses without deleting the replacement.
4. Keep resurrection blocked while a scoped delete is `planned`, `applying`, or
   `cleanup_pending`; add pending-cleanup recovery coverage and a content-free
   public 409.
5. Snapshot/restore exact handle rows in `SeamRuntime.persist_ir` compensation,
   and prove a failed vector write is an exact no-op.
6. Make `deletion_id` stable across public-ID-key rotation without exposing the
   lifecycle operation ID; add replay coverage.
7. Run the focused public/lifecycle/migration/vector/graph/server slices, Ruff,
   compile, diff check, and secret scan. Then rerun independent Sol and
   CodeRabbit review.
8. Reconcile `docs/PUBLIC_SDK_API.md`, the S6 threat-model delta, campaign/status
   docs, and evidence manifest. Remove unrelated TUI hunks from the S6 diff.
9. Only after the full non-external and live external lanes, continuity gates,
   exact-head CI, and protected merge may S6 be marked complete and S7 begin.

## Files in scope

Runtime work is in `seam_runtime/config.py`, `lifecycle.py`, `migrations.py`,
`nl.py`, `public_api.py`, `public_memory_handles.py`, `runtime.py`, `server.py`,
`storage.py`, and `tenancy.py`. Active tests are the modified/untracked files
shown by `git status`, especially the public API, handle schema, auth limiter,
migration, compiler-salt, and typed-reference modules. Preserve every unrelated
primary/sibling worktree artifact.
