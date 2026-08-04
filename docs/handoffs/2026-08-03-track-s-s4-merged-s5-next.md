---
handoff_id: 2026-08-03-track-s-s4-merged-s5-next
supersedes: 2026-08-03-track-s-s4-requalified
handoff_status: superseded
history: HISTORY#531
---

# Track S S4 merged; S5 is the next stage

**Date:** 2026-08-03

**Branch:** `fix/history-worktree-lock-and-s4-registration`

**Base:** protected `main@ea4e46e`

**Publication:** S0-S4 merged; zero PRs open

## Current state

S4 is published through PR #195 at `main@ea4e46e`. All eight required and
advisory checks passed on the exact head `95a07ab` — `repo-hygiene`,
`chroma-real-smoke`, `locomo-quickstart-bil2`, `package-smoke`,
`pgvector-integration`, `registry-plan`, `test-and-benchmark`, and CodeRabbit —
and the branch was squash-merged and deleted. The predecessor handoff's "exact
next move" (force-push #195 and mark it ready) is complete and is retired here
so no later session re-runs it.

This document supersedes that handoff and opens S5.

## Why S5 and nothing else

S5 is the only stage unblocked by merged work. Reading the campaign's declared
dependencies: S5 needs S2 (merged); S6 needs S2 and S5; S7 needs S3, S4, and
S6; S8 needs S1, S5, S6, and S7; S9 needs S7 and S8; S10 needs all of S0-S9.
S5 is therefore the single node gating the remaining half of the campaign.

## What S5 already has, and what it does not

S4 shipped a per-canonical-store `_persist_projection_lock` that serializes the
write/index/compensate sequence in one process, plus `snapshot_vector_rows`,
`restore_ir_after_failed_projection`, and an `index_records_atomic` flag on the
vector adapters. That is a starting substrate. It satisfies **none** of the S5
exit-gate clauses, which remain entirely open:

- Crashes before and after canonical commit, vector indexing, and outbox
  acknowledgement must converge to the same state after reopen. The lock covers
  same-process failure only; process loss is untouched.
- Duplicate replay must be harmless.
- SQLite-vector, pgvector, and Chroma divergence must be detected and repaired.
- Warm `mix` retrieval must open no new physical SQLite connections, and a
  40-thread stress run must stay within the configured pool.
- Every SQLite-backed leg and visibility check in one retrieval request must
  read from one committed snapshot.
- Pgvector search must perform no DDL or schema-ensure operation.
- Ranking, IDs, order, and provenance must not change.

## The trap to design around, not discover

`HISTORY#528` recorded that routing the eleven `store._connect()` call sites
through a pool satisfies the pooling clause while leaving the read-snapshot
tear intact: `_connect` leaves `isolation_level` at the sqlite3 default, and one
connection is opened inside the hop loop. `HISTORY#529` then tightened the gate
to require the single-snapshot clause explicitly. Pooling and snapshot
consistency have to be designed together; a pool-only patch will pass one clause
and leave the observed mixed-state fingerprint defect in place.

## Also in this slice

`tools/history/new_entry.py` resolved its advisory lock with an `is_dir()` test
on `<repo>/.git`. In a linked worktree that path is a *file* holding
`gitdir: <path>`, so the check fell through to `HISTORY_INDEX.md.lock` beside
the index — untracked, inside the working tree, and swept up by `git add -A`.
It happened during the S4 closeout and the file had to be removed from the
index by hand before committing. `history_lock_path()` now parses the `gitdir:`
pointer (absolute or relative) and keeps the lock in the worktree's real git
directory; five tests in `tools/history/test_history_tools.py` cover the clone,
worktree, relative-pointer, no-git, and end-to-end no-stray-file cases.

## Honest boundaries

- S5 is unstarted. No outbox, pooling, divergence-repair, or snapshot-consistency
  code exists yet, and nothing in this slice measures any S5 clause.
- No paid provider call, competitive benchmark, retrieval-score claim, artifact
  publish, deploy, or release ran. This does not claim SEAM has beaten Mem0,
  Zep, or Cognee, reached 100% canonical memory, or eliminated model
  hallucinations.
- Unrelated open items carried forward, none of them Track S: `dashboard.py`
  (3,160 lines, no dedicated test file), benchmark seal/BIL integrity, and MIRL
  losslessness round-tripping remain unaudited across two consecutive
  whole-repository audits. `HISTORY#528` also noted that `test-and-benchmark`
  has now been green on five consecutive PRs, which satisfies S10's stated
  condition for promoting it to a required check — a ruleset change, not a code
  change.
- The `agent/track-s-s4-prep` worktree at
  `/home/terrabyte/Documents/Projects/Seam-track-s-s4-prep` is clean and fully
  merged but still present, along with several older worktrees. AGENTS.md
  requires finishing them; removal is left for explicit operator confirmation.

## Exact next move

Begin S5 on `main@ea4e46e`. Design the durable outbox and the pooled,
single-snapshot read path together, and write the crash-convergence and
40-thread stress evidence before claiming any clause.
