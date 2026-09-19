---
handoff_id: 2026-09-19-suite-license-review
supersedes: 2026-09-17-suite-mcp-registration
handoff_status: superseded
history: HISTORY#650
---

# Suite license review continuation

The [license/member review](../audits/2026-09-19-suite-license-membership.md)
continues the [MCP/package handoff](2026-09-17-suite-mcp-registration.md).
Exact saved wheel/sdist runtime bytes match PR #266 at `9f0bfae`; the
per-member evidence is now tracked. README scopes the existing free
self-hosting grant to qualifying Distributed Runtime material. No license
terms, runtime source, artifact contents or publication controls changed.

Two remaining licensing issues are explicit: candidate runtime membership
needs an owner decision; the local BUSL file omits the standard closing
permission/covenant sections. Do not add notices to all runtime files or
remove `Private :: Do Not Upload` as an inferred grant. The separate paid SDK
remains private and distinct from bundled `seam_runtime.sdk`.

Next: obtain the owner's exact candidate membership/delivery decision, repair
the license text consistently with that decision, rebuild fresh artifacts,
and verify notices, metadata and destination. Then qualify the applicable
TestPyPI/MCP path. No private-SDK upload, paid call, merge, release or deployment
is authorized by this report. The core implementation does not need a new
package split merely to complete the rights review.

Website PR #29 has a separate copy correction for blanket Apache/open-source
claims; read its current head and checks before reporting its delivery status.
Historical release claims are excluded from current-product copy repair.

PR #266's prior required checks failed or were cancelled. Its cumulative
package qualification remains `NOT_QUALIFIED / TDD_UNPROVEN`; any successful
documentation-only checks for this review do not clear those conditions.
Keep both PRs draft for the requested further review. Independent receipts,
current checks and exact heads must be refreshed before readiness claims.

The primary `docs/deep-audit-20260829` checkout and all unrelated linked
worktrees remain untouched. Its dirty audit/history/streams/handoff files and
untracked local directories are excluded as recorded in the review. Finish
and remove this session's isolated worktree after preserving its receipts and
snapshot; do not clean the primary checkout.
