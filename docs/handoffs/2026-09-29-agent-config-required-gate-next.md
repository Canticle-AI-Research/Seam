---
handoff_id: 2026-09-29-agent-config-required-gate-next
supersedes: 2026-09-14-claude-code-benchmark-next
handoff_status: superseded
history: HISTORY#650
---

# Agent-configuration required gate continuation

## Start here

The four unresolved PR #258 agent-configuration findings are implemented on
draft [PR #274](https://github.com/Canticle-AI-Research/Seam/pull/274), branch
`fix/agent-config-required-gate-20260929`. The PR is intentionally stacked on
draft PR #273 through base branch `fix/gate-parity-invariant`; do not merge or
mark either PR ready from this handoff. After #273 lands, reconcile #274 onto
the resulting protected-main head, retarget it, and rerun exact-head review,
CI, content scans, continuity, and closeout before any merge decision.

The independently qualified implementation state is
`a0f50a792949a56525a0e9bd425d56a02f86a8af`, based exactly on
`efb30b73f97011e887a29e94c40e2167cb627e73`. The later commit containing this
tracked handoff and HISTORY event is continuity bookkeeping after that
qualification; inspect the live draft PR before making claims about its final
head or checks.

## What changed

`tools.git.verify_agent_config` now inspects every Git index path even when a
committed forbidden path has no staged diff. It rejects case-insensitive
`.claude`, `.opencode`, and `.agents` directory components and root OpenCode
configuration names, except for the literal nine-path `OPENCODE_COMPAT_PATHS`
set. Each compatibility entry is optional project documentation and is
accepted only as a regular, nonexecutable, stage-zero index entry; arbitrary,
renamed, nested, case-variant, symlink, and unresolved entries fail closed.

The root `.claude/CLAUDE.md` memory pin retains its exact-object, staged-object
ID, mode, size, duplicate-key, no-symlink, and staged-versus-working-copy
guarantees. Required `repo-hygiene` now invokes the validator unconditionally.
The parity audit covers required CI, Claude preflight, the canonical hook, and
closeout while preserving the hook's early bare
`verify_agent_config --staged || exit 1` abort. The policy documents now state
the narrow root-pin and retained OpenCode-document exceptions without turning
them into general agent-local storage allowances.

No production wrapper interface changed. Runner isolation, general content
safety, packages, release workflows, workspace cleanup, SkillDB, product
runtime, benchmarks, dependencies, and PRs #269/#270 remain outside this
slice.

## Verification evidence

The exact three-file regression command first witnessed 27 failures and 74
passes against the unchanged implementation, then 101 passes after the
implementation. Regressions use real temporary Git repositories and copied
gate fixtures. They cover committed forbidden paths with empty staged diffs,
all nine exact compatibility paths and negative variants, every local and
required-CI invocation, advisory-only placement, missing hook `--staged`,
weakened aborts, late placement, and conditional or suppressed CI execution.

The required five-file focused collection passed 158 tests. Both validator
modes, Ruff, and whitespace checks passed. With the documented Compose
pgvector service healthy and the existing nonsecret `HF_HUB_CACHE` preserved,
the full approved collection completed with 3,732 passed, 2 expected xfailed,
0 skipped, and 0 failed in 614.15 seconds. The two expected failures are the
existing compiler entity-extraction cases. A prior connection-refused run
without the service is explicitly invalid evidence, not a pass.

All six continuity gates and both working-tree and exact-range secret/session
scans passed before delivery. The draft PR's required `repo-hygiene`,
`chroma-real-smoke`, and `locomo-quickstart-bil2` checks passed on the
qualified implementation head; package smoke, registry plan, and pgvector
integration also passed. Recheck the live PR for the handoff commit and the
advisory matrix before relying on remote state.

## Closeout chain

The first exact-state request,
`01a0ecb1-cde0-7b23-887b-ed4a420e27f8-2c698ba8182a816b`, remains preserved
with a validated `NOT_QUALIFIED` receipt. Its TDD references were accidentally
semicolon-joined into literal list elements, so coverage correctly reported
`TDD_UNPROVEN` even though the underlying RED and GREEN runs were genuine.

The corrected request,
`01a0ecb1-cde0-7b23-887b-ed4a420e27f8-a8e5bb0a950c7a3b`, uses repeated CLI
fields for each exact test and implementation path. Independent review
recomputed `TDD_PROVEN`, reran 101 focused tests plus all required continuity
checks, confirmed exact head and diff-fingerprint stability, and returned
`QUALIFIED`. Its admitted receipt explicitly supersedes the failed request,
leaving this worktree's closeout queue empty.

Unrelated orchestration states remain separate. In particular, the reports
worktree's prior `NOT_QUALIFIED`/`TDD_UNPROVEN` and older `INDETERMINATE`
evidence was not altered or treated as globally resolved. Unrelated dirty
linked worktrees were preserved; the private branch push used the hook's
documented one-push dirty-worktree continuation while retaining signature,
secret-scan, and public-freeze protections.

## Next action

Keep PR #274 draft and focused. Review any new comments against the exact live
head. Once PR #273 has a protected-main outcome, update #274's base without
folding in unrelated work, rerun the full local and remote qualification, and
obtain a fresh exact-state receipt if the diff fingerprint changes. Merge,
publication, ruleset changes, and marking the PR ready remain unauthorized.
