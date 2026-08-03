---
handoff_id: 2026-08-03-audit-repairs-merged
supersedes: 2026-08-02-track-s-audit-recovery-locally-repaired
handoff_status: superseded
history: HISTORY#528
---

# Audit repairs merged; S3 and S4 need a rebase before merge

**Date:** 2026-08-03

**Branch:** `main`

**Base:** `main@67d9c7c`

**Publication:** PR #193 and PR #196 are both **merged**. Nothing is pending
local publication.

## Current state

Read this instead of trusting any older status prose: the predecessor handoff
described PR #193 as an unmerged draft with protected `main` at `94375e8`. That
has not been true since 2026-08-02T11:55Z.

- `main` is `67d9c7c`. It carries the S2 migration spine, the HISTORY#525 audit
  remediation (PR #193, `6b7c22d`), and the HISTORY#527 second-audit repairs
  (PR #196, `67d9c7c`).
- Draft PRs **#194 (Track S S3)** and **#195 (Track S S4)** are open. Both were
  fully green — but against the *old* `repo-hygiene` gate.

## What changed under #194 and #195

PR #196 made the required `repo-hygiene` check materially stricter. Both open
PRs need a rebase onto `67d9c7c` and a fresh run before merge; their existing
green is stale evidence, not current evidence.

- `ruff check .` replaced `ruff check seam_runtime/ tools/ seam.py`. `tests/`
  was previously unlinted — roughly half the Python in this repo.
- `verify_integrity`, `verify_continuity`, `verify_routing`, and
  `verify_streams` moved out of the advisory `test-and-benchmark` lane into the
  required gate. Only `verify_handoffs` used to be required.

## Also worth acting on now

`test-and-benchmark` has been green on four consecutive PRs (#193, #194, #195,
#196). S10's exit gate promotes it to a required check "only after its green
proof is current and stable"; that condition now looks satisfied. Promoting it
is a ruleset change, not a code change.

## Open, with the reasoning that matters

Recorded in full in `PROJECT_STATUS.md`. The two that will bite a future stage
if taken at face value:

- **S5's exit gate is insufficient as written.** It says warm `mix` retrieval
  "opens no new physical SQLite connections". Routing the 11 `store._connect()`
  sites in `retrieval_orchestrator/adapters.py` through the pool would satisfy
  that clause and still leave the defect: `_connect` leaves `isolation_level`
  at the sqlite3 default, so every leg is its own read transaction and one is
  opened *inside* the hop loop. A `mix` search concurrent with an ingest can
  emit a path through a node the visibility check then drops, so
  `candidate_set_sha256` can attest a candidate set that existed in no single
  committed database state. S5 needs a snapshot-consistency clause, not just a
  connection-count clause.
- **S3's exit gate is 4/4 refusal-shaped** with no clause requiring a rebuild
  to succeed. A rebuild that does nothing passes all four. This is the same
  asymmetry that produced the missing forward-migration path in S2, and PR #194
  is open against it. Classified across the campaign: S5 2/6 positive, S6 1/4,
  S7 3/5, S8 4/6 — HISTORY#525's blanket "S3-S10 are all refusal" was too
  broad.

Also open: `/v1` has no tenancy binding and zero HTTP-level tests (S6 must
first decide whether tenancy terminates in a proxy or in-process — that is
written down nowhere); unbounded SQL variable expansion in
`knowledge_graph.py`; no ledger of shipped projection versions, so bumping any
of the 13 constants renders existing stores unopenable; 6 worktrees with 2
dirty.

## The gap to close next

`dashboard.py` (3,160 lines, zero dedicated test file), benchmark seal/BIL
integrity, and MIRL losslessness round-tripping have now gone **unaudited
across two consecutive whole-repo audits**. Six of eight audit lanes hit a
session limit before reaching them. This is untested ground, not
tested-and-clean ground, and it is the largest known unknown in the repo.

## Exact next move

Rebase #194 onto `67d9c7c`, re-run its checks under the stricter
`repo-hygiene`, and settle the S3 exit-gate asymmetry above before merging it —
adding a positive clause is cheaper now than retrofitting it after S3 lands.
