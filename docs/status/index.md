# Status Stream Index

Decomposition of `PROJECT_STATUS.md` into routed streams, mirroring the
history-stream pattern. Read the stream your task touches instead of loading
the whole status surface.

schema: v1
source: PROJECT_STATUS.md
streams: 9

| stream | file | covers |
|---|---|---|
| `retrieval` | [retrieval.md](retrieval.md) | Retrieval engine, ranking policies, and the open ablation gate |
| `benchmarks` | [benchmarks.md](benchmarks.md) | LoCoMo, WANDR, BEAM, harness, integrity levels, and recorded audits |
| `surfaces` | [surfaces.md](surfaces.md) | CLI, shell, TUI dashboard, webui, REST, MCP, SDK, installers |
| `compression-visual` | [compression-visual.md](compression-visual.md) | MIRL/RC, SEAM-LX/1, and SEAM-HS/1 holographic surfaces |
| `packaging-licensing` | [packaging-licensing.md](packaging-licensing.md) | Distribution shape, licensing, and the public/private boundary |
| `protocol-continuity` | [protocol-continuity.md](protocol-continuity.md) | History protocol, streams, routing, and context budget |
| `operations` | [operations.md](operations.md) | pgvector, Docker, CI, guardrails, and durable operator workflows |
| `workspace` | [workspace.md](workspace.md) | Worktrees, branch/PR aliases, coupled repositories, local artifacts, overlap, and safe next actions |
| `deferred` | [deferred.md](deferred.md) | Explicitly deferred backlog — parked, not lost |

## Routing hints

| if the task touches... | read |
|---|---|
| ranking, legs, fusion, ablation, recall | `retrieval` |
| LoCoMo, WANDR, BEAM, BIL, paid runs | `benchmarks` |
| CLI, shell, TUI, webui, REST, MCP, SDK | `surfaces` |
| MIRL/RC, LX, HS/1, PACK, codecs | `compression-visual` |
| licensing, PyPI, public/private boundary | `packaging-licensing` |
| HISTORY, streams, routing, context budget | `protocol-continuity` |
| pgvector, Docker, CI, guardrails | `operations` |
| worktrees, branches, PR aliases, companion repositories, local artifacts, duplicate work | `workspace` |
| parked backlog | `deferred` |

## Invariants

- A stream holds **current state**, never chronology. Chronology is `HISTORY.md`.
- Never stack `Current update:` blocks in a stream; supersede the text in place.
- `PROJECT_STATUS.md` stays a thin router and must remain readable in one read.
