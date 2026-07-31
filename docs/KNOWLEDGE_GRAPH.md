# SEAM Deep Knowledge Workspace

SEAM maintains one persistent, self-building knowledge graph over all canonical
MIRL knowledge. Operators and agents do not draw nodes or maintain edges by
hand. Any successful write through chat, REST, MCP, the CLI, ingestion, or
direct MIRL persistence updates the graph in the same SQLite transaction.

## What the graph contains

The projection distinguishes semantic knowledge from its evidence:

- nodes: agents, entities, claims, events, relations, states, values, sources,
  evidence spans, provenance activities, symbols, packs, flows, and metadata;
- edges: direct semantic predicates plus grounding, evidence, provenance, and
  agent-contribution relationships;
- episodes: immutable RAW source observations with content hashes, source refs,
  contributing agents, namespaces, scopes, and recorded/valid times;
- temporal state: `valid_from`, `valid_to`, status, and `expired_at` preserve
  current and historical views without silently overwriting earlier claims.
- identity terms: `knowledge_node_terms` indexes scoped canonical entity names,
  explicit aliases, symbols, agents, and short concept literals with source
  record provenance. Assertion labels, episode text, and sentence-like literal
  values are excluded so source prose cannot masquerade as extra concepts.

MIRL and RAW remain the canonical truth. `knowledge_nodes`, `knowledge_edges`,
and `knowledge_episodes` are durable indexed projections that can be rebuilt
from `ir_records`. PACK and dashboard views remain disposable presentations.

## 5W1H+Then ontology

Every claim, relation, event, and state may expose a conservative derived lens:

- **who** (`performed_by`): actor, subject, source entity, or responsible agent;
- **what** (`about`): object, affected entity, or outcome under discussion;
- **when** (`occurred_at`): canonical record time or an explicit timestamp;
- **where** (`located_in`): only an explicit location already present in MIRL;
- **why** (`caused_by`): only an explicit reason or causal relationship;
- **how** (`via`): only an explicit method, tool, or mechanism;
- **then** (`resulted_in`): a result, successor, outcome, or temporal next step.

This is a rebuildable graph lens, not a second truth store. Explicit
`attrs.facets` win; conservative MIRL field and predicate-family fallbacks fill
only facts already present. Missing `where`, `why`, or `how` values stay missing
rather than being guessed. The compiler can emit grounded relation/event/state
records when the extractor supplies evidence-localized structured output.

## Evidence-gated trust

The graph derives one of seven trust states for assertion-bearing records:
`verified`, `supported`, `contested`, `unverified`, `refuted`, `stale`, or
`superseded`. Multiple independent evidence paths can verify a claim; one can
support it. Model or agent output remains provenance but is not independent
corroboration. Contradiction/refutation, temporal validity, lifecycle state,
hypothetical status, namespace, and scope all participate in the decision.

Only current `supported` and `verified` claims, relations, events, and states may
enter an asserted chat system prompt. Unknown IDs, cross-namespace/scope IDs,
model-only claims, and every non-assertable trust state fail closed. Descriptive
and evidence records are also rejected when their only provenance is model
output. Rejected records are not deleted or hidden: graph/history/workspace
exploration retains them with their trust labels. Both `/chat` and
`/chat/stream` use this same boundary.

## Automatic build lifecycle

1. SEAM compiles or accepts MIRL.
2. `SQLiteStore.persist_ir` reconciles canonical entity IDs and writes MIRL.
3. The graph projector removes topology sourced by the previous version of any
   updated record, then upserts its nodes, semantic edges, provenance, agents,
   and source-episode links.
4. SQLite commits the MIRL record and graph projection atomically.
5. Re-ingesting the same `source_ref` expires the old episode for current-view
   queries while preserving it for history and knowledge-horizon inspection.
6. Opening an existing database performs a one-time versioned backfill, so old
   SEAM knowledge appears without manual migration.

The identity index is part of that rebuildable projection. Alias rows never
rewrite canonical MIRL or silently merge entities; reversible entity merges and
conflict handling remain a later graph-maturity stage.

The deterministic compiler always produces grounded source, entity, claim,
value, evidence, and provenance topology. When the configured NL extractor
emits richer MIRL `REL`, `EVT`, `STA`, or structured `CLM` records, those become
direct typed semantic relationships automatically. Agents can also persist
structured MIRL directly when they already know the relation shape.

