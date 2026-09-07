# S8 completion evidence

The governing completion gate is
[`TRACK_S_S8_S10_PRODUCTION_CORE.md`](../../docs/roadmap/TRACK_S_S8_S10_PRODUCTION_CORE.md#r1---s8-retrieval-contract).
This matrix binds its prerequisites and the original S8 mechanism exits to
executable regressions. The frozen source baseline is protected
`main@2f9a96b9bbc1015bb8057e01793e42cec95034af` through PR #254 (HISTORY#641).
Candidate `a6715c2f` passed required CI, PostgreSQL integration and independently
stored release qualification before merge. CI run `34086580171` passed the
three required checks plus PostgreSQL integration on exact main; its source
tree is identical to the qualified candidate. Advisory workflow outcomes are
recorded separately and are not inferred from required-job success.

## Prerequisites

All paths in this table are relative to `tests/audit/`.

| Gate | Regression evidence |
| --- | --- |
| D1 recoverable canonical storage | `test_sqlite_migration_spine.py` |
| D2 atomic ingest | `test_atomic_ingest.py` |
| D3 lifecycle exclusion | `test_lifecycle_exclusion.py`, `test_lifecycle_retrieval_regressions.py` |
| D4 consistent reads | `test_read_snapshot_consistency.py` |
| T1 temporal semantics | `test_temporal_semantics_contract.py` |
| G1 graph/trust and retained disagreement | `test_deep_knowledge_graph.py`, `test_reasoning_patterns.py` |
| R1 one retrieval contract | `test_s8_r1_retrieval_contract.py` |
| R2 structured, temporal and compatibility acquisition | `test_s8_r2_sqlite_scale.py`, `test_s8_r2_temporal_scale.py`, `test_s8_r2_legacy_scale.py` |
| R2 exact backend scores, ties, filters and growth | `test_s8_r2_sqlite_vector_parity.py`, `test_s8_r2_pgvector_parity.py`, `test_s8_r2_chroma_exact.py`, `test_s8_r2_semantic_admission.py` |
| R2 optional HNSW expression and actual query-plan admission | `test_s8_r2_pgvector_parity.py` |
| R2 explicit search modes and truthful traces | `test_s8_r2_vector_search_modes.py` |

R2's acquisition and backend evidence, with separate work/memory/latency
boundaries, is in [SQLite scale](r2-sqlite-scale.md),
[acquisition parity](r2-acquisition-parity.md), and
[backend parity](r2-backend-parity.md).

## Original S8 mechanism exits

| Required behavior | Regression evidence under `tests/audit/` |
| --- | --- |
| A legacy plan executes only the legacy adapter | `test_s8_retrieval_coherence.py` |
| Shipped entry paths match direct runtime candidates/order | `test_s8_retrieval_coherence.py` |
| Absent/all-one/zero/non-unit weights replay; all-one is bitwise `/2` | `test_s8_retrieval_coherence.py`, `test_fusion_leg_weights.py` |
| Unknown leg names fail before retrieval | `test_fusion_leg_weights.py` |
| One tenant-scoped event per enabled success; telemetry cannot change answers | `test_s8_retrieval_coherence.py` |
| Accepted identity merges are reversible and audited | `test_identity_resolution.py` |
| Explicit flag-cache refresh; large graph frontiers respect SQLite bounds | `test_s8_retrieval_coherence.py` |

The boundary-only SQL decision remains explicit: query-authored namespace plus
scope admits the non-lexical SQL tail at inclusive `0.80`; runtime tenancy alone
does not. Graph seeds need lexical evidence or structured score `1.00`.
`legacy-weighted/1` remains the compatibility default. Neither exact-vector
selection nor a tie correction promotes a new ranking policy.

## Verification boundary

The integration selection is:

```bash
env -u SEAM_PGVECTOR_DSN -u PGVECTOR_TEST_DSN PYTHONPATH=. \
  SEAM_DB_PATH=test_seam/r2-backend/resume/full-default.db \
  python -m pytest test_seam_all/ tools/history/test_history_tools.py \
  tools/streams/ tests/ -m "not external" --durations=15 -ra -o addopts=
```

Live backend qualification runs `python -m pytest tests/audit/ -m external -ra
-o addopts= --durations=10` with both PostgreSQL variables injected privately
from the owned scratch service, plus the subsequent real-Chroma growth case.
Both backend extras are installed in their execution lanes. External cases
are explicitly deselected from the core lane, never silently skipped.

Local receipts and logs live under `test_seam/r2-backend/resume/`. They record
commands, time, source/test hashes, exit status, and output hashes. The broad
pre-repair runs remain failures; their later fixture repairs do not rewrite
those outcomes. The fresh integration result is 3540 passed, 65 deselected, 2 xfailed, 2 warnings in 508.17s (0:08:28). Runtime, test and CI
source hashes remained unchanged throughout. The current handoff and
HISTORY#640 bind the local candidate to its later publication gates.

S8 completion does not complete S9 benchmark qualification/Promotion, S10
reproducible release/deployment proof, Suite/API/WebUI operator acceptance, or
the private SDK/package delivery blockers. The launch plan still places
operator-product completion before expensive score campaigns. No paid
benchmark, package publication, or deployment belongs to this qualification.
