---
handoff_id: 2026-09-06-l1-packaging-candidate
supersedes: 2026-09-06-launch-baseline-packaging-next
handoff_status: current
history: HISTORY#636
---

# L1 packaging candidate and private paid SDK boundary

## Resume point

Read the [L1 packet](../audits/2026-09-06-l1-packaging-migration.md) and
[packaging status](../status/packaging-licensing.md). They own the artifact map,
installed compatibility evidence, exact file hashes, and release blockers.

The operator clarified that SEAM SDK is private, with access for paying users.
It is distinct from the public HTTP client. Further paid capabilities are not
specified. No source, package coordinate, license text, customer access,
release workflow, deployment or published artifact was changed.

The candidate branch is `docs/l1-packaging-migration-20260906`, stacked on
the documentation source `2551830`. PR #250 merged at protected
`7c0810447d46afd5aa419651926c767400d43d87` after its required checks passed;
the L1 commit is rebased on that merged baseline before pushing. The operator
authorized this handoff, push and protected merge after verification. L1 still
requires its own exact-head checks and merge. Reconcile the PR state before
resuming; the indexed document survives the temporary worktree.

## Evidence and remaining work

Runtime source `2551830` and private SDK source `294ab08` were built outside
the source tree. Archive scans passed, as did scoped installed local SDK/HTTP
calls, the private SDK's existing reasoning tests, and a synthetic 1.3.1
runtime database upgrade. The report contains the exact scope and limitations.

The private SDK still pins runtime `6b746ad`; it differs from current runtime
in semantic graph seeding defaults/None handling and persisted retrieval leg
weights. Repair and qualify it in its private repository before a customer
repin. Do not copy its implementation into this repository.

PyPI ownership and the missing legacy source repository remain unverified.
The current runtime build shares version 2.4.0 with a different historical
release; a successor needs a fresh version and exact membership/notices review.
Paid SDK delivery and compiled self-host migration also remain explicit work.
The new package names are provisional, with no name reservation or upload.

Next: review the stacked documentation candidate, resolve operator-owned
source/ownership and distribution decisions, and take R2 as the next runtime
slice. Keep L1 release blockers explicit through later launch qualification.
Package publication, paid provider calls and deployment remain outside the
authorized documentation push/merge.

## Preserved work

The primary audit checkout remains on `docs/deep-audit-20260829@780b377`.
Its modified history/index/stream files, audit and handoff registries,
`docs/handoffs/2026-08-29-grounded-research-acquisition-roadmap.md`, untracked
audit/handoff files, `.codex/`, `.disposable/`, and `.seam/orchestration/` are
excluded. The complete primary path inventory remains in the predecessor
[handoff](2026-09-06-launch-baseline-packaging-next.md#preserved-work-and-exclusions).

The locked audit-cleanup worktree and staged/unstaged Codex hook candidate are
also excluded. Preserve them. A documented one-push dirty-worktree exception
may be used to preserve the unrelated hook candidate; it does not waive commit
signing, candidate scans or continuity checks. No stash was created.

The temporary L1 worktree is removed after its reviewed commit is pushed.
Local artifacts remain at
`/home/terrabyte/.local/share/seam/packaging/l1-20260906`; portable hashes,
inventories and sanitized probe evidence are tracked beside the report.
Independent documentation assurance accepted the repaired evidence packet.
All canonical closeout gates passed after correcting archive-member citations.
Final exact-state qualification and CI results belong to the candidate receipt
and PR. HISTORY#635 records artifact preparation; HISTORY#636 records the
later documentation merge authority and protected baseline.
