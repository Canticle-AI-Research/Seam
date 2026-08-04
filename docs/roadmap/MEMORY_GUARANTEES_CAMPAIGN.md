# Track S: Production-Core Integrity Campaign

**Status:** in progress
**Activated:** 2026-08-01 via `HISTORY#511`
**Latest evidence:** S4 is published through PR #195 at `main@ea4e46e`,
recorded by `HISTORY#530` and registered by `HISTORY#531`
**Roadmap item:** `roadmap:track:S`
**Execution boundary:** provider-free, local, fail-closed, and evidence-gated
**Publication boundary:** S0-S4 are merged; S5 is the next stage and must be
built on `main@ea4e46e` rather than stacked on an unmerged base

Track S is the production-hardening campaign for SEAM's durable-memory core.
It converts the verified F1-F22 findings below into one dependency-ordered
program with exact exit gates. It coordinates existing work in Track R
(knowledge/reasoning graphs), H2 (improvement evidence), E2 (tenancy), and K14
(contradiction inspection); it does not supersede any of them.

The campaign began from semantic baseline commit `86a81e2`. That commit
integrates fail-closed canonical REL/ENT graph admission, offline embedding
coverage checks, and an explicitly research-only relation-extraction lane. Its
12-module focused scope passed 269/269 tests. The replacement branch then
satisfied S0's broader suite, review, path, security, and continuity gates; see
`HISTORY#513` and the current handoff. S1 then closed the immediate
deterministic-order, retrieval-validation, server-factory,
projection-version, scanner, MCP-version, and dependency-contract guardrails.
`HISTORY#524` closes the discovered `seam doctor` contradiction so an absent
opt-in-only Chroma install is informational rather than a core failure. The
post-S2 audit in `HISTORY#525` exposed a missing forward projection path;
`HISTORY#526` requalified S2 with registered projection transitions, locked
backup ordering, and durable per-step resume; PR #193 published it to protected
`main`. `HISTORY#527` and `HISTORY#528` record the merged second-audit repairs
and corrected handoff. `HISTORY#529` requalifies S3's exact KG/4-to-KG/5
transition on that current ancestry; PR #194 publishes it at `main@9bd40cb`.
`HISTORY#530` requalifies S4's closed typed-reference contract and exact
core-storage/1-to-/2 plus KG/5-to-/6 transitions on that merged S3 base.

## Governing invariants

1. SQLite remains canonical truth. Graphs, vectors, projections, events, and
   PACKs are derived or append-only evidence layers, never substitute truth.
2. Retrieval has one engine. Legacy behavior may remain as a versioned adapter
   inside that engine, but no second live scorer may grow beside it.
3. A recovery, rebuild, migration, or cleanup operation must fail closed and
   leave a newer or unsupported store byte-unchanged.
4. Namespace/scope labels are not principal identity. Authenticated hosted
   paths require an explicit principal boundary before multi-tenant claims.
5. Semantic graph claims require exact SPAN-to-RAW provenance and a qualifying
   corpus. Mechanism tests, zero-row corpus observations, and research-only
   extraction do not establish graph lift.
6. Benchmark promotion is provider-free unless the operator separately
   authorizes spend. Every arm starts from its own clone of one pristine
   ingest-only snapshot.
7. A stage changes status only through auditable evidence in HISTORY, status
   streams, the tracked handoff chain, and the canonical verification gates.

## Verdict vocabulary

- **CONFIRMED:** the finding is present in the current implementation or live
  repository configuration and is routed to a production stage.
- **QUALIFIED:** the core condition is present, but part of the original scope,
  caller count, or corpus interpretation was too broad and is narrowed here.
- **PARTLY STALE:** the original report combined intentional compatibility with
  a real drift item; only the verified drift enters the campaign.

These are audit verdicts, not severity labels and not completion claims.

## Authoritative F1-F22 verdict matrix

