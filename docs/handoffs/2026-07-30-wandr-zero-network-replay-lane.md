---
handoff_id: 2026-07-30-wandr-zero-network-replay-lane
supersedes: 2026-07-30-retrieval-baseline-ablation-in-progress
handoff_status: superseded
history: HISTORY#505
---

# Handoff: zero-network WANDR replay lane implemented

**Date:** 2026-07-30
**Branch:** `refactor/unify-retrieval-paths` (local-only; the retrieval hold
from HISTORY#503/#504 still applies to the ranking, not to this lane)
**Scope:** the non-official, provider-free WANDR replay adapter requested by
`2026-07-29-wandr-provider-free-replay-next`

## One-line state

A zero-network WANDR replay lane exists over a hash-pinned local corpus, with
provider/network/cost counters verified at zero and a same-code native versus
event-only ablation that currently reports **parity**.

## Why replay, and why a synthetic corpus

WANDR's official path cannot be run here. Every task — including `smoke` —
declares `network_mode = "public"` and expects `OPENAI_API_KEY` /
`PERPLEXITY_API_KEY`. The prior handoff forbids that path without new approval.

The upstream pipeline *does* support replay natively: `fetch`, `triage`, `canon`,
`dedup`, and `judge` are each wrapped in
`persisted(component, key=..., path=debug/<stage>.jsonl)`, documented as
"Persist component outputs to JSONL. On hit, return stored output." Pre-populated
caches therefore short-circuit every networked and LLM stage. **No such cache
artifacts exist in the checkout** — they are produced by a real (paid, networked)
run, so they could not be harvested without approval.

The corpus here is consequently **hand-authored and synthetic**. That also avoids
a licensing hazard: WANDR is Apache-2.0, but its `NOTICE` states the grant covers
only material Perplexity holds rights to, and "third-party materials remain
subject to their respective copyright" — i.e. fetched page text is not ours to
vendor. Nothing upstream is redistributed; only the workload *shape* is followed.

## What landed

- `benchmarks/external/wandr/types.py` — `WandrRow`, `WandrTask`, `KeySpec`,
  `ReplayCounters`, deterministic `stable_id`.
- `benchmarks/external/wandr/corpus.py` — SHA-256-pinned corpus loading;
  `CorpusIntegrityError` on drift; `validate_hierarchy`.
- `benchmarks/external/wandr/adapters/seam.py` — the adapter endpoints:
  `reset`, `ingest_row`, `ingest_task`, `retrieve`, `recovered_sources`,
  `submit`, `write_submission`, `counters`, and `fetch` (which always raises
  `ZeroNetworkViolation`).
- `benchmarks/external/wandr/run.py` — CLI: `--task`, `--lane`, `--ablate`,
  `--dry-run`, `--list-tasks`, `--output`. Exits non-zero if any cost counter
  is non-zero.
- `benchmarks/fixtures/wandr/` — `smoke.replay.jsonl` (3 topics × 2 urls),
  `hierarchy.replay.jsonl` (4 operators × 2+ urls), `MANIFEST.json` with pins.
- `tests/audit/test_wandr_replay_adapter.py` — 17 tests.

## Handoff requirements, point by point

| # | Requirement | Status |
| --- | --- | --- |
| 1 | smoke workload | `--task smoke` |
| 2 | one representative hierarchy task | `--task hierarchy`, two-level key hierarchy |
| 3 | isolated namespaces/scopes | `wandr:<scope>`, per-scope SQLite store |
| 4 | deterministic source/episode/task/request IDs | `stable_id`, SHA-256 based |
| 5 | fixed hash-pinned corpus, no live fetch | `MANIFEST.json` pins; `.invalid` URLs; `fetch()` raises |
| 6 | provider/network/cost counters at zero | asserted in report and tests; runner exits 1 otherwise |
| 7 | matched budgets across lanes | same `budget`/`search_top_k`; only graph participation differs |
| 8 | attribution, canonicalization, dedup, provenance, recovery | per-member attribution, `canonical_url`, ingest-time dedup, `source_ref` provenance, reopen-based batch recovery |

## Measured result (honest)

`--task hierarchy --ablate`:

| lane | source recall | batch recovery | duplicates collapsed |
| --- | ---: | --- | ---: |
| native (`mix`, graph on) | 1.0 | ok | 2 of 10 rows |
| event-only (`hybrid`, no graph) | 1.0 | ok | 2 of 10 rows |

Verdict: **parity**, delta 0.0. Provider calls 0, network calls 0, cost $0.00.

This is mechanism evidence only, exactly as the prior handoff anticipated. Both
lanes sit at a **1.0 ceiling**, so the corpus cannot currently discriminate
between them — parity here does not mean the graph is useless, it means this
corpus is too easy to detect a difference. **Do not read this as graph lift, and
do not read it as evidence against the graph either.**

## Exact next step

1. Harden the corpus so it can discriminate: add distractor sources, cross-member
   entity collisions, and members whose evidence is only reachable by a
   multi-source join. The ceiling must be broken before an ablation means
   anything.
2. Re-run `--ablate` and require an attributable per-member gain, not an
   aggregate one, before any incremental-graph claim.
3. Only if the operator later approves a paid run: harvest genuine
   `debug/*.jsonl` caches from one official smoke run and add a second,
   real-corpus replay task alongside the synthetic one.

## Preserved boundaries

- WANDR's official networked/paid path was not executed; no provider, network,
  or paid call occurred.
- No upstream WANDR data or fetched page content is vendored.
- The retrieval-ranking hold from HISTORY#503/#504 is unchanged: the one-engine
  RRF ranking remains unpromoted pending the 1,542-question hybrid-vs-mix gate.
- Unrelated `.ua/`, `seam_runtime/.ua/`, `dist/`, and report PNG files untouched.
