# SEAM Project Status

This file routes current operating state. Detail lives in the status streams;
chronology lives in `HISTORY.md`. Plans are not implementation evidence.

## Current headline

**2026-09-07 — R2 backend implementation and all S8 local mechanism gates are
qualified; the protected freeze candidate awaits publication checks.**
HISTORY#640 records exact vector defaults, explicit approximation, deterministic
cutoffs, real backend parity/growth and independent review. See the
[S8 gate matrix](tests/docs/s8-completion.md),
[backend evidence](tests/docs/r2-backend-parity.md), and
[current handoff](docs/handoffs/INDEX.md) for the exact candidate boundary.
The protected starting baseline is `main@5f115664` (PR #253); SQLite structured
scale and temporal/compatibility acquisition are already merged through PRs
#252 and #253. Local qualification does not itself establish the protected
freeze. Candidate CI, the independent release receipt and exact-main checks
must pass before that claim.

The SQL-tail decision remains recorded and `legacy-weighted/1` remains the
compatibility default. S9 qualification/Promotion and S10 release/deployment
proof are separate. Surface Encoded Agent Memory, self-hosted Canticle SEAM
Suite, paid Canticle SEAM API and SEAM WebUI retain the boundaries in the
[product map](docs/PRODUCTS.md) and [launch plan](docs/roadmap/SEAM_LAUNCH.md).
The [L1 packet](docs/audits/2026-09-06-l1-packaging-migration.md) records private
paid SDK access and unresolved customer-delivery/artifact blockers.

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
