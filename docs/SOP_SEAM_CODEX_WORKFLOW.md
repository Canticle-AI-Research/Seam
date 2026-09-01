# SOP — Continuing SEAM Work with Codex

Issued: 2026-08-31
Authority: `AGENTS.md` and `REPO_LEDGER.md`
Agent mechanics: [Codex root-supplied agent orchestration](SOP_AGENT_ORCHESTRATION.md)

## Purpose

Use this runbook when the operator asks Codex to continue, resume, repair, or
complete a SEAM initiative. It is the ordered operator workflow from live-state
reconciliation through protected merge and durable resume.

This page owns the sequence. The orchestration SOP owns role boundaries,
context packets, session-state evidence, closeout requests and receipts, and
context-guardian mechanics. `AGENTS.md` owns repository startup, continuity,
security, and protected-branch policy. Follow those authorities at the phases
that point to them; do not reconstruct their schemas or command surfaces here.

## 1. Reconcile the live initiative

**Owner: Codex root**

Before authorizing writes, reconcile protected `origin/main`, the current
branch and remote PR head, every worktree, dirty and untracked paths, stashes,
the registered current handoff, and pending SessionEnd closeout requests. Use
the repository CLI and GitHub CLI; treat branch-local, merged, released,
deployed, and benchmark-qualified as different states.

Preserve unrelated work as named exclusions. Dispatch every pending closeout
request to the release wave described in the orchestration SOP. A verdict
other than `QUALIFIED` remains an open condition: make its concrete repair or
authority blocker the active work before beginning an unrelated initiative.

Treat tracked hooks and custom agent profiles as configuration candidates until
a fresh trusted Codex client has discovered and smoke-tested them.

**Complete when:** the root has recorded the exact protected-main SHA, current
HEAD and upstream/PR head, dirty-path ownership, worktree and stash state,
current handoff, and every pending request's validated disposition. Any
non-qualified request has one named next action and owner.

## 2. Frame the operator contract

**Owner: Codex root; operator owns authority decisions**

Turn the request into one objective, observable acceptance criteria, non-goals,
dependencies, owned paths, and stop conditions. Load the governing SEAM and
MIRL contracts when product behavior is involved. For a runtime change, name
the pre-agreed **public seam** where the vertical slice will be tested: an
operator-visible API, CLI, persistence, or runtime boundary rather than only a
private helper.

Record authority separately for pushes and protected merge. Paid provider
calls, releases, deployments, destructive cleanup, and scope expansion require
an explicit operator decision at the point of action; an implementation request
does not imply any of them.

For repo-changing work, initialize or update the root session-state record as
specified by the orchestration SOP.

**Complete when:** the root plan names the objective, acceptance criteria,
public seam when required, ownership map, tests, constraints, authority gates,
and first reversible action, and the bounded session-state record represents
that plan.

## 3. Resolve only blocking context

**Owner: Context orchestrator; Codex root integrates**

Run a context wave only for a bounded contract, dependency, or unknown that
blocks the framed slice. The root supplies relevant extracts and exact source
pointers. Follow the orchestration SOP for packet and return contracts. A
product decision or missing operator choice returns to the root and operator.

**Complete when:** every blocking unknown is either resolved with exact source
references or represented as one explicit `MISSING_CONTEXT` or operator
decision; no child has widened repository scope.

## 4. Establish the protected delivery lane

**Owner: Codex root**

Resume the intended PR branch only after confirming its remote head and base
drift. For new work, update from protected main and use a working branch and,
when isolation is needed, a dedicated worktree. Keep one writable owner per
path and wave. Root retains integration, staging, continuity, and PR artifacts.

**Complete when:** the branch/worktree lineage is anchored to a recorded base
SHA, the PR relationship is known, writable paths have one owner each, and all
unrelated dirty paths remain excluded.

## 5. Deliver one vertical red-green slice

**Owner: Delivery orchestrator; specialists own only packet-assigned paths**

Send one approved slice through the delivery wave defined by the orchestration
SOP. For runtime work, first make a test at the pre-agreed public seam fail for
the intended reason, implement the smallest coherent vertical behavior, then
make that same slice green. Record the witnessed red-green evidence in session
state through the tracked helper; a green-only run is `TDD_UNPROVEN`.

Keep additional specialists independent and path-disjoint. Stop at product,
security, authority, or scope decisions rather than absorbing them into the
implementation.

**Complete when:** the public behavior has a witnessed red then green cycle,
the session-state evidence covers every changed runtime path, focused tests are
green, and the return packet accounts for every owned-path change and residual
risk. For documentation-only work, completion requires the named lint or
verification slice and a recorded rationale that TDD does not apply.

## 6. Integrate the slice

