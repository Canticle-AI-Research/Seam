---
handoff_id: 2026-09-19-suite-personal-license
supersedes: 2026-09-19-suite-license-review
handoff_status: current
history: HISTORY#651
---

# Personal Suite license continuation

The owner resolved the [previous membership question](2026-09-19-suite-license-review.md):
Suite stays proprietary with free personal, noncommercial self-hosting only.
Business, employment, client and organizational use require a separate written
agreement through licensing@canticle.cc, including internal business operation.
MIRL/HS/1 may run as embedded components of the authorized Suite; extraction,
independent reuse, redistribution and commercial offerings are not granted.
The separate paid SDK remains excluded. Existing exact-version grants survive.

See the [decision and artifact review](../audits/2026-09-19-suite-personal-license.md)
for the narrow grant, manifest and fresh package evidence. Runtime code and
entry points are unchanged. Current product, release and website copy follows
the owner decision. The historical BUSL closing-text discrepancy remains a
separate unresolved issue; no new BUSL membership was granted.

Next: review this concrete licensing/package slice, resolve the cumulative
PR #266 `NOT_QUALIFIED / TDD_UNPROVEN` condition, and obtain required checks on
the pushed head. Then complete final release eligibility and TestPyPI publisher
qualification. Keep `Private :: Do Not Upload` until that release gate is met.
No upload, MCP registration, merge, deployment or paid call was performed.

Companion website PR #29 at `13a40ea1b44a6e11f3c56daf9f3077324ee08bc9`
contains matching current-product copy. Its focused checks pass; its full
Python baseline failures and email-worker failure remain. Pages preview is
available, but owner desktop/mobile acceptance is still pending. Both PRs
remain draft; local startup evidence is not full product qualification.

Preserve the primary `docs/deep-audit-20260829` checkout: dirty HISTORY/index,
history streams/cross-index, audit registry and handoff files; untracked
`.codex/`, `.disposable/`, `.seam/orchestration/`, cross-index archive,
audit/handoff documents and `error.log` are excluded. Hook, formation and sleep
worktrees remain separate. Archive this session's receipt/snapshot and remove
only its isolated task checkout after pushing the coherent branch slice.
