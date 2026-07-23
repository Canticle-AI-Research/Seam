# SEAM RAG Architecture

SEAM uses MIRL as the canonical memory graph and keeps vector stores as derived
indexes.

## Competitive Notes

LightRAG is strong at document ingestion, entity/relation extraction, graph plus
vector retrieval, WebUI graph exploration, reranking, and incremental updates.
SEAM now adopts the same practical retrieval shape while keeping its own
contract: canonical meaning lives in MIRL records stored in SQLite.

claude-mem is strong at agent integration: one-command install, automatic
capture, progressive disclosure, and Claude Code ecosystem fit. SEAM follows
that pattern with command-first install docs, compact `memory search`, full
`memory get`, and a standard MCP stdio server that wrappers can sit on top of
without rewriting the Python runtime.

## Data Flow

1. `seam ingest <path> --persist` reads text and compiles MIRL records.
2. `document_status` records source ref, source hash, byte count, chunk count,
   extraction status, and index status.
3. `ir_records` stays canonical for claims, states, events, entities, and
   relations.
4. `ir_edges` stores derived graph edges from MIRL refs, relations, evidence,
   and provenance.
5. `vector_index` stores derived embeddings with source hashes for cache/stale
   detection.
6. Retrieval builds a compact PACK only after records are selected.

## Retrieval Modes

- `vector`: embedding-only semantic recall through the configured vector
  adapter.
- `graph`: MIRL edge expansion over entities, relations, evidence, and
  provenance.
- `hybrid`: structured SQL plus vector recall.
- `mix`: SQL, vector, and graph legs merged together. Use this for agent RAG
  unless a benchmark says another mode is better for the task.

Example:

```powershell
seam retrieve "persistent memory" --mode mix --budget 5 --trace
seam context "persistent memory" --retrieval-mode mix --view prompt
```

## Progressive Disclosure

Use compact search before fetching full detail:

```powershell
seam memory search "benchmark gate"
seam memory get clm:1,clm:2 --timeline
```

This keeps prompt cost low. Agents inspect IDs, summaries, refs, and scores
first, then fetch full MIRL only for selected records.

## Agent Bridge

`seam mcp stdio` and the `seam-mcp` console script start a standards-compliant
MCP JSON-RPC server over stdio. Gemini CLI, Claude Desktop, Cursor, OpenCode,
and other MCP clients can configure it as a local stdio server and discover
these SEAM tools:

- `seam_memory_search`
- `seam_memory_get`
- `seam_ingest`
- `seam_stats`
- `seam_documents`
- `seam_context`
- `seam_doctor`
- `seam_surface_list`
- `seam_surface_show`
- `seam_surface_query`
- `seam_surface_decode`
- `seam_surface_verify`
- `seam_surface_context`
- `seam_index_status`
- `seam_retrieve`
- `seam_benchmark_latest`

The MCP server is intentionally thin: it adapts MCP `initialize`, `tools/list`,
and `tools/call` to the existing SEAM runtime dispatcher. The older
`seam mcp serve` JSON-lines bridge is retained for legacy local wrappers, but
new agent integrations should use `seam mcp stdio`.

For agents that should use the real pgvector adapter, start the MCP server with
`--ensure-pgvector`. That flag reads the private env file from `SEAM_LOCAL_ENV`,
`~/OneDrive/Documents/SEAM/local/.env`, or a local ignored `.env`, starts the
repo Docker Compose `pgvector` service, waits for the `seam-pgvector` container
to become healthy, creates the `vector` extension if needed, sets
`SEAM_PGVECTOR_DSN` only in the server process, and then begins MCP JSON-RPC
serving. Startup logs go to stderr so stdout remains valid MCP messages.

Gemini project-local config:

```json
{
  "mcpServers": {
    "seam": {
      "command": "python",
      "args": ["-m", "seam_runtime.mcp_protocol", "--ensure-pgvector", "--pgvector-timeout", "120"],
      "cwd": ".",
      "timeout": 120000,
      "trust": false,
      "description": "SEAM local memory runtime MCP server with pgvector auto-start"
    }
  }
}
```

## Stale Index Detection

The SQLite vector index records a source hash for each vectorized record. When
`seam reindex` runs, the report includes `stale_before` entries for missing,
changed, or dimension-mismatched vectors before they are refreshed.

Example:

```powershell
seam reindex
```

PgVector follows the same derived-index rule. If the embedding model or vector
dimension changes, reindex vectors instead of treating the old vector table as
canonical memory.

Pgvector rows written before namespace/scope boundaries were enforced at the
adapter level (or moved across namespace/scope after indexing) carry stale
`namespace`/`scope` metadata even though their embedding is still valid. Repair
this without re-embedding:

```powershell
seam reindex --boundary-only --namespace <ns> --scope <scope>
```

`--boundary-only` calls `PgVectorAdapter.sync_boundaries`, which updates only
the `namespace`/`scope` columns for rows whose `source_hash`/dimension still
match the canonical MIRL record; rows with content drift or a missing vector
row are reported (`skipped_content_changed`, `skipped_missing`) but not
touched — rerun a full `seam reindex` for those. `--namespace`/`--scope`
scope which MIRL records are considered; omit both to sweep every record.

This is conservative on purpose and can under-fire: plain (non-RAW,
non-grounded-CLM) records carry a text-render that is sensitive to `attrs`
dict key order, and the CLI's storage reload does not preserve the original
insertion order, so an unchanged record can fail the hash check and land in
`skipped_content_changed` instead of getting its boundary repaired. If a
boundary-only sweep leaves records behind, a full `seam reindex` (re-embeds)
is the fallback.

## Boundaries

- SQLite remains canonical.
- Vector stores and graph edges are rebuildable.
- Reranking belongs behind the optional `rerank` extra.
- External agent ecosystem wrappers belong outside the core runtime unless they
  are small bridge shims.
- Benchmark claims still require verified bundles, diffs, and gates.
