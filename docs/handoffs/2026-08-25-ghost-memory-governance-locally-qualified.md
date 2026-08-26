---
handoff_id: 2026-08-25-ghost-memory-governance-locally-qualified
supersedes: 2026-08-25-ghost-public-agent-api-published
handoff_status: superseded
history: HISTORY#610
---

# Ghost deliberate-memory governance locally qualified

## Candidate boundary

The isolated `feat/public-memory-governance` worktree is based on current
`origin/main@cd98439`. It extends the opaque Ghost API with explicit
admit/reject/review decisions, principal/workspace/project/thread isolation,
current/history views with visible lifecycle status, and principal-only
additive correction through a replacement, `supersedes` relation, and
canonical soft deletion.

History retrieval is audit-only: deleted records can be rendered with their
status, but the server does not register their opaque IDs as mutation handles.
Legacy callers that omit admission retain auto-admit compatibility. No private
MIRL shape or canonical identifier enters a response.

## Local verification

- Focused public memory and agent-turn HTTP suites pass.
- The complete provider-free suite passes with `-m "not external"`; one linked-
  worktree console-import test is deselected because it deliberately clears
  `PYTHONPATH` and resolves the shared primary checkout instead of this
  candidate.
- The first unrestricted suite attempt correctly failed strict no-skip because
  local `PGVECTOR_TEST_DSN` was absent; the supported non-external lane was then
  rerun without suppression and passed.
- Repository-wide Ruff, `git diff --check`, and an isolated wheel build pass.
- CodeRabbit's SEAM review was unavailable after the free CLI allowance was
  exhausted. A bounded manual review caught and repaired the historical-handle
  registration defect, with a regression test.

## Preserve and next

The stale dirty primary checkout at `feat/tui-canticle-rework` contains Cline's
duplicate local `HISTORY#605`, stream roll, TUI work, and other operator files.
It is nine commits behind `origin/main` and was not edited, cleaned, staged, or
renumbered here. This candidate owns canonical `HISTORY#610` only.

Next: commit and push the isolated candidate, obtain exact-head hosted checks,
merge through protected `main`, then write the successor publication handoff.
This is mechanism qualification only: it changes no Track S stage and makes no
memory-quality, package-release, or hosted-deployment claim.
