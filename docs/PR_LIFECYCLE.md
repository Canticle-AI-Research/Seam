# Pull request completion and backlog policy

Keep one active PR per repository, including drafts and stacked branches. Finish
its reviewed slice through required CI, protected merge and verification of the
resulting main before opening another implementation PR. A push or a closed PR
does not establish a merge.

When work is deferred or superseded, preserve its exact commit and branch or
archive ref, link a recovery issue with remaining acceptance, and close the PR.
Closing the PR does not complete its product requirements. The original eight
PRs reconciled on October 16 have their exact dispositions and preserved refs in
[the audit receipt](audits/evidence/2026-10-16-pr-closeout/original-pr-dispositions.json).
Private website proposal contents remain in the private website repository.

## Check the current backlog

Run from a qualified SEAM checkout with its owning Python interpreter and an
authenticated GitHub CLI:

```bash
python -m tools.ci.pr_lifecycle --repo Canticle-AI-Research/Seam --json
python -m tools.ci.pr_lifecycle --repo BlackhatShiftey/Cantlicle --json
```

Each invocation independently resolves main and reads its lifecycle policy.
The initial policy permits one ordinary PR and no blocker exceptions. Source
`repo-hygiene` and the canonical pre-push hook run the same source-repository
gate. The scheduled repository-maintenance workflow checks it again. Source CI
does not claim website enforcement or require credentials for that private
repository; the explicit website CLI invocation is a separate local check.

A genuine blocker can retain an active PR only through an exception admitted on
protected main in `.github/pr-lifecycle-policy.json`. It binds the repository,
PR number, exact head SHA, open blocker issue, owner, concrete condition and UTC
expiry. Labels, PR prose and a policy edited only on the candidate cannot grant
an exception. An active exception fails on expiry, head movement or a closed
blocker. Invalid policy, unavailable authentication or incomplete source access
also fails the check. Prefer preserving and closing deferred work over leaving
it indefinitely active.

To admit an exception without exceeding the existing cap, first preserve and
close the blocked PR. Admit its exact PR/head exception in the sole active policy
PR, finish that PR through verified protected main, then reopen the preserved
blocked PR. Structurally valid entries for PRs absent from the complete open
inventory are dormant: they grant no exemption and do not block ordinary work,
even after expiry. Reopening activates all exact-head, open-blocker and expiry
checks. Closing an exceptional PR makes its entry dormant; remove obsolete
entries in a later policy change. Missing inventory never implies dormancy.

## Install worktree-aware local hooks

```bash
bash tools/git-hooks/install.sh
```

The installer uses the common Git directory and permanent dispatchers that
resolve the invoking checkout. Installation from a linked worktree survives
removal of that worktree. Existing unknown hooks require explicit replacement;
replaced hooks are backed up. A configured `core.hooksPath` requires a separate
explicit integration. The dispatcher rejects a missing or older canonical
hook protocol, so a stale checkout cannot silently use weaker enforcement.
Installation does not update or authorize that checkout's source.

## Complete and verify a merge

Follow [the Codex workflow](SOP_SEAM_CODEX_WORKFLOW.md), including independent
assurance, canonical continuity, the candidate secret scan, exact-head required
CI, and an independently qualified receipt admitted by `closeout_queue`.
Recheck live lifecycle and candidate identity immediately before protected
merge. This verifier initially supports ordinary merge commits; use the
protected merge-commit path. Unsupported squash/rebase mappings fail closed.

Fetch main and prepare a clean, isolated checkout at the exact resulting merge
commit. Supply actual full SHAs and the original stored request and receipt:

```bash
python -m tools.ci.verify_merge \
  --repo Canticle-AI-Research/Seam --pr PR_NUMBER \
  --expected-candidate CANDIDATE_SHA --expected-main MERGE_SHA \
  --worktree /absolute/path/to/isolated-main \
  --request /absolute/path/to/request.json \
  --receipt /absolute/path/to/stored-receipt.json \
  --evidence /absolute/path/to/new-merge-evidence.json
```

The command independently checks GitHub merged state, source identity,
required check results, stored qualification, local candidate ancestry and
actual canonical gates on exact main. For each ruleset-bound check it selects
the latest eligible run by aware start time; a later pending, failed, or
post-qualification run cannot fall back to an older success. Before local Git
inspection or canonical gates, it requires
`check start <= check completion <= qualification completion <= PR merge` and
rejects missing, malformed, timezone-naive, or reversed times. It preserves the
source timestamp strings in successful evidence and writes that new evidence
file only after every proof succeeds. Preserve a failed attempt as a failure
and repair any protocol defect through a new reviewed delivery wave before
claiming completion. A stored receipt or empty pending queue alone does not
execute these checks.

Record the verified merge receipt in the tracker or recovery issue, reconcile
pending closeouts, and finish the session's worktree and branch. Preserve
unrelated dirty work and existing source recovery refs. Release, installation,
publication and product acceptance retain their own evidence and authority.
