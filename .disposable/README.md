# .disposable — the ONLY deletable location in SEAM

**Nothing in this repository is ever deleted except from inside this
folder, and deletion from this folder is performed by the OPERATOR ONLY.**

An artifact becomes "disposable" ONLY by passing through this process:

1. **Proposal.** An agent that believes an artifact is deletable proposes
   moving it here. The agent performs no deletion and no move on its own
   authority — the proposal is a message to the operator, nothing more.
2. **Operator decision.** The operator decides, for the specific named
   artifact, whether it enters this folder. Git-ignored status, cache
   labels, "regenerable" claims, and disk pressure grant NO deletion
   authority to any agent.
3. **Recorded move.** When the operator approves, the artifact is MOVED
   (not deleted) into `.disposable/<date>-<name>/` and a HISTORY entry
   records: what was moved, its path of origin, why, and the operator's
   approval. The entry is append-only like every other entry.
4. **Operator-only purge.** Anything inside this folder may be deleted by
   the operator at any time. Agents never purge this folder, even when
   asked to "clean up", unless the operator names the exact path in the
   same instruction.

## Why this folder exists

On 2026-08-25 an agent deleted `test_seam/ab_A`, `ab_B`, `ab_B2`, `ab_C`,
and `ab_D` (~3.4 GB of A/B evaluation arms built from the LoCoMo pristine
corpus) to free disk space during a disk-full event, without operator
authorization, wrongly treating git-ignored test artifacts as disposable.
That deletion destroyed run evidence and violated the repository's own
no-deletion protocol. HISTORY records the full account. This folder and
its process exist so that "disposable" is a recorded state with an
operator decision behind it — never an agent's inference.

## Hard rules

- **Before deleting anything in any repository, an agent MUST invoke
  Ask_user and receive explicit operator approval naming the exact path.**
  No approval, no deletion — under any conditions.
- `HISTORY.md` is append-only. No entry is ever edited or removed.
- No agent deletes, truncates, moves out of the tree, or rewrites any
  file, directory, branch, tag, snapshot, or artifact anywhere in this
  repository — ever — for any reason, including avoiding truncation or
  disk-full conditions. The correct response to disk pressure is: STOP
  WRITING and tell the operator.
- If a write fails due to disk space, the failure is reported. It is
  never "solved" by deleting repo content.
