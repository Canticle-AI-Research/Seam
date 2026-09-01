# SEAM Project Status

> **This file is a router, not an archive.** It holds the single current
> headline plus pointers. Detail lives in routed status streams; chronology
> lives in `HISTORY.md`. Both are authoritative over this file.
>
> Read the stream your task touches — see `docs/status/index.md` — rather
> than loading the whole status surface.

## Current headline

**2026-09-01 — protected `main@253037a` contains complete D1 Recovery, D2
Atomic Ingest, and D3 Lifecycle Exclusion; D4 Snapshot Integrity is locally
qualified on `codex/d4-snapshot-integrity`.** D3 reached protected main through
PR #241. D4 now keeps a rejected store write inside the original committed read
snapshot, gives nested readers a guarded connection/cursor facade, denies every
transaction and savepoint transition, and keeps authorizer removal, close,
BLOB mutation, deserialize, mutating PRAGMAs, ATTACH/DETACH, and other SQLite
mutation controls under the snapshot owner's exclusive release boundary.
Owner-managed `query_only` state is restored when the pooled connection is
returned. The exact candidate has 3,238 selected non-external cases green with
two established xfails, all 23 live pgvector external tests green, 51 focused
snapshot/pool/retrieval/lifecycle regressions green, changed-file Ruff and diff
checks green, and independent standards/spec assurance with no remaining
finding. D4 still requires commit, exact-head hosted checks, a root-stored
qualification receipt, and protected merge before it is protected-main
complete. T1 follows only after that merge; S8 remains incomplete, S9 has not
started, and no S10 release, deployment, or hosted-production claim is made. See
`docs/roadmap/TRACK_S_S8_S10_PRODUCTION_CORE.md` and the current handoff.

**2026-08-26 — protected `main@0b07244` publishes deliberate-memory governance
for Ghost through PR #233.** The exact source head `f8a1486` passed all seven
hosted jobs in runs `32931607726` and `32931607783`. The public boundary now
records explicit admit/reject/review decisions, persists only admitted turns,
isolates principal/workspace/project/thread state, exposes current/history
views with lifecycle status, and corrects caller-owned memory additively with a
`supersedes` relation plus canonical soft deletion. This changes no Track S
stage and makes no memory-quality, package-release, or hosted-deployment claim.

**2026-08-25 — protected `main@9d29c24` publishes the opaque public agent-turn
lifecycle for Ghost through PR #231 without distributing private SEAM code.**
The exact source head `40562b3` passed all seven hosted jobs before merge.
Focused HTTP tests cover accepted completion and recall, rejected-turn
non-ingest, cross-principal and cross-session handle isolation, terminal replay
idempotency, and refusal of post-terminal action writes. This source
publication does not alter Track S stage and is not a hosted-deployment or
public-runtime-release claim.

**2026-08-25 — protected `main@bb156e3` contains finished Track S S7 through
merged PR #226, the chronological S8-next handoff through merged PR #227, and
the S8 retrieval-coherence mechanism slice through merged PR #228.** S7 closes the
exit mechanics for exact entity mention evidence,
same-boundary and explicit identity reconciliation, deterministic temporal
reconciliation, concurrent replay idempotency, fail-closed REL traversal, and
as-of graph intervals. A provider-free retrieved-ENT fixture resolved 5/5
entities through complete exact SPAN-to-RAW chains. The chronological
S8-next handoff reached protected main before implementation began. The
published S8 mechanism work closes fail-closed fusion leg names over the exact set
the engine emits (including `chroma`), legacy-policy adapter isolation,
persisted absent/all-one/zero/non-unit weighted-policy replay with all-one
bitwise identical to `/2`, `search_ir`/REST candidate parity with direct
`retrieve()` under the same policy across REST, SDK, MCP, and the TUI read
path, exactly one tenant-scoped retrieval event
per successful retrieval with telemetry failure proven answer-inert, an
explicit process-lifetime flag-cache refresh contract, and SQLite
999-variable-floor bounds on three graph-traversal statements. It does NOT
complete S8: the boundary-only SQL gate decision remains, and `search_ir`
still defaults to `legacy-weighted/1` because retiring
it would change every recorded LoCoMo/mem0 arm — an S9-gated measurement
decision, not an S8 refactor. Nothing here authorizes S9 or claims a
quality lift. The governing reports are:

