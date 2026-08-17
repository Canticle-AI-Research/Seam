# SEAM Project Status

> **This file is a router, not an archive.** It holds the single current
> headline plus pointers. Detail lives in routed status streams; chronology
> lives in `HISTORY.md`. Both are authoritative over this file.
>
> Read the stream your task touches — see `docs/status/index.md` —
> rather than loading the whole status surface.

## Current headline

**2026-08-12 — whole-repository deep audit filed at
`docs/audits/2026-08-12-full-repo-audit.md` (HISTORY#560)**, with the
complete project timeline at
`docs/audits/2026-08-12-seam-complete-timeline.md`. Protected `main` is
`f5d304c`. All four critical/high reproducers from the prior audits are
verified fixed in code; no new criticals. Open: a MEDIUM cluster (chat
response buffering, REST /persist caller-supplied ids, applied-policy
divergence across surfaces, process-lifetime flag cache, unbounded SQL IN
expansion, outbox soft-delete replay) plus documentation drift, repaired in
this entry. This supersedes the 2026-08-03 HISTORY#533 headline.

S6 — principal tenancy and opaque deletion — is now the only unblocked stage.
The termination decision is recorded (2026-08-05, HISTORY#538): tenancy
terminates in-process with an optional principal. `/v1` still has no tenancy
binding, and carries 35 HTTP-level tests.

S5 was designed as one change rather than two, because `HISTORY#528` recorded
that pooling alone satisfies the connection clause while leaving the
read-snapshot tear intact:

- **One committed read snapshot per request.** A context-local binding, keyed
  by database identity, holds one deferred read transaction on one pooled
  connection. `SnapshotAwarePool` routes every checkout to it, so joining is
  the default rather than something any of ~100 read helpers can omit. The key
  is the *database*, not the store, which is what pulls in the SQLite vector
  index: it is opened on `store.path`, so the semantic leg was reading a second
  committed state even after the canonical legs were pooled. The snapshot
  carries an authorizer denying mutations — without it a stray write would join
  the read transaction and be silently discarded by the closing rollback, a
  failure mode worse than the tear being fixed.
- **A durable vector outbox** (F7) commits the intent to index in the same
  transaction as the canonical rows, acknowledges only after indexing succeeds,
  and replays on reopen. Replay assumes the backend was *not* updated, because
  after a crash that is unknowable; re-indexing is a content-hash no-op, so
  duplicate replay is harmless by construction. Deletes stay on lifecycle's
  existing `cleanup_pending` state rather than gaining a second source of truth.
- **No schema work on the read path** (F14). `PgVectorAdapter.search` ran a
  create-extension/create-table/probe/ALTER/create-index/HNSW script on every
  query; it now ensures nothing. `SQLiteVectorIndex.ensure_schema` had the same
  defect and was also the reason warm retrieval kept opening connections
  despite the pool.
- **Divergence detection and repair** across SQLite-vector, pgvector, and
  Chroma, reported as three separately-repairable shapes (missing, stale,
  orphan). Chroma had no inspection methods at all and gained them.

Two findings came out of building it. A failed persist whose restore succeeds
must retire its outbox intents, or it violates S4's qualified invariant that
such a write is an exact no-op — caught by four existing tests. And the first
version of the fingerprint test passed against a deliberately broken
implementation: it varied record text, and under the 64-dimension signed hash
embedding the distinguishing word collided destructively with the query term,
dropping those records from the semantic leg so a torn read looked identical.
The fixture now varies only record ids, and the test was re-verified to fail
with the snapshot disabled.

Full suite at the 2026-08-12 audit (live pgvector lane): **2382 passed,
0 skipped, 2 xfailed** in 256s; ruff clean. The 2 xfails remain the
pre-existing `compile_nl` compiler-rewrite targets.

S4 replaces colon/prefix inference with closed typed-reference contracts.
Timestamps, URLs, and arbitrary colon-bearing values remain literals unless a
schema field and exact canonical membership make them references; explicit
virtual identities remain deliberate. Exact `core-storage/1 -> /2` and
`knowledge-graph/5 -> /6` migrations persist both endpoint types, validate both
sides of every edge, retain the truthful S3 `/5` resume point, and replay
lifecycle, document-supersession, and identity-judgement truth after
reprojection. It is published at `main@ea4e46e`.

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
  does not exist here. The S6 termination decision is now recorded: tenancy
  terminates **in-process with an optional principal**
  (2026-08-05, HISTORY#538; `docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md` S6).
  `/v1` carries 35 HTTP-level tests in `tests/audit/test_public_api_v1_http.py`
  (HISTORY#535).
- ~~**Retrieval legs share no read snapshot.**~~ **Closed and published** by
  S5 at `main@19b3a76`: the eleven `store._connect()` sites now use the pool,
  and the pool itself routes to a per-request committed snapshot that the
  same-file SQLite vector index joins. Verified to discriminate — with the
  snapshot disabled, a mid-request commit enters the candidate set and
  `candidate_set_sha256` changes.
- **Unbounded SQL variable expansion** remains open at current sites:
  `knowledge_graph.py` `_graph_episode_rows` (`:2613-2660`, ~40k bind variables
  worst case) and the retrieval/KG load paths (`adapters.py`, `:1515-1517`,
  `:1558`, `:1576-1580`). Chunked at 400 in `reusable_node_vectors` only.
  Latent on SQLite ≥ 3.32; breaks on the 999-variable default (Debian 10,
  Ubuntu 18.04, RHEL/CentOS 7-8, Amazon Linux 2).
- **Projection transitions now exist but are not statically completeness-
  checked.** Protected `main` carries KG/4-to-/5; this candidate adds exact
  core-storage/1-to-/2 and KG/5-to-/6 transitions. S10 still needs a release
  gate proving every shipped projection-version bump has one registered path.
- **S3 and S4's former positive-gate asymmetry is closed.** S3 is merged; S4's
  successful populated-store transitions and bounded failure/resume path are
  covered locally, with exact-head review and CI still pending.
- Pre-existing worktree/branch hygiene is now routed through
  `docs/status/workspace.md`: active PR aliases, merged cleanup candidates,
  local-only branches, and ignored artifacts remain separate and are preserved
  until their exact dispositions are authorized.
- Dashboard/TUI chat-client coverage landed in the 2026-08-12 audit (see the
  chat allowlist finding); `dashboard.py` (3,198 lines) now has dedicated
  command-palette/shell tests. Still never audited: benchmark seal/BIL
  integrity, MIRL losslessness round-tripping.

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
| [`workspace`](docs/status/workspace.md) | worktrees, branch/PR aliases, local artifacts, overlap, and cleanup boundaries |
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
