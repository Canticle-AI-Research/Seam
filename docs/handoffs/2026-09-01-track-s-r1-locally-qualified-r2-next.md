---
handoff_id: 2026-09-01-track-s-r1-locally-qualified-r2-next
supersedes: 2026-09-01-track-s-g1-locally-qualified-r1-next
handoff_status: superseded
history: HISTORY#629
---

# Track S R1 locally qualified; R2 next after protected merge

## Exact state

Protected `main@e8ff231dc5b327f802ccacbaf06b8819b152129d` contains complete
D1-D4, T1, and G1 through merged PR #244. The isolated branch
`codex/s8-r1-retrieval-contract`, based exactly on that commit, closes R1
Retrieval Contract findings F-20-F-23.

Persisted positive `search_top_k` and `context_budget` values load through the
applied-state contract with logged fail-closed rejection, but remain excluded
from self-improvement proposal flags. Query-authored `ns:` plus `scope:`
filters admit the SQL non-lexical tail at inclusive score `0.80`; runtime-only
tenant boundaries do not request it, and graph seed acquisition refuses it
below structured score `1.00`. Both RRF implementations use one-based ranks
and record-ID ties. Runtime, MCP, SDK, and compatibility retrieval resolve graph
semantic seeding from one applied policy unless explicitly overridden, and the
resolved boolean is recorded in every plan. `legacy-weighted/1` remains the
versioned compatibility default pending S9 Promotion evidence.

## Qualification

- Affected retrieval/SDK/MCP matrix: 119 passed.
- Full strict non-external selection: exit 0, two established xfails, no skips.
- Isolated live-pgvector external lane: 23 passed, no skips.
- Changed-file Ruff and `git diff --check`: green.
- Root-witnessed red/green cycles cover F-20-F-23 and the bounded graph-tail
  regression discovered by the first full-suite run.

## Claim boundary and resume order

R1 is locally qualified, not protected-main complete. Finish signed commit,
push, exact-head hosted checks, root-stored `QUALIFIED` receipt, protected
merge, and exact-main verification before starting R2.

R2 owns bounded compatibility/temporal acquisition, namespace-selective SQLite
plans, pgvector HNSW expression parity, deterministic backend tie behavior, and
fixed-slice growth/parity cases. Do not freeze S8 until R2 is green. S9, S10,
release, deployment, and hosted-production claims remain unopened.
