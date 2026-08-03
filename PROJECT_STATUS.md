# SEAM Project Status

> **This file is a router, not an archive.** It holds the single current
> headline plus pointers. Detail lives in routed status streams; chronology
> lives in `HISTORY.md`. Both are authoritative over this file.
>
> Read the stream your task touches — see `docs/status/index.md` —
> rather than loading the whole status surface.

## Current headline

**2026-08-03 — HISTORY#530, rebuilt Track S S4 candidate** (supersedes the
2026-08-03 HISTORY#529 headline). Protected `main` is `9bd40cb`: S3 merged
through PR #194 after every required and advisory exact-head check passed. S4
has been selectively rebuilt from that exact ancestry; PR #195 is retargeted to
`main`, but its old head and old green checks remain superseded until this
candidate replaces them and fresh review plus CI pass.

S4 replaces colon/prefix inference with closed typed-reference contracts.
Timestamps, URLs, and arbitrary colon-bearing values remain literals unless a
schema field and exact canonical membership make them references; explicit
virtual identities remain deliberate. Exact `core-storage/1 -> /2` and
`knowledge-graph/5 -> /6` migrations persist both endpoint types, validate both
sides of every edge, retain the truthful S3 `/5` resume point, and replay
lifecycle, document-supersession, and identity-judgement truth after
reprojection.

S3 remains the published foundation. Its known-good `knowledge-graph/4` store
applies exactly one registered `/4 -> /5` transition, rebuilds disposable
topology from canonical MIRL/lifecycle/document truth, preserves
current/history/point-in-time semantics and independently supported edges, and
resurrects zero excluded records. Invalid canonical document identifiers fail
closed with digest-only diagnostics.

A second whole-repository audit against the merged tree found one CRITICAL and
two HIGH issues the first audit missed, now merged through PR #196:

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

Also merged through PR #196: the required `repo-hygiene` gate now runs `ruff check .`
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
HTML file is absent. The live branch-protection ruleset requires
`repo-hygiene`, `chroma-real-smoke`, and `locomo-quickstart-bil2`;
`test-and-benchmark` remains advisory. Prior #194/#195 green runs used the old
workflow and do not qualify the rebuilt heads.

The frozen rebuilt S4 candidate passed **332/332** focused S4 audit tests. The
expanded focused run also passed **118/120** legacy fidelity cases, with the
other two remaining established xfails, and the complete provider-free audit
passed **1,806/1,806** selected non-external cases; 23 external cases are
explicitly reserved for the live pgvector CI lane. Ruff, Python compilation,
and diff hygiene pass; the candidate secret/session scan is rerun only after
the evidence freeze. Repeated semantic, batching, and exact-diff reviews closed
the publication blockers they found:
unbounded migration materialization, raw canonical IDs in diagnostics, orphan
graph vectors, missing source ownership, batch-dependent RAW attribution,
lost boundary-only vector reuse, repeated identity-ledger scans, incomplete
current-store contributor validation, per-edge conflict queries, duplicate
batch IDs, incomplete entity-reference remapping, unresolved required/generic
endpoints, canonical PROV fallback gaps, hard deletes that could leave dangling
payload references, divergent reconciliation/facet contracts, and bypassable
virtual-reference metadata validation. The final repair pass also closes
malformed required/list shapes at both object and raw-JSON boundaries,
registry-less KG/4 bootstrap and hybrid-registry ambiguity, stale optional-
reference graph projections after delete, stale ordinary-write PROV
attribution, explicit-facet precedence, reconciliation-based kind-change
bypass, and non-atomic runtime recovery after vector failure. Current-store
reopen validates canonical payload closure in bounded batches; required-target
deletion refuses atomically, while surviving optional references are
reprojected as literals or explicitly declared virtual identities. One
independent frozen-diff review plus exact-head CodeRabbit and CI remain required
before publication.

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
- **Projection transitions now exist but are not statically completeness-
  checked.** Protected `main` carries KG/4-to-/5; this candidate adds exact
  core-storage/1-to-/2 and KG/5-to-/6 transitions. S10 still needs a release
  gate proving every shipped projection-version bump has one registered path.
- **S3 and S4's former positive-gate asymmetry is closed.** S3 is merged; S4's
  successful populated-store transitions and bounded failure/resume path are
  covered locally, with exact-head review and CI still pending.
- Pre-existing unrelated worktree/branch hygiene remains outside this PR and
  is preserved rather than silently combined.
- Never audited, across two consecutive audits: `dashboard.py` (3,160 lines,
  zero dedicated tests), benchmark seal/BIL integrity, MIRL losslessness
  round-tripping.

No paid provider, competitive retrieval-score benchmark, artifact publish,
deploy, or release ran. S3 is merged; rebuilt S4 PR #195 is the next ordered
publication boundary.

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
