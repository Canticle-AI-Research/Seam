# SEAM Project Status

This file routes current operating state. Detail lives in the status streams;
chronology lives in `HISTORY.md`. Plans are not implementation evidence.

## Current headline

**2026-09-12 — memory formation is the active priority.** The
[detailed roadmap](docs/roadmap/MEMORY_FORMATION.md) preserves the recovered
chunking/temporal-entity direction and defines setup, dependency-ordered work
streams and parallel scopes. Start with M1's current-code/history audit; B1
(BIL-3 design), E1 (Anthropic/evaluation setup) and P0 (report-home discovery)
can follow alongside it after the documentation merge. The diagnosis remains
a hypothesis. No formation implementation, BIL-3 support, paid benchmark or
website deployment was performed in this planning slice. See HISTORY#645 and
the [current handoff](docs/handoffs/INDEX.md).

**2026-09-08 naming candidate:** `seam-suite` 2.4.1rc1 names the self-hosted
Suite; SEAM Client names the paid API and its WebUI; `seam-sdk` remains private
paid delivery. The existing `seam-client` wheel remains a Python HTTP client.
TestPyPI must precede production publication. Artifact eligibility and test
publisher access remain open; see [the procedure](docs/TESTPYPI.md) and
HISTORY#642. This branch candidate does not publish a package.

**2026-09-07 — R2 is complete and S8 is frozen on protected main through
PR #254 at `2f9a96b9`.** Candidate `a6715c2f` passed the three required checks
and PostgreSQL integration, received an independently authored and validated
release receipt, and merged through the protected PR path. The resulting
main tree is identical to the qualified candidate; the same required checks
and PostgreSQL integration passed on exact main. HISTORY#641 records the
publication boundary and [current handoff](docs/handoffs/INDEX.md).

The [S8 gate matrix](tests/docs/s8-completion.md) covers all prerequisites and
original mechanism exits; [backend evidence](tests/docs/r2-backend-parity.md)
separates exact parity from selected-corpus work, cache/page storage, ANN recall
and synthetic cost measurements. The SQL-tail decision is recorded and
`legacy-weighted/1` remains the compatibility default. S9 qualification and
Promotion, S10 release/deployment proof, and operator-product acceptance remain
open. No benchmark quality improvement or hosted-production claim follows
from this freeze.

The previous surface-first score-campaign sequence is superseded by the
new roadmap. Surface and packaging acceptance remain required for their
products; the [launch plan](docs/roadmap/SEAM_LAUNCH.md) is retained as that
backlog. The [L1 packet](docs/audits/2026-09-06-l1-packaging-migration.md)
continues to record private SDK and artifact/customer-delivery blockers.
Score aspirations require a named benchmark, metric and agreed conditions;
existing correctness and required CI checks continue throughout.

The TUI and browser prototype are existing implementation inputs. Review,
curation, health, real backend acknowledgements, credential handling, and the
independently loadable graph/database/glassbox sections need acceptance evidence.
Use the [surface stream](docs/status/surfaces.md) for those boundaries.

GitHub currently reports the canonical repository as public. Root package
metadata now declares the `seam-suite` 2.4.1rc1 candidate with `Private :: Do Not Upload`;
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
