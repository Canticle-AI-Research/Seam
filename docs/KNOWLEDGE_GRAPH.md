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
retrieval policies still run through the real H2 scoring/proposal store and
apply-state path; this is not a disconnected demo loop.

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
- Real-model, provider, remote-worker, pgvector, and paid benchmark execution
  remain optional operator-configured boundaries; the local graph/workspace
  feature does not require any of them.
