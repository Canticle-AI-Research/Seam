---
handoff_id: 2026-08-03-track-s-s5-locally-qualified
supersedes: 2026-08-03-track-s-s4-merged-s5-next
handoff_status: superseded
history: HISTORY#532
---

# Track S S5 locally qualified; publication is the next move

**Date:** 2026-08-03

**Branch:** `agent/track-s-s5-outbox-pooling`

**Base:** protected `main@50f4ead`

**Publication:** S0-S4 merged; S5 is local only; zero PRs open

## Current state

Every S5 exit-gate clause has local evidence. Nothing is published: exact-head
CI, CodeRabbit, and an independent diff review remain required, and the
live-pgvector lane (4 external cases) runs only in CI.

| clause | evidence |
|---|---|
| crash points converge after reopen | `test_vector_outbox_durability.py` |
| duplicate replay is harmless | `test_vector_outbox_durability.py` |
| SQLite/pgvector/Chroma divergence detected and repaired | `test_vector_divergence_repair.py` |
| warm `mix` opens no new connections; 40 threads stay within the pool | `test_read_snapshot_consistency.py` |
| one committed snapshot per request; no torn candidate set or fingerprint | `test_read_snapshot_consistency.py`, `test_retrieval_fingerprint_consistency.py` |
| pgvector search performs no DDL or schema ensure | `test_pgvector_search_no_ddl.py` |
| ranking, IDs, order, provenance unchanged | `test_read_snapshot_consistency.py` + full suite |

Full suite: **2024 passed, 4 skipped, 2 xfailed**; ruff clean.

## The trap, and what it actually took

`HISTORY#528` warned that routing the eleven `store._connect()` sites through a
pool satisfies the pooling clause while leaving the read-snapshot tear intact.
That was right, and it understated the surface by one reader: the SQLite vector
index is constructed on `store.path` (`runtime.py:106`), so the semantic leg is
a *second connection to the same file*. Pooling the canonical legs leaves it
reading its own committed state. Any design that enumerated only the eleven
sites would have passed its own tests and shipped the defect.

Two mechanisms carry the fix:

- Snapshots are keyed by **database identity**, not store identity, so every
  reader of one file joins one snapshot.
- The pool wrapper routes checkouts, so joining is the default. Editing ~100
  call sites would have left the guarantee dependent on none of them being
  missed later.

The snapshot holds a SQLite authorizer denying mutations for its duration. This
is not defensive decoration: the snapshot ends in `rollback`, so without the
guard a stray write inside a request would join the read transaction and vanish
silently — a data-loss mode strictly worse than the tear.

## Findings surfaced while building

1. **`SQLiteVectorIndex.ensure_schema` ran on every search**, re-executing its
   whole create/alter script on a fresh connection per query. This was the same
   defect as pgvector's F14 on the SQLite side, and it — not the adapter call
   sites — was why warm retrieval kept opening connections despite the pool.
2. **A failed persist must retire its outbox intents.** Four existing
   `test_runtime_persist_atomic_restore.py` cases assert that a failed vector
   index leaves the database logically identical. Intents left pending violated
   that. They are now retired when the restore succeeds and kept only when it
   does not, which is also the fail-safe direction.
3. **The first fingerprint test was not evidence.** It passed against a
   deliberately broken implementation. It varied record text per record, and
   under the 64-dimension signed hash embedding the distinguishing word
   collided destructively with the query term, scoring those records at or
   below zero and dropping them from the semantic leg — so a torn read produced
   no visible difference. The fixture now varies only record ids, and the test
   was re-verified to fail with the snapshot disabled.

Point 3 generalises: **every S5 test was run against a disabled snapshot**, and
the ones that did not discriminate were rewritten until they did.

## Honest boundaries

- S5 is **locally qualified, not published**. No PR is open.
- The live-pgvector clause is exercised provider-free against a recording
  cursor; the real service lane still runs only in CI.
- No paid provider call, competitive benchmark, retrieval-score claim, artifact
  publish, deploy, or release ran. Nothing here claims SEAM has beaten Mem0,
  Zep, or Cognee, reached 100% canonical memory, or eliminated hallucinations.
- Carried forward, none of them Track S: `dashboard.py` (3,160 lines, no
  dedicated test file), benchmark seal/BIL integrity, and MIRL losslessness
  round-tripping remain unaudited across two whole-repository audits.
  `test-and-benchmark` has been green on five consecutive PRs, satisfying S10's
  stated condition for promoting it to a required check — a ruleset change.
- Older worktrees remain present; AGENTS.md requires finishing them, and
  removal is left for explicit operator confirmation.

## Exact next move

Open the S5 PR from `agent/track-s-s5-outbox-pooling` against `main@50f4ead`,
and require all eight checks plus CodeRabbit on the exact head before merge.
S6 (principal tenancy and opaque deletion) unblocks only after S5 is published,
and must state explicitly whether tenancy terminates in a proxy ahead of `/v1`
or in-process — a decision currently written down nowhere.
