# Track S, Operator Surface, and Deployment Readiness Audit

**Status:** audit complete; bounded repairs implemented on a draft candidate

**Date:** 2026-08-18

**Committed baseline:** `main@48c5448157711f6db74f4c24be06b9c563aef5c6`

**Candidate branch:** `audit/track-s-deployment-20260818`

## Verdict

SEAM is not at S10 and is not ready to be described as a hosted beta. The
truthful boundary is:

- S0-S5 are published.
- S6-S10 are open and dependency-ordered.
- the Textual TUI is a functional local operator surface with unfinished
  Review, Curate, Health, and scope workflows;
- the served WebUI is a mixed live/simulated prototype, not a trustworthy
  operator beta;
- graph implementation is broad, but current measurements do not establish a
  graph-caused competitive advantage; and
- trusted-loopback, single-user operation is viable, while a production hosted
  deployment remains blocked by tenancy and operations work.

This audit also found and repaired a bounded set of correctness defects that do
not require new product decisions. Those repairs are candidate state, not
protected-main fact, until the associated PR merges.

## Reconciled live state

The audit began by separating repository identities and uncommitted work:

- protected `main` and `origin/main` were both
  `48c5448157711f6db74f4c24be06b9c563aef5c6`;
- the operator's primary checkout was on the separate draft research branch
  for PR #221, with its ignored/untracked `AppDir/`, `squashfs-root/`,
  installed skills, and skill lock preserved;
- PR #221 was clean and green at the audit cutoff, while older PRs #207 and
  #213 had base conflicts;
- the implementation work was isolated in its own linked worktree from
  `origin/main`; and
- the latest local snapshot verified before the audit. It is an ignored local
  continuity artifact, not a committed repository file.

This report describes the committed baseline and names branch-local fixes
explicitly. It does not treat sibling repositories, ignored application
artifacts, or another draft PR's history entry as part of this candidate.

## Track S stage audit

The campaign dependency contract is linear from S6 onward
(`docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md:106-125`), and a stage is complete
only when every exit clause has evidence
(`docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md:527-528`).

| stage | committed-baseline status | exact boundary |
| --- | --- | --- |
| S0 | **published** | PR #190, `main@778de2c`; canonical baseline |
| S1 | **published, later counterexample repaired on candidate** | PR #191, `main@ebbf2f3`; immediate fail-closed guardrails |
| S2 | **published** | PR #193, `main@6b7c22d`; migration spine |
| S3 | **published** | PR #194, `main@9bd40cb`; projection migration |
| S4 | **published** | PR #195, `main@ea4e46e`; typed references and canonical rebuild |
| S5 | **published, later counterexample repaired on candidate** | PR #199, `main@19b3a76`; snapshot/outbox/vector guarantees |
| S6 | **not started as a stage** | optional in-process principal is decided, but principal binding and opaque `/v1` deletion are absent |
| S7 | **not started** | semantic ingest is scorer-ineligible; entity evidence still has strict compiler xfails |
| S8 | **not started** | one-engine substrate exists, but policy, fusion, surface, and event parity are not qualified |
| S9 | **not started** | the pre-stage 1,542-case LoCoMo result is not post-S7/S8 graph qualification |
| S10 | **not started** | release tooling is partial; the complete evidence bundle and required long gate do not exist |

S6's settled in-process principal contract and two-principal exit matrix are at
`docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md:348-403`. S7-S10 and their exact
exit clauses are at
`docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md:405-509`.

### **A-1 — HIGH · S6 is the hosted deployment boundary**

`public_api.remember`, `recall`, and `context` accept caller-supplied
namespace/session data without a bound principal
(`seam_runtime/public_api.py:104-180`). The HTTP regression suite records that
one bearer token can cross namespaces
(`tests/audit/test_public_api_v1_http.py:315-344`).

**Consequence:** a reverse proxy, styling pass, or stronger shared token cannot
turn the current `/v1` surface into a multi-tenant hosted API. S6 must land
first.

### **A-2 — MEDIUM · S7 graph construction is not admissible evidence**

The current relation lane has 27 relations over 419 turns and remains
scorer-ineligible; retrieved entity provenance is `0.0000`
(`docs/status/retrieval.md:46-63`). The campaign requires exact evidence,
temporal reconciliation, separable same-name entities, and complete entity
source coverage before S7 exits
(`docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md:405-422`).

**Consequence:** more graph retrieval machinery cannot substitute for proving
that the graph being built is correct.

### **A-3 — MEDIUM · S8 has implementation without one coherent contract**

