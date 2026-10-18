# Protocol completion and restart repair

[Report registry](INDEX.md) · [Current handoff](../handoffs/INDEX.md) ·
[Project status](../../PROJECT_STATUS.md)

Date: 2026-10-17
History: HISTORY#687
Reviewed base: `79c40b55f8aea7a6615bdccf4b331b41dd46a362`

## Scope

This is the bounded successor to the PR #313 restart/protocol audit. It verifies
the completion claims that govern the current task, corrects current resume
instructions, and repairs observable protocol boundaries. It is not an audit
of every historical roadmap completion, a new product qualification, or a
claim that every historical agent action followed protocol.

## Historical findings retained

| Finding | Verified consequence | Repair requirement |
|---|---|---|
| Session state initialized before all pending requests were reconciled | Ignored state was written early; tracked edits waited for admission | Gate initialization before any session-state write and include retained queue locations |
| Unexpected compaction was not reconciled | Planned-compaction recording failed because no prior COMPACT_NOW existed; work continued | Record the unexpected event honestly with an explicit recovery boundary; never invent a prior checkpoint |
| Whitespace repair followed independent assurance | Final release review covered the candidate, but assurance was not repeated before push | Bind assurance to the final committed content and invalidate it after any candidate change |
| Current handoff still described completed delivery as pending | A restart could repeat PR #313 work | Resolve completion from durable verified evidence and a conditional next action |

PR #313's successful exact-state delivery does not erase these process failures.
Original history, requests, receipts and dated reports remain unchanged.

## Completion claims checked

| Item | Supported status and evidence boundary |
|---|---|
| Licensing PR #286 and PR #288 | Merged ancestors of reviewed main; current Suite source manifest passes. No new legal interpretation or license change. |
| Suite 2.4.1rc1 TestPyPI | Fresh downloads match the exact accepted wheel/sdist hashes and sizes. GitHub publisher run38562182535 remains successful on source7b96a012; its historical downloaded-install logs contain eight tests and clean dependency checks per format. Installation acceptance is dated October14, not a fresh installation claim. |
| Protocol PR #312 | Preserved candidate/merge identities and actual Git trees agree; required check times precede qualification and merge; actual resulting-main proof records successful canonical gates. |
| Documentation PR #313 | Candidate1d42c3a merged79c40b55; required checks completed before qualification, which preceded merge. Preserved proof, canonical receipt and actual Git objects agree. Protocol follow-up is this separate repair. |
| Eight original PR dispositions | All remain closed without merge; all original source pull refs remain at their recorded tips. Deferred feature acceptance remains open. |
| Private website proposals / issue #291 | Exact private tag, branch and pull ref agree; all six preserved file hashes match. Proposal implementation remains planned in issue #302; no private contents were copied. |
| About reminder #287 | Current description matches the verified licensing wording; reminder remains closed. |
| PR #305 retrospective qualification | Partial remains Partial. Later success cannot manufacture missing historical evidence. |
| Doctor, deferred recovery and production | Not completed by these observations; retain their own acceptance gates and existing hold. |

PR #249's Dependabot branch is now absent remotely, while exact commit
`8d77775fe6e029717115758b917c94c757ed0d4a` remains at `refs/pull/249/head`.
The October16 receipt's branch-retention observation is preserved. Current
branch-recovery guidance and issue #301 carry this later correction; no cause
or actor is inferred and the comparator proposal remains held.

The current source/site workspace inventory found seven existing queue roots,
including the retained `Seam-pr-cleanup-20261016` location omitted from the
earlier six-root audit. All validated as reconciled before this repair's
worktree and session-state initialization. Unrelated dirty work was preserved.

## Delivery boundary

This repair is an in-progress local checkpoint. Automatic context compaction
actually occurred during its independent review. The immutable event
`automatic-20261017-repair-review` preserves the prior 74.677 percent usage,
`COMPACT_AT_MILESTONE` action, existing checkpoint, and first compaction.
The resulting `HANDOFF_REQUIRED` prevents this session from receiving assurance
or qualification. There is no push, merge, or exact-main acceptance for this
repair. A genuine successor must preserve the original base and reconcile
the predecessor's recovery and nonqualified request before advancing.

Independent review also identified a missing successor interface: normal
initialization takes current HEAD, while unresolved prior requests block
admission. Request-bound administrative assurance must not bypass the recovered
session's guardian. A future explicit transition must preserve predecessor
records and the original comparison base. This limitation remains open;
the current recovery gate is not described as a complete automatic restart flow.

