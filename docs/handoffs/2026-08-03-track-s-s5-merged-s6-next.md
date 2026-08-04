---
handoff_id: 2026-08-03-track-s-s5-merged-s6-next
supersedes: 2026-08-03-track-s-s5-locally-qualified
handoff_status: current
history: HISTORY#533
---

# Track S S5 merged; S6 is the next stage

**Date:** 2026-08-03

**Base:** protected `main@19b3a76`

**Publication:** S0-S5 merged; zero PRs open

## Current state

S5 is published through PR #199. All eight required and advisory checks passed
on the exact head — `repo-hygiene`, `chroma-real-smoke`,
`locomo-quickstart-bil2`, `package-smoke`, `pgvector-integration`,
`registry-plan`, `test-and-benchmark`, and CodeRabbit, which left zero review
comments — and the branch was squash-merged and deleted. The predecessor
handoff's "exact next move" (open the S5 PR and require all eight checks) is
complete and is retired here so no later session re-runs it.

Retrieval now answers every request from one committed snapshot, derived vector
indexing is process-durable, neither vector search path performs schema work,
and divergence is detectable and repairable on all three backends.

## Why S6 and nothing else

Reading the campaign's declared dependencies: S6 needs S2 and S5, both merged.
S7 needs S3, S4, and S6. S8 needs S1, S5, S6, and S7. S9 needs S7 and S8. S10
needs all of S0-S9. S6 is therefore the single node gating the rest.

## What S6 must decide first

**`/v1` has no tenancy binding.** `public_api.remember/recall/context` take no
caller identity; `namespace` and `session_id` come off the request body, so one
bearer token reads and writes every namespace. That is correct for BUSL
self-host and is the multi-tenant boundary for the paid hosted API.

**S6 must state explicitly whether tenancy terminates in a proxy ahead of `/v1`
or in-process.** That decision is currently written down nowhere, and every
later clause depends on it. `/v1` also has zero HTTP-level tests: two references
in the whole test tree, and no test exercises `POST /v1/memories`,
`/v1/memories/recall`, or `/v1/context`.

`SEAM_API_TOKEN` remains optional for trusted-loopback development; automatic
first-launch token provisioning is a separate authentication/UX policy decision
that S6 also has to settle or explicitly defer.

## Running the full suite without skips

The live pgvector lane skips unless `PGVECTOR_TEST_DSN` is set. The
`seam-pgvector` container already exposes it locally on port 55432:

```
export PGVECTOR_TEST_DSN="$SEAM_PGVECTOR_DSN"
.venv/bin/python -m pytest tests/
```

With it: **2028 passed, 0 skipped, 2 xfailed**. Without it, 4 external cases
skip. The 2 xfails are the pre-existing `compile_nl` compiler-rewrite targets
(`tests/fidelity/test_compile_fidelity.py`), not S5 regressions.

## Honest boundaries

- No paid provider call, competitive benchmark, retrieval-score claim, artifact
  publish, deploy, or release ran. Nothing here claims SEAM has beaten Mem0,
  Zep, or Cognee, reached 100% canonical memory, or eliminated hallucinations.
- Carried forward, none of them Track S: `dashboard.py` (3,160 lines, no
  dedicated test file), benchmark seal/BIL integrity, and MIRL losslessness
  round-tripping remain unaudited across two whole-repository audits.
- `test-and-benchmark` has now been green on six consecutive PRs, exceeding
  S10's stated condition for promoting it to a required check. That is a
  branch-protection ruleset change, not a code change, and is still unmade.
- Unbounded SQL variable expansion in `knowledge_graph.py` (`:1106`, `:1143`,
  `:1161`, `_graph_episode_rows` `:2074-2090`) remains open: latent on SQLite
  >= 3.32, breaks on the 999-variable default.
- Several older worktrees remain present; AGENTS.md requires finishing them, and
  removal is left for explicit operator confirmation.

## Exact next move

Begin S6 on `main@19b3a76`. Write down the tenancy termination decision before
writing code, and give `/v1` its first HTTP-level tests as part of the same
slice.
