---
handoff_id: 2026-09-07-s8-protected-main-suite-next
supersedes: 2026-09-07-r2-backend-s8-qualified
handoff_status: superseded
history: HISTORY#641
---

# S8 protected freeze; bounded operator-product work next

## Completed source boundary

R2 and the documented S8 completion gate are complete. PR #254 protected-merged
candidate `a6715c2f32f3c72efd501fb8be6b3303a9a105f3` at
`2f9a96b9bbc1015bb8057e01793e42cec95034af` on 2026-09-07. This is the frozen
S8 source baseline. Candidate and merge trees are identical. Required
`repo-hygiene`, `chroma-real-smoke` and `locomo-quickstart-bil2`, plus the changed
backend's `pgvector-integration`, passed on the candidate and exact main
(CI runs `34085941485` and `34086580171`). The candidate advisory test-and-benchmark job also passed. Exact-main
advisory results must be read separately; required-job success is not a
whole-workflow claim.

An independent read-only release agent authored the candidate's `QUALIFIED`
receipt. Root validated and stored it through `tools.agents.closeout_queue`,
rechecked the fingerprint immediately before merge, and confirmed candidate
ancestry and exact-main tree identity afterward. The preceding local handoff
and HISTORY#640 remain the candidacy checkpoint, not a rewritten merge record.

The [S8 evidence matrix](../../tests/docs/s8-completion.md) maps every original
exit and D1-D4/T1/G1/R1/R2 prerequisite. The fresh source integration selection
passed 3540 cases, explicitly deselected 65 external cases and retained two
established xfails, with zero skips and unchanged source/test/CI hashes. Real
backend tests, independent Chroma growth assurance, original-vector precision,
optional HNSW-plan admission, mode traces and separate scale limits are in
[backend evidence](../../tests/docs/r2-backend-parity.md).

The SQL-tail boundary decision remains inclusive 0.80 for query-authored
namespace plus scope; `legacy-weighted/1` remains the compatibility default.
Exact vector search is the default, approximation is explicit, and existing
external projections without original vectors need explicit reindex/sync.
Selected-corpus work, scalar metadata and cache storage can grow. The source
freeze does not establish ANN recall, benchmark advantage, S9 Promotion,
S10 release/deployment proof or hosted production.

## First next action

The R2/S8 core initiative is finished. Start the next bounded product pass from
the [surface inventory](../status/surfaces.md) and
[launch acceptance](../roadmap/SEAM_LAUNCH.md). Reconcile current code first,
choose one real Suite/API/WebUI workflow, and define its public-seam success
and failure behavior before implementation. A useful first vertical workflow
is ingest, retrieve and inspect the supporting evidence with truthful backend
acknowledgements. Keep independent graph/database/glassbox sections and
Review/Curate/Health acceptance in the product plan; do not infer UI completion
from S8 backend tests.

L1 customer-delivery/artifact ownership blockers and private paid SDK
compatibility remain in the packaging packet. Expensive score campaigns follow
operator-product completion; agree the benchmark/metric and evaluation budget
before pursuing the 90 percent target. No paid provider, package publication,
deployment, or new ranking-default Promotion was authorized or performed here.

## Documentation successor and local cleanup

This successor changes only documentation/continuity and retains the frozen
runtime/test/CI source bytes. Its own protected PR and exact-main required
checks must be reconciled live; they do not redefine the S8 runtime baseline.

Preserve the primary `docs/deep-audit-20260829` checkout's modified HISTORY,
index/history-stream/cross-index files, audit/handoff indexes and older
grounded-research handoff, plus untracked `.codex/`, `.disposable/`,
`.seam/orchestration/`, cross-index archive, full-repo audit and deep-audit
handoff. Preserve the locked audit-cleanup and dirty Codex-hook worktrees.
No stash was created. Root owns final cleanup of this session's two merged
branches and backend worktree only.

Before worktree removal, retain logs/manifests/scripts, snapshots, original
session state, packets and both independently authored receipts under the
primary `.seam/orchestration/completed/r2-s8-freeze-20260907/` evidence home.
Generated test databases are disposable scratch, not source evidence. Stop
only `seam-r2-backend-20260907` and remove its generated connection file;
preserve `hebhive-db`. The preserved primary checkout is intentionally old and
dirty: read the registered handoff from freshly fetched `origin/main` when
resuming instead of treating its old working-tree docs as current source.