## Product surfaces

Browser dashboard:

- open `/` and select Memory, or deep-link to `/?view=knowledge`;
- search nodes and facts, filter by type or contributing agent, change traversal
  depth, and inspect the current graph or a historical knowledge horizon;
- select any node to open its graph-backed knowledge page with facts,
  backlinks, agents, source episodes, validity, confidence, and canonical MIRL.

CLI:

```bash
seam knowledge search "billing service" --agent-id codex --hops 2
seam knowledge search --root-id ent:billing --history --format json
seam knowledge node ent:billing --at 2026-07-01T00:00:00Z
```

REST:

```text
GET /knowledge-graph?query=billing&agent_id=codex&hops=2
GET /knowledge-graph?root_id=ent:billing&include_history=true
GET /knowledge-node?node_id=ent:billing&include_history=true&at=2026-07-01T00:00:00Z
```

MCP:

- `seam_ingest` accepts `agent_id` so each agent's contribution is attributable;
- `seam_knowledge_graph` searches and traverses the graph;
- `seam_knowledge_node` opens a page with facts, backlinks, agents, and sources.

Structured workspace and replay:

```text
GET  /workspace/capabilities
GET  /workspace/events?after=<event-id>&limit=200
GET  /workspace/runs
GET  /workspace/runs/<run-id>
POST /chat/stream                         # POST-backed SSE
```

`workspace_run` and `workspace_event` are append-only SQLite telemetry. Events
have monotonic per-run sequence numbers and stable IDs, and replay uses the same
wire object emitted over SSE. The allowlisted event vocabulary is: run,
retrieval, graph activation, reasoning summary, J-lens concept, tool,
hypothesis, decision, verification, answer delta, completion, and failure.
Payload schemas recursively remove unknown fields, credential-shaped keys,
hidden chain-of-thought, tensor-shaped data, and raw activation fields before
persistence. A stream emits exactly one terminal completion or failure event.

Workspace telemetry is operational trace, not canonical knowledge. Only a
separate, explicit MIRL persistence step turns selected conclusions into durable
knowledge.

The durable reasoning graph is a third, bounded role alongside canonical
knowledge and live telemetry. It anchors typed objectives, premises,
hypotheses, inferences, decisions, and outcomes to `workspace_run`, with exact
knowledge/MIRL evidence references and append-only state history. It is public
justification, never hidden chain-of-thought, and it cannot promote itself into
MIRL. R2 adds a fixed retrieval decision and content-free candidate ledger:
bounded selected and rejected record IDs, boundary/content fingerprints,
scores, controlled reason codes, plan/policy/model identity, and latency.
Record payloads stay in MIRL and are never copied into that ledger. See
`docs/REASONING_GRAPH.md`.

## Honest J-lens capability boundary

SEAM distinguishes structured workspace trace from activation-derived J-lens
concepts. Hosted-provider summaries, retrieval paths, tools, hypotheses, and
decisions are never labeled as hidden reasoning or J-Space. A genuine J-lens is
reported only when the configured worker can inspect model internals and verify
the exact model/revision and model/lens artifact SHA-256 identities.

The default capability is `structured_workspace_only`: no model weights are
bundled, no network request or download occurs, and no raw activations are
persisted. Two opt-in adapters exist:

- local Hugging Face Qwen: requires `torch`/`transformers`, an external
  activation-capable analyzer, a local model manifest, a lens artifact, and
  matching hashes; downloads remain off unless explicitly enabled;
- authenticated remote worker: requires HTTPS except for loopback, an
  operator allowlisted host, exact DNS/IP pins, bounded no-redirect responses,
  a bearer token, and matching returned model/revision/artifact identities.

Configuration is operator-owned through `SEAM_JSPACE_BACKEND` plus the
`SEAM_JSPACE_*` model, revision, hash, artifact/analyzer, remote URL/token,
allowlist, pin, and timeout variables. Tokens and artifacts remain outside the
repository. A configured remote endpoint is only
`jacobian_lens_pending_identity` until a response proves its identity.

## Dashboard layers and LIVE

The Memory workspace exposes seven independently selectable layers:
**Knowledge**, **5W1H**, **Episodes**, **Trust**, **Workspace**, **Activation**,
and **Improvement**. Knowledge, 5W1H, episode, and trust layers show durable
graph state. Workspace and Improvement show structured operational/audit events.
Activation is explicitly marked unavailable when no genuine J-lens capability
is connected.

