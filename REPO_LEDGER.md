# SEAM Repo Ledger

Last updated: 2026-08-22

This ledger is the stable engineering memory for repo-level decisions only.
Detailed session history, milestones, and plan transitions now live in `HISTORY.md`
and `HISTORY_INDEX.md`.

## Startup Read Order

1. `PROJECT_STATUS.md` (current state)
2. `AGENTS.md` (cross-agent protocol)
3. `HISTORY_INDEX.md` (history map)
4. `HISTORY.md` only by surgical read using indexed line/byte ranges

## Project Identity

- `SEAM`: runtime/tool identity
- `MIRL`: canonical memory IR
- `PACK`: derived prompt-time context representation
- `SEAM-LX/1`: exact machine-text envelope for lossless workflows
- `SEAM-HS/1`: lossless PNG-backed Holographic Surface for visual memory snapshots

## Stable Decisions

- **The SEAM spec is the governing contract.** `SEAM_SPEC_V0.1.md` (the four-layer
  RAW/IR/PACK/LENS model, the north star "maximum durable intelligence per token",
  the loss model RAW=phrasing/IR=meaning/PACK=utility, the NL<->IR<->PACK<->NL
  translation directions, the symbol-table improvement loop, and the compression
  metrics `cr/rr/sr/pr/tr/qr` with the §24 "denser only when recovery is proven"
  promotion rule) together with `docs/MIRL_V1.md` (the Readable Lossless
  Compression Contract, MIRL record kinds/fields, RC/1, HS/1, the PACK
  Exact/Context/Narrative contracts) define what SEAM IS. Every change to SEAM
  product behavior is measured against them. Agents MUST read the spec before
  redesigning, "improving", or declaring a component broken (AGENTS.md Session
  Start item 6). A component is only "broken" if it fails the contract it is
  actually supposed to satisfy — e.g. RC/1's contract is lossless + directly
  queryable + exact rebuild (NOT token reduction; token reduction lives in PACK,
  the symbol loop, and the Track J codec); the former overfit `compile_nl` stub
  genuinely violated the §3.2 compiler responsibilities + §8 recoverable-meaning
  contract (fixed by the HISTORY#308 deterministic floor and unified into one
  faithful pipeline at #311; the rich S-P-O extractor is Stage 4). New fidelity
  or metric harnesses align to the spec's own metrics (§22/§24), not invented
  ad-hoc properties. This decision exists because the spec was historically
  absent from the mandatory read order, which let implementations drift from the
  design (the overfit `compile_nl` stub being the clearest case).
- `Canticle-AI-Research/Seam` is the canonical proprietary private development
  repository. The locally configured legacy URL `BlackhatShiftey/Seam`
  currently redirects to that organization repository; treat the two owner
  strings as one repository identity, not two publication targets. MIRL's
  authored specification, source, schemas as expressed,
  documentation, examples, tests, diagrams, and related implementation
  material are copyrighted Reserved Materials under `LICENSE`. HS/1's authored
  specification, container expression, visual designs, codecs, surface
  library, source, docs, tests, and related implementation material are
  separately named copyrighted Reserved Materials under the same terms.
- The SEAM Distributed Runtime, version 2.4.0 or later, is published under the
  Business Source License 1.1 as of 2026-07-27 (`LICENSE` v2.1 §7A, parameters
  in `LICENSES/BUSL-1.1.txt`). Change Date is four years per published version;
  Change License is MPL 2.0. The Additional Use Grant permits free self-hosting
  at any scale, including internal commercial production use, plus
  non-commercial research, education, and publication of benchmark results; it
  withholds offering the runtime to third parties on a hosted or embedded basis
  as a paid competitive offering. Membership in the Distributed Runtime is
  decided by publication plus a conspicuous per-file BUSL notice, never by path
  — a shared filename, purpose, interface, or ancestry grants nothing.
  Publishing one version waives nothing in unpublished versions and creates no
  obligation to publish any future version.
- `BlackhatShiftey/Seam_Runtime` is a frozen legacy Apache-2.0 release. Exact
  versions already published there retain Apache-2.0 and cannot be clawed
  back; later private versions and new MIRL or HS/1 material do not inherit that
  license. Its public `main` head at the freeze was
  `0f4b40aab7fda643ce776e597f0b430faa465ca8`. The required Apache text is
  preserved at `LICENSES/Apache-2.0.txt` for unchanged legacy material
  incorporated into later private distributions.
- The private-to-public mirror is gone, not merely disabled: `sync_public_mirror.py`
  was removed with the rest of the split tooling. `verify_public_safe.py` and its
  `public_manifest.py` path classifier are RETAINED as a secret and
  reserved-material push gate — kept because a `seam.db` snapshot once leaked into
  another repository's history (HISTORY#344), independent of any distribution
  model. The pre-push hook still refuses the legacy public remote. Any future
  public client/SDK is a separate ground-up artifact with its own boundary,
  license review, and written owner approval; do not reconstruct the old mirror.
- The operator-approved public integration surface is the separately authored
  Apache-2.0 `seam-client` package under `BlackhatShiftey/Seam_Runtime/sdk`.
  It may contain HTTP transport, typed public models, sync/async clients, and
  framework-neutral agent-memory hooks. It must not import, package, copy, or
  expose private runtime modules, MIRL/HS/1 implementation, storage, retrieval,
  graph, PACK, surface, or benchmark internals.
- The stable protected-main public server boundary is `/v1/health`,
  `/v1/memories`, `/v1/memories/recall`, and `/v1/context`. Public stateful
  calls use the existing bearer-token guard. Public namespaces are mapped
  under an SDK-only prefix with optional hashed session partitions, and
  responses use opaque receipts/IDs plus user-facing text rather than private
  record shapes. Published Track S S6 adds
  `/v1/memories/delete` and an optional in-process principal resolver. In
  principal mode, the subject derives the internal tenant/namespace boundary
  and legacy private data routes return 404; token-only mode remains a trusted
  single-user gate and is not tenancy.
- Private contributions use the proprietary contribution grant in
  `LICENSE`/`CONTRIBUTING.md` unless a separate signed agreement controls.
- SINGLE PACKAGE POLICY. `seam-runtime` (root `pyproject.toml`) is the ONLY
  package definition in this repository. It is the full private runtime with
  readable MIRL and HS/1 source, used to operate the hosted service on
  operator-controlled infrastructure. It is not distributed. It must retain the
  `Private :: Do Not Upload` classifier as the tripwire against an accidental
  PyPI upload of a full-MIRL runtime.
- The retrofitted distribution split is RETIRED. The compiled `seam-self-host`
  package, the API-only `public_pkg/` shim, `selfhost/`, their build and verify
  tooling, the self-host release workflow, and the boundary audit suite were all
  removed. A public edition will be built separately, from the ground up, with
  separation as an architectural property rather than a boundary retrofitted
  onto a codebase that was not designed for it. `LICENSES/BUSL-1.1.txt` is
  already parameterized for that future edition (Licensor, Licensed Work 2.4.0+,
  self-hosting permitted, competing hosted resale withheld, four-year Change
  Date to MPL 2.0) and is retained unused until then.
- Artifacts already published are unaffected and stay live: `seam-self-host`
  1.1.2 and Apache-2.0 `seam-client` 2.0.0 on PyPI, and legacy Apache-2.0
  `seam-runtime` 1.3.1 (yanked, deliberately retained as a rollback point).
  Removing the in-tree tooling does not unpublish them; it means no further
  releases of them are produced from this repository.
- GitHub Issues are the coordination intake, not a replacement for SEAM's
  status/history authorities. Blank issues are disabled. Structured forms own
  bugs, features, research/benchmark tasks, and private-runtime release
  proposals; sensitive security findings route to private advisories. Issue
  closure, labels, and milestones do not by themselves prove implementation,
  qualification, publication, or deployment.
- `.github/workflows/package-release.yml` is RETAINED and is the only remaining
  release path: serialized manual dispatch is restricted to the default branch
  and an exact new SemVer already present in `pyproject.toml`; it builds exactly
  one private `seam-runtime` wheel and sdist, rejects unsafe members and
  secret-shaped packaged content, smoke-tests the installed commands, emits and
  verifies `SHA256SUMS.txt`, and creates a private GitHub Release draft with
  categorized generated notes. After environment approval it revalidates
  the live protected head immediately before atomically reserving the exact tag,
  uploads assets into the draft, and leaves publication to the separate
  environment-gated `publish-private-release.yml` follow-up after an operator
  reviews the generated notes for private data and unsupported claims. The
  follow-up runs only on a fresh first attempt whose original and triggering
  actors both match the account named by the repository
  `PRIVATE_RELEASE_APPROVER` Actions variable, requires that target to remain
  the current protected-main head, and binds the reviewed draft byte-for-byte
  to the immutable artifact from the named successful preparation run. It
  rechecks the lightweight tag, reviewed manifest and notes digests, exact
  checksum coverage, downloaded artifact name/version metadata and content,
  archive member paths and the complete decompressed sdist stream, exact
  release title, text secret scan, unchanged draft fingerprint, and live
  protected head immediately before publication. The operator must attest the
  live repository immutability setting, and the follow-up verifies the
  published release's immutable flag or removes the mutable release/tag. A
  failed attempt removes only its exact unpublished draft/tag, while ambiguous
  or already-published state is left for operator review. Prerelease SemVer is
  marked as a GitHub prerelease. It has no PyPI target, public publish step, or
  `id-token` permission. Private 2.4.0 is live as GitHub release `v2.4.0`,
  pinned to protected-main merge
  `01f35817810f1490c88e9f832d92c8f1aab3944d`; its downloaded wheel and sdist
  passed clean installation, SQLite, and live-pgvector API proofs.
- The compiled `seam-self-host` distribution is RETIRED. Published 1.1.2 stays
  live on PyPI and keeps working; removing the in-tree tooling means no further
  releases are produced from this repository. Its package definition, Docker
  builder, content ratchet, and boundary proofs were removed with the rest of
  the retrofitted split. Do not reconstruct them here — a public edition is a
  separate ground-up build with separation designed in.
- Apache-2.0 `seam-client` 2.0.0 is live at
  `https://pypi.org/project/seam-client/`. It was published from reviewed
  public `Seam_Runtime/main` through the protected `pypi` environment and PyPI
  Trusted Publishing/OIDC. Live metadata and clean isolated installs were
  verified. No stored PyPI token is used, and this release does not change the
  private `seam-runtime` PyPI prohibition.
- The private GitHub repository has `private-package-release` and `pypi`
  environments restricted to protected branches. The current account plan did
  not accept wait-timer or required-reviewer protection rules, so do not
  describe either environment as reviewer-approved or time-delayed. Private
  release publication instead fails before the write-permission job unless
  both `github.actor` and `github.triggering_actor` match the admin-controlled
  `PRIVATE_RELEASE_APPROVER` repository variable, and reruns are rejected; the
  protected-branch environment remains a second deployment boundary. PyPI
  itself still requires the separate Trusted Publisher registration before any
  OIDC upload can work.
- Security-sensitive reports should be handled privately through `SECURITY.md`;
  do not disclose private data, credential material, customer data, or exploit
  details in public issues.
- `docs/PROTECTION_MODEL.md` documents the public/private repo split and must
  not be added to the mandatory startup read list unless the task touches
  licensing, contribution policy, repo protection, or public/private separation.
- Protection changes must not silently alter runtime behavior, CLI commands,
  installer behavior, dashboard behavior, API behavior, benchmark behavior, or
  history tooling. Package and release metadata must accurately identify the
  private proprietary distribution.
- SQLite is canonical source of truth.
- Canonical SQLite and every initialized durable projection are governed by
  the central `seam_runtime.migrations` spine at schema version 2. Read-only
  preflight refuses unknown/newer schema identities, projection registries, or
  knowledge-graph markers before writable open. Supported upgrades run ordered
  transactional steps with `integrity_check` and `foreign_key_check`, retain a
  private pre-migration backup, and expose explicit atomic restore. Current
  stores never rerun idempotent DDL on ordinary open; missing registered tables
  are corruption, while pre-spine historical stores migrate explicitly. A
  projection version changes only through an exact, statically registered
  `from_version` -> `to_version` callable with explicit source/target table
  contracts, planned deterministically before writable open. One migration-
  owner connection selects and asserts SQLite exclusive locking before its
  first database access, reruns authoritative preflight under `BEGIN
  EXCLUSIVE`, and retains writer exclusion across the same-owner backup and
  every separately committed step. Each callable then runs under `BEGIN
  IMMEDIATE` through a narrow facade that cannot control its transaction or
  locking mode; compare-and-swap advances only its owned marker, and required-
  table, component-marker, integrity, and foreign-key gates pass before commit.
  A failed later step rolls back without losing earlier durable resume points.
  Missing, extra, cyclic, or unregistered projection states refuse before
  backup or mutation. The registered graph chain is exactly
  `knowledge-graph/4 -> /5 -> /6`: S3 rebuilds disposable topology from
  canonical MIRL and durable lifecycle/supersession truth while preserving the
  identity judgement ledger; S4 then applies closed typed-reference contracts
  and restores those same canonical exclusions and judgements. A failed
  downstream step leaves the durable `/5` checkpoint truthful and resumable.
  Core storage advances exactly `core-storage/1 -> /2` to persist typed IR-edge
  endpoints and `core-storage/2 -> /3` for the append-only improvement-
  experiment ledger. Published S6 adds the registered `core-storage/3 -> /4`
  indexed public-memory-handle projection. Both S4 rebuilds consume canonical
  records in bounded batches;
  edge-type checks use at most 900 SQLite variables rather than one query per
  edge. A registry-less central-v0 store at exact `core-storage/1` plus KG/4 is
  the only supported pre-spine projection bootstrap: it runs the registered
  `/4 -> /5 -> /6` graph chain inside the central bootstrap transaction. A
  projection registry without the central migration registry is an ambiguous
  hybrid and refuses read-only. Current stores fail closed if a contributor
  loses its canonical source or edge, a canonical payload loses a required
  endpoint, or a required/list position has the wrong container or member
  shape. Reserved virtual-reference metadata is validated unconditionally.
  Hard deletes refuse atomically when a surviving canonical record still
  requires the target; optional survivors are reprojected as literal or
  explicitly virtual instead of retaining stale canonical topology. Ordinary
  writes and deletes refresh RAW/episode PROV attribution deterministically,
  and explicit facet values outrank generated fallbacks. A runtime vector-
  projection failure restores canonical, graph, and vector state together with
  content-free diagnostics. Rebuilds remove derived orphan vectors and keep
  identifier diagnostics content-free.
  See `docs/SQLITE_MIGRATIONS.md`, HISTORY#522, HISTORY#526, HISTORY#529, and
  HISTORY#530.
- RETRIEVAL HAS ONE ENGINE as an architectural invariant.
  `RetrievalOrchestrator` is the canonical SQL/vector/graph/temporal owner for
  the full runtime, and `SeamRuntime.retrieve()` is its local entry point. The
  longstanding `search_ir()` method is retained only as a compatibility
  result-shape adapter and must not become a second live scorer. CLI, MCP,
  REST, opaque `/v1`, dashboard, SDK, LoCoMo, self-improvement probes, and HS/1
  MIRL queries must reach that same engine. RAW inclusion, namespace/scope,
  lens metadata, explicit temporal window/reference, applied graph seeding
  policy, current-state filtering, and evidence closure must cross the same
  boundary. All SQLite-backed legs and visibility checks for one retrieval
  request must observe one committed read snapshot; routing connections through
  a pool without that snapshot contract is insufficient. This architecture is
  not authorization to change ranked behavior:
  the full provider-free gate in HISTORY#503 found the uncommitted fixed-RRF
  consolidation at 0.755616 context recall versus 0.766420 for the legacy
  scorer, while warm median latency rose from 156.4 to 207.2 ms. Preserve the
  legacy RAW/BM25/weighted ranking semantics inside the orchestrator as the
  versioned behavioral baseline, isolate graph attribution with a same-code
  hybrid-versus-mix ablation, and require full-corpus non-regression before
  promotion. Quickstart parity is insufficient. Component-level
  representation evals may still call the pure `search_batch` scorer as a
  named comparison track, but it is not a live runtime path. See HISTORY#502
  and HISTORY#503.
- SEAM's knowledge graph is a self-building, versioned SQLite projection of
  canonical MIRL, not a manually authored or browser-generated topology.
  `knowledge_nodes`, `knowledge_edges`, and `knowledge_episodes` preserve typed
  semantics, agent/source provenance, confidence/status, and temporal validity;
  every `SQLiteStore.persist_ir` write maintains the projection atomically.
  Entity reconciliation is read-before-write, so the shared persistence helper
  acquires `BEGIN IMMEDIATE` before reading canonical identities unless its
  caller already owns a transaction; concurrent ingests cannot mint divergent
  canonical entities from the same stale snapshot. Malformed or timezone-
  incomparable validity timestamps warn without logging their contents and
  fail toward expired/stale, never lexicographic established knowledge.
  Ordinary store open refuses missing, stale, or newer projection markers
  before graph DDL or reprojection; historical upgrades belong to an explicit,
  transactional migration workflow rather than implicit open-time backfill.
  The exact `knowledge-graph/4` -> `/5` transition atomically rebuilds only
  disposable topology from canonical MIRL, MIRL lifecycle status, and durable
  `document_status` supersession. It preserves and revalidates the separate
  identity-merge judgement ledger, refuses invalid canonical document
  identifiers without logging their contents, and leaves relevant table hashes
  unchanged on failed or unsupported rebuilds. RAW/MIRL remain the truth,
  graph retrieval and the dashboard consume the same projection. Graph hits
  reached by traversal expose deterministic edge/episode backtraces and may
  select the same current, full-history, or point-in-time validity view as the
  dashboard; inactive claims remain available only through those explicit
  history views. See
  `docs/KNOWLEDGE_GRAPH.md`, HISTORY#402, and HISTORY#529.
- Graph identity lookup is a scoped, rebuildable projection, not inference from
  assertion/source labels. `knowledge_node_terms` indexes canonical entity
  names, explicit aliases, symbols, agents, and short concept literals with
  source-record provenance; sentence-like values stay out. Extracted entities
  carry compile provenance to their RAW episode, and graph-to-source agreement
  uses one-to-one concept/query-term matching over semantic-edge and episode-
  mention paths. Track R's graph-first G1-G7 contract lives in
  `docs/roadmap/GRAPH_MEMORY_MATURITY.md`; benchmarks qualify completed graph
  stages but do not gate construction of missing graph substrate. See
  HISTORY#454.
- Track S S7 is locally qualified on draft PR #226, not yet protected-main
  behavior. The compiler accumulates each observed mention's exact proposition
  SPAN; scoped canonicalization merges repeat evidence while explicit identity
  keys keep same-name people separate. Temporal/cardinality reconciliation,
  concurrent replay, as-of intervals, cross-boundary REL refusal, and closed
  predicate admission now have provider-free counterexamples. A retrieved-ENT
  fixture resolves 5/5 entities through complete exact SPAN-to-RAW chains.
  Historical native LoCoMo ENT coverage remains 0.0000; native corpus
  freeze/review and scorer promotion remain S9. See HISTORY#602.
- The deep knowledge ontology is a conservative 5W1H+Then lens over MIRL, not a
  parallel truth store. Explicit facets and already-present MIRL fields may
  project `who`, `what`, `when`, `where`, `why`, `how`, and `then`; missing
  facets are never invented. Graph provenance edges aggregate contributors by
  episode/node pair so the API has stable unique edge IDs without losing the
  contributing record list. See HISTORY#403.
- G4 graph products are an append-only, rebuildable projection over the current
  trust-gated knowledge graph, never a second truth store. Entity summaries,
  connected-community summaries, and multi-episode observations are versioned
  by stable key. Identical source fingerprints reuse the prior complete
  snapshot; changed or empty eligible inputs append a new immutable boundary
  snapshot so stale derived text cannot remain current. Every rendered sentence
  carries exact supporting MIRL record and active episode IDs, and only current
  `supported` or `verified` same-namespace/scope facts may contribute text.
- G5 context assembly is a disposable `context-assembly/1` PACK over current
  canonical facts/entities/episodes and G4 products. Every item retains exact
  record and episode backtraces; derived items also retain their product ID.
  Task/trust/time ordering, whole-item truncation, exact token accounting, and
  the grounded-fact reservation are deterministic. Context never becomes a
  second truth store.
- G6 lifecycle is append-only audit around canonical MIRL, not hard deletion of
  truth. A scoped delete validates every target against one namespace/scope,
  requires exact caller-supplied internal boundary ownership, marks canonical
  rows `deleted_soft`,
  retains prior content for audit, and removes only disposable graph/vector/
  projection rows. Cross-store vector cleanup uses a committed
  `cleanup_pending` outbox: external failure remains recoverable and caller-owned
  transactions fail closed before external mutation. Current retrieval filters
  lifecycle-excluded records before graph seeding, and G5 revalidates every G4
  support before packing. Batch ingest is idempotency-keyed, records item
  progress, and resumes after interruption without duplicating canonical rows.
  Raw batch text is digest-bound in a tenant-authorized transient table and
  purged on completion; it is never copied into append-only lifecycle JSON.
  A pending vector-index intent never outranks later canonical lifecycle truth:
  replay acknowledges intents for missing or `deleted_soft` records without
  indexing them. Internal tenant-id/prefix validation alone is not
  authenticated principal binding. Published Track S S6 binds
  the resolved in-process principal to that existing lifecycle boundary and
  resolves generation-bound opaque delete handles through an exact indexed
  projection; it does not add a second deletion state machine.
- Assertion trust is evidence-gated and fail-closed. Claim/relation/event/state
  records enter `/chat` and `/chat/stream` asserted memory only when current and
  `supported` or `verified` inside the requested namespace and scope. Model or
  agent output is provenance, not independent evidence. Contested, unverified,
  refuted, stale, superseded, unknown, and cross-boundary records remain visible
  in graph/history exploration but are excluded from answer context.
- Structured workspace runs/events are append-only operational telemetry, not
  canonical MIRL. The schema allowlists event payload fields and strips unknown,
  credential-shaped, hidden-chain-of-thought, raw-activation, and tensor data.
  POST-backed SSE and replay share stable event IDs and per-run sequence order;
  every stream has exactly one completion/failure terminal event.
- The reasoning graph is an append-only public justification plane anchored to
  `workspace_run`, parallel to the canonical MIRL-backed knowledge graph. It
  stores only typed summaries, relationships, status history, and exact scoped
  knowledge/evidence references; it never stores hidden chain-of-thought or raw
  model internals and never promotes itself into MIRL. R2 retrieval decisions
  use fixed typed columns plus a bounded content-free candidate ledger (record
  IDs, boundary/content fingerprints, scores, and reason codes), enforce the
  insertion-time run/namespace/scope boundary in SQLite, detect later evidence
  drift, and pin planner/fusion, semantic-adapter/model identities, and the
  selected graph time view; raw record/provider payloads are forbidden. The
  local Python SDK is the stable integration boundary; CLI, REST, MCP, and
  framework adapters should wrap that contract rather than depend on SQLite
  tables. SDK semantic graph seeding is an explicit opt-in over the legacy
  orchestrator default and does not establish a full G3 quality/scale claim.
  R3 verification records are likewise append-only and content-free:
  controlled check identity/verdict, bounded public summary, exact scoped
  evidence references, and a hash/byte length instead of raw tool output.
  Retries form one immutable linear chain. Only current same-run passed checks
  may atomically support a verified outcome; failed and superseded attempts
  remain visible, and no verification path promotes itself into MIRL.
  R4 distills every verified accepted outcome into an append-only structural
  recipe containing only public node kinds, controlled operations, edge
  relations, and check kinds. Same-boundary task/operation retrieval requires
  fresh current verification, knowledge, and exact MIRL-fingerprint provenance.
  Explicit reuse followed by a verified outcome strengthens future ranking;
  explicit failure weakens it. Recipes never copy summaries, conclusions, raw
  tool output, provider payloads, or hidden reasoning, and never promote
  themselves into MIRL.
  R5 is the only explicit reviewed bridge from one verified accepted outcome
  into a proposed canonical claim. Proposals bind current verification IDs,
  knowledge references, and exact MIRL evidence fingerprints to a bounded CLM
  payload. A separate human or policy review may approve or reject, but only a
  later explicit Store/SDK application rechecks eligibility and atomically
  persists both the exact assertion and its application fingerprint. Nothing
  auto-applies. Reversal requires the exact assertion fingerprint still to be
  present and appends an immutable reversal plus a MIRL `supersedes` relation;
  it never deletes or rewrites the assertion, reasoning outcome, reviews, or
  evidence.
  R6/G7 qualification uses frozen, versioned adapter and manifest contracts.
  Native and event-only results remain separate from matched Mem0/Zep lanes.
  External lanes may carry only `NOT_RUN`/`BLOCKED`, exact paid commands, zero
  provider calls, and null scores until explicit operator approval and required
  credentials exist. Provider-free results cannot be republished as competitor
  results. Native/event-only comparisons use identical context and result
  budgets; the current corrected provider-free result is parity, not an
  incremental graph-value claim.
  LoCoMo remains a memory-quality and regression floor; by itself it cannot
  establish graph-caused lift or top-level graph/reasoning performance. Public
  top-level claims require the matched causal arms, fixed budgets, per-case
  evidence, quality/latency/cost accounting, and R3 admission across the
  multi-benchmark portfolio defined in
  `docs/audits/2026-08-18-graph-benchmark-readiness-research.md`, followed by
  one independent R4 reproduction. Vendor or paper scores remain attributed
  context until reproduced under that contract.
  See `docs/REASONING_GRAPH.md`.
- Cross-leg retrieval fusion uses the fixed, versioned
  `reciprocal-rank-fusion/2` contract. Each SQL, record-vector, graph-node,
  traversal-graph, or Chroma leg deduplicates records by best raw score, ranks
  within its own score domain by raw score then record ID, contributes
  `1 / (60 + rank)`, and sums those comparable values. Raw leg magnitudes
  remain in the live trace; new R2 decisions persist the policy fingerprint and
  legal rank-derived contributions. Qualification covers structured,
  bounded-hop, historical, and semantic-seeded mixed shapes on a synthetic
  2,048-node graph plus a pinned LoCoMo development/holdout selector gate using
  complete versioned graph-node vectors and explicit `graph_node` traces.
  `rrf_k` must be a positive integer before fusion, and every equal-score or
  equal-fusion boundary resolves by stable record ID so SQLite row rewrites do
  not change budgeted output.
  See `docs/REASONING_GRAPH.md` and HISTORY#467.
- J-lens capability claims are honest and opt-in. The default is structured
  workspace only, with no bundled weights, network access, downloads, or raw
  activation persistence. A genuine J-lens requires activation-capable local
  model access or an authenticated remote worker plus verified model/revision
  and model/lens artifact hashes. Hosted-provider traces are never relabeled as
  J-Space. Remote workers require operator host allowlisting and exact IP pins;
  credentials/artifacts remain outside the repository.
- The H2 improvement loop is a strict propose-and-approve ratchet. It can derive
  free probes from the live graph and writes proposals into the existing H2
  store, but aggregate/category/integrity/trust/temporal/provenance/holdout gates
  must all pass with evidence. Any failure or missing/malformed gate records an
  append-only rejection; a full pass remains pending until explicit approval,
  and `auto_approve` cannot bypass that boundary. The apply path admits only an
  approved, non-violating proposal with a passing stored ratchet. Only
  graph-aware scorers may propose the bounded graph semantic-seed/score-floor
  levers. Once approved and applied, those flags change later knowledge-graph
  behavior across SDK, CLI, MCP, REST, and internal runtime surfaces; the
  existing revert path restores the prior policy.
- Every default H2 cycle must create a durable `improvement-experiment/1`
  record before baseline scoring. Its immutable definition hash commits to the
  lane, method, baseline, evaluator, dataset, candidate space, budget, code, and
  definition metadata; append-only chained events retain the baseline, every
  completed candidate (including losses), proposal linkage, terminal outcome,
  and content-free failures. Experiment success is evidence, never application
  authority: counterfactual candidates cannot mutate applied flags, a passing
  strict ratchet remains pending, and permanent changes still require explicit
  operator approval plus apply. The AutoResearch-style fixed-evaluator/bounded-
  search pattern does not authorize arbitrary downloaded code or unrestricted
  source modification. See `docs/IMPROVEMENT_EXPERIMENTS.md`.
- Vector stores (SQLite vector index, Chroma, PgVector) are derived retrieval layers. The SQLite vector adapter is the DEFAULT backend; `chromadb` and `psycopg` (pgvector) are OPTIONAL extras (`seam[chroma]`, `seam[pgvector]`), never core dependencies. All Chroma imports are lazy (`ChromaSemanticAdapter._client` raises a clear error if chromadb is absent). chromadb 1.0.0-1.5.9 (the whole current 1.x line) carries an UNPATCHED critical advisory GHSA-f4j7-r4q5-qw2c (pre-auth code injection in the Chroma SERVER); SEAM uses only the embedded `PersistentClient` so the server/auth surface is not reachable, but chromadb is kept OPT-IN ONLY: not in core `dependencies`, not in `requirements.txt` (installer/bootstrap path), and not in `all-extras` - only in the explicit `chroma` extra. Do not reintroduce it to any default/convenience path (guarded by `tests/audit/test_chroma_optional.py`).
- Native SQLite and pgvector vector searches carry both namespace and scope into
  pre-top-K filtering; post-filtering remains a fail-closed defense. SQLite
  upgrades backfill both fields from canonical `ir_records`. Existing external
  pgvector rows created before the scope column must be resynced explicitly;
  their scope cannot be inferred safely inside the external vector table.
  Namespace/scope-only repair must update metadata without recomputing an
  unchanged embedding, including when the configured embedder is paid/remote.
- Derived vector text is governed by the explicit
  `mirl-vector-text/2` contract. Generic records render in deterministic
  semantic field order with recursively sorted maps and stable list order;
  RAW content and grounded-CLM special rendering stay byte-identical.
  SQLite, pgvector, and Chroma search only current-version rows. Additive
  schema migration labels older rows v1 without embedding; operators must run
  an explicit full reindex (or explicit Chroma index sync) to upgrade them.
  Boundary-only repair never upgrades render versions or invokes embeddings.
- Document ingest status is canonical SQLite metadata. Source refs, source hashes, extraction status, index status, and deletion state belong in `document_status`, not only in derived vector stores.
- Agent-facing retrieval should use progressive disclosure where possible: compact search/index results first, then full MIRL records by selected IDs.
- Default agent RAG should prefer `mix` retrieval only after benchmark validation; the supported retrieval modes are `vector`, `graph`, `hybrid`, and `mix`.
- Retrieval is ANSWERER-AWARE via named profiles in `RetrievalFlags` (`RETRIEVAL_PROFILES`, env `SEAM_RETRIEVAL_PROFILE`): `compact`=(top_k 100, context_budget 8000) for small/local answerers (tight context, dilution-averse) and `broad`=(300, 60000) for capable answerers (high coverage). The right retrieval knee is answerer-dependent — holdout-validated on LoCoMo cat1 (a capable answerer's broad knee +0.139 judged where the same broad context COLLAPSED a weak 3B answerer). `search_top_k` and `context_budget` are CONFIG knobs (env-driven, explicit vars override the preset). They are loop-tunable as candidate levers (`candidate_levers(profile_levers=True)`) ONLY when every scorer in the improvement loop is dilution-sensitive (`profile_safe`) — the free-LoCoMo answer-quality scorer (`PooledLocomoAnswerQualityScorer`, generated-answer `token_f1` via a local Ollama answerer) or the operator-gated paid judge — and NEVER under the `#290` self-probe or `#292` context_recall scorers, which a bigger budget mechanically inflates (the gaming hazard `#320`/`#328` originally avoided by excluding the knobs entirely; `#332`/Strand B re-admits them behind the `profile_safe` gate). `run_improvement_cycle` enables `profile_levers` iff every scorer reports `profile_safe`; `getattr(scorer, "profile_safe", False)` defaults unmarked scorers to unsafe. Default (no profile) is byte-identical to the prior baseline — both knobs `None` → call-site budget / prior 512 pack default. The profile flows through `load_retrieval_flags` so every surface (CLI/REST/MCP/dashboard/benchmark) inherits it, not just the benchmark.
- The canonical paid holdout path accepts `seam improve validate --profile {compact,broad}`. The named profile overlays only the candidate's `search_top_k` and `context_budget`, composes with explicit answer-policy `--flags` (or the loop's applied state), and never changes the stock baseline. A full 344-case operator-approved run at `99079f7` reproduced the prior broad-stack candidate exactly (`0.732558`) through this CLI path. This is an opt-in validation surface, not a default-ON decision for any runtime or policy.
- Agent ecosystem integrations should be thin wrappers over SEAM CLI/REST/MCP surfaces. Do not rewrite the Python runtime into Node just to fit Claude Code-style plugin ecosystems.
- Standard MCP stdio is the canonical agent-tool protocol for Gemini, Claude,
  Cursor, OpenCode, and future MCP clients: use `seam mcp stdio` or `seam-mcp`
  for JSON-RPC MCP discovery/calls. `seam mcp serve` remains only as the legacy
  JSON-lines bridge for older local wrappers.
- Agent clients that need the real pgvector adapter should launch MCP with
  `--ensure-pgvector`. That path starts the repo Docker Compose `pgvector`
  service, waits for container `seam-pgvector`, sets `SEAM_PGVECTOR_DSN` only
  in the MCP server process, and reads credentials only from ignored local env
  files such as `SEAM_LOCAL_ENV` or `~/OneDrive/Documents/SEAM/local/.env`.
- Lossless claims require exact reconstruction and integrity checks.
- SEAM compression must produce directly readable AI-native machine language as the primary artifact; opaque byte compression is only an optional reconstruction/integrity backing layer.
- A compressed SEAM artifact is not complete unless SEAM can answer detail questions from the compressed language without restoring the original source.
- Holographic surfaces are queryable visual containers for embedded MIRL or `SEAM-RC/1`; they are not a replacement for SQLite canonical truth and are not a claim of free compression.
- `seam surface compile` is the default source-to-surface operator flow: compile source text into MIRL, then encode MIRL into `SEAM-HS/1` with `rgb24` unless a denser mode is explicitly requested.
- Benchmark claims must be auditable (bundle hash, case hashes, fixture hashes, git SHA), diffed against a prior run, pass the benchmark gate, and stay separated from publish-only holdout runs.
- External memory benchmark claims require a non-stub judge plus passing BIL-2
  bundle verification before `validate_publication_readiness` can return
  publication-ready. Stub judge output is smoke-only even when it can be sealed
  with an explicit test override.
- GitHub PRs must keep no-paid benchmark integrity visible: CI runs a LoCoMo
  quickstart smoke with the stub judge, seals it as BIL-2 with the explicit
  stub override, verifies the bundle, and uploads the result/bundle/verify
  artifacts. CI also runs a real Chroma smoke through `chromadb`, `git diff
  --check`, and a non-printing secret/session URL scan. Paid answerer, judge,
  decomposer, or full LoCoMo runs remain operator-gated and must not be added
  to default PR CI.
- `tools.security.secret_scan` is the canonical repository credential and
  private-session scanner. CI scans the working tree; the private-origin
  pre-push hook scans every blob introduced by each pushed range, including
  added-then-deleted content. Oversized text fails closed unless an exact
  manifest-pinned repository dataset hash authorizes that one path.
- `pyproject.toml` `[tool.seam.dependency-contract]` is the checked authority
  for runtime dependency source, installer mirror, convenience-extra members,
  exclusions, and retired extras. `tools.ci.verify_dependency_contract` guards
  CI/install drift. `seam doctor` must require only the imports corresponding
  to that core runtime source; optional and excluded adapters such as Chroma may
  be reported as available or absent but must not fail a policy-compliant core
  install. Release lock and artifact hash proof remains an S10 gate.
- The self-improvement loop's paid judged validation tier
  (`benchmarks/external/locomo/judged_scorer.py` + `tools/h2/paid_validation.py`)
  is reachable ONLY via `seam improve validate --confirm-paid`. Without
  `--confirm-paid` the command is a zero-cost dry run (case/call-count estimate;
  no client constructed, no ingest). The judged scorer must never be added to
  the always-on improvement loop's scorer list, never auto-run by any agent, and
  every execution requires fresh explicit operator confirmation. It validates on
  the HOLDOUT split by default; the loop itself tunes on dev only and must never
  tune on holdout.
- GitHub `main` is protected by repository ruleset `Protect main (PR +
  hygiene gates)`: no bypass actors, no deletion, no non-fast-forward update,
  pull request required, and `repo-hygiene`, `chroma-real-smoke`, and
  `locomo-quickstart-bil2` required with strict latest-code status checks.
  Do not reintroduce direct-push bypass except as a time-boxed emergency
  with a follow-up HISTORY entry.
- On the single `seam-box` runner, the advisory `test-and-benchmark` job must
  depend on all five short Linux jobs so required merge feedback completes
  before the 20-30 minute suite can occupy the runner. Do not remove that
  ordering unless equivalent runner capacity or a stronger scheduling
  guarantee replaces it.
- `AGENTS.md` contains the cross-agent GitHub PR workflow: work through
  branches and draft PRs, isolate unrelated dirty files, keep PR bodies current,
  distinguish required checks from advisory matrix failures, and resolve stale
  PRs/branches as merged, closed, active, or concretely blocked instead of
  letting them accumulate.
- `docs/status/workspace.md` is the canonical current inventory for local
  worktrees, local/remote branch aliases, open or merged PR ownership, ignored
  artifacts, directly coupled sibling repositories, and overlap between
  workstreams. Before creating or reviving a branch/worktree, refresh its
  commands and match by purpose, PR, and commit so a differently named alias is
  not reimplemented as new work. The inventory is advisory and grants no
  deletion authority; ignored files and dirty companion-repository output
  require their own preserve/delete decision even when the SEAM tracked tree
  is clean.
- Benchmark evidence proves SEAM value but never grants trademark rights,
  implies endorsement, or grants access to private hosted, enterprise,
  customer-specific, or unreleased SEAM offerings.
- Compatibility CLI aliases are acceptable during naming transitions.
- Agent continuity is protocol-driven (`AGENTS.md`), not model-specific duplicate docs.
- Linux install has two supported flows: default `install_seam_linux.sh` creates
  global user command shims and persistent runtime state; `install_seam_linux.sh --dev`
  creates/reuses the repo-local Python `.venv`, handles the external-drive
  `lib64` venv fallback, installs Python dev dependencies, runs SEAM protocol
  verification. (It once also skipped `experimental/webui/`; that tree was
  removed in HISTORY#285 and the exclusion no longer refers to anything.)
- Cross-file duplication is disallowed; use pointer cards (`see HISTORY#NNN`).
- Tracked testing documentation belongs under `tests/docs/`. Disposable local
  test outputs belong under ignored `test_seam/<area>/` subdirectories
  (`test_seam/pgvector/` for `test_pgvector_*` artifacts). Do not leave ad-hoc
  test notes, `Test*` scratch files, or generated `test_*` artifacts in the
  repo root.

## AI-Native Compression Policy

- The compressed language is the working document for AI question answering.
- Direct readability is mandatory for documents, text, images, audio, and video: quotes, table cells, OCR spans, image regions, timestamps, transcript spans, and provenance must be represented in machine-readable records.
- Opaque payload formats such as SEAM-LX/1 may be retained for exact rebuilds and hash checks, but they must not be the only artifact used for semantic read/query workflows.
- Future compression interpreters and codecs must optimize intelligence per token while preserving exact detail access through MIRL or a successor SEAM machine language.
- SEAM-HS/1 may carry MIRL, RC/1, LX/1, or raw bytes in lossless PNG pixels. MIRL and RC/1 payloads are directly queryable from the surface; LX/1 payloads are verify/decode only until converted into a readable payload.
- The planned surface library stores `.seam.png` artifacts as addressable visual memory surfaces with SQLite metadata, hashes, verification state, and lookup fields. Queries should read embedded MIRL/RC payloads directly from the lossless image bytes in memory; PACK remains derived prompt-time context and must not become the raw image store.
- The private runtime repo stores source and metadata code for surface-library
  adapters, not generated operator/user `.seam.png` artifacts by default.
  Generated surface files stay operator-controlled unless explicitly promoted
  as repo-owned fixtures or documentation assets.

## Handoff Policy

- Default chronology: record state via `HISTORY.md` entries + `HISTORY_INDEX.md`.
- Canonical tracked recovery route: `docs/handoffs/INDEX.md` points to exactly
  one current handoff and records one linear, newest-first supersession chain.
  Every `docs/handoffs/*.md` document must be registered and declare
  `handoff_id`, `supersedes`, `handoff_status`, and `history`. A new handoff
  supersedes the current head; standalone dated files are not valid handoffs.
- `python -m tools.history.verify_handoffs` enforces path/history existence,
  metadata agreement, one root, no cycles or forks, one current/live head, and
  `latest`/table-order consistency. Every handoff is part of the authoritative
  temporal chain: the newer handoff must reference a strictly later HISTORY ID
  whose timestamp is not earlier than its predecessor's entry. The verifier
  enforces those ID and timestamp constraints across the complete registered
  chain, and it runs in local commit and CI gates.
- Session close writes one validated snapshot in `.seam/snapshots/`.
- `HISTORY_INDEX.md` and snapshots are derived artifacts; `HISTORY.md` is authoritative.
- The `handoff/archive` branch is reserved for PDF and handoff artifact publication, not primary runtime/source work.

## Temporal Continuity Policy

- Every material repo change must produce an append-only `HISTORY.md` entry, rebuilt `HISTORY_INDEX.md`, verified integrity, and one validated snapshot.
- History entries must preserve the temporal chain: previous state, new state, `supersedes` link when applicable, successes, failures, skipped verification, changed files, and unresolved next steps.
- HISTORY topic tags use the controlled vocabulary in `AGENTS.md`. Because
  `HISTORY.md` is immutable, a tag already present in a merged entry is retired
  or admitted by changing that vocabulary prospectively; agents never rewrite
  the old entry merely to normalize its routing metadata.
- Stable repo facts live here in `REPO_LEDGER.md`; detailed session chronology lives in `HISTORY.md`. Do not duplicate long prose across both files.
- Agents must update this ledger when changing stable repo policy, architecture, active/archive routing, runtime safety rules, durable operator workflows, benchmark publication rules, or cross-agent protocol.
- Agents must update `PROJECT_STATUS.md` when the current operating state or active focus changes.
- Model-specific guides such as `CLAUDE.md`, `GEMINI.md`, and `ANTIGRAVITY.md` must route back to `AGENTS.md` and must not create a competing protocol.
- Cross-agent commit gate: `tools/git-hooks/pre-commit` is the canonical pre-commit hook for this repo. It runs for every `git commit` regardless of who initiated it (Claude, Codex, Gemini, Aider, Cursor, OpenCode, human operator) because git itself enforces `.git/hooks/pre-commit`. The hook scope-blocks `.claude/`, `.opencode/`, `.agents/`, and `opencode.jsonc?` paths from staging, then runs `verify_integrity`, `verify_routing`, `verify_handoffs`, `verify_continuity`, `verify_streams`, and `verify_wiki` against the SEAM continuity, streams, and documentation protocols; non-zero gate exits non-zero and blocks the commit. Operators install the hook into `.git/hooks/pre-commit` with `bash tools/git-hooks/install.sh`, which symlinks where supported and falls back to a copy with a `CANONICAL_SHA` marker on filesystems that do not support symlinks (exFAT, FAT32, some Windows configurations). `seam doctor` reports the gate state under `commit_gate` and the streams substrate state under `streams`, and tells the operator how to repair drift.
- Legacy public-mirror freeze (HISTORY#467, superseding HISTORY#344/#355/#356
  as current policy): `tools/git-hooks/pre-push` unconditionally refuses any
  update to the `seam-runtime`/`Seam_Runtime` remote. The safety scanner
  explicitly blocks MIRL and HS/1 Reserved Materials and every private-by-default path,
  and `public_manifest.py` exposes no synced private paths. The former
  `sync_public_mirror.py` utility has been removed with the split-distribution
  tooling; do not recreate or substitute a private-to-public sync path.
  Pushes to private `origin` are unaffected. Do not bypass the freeze.
- The former curated-sync implementation and `public_seed/` content are removed,
  not an active release mechanism. A future public client/SDK must use a separate repository,
  dependency boundary, manifest, license, and review; it must not reuse or
  reactivate the whole-runtime mirror.
- Recorded-fact discrepancy audit is part of `verify_continuity`. Checkable facts written into active docs or the latest history entry must include enough scope to verify them later. The initial typed checks cover scoped pytest count claims, ambiguous hard-coded test totals, current handoff pointers, latest history refs that point at missing files, and same-scope test-count precedence drops (for example a later `150 passed` claim after an earlier same-scope `180 passed`). Future fact types should be added as extractors under `tools/history/recorded_fact_audit.py` so continuity catches disappearing data instead of relying on manual review.
- Context Streams substrate (Track H1 implemented and measured): `tools/streams/` provides generic stream tooling that generalizes the single-stream history protocol into a multi-stream substrate. Root `HISTORY.md` + `HISTORY_INDEX.md` remain canonical; `.seam/streams/history/log.md` + `index.md` are byte-equivalent derived mirrors via `tools/streams/history_adapter.py`. The `roadmap` stream is populated for every track in `ROADMAP.md` via `seam:item` markers (34 items as of HISTORY#171). New `experience` stream lives entirely under `.seam/streams/`. `roadmap/state.md` is the compact agent-facing status view; `.seam/cross_index.md` is the derived global temporal join with two-tier indexing (200-event hot zone plus `.seam/cross_index_archive/` chunks). `tools/streams/build_context_pack.py` is the stream-aware pack builder; for `--stream history` it delegates to the canonical history pack so output is byte-equivalent. `tools/streams/bloat_report.py` measures the H1 reduction under the canonical cl100k_base tokenizer: roadmap status reads drop 88.4 percent (ROADMAP.md to state.md), history map reads drop 89.5 percent (HISTORY.md to HISTORY_INDEX.md), and cross-stream recent reads drop 88.6 percent (HISTORY.md plus ROADMAP.md to cross_index.md). Earlier-cited 93.5/90.5/91.0 numbers used a word-count heuristic that overstated savings; see HISTORY#216 for the tokenizer unification. The `verify_streams` gate enforces parseability, history-mirror byte-equivalence, per-stream index consistency, and cross-index presence; it runs in the canonical pre-commit hook and the Claude preflight as a fourth gate. Path canonicality flip for `history` (root → `.seam/streams/history/`) is explicitly deferred to a separate later HISTORY entry per `docs/roadmap/CONTEXT_STREAMS.md` §9. AGENTS.md "Context Loop" describes the bounded session-start read protocol that uses `roadmap/state.md` instead of full `ROADMAP.md` and `cross_index.md` for cross-stream temporal queries.
- Claude Code defense-in-depth: a per-operator-local `.claude/settings.json` may wire `tools/claude/preflight_protocol.sh` (PreToolUse Bash hook) and `tools/claude/session_start_brief.sh` (SessionStart hook) so Claude Code reproduces the same verify chain before invoking git and prints the AGENTS.md read order on session start. `.claude/` stays gitignored and is rejected by the canonical pre-commit hook; each Claude Code operator wires their own machine. The Claude hook is belt-and-suspenders to the canonical git hook; the git hook is the protocol enforcement, the Claude hook is the early warning. Equivalent wiring for Codex, Gemini, and other agents is open follow-up work tracked in HISTORY; the canonical git hook covers them today even without per-agent wiring.
- DeepSeek parallel audit execution is documented in `docs/SOP_DEEPSEEK_PARALLEL_AUDIT_EXECUTION.md` (see HISTORY#205). That SOP is the durable handoff for asking DeepSeek to use its own parallel workers for SEAM debugging, systematic audit, verification, adversarial review, and merge-request preparation. Codex review/merge handling remains local and non-agentic unless the operator explicitly changes that constraint.
- Advisor/executor execution is documented in `docs/SOP_ADVISOR_EXECUTOR_LOOP.md`. Codex or true Claude Opus may act as Advisor for strategy, planning, review, and final approval; `claude-ds`/DeepSeek acts as bounded Executor for Advisor-authored task packets, must escalate uncertainty with `ADVISOR_ESCALATION`, and does not own commits, pushes, history closeout, architecture, or scope expansion unless explicitly delegated.

## Context Budget Policy

- Full continuity is preserved in append-only history, but normal startup must not load full history.
- `HISTORY_INDEX.md` is the compact route map; `.seam/snapshots/` are bounded handoff packs; `tools.history.build_context_pack` builds topic/latest/supersedes packs under an explicit token budget.
- `tools.history.verify_continuity` is the quality gate for history/index/snapshot freshness, supersedes validity, and session-link/secret hygiene.
- Prefer task-specific context packs over broad scans. If a pack is insufficient, add targeted topics, explicit entries, or refs instead of reading all of `HISTORY.md`.

## Data Routing Policy

- `tools/history/routing_manifest.json` defines logical branches for AI-searchable history such as `maintenance/docker`, `maintenance/pgvector`, `protocol/context`, and `protocol/security`.
- Route classifications are mutable, but route mutations must remain reconstructable through `HISTORY.md`, manifest lifecycle fields, and stable topic ledgers under `docs/ledgers/`.
- `tools.history.verify_routing` checks route tree integrity, parent links, route lifecycle fields, ledger paths, and referenced history entries.
- Deleting a classification means removing it from active use through `status=retired` or `status=moved`; the audit trail must remain.

## Documentation Separation Policy

- `docs/README.md` is the single canonical SEAM Wiki home. It is a navigation
  layer over existing authorities, not a second place to maintain volatile
  product claims, status, benchmark results, or plans.
- Every active `docs/**/*.md` page must remain reachable from the wiki home.
  `python -m tools.docs.verify_wiki` uses CommonMark parsing to enforce coverage
  and safe rendered local links across every reachable page. It also enforces
  the report-registry contract below. The commit hook exports and checks the
  exact Git index so an unstaged repair cannot mask invalid staged navigation;
  the working-tree verifier also runs in closeout, agent preflight, and required
  CI.
- `docs/audits/` is the canonical tracked home for dated, human-readable SEAM
  reports, including visual status reports, focused investigations,
  architecture assessments, and interpreted benchmark reports. Every new
  report is date-slug named, registered in `docs/audits/INDEX.md`, and linked to
  its latest governing HISTORY entry. From the registry's prospective
  `policy_start`, every new report also declares an evidence manifest: either
  no raw artifacts or each durable artifact's path and SHA-256. Raw benchmark
  bundles remain in their configured durable artifact store or ignored run
  directory; historical reports before that boundary are not rewritten.
- Inactive docs, old handoffs, superseded setup notes, and historical coding artifacts live under `docs/archive/`.
- Archived docs are traceability records, not current instructions.
- When old prose is useful, rewrite the current part into an active doc and point to `HISTORY#NNN`; do not duplicate stale context across active docs.

## Code Separation Policy

- Active runtime code lives in `seam_runtime/` and `seam.py`.
- Active operator/dev tooling lives in `tools/`, `scripts/`, and `installers/`.
- There is no `experimental/` tree. It was removed in HISTORY#285; nothing in
  this repo is experimental. See `docs/CODE_LAYOUT.md`.
- Inactive or retired code lives under `archive/code/` and must not be imported, packaged, or used as current behavior.
- Generated build copies live in ignored paths (`build/` or `archive/code/generated-build*/`) and should not guide implementation decisions.
- The current code map is `docs/CODE_LAYOUT.md`.

## Lint Policy

- `ruff` is the one general-purpose Python linter (install via `seam[lint]`); config lives in `pyproject.toml`'s `[tool.ruff]`/`[tool.ruff.lint]`. Rule set is deliberately narrow (`E4`, `E7`, `E9`, `F`, `I`) — no `E501`/pure-style rules, no mypy/type-check gate yet.
- The dev-only `seam[lint]` extra also carries `markdown-it-py`, which gives the
  required wiki verifier actual CommonMark semantics without adding a runtime
  dependency to SEAM.
- `extend-exclude` skips `archive/` and `build/` (retired/generated code, never a gate). `per-file-ignores` carries structural `E402` exemptions for `seam_runtime/dashboard.py` (optional rich/textual import guards) and `installers/install_seam.py` (sys.path-before-import) — both intentional, not accidents.
- **`ruff check --fix`'s F401 (unused-import) removal is not always safe**: it only sees usage within the same file, so it can silently delete (a) public re-export facades like `seam.py`'s `from seam_runtime.runtime import SeamRuntime` (kept alive only for downstream `from seam import X`, nothing inside the file calls it), and (b) test-monkeypatch attribute targets — `tools/history/test_history_tools.py`'s `_MultiPatch` patches module attributes by string name via `getattr`/`setattr`, not `from module import name`, so a plain grep won't find the usage either. Before trusting any F401 removal (auto or manual), grep for `from <module> import.*NAME` / `<module>.NAME` AND for `getattr(`/`setattr(`/`monkeypatch.setattr(` references to that name across `tests/`, `test_seam_all/`, `tools/`. If either finds a hit, keep the import with `# noqa: F401` and a one-line comment stating which case it is.

## Runtime Service Safety Policy

- External services for real-adapter tests (for example Docker pgvector) must be started only for the active test window.
- Every service started for a test run must be explicitly stopped and removed at the end of that run.
- Prefer non-conflicting ports for temporary services and verify they are released after cleanup.
- Keep resource monitoring lightweight during runs (snapshot checks or low-frequency polling) to avoid adding load.
- If a run fails or exits early, perform the same shutdown/cleanup sequence before continuing.
- Default guardrail for local runs: warn around `82%` RAM usage and treat `90%` RAM as hard limit unless explicitly overridden for a task.
- Use `scripts/run_guarded.ps1` for heavy commands so CPU/RAM/disk are watched during execution.
- Use `scripts/run_real_adapters_guarded.ps1` for end-to-end real-adapter validation; it starts pgvector, runs guarded checks, and cleans up containers/artifacts on exit.
- Archive benchmarks with `scripts/store_benchmark.ps1` to keep publication-required hashes and reproducibility metadata in Documents; outputs are sequence+time indexed and blocked from writing inside the git repo by default.

## REST API Policy

- The REST API is optional and installed with the `server` extra.
- `seam serve` and `seam-server` run the FastAPI/Uvicorn surface against the configured SQLite database.
- Protected endpoints require `Authorization: Bearer <token>` when `SEAM_API_TOKEN` is set; leave that variable unset only for trusted local development.
- Bearer-token-only operation authenticates one trusted deployment boundary;
  it does not identify principals and must not be described as shared hosted
  tenancy.
- Published Track S S6 optionally resolves a bearer credential
  to a stable in-process principal. The environment adapter binds
  `SEAM_API_TOKEN` to `SEAM_API_PRINCIPAL`; injected deployments may supply a
  resolver directly. Principal mode requires a stable injected public-ID key or
  `SEAM_API_PUBLIC_ID_KEY` of at least 32 bytes, derives internal tenant and
  namespace identity from the subject, and disables legacy private data routes.
- Candidate principal mode cannot silently run unbounded: unset or zero rate-
  limit configuration resolves to 60 requests per minute. Invalid/rotating
  credentials share a bounded client-address pre-resolver bucket, successful
  requests release that reservation and use a stable subject bucket, and
  multi-worker launch is refused unless an upstream shared limiter is
  explicitly acknowledged. Legacy token-only mode preserves its configured
  zero/unset behavior.
- An injected principal resolver must declare the exact `process_workers`
  topology when creating the app. The same process-local limiter refusal then
  applies to injected and environment adapters; omission is a startup error,
  not an assumed single-worker deployment.
- SQLite runtime canonical writes, vector projection/compensation, scoped
  delete planning/apply, and public-handle publication share a reentrant
  cross-process file lock keyed to the resolved store path. The lock is stored
  beside the database under the store directory's permissions and uses a
  bounded 60-second nonblocking acquisition loop on POSIX and Windows. This is
  canonical/projection atomicity across local workers; it is not an upstream
  shared request limiter or distributed-database claim.
- Principal authentication uses three bounded process-local budgets: a
  client/IP reservation for pre-parse work and rotating invalid credentials, a
  non-released credential-fingerprint budget for resolver invocations, and a
  stable hashed principal budget for authenticated requests. The credential
  budget refuses new fingerprints at key-map capacity rather than evicting a
  live reservation. Successful authentication releases only the client/IP
  reservation, so separate principals sharing one address remain independent
  without allowing one valid credential to invoke an injected resolver beyond
  its request budget.
- Candidate principal-mode data routes are `POST /v1/memories`,
  `POST /v1/memories/recall`, `POST /v1/context`, and
  `POST /v1/memories/delete`. Delete accepts only exact indexed, generation-
  bound opaque handles inside the caller's derived tenant/namespace/scope and
  reuses the existing G6 lifecycle plan/apply and recoverable-cleanup contracts.
  Recall/context registration verifies the canonical generation in the same
  write transaction and shares the runtime projection lock with write
  compensation; cross-process rollback additionally preserves concurrent
  handle rows only when they still match the restored active canonical
  generation. Deleted records cannot publish or resolve handles. Same-key
  delete retries resume the existing operation only while no target has a new
  live generation, with every public apply fast path rechecking that condition
  inside the lifecycle transaction, including a planner that raced and returned
  an existing operation. Deletion plans recheck generation inside the
  canonical delete transaction; writes overlapping an active tenant-indexed
  scoped deletion refuse. Principal mode blocks disallowed route/method pairs
  before router matching, normalizes the ASGI `root_path`, and allows CORS
  preflights for its four data routes.
  Repaired-head exact CI and merge remain before this becomes protected-main
  behavior.
- `/health` is unauthenticated for local service checks but still participates in the same rate limiter.
- Rate limiting is configured by `SEAM_API_RATE_LIMIT_PER_MINUTE` or
  `SEAM_API_RATE_LIMIT`; `0` or unset disables the limiter in legacy mode and
  selects the bounded 60-request/minute default in candidate principal mode.
- Legacy/custom local development origins `http://127.0.0.1:5173` and
  `http://localhost:5173` remain allowed by default through CORS. The active
  bundled WebUI is same-origin; the old Vite source is archived. Override with
  `SEAM_API_CORS_ORIGINS`, or set it to `0`, `false`, `off`, or `none`
  to disable CORS.
- API handlers must use existing `SeamRuntime` behavior and public report `to_dict()` methods rather than inventing parallel response fields.
- POST/PUT/PATCH bodies are bounded by `SEAM_API_MAX_BODY_BYTES` (default `5000000`; `0` disables). Oversized requests return HTTP 413 before endpoint handlers run.
- Private REST `POST /persist` is create-only at the HTTP boundary. It checks
  canonical id collisions while holding the SQLite write lock and returns a
  content-free HTTP 409 without changing the existing row. Direct
  `SeamRuntime` and store persistence remain deliberate internal upsert paths.
- Authenticated REST servers refuse non-loopback binds such as `0.0.0.0` unless the operator intentionally sets `SEAM_API_ALLOW_INSECURE_REMOTE=1` or places the API behind a TLS terminator. Bearer-token deployments should prefer loopback plus TLS reverse proxy for remote access.
- The built-in rate limiter is process-local. If `SEAM_API_RATE_LIMIT_PER_MINUTE` is enabled, `seam serve --workers` greater than 1 is refused unless `SEAM_API_ALLOW_PROCESS_LOCAL_RATE_LIMIT=1` is set after an external shared limiter is in front. `SEAM_API_RATE_LIMIT_MAX_KEYS` bounds tracked client keys.
- The `/chat` endpoint's outbound provider call is SSRF-guarded by a host allowlist: the caller-supplied `base_url` host must be a built-in provider (`_BUILTIN_CHAT_HOSTS`) or loopback (local Ollama); arbitrary hosts are rejected. Operators permit additional custom/self-hosted providers via `SEAM_CHAT_ALLOWED_HOSTS` (comma-separated) — an operator-set knob, never caller-set. The allowlist closes DNS-rebinding by construction; a resolved-IP range check (private/link-local/reserved/multicast/unspecified rejected, loopback exempt) is kept as defense-in-depth, and the outbound opener refuses 3xx redirects so a validated host cannot bounce to an internal address.
- Buffered `/chat` provider responses are bounded by
  `SEAM_CHAT_MAX_RESPONSE_BYTES` (default `5000000`). Declared oversized
  bodies refuse before reading; undeclared or malformed-length bodies are read
  through the same hard allocation cap. A rejected response is never compiled
  or persisted.
- Process-environment chat credentials are bound one-to-one to their built-in
  provider hosts. A request cannot select another variable name, custom hosts
  require an explicit caller-owned key, and validated loopback targets never
  consult `os.environ`. Both `/chat` and `/chat/stream` use the same resolver.
  `SEAM_API_TOKEN` remains optional only for explicitly trusted local
  development; automatic first-launch token provisioning is a separate
  authentication/UX policy boundary and is not implied by the credential-
  forwarding fix.
- Operator surfaces must distinguish live, unavailable, and demo data. Browser-
  local timers, random metrics, mock records, or fake command results must never
  be presented as successful runtime actions, and provider credentials must not
  be persisted in browser `localStorage`. Truthful backend acknowledgement and
  explicit error states precede beta or production-readiness claims.

## Benchmark Publication Policy

Holographic Surface claims must report `surface_exact_rate`, payload hash match
rate, direct query exactness, stored surface lookup, stored surface query after
original-output deletion, repair success, repair query exactness, and the PNG
mode (`bw1`, `rgb`/`rgb24`, explicit `rgba32`, or explicit `rgba64`).

Graph or reasoning-pattern superiority claims must also satisfy the R3 matched-
causal portfolio and independent R4 reproduction gate in
`docs/audits/2026-08-18-graph-benchmark-readiness-research.md`. LoCoMo-only,
implementation-conformance, saturated-parity, and provider-free placeholder
results must stay scoped to those narrower claims.

Published benchmark statements must include:

- command used
- bundle hash
- per-case hashes
- fixture hashes
- tokenizer/dependency state
- git SHA
- benchmark diff output comparing the claim run against its baseline
- benchmark gate output from `seam benchmark gate <bundle> [--baseline <run-a>]`
- holdout result bundle when the statement is an external or publication claim

Holdout benchmark fixtures live under `benchmarks/fixtures/holdout/` and are ignored by git by default. They must be run only with `seam benchmark run --holdout --confirm-holdout`, and default holdout result bundles are written separately under `benchmarks/runs/holdout/`.

## Benchmark Dataset Integrity Policy

The LoCoMo dataset was once lost because it lived only on the near-full root volume (`/`). To prevent silent recurrence, benchmark source datasets follow defense-in-depth:

- The canonical LoCoMo dataset is committed in-repo at `benchmarks/external/locomo/data/locomo10.json` (so it lives on T7 and offsite via the private GitHub repo), never only on the root volume.
- `benchmarks/external/locomo/data/locomo10.manifest.json` pins the source URL, SHA256, byte size, and sample/QA/category counts. Treat the SHA256 as the integrity authority — LoCoMo releases reuse `sample_id` labels across different content, so verify by hash, not by label.
- `python -m tools.benchmarks.restore_locomo` restores and SHA-verifies the dataset from, in priority order: the in-repo copy → the T7 durable copy (`.dataset_store/locomo/`) → the canonical network source. Use `--verify` before any run, `--ensure` to repair all standard locations, `--to <path>` for a specific target.
- The no-paid LoCoMo path (`--answerer none --judge none`) runs self-contained on the local `SQLiteVectorAdapter` with local `BAAI/bge-small-en-v1.5` embeddings; it does NOT require the Docker pgvector service. SQLite-vector and pgvector are score-equivalent for this workload (verified: both reproduce `context_recall_mean=0.528308`).
- `--keep-db` reuses per-scope SQLite DBs by `sample_id`; never reuse DBs ingested from a different dataset release on the same `--db-path`, or retrieval silently reads the wrong conversation. Use a fresh `--db-path` when the dataset version changes.
