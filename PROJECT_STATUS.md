# SEAM Project Status

> **This file is a router, not an archive.** It holds the single current
> headline plus pointers. Detail lives in routed status streams; chronology
> lives in `HISTORY.md`. Both are authoritative over this file.
>
> Read the stream your task touches — see `docs/status/index.md` —
> rather than loading the whole status surface.

## Current headline

**2026-08-02 — HISTORY#527, branch `fix/audit-2026-08-02-critical`.** PR #193
**merged** at `6b7c22d`; protected `main` now carries the S2 spine and the
HISTORY#525 audit remediation. Draft PRs **#194 (S3)** and **#195 (S4)** are
open and fully green, including advisory `test-and-benchmark`.

A second whole-repository audit against the merged tree found one CRITICAL and
two HIGH issues the first audit missed, now repaired on this branch:

- `/chat` echoed the target's HTTP response body into its 502 detail. Because a
  loopback `base_url` is allowed unconditionally so local Ollama works, that
  turned the allowance into a **read primitive over every service bound to
  127.0.0.1**. Loopback failures now report the status code or exception type
  only, matching what `/chat/stream` already did.
- FastAPI's generated `/docs`, `/redoc`, and `/openapi.json` carried no
  dependency, so they bypassed both the bearer guard and the rate limiter. They
  are now disabled whenever `SEAM_API_TOKEN` is set.
- The knowledge-graph hop query ordered only by `(confidence desc, updated_at
  desc)`. Rows are consumed in returned order and the loop stops at `limit`, so
  ties selected **which nodes were in the answer**. Reversing physical insert
  order returned a disjoint set; a terminal `e.id` tiebreak fixes it. This fed
  the self-improvement graph probe scorer, so proposals could turn on insert
  order.

The prior audit's claim that this tiebreak affected `candidate_set_sha256` was
**wrong** and is corrected: the orchestrator has its own already-tiebroken
traversal (`adapters.py:776`) and never calls `query_graph`.

Also on this branch: the required `repo-hygiene` gate now runs `ruff check .`
(it linted only `seam_runtime/`, `tools/`, and `seam.py`, leaving `tests/`
unlinted with two live errors) and now runs `verify_integrity`,
`verify_continuity`, `verify_routing`, and `verify_streams`, which previously
ran only in the advisory lane. Malformed `SEAM_RETRIEVAL_LEG_WEIGHTS` and
`SEAM_GRAPH_SEMANTIC_*` values now log a warning instead of silently disabling
an ablation.

The four highest-severity reproducers from HISTORY#525, repaired in HISTORY#526
and now on `main`:

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

The accidental generated HTML audit commit is not an ancestor of `main`, and the
HTML file is absent. The live branch-protection ruleset is exactly
`repo-hygiene`, `chroma-real-smoke`, and `locomo-quickstart-bil2` (re-queried
2026-08-02); `test-and-benchmark` remains advisory, though it is currently green
on both #194 and #195.

Exact-tree provider-free verification selected **2,172 tests: 2,170 passed and
the two established strict cases xfailed, with no skips or failures**. The live
five-file pgvector lane passed **30/30**. The focused migration suite passed
43/43, Ruff, Python compilation, diff hygiene, and the canonical secret/session
scan passed, and independent adversarial review ended with no blockers. The
local CodeRabbit rerun's only remaining suggestion was already satisfied by
`requires-python = ">=3.11"`.

This is not full hosted hardening. `SEAM_API_TOKEN` remains optional for
trusted-loopback development; automatic token provisioning and principal
tenancy remain S6.

**Known open, deliberately not attempted on this branch:**

- **`/v1` has no tenancy binding.** `public_api.remember/recall/context` take no
  caller identity; `namespace` and `session_id` come off the request body, so
  one bearer token reads and writes every namespace. Correct for BUSL
  self-host; for the paid hosted API this is the multi-tenant boundary and it
  does not exist here. **S6 must state explicitly whether tenancy terminates in
  a proxy ahead of `/v1` or in-process** — that decision is currently written
  down nowhere. `/v1` also has zero HTTP-level tests (2 references in the whole
  test tree; no test exercises `POST /v1/memories`, `/v1/memories/recall`, or
  `/v1/context`).
- **Retrieval legs share no read snapshot.** Eleven `store._connect()` sites in
  `retrieval_orchestrator/adapters.py` bypass the pool, and `_connect` leaves
  `isolation_level` at the sqlite3 default, so each leg is its own read
  transaction and one is opened *inside* the hop loop. A `mix` search
  concurrent with an ingest can emit a path through a node the visibility check
  then drops, making `candidate_set_sha256` attest a set that existed in no
  committed database state. **Pooling alone does not fix this** — S5's gate as
  written ("opens no new physical SQLite connections") would pass while the
  tear remains, and needs a snapshot-consistency clause.
- **Unbounded SQL variable expansion** in `knowledge_graph.py` (`:1106`,
  `:1143`, `:1161`, `_graph_episode_rows` `:2074-2090`), where the orchestrator
  chunks at 400. Latent on SQLite ≥ 3.32; breaks on the 999-variable default
  (Debian 10, Ubuntu 18.04, RHEL/CentOS 7-8, Amazon Linux 2).
- **No ledger of shipped projection versions.** `PROJECTION_MIGRATIONS` is
  empty and nothing forces a version bump to ship with a registered migration,
  so bumping any of the 13 constants renders existing stores unopenable.
- **S3's exit gate is 4/4 refusal-shaped** with no clause requiring a rebuild to
  succeed — the same asymmetry that produced the missing forward-migration path
  in S2. PR #194 is open against it.
- Worktree hygiene: 6 worktrees, 2 dirty; 3 merged branches undeleted.
- Never audited, across two consecutive audits: `dashboard.py` (3,160 lines,
  zero dedicated tests), benchmark seal/BIL integrity, MIRL losslessness
  round-tripping.

No paid provider, retrieval-score benchmark, artifact publish, deploy, or
release ran. S3 durable supersession and S4 typed references are in flight as
draft PRs #194 and #195.

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
