# R2 backend exactness and scale evidence

This slice starts at protected `main@5f115664` (PR #253), following the
[structured SQLite](../../docs/handoffs/2026-09-06-r2-sqlite-scale-next.md) and
[temporal/compatibility acquisition](r2-acquisition-parity.md) slices.
The operator approved exact vector search by default, explicit approximate
search, and smaller record IDs first at equal scores. `legacy-weighted/1`
remains the compatibility default. No paid evaluation, publication or deployment
is part of this qualification.

## Search contract

`SeamRuntime(vector_search_mode="exact")` and `SEAM_VECTOR_SEARCH_MODE=exact`
select the default policy. `approximate` opts supported backends into ANN.
The explicit constructor value overrides the environment; selection remains
stable for that runtime. Injected adapters retain their own policy. Public
plans and traces report the actual adapter mode, `unknown` for an undeclared
custom adapter, or `unused` when no vector leg executes. SQLite always searches
exactly. Ranking-policy selection is separate from vector search mode.

Exact parity means identical ordered IDs and unrounded cosine scores for
identical original embeddings under the same scoring implementation. The
existing `models.cosine` arithmetic is unchanged. This does not promise
bit-identical arithmetic across arbitrary numerical libraries or hardware.
Native float32 storage cannot preserve every original winner: for query
`[1, 0]`, vectors `[1, 1]` and `[1.00000001, 1]` have distinct original scores
but collapse to a native float32 tie.

SQLite fixes cutoff membership before final sorting and hashes ordered vector
contents within the same snapshot used for cache refill. Equal or backdated
timestamps cannot conceal replacement. PostgreSQL stores versioned original
JSON vectors alongside its native index and streams an exact statement through
a named server cursor. Current rows without valid originals require explicit
migration/reindex; search performs no DDL or hidden embedding repair.

Exact Chroma scores originals retained in Chroma metadata. It pages canonical
IDs, validates complete eligible coverage and model/render/source metadata,
then selects winners. RAW exclusion applies before coverage and selection.
Persistent embedded collection locks use the client's actual storage path,
tenant, database and collection, before the canonical snapshot opens. Opaque or
nonpersistent clients receive a conservative process-local lock. Arbitrary
external collection writes and remote-service atomicity are outside that
locking guarantee. Existing projections need explicit synchronization to
populate original-vector metadata; a different embedding space needs a
compatible separate collection.

The wrapped SQLite/pgvector semantic adapter expands exact candidate prefixes
until it fills the eligible page or exhausts the backend. Canonical MIRL
hydration stays paged. This repairs filters and RAW exclusion consuming the
initial cutoff. Approximate/custom adapters retain their subset behavior.

PostgreSQL ANN orders the dimension-cast expression matching its HNSW index,
uses a literal dimension predicate, and applies transaction-local search
settings. It reranks selected originals. Chroma ANN retains native-distance
scores. Both remain approximate: post-query sorting cannot recover omitted
members or global cutoff ties. Exact parity evidence does not establish ANN
recall or promote a ranking default.

## Portable regression witnesses

| Contract | Source witness |
| --- | --- |
| SQLite ties, original precision, replacement, snapshots and selective work | `tests/audit/test_s8_r2_sqlite_vector_parity.py` |
| Real PostgreSQL precision, migration, model/boundary isolation, plans and cursor memory | `tests/audit/test_s8_r2_pgvector_parity.py` |
| Real Chroma precision, coverage, RAW eligibility and collection locking | `tests/audit/test_s8_r2_chroma_exact.py` |
| Filters beyond the initial cutoff; SQLite/Chroma result and score parity | `tests/audit/test_s8_r2_semantic_admission.py` |
| Mode selection, public traces and custom adapter compatibility | `tests/audit/test_s8_r2_vector_search_modes.py` |

The dedicated pgvector CI job runs the new PostgreSQL module. Required
`chroma-real-smoke` runs both real-Chroma external selections after installing
the explicit Chroma extra. `test_github_pr_gates.py` checks that every external
test file has a backend execution lane. Core test collection requires neither
service and deselects external tests explicitly.

## Separate cost measurements

These are deterministic synthetic fixture measurements, not production SLOs
or task-quality benchmarks. Local raw evidence lives under
`test_seam/r2-backend/`; preserve it under the primary checkout's
`.seam/orchestration/completed/` before removing the worktree.

| Fixture | Measured result |
| --- | --- |
| SQLite selected 8, unrelated 0 / 128 / 1024, warm cache | 99 SQLite VM steps and 792 retained vector/ID bytes at each size; no JSON decoding |
| SQLite selected 128 / 1024, warm cache | 819 / 6195 VM steps; 11,832 / 94,872 retained vector/ID bytes |
| PostgreSQL selected 64, unrelated namespace/model groups 512+512 / 8192+8192 | Actual exact cursor plans return 64 rows, filter no unrelated rows, and use 7 / 8 shared blocks |
| PostgreSQL selected 257 / 4097, limit 5 | Maximum page 128; traced client allocation peak 52,276 / 53,651 bytes |
| PostgreSQL ANN collections 2048 / 8192 | Unforced HNSW admission with boundary filters and automatic/generic prepared plans; actual search settings recorded |
| Real Chroma selected 64 projected records plus one canonical subject; unrelated namespace/scope groups each 0 / 128 / 1024; separate model collection 0 / 128 / 1024 | Direct and public retrieval each retain identical IDs/scores, 1669 canonical SQLite VM steps, 65 canonical rows and one 64-ID Chroma page at every size |
| Filtered exact admission, 180 distractors, four query-only samples per backend | Wrapped SQLite repeats query embedding 5 times for prefixes 15 / 30 / 60 / 120 / 240; real Chroma embeds once; identical ordered IDs and public scores in all samples |
| Same instrumented synthetic admission fixture, first / three warm samples | SQLite 26.63 ms / 24.01–24.16 ms; Chroma 12.10 ms / 5.43–6.01 ms |

The PostgreSQL numbers were independently reproduced. SQLite cache storage
remains O(ND) per selected slice, and multiple slices can coexist. Its uncached
path retains no vector matrix. Exact Chroma and PostgreSQL still perform
O(ND) selected-vector work and retain original-vector storage copies. MIRL
pages and winner heaps are bounded; progressive wrapped admission can retain
growing scalar prefixes, repeat scans and repeat query embedding calls.
Latency samples, retained storage, allocation measurements and quality must
remain separate. Local synthetic embedding calls are not billed-provider token
measurements.
The Chroma growth witness was independently reproduced on the final test
source. It measures canonical SQLite work and real Chroma ID acquisition
separately; Chroma's internal CPU/storage work is unmeasured. Model isolation
uses supported separate collections, not a canonical-record model filter.
The admission probe uses a local counting embedding model: invocation counts
measure repeated work, not tokenizer output or billed provider tokens. Reusing
one query embedding across exact prefix expansion is a concrete future cost
optimization; it must preserve the verified scoring and snapshot contracts.

## Qualification checkpoint

SQLite, PostgreSQL, mode/CI integration, and the repaired Chroma source have
focused evidence. Independent review found and prompted fixes for a wrong
custom-wrapper mode, duplicate custom lock acquisition, RAW eligibility and
injected-client lock identity. Historical failures remain recorded.

The first broad local run was interrupted after fixture mismatches and an
inherited PostgreSQL setting affected tests outside `tests/conftest.py`.
Credential-bearing traceback content was redacted immediately. Subsequent
non-external commands explicitly unset both PostgreSQL DSN variables. Legacy
test doubles were updated without weakening their assertions.

The final non-external integration command in
`tests/docs/s8-completion.md` completed: 3540 passed, 65 deselected, 2 xfailed, 2 warnings in 508.17s (0:08:28).
`test_seam/r2-backend/resume/full.json` binds unchanged runtime/test/CI hashes
and its raw output. The live backend suite passed 64 cases before the growth
addition; the final real-Chroma selection passed 25 cases with five explicit
non-external deselections, and independent growth assurance passed the added
case. No skip was admitted. Independent standards and spec reviews report no
unresolved blocker. HISTORY#641 records protected PR #254, its independently
stored release receipt, the identical merge tree and exact-main required/backend
checks. The S8 source freeze is `2f9a96b9`; the measurement limits above remain.

The recovery pass corrected two old fixtures in
`tests/audit/test_reasoning_retrieval.py`: the simulated pre-scope SQLite schema
must omit the new scope-dependent index, and the native-query Chroma fake must
explicitly select approximate mode, declare model/dimension and inject its
fake client. The assertions remain intact, with extra model/dimension checks.
An independent import-block probe confirmed the fake works without the optional
Chroma package. No runtime source changed during that recovery.

All documented S8 prerequisites and original mechanism exits are mapped in
[the S8 completion evidence](s8-completion.md). The full integration result,
canonical closeout and protected-main boundary must be read together there and
in the current handoff.
