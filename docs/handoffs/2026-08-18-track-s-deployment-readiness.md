---
handoff_id: 2026-08-18-track-s-deployment-readiness
supersedes: 2026-08-12-deep-audit
handoff_status: current
history: HISTORY#571
---

# Track S, graph evidence, operator surfaces, and deployment readiness

## Current state

The complete audit and dependency-aware to-do are in
`docs/audits/2026-08-18-track-s-deployment-readiness-audit.md`. The benchmark
portfolio and causal claim gates are in
`docs/audits/2026-08-18-graph-benchmark-readiness-research.md`.

- S0-S5 are published.
- S6-S10 remain open in that order.
- The repair candidate closes the 2026-08-12 full-audit F-5, F-6, F-10, and
  F-11 plus several bounded hygiene defects; those are not the campaign matrix
  IDs, and none becomes protected-main fact before its PR merges.
- Existing graph measurements prove plumbing and parity, not graph-caused
  competitive lift.
- The Textual TUI is a functional local surface with unfinished operator
  workflows. The operator's newer TUI source was not found and must be supplied.
- The WebUI is not beta-ready because simulated/browser-local actions are
  presented as live. Truthfulness and credential handling precede restyling.
- Hosted deployment remains blocked by S6 and an unimplemented production
  service/backup/rollback topology.

## Resume in this order

1. Reconcile protected main, the repair PR, draft PR #221, exact-head CI, and
   `docs/status/workspace.md`; whichever candidate lands second must rebase
   its next HISTORY entry.
2. Land or revise the bounded repair candidate.
3. Close the TUI provider-host and response-allocation parity gaps in a focused
   security slice.
4. Implement S6 principal binding and opaque delete.
5. Execute S7, then S8, then the multi-benchmark S9 program.
6. Obtain and integrate the operator's newer TUI source.
7. Make the WebUI truthful and backend-backed, then run the visual design pass.
8. Complete the S10 release and deployment proof before hosted beta wording.

## Verification boundary

No paid benchmark, model-provider call, hosted deployment, release, merge, or
publication was performed by the audit. Exact candidate verification and
remaining risks are recorded in HISTORY#571 and the repair PR.