| Finding | Verdict | Verified production boundary | Owning stage(s) |
| --- | --- | --- | --- |
| F1 | **CONFIRMED** | Destructive projection rebuild can lose graph-only supersession state. Previously quoted empirical counts are not rerun or republished by this plan. | S3 |
| F2 | **CONFIRMED** | S1 adds deterministic record loading and record-ID tie breaks through the final retrieval boundary, including budget 1. | S1 |
| F3 | **QUALIFIED** | Planner work is wasted on the legacy path and `search_ir()` hardcodes legacy behavior. The earlier “only two callers” count is stale. Promotion remains gated by cat3 and the full S9 result. | S8, S9 |
| F4 | **CONFIRMED** | Caller namespace sits behind one bearer token, not a principal identity. This is critical for a shared hosted topology and topology-dependent otherwise. | S6 |
| F5 | **QUALIFIED** | Default ingest remains relation-free. An explicit compiler/research lane can emit REL, but the measured 27/419 coverage is insufficient and scorer-ineligible. | S7, S9 |
| F6 | **CONFIRMED** | S1 routes real Uvicorn factory startup through the same bind/worker safety contract as normal launch. | S1 |
| F7 | **CONFIRMED** | Canonical database commit precedes derived vector indexing; current compensation is not process-durable. | S5 |
| F8 | **CONFIRMED** | Weighted fusion implemented on the retrieval branch is rejected by reasoned-retrieval policy persistence, while unknown leg names are accepted. | S8 |
| F9 | **QUALIFIED** | Retrieval observation has live event, identity, and semantic gaps. Zero-row counts are corpus observations, not universal runtime guarantees. | S8 |
| F10 | **CONFIRMED** | A colon heuristic can promote arbitrary free text, including timestamp/URL-like values, into record IDs. | S4 |
| F11 | **CONFIRMED** | The orphan sweep does not cover both real reference endpoints. The repair must follow typed record/edge contracts, not widen string-prefix guessing. | S4 |
| F12 | **CONFIRMED** | Reconciliation is explicit-only, leaves loser status unchanged, and ingest does not carry a complete valid-time contract. | S7 |
| F13 | **QUALIFIED** | Scoped SDK soft-delete exists. The opaque remote deletion/retention contract does not. | S6 |
| F14 | **CONFIRMED** | Retrieval adapters open fresh connections, and pgvector performs schema ensure work during search. | S5 |
| F15 | **QUALIFIED** | Entity extraction/provenance remains heuristic and weak. Within-namespace normalized-label canonicalization exists; cross-tenant separation is intentional and must remain. | S7 |
| F16 | **CONFIRMED** | The live branch-protection ruleset requires three short gates but not the full `test-and-benchmark` suite. | S10 |
| F17 | **CONFIRMED** | At activation there was no central schema/migration version governing all durable projections. S2 added the central registry, and HISTORY#526 adds the locally qualified forward transition path; protected-main publication remains pending. | S2 |
| F18 | **CONFIRMED** | S1 rejects non-positive `rrf_k` at flag construction, coercion, and environment loading before fusion. | S1 |
| F19 | **CONFIRMED** | S1 centralizes secret patterns and scans every new commit-range blob, including added-then-deleted content. | S1 |
| F20 | **PARTLY STALE** | `server.json` retains its intentional legacy compatibility value; S1 makes the private MCP handshake report installed package metadata. | S1 |
| F21 | **CONFIRMED** | The reconstruction source branches carried 59 tracked `.ua` files. The clean replacement baseline intentionally omits them. | S0 |
| F22 | **CONFIRMED** | S1 establishes and checks one dependency source/mirror/extra policy; S10 still owns frozen release-artifact and lock/hash evidence. | S1, S10 |

## Dependency order

The stages are not a flat backlog. The execution graph is:

```text
S0 -> S1 -> S2
             |-> S3 -\
             |-> S4 --+-> S7 -\
             `-> S5 -> S6 -----+-> S8 -> S9
S0 through S9 ---------------------------> S10
```

- S3 and S4 may proceed in parallel after S2.
- S5 begins after S2; S6 requires S5's durable outbox/recovery substrate.
- S7 requires S3, S4, and S6 so semantic truth is durable, typed, and tenant
  safe before it becomes retrieval substrate.
- S8 requires S1, S5, S6, and S7. It may not qualify surface parity over
  unstable storage, identity, or semantic inputs.
- S9 requires both S7 and S8. It is the promotion gate, not a debugging lane.
- S10 is the release gate over the completed evidence of S0-S9.

## S0 - Canonical baseline

**Status:** locally qualified on 2026-08-01 via `HISTORY#513`; protected-main
merge evidence remains a repository/PR event, not an additional S0 defect fix.

**Purpose:** establish one clean replacement baseline, preserve the reviewed
semantic integration, and exclude source-branch contamination before defect
repair begins.

**Findings:** F21, and the baseline boundary for all others.
**Dependencies:** none.

**Exit gate (all required):**

- The replacement diff contains no `.ua`, `dist/`, report PNG, private-link,
  accidental, or generated-source files.
- An explicit tree comparison accounts for every difference from the source
  heads.
- The existing full suite and all SEAM integrity/routing/handoff/continuity/
  stream gates are green.