The **LIVE** control polls the append-only event cursor and advances a structured
signal tape; with LIVE off, the same events can be scrubbed or replayed. A live
feed failure does not invalidate or hide the durable graph. Edge IDs are unique
in the API response: provenance contributors for the same episode/node pair are
aggregated into one edge with `contributing_record_ids`, preventing duplicate
rendered relationships without discarding provenance.

## Graph-derived improvement ratchet

The free H2 cycle can generate deterministic probes from the live graph across
seven motif families: 5W1H+Then completeness, multi-hop paths, causal/temporal
chains, trust/evidence state, provenance, and related graph structure. Candidate
retrieval policies include bounded semantic graph-node seed counts and score
floors. They run through the real H2 scoring/proposal store, disjoint holdout
gates, operator approval, applied-state, and revert path; this is not a
disconnected demo loop. `SeamRuntime.knowledge_graph` consumes the applied
state, so an approved policy changes subsequent SDK, CLI, MCP, REST, and
internal graph searches. Environment overrides remain explicit operator-owned
precedence.

Promotion is fail-closed. Aggregate, category, integrity, trust, temporal,
provenance, and holdout gate families are all required, with nonblank evidence
references. Any failed, malformed, duplicate, missing, non-finite, or holdout-
violating gate records an append-only rejection. A complete pass becomes
`pending_approval` with `can_apply=false`; even the legacy `auto_approve` option
cannot bypass the operator decision. `improvement review apply` considers only
explicitly approved, non-violating proposals whose stored ratchet passed.

## Retrieval behavior

The graph retrieval leg reads `knowledge_edges`, not the legacy minimal
`ir_edges` table. This means the topology used by agents is the same topology
shown in the dashboard, including typed predicates and current-state filtering.
Graph hits still resolve back to MIRL records for ranking, packing, and complete
RAW/provenance backtraces.

Traversal is stricter than projection. An edge can enter adjacency only when it
is the exact entity-to-entity projection of a canonical MIRL `REL`: its relation
ID, source entity, destination entity, predicate, namespace, and scope must all
match, and both endpoints must be canonical non-synthetic `ENT` records.
Structural edges that attach claims, values, evidence, excerpts, sources, and
provenance remain useful for seed grounding and evidence backtraces but never
enter the traversal frontier. When no admissible `REL` exists, traversal returns
an empty leg with `graph_skipped_reason=no_semantic_relation_edges`; explicit
graph-node semantic retrieval remains independent of that skip.

## Relation extraction qualification

The existence of graph tables does not establish a semantic traversal
substrate. Before any adaptive-depth or query-aware relation/path scorer is
built, an isolated extracted corpus must pass the provider-free
`relation-extraction-qualification/1` gate over a pinned SQLite snapshot.

The gate uses the same canonical admission joins as runtime traversal and
reports a strict funnel: pinned RAW turns, persisted `REL` records, admitted
REL-backed entity edges, admitted relations with complete RAW backtraces,
relation-bearing turns, unique entity pairs and predicates, hub degree, and
incremental two-hop reachability. Every admitted relation must make three
independent paths converge on the same source RAW record:
`REL -> SPAN -> RAW`, `REL -> PROV -> RAW`, and
`knowledge edge -> edge episode -> source RAW`. Stored field-level subject,
predicate, and object spans must reproduce the exact RAW slices. Direct-write
`mirl://` episodes, dangling references, self-loops, cross-boundary endpoints,
and projected edges that do not exactly match their canonical `REL` fail the
extraction gate.

Structural validity is not semantic precision. The qualifier therefore emits
a separate deterministic predicate- and hub-stratified review template. All
relations are reviewed below 50; otherwise at least 50 are reviewed. The
analyzer makes no provider or model calls, and its publishable report contains
only counts, opaque IDs, and digests. It consumes the hash-pinned,
content-bearing label file and requires both point precision at or above 0.90
and a 95 percent Wilson lower bound at or above 0.80. The review template
contains source evidence and is not a publishable benchmark summary.

The predeclared substrate floor is:

- at least 30 admitted relations;
- admitted relations on at least 10 percent of the pinned RAW-turn
  denominator;
