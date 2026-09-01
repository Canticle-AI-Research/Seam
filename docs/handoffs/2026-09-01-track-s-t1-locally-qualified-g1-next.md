---
handoff_id: 2026-09-01-track-s-t1-locally-qualified-g1-next
supersedes: 2026-09-01-track-s-d4-locally-qualified-t1-next
handoff_status: superseded
history: HISTORY#627
---

# Track S T1 locally qualified; G1 next after protected merge

## Exact state

Protected `main@0f4bd829058aa65770b1f25ef092f4bd166b8bd2` contains complete
D1 Recovery, D2 Atomic Ingest, D3 Lifecycle Exclusion, and D4 Snapshot
Integrity through merged PR #242. The isolated branch `codex/t1-public-seam`,
based exactly on that commit, closes the local T1 Temporal Semantics
implementation and evidence gap.

One policy in `seam_runtime.temporal` now owns `Z`/`z`, numeric offsets,
naive-as-UTC values, missing/blank interval bounds, and invalid nonblank values.
Reconciliation, graph as-of/current visibility and order, stale horizons,
graph-source selection, graph products, trace/self-improvement reads, context
assembly, reasoning patterns, and both temporal retrieval policies share that
policy. Missing bounds remain open; invalid values fail closed. Original MIRL
timestamp text remains unchanged, while derived graph/context comparison keys
are canonical UTC. The serialized context contract is explicitly bumped to
`context-assembly/2`, including its qualification manifest.

## Qualification

- Full non-external selection: all 3,257 selected tests completed with exit 0;
  the two established xfails remain.
- Live pgvector external lane: all 23 tests passed with strict no-skip.
- Affected temporal/reconciliation/graph/retrieval/context/snapshot matrix: 130
  passed.
- Changed-file Ruff and `git diff --check`: green.
- Root-witnessed red/green cycles cover the base public seam plus direct aware
  retrieval, open-vs-invalid intervals, snapshot/direct SQLite connections,
  derived timestamp writers, context contract versioning, and every blank-bound
  graph consumer found in review.
- Independent standards and spec reviews rejected partial iterations; both
  final reviews returned no findings.

## Claim boundary and resume order

T1 is locally qualified, not protected-main complete. Finish this branch
through explicit staging, signed commit, push, exact-head hosted checks, a
root-stored `QUALIFIED` receipt, protected merge, and exact-main resume. Do not
count D4's hosted checks for this successor tree.

After that merge, start G1 Graph and Trust Integrity from fresh protected main
with the same isolated public-seam TDD and independent-assurance protocol. R1
may follow or proceed as an independently isolated stream after T1 is protected;
R2 depends on R1. Do not freeze S8 until G1, R1, and R2 are all green, and do
not start S9 measurement before the complete S8 freeze. No S8, S9, S10,
release, deployment, or hosted-production claim is established here.