- PR #189's exact-REL, same-boundary, canonical-ENT fail-closed admission is
  retained, and the research relation lane remains `scorer_eligible=false`.
- Review remains bounded to the intentional replacement and semantic baseline.

## S1 - Immediate fail-closed guardrails

**Status:** locally qualified on 2026-08-01 via `HISTORY#520`; doctor dependency
policy corrected via `HISTORY#524`. Protected-main CI and merge remain the
publication boundary.

**Purpose:** remove crash, nondeterminism, unsafe factory, scanner, version, and
dependency hazards before introducing migrations.

**Findings:** F2, F6, F18, F19, F20, and the immediate portion of F22.
**Dependencies:** S0.

**Exit gate (all required):**

- Rewriting an unrelated row and reopening the store cannot change tied result
  order, including at budget 1; non-tied output remains bitwise unchanged.
- Invalid `rrf_k` fails validation and cannot crash fusion.
- Unsafe real Uvicorn factory launches refuse startup through the same safety
  contract as non-factory launches.
- Newer or stale projection versions fail closed without changing table hashes.
- The central scanner detects `sk-proj` and provider session/share URL fixtures,
  including added-then-deleted commit-range content.
- Compatibility metadata remains intentional, while the private MCP handshake
  reports the current package/protocol version.
- Dependency-source drift has a single checked contract suitable for S10.

## S2 - Migration spine

**Status:** locally requalified on 2026-08-02 via `HISTORY#526` after the
post-S2 forward-migration audit finding. Protected-main CI and merge remain the
publication boundary.

**Purpose:** add one central, transactional, recoverable schema/projection
version spine before any durable layout changes.

**Findings:** F17.
**Dependencies:** S1.

**Exit gate (all required):**

- An empty store and every maintained historical database fixture upgrade.
- Failure injected after every migration step rolls the whole step back.
- SQLite `integrity_check` and `foreign_key_check` pass after each supported
  upgrade path.
- A registered projection-version bump upgrades a populated store through an
  explicit transactional callable without losing canonical or projection data;
  an unregistered add, remove, or version change still refuses byte-unchanged.
- Locked revalidation and the same-owner backup precede mutation; competing
  writers remain blocked across every separately committed step in DELETE and
  WAL modes, while an earlier completed step survives a later failure and
  remains resumable.
- An unknown/newer database remains byte-unchanged after refusal.
- Recovery from the pre-migration backup is demonstrated, not assumed.

The audit repairs in `HISTORY#526` are intentionally narrow. Locking entity
reconciliation closes one concurrent identity-fragmentation path but does not
complete S7 extraction, provenance, or reconciliation. Host-bound chat
credential lookup closes arbitrary environment forwarding but does not provide
S6 principal tenancy or automatic token provisioning. Audit findings 7-10 and
12 remain open.

## S3 - Durable supersession and guarded reprojection

**Status:** published through PR #194 at `main@9bd40cb`; local qualification is
recorded by `HISTORY#529` and exact-head required plus advisory CI passed.

**Purpose:** make temporal supersession canonical and ensure graph rebuilds are
non-destructive, atomic, and history-equivalent.

**Findings:** F1.
**Dependencies:** S2.

**Exit gate (all required):**

- A known-good KG/4 store applies exactly one registered `/4 -> /5`
  transition, advances both projection markers to `/5`, preserves current,
  full-history, and point-in-time views, resurrects zero excluded records, and
  retains independently supported live edges.
- The resurrection reproducer reports zero superseded-to-live flips.
- Lifecycle exclusions and both `graph_at` and full-history views are identical
  before and after an explicit rebuild.
- A shared edge remains active when another live episode still supports it.
- A failed rebuild or a rebuild request against a newer schema leaves all
  relevant table hashes unchanged.
- An invalid canonical `document_status` identifier refuses the rebuild,
  preserves all relevant table hashes, and logs only its digest.

The qualified transition derives topology from canonical MIRL, lifecycle
status, and durable `document_status` supersession. It preserves and revalidates
the separate identity-merge judgement ledger; missing judgement tables, an
invalid document identifier, a missing graph marker, or an unsupported source
state refuses without publishing partial topology.

## S4 - Typed references and orphan integrity

**Status:** published through PR #195 at `main@ea4e46e`; local qualification is
recorded by `HISTORY#530` and all eight required plus advisory exact-head
checks passed.

**Purpose:** replace string heuristics with typed MIRL/edge reference contracts
and complete orphan validation.

**Findings:** F10, F11.
**Dependencies:** S2.

**Exit gate (all required):**

