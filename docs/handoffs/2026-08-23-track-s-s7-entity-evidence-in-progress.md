---
handoff_id: 2026-08-23-track-s-s7-entity-evidence-in-progress
supersedes: 2026-08-23-s6-github-operations-merged-s7-next
handoff_status: current
history: HISTORY#601
---

# Track S S7 entity evidence in progress

## Authoritative state

- S6 is finished and published through PR #223. Its source head `fbefb81` and
  merge commit `abd2a59` are ancestors of protected `origin/main@1752532`.
- S7 started from that exact protected head on
  `track-s/s7-semantic-ingest` in the reused
  `/home/terrabyte/Documents/Projects/Seam-track-s-s6` worktree.
- The primary checkout remains separate draft PR #221 work and contains
  unrelated untracked operator assets. None belongs to S7.

## First coherent slice

- `compile_nl` attaches the containing proposition SPAN to every admitted ENT
  mention and accumulates distinct spans for repeated mentions.
- Persisted compiled ENTs resolve through exact SPAN offsets to source RAW with
  complete provenance chains in the focused fixture.
- The graph identity projection rejects canonical and alias entity terms made
  entirely from a closed stopword set. Multiword names remain indexable.
- Existing REL admission already fails closed on canonical same-boundary
  endpoints and exact source/evidence identity; the relation qualification
  lane remains research-only and scorer-ineligible until its corpus gate is
  satisfied.

## Verification boundary

- The new red tests failed on all three intended gaps before implementation.
- The focused S7 tests pass.
- The provenance/entity/graph/relation slice passed 92 tests, scoped to
  `test_s7_entity_evidence.py`, `test_provenance_chain.py`,
  `test_entity_coreference.py`, `test_knowledge_graph.py`,
  `test_relation_extraction_qualification.py`, and
  `test_relation_extraction_ingest.py` under `tests/audit/`.
- The compiler/concurrency slice passed 81 tests, scoped to
  `tests/audit/test_conversation_turn_compile.py`,
  `tests/audit/test_persist_ir_concurrency.py`, and
  `tests/fidelity/test_nl_extract.py`.
- The complete non-external pytest lane passed with `SEAM_DB_PATH` pointed at
  an isolated `/tmp` database and the ambient `SEAM_PGVECTOR_DSN` removed. An
  initial unisolated run failed because this retained worktree has an ignored
  August 19 `seam.db` with an older schema and the operator shell exports a
  pgvector DSN; those are environmental failures, not a green baseline.
- The linked worktree has no local `.venv`; commands use the primary checkout's
  unchanged virtual environment with `PYTHONPATH=.`.

## Still required for S7

Do not mark S7 complete until every campaign exit condition is independently
proved. The next work must cover:

1. functional versus multivalued predicate policy and deterministic
   older/newer/equal/missing-time reconciliation;
2. concurrency, idempotency, and as-of retrieval counterexamples;
3. same-name-person separation across source turns without tenant leakage;
4. native corpus freeze, independent entity/relation review, and digest-bound
   scorer eligibility; and
5. fresh retrieved-ENT coverage measurement after corpus rebuild. Historical
   corpora remain evidence-empty and the recorded ENT result remains 0.0000.

S8 must not start while these S7 gates remain open.
