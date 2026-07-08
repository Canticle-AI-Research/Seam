# Design task: SQLiteVectorIndex full-scan search (default local backend)

- **Date:** 2026-07-07 (updated 2026-07-08)
- **Status:** Option 1 IMPLEMENTED (HISTORY#364); options 2–3 still future.
- **Origin:** HISTORY#362 handoff (`docs/handoffs/2026-07-07-cat1-cat3-scoping-handoff.md`, perf bug #2) + new measurements from HISTORY#363

## Update 2026-07-08 (HISTORY#364): option 1 landed

Option 1 (in-memory matrix cache) is implemented in `seam_runtime/vector.py`:
an instance-level cache keyed by `(model_name, dimension, namespace)` holding
the deserialized float64 matrix + per-row norms, invalidated by a cheap
`(row count, max updated_at)` fingerprint checked on every search (so writes
from this process **or another** — the MCP server and CLI share the DB — force
a rebuild). This kills the per-query `json.loads` (the measured 88%) and
amortizes deserialization across queries (the write-once/query-many benchmark
pattern). Measured **7.5x** on a 400–800 row hash-embedding corpus; the real
LoCoMo win is larger because the paid benchmark issues hundreds of queries
against a static corpus.

**Byte-identical, verified.** `tests/audit/test_vector_cache_parity.py` pins
the cached path to return the SAME record ids, order, and float scores as the
pure-Python scan. Getting there required two non-obvious matches:
- score PER ROW with `query @ matrix[i]` (a single batched `matrix @ query`
  gemv rounds differently and flipped tied records — 47/150 reorders measured);
- compute row norms **per row** at cache-build (`norm(matrix[i])` in a loop),
  NOT the batched `norm(matrix, axis=1)`, whose reduction also rounds
  differently and flipped ties.
With both, parity is exact (max score diff `0.0`, 0 reorders) even on the
tie-heavy hash embedding — the hardest case for identity.

numpy stays optional: `search()` falls back to the original pure-Python
per-row scan (`_search_scan`) when numpy is absent. What remains for options
2–3: the scan is still O(N) dot-products per query (now cheap, no json); BLOB
float32 storage would shrink cache-build + memory, and an ANN index would make
search sub-linear. Those are still future and still gated on a measured
corpus-size need.

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
