# Two-week protocol retrospective — 2026-10-16

This is a bounded review of recorded delivery and protocol evidence for October
2–16, not a whole-product audit. See HISTORY#685. The operator requested a
retrospective after incorrect completion/priority statements and concern that
repository protocol had been bypassed.

## Verified scope and limits

The [merge matrix](evidence/2026-10-16-protocol-retrospective/merged-pr-ci-evidence.json)
covers source PRs279,281,283,284,285,286,288,289,303,304,305,307,308,309 and311.
An independent read-only review inspected paginated exact-candidate check runs
and immutable Git merge objects. All45 selected required checks succeeded
before their respective merge. All15 reviewed merges have the candidate as
second parent and an identical candidate/merge tree. No required-CI bypass was
found in that scope. This does not establish every earlier startup read,
prewrite admission, TDD cycle, review, stored qualification or product exit.
The export is not an independent enumeration of every merge in the window.

Historical raw qualification receipts were not available to the independent
reviewer. Root's bounded search of known retained queue/evidence roots did not
recover all older receipts. Missing evidence remains Partial; present-day green
checks cannot recreate or retroactively qualify those earlier phases. No
provider, external service, native installer or full product regression was run
for this retrospective.

## Confirmed defects and corrections

1. **Merge verifier omitted phase chronology.** At base
   `fa66a82771de298bc46f965c2cd7855cadc8f5d6`,
   `tools/ci/verify_merge.py` selected required-check facts and accepted an
   admitted qualification but did not compare their times with the merge.
   The public CLI regression
   `tests/audit/test_verify_merge.py::test_verify_merge_rejects_qualification_completed_after_merge`
   actually returned PASS/exit0 when qualification followed the merge; its
   intended RED was witnessed before implementation. The repair enforces
   aware timestamps and check start ≤ completion ≤ qualification ≤ merge,
   before local Git/gates/output. It preserves latest-run fail-closed selection,
   timestamp strings and the existing evidence schema. This proves recorded
   completion order only, not when a receipt was physically stored or whether
   startup and prewrite rules were followed.
2. **PR305 has a public qualification-sequence discrepancy.** Its
   [11:41:24Z comment](https://github.com/Canticle-AI-Research/Seam/pull/305#issuecomment-6167506629)
   announced QUALIFIED/stored while waiting for required CI. The final required
   check completed11:42:48Z; merge occurred11:43:19Z. The governing workflow at
   `ffd4e98cd28fb9054eb1669c6a2f7835538921f6`, section10, already required exact
   successful required CI for release qualification. The announcement conflicts
   with that order. The raw receipt and any later successor have not been
   recovered in the bounded search, so actual later admission remains unresolved.
   Required checks were green before merge; no new retrospective receipt is made.
3. **The first PR307 publisher attempt failed clean-checkout continuity.**
   [Run38560873494](https://github.com/Canticle-AI-Research/Seam/actions/runs/38560873494)
   failed before upload because the retained snapshot was older than current
   history. PR308 repaired runner-local snapshot preparation; the successful
   [publisher38562182535](https://github.com/Canticle-AI-Research/Seam/actions/runs/38562182535)
   and HISTORY#680 retain completed TestPyPI/downloaded-install acceptance.
   Neither failure nor later success is hidden or relabeled.
4. **Stale current records misrepresented completion and priority.** Licensing
   was completed in PR286, with artifact scope in288. Reporting it as next was
   incorrect. This candidate updates the ledger/layout pointers to distinguish that completed
   scope and TestPyPI delivery from remaining documentation review and production
   delivery. The current retrieval status route is a pointer to
   `docs/status/retrieval.md`; historical measurements are not silently replaced.
   The local primary ledger and merged-main ledger had different ancestry: the
   difference did not establish that a correction had been reverted on main.
5. **Merged PR descriptions retained draft/obsolete-candidate wording.**
   Bodies279/281/283/284 were corrected through authenticated GitHub REST and
   read back. Preparation-time scope and test boundaries remain dated;284 now
   explicitly distinguishes its earlier CI candidate from final `a4262c02`.
   Description correction does not upgrade old qualification evidence.
6. **Tracker summary, task and baseline disagreed.** Request25207 was already
   QUALIFIED at12:51:15Z while one parent row and baseline child still called it
   pending. Active records now agree with the original receipt; old events stay
   dated. A later administrative request was independently qualified19:49UTC and
   admitted before this repair's worktree/source writes. The inspected primary
   scope then contained35records:20qualifying and15validsuperseded, pending0.
   That acceptance covers retained administrative state, not historical products.
   The existing four-hour monitor now cross-checks active records before an
   unchanged receipt and preserves settled licensing and phase limits.

## Preserved evidence and next exits

PR311's actual required CI completed13:38:02Z, qualification completed
13:39:56.989549Z and merge occurred13:41:11Z. Those recorded times are ordered;
the newly found verifier defect does not invalidate their actual chronology.
For that specific cleanup, retained action metadata also places admission of
three administrative receipts and pending0 before worktree creation and builder
start. This is a bounded observation, not blanket proof for the fortnight.

All eight original cleanup candidates remain closed **without merge**, with
exact source preserved and recovery issues retained. Licensing and the Suite
2.4.1rc1 TestPyPI delivery remain completed. Complete the reviewed chronology
repair through required CI, subsequent independent qualification, protected
merge and actual resulting-main verification. Then return to the remaining
finite documentation/disposition review, followed by conditional independent
Doctor. Historical evidence gaps and advisory runner issue293 remain explicit.
No license activation, production release, website deployment, model/provider
execution or unrelated product implementation belongs to this repair.

## Verification checklist

- Actual public CLI RED preceded implementation; three vertical cycles are
  recorded in the evidence below, with retained log hashes.
- Builder and independent implementation reviewer each executed the32-case
  verifier suite successfully. Root's five-module affected slice collected and
  passed145cases. A mistyped first invocation exited4 before running tests;
  its corrected actual filename and successful result are recorded separately.
- Canonical working-tree secret scanner passed; existing policy-excluded binary
  and pinned oversized paths remain explicitly excluded by the canonical tool.
- Required hosted CI, release qualification, protected merge and actual resulting
  main checks remain later delivery phases; this report does not predeclare them.

## Evidence manifest

- `docs/audits/evidence/2026-10-16-protocol-retrospective/local-verification.json` — SHA-256: `c8d00f5d26a374c5ed84b8d1fbef81b7c788be12a3dc4be80803d4afb1c9861e`
- `docs/audits/evidence/2026-10-16-protocol-retrospective/merged-pr-ci-evidence.json` — SHA-256: `b6c8329ecc49a4c3e9bd0d7f0a64313d84c6999d4f6a6e7dfc8379cfbb02ae3e`
- `docs/audits/evidence/2026-10-16-protocol-retrospective/pr-description-corrections.json` — SHA-256: `287a39da1c3eb02897511eb01dc951c16990bddd9940dc2e3febf20dad793222`
- `docs/audits/evidence/2026-10-16-protocol-retrospective/tdd-evidence.json` — SHA-256: `af67d7709c115854d75a3d4ae15961a7941edf8de3e249ae08e41c4e4d436cf4`
