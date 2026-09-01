---
handoff_id: 2026-09-01-track-s-d2-locally-qualified-d3-next
supersedes: 2026-09-01-track-s-d1-locally-qualified-d2-next
handoff_status: current
history: HISTORY#622
---

# Track S D2 locally qualified; D3 next after protected merge

## Exact state

Protected `main@64e4434` contains the complete D1 Recovery Boundary through
merged PRs #237 and #239. The isolated branch `feat/d2-atomic-ingest`, based on
that main commit, closes the local D2 Atomic Ingest implementation and evidence
gap.

`SeamRuntime.ingest_text` and `ingest_conversation_turn` now return one
compatible `IngestOutcome`. Normalized MIRL and its graph projection,
same-source supersession, the active document row, and durable vector
reconciliation intents commit in one SQLite transaction. Supersession is
bounded by namespace, scope, and source reference. Preview ingest is
mutation-free.

External record and node vectors remain derived. A pre-commit fault restores
the complete previous state. A post-commit projection fault leaves one
canonical pending outcome; replay indexes the winning generation, deletes
superseded records, rebuilds node vectors, acknowledges every intent associated
with that ingest, and only then marks the document indexed. Historical graph
episodes remain available, obsolete facts are absent from current retrieval,
and graph rebuild preserves shared entities still referenced by the winner.

## Qualification

- Focused atomic-ingest and general-persistence slice: 60 passed.
- Full non-external collection: 3,213 tests, two established xfails, no failure
  or skip.
- Live pgvector external lane: 23 passed against the healthy local container.
- Affected graph, relation extraction, retrieval, chat, MCP, and WebUI surfaces,
  changed-file Ruff, and `git diff --check`: green.
- Independent delivery and assurance agents completed three repair waves; final
  assurance reports zero findings.
- Eight root-recorded red-green cycles cover rollback, vector deletion replay,
  historical/current graph semantics, namespace/scope isolation, durable
  document-intent association, node-vector replay, shared-entity rebuild, and
  relation-extraction identity.

## Claim boundary and resume order

D2 is locally qualified, not protected-main complete. Finish this branch
through explicit staging, signed commit, push, exact-head hosted checks, a
root-stored `QUALIFIED` receipt, protected merge, and exact-main resume. Do not
count D1's hosted checks for this successor tree.

After that merge, start D3 Lifecycle Exclusion from fresh protected main with a
new isolated worktree, session state, bounded context packet, public-seam red
test, delivery wave, and independent assurance. Do not start S9 measurement
until every S8 stream and its boundary-only SQL decision are frozen. No S8,
S9, S10, release, deployment, or hosted-production claim is established here.
