---
handoff_id: 2026-07-30-semantic-graph-admission-qualified
supersedes: 2026-07-30-wandr-zero-network-replay-lane
handoff_status: superseded
history: HISTORY#506
---

# Handoff: semantic graph admission qualified

**Date:** 2026-07-30
**Branch:** `fix/semantic-graph-admission`
**Scope:** canonical semantic-edge admission, content-free retrieval traces,
and the full provider-free LoCoMo qualification

## One-line state

The unified retrieval path clears the aggregate legacy floor, but the pinned
LoCoMo graph has no admissible canonical entity-to-entity `REL` edges:
`hybrid` and `mix` are exactly equal, traversal correctly fails closed, and an
edge scorer remains gated on a future isolated semantic-extraction
qualification.

## Decision

Do **not** build or promote an edge scorer yet. Scoring structural
claim/evidence/provenance edges would only rank the seed record's closure.
Traversal now admits only an exact projection of canonical MIRL `REL`, so the
runtime cannot mistake record structure for semantic adjacency.

When the operator clears the local-extraction pause, the next bounded action is
an isolated re-ingest and coverage gate. Only measured relation coverage,
predicate diversity, endpoint coreference, and multi-hop path yield can
authorize query-aware edge/path scoring.

## What changed

- Graph traversal admits only an entity-to-entity edge backed by the exact
  canonical `ir_records.kind='REL'` record. Relation ID, predicate, endpoint,
  namespace, and scope must match, and both endpoints must be canonical
  non-synthetic `ENT` records.
- Structural edges may ground seeds and recover evidence, but they never enter
  the traversal frontier.
- A boundary with no admitted relation returns an empty traversal leg and
  `graph_skipped_reason=no_semantic_relation_edges`. The independent
  graph-node vector leg still works when enabled.
- Seed selection, SQLite lookups, source resolution, and fanout are bounded and
  chunked below SQLite's conservative variable floor.
- Exported traces use the bounded `seam-retrieval-search-trace/1` allowlist:
  plan shape, opaque record IDs, numeric scores, counts, candidate fingerprints,
  and latency. Query text, payloads, attributes, rationales, graph paths, filter
  values, temporal values, and lens text are excluded.
- `legacy-weighted/1` plans only its self-contained control leg. The old plan
  spent time running vector, graph, and temporal legs whose results the legacy
  ranker ignored.
- The two hash-pinned WANDR replay JSONL fixtures are tracked explicitly despite
  the repository-wide `*.jsonl` ignore rule, so clean worktrees reproduce the
  17-test replay audit.

## Full LoCoMo gate

All arms used independent clones of the same pristine ingest-only snapshot:
10 scopes, 5,882 turns, 1,542 answerable questions, cached offline BGE, one
worker, top-k 100, and an 8,000-character context budget.

| arm | overall recall | category 1 | category 3 |
| --- | ---: | ---: | ---: |
| `legacy-weighted` | 0.7664201903042236 | 0.6338417577496843 | 0.4126967778738289 |
| `hybrid` | 0.7761776456987288 | 0.6421086583741139 | 0.37592183956251296 |
| `mix` | 0.7761776456987288 | 0.6421086583741139 | 0.37592183956251296 |

`hybrid` and `mix` match on every case, retrieved context, selected record ID
and score, SQL candidate, and vector candidate. Traversal skipped 1,542/1,542
queries, with zero traversal hits, graph paths, graph-node hits, or selected
graph sources. The skipped graph leg measured 1.51 ms median and 1.74 ms p95.

The unified path therefore clears the aggregate legacy floor by
`+0.0097574553945052` and category 1 by `+0.0082669006244296`. Category 3 is
still `-0.0367749383113159` below the legacy control and remains an explicit
residual risk. This gate proves correct admission and aggregate
non-regression; it does **not** prove graph-incremental value.

## Verification

- Strict audit: 1,401 passed, 0 failed, 0 skipped, 0 xfailed; 23 external tests
  intentionally deselected, 1,424 total collected.
- Changed Python files: Ruff clean and `py_compile` clean.
- `git diff --check`: clean.
- Recursive trace privacy audit: zero forbidden fields or values across all
  1,542 cases.
- Candidate-file secret and private-session scan: zero findings.
- WANDR replay audit: 17/17 passed; both fixture hashes match the manifest.
- Every benchmark run used a sterile provider-free environment. There were no
  provider, answerer, judge, decomposer, reranker, pgvector, TCP, or UDP calls.
  A system Ollama daemon existed independently, but these runs did not inspect,
  contact, stop, or modify it.

Full retained artifacts are outside the repository at
`/media/terrabyte/T71/seam-benchmarks/semantic-graph-admission-20260730/`.

## Exact next step

1. Land this admission repair and the content-free trace contract through the
   protected PR workflow.
2. Leave extraction and Ollama untouched until the operator explicitly clears
   the pause.
3. Then re-ingest an isolated database clone with semantic extraction and
   measure `REL` coverage, endpoint quality, predicate entropy, reachable
   two-hop paths, and category-1 retrieval yield.
4. Only if that substrate is real, add adaptive depth gating plus
   query-to-verbalized-triple/path scoring and require an attributable
   category-1 holdout gain over `hybrid`.