- `docs/audits/2026-08-18-track-s-deployment-readiness-audit.md`;
- `docs/audits/2026-08-18-graph-benchmark-readiness-research.md`; and
- `docs/audits/2026-08-19-track-s-s6-principal-tenancy-threat-model.md`; and
- the current handoff in `docs/handoffs/INDEX.md`.

Track S is not complete. S0-S6 are published through PRs #190, #191, #193,
#194, #195, #199, and #223, and PR #222 landed the later S1/S5 counterexample
repairs. S6's exact source head `fbefb81` passed the three required checks after
185 focused strict-no-skip tests and three review-repair cycles; its final
Codex review found no major issue before merge. PR #224's structured issue
forms and guarded private GitHub Release workflows are now protected-main fact,
not another Track S stage. Live verification found only existing issue #212
open and no milestones; the forms establish intake, not a populated backlog.
The repository has the admin-controlled `PRIVATE_RELEASE_APPROVER` variable,
and no new issue, milestone, tag, release, or deployment was created during
setup.
The historical native LoCoMo ENT measurement remains 0.0000. Native corpus
freeze/review, scorer eligibility, and promotion remain S9 work; the 5/5 S7
conformance fixture is not a production-corpus or quality-lift claim.
S8-S10 stay dependency-ordered:

```text
S6 principal tenancy published
  -> S7 admissible semantic graph (published, PR #226)
  -> S8 one coherent retrieval engine (next)
  -> S9 matched multi-benchmark qualification
  -> S10 required CI, release, and deployment proof
```

PR #222 closed the bounded, non-design findings that could be reproduced
safely: capped server `/chat` provider responses (2026-08-12
audit F-5), create-only REST `/persist` collisions (audit F-6), deleted-record
vector-outbox replay (audit F-10), deterministic SQL-leg ties (audit F-11),
zero-confidence activation leakage, duplicate
OpenAPI operation IDs, disposable LoCoMo adapter state, and linked-worktree
pre-push misclassification. These are protected-main facts at `a177852`;
internal runtime/store persistence deliberately remains an upsert.

Those hyphenated IDs belong to the 2026-08-12 full-repository audit, not the
campaign's activation-time F1-F22 matrix.

Current graph evidence proves structure, provenance machinery, and parity, not
a graph-caused quality advantage. The matched 1,542-case LoCoMo graph/non-graph
arms tie at `0.776048` because the snapshot has zero admissible semantic
relations; WANDR and G7/R6 are saturated parity lanes with zero graph-
incremental hits. A top-level claim therefore requires the causal portfolio in
the graph-readiness report, not another unsupported headline score.

The Textual TUI is a real seven-tab, runtime-backed local operator surface, but
the target Review/Curate/Health workflow is incomplete. The operator-authored
source was located at `/media/terrabyte/External2/SEAM TUI Concept.dc.html` and
audited as a visual mock/prototype, not a runnable replacement. A separate
`feat/tui-concept-shell` candidate is porting that concept; neither it nor the
external source is shipped behavior.
The served WebUI is a prototype that mixes live API calls with simulated
success, mock persistence, browser-stored credentials, and fabricated metrics.
It is not a beta operator surface and should be made truthful and secure before
a visual restyle.

Hosted deployment remains blocked on S8-S10 qualification and a production
topology that proves TLS, shared rate limiting, service supervision,
backup/restore, and disaster recovery. Trusted-loopback single-user use remains
the deployment boundary unless S6 principal mode is explicitly configured; its
legacy token-only mode is likewise trusted and does not provide tenancy.

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
