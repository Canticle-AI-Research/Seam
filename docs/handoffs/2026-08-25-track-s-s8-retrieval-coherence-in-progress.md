---
handoff_id: 2026-08-25-track-s-s8-retrieval-coherence-in-progress
supersedes: 2026-08-24-track-s-s7-merged-s8-next
handoff_status: superseded
history: HISTORY#605
---

# Track S S8 retrieval coherence — first bounded slice in progress

## Exact branch boundary

- Worktree: `/home/terrabyte/Documents/Projects/Seam-track-s-s6`.
- Branch: `track-s/s8-retrieval-coherence`.
- Exact protected base: `440a014313870067d4c2f04a528aec9e235ba01f`,
  the merge of chronological handoff PR #227.
- This is a branch-local, in-progress S8 slice. It is not S8 completion, S9
  qualification, protected-main behavior, or a release claim.

## Implemented slice

- `normalize_leg_weights()` owns a closed set of exact canonical RRF leg names:
  `sql`, `vector`, `graph`, `graph_node`, and `temporal`.
- Misspelled, legacy-only, or whitespace-padded leg names fail at the public
  runtime boundary before retrieval planning, adapter search, or
  candidate-dependent fusion. Configured-but-inactive exact known legs remain
  valid.
- The orchestrator validates once before planning and reuses that normalized
  map for ranking, so trace configuration and ranking cannot diverge through
  implicit leg-name normalization.

## Verification and review

- The unknown-leg runtime tracer failed red with `DID NOT RAISE`, then passed
  after the closed-name validation was introduced. The whitespace-padded
  `" vector "` tracer independently failed red with `DID NOT RAISE`, then
  passed after implicit `.strip()` normalization was removed.
- `tests/audit/test_fusion_leg_weights.py` passed 21 tests. The affected fusion,
  retrieval-consolidation, trace-plumbing, and retrieval-flags slice collected
  and passed 69 tests.
- The first complete `tests/audit -q` run reached 100 percent without assertion
  failures but correctly failed strict no-skip because both real-pgvector DSNs
  were absent and 23 service tests skipped. The existing local
  `seam-pgvector` container was started and reported healthy; the five affected
  pgvector modules passed 30 tests with both DSNs set. The complete live-DSN
  audit rerun collected 2,458 tests across 191 files and passed at 100 percent
  with no failures or skips. The container was then restored to its pre-session
  stopped state.
- Changed-path Ruff, `git diff --check`, and the canonical secret/private-session
  scan passed. CodeRabbit CLI 0.7.5 reviewed the exact three-file uncommitted
  diff against `440a014313870067d4c2f04a528aec9e235ba01f` and returned zero
  findings.

## Remaining S8 exits

This slice does not close the other campaign exits. Still required:

- persisted absent/all-one/zero/non-unit weighted-policy replay, including
  bitwise all-one parity with `reciprocal-rank-fusion/2`;
- candidate-ID and order parity across every shipped retrieval surface;
- exactly one tenant-scoped retrieval event per enabled successful retrieval,
  with telemetry failure answer-inert;
- reversible, fully audited accepted identity merges;
- the bounded process-lifetime flag-cache decision, SQLite 999-variable floors,
  and boundary-only SQL/legacy policy decisions assigned to S8 by the deployment
  audit.

## Next steps

1. Finish canonical derived-state closeout and all unsuppressed session-end
   gates for HISTORY#605.
2. Secret-scan and explicitly stage only the owned S8 and chronological
   closeout paths; create and verify a signed commit.
3. Push `track-s/s8-retrieval-coherence`, open a draft PR, and require exact-head
   CI plus review before any protected-main or completed-stage claim.
4. Continue remaining S8 exits as bounded red-green slices. S9 remains the
   promotion gate; do not enable or claim unqualified graph/scorer behavior.

The dirty primary checkout, unrelated worktrees and branches, sibling
repositories, ignored artifacts, provider assets, and operator work remain
outside this workstream and must stay untouched.
