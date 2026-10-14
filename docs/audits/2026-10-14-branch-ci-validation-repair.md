# Branch recovery CI validation repair — 2026-10-14

GitHub rejected the first PR #303 workflow before allocation because job-level
`env` referenced `runner.temp`, a context unavailable at that location. The
fixture state now uses a unique workspace-relative ignored test path with only
GitHub run/attempt IDs. A witnessed regression fails on the rejected setting;
all 19 fixture/gate cases pass after repair. The fixture implementation, image,
47-case actual service evidence, manifest and qualified package inputs are
unchanged. Actual GitHub execution must still pass on the successor head.

Independent exact-state release verification also rejected two nonexistent
root-supplied affected-test paths. The immutable first NOT_QUALIFIED receipt is
stored. The intended real snapshot/outbox modules both pass (42 cases), and
root state now names those actual files. The successor must rerun the corrected
list and all required checks, then explicitly supersede the earlier request;
no earlier verdict is upgraded or deleted. See HISTORY#671 and the
[branch plan](../roadmap/BRANCH_RECOVERY.md).

## Evidence manifest

- `docs/audits/evidence/2026-10-14-branch-recovery/workflow-context-repair.json` — SHA-256: `302a9a28be82ab0ec06f370cbeb5f4f417b41f5935be3246ef5982c57da1e741`
