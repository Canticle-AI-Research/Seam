---
handoff_id: 2026-08-25-ghost-public-agent-api-locally-qualified
supersedes: 2026-08-25-track-s-s8-slice-published
handoff_status: current
history: HISTORY#608
---

# Ghost public agent-turn API locally qualified

## Boundary

`feat/ghost-api-parity` starts exactly at protected
`origin/main@bc6b927e6fbc3cbef7db505e1af0929a6cf839f2` and adds four opaque
public routes for Ghost: begin, actions, complete, and fail. This is an
additive server surface over the existing private runtime, not a second memory
engine, a public runtime distribution, a Track S stage change, or a hosted
deployment claim.

## What the service now enforces

- reasoned retrieval opens before Ghost acts and returns only bounded public
  text plus opaque handles;
- action attempts become decisions and verifications while the reasoning graph
  retains only tool-result length/hash;
- accepted completion derives selected evidence and passed checks server-side,
  compiles through the canonical runtime, and returns a deterministic receipt;
- rejected failure accepts only a bounded error class and performs no ingest;
- terminal replay is idempotent, post-terminal actions conflict, and one turn
  carries at most 64 checks across all batches;
- principal, namespace, scope, and optional session partitioning make foreign
  handles content-free 404; and
- complete/action/fail transitions share the runtime write/projection lock.

## Review and verification

The adjacent public API, principal authorization/rate-limit, reasoning graph,
and bind-safety slice passed 165 tests with no skips. Changed-path Ruff and
`git diff --check` passed. CodeRabbit reviewed all tracked and untracked files
against `main` and returned four findings: durable replay count and cumulative
verification bound were repaired; the request bound was documented because
Ghost already caps it below the server maximum; explicit session-field storage
was rejected because `parse_memory_query` already incorporates session ID into
the checked internal namespace, now pinned by a cross-session 404 test.

No provider, paid benchmark, production service, package release, or deployment
was invoked.

## Next

Commit the exact locally qualified slice, push it, open a focused PR, require
the protected `repo-hygiene`, `chroma-real-smoke`, and
`locomo-quickstart-bil2` checks plus advisory exact-head review, repair any
valid finding, merge through protected main, and remove this worktree. Ghost's
public client PR remains dependent on this server contract and must not claim a
compatible deployed endpoint merely because both source candidates exist.