## Local checkpoint verification

The exact nine-module command and source hashes in the
[checkpoint evidence](evidence/2026-10-17-protocol-completion/checkpoint-verification.json)
record 194 passing tests, no failures and no skips. The final audit collection
completed successfully. Independent Astra review reproduced the reported
admission, compaction, assurance and delivery failures, then verified their
corrections through bounded Git and CLI probes. This is checkpoint review,
not final publication assurance.

The broader `tests/audit` run with external tests deselected exited nonzero
and listed 46 failing cases. Reported errors include absent local embedding,
tokenizer and server dependencies. Its exact failing nodes and log hash are
preserved; no baseline comparison or full-suite success is claimed. Delivery
integration fixtures exercise actual Git, subprocesses and worktree removal,
but stub network calls and ten canonical gate implementations. Real repository
continuity gates are checked separately before the local checkpoint commit.

The builder's first reconstructed delivery TDD command named the wrong test
module. The root excluded that cycle and recorded the separate witnessed
review regression against `tests/audit/test_verify_merge.py`; original raw
logs remain unchanged. Additional review regressions are not retroactively
described as test-first when their initial failure was independently probed
rather than captured by the later pytest command.

The [delivery plan](../delivery/current.json) names the stable operation and its
next action. The [workflow](../SOP_SEAM_CODEX_WORKFLOW.md) governs admission,
independent assurance, exact-head CI, qualification and protected merge.
Run `python -m tools.agents.delivery_status` after resuming. A missing or invalid
completion record is not success; restore validated evidence or reproduce
verification. Only verified completion permits the plan's conditional next
action. This route does not require a new status-only PR after every merge.

The local record cannot prove an unreported client event or authenticate a
human/model reviewer by itself. Root delegation, independent review and trusted
client/hook configuration remain explicit trust boundaries. Runtime features,
production publication, paid execution, rendered website acceptance and the
existing advisory runner issue #293 are outside this repair's completion claim.

## Evidence manifest

Evidence rows below are exact files read during the completion audit; the old
records remain historical rather than being overwritten by new observations.

| Evidence | SHA-256 |
|---|---|
| [Live completion readback](evidence/2026-10-17-protocol-completion/completion-live-readback.json) (`evidence/2026-10-17-protocol-completion/completion-live-readback.json`) | `c973d5f614c545b4e53559ba977235e349aafbb7dd9ee864508125e90d2b5e69` |
| [Public artifact bytes](evidence/2026-10-17-protocol-completion/artifact-readback.json) (`evidence/2026-10-17-protocol-completion/artifact-readback.json`) | `96fe6c93bb9436672743e8d20d5afc4fcab9218a1eea99473cd43b2303f1d09b` |
| [Historical installed acceptance](evidence/2026-10-17-protocol-completion/publisher-installed-evidence.json) (`evidence/2026-10-17-protocol-completion/publisher-installed-evidence.json`) | `7e61aa478147d71f6192e5df0ffd7b690aad4082d08ebbe7c0ac67d9ef70765a` |
| [Current preservation readback](evidence/2026-10-17-protocol-completion/preservation-readback.json) (`evidence/2026-10-17-protocol-completion/preservation-readback.json`) | `8397057e53853246993af7a0e0eef431feb343e05c2e3285695b0b2353a55a29` |
| [PR #313 exact-main proof](evidence/2026-10-17-protocol-completion/pr313-merge-verification.json) (`evidence/2026-10-17-protocol-completion/pr313-merge-verification.json`) | `8ea8c10cdf4c520f9b7969206a3d256f1ec51851bcc712574d76c044dd92248f` |
| [PR #313 canonical qualification](evidence/2026-10-17-protocol-completion/pr313-qualification.json) (`evidence/2026-10-17-protocol-completion/pr313-qualification.json`) | `a7314db05d62b100bc8f999356e4902b05d8a76bb9581dfd0f2f1837b5f6a5d2` |
| [Local checkpoint verification](evidence/2026-10-17-protocol-completion/checkpoint-verification.json) (`evidence/2026-10-17-protocol-completion/checkpoint-verification.json`) | `682b22d3ef66431de0a1c24e9aa21701957ebcdff7e7826a38816f2c156b32df` |