- Timestamps, URLs, and arbitrary colon-bearing text remain literals.
- Same-batch and already-stored typed references resolve deterministically.
- Every MIRL kind and both endpoints of every supported edge/reference contract
  participate in orphan checks.
- Deliberate virtual entities are preserved.
- All supported reconciliation pointers and explicit facet positions share the
  same remap, candidate, typed-edge, and graph-projection contract.
- Reserved virtual-reference metadata is validated even when a record has no
  missing endpoint, and malformed metadata is never durable.
- Hard delete cannot leave a surviving required canonical reference; refusal is
  atomic, while deleting every dependent source in the same operation succeeds.
- Reopening and rerunning integrity work is idempotent.
- Whole-message compilation creates zero phantom IDs from colon heuristics.
- A populated `core-storage/1` plus `knowledge-graph/5` store successfully
  applies exactly the `/1 -> /2` and `/5 -> /6` transitions, advances durable
  and component markers together, removes colon-phantom topology and orphan
  vectors, and preserves canonical typed edges.
- Every projected IR edge retains source-record ownership. Rewriting one CLM or
  REL replaces only its own contributions, and a shared edge remains while any
  independent canonical record still supports it.
- Already-current stores fail closed when a canonical payload loses a required
  endpoint or a contributor loses either its canonical source record or its
  derived edge, without modifying database bytes or creating a migration
  backup.
- Canonical migration input is consumed in bounded batches; invalid or
  mismatched private record identifiers roll the step back and surface only a
  digest, never the raw identifier.
- Edge-type conflict validation is set-based and stays below SQLite's legacy
  variable limit; contradictory endpoint types within or across canonical
  batches roll the whole step back.
- When the downstream typed-reference step fails after S3, `/5` remains the
  truthful durable checkpoint and reopen resumes only `/5 -> /6` while
  preserving zero-resurrection semantics.

The qualified implementation persists explicit edge endpoint types and
source-record contributors, validates all closed reference candidates,
preserves declared virtual references, and uses candidate-only chunked lookups,
bounded canonical batches, and 300-triple conflict checks rather than
whole-corpus or per-edge scans.
Fallback RAW-agent attribution is globally ordered and independent of batch
boundaries; ordinary boundary-only writes retain content-hash vector reuse,
while migrations remove orphan graph vectors only after full reprojection and
canonical-state restoration.

## S5 - Vector outbox and connection pooling

**Status:** locally qualified on `agent/track-s-s5-outbox-pooling`; every clause
below has evidence. Exact-head CI and review remain required before publication.
S6-S10 all depend on this stage directly or transitively.

**Purpose:** make derived-index updates process-durable and eliminate search-time
connection/schema churn without changing answers.

**Findings:** F7, F14.
**Dependencies:** S2.

**Exit gate (all required):**

- Crashes before and after canonical commit, vector indexing, and outbox
  acknowledgement converge to the same state after reopen.
- Duplicate replay is harmless.
- SQLite-vector, pgvector, and Chroma divergence is detected and repaired.
- Warm `mix` retrieval opens no new physical SQLite connections; a 40-thread
  stress run remains within the configured pool.
- Every SQLite-backed leg and visibility check in one retrieval request reads
  from one committed snapshot; a concurrent ingest cannot produce a candidate
  set or fingerprint assembled from mutually inconsistent database states.
- Pgvector search performs no DDL or schema ensure operation.
- Ranking, IDs, order, and provenance remain unchanged.

**Local evidence:** `tests/audit/test_read_snapshot_consistency.py` (leg
sharing, same-file vector-index join, mid-request commit isolation, write
guard, re-entry, zero warm connection opens, 40-thread stress within the pool,
unchanged ranking/order/provenance); `test_vector_outbox_durability.py` (each
crash point converging, duplicate replay, idempotence on the real backend,
backend-down retry, reopen safety); `test_vector_divergence_repair.py`
(missing/stale/orphan detected and repaired on SQLite-vector, pgvector, and
Chroma); `test_pgvector_search_no_ddl.py` (provider-free, recording cursor);
`test_retrieval_fingerprint_consistency.py` (candidate set and
`candidate_set_sha256` attest one committed state). The last was verified to
discriminate: with the snapshot disabled it fails.

## S6 - Principal tenancy and opaque deletion

**Purpose:** promote authentication from a shared token gate to principal-bound
authorization and complete the opaque remote delete/retention contract.

**Findings:** F4, F13.
**Dependencies:** S2 and S5.

**Exit gate (all required):**

- A two-principal matrix denies cross-tenant read, write, search, context, and
  delete even under namespace/session replay.