**Owner: Codex root**

Inspect each returned diff and evidence packet, reject out-of-scope changes,
and integrate only supported facts. Reconcile concurrent edits before changing
shared files. Stage explicit paths only after the integrated tree is coherent.
Evaluate the context guardian at this milestone and follow its compaction or
handoff action before the context budget becomes unsafe.

**Complete when:** the integrated diff is attributable to the objective,
ownership collisions are resolved, focused verification still passes, the
session-state plan matches the tree, and guardian state names the next exact
action.

## 7. Obtain independent assurance

**Owner: Assurance orchestrator; Codex root routes findings**

Give assurance the integrated diff, governing-contract digest, claimed
acceptance evidence, tests, and exclusions using the orchestration SOP. The
assurance wave is read-only and cannot repair its own findings.

Route every actionable finding to a **new delivery wave**, then reintegrate and
run independent assurance again on the changed exact state. Do not convert a
review report into qualification by assertion.

**Complete when:** independent assurance reports no unresolved blocking
finding on the current diff, and every non-blocking observation has an explicit
disposition and owner.

## 8. Build the canonical closeout state

**Owner: Codex root**

Update the temporal chain, current status, ledger, handoff, streams, and
snapshot only where `AGENTS.md` requires them for this change. Run the canonical
continuity gates exactly as written there. Run the change's required tests and
the verification matrix appropriate to its surface. Scan every candidate path,
including untracked candidates, for secrets and private provider or session
links before staging or committing.

Any repair changes the reviewed state: return it through delivery,
integration, assurance, and this closeout phase.

**Complete when:** required tests and every canonical continuity gate exit
zero, the current handoff and snapshot identify the exact candidate state, the
secret scan is clean, and no candidate or excluded dirty path is unaccounted
for.

## 9. Publish one exact PR candidate

**Owner: Codex root; operator owns push/merge authority**

Stage explicit paths, commit the reviewed candidate, and push only with the
recorded authority. Open or update the protected-branch PR with scope,
verification, risks, and exclusions. Record one candidate SHA and require the
repository's current required CI checks on that exact head.

If the branch changes, a check is rerun on another SHA, or CI exposes a defect,
return to a new delivery wave and repeat assurance and closeout on the successor
state.

**Complete when:** local HEAD, remote branch head, PR head, reviewed candidate,
and verification evidence name the same SHA, and every required exact-head CI
check is successful.

## 10. Store exact-state release qualification

**Owner: Release orchestrator; Codex root validates and stores**

Create the exact-state closeout request and run the read-only release wave as
defined by the orchestration SOP. Supply the candidate SHA and diff identity,
recorded TDD evidence, canonical gates, plan alignment, independent assurance,
secret-scan result, and exact-head required CI.

The release orchestrator reports only. It cannot repair, commit, push, merge,
call a paid provider, release, or deploy. The root admits its result only
through the tracked validator and atomic receipt store. A repair follows a new
delivery wave and produces a new exact-state request; prior verdicts remain
immutable evidence.

**Complete when:** a validated stored `QUALIFIED` receipt matches the current
candidate exactly, explicitly supersedes applicable older requests, and the
validated pending-request queue is empty. No merge proceeds on a merely clean
review or an unstored receipt. Because receipt admission is a point-in-time
boundary rather than an editor lock, the root must recheck the candidate
fingerprint immediately before merge; any later mutation returns to a new
exact-state request.

## 11. Merge through protected main

**Owner: Codex root; operator authorizes merge**

Recheck that the PR head has not moved and that phases 7–10 still describe that
head. Merge through the protected PR path. Keep release and deployment as
separate operator-authority gates after merge; a merged implementation is not
evidence that either occurred.

**Complete when:** GitHub records the PR as merged, protected `origin/main`
contains the qualified candidate, and the merge commit or resulting main SHA
is recorded without promoting it to released, deployed, or benchmark-qualified.

## 12. Verify exact main and leave a durable resume

**Owner: Codex root; operator owns destructive cleanup**

Fetch protected main after merge and verify the resulting exact main SHA,
candidate ancestry, PR state, and applicable post-merge checks. Reconcile the
closeout queue again. Update the resume pointer to the next unresolved
initiative or to an explicit clean-stop state.

Reconcile the working branch, worktree, and stashes. Remove a clean merged
branch or worktree only when that cleanup is authorized and recoverability is
clear; otherwise record exactly why it is retained and who owns cleanup. Never
discard unrelated dirty work as cleanup.

**Complete when:** exact protected-main state is verified and recorded, no
closeout request lacks a disposition, the handoff/resume pointer names the
first next action or clean stop, and every branch, worktree, stash, and dirty
path is either safely closed or explicitly retained with an owner.
