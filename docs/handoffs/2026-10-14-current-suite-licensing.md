---
handoff_id: 2026-10-14-current-suite-licensing
supersedes: 2026-09-30-agent-config-gates-landed-next
handoff_status: current
history: HISTORY#665
---

# Current Suite licensing continuation

The owner decision is settled: proprietary Suite, free personal noncommercial
self-hosting, separate written agreement for business and organizational use,
and no separate paid SDK inclusion. Embedded MIRL/HS/1 use may operate the Suite;
independent reuse and redistribution remain reserved. Do not ask the owner to
repeat the decision. See [the report](../audits/2026-10-14-licensing-reconciliation.md)
and [the licensing status](../status/packaging-licensing.md).

The first-launch licensing successor starts from protected main
`e4abc1d9c9b1afb415ad67e06a3e7bb6907ecee1`. It refreshes the exact current
implementation manifest and aligns controlling terms, package metadata and
current documentation. Historical license files and runtime source remain
unchanged; no rollback or legacy-user migration work is included.

The remaining dependency/release/MCP work stays on draft PR #266. This successor
does not import its colliding branch-local HISTORY IDs or claim to clear its
cumulative package qualification condition. Website PR #29's conflicts and
acceptance are separate. Earlier unrelated closeout requests recorded by the
predecessor are preserved; none are present in this fresh workspace's queue.
No user-owned dirty files or stashes were present at task start.

Finish exact-state independent review, continuity qualification and required
checks on the focused licensing PR. After protected integration, continue
package/TestPyPI qualification as a separate task. `Private :: Do Not Upload`
remains; no upload, registry registration, release or deployment follows from
the licensing change.
