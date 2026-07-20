---
handoff_id: 2026-07-20-derived-facts-landed-and-kb-scaffold
supersedes: 2026-07-20-second-hop-negative-and-count-lever-conflict
handoff_status: current
history: HISTORY#436
---

# Handoff: derived-facts lever landed; two facade levers exhausted; memory-systems KB scaffolded

- **Date:** 2026-07-20
- **Branch:** `agent/roadmap-zep-after-benchmarks` (PR #153, draft; CI green on
  the self-hosted `seam-terrabyte` runner)
- **Pushed:** through `6cbaf81` (HISTORY#435). This handoff (#436) + KB (#437)
  land on top.
- **Spend state:** no paid work authorized by this handoff. Every remaining
  gate below is FREE first.

This handoff catches the registry up from #432 to #436 — #433/#434/#435 landed
without registering handoffs.

## Where the scoreboard actually is (matched gpt-4o contract, mem0 harness)

The #429 matched run is the honest, citable state: **SEAM tops mem0 on
nothing under matched conditions.**

| Category | SEAM matched | mem0 published | Gap |
| --- | --- | --- | --- |
| cat1 multi-hop | 87.94% (248/282) | 91.3% | −3.4 |
| cat3 open-domain | 69.79% (67/96) | 72.7% | −2.9 |
| cat4 single-hop | 87.16% (mini) | 91.2% | −4.0 |
| cat2 temporal | 71.96% (mini) | 92.0% | −20.0 |

Native judge/1 champion (separate scoreboard, never averaged — #415) is
unchanged at **0.7762**. The "cat3 topped" claim was a lenient-mini-judge
artifact; do not repeat it for matched conditions.

## What happened since #429 (the lever arc)

Three levers aimed at the #429 miss buckets; **the two facade-only levers are
exhausted, the architectural one is the live path**:

1. **`entity-bridge/1` second-hop retrieval (#431) — KILLED at the FREE gate
   (#432).** 0 of 48 misses gained. You cannot bridge from evidence you never
   retrieved. Committed, default-off, harmless. Root cause verified: the wall
   is query↔evidence WORDING DISTANCE (querying `"surfing"` returns the gold
   turn at rank 1; the natural question never does), because SEAM serves raw
   turns, not distilled facts.
2. **`event-count/distinct/2` same-event grouping (#433, recovered from an
   interrupted session — NOT operator-rejected; #430's label was wrong, proven
   by mtimes+reflog). Paid microgate NEGATIVE (#434): net +1, gate 7.** A
   strong gpt-4o answerer already counts well (baseline 6/13), and 6/13 stored
   count-misses recover on a plain rerun (gpt-4o non-determinism). Committed,
   default-off. The count bucket has little headroom under a strong answerer.
3. **`grounded-clm/1` derived-facts (#435, codex) — the RIGHT architecture, now
   BUILT.** See next section. This is the direction #432 pointed to and the one
   with real headroom.

## The live lever: `grounded-clm/1` derived facts (#435)

`seam_runtime/derived_fact_context.py` + `nl_extract.py` + adapter/facade
wiring. Default-off, auditable, benchmark-evaluable vertical slice (NOT a
product default yet, NOT a score claim yet).

- **Ingest contract:** persists ONLY explicit singular first-person claims that
  losslessly ground to a canonical turn and rebase to that turn's speaker.
  Everything uncertain (third-person, plural, negation, quotation, reported
  speech, …) fails closed to the RAW floor.
- **Serve contract:** eligible CLM records render as `SEAM-FACT/1` beside an
  exact `SEAM-SOURCE/1` RAW record; `raw-prefix-floor/2` splice keeps ≤20% facts
  in every prefix and a fact never precedes its source. Count/temporal
  projections keep precedence.
- **Trust contract:** frozen manifest pins policy, extraction schema/prompt,
  Ollama model digest, cache identity, and the exact embedding contract
  (`BAAI/bge-small-en-v1.5` rev `5c38ec7c…`, 384-dim, local-only). Fresh/warm
  mismatch, digest drift, shared pgvector, or a remote embedder are refused.
- **Verified:** `tests/audit/test_derived_fact_context.py` passes (re-confirmed
  this session); a real qwen2.5:14b smoke produced the grounded fact
  **`John likes surfing`** with its source RAW first — that is tonight's
  `conv4_q11` miss, the exact shape this lever exists to fix.

### The honest next gate for derived facts (all FREE first)

1. **Extractor speed is the blocker.** Only `qwen2.5:14b` is installed
   (`ollama list`), at ~138 s/turn — a full 10-conversation preflight (~5,900
   turns) is impractical. Install/select a **faster local extractor** (operator
   decision) before any corpus run.
2. **No free coverage/precision preflight runner exists yet** for derived facts
   (only the event-count one does). Build one that reports, over the stored
   #429 miss set, per-turn fact yield, grounding precision, and whether facts
   surface gold evidence the raw query missed — the derived-facts analogue of
   `preflight_event_count_context.py`. THIS is the highest-value next build.
3. Only then a paid answerer microgate, gated on measured fact yield +
   retrieval lift, on the same 13-ish cat1 stored contexts.

## New this session: memory-systems knowledgebase (#437)

`docs/kb/` — a Leeroopedia-style, version-controlled KB so every agent (me,
SOL, codex) shares hard-won knowledge instead of re-deriving it. Seeded with
the two things that are actually scarce (per the #423–#434 arc): (a) how
competitors architect ingest→store→retrieve (serves the derived-facts build),
and (b) memory-eval methodology traps (would have caught the model-mismatch,
rerun-noise, and token-overlap errors that cost real time/money). Also carries
the lever graveyard. Start at `docs/kb/README.md`. A local (gitignored)
`.claude/agents/seam-retrieval.md` points at it.

## Standing infra / rules

- CI: all 6 jobs green on self-hosted `seam-terrabyte`; windows leg manual-only
  (`ci-windows.yml`). Stale HF token parked at
  `~/.cache/huggingface/token.stale-2026-07-19`. Full local suite needs the T7
  offline HF env + local pgvector DSN (`dbname=seam user=seam`, password via
  `docker inspect seam-pgvector`; port 55432 — CI uses 55433).
- Cost: use `benchmarks.external.common.cost_report` (o200k, tokenizer-true)
  before quoting AND after any paid run; treat its number as a LOWER BOUND
  (invisible retry/rerun passes bill on top). Reconcile against the provider
  dashboard.
- Paid-run discipline: FREE falsifying gate before any spend; check runner
  model constants against the artifact's contract before firing (the #434
  model-mismatch lesson); operator confirms every paid run.
