# Entity-aggregation retrieval (cat1) — measured marginal at the retrieval-time tier

Date: 2026-06-15
Route: locomo / retrieval
Status: investigation complete; lever landed **default-OFF**; real lever deferred to the ingest rebuild.

## Hypothesis

HISTORY#321 named the cat1 (single-hop) root blocker: SEAM has **no cross-turn entity
coreference**. LoCoMo ingests per-turn, so each turn's speaker becomes a *fresh* `ent:`
id with zero `ir_edges`; facts about one person are scattered across many unlinked ids.
The proposed lever: **entity-aggregation retrieval** — gather every claim grounded to
(or mentioning) the question's entity and present it as a clean, re-attributed list.

This audit tests a **retrieval-time prototype** of that lever (string-match over CLM
records at query time) — the cheap proxy for the real ingest-side rebuild.

## What was built (benchmark adapter only)

`benchmarks/external/locomo/adapters/seam.py`, opt-in via `entity_aggregation=` /
`SEAM_BENCH_ENTITY_AGG` (default **OFF**):

- `_question_entities` — proper-noun runs + acronyms, sentence-start stopword trim.
- `_entity_aggregate` — resolves each CLM `subject` (`ent:` id) to its ENT label so a
  first-person object ("I researched X") is **re-attributed** to the named entity
  ("Caroline: I researched X") — the coreference fix in the *presented text*.
  Matches entity in subject **or** object (word-boundary), dedups, ranks, caps.
- Hardened ranking: **query-relevance** (stemmed lexical overlap with the question's
  content words) floats the answer needle above the cap; cap lowered 40→20.
- Free measurement infra added: a local **Ollama answerer** (`answerer=ollama`,
  `_ollama_short_answer`, urllib, no new dep) with seed+greedy determinism, so
  answer-quality is testable for free before any paid run.

## Measurements

### 1. Free recall A/B (deterministic; `context_recall`, no model)

Refined matcher, 10 conversations, 1198 dev questions:

| cat | n | OFF | ON | Δ | cases improved | mean gain when fired |
|---|---|---|---|---|---|---|
| 1 single-hop | 221 | 0.6613 | 0.6865 | +0.0252 | 16 | 0.348 |
| 2 temporal | 247 | 0.7637 | 0.7700 | +0.0063 | 6 | 0.260 |
| 3 open-domain | 75 | 0.3972 | 0.4316 | +0.0344 | 9 | 0.287 |
| 4 multi-hop | 654 | 0.8693 | 0.8810 | +0.0117 | 20 | 0.384 |

Read: gains concentrate on the weak categories (cat1/cat3), **not** uniform inflation.
The lever is a **targeted rescue** — fires on ~7–12% of cases, rescues them hard
(+0.35 recall when it fires). **Caveat:** the agg block is *additive* (appended, never
evicts), and `context_recall` is set-based, so it can only go up — recall **overstates**
the value. It says tokens are now present, not that the answer is produced.

### 2. Free answer-quality A/B (local Ollama qwen2.5:3b, `token_f1` vs gold)

The decisive gate, and where the recall win evaporated.

- **Determinism failure (caught on verification):** at `temperature=0`, the same
  (question, context) prompt gave *different* answers 4/15 times; a cat1 re-run flipped
  the aggregate from +0.012 to −0.003. The ~0.01 effect was **below the answerer's own
  noise floor**. First "+0.012, 23 win/18 loss" reading was largely **noise**.
- **Fix:** `seed` + `top_k=1` + `temp=0` → 3/3 identical within a process.
- **Deterministic cat1 (112 cases):**

| config | OFF | ON | within-run Δ | improved / regressed |
|---|---|---|---|---|
| raw hack (cap 40) | 0.2066 | 0.2013 | −0.0054 | 20 / 21 |
| hardened (cap 20, query-rank+stem) | 0.2039 | 0.2093 | +0.0055 | 25 / 25 |

Even with the seed, OFF drifted 0.2066→0.2039 across processes (~0.003 residual
non-determinism), so +0.0055 sits at the noise floor.

Mechanism (from sample cases): **wins are real coreference fixes** ("What did Caroline
research?" 0.67→1.00; "Do Jon and Gina start businesses out of what they love?"
unknown→Yes). **Losses are dilution** ("What instruments does Melanie play?"
clarinet→unknown) — the claim-list buries the needle and the small model gives up.
Query-ranking + stemming converts some losses but does not produce a clear net win.

## Verdict

The **retrieval-time string-match** entity-aggregation lever is **marginal — a wash on
cat1 answer quality** at the free tier, hardened or not. Recall recovers the tokens; the
answerer does not convert them net-positive because recovered facts compete with the
dilution they ride in on. This is the ceiling of the retrieval-time approach and matches
HISTORY#321's prediction.

**Residual confound:** qwen2.5:3b is weak and abstains easily; the local signal is
*conservative*. A capable answerer might convert the recovered facts better. Resolving
the exact sign of a marginal hack is low-EV, so no paid run was spent (per the
"paid is the last lever" rule — free measurement settled the direction).

## Outcome

- The lever stays **default-OFF**, env-gated, documented — a tested-and-parked idea
  (and the retrieval-side prototype the ingest rebuild can reuse), not a default.
- The **free answer-quality infra** (local Ollama answerer + determinism + `token_f1`
  A/B) is the durable win — it makes future levers testable for free.

## Next: the real lever (ingest rebuild)

Build cross-turn entity coreference at **ingest** (link per-turn entity mentions to
stable ids + real aggregation retrieval over edges), not string-matched at query time.
The prototype's wins (re-attribution) validate the concept; its ceiling validates moving
the work to ingest. Scope + free-validate (deterministic recall + the local-answerer
gate above) before building. 80% is a milestone to unlock other roadmap items, not a
one-fix target.