The active retrieval stream records unresolved policy persistence, literal
surface defaults, unvalidated leg weights, and missing surface/event parity
(`docs/status/retrieval.md:14-27,71-89`). The committed SQL leg also used
mutable update time to break equal-score ties, contrary to the fixed RRF/2
contract; the candidate changes the terminal order to record id
(`seam_runtime/retrieval_orchestrator/adapters.py:1467-1474`).

**Consequence:** a good score from one entrypoint is not yet proof that REST,
MCP, SDK, TUI, and direct runtime retrieval mean the same thing.

### **A-4 — MEDIUM · current S9 evidence is LoCoMo-only and graph-inert**

On the matched 1,542-case run, `hybrid`, `mix`, and
`mix + graph=0` all scored `0.776048`; the snapshot contained no admissible
semantic relation edges (`docs/status/retrieval.md:29-52`). WANDR is a
saturated parity lane (`docs/status/benchmarks.md:19-37`), and G7/R6 records
zero graph-incremental hits
(`docs/roadmap/GRAPH_MEMORY_MATURITY.md:109-139`).

**Consequence:** current evidence supports “implemented and auditable,” not
“top-level graph performance.” The companion report
`docs/audits/2026-08-18-graph-benchmark-readiness-research.md:13-283`
defines the minimum six-lane causal program, K0-K6/R0-R4 arms, artifacts, and
claim tiers. No benchmark, comparator, provider, or paid service was run during
that research.

### **A-5 — MEDIUM · the TUI is functional but not the full operator loop**

The live Textual app declares seven tabs
(`seam_runtime/tui/app.py:60-68`) and composes real runtime-backed panels
(`seam_runtime/tui/app.py:371-395`). The target is eight operator tasks:
Memory, Recall, Review, Curate, Health, Engine, Chat, and Settings
(`docs/roadmap/TUI_OPERATOR_SURFACE.md:29-44`). Namespace/scope selection,
context-pack preview, review, deletion/recovery, and health/repair remain
ordered roadmap slices
(`docs/roadmap/TUI_OPERATOR_SURFACE.md:205-344`).

The operator's newer TUI source was not found in any active checkout, the
installed `seam-tui` entrypoint, `AppDir/`, or `squashfs-root/`.
`AppDir/` and `squashfs-root/` contain OpenToonz desktop material, not SEAM
TUI code. No TUI visual or source integration was attempted.

The remaining TUI provider security blockers are shared host policy and
response-cap parity:
`SeamChatClient` accepts its base URL and sends the bearer credential directly
and buffers `response.json()` without the server's allocation bound
(`seam_runtime/dashboard.py:256-325`). The prior audit's statement that
httpx follows redirects by default was false for the pinned client; the missing
host allowlist and missing cap remain real.

### **A-6 — HIGH · the WebUI is not an operator beta**

The single-file WebUI currently presents simulated or browser-local behavior as
live operator success:

- provider credentials persist in browser `localStorage` while the UI claims
  encrypted key-file handling
  (`seam_runtime/webui/dashboard.html:753-920`);
- restart actions are timers that report completion
  (`seam_runtime/webui/dashboard.html:1341-1407`);
- benchmark values and PASS results are randomized
  (`seam_runtime/webui/dashboard.html:3254-3291`);
- unsupported GPU/network metrics are synthesized
  (`seam_runtime/webui/dashboard.html:4621-4649`);
- disconnected memory views fall back to mock records and simulated persisted
  writes (`seam_runtime/webui/dashboard.html:5342-5413`);
- editor Save mutates only browser state
  (`seam_runtime/webui/dashboard.html:6020-6047`); and
- generic SEAM and shell commands report success without execution
  (`seam_runtime/webui/dashboard.html:6263-6277`).

It also depends on CDN development React/Babel at runtime
(`seam_runtime/webui/dashboard.html:8-14`).

**Consequence:** the next WebUI slice is not a style refresh. It is a
truthfulness, credential, backend-contract, and testability pass. Visual design
starts only after those behaviors are real or explicitly labelled demo-only.

### **A-7 — HIGH · no production deployment topology is qualified**

The server explicitly leaves TLS and shared rate limiting to deployment
infrastructure (`seam_runtime/server.py:1620-1639`). The active repository has
no tested container/reverse-proxy, service-manager, automated backup/restore, or
cloud deployment manifest. The private package workflow builds and smoke-tests
artifacts; it is not a hosted deployment system
(`.github/workflows/package-release.yml:46-93`).

