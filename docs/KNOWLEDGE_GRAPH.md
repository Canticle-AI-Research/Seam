# SEAM Knowledge Graph

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
