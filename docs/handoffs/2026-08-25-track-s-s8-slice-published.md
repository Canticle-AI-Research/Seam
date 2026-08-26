---
handoff_id: 2026-08-25-track-s-s8-slice-published
supersedes: 2026-08-25-track-s-s8-retrieval-coherence-review-repaired
handoff_status: superseded
history: HISTORY#607
---

# Track S S8 mechanism slice published — remaining S8 work

## Protected publication state

- Published through merged PR #228 at merge commit
  `bb156e3335ea17aebd6226774512ac681c00553f`.
- Exact signed source head `16f1ee581637c7297c9aa766b5f58af9d39a5771` matched
  the PR head and passed `repo-hygiene`, `chroma-real-smoke`,
  `locomo-quickstart-bil2`, `pgvector-integration`, `package-smoke`,
  `registry-plan`, and `test-and-benchmark` (9m33s) before merge.
- Ancestry verified: the signed source commit is an ancestor of protected main.
  The merged branch is deleted on the remote and locally.

## What is now protected-main mechanism

Fail-closed fusion leg names over the exact set the engine emits, one shared
definition between fusion and the reasoning recorder, persisted
weighted-policy replay (`reasoning_retrieval.leg_weights_json` plus its
additive migration) with all-one bitwise identical to
`reciprocal-rank-fusion/2`, candidate ID/order parity with direct `retrieve()`
across `search_ir`, REST, the SDK engine path, MCP, and the TUI read path,
exactly one tenant-scoped retrieval event per successful retrieval with
telemetry failure proven answer-inert, an explicit `refresh_retrieval_flags()`
contract for the process-lifetime flag cache, and three graph-traversal
statements bounded under SQLite's legacy 999-variable floor.

**No default behavior changed.** Retrieval telemetry ships default-off behind
`SEAM_RETRIEVAL_EVENTS`, and weighted fusion stays inert until an operator sets
a weight. This is mechanism publication only: no graph, scorer, quality, or
benchmark claim is attached. S9 remains the promotion gate.

## Remaining S8 work

1. **Legacy-versus-RRF retirement — operator decision, not an agent call.**
   `search_ir` still defaults to `legacy-weighted/1`. It feeds the LoCoMo
   adapter and the mem0 harness, so switching the default to
   `reciprocal-rank-fusion/2` changes every recorded arm and invalidates the
   matched `0.776048` comparison. It needs an operator-approved paid re-run to
   re-qualify. Do not flip it inside a refactor.
2. **Boundary-only SQL gate** — still undecided.

## Open repository items (not Track S)

- One high-severity Dependabot alert: `nanoid` in
  `archive/webui-vite-source/package-lock.json`. Archived source, not shipped
  code.
- Older workstream PRs #207, #213, and #221 remain open and are not qualified
  by this publication.
- Stale linked worktrees whose branches are merged and remote-deleted
  (`Seam-wiki`, `Seam-tui-reload-fix`) plus a detached-HEAD
  `Seam-github-operations`. They belong to other tracks; removal is an operator
  decision.

## Preserve these boundaries

The dirty primary checkout, unrelated worktrees and branches, sibling
repositories, ignored artifacts, and operator assets remain outside this
workstream and untouched.
