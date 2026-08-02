---
handoff_id: 2026-08-01-track-s-s2-locally-qualified
supersedes: 2026-08-01-track-s-s1-locally-qualified
handoff_status: superseded
history: HISTORY#523
---

# Track S S2 locally qualified

**Date:** 2026-08-01

**Branch:** `feat/track-s-s2-migration-spine`

**Base:** `origin/main@94375e8`

## Current state

Track S is active. S0 and S1 remain complete, and S2's central SQLite
migration spine is locally qualified. Schema version 2 now governs canonical
SQLite storage and every durable projection initialized by `SQLiteStore`.

S3 durable supersession and guarded reprojection is the next canonical move.
S4 typed-reference integrity may proceed in parallel, and S5 is also unblocked
by S2's completed dependency.

## What changed

- Added one ordered, transactional migration registry for canonical storage and
  all initialized durable projections.
- Added read-only preflight that refuses unknown, newer, or inconsistent stores
  before a writable connection opens.
- Added retained private pre-migration backups and an explicit atomic restore
  path that is verified before replacement.
- Added per-step required-table, `integrity_check`, and `foreign_key_check`
  gates, plus failure injection before every step commit.
- Replaced projection-level `executescript` calls with the central
  transaction-preserving script executor.
- Added maintained historical fixtures derived from released v1.2.0 and v2.4.0
  layouts, and documented the operator contract in `docs/SQLITE_MIGRATIONS.md`.

## Qualification evidence

- Historical v1.2.0 and v2.4.0 fixtures, a new empty store, and a partially
  migrated v1 store all upgrade to schema v2 without losing canonical truth.
- Injected failure after step 0 -> 1 and step 1 -> 2 rolls back the active step;
  earlier committed steps remain resumable and the retained backup remains
  available.
- Integrity and foreign-key checks are observed after every migration step.
- Unknown central versions, newer projection versions, and stale component
  markers are refused byte-for-byte unchanged.
- Recovery is real: canonical truth is deleted from an upgraded working copy,
  its retained legacy backup is restored atomically, and the restored database
  reopens and upgrades with graph truth preserved.
- The strict non-external audit scope collected and passed 1,570 tests.
- The complete non-external repository scope collected 2,130 tests: 2,128
  passed and the two established cases xfailed, with no skips or failures.
- A full S2 code review reported zero findings after its useful tuple-row
  compatibility and transactional-hardening findings were addressed. The final
  whole-tree rerun after a narrow fixture-contract change and this handoff was
  blocked by the free-plan rate limit; paid review was not enabled.

## Honest boundaries

- No provider-paid benchmark, retrieval measurement, artifact build, publish,
  deploy, or release was run.
- The local pgvector container was healthy, but `PGVECTOR_TEST_DSN` was not
  exported to this process, so the external test lane was not rerun for S2.
- Existing stale KG4/newer graph projections still fail closed. Their
  non-destructive, history-equivalent replacement belongs to S3.
- Protected-main CI and merge remain the publication boundary.

## Exact next move

Implement S3 from `docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md`: make temporal
supersession canonical, then prove graph reprojection is guarded,
non-destructive, atomic, and history-equivalent. Keep the S2 migration spine as
the sole layout-change path and retain byte-unchanged refusal for unsupported
projection states.