- Authenticated data paths never execute with `ns=None`.
- `/v1` leaks no tenant prefix, MIRL shape, retrieval policy, or graph internals.
- Delete is idempotent, excludes data from retrieval immediately, completes
  derived cleanup through the recoverable outbox, and retains an immutable
  audit record.

## S7 - Semantic ingest, temporal reconciliation, and entities

**Purpose:** admit useful relations only with exact evidence, resolve temporal
truth deterministically, and make entity evidence retrieval-grade.

**Findings:** F5, F12, F15.
**Dependencies:** S3, S4, and S6.

**Exit gate (all required):**

- Every admitted REL carries exact SPAN-to-RAW proof; unknown predicates never
  traverse and no cross-boundary edge can be created.
- Functional versus multivalued predicates and older/newer/equal/missing-time
  cases reconcile correctly.
- Concurrency, idempotency, and as-of retrieval are correct.
- Retrieved ENT evidence reaches 100 percent exact source coverage.
- Multiword names are preserved, stopwords are rejected, and two same-name
  people remain separable.

## S8 - One retrieval engine, coherent fusion, events, and identity

**Purpose:** remove planner/adapter ambiguity, make fusion contracts consistent
across persistence, and ensure every surface observes the same retrieval event
and identity policy.

**Findings:** F3, F8, F9.
**Dependencies:** S1, S5, S6, and S7.

**Exit gate (all required):**

- A legacy-policy plan executes only the legacy adapter.
- Every shipped surface returns the same candidate IDs and order as a direct
  `SeamRuntime.retrieve()` call under the same request.
- Absent, all-1, zero, and non-unit weight configurations replay exactly; all-1
  is bitwise identical to `reciprocal-rank-fusion/2`.
- Misspelled or unknown leg names fail before search.
- Exactly one tenant-scoped event is recorded for each successful enabled
  retrieval, and telemetry failure cannot alter the answer.
- An accepted identity merge is reversible and fully audited.

## S9 - Provider-free retrieval and semantic qualification

**Purpose:** decide promotion with full-corpus, offline, attributable evidence;
keep graph/scorer behavior default-off until semantic substrate qualifies.

**Findings:** promotion boundary for F3, F5, F8, and F9.
**Dependencies:** S7 and S8.

**Exit gate (all required):**

- Build one pristine ingest-only snapshot, clone it independently for every
  arm, pin offline BGE, and prove full embedding coverage.
- The full 1,542-case provider-free LoCoMo gate is at or above
  `0.7664201903042236`, with category-level non-regression.
- Replay/rewrite is deterministic and retained traces identify the actual legs
  that executed.
- A graph-eligible corpus contains at least 30 REL records spanning at least 10
  percent of turns, provenance completeness 1.0, predicate diversity, bounded
  hub concentration, cross-turn paths/motifs, and human-reviewed precision.
- A fresh matched ablation shows attributable graph-only lift. If any graph
  substrate or lift gate fails, graph/scorer behavior remains default-off.

## S10 - Required CI and release gates

**Purpose:** promote only a fully verified candidate and keep publication and
cleanup under separate operator authorization.

**Findings:** F16 and the release portion of F22.
**Dependencies:** all evidence from S0-S9.

**Exit gate (all required):**

- Strict zero-skip non-external suite and live-pgvector external suite pass.
- Focused migration, crash, tenancy, semantic, and retrieval suites pass.
- Clean wheel and sdist pass hermetic installation, privacy, and opaque public-
  boundary proofs.
- Candidate files pass the secret/session scan before CodeRabbit review, and
  all critical findings and warnings are resolved or explicitly rejected with
  evidence.
- History, index, snapshot, handoff, integrity, continuity, routing, and stream
  gates are all green.
- `test-and-benchmark` becomes a required merge check only after its green proof
  is current and stable.
- Publication is separately authorized. Worktree, artifact, or source-branch
  deletion requires explicit approval for the exact target.

## Campaign operating record

Each implementation slice must state its F-ID and stage in the branch/PR,
tests, and HISTORY entry. A slice may fix more than one finding only when they
share the same dependency boundary and exit evidence; otherwise split it.

Every stage handoff must report:

- exact files and durable schema/projection versions changed;
- exact reproduction and test commands, including failures and skipped scope;
- invariant checks for byte/hash preservation and tenant boundaries;
- benchmark corpus, snapshot, arm-cloning, offline/provider, and attribution
  boundaries when measurement is involved;
- which exit-gate clauses passed, which remain open, and the next dependency;
- candidate secret/session scan scope and canonical history/snapshot gates.

No stage is complete merely because implementation exists or focused tests are
green. Completion means every exact exit clause above has current evidence.
