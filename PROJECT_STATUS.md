# SEAM Project Status

This file routes current operating state. Detail lives in the status streams;
chronology lives in `HISTORY.md`. Plans are not implementation evidence.

## Current headline

**2026-09-06 — R2 structured SQLite scale slice; acquisition and backend parity
remain open.** HISTORY#637 records the scoped runtime change and its
[evidence](tests/docs/r2-sqlite-scale.md). L1 packaging preparation and the
private paid SDK boundary remain recorded.
The product direction is Surface Encoded Agent Memory,
Canticle SEAM Suite for self-hosting, and Canticle SEAM API with SEAM WebUI for
the paid service. See the [product map](docs/PRODUCTS.md),
[launch plan](docs/roadmap/SEAM_LAUNCH.md), and current handoff in
[the registry](docs/handoffs/INDEX.md). Decision and reconciliation: HISTORY#634.

The [L1 packaging candidate](docs/audits/2026-09-06-l1-packaging-migration.md)
now records exact local artifact evidence and unresolved release blockers
(HISTORY#635). SEAM SDK is private, with access for paying users; the public
HTTP client remains a distinct artifact. See the current handoff for scope.

The checked protected baseline is `main@2f6e747` (PR #251); it contains the
launch documentation and L1 packaging candidate (HISTORY#634-#636). It contains D1-D4,
T1, G1, and R1, followed by the R1 continuity correction, audit cleanup, and uv
lockfile work. **R2 Retrieval Scale and Backend Parity remains in progress
before S8 freeze.** The structured SQL slice does not complete its acquisition
or backend gates. `legacy-weighted/1` remains the compatibility default;
S9 Promotion evidence is still required to change it. See
[Track S](docs/roadmap/TRACK_S_S8_S10_PRODUCTION_CORE.md) and HISTORY#630-#633.

The operator-surface lane is now part of launch delivery. Complete and review
Suite and API/WebUI before the expensive benchmark score campaign; existing
correctness, security, conformance, and required CI checks continue throughout.
The requested 90% target needs a named benchmark/metric and agreed evaluation
conditions. S9 qualification and S10 release/deployment proof remain open.

The TUI and browser prototype are existing implementation inputs. Review,
curation, health, real backend acknowledgements, credential handling, and the
independently loadable graph/database/glassbox sections need acceptance evidence.
Use the [surface stream](docs/status/surfaces.md) for those boundaries.

GitHub currently reports the canonical repository as public. Root package
metadata still declares `seam-runtime` 2.4.0 with `Private :: Do Not Upload`;
existing license files and the PyPI prohibition are unchanged. The
[packaging stream](docs/status/packaging-licensing.md) separates source visibility,
existing releases, future artifact eligibility, and migration work. No naming
change in these docs publishes a package or deploys a service.

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
