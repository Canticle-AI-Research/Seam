---
handoff_id: 2026-09-07-r2-acquisition-backend-next
supersedes: 2026-09-06-r2-sqlite-scale-next
handoff_status: current
history: HISTORY#639
---

# R2 acquisition slice; backend policy and parity next

## Authority and baseline

The operator requested a verified work loop using subagents until R2 is
finished, with durable handoffs, pushes and protected merges. Read-only context
workers separated temporal acquisition, compatibility scoring and backend
parity. Delivery workers owned disjoint runtime sections; independent reviewers
receive the resulting code and exact public-test evidence.

This branch is `fix/r2-acquisition-parity-20260906`, based on freshly fetched
protected main `ab9fe4b8d0d6a2c8bac4449fb683e2a50539cb03` (PR #252). Its
working checkout is `.worktrees/r2-acquisition-parity-20260906`. Reconcile the
PR, remote head, required checks and stored current receipt before treating
candidate source as merged. `legacy-weighted/1` remains the compatibility
default. This slice does not freeze S8 or qualify S9/S10.

## Implemented acquisition work

`SQLiteTemporalAdapter` selects by canonical temporal score and record ID in
SQLite before loading winning MIRL payloads. Canonical scoring and Python
attribute-filter semantics are registered through the existing temporal
connection lifecycle; snapshot guards are unchanged. Exact UTC comparison,
inclusive windows, subsecond ordering, small positive scores, invalid-value
exclusion, history, and namespace/scope/query filters are covered by public
tests. Timestamp work still grows with the selected namespace.

`LegacyWeightedAdapter` uses a bounded cursor iterator and shared scoring
primitives instead of loading a full boundary into an IR batch. It retains the
original symbol, graph/entity and BM25 context. Query-specific BM25 statistics
replace retained document token tables. Weighted fusion retains top-K records;
internal RRF retains scalar IDs/channel scores for its full ranks. Peak record
and payload retention is bounded, while metadata and total work can grow.
No arbitrary top-N prefilter or new ranking default is introduced.

Evidence and verification boundaries live in
`tests/docs/r2-acquisition-parity.md`; new public regressions are
`tests/audit/test_s8_r2_temporal_scale.py` and
`tests/audit/test_s8_r2_legacy_scale.py`. Raw delivery logs, comparison outputs
and fingerprints are under the ignored `test_seam/r2-temporal/` and
`test_seam/r2-legacy/` paths during work. Preserve them outside any worktree
being removed; the primary `.seam/orchestration/completed/` directory is the
local retained evidence home. Portable source evidence must remain sufficient
to repeat the tests without those local files.

## Verified candidate checkpoint

HISTORY#639 corrects premature publication wording in HISTORY#638 without
rewriting that entry. Both independent runtime reviews passed after the
numeric-timestamp repair. The final complete local audit command in the
evidence document passed 2,929 cases, explicitly deselected 23 external cases,
and recorded zero skips; source hashes stayed unchanged throughout. Exact
pushed-head CI, a freshly authored release receipt and protected merge remain
pending at this checkpoint. Reconcile them live before continuing.

## Backend decisions and unfinished R2 work

Two operator decisions were requested and remain pending at this checkpoint:

1. Preserve exact pgvector retrieval by default and expose indexed approximate
   retrieval only through explicit selection, or allow an approximate default
   after measured quality qualification. The recommendation is exact default
   with explicit approximation. HNSW cannot guarantee exact SQLite membership,
   and reranking/oversampling alone does not repair missing candidates.
2. Standardize equal-score cutoff membership on smaller record IDs first, or
   preserve SQLite's historical larger-ID heap cutoff. The recommendation is
   smaller IDs first across backends, consistent with later canonical ranking.
   Do not silently implement either pending choice.

After those decisions, align PostgreSQL's query cast/predicate with its
dimension-specific HNSW expression index and verify the actual admitted plan
on a live isolated service. Test complete tied sets beyond backend and public
cutoffs, insertion/rebuild order, scope/namespace/model/render isolation,
near-tie arithmetic, and fixed-slice growth against SQLite and real Chroma.
Post-query sorting cannot recover records already lost at a backend cutoff.
The current Chroma fake's sorted output is insufficient evidence for this.

No backend source was changed for these pending decisions. Once backend work
is implemented, independently assure the full R2 diff, run required checks on
the exact pushed candidate, obtain a freshly authored and validated release
receipt, merge through the protected PR path, verify exact main, then evaluate
S8's full completion gate. S9/S10 and the prior L1 release blockers remain
separate; no paid benchmark, package publication or deployment was authorized
by this R2 continuation.

## Verification-record issue

The old PR #252 receipt's independent authorship is unverified: the release
worker reported that it did not author it or finish all attributed checks.
Do not rewrite that receipt or claim retroactive pre-merge assurance. A fresh
independent source review, public SQLite regression and canonical continuity
checks passed against clean exact main on 2026-09-07; the evidence document
records times, hashes and retained logs. Original `/tmp` red/green logs are no
longer available. Their historical hashes are not replacement raw evidence.

## Local state and cleanup

Preserve the primary `docs/deep-audit-20260829` checkout and its modified
`HISTORY.md`, `HISTORY_INDEX.md`, `.seam/cross_index.md`, history stream files,
audit/handoff indexes and older grounded-research handoff. Preserve its
untracked `.codex/`, `.disposable/`, `.seam/orchestration/`, cross-index archive,
full-repo audit and deep-audit handoff. The locked audit-cleanup worktree and
dirty Codex-hook worktree also remain excluded. No stash was created.

The detached baseline verification worktree was clean and removed after its
checks. The owned scratch `seam-r2-parity-20260906` PostgreSQL service passed
the existing external baseline suite and was stopped after that test window;
its generated credential file was removed. The unrelated `hebhive-db` service
was left running. Future backend qualification should start a fresh isolated
service and clean up only its own artifacts.

The documented one-push dirty-worktree exception may preserve the excluded
work while retaining signatures, scans and all gates. Archive the current
request, independently returned receipt and raw evidence before removing the
clean merged acquisition worktree and local branch. Keep a concrete blocker
and successor action if backend operator decisions remain unanswered.
