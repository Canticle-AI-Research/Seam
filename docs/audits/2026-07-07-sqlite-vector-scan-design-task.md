# Design task: SQLiteVectorIndex full-scan search (default local backend)

- **Date:** 2026-07-07
- **Status:** SCOPED, not started — pick up as its own work item
- **Origin:** HISTORY#362 handoff (`docs/handoffs/2026-07-07-cat1-cat3-scoping-handoff.md`, perf bug #2) + new measurements from HISTORY#363

## Problem

`seam_runtime/vector.py` `SQLiteVectorIndex.search()` brute-force scans every
stored vector for the model on every query: `SELECT` all rows, `json.loads()`
each `vector_json`, cosine each one, heap the top-k. This is the **default
local backend** (no pgvector configured), so every local SEAM search pays it,
and it degrades linearly with corpus size. PR #121's HNSW work covers only the
opt-in pgvector backend, not this path.

## Measurement that constrains the design (HISTORY#363)

The HISTORY#362 handoff recommended a numpy `cosine()` rewrite as the fix's
first half. Measured before building (2000 stored vectors, dim=1152, the
real search-loop shape):

| variant | time | note |
|---|---|---|
| `json.loads` + pure-Python cosine (status quo) | 0.810 s | |
| `json.loads` + numpy cosine, query converted once | 0.642 s | only 1.3x |
| `json.loads` alone | 0.563 s | **88% of the optimized loop** |

**The scan is JSON-deserialization-bound, not cosine-bound.** The numpy
cosine landed in HISTORY#363 (free, safe, helps every caller), but no cosine
implementation can buy more than ~1.3x here. Any real fix must eliminate the
per-query `json.loads` of every stored vector.

## Design options (decide deliberately, in roughly increasing invasiveness)

1. **Per-connection in-memory matrix cache.** On first search, load all
   vectors for `(model, dimension, namespace)` into one `numpy` float32
   matrix + record-id list; score with a single matvec + `argpartition`.
   Invalidate on a cheap `SELECT count(*), max(updated_at)` fingerprint.
   No schema change; memory cost ~4 bytes × dim × corpus (float32, ~46 MB per
   10k vectors at dim=1152); must handle multi-process writers (MCP server +
   CLI share the DB — fingerprint check per query keeps it correct).
   numpy becomes required for the fast path only; fallback stays.
2. **BLOB storage.** Store vectors as packed float32 bytes instead of JSON
   (`numpy.frombuffer` is near-zero-cost vs ~281 µs/row for `json.loads` at
   dim=1152). Schema migration required (new column or dual-read window for
   existing `vector_json` rows); pairs well with option 1.
3. **Real ANN index for SQLite** (e.g. sqlite-vec extension or an on-disk
   HNSW). Biggest win at large corpora, biggest dependency/portability
   decision; only worth it if 1+2 prove insufficient at target corpus sizes.

## Recommendation

Do 1, then 2 behind a dual-read migration; defer 3 until a measured corpus
size demands it. Validate each step with the free recall A/B ladder (results
must be byte-identical — this is a perf change, not a ranking change) plus a
wall-clock benchmark at LoCoMo-10 scale.

## Constraints

- Default-path behavior: search results (ids, scores, ordering) must not
  change. Parity tests like `tests/audit/test_cosine_numpy_parity.py` set the
  pattern.
- numpy must remain optional for core installs (`rich` + `tiktoken` only);
  pure-Python fallback keeps working.
- One heavy job at a time on this box when benchmarking (GPU/CPU contention,
  see the HISTORY#362 handoff's environment notes).
