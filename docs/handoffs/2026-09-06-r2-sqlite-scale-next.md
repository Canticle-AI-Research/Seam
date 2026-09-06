---
handoff_id: 2026-09-06-r2-sqlite-scale-next
supersedes: 2026-09-06-l1-packaging-candidate
handoff_status: current
history: HISTORY#637
---

# R2 structured SQLite scale slice; acquisition and backend parity next

## Resume point and authority

The operator requested continued R2 work, a handoff at context capacity or
completion, then push and protected merge. This session started from freshly
fetched `origin/main@2f6e7478f38dad918bc448eaaf53e50764a69525`, the verified
PR #251 merge. The L1 handoff's pending-merge statement is therefore historical;
its release blockers remain open. The isolated branch is
`fix/r2-bounded-candidates-20260906`; its name does not imply that compatibility
or temporal candidate acquisition is fixed.

The session closes one coherent R2 slice at the context checkpoint. Reconcile
the PR head, merge state and required checks before resuming. Source changes,
local tests, protected merge, S8 freeze, S9 qualification and deployment remain
separate claims. Package publication and deployment are outside this task.

## This slice

Structured SQL previously grouped every `vector_index` row before joining the
requested canonical namespace. The candidate replaces that global aggregation
with a per-record indexed lookup while preserving `max(source_text)`, payload
fallback, scoring, query-authored boundary gates and record-ID ties.

Verification evidence and its measurement boundary are recorded in
`tests/docs/r2-sqlite-scale.md`. The public regression uses
`SeamRuntime.retrieve(mode="hybrid")`: `sql` is an internal leg, not a supported
public mode. It measures that leg separately from semantic retrieval and
provenance work. Fixed-slice SQL evidence is not a whole-request latency or
whole-R2 scale claim. The query also feeds graph seed acquisition, so R1 graph
boundary regressions remain in the affected verification scope.

## Next R2 work

1. Address temporal candidate acquisition in `SQLiteTemporalAdapter.search`.
   It still loads the namespace before ranking. Preserve canonical UTC instant
   handling, inclusive windows, decay scores, invalid-time exclusion, history
   filters and deterministic ties. The existing `seam_timestamp_key` SQL
   function is backed by `seam_runtime/temporal.py`; avoid introducing a second
   timestamp parser or losing subsecond ordering. Test the public retrieval
   seam, returned IDs/scores and materialized-record growth separately from
   database scan work. No temporal optimization was implemented here.
2. Address `LegacyWeightedAdapter.search` without an arbitrary top-N prefilter.
   `search_batch` builds symbol maps, graph neighbors, entity labels and BM25
   statistics from the full batch. Chunking candidates alone changes that
   context, and bounded memory alone does not prove flat latency. First pin
   score/result parity on symbols, graph grounding, RAW/BM25 and temporal
   contexts; then design bounded acquisition/metadata access with explicit
   cost measurements. `legacy-weighted/1` remains the compatibility default.
3. Repair pgvector HNSW expression use together with deterministic cut/tie
   behavior, as paired findings F-13/F-29 require. The change can make a
   previously exact scan approximate; prove the admitted plan and retrieval
   parity on an isolated live service rather than treating an index name as
   evidence. Include SQLite/pgvector/Chroma tie cases and fixed-slice budgets.
4. Independently assure the remaining R2 work and qualify its exact protected
   main before freezing S8. S9 and S10 remain open; no paid benchmark was run.

## Other unresolved work

The first broad audit run had two location-dependent failures in
`tests/audit/test_locomo_result_durability.py`: its assertions require the
repository's default result paths to live outside `/tmp`. The worktree was
moved intact to
`/home/terrabyte/Documents/Projects/Seam/.worktrees/r2-sqlite-scale-20260906`;
that complete test module then passed. Use a persistent worktree for the full
audit suite. Separately, existing REST TestClient tests stalled in the sandbox
thread portal; the same focused selection passed unrestricted. Neither issue
required changing runtime behavior or weakening a test.

L1's private SDK repin/behavior drift, delivery and source ownership,
successor version, artifact membership/notices and compiled self-host migration
remain in `docs/handoffs/2026-09-06-l1-packaging-candidate.md` and its report.
No package, license, customer-access or service change belongs to this R2 slice.

## Preserved work and cleanup

The primary checkout remains `docs/deep-audit-20260829@780b377`. Excluded modified
paths: `.seam/cross_index.md`, `.seam/streams/history/index.md`,
`.seam/streams/history/log.md`, `HISTORY.md`, `HISTORY_INDEX.md`,
`docs/audits/INDEX.md`, `docs/handoffs/INDEX.md`, and
`docs/handoffs/2026-08-29-grounded-research-acquisition-roadmap.md`.
Excluded untracked paths: `.codex/`, `.disposable/`, `.seam/orchestration/`,
`.seam/cross_index_archive/0001-0477.cross.md`,
`docs/audits/2026-08-29-full-repo-audit.md`, and
`docs/handoffs/2026-08-30-deep-audit-findings.md`.

Also preserve the locked audit-cleanup worktree and dirty Codex-hook candidate.
The documented one-push `SEAM_ALLOW_DIRTY_WORKTREES=1` exception may preserve
those exclusions; signature, content scanning and continuity gates still apply.
No stash was created. The clean R2 worktree and merged local branch are removed
after publication; the canonical handoff and tests survive on protected main.
