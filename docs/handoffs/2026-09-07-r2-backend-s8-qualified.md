---
handoff_id: 2026-09-07-r2-backend-s8-qualified
supersedes: 2026-09-07-r2-acquisition-backend-next
handoff_status: superseded
history: HISTORY#640
---

# R2 and S8 locally qualified; protected freeze candidate

## Exact checkpoint

Branch `fix/r2-backend-parity-20260907` starts at protected
`main@5f115664b7ce7bd01f04b6f21ce5c3cf53ea0d0b` (PR #253), in
`.worktrees/r2-backend-parity-20260907`. SQLite structured scale and
temporal/compatibility acquisition are already merged through PRs #252/#253.
The operator approved completion through protected push/merge, exact default
search, explicit approximation and smaller-record-ID ties. No further policy
decision is pending for this slice. Preserve `legacy-weighted/1`.

R2 source, local qualification and independent assurance are complete. This
handoff is authored before candidate CI, independently stored release receipt,
protected merge and exact-main checks. Reconcile them live before asserting
the frozen S8 baseline. Do not equate this checkpoint with S9/S10, a package
release, a deployment, or benchmark-quality improvement.

## Evidence and repaired recovery

The [backend evidence](../../tests/docs/r2-backend-parity.md) owns exact scores,
cutoffs, mode traces, coverage, original-vector migration, locking and separate
scale/cost limits. The [S8 matrix](../../tests/docs/s8-completion.md) maps all
D1-D4/T1/G1/R1/R2 and original S8 exits to executable tests.

The fresh full non-external integration result is 3540 passed, 65 deselected, 2 xfailed, 2 warnings in 508.17s (0:08:28).
The live-backend run passed its 64 pre-growth cases; the final real-Chroma
selection passed 25 cases and the new growth case passed independent rerun.
Core tests explicitly deselect external cases; no skip was admitted. All
changed-module collection, optional-dependency absence, scoped and whole-repo
lint checks passed. Raw commands, times, hashes and logs live under
`test_seam/r2-backend/resume/`.

Two inherited downgrade/native-query test fixtures needed repair. Assertions
remain intact; the Chroma fake also checks model/dimension predicates and
works without the optional package. Runtime bytes did not change on resume.
Earlier interrupted/failed suites remain recorded, including the already
redacted credential-bearing traceback. Those runs are not relabeled green.

Independent standards and spec reviews have no unresolved blocker. A duplicate
top-K heap is a nonblocking future runtime-maintainer refactor, covered by
parity tests. The independent TDD preflight matched thirteen recovered cycles
to their original logs and timestamps, covering seven runtime files. Initial
mode/SQLite test-fixture adjustments remain documented; no missing per-function
hashes or retrospective authorship were invented.

## Finish publication, then stop this core initiative

1. Complete the canonical HISTORY#640 snapshot/gates, scan and sign explicit
   paths, push the coherent candidate, and create its protected-branch PR.
2. Verify required `repo-hygiene`, `chroma-real-smoke` and
   `locomo-quickstart-bil2` checks on that exact head. Inspect related failures.
3. Create an exact-state closeout request. A read-only independent release
   agent must author the receipt; root validates/stores it through
   `tools.agents.closeout_queue`. Recheck the fingerprint immediately before
   merging. Do not reuse an earlier slice's receipt.
4. Protected-merge, fetch and verify exact main, candidate ancestry and
   post-merge checks. Record the accepted protected source as the S8 freeze.
5. Leave the next bounded product handoff through
   [the launch plan](../roadmap/SEAM_LAUNCH.md): inspect and define acceptance
   for one real Suite/API/WebUI workflow. L1 SDK/artifact blockers remain;
   expensive score work, ranking Promotion and deployment need their own gates.

## Preserved local state and owned cleanup

The primary `docs/deep-audit-20260829` checkout remains excluded: modified
`HISTORY.md`, `HISTORY_INDEX.md`, `.seam/cross_index.md`, history stream files,
audit/handoff indexes and the older grounded-research handoff; untracked
`.codex/`, `.disposable/`, `.seam/orchestration/`, cross-index archive, full-repo
audit and deep-audit handoff. Preserve the locked audit-cleanup and dirty
Codex-hook worktrees. No stash was created.

Before removing this clean merged worktree, retain its logs, manifests, scripts,
session/packet state and independently authored receipt under the primary
`.seam/orchestration/completed/` evidence home. Large disposable test databases
need not be copied into tracked source. Stop only the owned
`seam-r2-backend-20260907` PostgreSQL container and remove its generated
outside-repository connection file. Preserve `hebhive-db`. Use the documented
one-push dirty-worktree exception only to retain excluded work, with signatures,
scans and all qualification gates still enforced.
