# SEAM Project Status

> **This file is a router, not an archive.** It holds the single current
> headline plus pointers. Detail lives in routed status streams; chronology
> lives in `HISTORY.md`. Both are authoritative over this file.
>
> Read the stream your task touches — see `docs/status/index.md` —
> rather than loading the whole status surface.

## Current headline

**2026-08-02 — HISTORY#526, draft PR #193.** The four highest-severity open
reproducers from the whole-repository audit in HISTORY#525 are repaired on the
local recovery candidate, not yet on protected `main`:

- `persist_ir` acquires its write lock before entity reconciliation, and eight
  concurrent ingests now preserve one canonical entity;
- `/chat` and `/chat/stream` bind environment credentials one-to-one to known
  provider hosts and never consult process environment for loopback targets;
- projection version changes have exact registered forward callables with
  version-specific source/target table contracts; and
- malformed or timezone-incomparable trust timestamps warn content-free and
  fail toward expired/stale instead of lexicographic established knowledge.

S2 is locally requalified under the missing positive migration gate. One
exclusive SQLite migration owner rechecks the live schema and exact plan under
lock, creates and durably publishes the same-owner backup, blocks competing
writers across separately committed steps, and preserves earlier resume points
when a later step fails. Projection callbacks and failure hooks cannot control
the spine-owned transaction or downgrade its lock through supported APIs.
Unknown, newer, missing, extra, cyclic, and unregistered states still refuse
before backup or mutation.

The accidental generated HTML audit commit is not an ancestor of the recovery
candidate, and the HTML file is absent. The live branch-protection ruleset was
restored to exactly `repo-hygiene`, `chroma-real-smoke`, and
`locomo-quickstart-bil2`; `test-and-benchmark` remains advisory. Protected
`main` remains `94375e8` until PR #193 is reviewed and merged.

Exact-tree provider-free verification selected **2,172 tests: 2,170 passed and
the two established strict cases xfailed, with no skips or failures**. The live
five-file pgvector lane passed **30/30**. The focused migration suite passed
43/43, Ruff, Python compilation, diff hygiene, and the canonical secret/session
scan passed, and independent adversarial review ended with no blockers. The
local CodeRabbit rerun's only remaining suggestion was already satisfied by
`requires-python = ">=3.11"`.

This is not full hosted hardening. `SEAM_API_TOKEN` remains optional for
trusted-loopback development; automatic token provisioning and principal
tenancy remain S6. Audit findings 7-10 and 12 remain open, including graph
ordering/SQL bounds, `/v1` coverage, retrieval connection pooling, and worktree
hygiene. No paid provider, retrieval-score benchmark, artifact publish, deploy,
or release ran. After protected publication, S3 durable supersession and
guarded reprojection is the next canonical boundary; S4 may proceed in
parallel.

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
