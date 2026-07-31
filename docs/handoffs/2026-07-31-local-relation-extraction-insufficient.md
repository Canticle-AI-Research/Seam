---
handoff_id: 2026-07-31-local-relation-extraction-insufficient
supersedes: 2026-07-31-embedding-preflight-relation-gate
handoff_status: current
history: HISTORY#508
---

# Handoff: local relation extraction is insufficient for scoring

**Date:** 2026-07-31
**Branch:** `fix/semantic-graph-admission`
**PR:** #189 (draft)
**Scope:** pinned local extraction, grounded REL qualification, and scorer
admission

## One-line state

One isolated local extraction produced real, exact-backtrace semantic topology,
but only 27 REL across 24/419 turns (5.73%). The substrate fails its predeclared
volume and coverage floors, so no eGoT/TREK scorer is eligible.

## Decision

Do not build adaptive depth, relation scoring, triplet scoring, or path
confidence on this corpus. The run proves that the local extractor can emit
canonical entity-to-entity relations and cross-turn paths; it does not prove
enough coverage or any human-reviewed precision.

If graph work continues, the next dependency is a separately authorized,
bounded extraction-yield improvement. It must produce a new pinned corpus and
pass the unchanged gate. A scorer remains downstream of both `passed=true` and
`scorer_eligible=true`.

## Pinned run

- Dataset: `benchmarks/external/locomo/data/locomo10.json`
- Dataset SHA-256:
  `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4`
- Scope: `conv-26`, 419 turns
- RAW identity:
  `493528a19823613e26414d7f7f9f99e069d3d445bddc2af9bcb68925c36a8ebb`
- Extractor: local Ollama `qwen2.5-7b-1m:latest`
- Installed model digest:
  `31ef7dc41e362c780fad4b23d2c5c7d781ebe672984e6fe3ce3e49977315ee89`
- Relation policy: `grounded-rel/1`; one extractor configuration
- Extraction cache: 1,208 misses and 122 same-config/content hits across 1,330
  proposition requests
- Cloud calls: zero; cloud-backed Ollama tags are rejected before extraction

## Qualification result

- RAW turns: expected 419, observed 419; identity matched
- REL persisted/admitted/exact-backtrace: 27/27/27
- Relation-bearing turns: 24/419 (5.7279%)
- Unique entity pairs/predicates: 27/27
- Full canonical admission and exact source backtrace: passed
- Self-loop and cross-boundary checks: passed
- Maximum hub degree: 6; bound: 8; passed
- Entities: 40; simple two-hop paths: 37
- Incremental cross-turn two-hop paths: 36; reached entities: 18/40
- Automatic floors: relation volume failed (27 < 30); turn coverage failed
  (5.73% < 10%)
- Final status: `insufficient_evidence`; `passed=false`;
  `scorer_eligible=false`

The deterministic review template contains all 27 relations and is retained
outside the repository. It is unlabeled. Point precision and Wilson precision
therefore remain unknown; they are not inferred from structural validity and
cannot rescue the failed automatic substrate floor.

## Implementation boundary

- `compile_nl` now validates the canonical speaker/timestamp envelope for the
  explicit, default-off relation lane without enabling derived-fact serving.
- A singular first-person claim is rebound only after the existing exact,
  explicit, lossless gate succeeds. Unsafe first-person claims and a global
  `I` entity fail closed. Existing derived-fact behavior is unchanged.
- `tools.relation_extraction_ingest` pins dataset, scope, local model tag and
  installed digest; rejects cloud tags and non-loopback hosts; requires a fresh
  SQLite output; preserves canonical LoCoMo formatting/source refs; caches by
  content plus exact extractor configuration; independently reconstructs RAW
  identity; and atomically writes the content-free report and external review
  template.
- Duplicate canonical source refs, artifact/SQLite-sidecar path collisions,
  nonfinite generation timeouts, source drift, model drift, and stored RAW
  identity drift fail before or during the run with named errors.

## Evidence and verification

External artifact directory:
`/mnt/data/seam-rel-qual-conv26.xpluzp/`

- Database SHA-256:
  `c9a81abdc08a1f0441c31b81b1c830b6292ac569a0512139fbdd8fd45d46def7`
- Content-free report SHA-256:
  `784f1ddf0c9a5cac732a8e0a519dda6cd6c085dbbbf02698140ffd649ede9774`
- Review-template SHA-256:
  `b69723e462c9e21298b850f788991f9b7fc403ed2edf657c1750b25c5fea7e15`
- The standalone read-only qualifier reproduced every funnel, graph, identity,
  and gate field and exited nonzero as required.
- Focused compiler, runner, and qualifier gate: 88 passed; Ruff,
  `py_compile`, and `git diff --check` passed.
- CodeRabbit found one test-isolation issue and four runner-hardening issues;
  all valid items were repaired and regression-tested. Its final retry was
  rate-limited, so an independent read-only agent review is the confirmation
  boundary.

## Exact next step

1. Land the bounded embedding guard, qualifier, explicit relation bridge, and
   runner through PR #189.
2. Keep the runtime graph leg fail-closed below semantic-edge admission.
3. Do not build a scorer from this 27-edge corpus.
4. If explicitly authorized, improve extraction yield in a separate pinned
   experiment and rerun the unchanged coverage, precision, hub, backtrace, and
   topology gates.
5. Only after both `passed=true` and `scorer_eligible=true`, benchmark adaptive
   depth plus query-aware relation/triplet scoring against `hybrid` on the
   category-1 holdout.