**Consequence:** “ready to deploy” currently means local, operator-controlled
trusted-loopback use. Hosted beta additionally requires S6, a real service
topology, backup/restore drill, secrets policy, TLS, health/readiness, and
rollback evidence.

## Bounded repairs implemented now

These fixes were reproduced, covered with regression tests, and kept inside
existing contracts:

The hyphenated F-IDs in this section belong to the 2026-08-12
full-repository audit. They are not the Track S campaign's activation-time
F1-F22 identifiers.

1. **2026-08-12 audit F-5 — server provider response cap.** Both OpenAI-compatible and Anthropic
   server paths enforce `SEAM_CHAT_MAX_RESPONSE_BYTES`, reject oversized
   Content-Length before reading, and cap undeclared bodies. Buffered `/chat`
   returns 502; `/chat/stream` emits a sanitized terminal failure event after
   its SSE response has begun. Neither path persists the failed turn
   (`seam_runtime/server.py:203-240,540-567`;
   `seam_runtime/server.py:1559-1569`;
   `tests/audit/test_chat_endpoint.py:261-400`).
2. **2026-08-12 audit F-6 — create-only REST persistence.** `/persist` requests now reject any
   existing canonical id under `BEGIN IMMEDIATE` and return content-free 409;
   the pooled connection rolls back before reuse, and internal runtime/store
   callers remain upsert-capable
   (`seam_runtime/server.py:1157-1172`;
   `seam_runtime/storage.py:1005-1020,1202-1234`;
   `tests/audit/test_rest_persist_create_only.py:1-68`).
3. **2026-08-12 audit F-10 — deleted outbox replay.** Reopen acknowledges pending intents for
   `deleted_soft` records without reindexing them
   (`seam_runtime/runtime.py:472-500`;
   `tests/audit/test_vector_outbox_durability.py:371-419`).
4. **2026-08-12 audit F-11 — deterministic SQL truncation.** Equal raw scores terminate by
   canonical record id; a metadata-only rewrite cannot change budgeted
   membership
   (`seam_runtime/retrieval_orchestrator/adapters.py:1467-1474`;
   `tests/audit/test_retrieval_fingerprint_consistency.py:212-240`).
5. **Zero-confidence graph edges.** A numeric zero no longer defaults to full
   confidence or propagates a zero-activation node
   (`seam_runtime/workspace.py:610-620`;
   `tests/audit/test_workspace_jspace.py:602-624`).
6. **OpenAPI identity.** GET and HEAD health routes retain both documented
   methods, preserve the existing GET client IDs, and give HEAD distinct IDs
   (`seam_runtime/server.py:731-762`;
   `tests/audit/test_server_bind_safety.py:162-183`).
7. **Disposable LoCoMo state and factory lifecycle.** The adapter uses a
   temporary directory unless the operator supplies `--db-path` or explicitly
   requests `--keep-db`; parallel runners deterministically close every
   factory-owned adapter on serial, worker, success, and failure paths
   (`benchmarks/external/locomo/adapters/seam.py:110-130,216-222`;
   `benchmarks/external/common/runner.py:18-25,96-141,245-299`;
   `test_seam_all/test_locomo_judge.py:327-393`). The replay audit also closes
   its internally owned adapter
   (`benchmarks/external/locomo/audit.py:300-323`;
   `tests/audit/test_locomo_failure_audit.py:105-131`).
8. **Linked-worktree push hygiene.** The pre-push gate now identifies the real
   primary worktree instead of treating whichever linked checkout initiated a
   push as primary (`tools/git-hooks/pre-push:115-136`;
   `tests/audit/test_public_safe_gate.py:286-307`).
9. **Documentation drift.** S0-S2 campaign paragraphs now name their published
   PRs and protected-main commits
   (`docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md:127-215`).

The active-code incomplete-marker scan found no other genuine Track S stub.
Remaining `pass`, `NotImplementedError`, judge stubs, and skip markers are
exception types, parsing fallbacks, supported-target refusals, test doubles, or
explicit optional/external lanes. The one genuine TODO was the LoCoMo default
database path and is repaired above.

## Remaining work: dependency-aware to-do

### 0. Land and reconcile the audit candidate

- Review and merge the bounded repair PR.
- Rebase whichever of this candidate or draft PR #221 lands second; both were
  independently based on `main@48c5448` and append the next history entry.
- Refresh `docs/status/workspace.md`, exact-head CI, and branch mergeability
  after merge. Do not mix or delete the operator's ignored artifacts.

### 1. Close the pre-S6 security and gate backlog

- Extract dependency-light provider host and response-allocation policies
  shared by REST and `SeamChatClient`; refuse an unallowlisted host before the
  TUI sends any key and cap its response before JSON buffering.
