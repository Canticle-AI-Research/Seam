# Status Stream: Retrieval

> Retrieval engine, ranking policies, semantic-edge admission, and qualification

_Source of truth for current state in this area. History lives in `HISTORY.md`._

## Status: QUALIFIED through the no-REL gate

One canonical engine. `RetrievalOrchestrator` owns SQL, vector, graph,
graph-node, and explicit temporal retrieval. `SeamRuntime.retrieve()` is the
canonical entry; `search_ir()` is a compatibility result/evidence adapter over
the same plan, not a second scorer.

Ranking policies are named and selectable: `legacy-weighted/1` (pre-refactor
RAW/BM25/vector weighted scorer, kept as one self-contained behavioral control
leg) and `reciprocal-rank-fusion/2`.

## Full provider-free gate (HISTORY#503 -> #506)

Every arm starts from an independent clone of one pristine ingest-only snapshot
and runs all 1,542 answerable LoCoMo questions with cached offline BGE, one
worker, no pgvector, and no provider, answerer, judge, decomposer, reranker,
network, or paid call.

| arm | overall recall | category 1 (n=282) | category 3 (n=96) |
| --- | ---: | ---: | ---: |
| `legacy-weighted` | 0.766420 | 0.633842 | 0.412697 |
| `hybrid` | 0.776178 | 0.642109 | 0.375922 |
| `mix` | 0.776178 | 0.642109 | 0.375922 |

`hybrid` and `mix` match on every case, context, selected ID, SQL leg, and
vector leg. The RRF path clears the versioned aggregate floor by `+0.009757`
and improves the target multi-hop category 1 by `+0.008267`; category 3 remains
`-0.036775` below the legacy control and stays an explicit residual risk.

This clears the provider-free aggregate non-regression hold. It does not
establish graph lift: the graph contributed no traversal candidate in this
corpus.

## Semantic-edge admission

Traversal adjacency admits only a `knowledge_edges` row backed by the exact
canonical MIRL `REL` record whose same-boundary, non-synthetic `ENT` endpoints
and predicate match the projected edge. Record-structure edges such as
`about`, `content`, `evidence`, `provenance`, and `excerpt_of` may ground a seed
or recover source evidence, but can never enter the traversal frontier.

When a boundary contains no admitted `REL`, traversal returns immediately with
`graph_skipped_reason=no_semantic_relation_edges`. The independent
`graph_node` semantic leg still runs when explicitly enabled. Across this full
gate, the skipped graph leg measured a `1.51 ms` median and `1.74 ms` p95.

## Content-free trace contract

`--save-retrieval-trace` exports `seam-retrieval-search-trace/1`, a bounded
allowlist containing plan shape, record IDs, numeric scores, counts, fusion
fingerprints, and latency only. Query text, normalized query, record payloads,
attributes, reasons, graph paths, filter values, temporal values, and lens text
are excluded. The 1,542-case recursive privacy audit found zero forbidden
fields or values.

Retrieval **mutates** the SQLite store, so every comparison arm must start from
an independent clone of one pristine ingest-only snapshot
(`benchmarks.external.locomo.ingest_only`). Cloning after a scored run is a
confound.

## Next gate

- Keep traversal fail-closed while canonical `REL` coverage is zero.
- When the operator clears the local-extraction pause, re-ingest an isolated
  clone and measure relation/entity coverage, endpoint coreference, predicate
  diversity, and multi-hop path yield before changing defaults.
- Build or adopt a query-aware edge/path scorer only after that substrate
  exists, then require a same-snapshot category-1 holdout gain over `hybrid`.