- exact admission and backtrace for 100 percent of persisted relations;
- no self-loop or cross-namespace/scope relation;
- maximum undirected distinct-neighbor degree no greater than
  `max(8, ceil(0.05 * unique_relation_edges))`.

Counts below the floor are insufficient evidence, not a weak pass. A zero-REL
corpus is a failure. Scorer eligibility additionally requires predicate
diversity and incremental two-hop paths whose two edges backtrace to distinct
RAW turns; a same-turn motif does not demonstrate the cross-turn coreference
needed for multi-hop retrieval.

Run the read-only analyzer only after independently pinning the corpus RAW
identity:

```bash
python -m tools.relation_extraction_qualification corpus.db \
  --expected-turns <count> \
  --expected-raw-digest <sha256> \
  --review-template <external-review-path>.json
```

Complete the five boolean judgments per sampled relation in the external
template, then rerun the same command with the template passed to `--labels`.
`passed` qualifies the extraction substrate; `scorer_eligible` is the stricter
authorization for adaptive depth and relation/triplet scoring.

G3 can explicitly seed graph traversal from both in-boundary semantic
fact/episode MIRL hits and versioned graph-node vectors for entities, values,
agents, and symbols. Graph-node hits enter `reciprocal-rank-fusion/2` as the
explicit `graph_node` leg and retain exact MIRL source-record resolution, rather
than acting as invisible traversal hints. A semantic
seed receives graph credit only when an actual current edge connects it. The SDK
opts into that behavior for `ReasoningSession.retrieve`; existing orchestrator
callers retain the default-off semantic-seeding behavior. Ranking is
deterministic. The versioned `reciprocal-rank-fusion/2` policy ranks within
each leg, maps rank to `1 / (60 + rank)`, sums those comparable contributions,
and fingerprints the contract in each new R2 decision; raw leg scores remain
visible in the live trace instead of being compared across incompatible score
domains. Exact historical paths and episode backtraces are returned for
hop-positive graph hits. A provider-free 2,048-node/2,047-edge fixture now
gates filter, 1-hop, 3-hop, historical, and semantic-seeded mixed query shapes
for expected evidence, exact path length, boundary isolation, deterministic
ranking, cross-leg evidence, and latency. A second provider-free gate verifies
the pinned LoCoMo corpus hash, complete versioned node-vector coverage, explicit
`graph_node` fusion traces, bounded candidate selection, and disjoint
development/holdout motif recall. With cached
`BAAI/bge-small-en-v1.5`, 4 seeds improved development recall by 0.1795 and
holdout by 0.1667; larger 8/16/32 candidates were refused when a motif
regressed. Native vector top-K prefilters namespace and scope; existing
pgvector indexes from before the scope column require an explicit resync
because canonical SQLite cannot backfill the external table.
Boundary-only resync updates metadata without calling the embedding model
again.

The default-off graph-to-source-RAW lane seeds only from
`knowledge_node_terms`. Its agreement score is a deterministic maximum
one-to-one match between supporting graph concepts and distinct query tokens:
one long label cannot count as several concepts, and several nodes matching the
same query word cannot inflate agreement. Selected paths still terminate at
exact `knowledge_episodes.source_record_id` values and enter only a
non-displacing RAW PACK.

The staged path from this identity foundation through hybrid path search,
summaries/observations, context assembly, lifecycle, and scale qualification is
maintained in `docs/roadmap/GRAPH_MEMORY_MATURITY.md`.

## Trust boundaries

- The graph never invents client-side topology; the browser renders only API
  nodes and edges.
- Agent and source attribution is metadata, not an authorization boundary.
  Namespace/scope controls and API authentication still govern access.
- Inferred, contradicted, superseded, and deleted knowledge remains explicitly
  labeled. Current queries exclude inactive knowledge; history queries retain it.
- Extraction confidence and record status travel with projected facts. The graph
  does not promote a hypothesis into an asserted fact.
- Structured reasoning summaries and graph activation are observable telemetry;
  they are not hidden chain-of-thought or raw neural activations.
- Durable reasoning nodes are non-canonical public artifacts. Cross-run edges
  and cross-namespace/scope evidence references fail closed, and accepted
  conclusions require explicit support.
- Real-model, provider, remote-worker, pgvector, and paid benchmark execution
  remain optional operator-configured boundaries; the local graph/workspace
  feature does not require any of them.
