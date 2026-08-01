# SEAM Project Status

> **This file is a router, not an archive.** It holds the single current
> headline plus pointers. Detail lives in routed status streams; chronology
> lives in `HISTORY.md`. Both are authoritative over this file.
>
> Read the stream your task touches — see `docs/status/index.md` —
> rather than loading the whole status surface.

## Current headline

**2026-08-01 — HISTORY#511.** Track S, the Production-Core Integrity
Campaign, is active. Its one canonical plan at
`docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md` records the verified F1-F22
verdicts, dependency-ordered stages S0-S10, and exact exit gates. It coordinates
Track R, H2, E2, and K14 without superseding them.

The clean semantic baseline is commit `86a81e2` (exactly 27 paths). Its exact
12-module semantic/offline-integrity slice passed **269/269**; changed-Python-
path Ruff, `git diff --check`, the 27-path allowlist/exclusion audit, and the
same candidate-path secret/session scan were clean. This was not a full-suite
run. The baseline retains fail-closed canonical REL admission and keeps the
27/419 research relation lane scorer-ineligible.

No F1-F22 production defect is claimed fixed by this continuity slice. S0 and
all later stages remain evidence-gated by the campaign plan. The current
retrieval evidence is still +0.009628 overall versus legacy with cat3
−0.036775, ENT provenance 0.0000, and live-leg fusion weights unvalidated; see
`docs/status/retrieval.md`.

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
| [`deferred`](docs/status/deferred.md) | explicitly parked backlog |

Index and routing hints: [`docs/status/index.md`](docs/status/index.md)

## Provenance of this restructure

The previous revision accumulated 143 stacked `Current update:` blocks across
~1,037 lines (348 KB) and could no longer be opened by a standard file read,
despite being step 1 of the mandatory session-start read order.

Nothing was discarded:

- The full prior file is preserved verbatim at
  `docs/status_archive/2026-07-30-project-status-full.md`.
- All **234** distinct `HISTORY#` entries it cited remain present in
  `HISTORY.md` (verified: zero missing).
- Every non-chronological bullet was routed into a status stream above.

Verify with `python -m tools.status.verify_streams`.

## Working Rule

When resuming:

1. Read `PROJECT_STATUS.md` (this file).
2. Read the relevant stream from `docs/status/index.md`.
3. Read `REPO_LEDGER.md`.
4. Read `HISTORY_INDEX.md`.
5. Read `docs/CODE_LAYOUT.md`.
6. Read `docs/DATA_ROUTING.md` when the task touches history, ledgers,
   maintenance records, routing, context budget, or auditability.
7. Read `SEAM_SPEC_V0.1.md` + `docs/MIRL_V1.md` — the governing contract — when
   the task touches compilation, MIRL/IR, compression, PACK, retrieval,
   surfaces, codecs, the improvement loop, benchmarks, or any design or
   measurement claim.
8. Pull only the required `HISTORY.md` entries via
   `python -m tools.history.build_context_pack`.
