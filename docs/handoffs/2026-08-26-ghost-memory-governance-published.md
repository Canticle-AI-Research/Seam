---
handoff_id: 2026-08-26-ghost-memory-governance-published
supersedes: 2026-08-25-ghost-memory-governance-locally-qualified
handoff_status: superseded
history: HISTORY#611
---

# Ghost deliberate-memory governance published

## Protected-main result

PR #233 merged exact source `f8a14864ff430cf9dcec230967e30b53f0360aa9`
as protected `main@0b0724407f05e07d98001ac1f4fcb401ba7fe2fe`.
Runs `32931607726` and `32931607783` passed all seven hosted jobs:
`repo-hygiene`, `chroma-real-smoke`, `locomo-quickstart-bil2`,
`pgvector-integration`, `package-smoke`, `registry-plan`, and
`test-and-benchmark`.

Protected source now records explicit admit/reject/review decisions, persists
only admitted turns, separates principal/workspace/project/namespace/scope/
thread boundaries, exposes current and historical lifecycle views, and
corrects memory additively through replacement, provenance-bearing
`supersedes`, and canonical soft deletion. Historical IDs remain audit-only and
cannot become mutation handles.

## Preserve and next

The dirty stale primary checkout, Cline's duplicate local `HISTORY#605`, TUI
work, licensing worktree, ignored corpora, skills, and other operator files
remain untouched. The cross-index archive roll in PR #233 was verified as a
strict one-line superset with zero prior lines lost.

This closes SEAM source publication for Ghost issue 6. It does not deploy a
compatible service, release a package, alter Track S stage, or prove memory
quality. Ghost must now merge its independently authored client/policy half
against this exact protected contract; later hosted operations and specialist
work retain their separate roadmap gates.
