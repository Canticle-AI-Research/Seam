---
handoff_id: 2026-09-01-track-s-g1-locally-qualified-r1-next
supersedes: 2026-09-01-track-s-t1-locally-qualified-g1-next
handoff_status: superseded
history: HISTORY#628
---

# Track S G1 locally qualified; R1 next after protected merge

## Exact state

Protected `main@72fbaa13d34608a16d56c9459140d59b1b436836` contains complete
D1 Recovery, D2 Atomic Ingest, D3 Lifecycle Exclusion, D4 Snapshot Integrity,
and T1 Temporal Semantics through merged PR #243. The isolated branch
`codex/s8-g1-graph-trust`, based exactly on that commit, closes the local G1
Graph and Trust Integrity implementation and evidence gap.

Trust evaluation now requires contradiction/refutation source nodes, relations,
source episodes, and relation episodes to share the target namespace/scope and
requested time horizon. Unevidenced status and relation disputes are retained
as explicit ignored decision inputs rather than silently demoting claims. Every
trust decision exposes exact episode, graph-edge, and canonical record IDs, and
every returned graph edge has both endpoints in the returned node set.

Reasoning-pattern results now retain later conflicting outcomes in an
append-only disagreement ledger. `reasoning-pattern-schema/1` stores migrate to
`reasoning-pattern-schema/2`; successful disagreements require a verified,
accepted outcome; same-outcome replays are idempotent by success state plus
outcome ID and return the originally stored evidence rather than caller wording.

## Qualification

- Full non-external selection: all 3,269 selected tests completed with exit 0;
  the two established xfails remain.
- Isolated live-pgvector external lane: all 23 tests passed with strict no-skip.
- Focused deep-graph, reasoning-pattern, and SQLite-migration matrix: 119
  passed.
- Changed-file Ruff and `git diff --check`: green.
- Root-witnessed red/green cycles cover unevidenced disputes, bare contradicted
  status, future relation evidence, future contradiction sources, graph endpoint
  closure, disagreement retention, same-outcome idempotency, replay evidence,
  and the v1-to-v2 migration.
- Independent standards and spec reviews rejected partial iterations; both
  final reviews returned no findings.

## Claim boundary and resume order

G1 is locally qualified, not protected-main complete. Finish this branch through
explicit staging, signed commit, push, exact-head hosted checks, a root-stored
`QUALIFIED` receipt, protected merge, and exact-main resume. Do not count T1's
hosted checks for this successor tree.

After that merge, start R1 S8 Retrieval Contract from fresh protected main. R1
must resolve the boundary-only SQL gate, flag parity, rank base/tie order, graph
semantic seeding plan field, and explicit legacy adapter contract before R2
scale/backend parity. Do not freeze S8 until R1 and R2 are also green, and do not
start S9 measurement before the complete S8 freeze. No S8, S9, S10, release,
deployment, or hosted-production claim is established here.