- Make local pre-commit, preflight, and closeout gates cover CI's full
  repo-hygiene contract: diff hygiene, whole-repo Ruff, and dependency
  contract, with a structural parity test. This changes commit-time tooling and
  should be its own reviewable slice.
- Decide F-14 dispute-evidence policy and F-15 reasoning-pattern disagreement
  behavior before patching either.

### 2. Finish S6 principal tenancy

- Add the optional principal to public API and server dependencies.
- Derive internal namespaces from the principal; never accept a cross-principal
  namespace replay.
- Expose idempotent opaque delete over the existing lifecycle engine.
- Prove two-principal read/write/search/context/delete denial, no tenant-prefix
  leaks, immediate retrieval exclusion, recoverable cleanup, and immutable
  audit.

### 3. Finish S7 admissible semantic memory

- Freeze and independently review the native relation/entity corpus.
- Meet or exceed the current 50-label relation admission floor with predicate
  diversity and adversarial aliases/coreference.
- Make every admitted relation SPAN-to-RAW provable.
- Bring retrieved entity provenance to complete exact source coverage.
- Prove temporal update, contradiction, expiry, deletion, concurrency,
  idempotency, and same-name separation.

### 4. Finish S8 one retrieval engine

- Resolve applied retrieval policy once and consume it from runtime, MCP, SDK,
  REST, TUI, and benchmarks.
- Remove or explicitly qualify the process-lifetime flag cache.
- Bound all large graph/retrieval `IN` queries for the 999-variable floor.
- Decide and test the boundary-only SQL gate and legacy-versus-RRF retirement.
- Fail closed on unknown weighted-fusion legs; prove absent/all-one/zero/non-unit
  replay.
- Prove exact candidate ID/order parity and exactly one tenant-scoped retrieval
  event across every shipped surface.

### 5. Execute S9 as a benchmark program, not one score

- Pass the native graph-conformance gate first.
- Implement the six claim-critical lanes from the companion report:
  GraphRAG-Bench, STaRK, Memora/FAMA, LongMemEval-V2, MemoryArena, plus native
  conformance; use BEAM-1M as the scale companion.
- Run matched K0-K6 and R0-R4 arms with the same model, reader, prompts,
  budgets, dataset split, and evaluator.
- Publish per-case artifacts, graph-incremental evidence, latency, memory,
  tokens/cost, code/data hashes, and paired uncertainty—not just aggregates.
- Keep LoCoMo's full-corpus floor and category non-regression as a memory lane,
  not the sole graph claim.
- Require an independent reproduction before public “top-level” wording.

### 6. Make the operator surfaces beta-truthful

- Obtain the operator's newer TUI source path or archive and integrate it in a
  separate visual branch.
- Complete TUI scope, Recall pack preview, Review, Curate/delete/recovery,
  Health/repair, and Settings restart semantics.
- Add a WebUI truthfulness suite: no credential persistence in
  `localStorage`, no success without a backend acknowledgement, no mock data
  presented as live, and explicit unavailable/error states.
- Replace CDN development/runtime compilation with a pinned production build or
  a deliberately dependency-free surface.
- Only then hold the WebUI design session, implement the new style, and capture
  fresh desktop and mobile renders for operator approval.

### 7. Finish S10 and deployment proof

- Run strict non-external and live-pgvector suites on the exact release head.
- Build wheel/sdist in a clean environment and rerun package privacy,
  installation, migration, tenancy, retrieval, and opaque-boundary proofs.
- Make the long benchmark/test gate required only after it is current and
  stable.
- Build a real deployment reference: TLS/reverse proxy, service supervision,
  shared limiting, external secret injection, backup/restore, health/readiness,
  logging/metrics, upgrade/rollback, and disaster-recovery drill.
- Re-run secret/session scan, independent review, history/index/snapshot,
  handoff, integrity, routing, streams, wiki, and release gates on that exact
  head.
- Keep publication and production cutover under separate operator approval.

## Threat-model delta

### Changed entrypoints and boundaries

- Server `POST /chat`: outbound provider replies now cross a bounded
  allocation boundary before JSON decoding or memory persistence.
- Private REST `POST /persist`: the HTTP boundary is create-only, while direct
  runtime/store persistence remains an internal upsert.
- Vector-outbox reopen: canonical lifecycle status now wins over an older index
  intent.
- Benchmark factory/replay runners: internally owned adapters and temporary
  databases are deterministically closed.

No schema version, public `/v1` response, principal boundary, model prompt, or
operator-approval rule changes in this candidate.

