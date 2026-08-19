# SEAM Project Status

> **This file is a router, not an archive.** It holds the single current
> headline plus pointers. Detail lives in routed status streams; chronology
> lives in `HISTORY.md`. Both are authoritative over this file.
>
> Read the stream your task touches — see `docs/status/index.md` — rather
> than loading the whole status surface.

## Current headline

**2026-08-18 — Track S, graph-benchmark, operator-surface, and deployment
readiness were re-audited from protected `main@48c5448`.** The governing
reports are:

- `docs/audits/2026-08-18-track-s-deployment-readiness-audit.md`;
- `docs/audits/2026-08-18-graph-benchmark-readiness-research.md`; and
- the current handoff in `docs/handoffs/INDEX.md`.

Track S is not complete. S0-S5 are published through PRs #190, #191, #193,
#194, #195, and #199. Later S1/S5 counterexamples are repaired on the audit
candidate and require merge/requalification before S6. S6-S10 remain ordered
work:

```text
S6 principal tenancy
  -> S7 admissible semantic graph
  -> S8 one coherent retrieval engine
  -> S9 matched multi-benchmark qualification
  -> S10 required CI, release, and deployment proof
```

The audit candidate closes the bounded, non-design findings that could be
reproduced safely now: capped server `/chat` provider responses (2026-08-12
audit F-5), create-only REST `/persist` collisions (audit F-6), deleted-record
vector-outbox replay (audit F-10), deterministic SQL-leg ties (audit F-11),
zero-confidence activation leakage, duplicate
OpenAPI operation IDs, disposable LoCoMo adapter state, and linked-worktree
pre-push misclassification. These are branch-local candidate repairs until
their PR merges; internal runtime/store persistence deliberately remains an
upsert.

Those hyphenated IDs belong to the 2026-08-12 full-repository audit, not the
campaign's activation-time F1-F22 matrix.

Current graph evidence proves structure, provenance machinery, and parity, not
a graph-caused quality advantage. The matched 1,542-case LoCoMo graph/non-graph
arms tie at `0.776048` because the snapshot has zero admissible semantic
relations; WANDR and G7/R6 are saturated parity lanes with zero graph-
incremental hits. A top-level claim therefore requires the causal portfolio in
the graph-readiness report, not another unsupported headline score.

The Textual TUI is a real seven-tab, runtime-backed local operator surface, but
the target Review/Curate/Health workflow is incomplete. The operator's newer
TUI source was not found in any active checkout, installed entrypoint,
`AppDir/`, or `squashfs-root/`; it must be supplied before integration.
The served WebUI is a prototype that mixes live API calls with simulated
success, mock persistence, browser-stored credentials, and fabricated metrics.
It is not a beta operator surface and should be made truthful and secure before
a visual restyle.

Hosted deployment is blocked by S6 and by the absence of a tested production
topology for TLS, shared rate limiting, service supervision, backup/restore,
and disaster recovery. Trusted-loopback single-user use remains the current
deployment boundary.

The 2026-08-12 full-repository audit and its detailed prior headline remain
available at `docs/audits/2026-08-12-full-repo-audit.md` and
`docs/handoffs/2026-08-12-deep-audit.md`; they are historical evidence, not
the current router.

## Status streams

| stream | covers |
|---|---|
| [`retrieval`](docs/status/retrieval.md) | ranking policies, legs, fusion, the open ablation gate |
| [`benchmarks`](docs/status/benchmarks.md) | LoCoMo, WANDR, BEAM, integrity levels, recorded audits |
| [`surfaces`](docs/status/surfaces.md) | CLI, shell, TUI, webui, REST, MCP, SDK, installers |
| [`compression-visual`](docs/status/compression-visual.md) | MIRL/RC, SEAM-LX/1, SEAM-HS/1 surfaces |
| [`packaging-licensing`](docs/status/packaging-licensing.md) | distribution shape, licensing, public/private boundary |
| [`protocol-continuity`](docs/status/protocol-continuity.md) | history protocol, streams, routing, context budget |
| [`operations`](docs/status/operations.md) | pgvector, Docker, CI, guardrails, operator workflows |
| [`workspace`](docs/status/workspace.md) | worktrees, branch/PR aliases, coupled repositories, local artifacts, overlap, and cleanup boundaries |
| [`deferred`](docs/status/deferred.md) | explicitly parked backlog |

Index and routing hints: [`docs/status/index.md`](docs/status/index.md)

## Provenance of this router

The previous pre-router status file accumulated 143 stacked update blocks and
was preserved verbatim at
`docs/status_archive/2026-07-30-project-status-full.md`. The detailed
2026-08-12 router headline is preserved by that date's audit and handoff.
Chronology remains append-only in `HISTORY.md`; current durable facts live in
the status streams and `REPO_LEDGER.md`.

Verify the routed status surface with `python -m tools.status.verify_streams`.

## Working rule

When resuming:

1. Read `PROJECT_STATUS.md` (this file).
2. Read the relevant stream from `docs/status/index.md`.
3. Read `REPO_LEDGER.md`.
4. Read `HISTORY_INDEX.md`.
5. Read `docs/CODE_LAYOUT.md`.
6. Read `docs/DATA_ROUTING.md` when the task touches history, ledgers,
   maintenance records, routing, context budget, or auditability.
7. Read `SEAM_SPEC_V0.1.md` + `docs/MIRL_V1.md` when the task touches
   compilation, MIRL/IR, compression, PACK, retrieval, surfaces, codecs, the
   improvement loop, benchmarks, or design/measurement claims.
8. Pull only required history via
   `python -m tools.history.build_context_pack`.
