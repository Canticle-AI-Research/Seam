# SEAM Project Status

> **This file is a router, not an archive.** It holds the single current
> headline plus pointers. Detail lives in routed status streams; chronology
> lives in `HISTORY.md`. Both are authoritative over this file.
>
> Read the stream your task touches — see `docs/status/index.md` —
> rather than loading the whole status surface.

## Current headline

**2026-08-01 — HISTORY#524.** A whole-repository read-only audit is recorded at
`docs/audits/2026-08-01-full-repo-audit.md` and registered in the new
`docs/audits/INDEX.md`; read the latest audit before concluding a defect is new.
It closed three CI/documentation findings and left four higher-severity ones
**open, with reproducers**: concurrent `persist_ir` defeats entity coreference
(8 concurrent ingests yield 8 distinct ENT records where sequential yields 1);
unauthenticated `/chat` forwards any environment variable to a caller-chosen
loopback address; the projection registry detects but cannot migrate across any
of its 13 version constants; and `_time_reached` falls back to lexicographic
comparison inside the trust gate. Fixed in the same session: 13 of 23 external
tests ran in no CI lane and the guard that should have caught it now derives its
required set from the test tree; `repo-hygiene` now runs the configured linter;
`SEAM_STRICT_NO_SKIP=0` is no longer silent; and the release documentation now
matches the real workflow, which has no PyPI path. Full repository scope with
the live pgvector external lane: **2,154 passed, 2 xfailed, no skips, no
failures**. The live ruleset still requires only `repo-hygiene`,
`chroma-real-smoke`, and `locomo-quickstart-bil2`.

**HISTORY#523.** Track S, the Production-Core Integrity
Campaign, is active and S2's central migration spine is locally qualified.
Schema version 2 now governs canonical SQLite plus every initialized durable
projection through two ordered transactional steps, read-only fail-closed
preflight, retained private pre-migration backups, per-step integrity/foreign-
key gates, and explicit atomic restore. Released v1.2.0 and v2.4.0 historical
fixtures, empty stores, both injected rollback boundaries, partial v1 resume,
unknown/newer byte-unchanged refusal, and real backup recovery are proven.
The repository-wide non-external scope collected 2,130 tests: 2,128 passed and
the two established cases xfailed. A full S2 code review reported zero findings
before the final narrow fixture-contract and handoff edits; the final whole-tree
rerun was blocked by the free-plan rate limit, and paid review was not enabled.
The live pgvector service was healthy, but its credential-bearing test DSN was
not exported to this process, so S2 did not rerun that external lane.

The S1 dependency guardrail now also governs `seam doctor`: only the canonical
core imports `rich` and `tiktoken` are required, while `chromadb` remains an
informational optional-adapter check. A real subprocess blocks every Chroma
import before SEAM loads and proves doctor still passes. The combined strict
non-external audit scope passed all 1,572 selected tests, and the final
three-file CodeRabbit review reported zero findings.

S3's durable supersession and guarded reprojection is the next canonical
boundary; S4 may proceed in parallel. F22's release lock/hash proof remains
owned by S10. The current
retrieval evidence is still +0.009628 overall versus
legacy with cat3 −0.036775, ENT provenance 0.0000, and live-leg fusion weights
unvalidated; see `docs/status/retrieval.md`.

The canonical plan remains
`docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md`. Track S coordinates Track R, H2,
E2, and K14 without superseding them. No provider-paid benchmark or release was
run as part of S2 or the S1 doctor correction.

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