### Assets and attacker-controlled fields

- Provider JSON bytes and `Content-Length` are remote-provider controlled.
- MIRL record IDs and record bodies at `/persist` are request-caller
  controlled: bearer-authenticated when `SEAM_API_TOKEN` is configured, and
  trusted-loopback otherwise.
- Vector outbox entry IDs are internal; canonical record lifecycle status is
  authoritative.
- Benchmark dataset paths and `--db-path` remain operator controlled.

### Abuse and partial-failure cases

1. A provider declares or streams an oversized body to exhaust memory and
   induce persistence of attacker-sized text.
2. An HTTP caller (a bearer-token holder when authentication is configured)
   reuses a discovered canonical ID to replace same-kind content or provenance.
3. Persist/index failure is followed by soft delete and restart, leaving a stale
   intent that attempts to resurrect derived content.
4. A benchmark worker or replay raises while owning open SQLite handles, making
   temporary cleanup platform- and GC-dependent.

Malformed/missing Content-Length falls through to the hard read cap. A REST ID
collision is checked under `BEGIN IMMEDIATE`, returns content-free 409, and
does not touch vector state. A missing or `deleted_soft` outbox target is
acknowledged without indexing. Factory-owned adapters close in `finally` on
both serial and worker paths.

### Controls and verification

| threat | preventive control | recovery/detection | verification |
| --- | --- | --- | --- |
| provider allocation exhaustion | 5,000,000-byte default, configurable minimum 1; precheck plus bounded read | content-free 502 for `/chat`; sanitized terminal failure for SSE; failed reply not compiled/persisted | both provider schemas, declared and undeclared length, plus streaming failure |
| canonical overwrite over REST | create-only collision check under SQLite write lock; rollback on failure | content-free 409; original canonical bytes remain | first create succeeds, collision fails, original is byte-identical, independent writer is not locked |
| deleted-content reindex | replay filters canonical `deleted_soft` state | stale intent acknowledged; no derived row recreated | persist-fail → delete → reopen regression |
| temporary database/handle leak | runner-owned adapter `finally` close | adapter cleanup owns temp-root removal | grouped/ungrouped, serial/parallel lifecycle tests plus replay-owner test |

### Prompt, secrets, privacy, and residual risk

Retrieved text receives no new action authority. No tool output enters a
privileged instruction channel. Existing server credential resolution and
content-free loopback errors are unchanged; credentials and provider bodies are
not logged or retained as artifacts by these failures.

Residual risk is explicit: TUI `SeamChatClient` still lacks the shared host
policy and response cap; the WebUI still stores credentials and simulates
success; `/v1` still lacks principal binding; external vector backends still
rely on their existing cleanup and operator controls. Those are blockers, not
assumptions hidden by this repair.

## Verification

History review was bounded to the latest verified snapshot, `HISTORY_INDEX.md`,
the cross-index hot zone, and recent topic-routed context packs. The full
`HISTORY.md` was not read or re-audited. Required integrity/continuity tools
mechanically verify the append-only chain at closeout without widening this
report into a historical audit.

Baseline non-external suite, strict no-skip policy, full collection, Python
compilation, and whole-repository Ruff were run before the candidate changes.
The baseline suite had one failure: the pre-push test misclassified the dirty
primary checkout when invoked from a linked worktree. That failure is repaired
with an isolated multi-worktree regression.

Focused regression slices for provider responses, REST persistence, vector
outbox replay, SQL determinism, workspace activation, OpenAPI IDs, LoCoMo
adapter cleanup, and pre-push worktree handling pass on the candidate. Final
full non-external, live-pgvector external, continuity, documentation, secret,
and review results are recorded in the associated HISTORY entry and PR rather
than predicted here.

## Corrections to prior belief

- S0-S2 were already published; their stage paragraphs were stale.
- S5's qualification record did not cover persist-fail → soft-delete → reopen;
  that counterexample was real and is repaired on this candidate.
- httpx does not follow redirects by default in the pinned client. F-16 remains
  a host-allowlist/credential-routing defect, not a redirect-default defect.
- A graph plane can be implemented and auditable while contributing zero
  incremental retrieval evidence. Those are separate claims.
- The WebUI's visual completeness is not beta readiness when operator actions
  can report simulated success.

## Evidence manifest

Raw artifacts: none

No paid benchmark, comparator API, model-provider API, deployment, release, or
publication action was performed. The external benchmark landscape and source
cutoff are recorded in the
[graph benchmark readiness report](2026-08-18-graph-benchmark-readiness-research.md).
