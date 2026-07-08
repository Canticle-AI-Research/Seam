# Handoff: cat1/cat3 → 80% scoping + a real local-retrieval perf bug

- **Date:** 2026-07-07
- **From:** Claude (Opus)
- **To:** Fable
- **Repo HEAD at handoff:** `587c606` (`main`, == `origin/main`, tree clean except this doc)
- **Operator's standing goal:** get LoCoMo **cat1 AND cat3 judged score past 80%** (not "+20 points" — the literal bar is >0.80 each). SEAM is a *local-first* memory runtime; the pitch is topping the LoCoMo charts at mem0's scale with a local memory layer. See memory `project_cat1_coreference_parked_and_20pt_goal`, `project_mem0_parity_goal`.

---

## TL;DR (read this, then the sections)

1. **Housekeeping is done.** The entire #358→#361 Windows-CI cleanup thread is closed; `main` is green on both Linux and Windows runners; all stale branches pruned. Nothing pending there.
2. **The next problem is cat1/cat3 → 80%.** I ran the cheapest possible free diagnostic (recall-level compact-vs-broad A/B across all 10 LoCoMo conversations, no API spend) to decide *where* the cat3 wall lives before building anything.
3. **Key finding — the cat3 wall is NOT a retrieval-recall problem.** Compact→broad barely moves cat3 recall (0.402 → 0.379), and **67 of 75 cat3 cases are byte-flat** between profiles. This overturns the earlier working hypothesis that broad *dilutes* cat3. The judged-score gap (broad 0.293 vs old compact-knee 0.42) is therefore almost certainly **downstream in generation/answerer**, not retrieval. **This is a hypothesis, not yet confirmed** — the confirming test is generation-side, not more retrieval tuning.
4. **Separately, profiling turned up a real, fixable perf bug in the DEFAULT local retrieval path** (not a hardware limit — the GPU is set up and working). Two hotspots: a pure-Python `cosine()` and a brute-force full-table-scan vector search. Details + fix rec below. This is *why* the free diagnostics are painfully slow.
5. **Open decision for you (the operator was mid-deciding):** (a) ship the small safe `cosine()` numpy fix, (b) scope the brute-force-scan gap separately, (c) pick the actual cat1/cat3 next step given both categories now look answerer-bound, not retrieval-bound.

---

## Repo state (all clean, nothing pending)

- `main` @ `587c606`, matches `origin/main`. Last CI run on that commit: **all jobs green**, including `test-and-benchmark` on both `ubuntu-latest` and `windows-latest` (the first fully-green Windows run in the whole #358→#361 thread).
- HISTORY chain is at **#361**; integrity/routing/continuity/streams all pass.
- Open PRs: only **#121** (`claude/refine-local-plan-74a997`, DRAFT) — pgvector HNSW index + per-run table isolation, part 1 of a corpus-scale-accuracy thread. Explicitly **incomplete**: `ef_search` not wired into `search()`, part-2 sweep tool never built, unverifiable in its sandbox (no Docker/pytest). Leave as draft; see its PR body.
- Branches: all merged/abandoned ones deleted this session; only protected (`handoff/archive`, `backup/*`) + the #121 draft branch remain.

---

## The next problem: cat1/cat3 → 80%

### Where each category stands (best judged numbers on record)

Source: `docs/progress_tables/benchmark_results.csv` + `docs/handoffs/2026-06-26-seam-vs-mem0-rungc-handoff.md` (the richest full-scale run: SEAM broad profile, 764 real questions across 5 LoCoMo conversations, gpt-4o-mini judge).

| Category | Best judged | Source | Gap to 0.80 |
|---|---|---|---|
| aggregate (rung C) | 0.674 | rungC handoff (764 Q, broad) | — |
| **cat1** single-hop | **0.705** | #328, 61-case holdout, broad + capable OpenAI answerer | ~+0.10 |
| cat2 temporal | 0.535 | rungC | — |
| **cat3** open-domain | **0.42** | #320, 100-case, OLD compact knee | ~+0.38 (much bigger) |
| cat4 multi-hop | 0.817 | rungC | already clear |
| cat5 adversarial | 0.75 | rungC | already clear |

Note the cat1 instability across samples: 0.705 on the 61-case holdout vs **0.528** on the rung-C 764-Q run — a 17-point swing purely from which conversations get sampled. Any cat1 claim must state its exact slice.

cat3's best (0.42) was under the **old compact knee**, and it was **worse (0.293) under broad** in rung C — the first hint that broad might be *hurting* cat3, which is what I set out to check.

### The free diagnostic I ran (this session)

**What:** deterministic, no-API `context_recall(retrieved_context, gold_answer)` A/B, compact `(top_k=100, budget=8000)` vs broad `(top_k=300, budget=60000)`, pooled over the **dev split** of **all 10** LoCoMo conversations (1198 questions), broken out per category.

**How (reproducible):** driver `benchmarks/external/locomo/recall_scorer.py` → `build_locomo_dev_scorer(dataset, max_scopes=10)` + `PooledLocomoRecallScorer.score(flags=...)`. My exact ad-hoc script is at the session scratchpad `cat3_compact_vs_broad_recall.py` **(session-local, NOT durable — you'll need to rebuild it; it's ~40 lines wrapping the tracked scorer above).** Run with `SEAM_PGVECTOR_DSN` **unset** (per-scope SQLite — leaving it set contaminates across scopes, see Environment below).

**Result (1198 pooled dev Q, all 10 scopes, FREE):**

| category | compact | broad | delta |
|---|---|---|---|
| cat1 single-hop | 0.6329 | 0.6238 | −0.0091 |
| cat2 temporal | 0.7519 | 0.7560 | +0.0041 |
| **cat3 open-domain** | **0.4017** | **0.3789** | **−0.0228** |
| cat4 multi-hop | 0.8616 | 0.8437 | −0.0179 |
| cat5 adversarial | 0.0000 | 0.0000 | 0.0000 |
| **aggregate** | **0.7673** | **0.7552** | **−0.0120** |

cat3 per-case (n=75): **improved=3, regressed=5, flat=67.** The −0.023 is driven by 5 outliers, two of them suspicious collapses:
- `conv-42::q14`: compact 1.000 → broad **0.000** (gold vanished entirely)
- `conv-43::q8`: compact 0.500 → broad **0.000**
- `conv-47::q19`: 0.682 → 0.500; `conv-41::q45`: 0.714 → 0.571; `conv-42::q4`: 0.647 → 0.529

**Caveats on this metric (important):** `context_recall` is a free *string-overlap* proxy — it measures whether gold tokens are **in the retrieved context**, NOT whether the answer is correct. That's deliberate: it isolates retrieval from generation. cat5's 0.0 is an artifact (adversarial gold lives in a different field), ignore it. See memory `reference_free_answer_quality_validation` for the full free→paid ladder and the determinism traps.

### Interpretation (what to infer)

- **cat3's judged wall is very likely generation-side, not retrieval.** Recall barely moves compact→broad and 89% of cases are flat, yet the *judged* score swings 0.42→0.293. If retrieval were the cause, recall would move with the profile. It doesn't. So the answerer is failing to convert already-retrieved context into correct answers — consistent with cat3 being **commonsense/personality inference** questions (I pulled real ones from `benchmarks/external/locomo/data/locomo10.json`: *"Would Melanie be considered an ally to the transgender community?" → "Yes, she is supportive"*). The gold is never stated verbatim; a bigger, noisier broad context plausibly hurts inference at generation time ("lost in the middle"). **This is a hypothesis** — confirm with a generation-side test, not more retrieval tuning.
- **cat1 is likewise flat at recall level** (0.633 vs 0.624), reinforcing the already-validated finding (memory `project_cat1_answerer_bound`) that cat1 is **answerer-bound**: ~92% of gold facts exist in the conversation, ~72% get retrieved into context, but only ~45% survive into the final answer — a multi-part **enumeration** failure ("what activities does X do?" → a list scattered across turns), not a retrieval miss. Every retrieval lever (top_k, budget, decomposition, cross-turn coreference, entity-aggregation) has been tried and is exhausted; see the "Outcome" section of `docs/audits/2026-06-17-cat1-coreference-graphrag-blueprint.md` (HISTORY#358 landed coreference but it was a null/negative on cat1 recall, parked default-OFF).
- **Net:** both cat1 and cat3 now point at the **generation/answerer** layer, not retrieval. Free retrieval levers are spent. The remaining moves are answerer-side (better prompt for enumeration/inference, or a more capable answerer) — and confirming those needs the **paid judge**, which is **operator-gated** (memory `feedback_no_paid_run_without_prompt` — never auto-launch, surface cost + get an explicit yes).

---

## The perf bug (separate thread — why the free diagnostics crawl)

The operator asked "can we speed this up / is GPU on?" **GPU is set up and working** — `torch 2.12.0+cu130`, `torch.cuda.is_available()==True`, RTX 2070, and I confirmed the running process was actually allocating GPU memory (282 MiB, ~27% util). Embeddings are GPU-accelerated. The slowness is **CPU-bound Python in the retrieval scoring loop**, which I profiled in isolation (15 questions, 1 scope, broad, `cProfile`):

```
35,993,935 function calls in 10.720 s   (15 questions)
   ncalls  cumtime  file:function
       15    8.648   seam_runtime/vector_adapters.py:35  search        <- top of stack
       15    8.499   seam_runtime/vector.py:83            search        <- the real work
   143194    4.325   builtins.sum                         (cosine's pure-python sums)
    26235    4.254   seam_runtime/models.py:176           cosine
    96926    3.492   json.loads                           (one per stored vector, per query)
    96926    2.876   json.decoder.raw_decode
       45    2.089   seam_runtime/storage.py:725          load_ir
    70691    1.211   seam_runtime/mirl.py:109             from_dict
```

Two real, fixable bugs (not hardware):

1. **`seam_runtime/models.py:176` `cosine()` is pure-Python, not vectorized.**
   ```python
   numerator  = sum(a * b for a, b in zip(left, right, strict=False))
   left_norm  = math.sqrt(sum(a * a for a in left))
   right_norm = math.sqrt(sum(b * b for b in right))
   ```
   ~1,150 Python-level mul-adds per call × 26,235 calls = >10M inner-loop iterations for 15 questions. A numpy rewrite (`np.dot` / `np.linalg.norm`) is a **drop-in, low-risk win.** Small, safe, do-regardless.

2. **`seam_runtime/vector.py:83` `SQLiteVectorIndex.search()` is a brute-force full-table scan.** It `SELECT`s and `json.loads()`-deserializes **every** stored vector for the model on **every** query, then heaps the top-k (96,926 `json.loads` for 15 queries). This is the **DEFAULT local backend** (no pgvector configured) — so it's not a benchmarking quirk, it's how every local SEAM search actually works, and it degrades **linearly with corpus size**. Architecturally the same class of problem PR#121 is fixing for pgvector (HNSW) — **except PR#121 doesn't touch this default SQLite path at all.** Bigger fix, real design choices (in-memory vector cache vs precomputed matrix vs an actual ANN index for SQLite) — **scope it deliberately, don't just dive in.**

---

## Open decisions for you (Fable)

The operator was mid-answering these when the session handed off:

1. **Ship the numpy `cosine()` fix now?** (My rec: yes — small, safe, unblocks every future free diagnostic. Full SEAM chain + PR.)
2. **Scope the SQLite brute-force-scan gap as its own item?** (My rec: yes, as a scoped design task, not an ad-hoc patch. Note the overlap with PR#121's pgvector work.)
3. **cat1/cat3 direction:** given both are now answerer-bound at the recall level, the next *diagnostic* is generation-side (does a better enumeration/inference prompt or a more capable answerer move the judged score?), which needs the **paid judge** → operator-gated, surface cost + get explicit go first. Do NOT reach for another retrieval lever; that well is dry.

---

## Environment / how-to-run (gotchas that will bite you)

- `cd /home/terrabyte/Documents/Projects/Seam && source .venv/bin/activate`
- **`unset SEAM_PGVECTOR_DSN` before any per-scope LoCoMo diagnostic.** With it set, all scopes route to one shared pgvector pool = cross-scope retrieval contamination (memory `project_cat1_answerer_bound` notes `test_seam_all/test_seam.py:103` forces it unset for exactly this reason). The DSN carries a password — **never print or commit its value** (CLAUDE.md hard rule).
- **Hardware:** 6 CPU cores, 31 GB RAM, one RTX 2070 (8 GB). GPU + CUDA are working. **Do NOT run two heavy embedding/retrieval jobs concurrently** — I did (profiler alongside the main diagnostic) and just created contention that slowed both; logged as a mistake. One heavy job at a time.
- **Dataset:** `benchmarks/external/locomo/data/locomo10.json` (committed, 2.8 MB, SHA-pinned by its `.manifest.json` — verify by hash, not label).
- Full canonical suite: `pytest tests/ test_seam_all/ tools/history/test_history_tools.py tools/streams/ -m "not external"` → expect all pass, 2 pre-existing xfail. (Add pgvector external leg only with the container up + `PGVECTOR_TEST_DSN` set.)
- **Repo-change protocol:** any repo change → append HISTORY, rebuild index, snapshot, `verify_integrity`/`verify_routing`/`verify_continuity`/`verify_streams`, update `PROJECT_STATUS.md`, branch + PR (main is protected; `--squash`, poll checks, **never `--auto`**). No Claude/agent attribution in commits.

---

## All data sources behind the decisions above (links)

**Repo files (clickable as path\:line):**
- `benchmarks/external/locomo/recall_scorer.py` — the free recall scorer used for the diagnostic (`build_locomo_dev_scorer`, `PooledLocomoRecallScorer`)
- `benchmarks/external/locomo/data/locomo10.json` — the LoCoMo-10 dataset (cat3 sample questions pulled from here)
- `seam_runtime/models.py:176` — the pure-Python `cosine()` (perf bug #1)
- `seam_runtime/vector.py:83` — `SQLiteVectorIndex.search()` brute-force scan (perf bug #2)
- `seam_runtime/retrieval.py:152` — `RETRIEVAL_PROFILES` (compact/broad); `:18` `RetrievalFlags`; `:67` `search_top_k`; `:78` `context_budget`
- `docs/audits/2026-06-17-cat1-coreference-graphrag-blueprint.md` — cat1 coreference blueprint + the HISTORY#358 "Outcome" (null result, parked)
- `docs/handoffs/2026-06-26-seam-vs-mem0-rungc-handoff.md` — rung-C per-category judged numbers (0.674 agg; cat1 0.528 / cat3 0.293)
- `docs/progress_tables/benchmark_results.csv` — the judged-run history table (cat1 0.705 holdout, cat3 0.42 old knee, etc.)
- `benchmarks/runs/locomo/rungc_mem0_retry_764.json` — the mem0-side rung-C artifact
- `tools/benchmarks/rung_c_paid.py` — the tracked paid rung-C runner (gated behind `--execute --confirm-paid`)

**Operator memory (project-scoped, same project → surfaces in your recall; key numbers summarized inline above so you're not recall-dependent):**
- `project_cat1_coreference_parked_and_20pt_goal` — the ">0.80 for cat1 AND cat3" bar; #358 coreference parked
- `project_cat1_answerer_bound` — the 92%→72%→45% cat1 funnel; cat1 is answerer-bound; broad-profile holdout lever; the `SEAM_PGVECTOR_DSN`-unset gotcha
- `project_paid_locomo_baseline_and_bottleneck` — the 0.40→0.52 budget-starvation history; decomposition ruled out
- `project_mem0_parity_goal` — local-first positioning; the A→B→C mem0 head-to-head; mem0 ~0.669 target
- `reference_free_answer_quality_validation` — the free→paid validation ladder + determinism traps
- `feedback_no_paid_run_without_prompt` — paid runs are operator-gated, never auto-launch
- `feedback_always_test_before_building` — validate-before-build; cheapest falsifying experiment first

**Session-local (ephemeral, will NOT survive into your session — rebuild from the tracked scorer above if needed):**
- scratchpad `cat3_compact_vs_broad_recall.py` — the diagnostic driver
- scratchpad `profile_retrieval.py` — the cProfile harness (1 scope, `question_limit=15`, broad)

---

## Guardrails (do not skip)

- **No paid run without an explicit operator yes** — surface the exact command + cost estimate first. The cat1/cat3 confirmation is paid-judge territory; free levers are exhausted, but that does NOT license auto-spending.
- **No secrets in any committed file** — especially the pgvector DSN password, no session/share URLs, no keys.
- **Test before building** — the cheapest falsifying experiment first (free metric → paid judge only to confirm). The whole cat1/cat3 arc is the proof this pays off.
- **Follow the SEAM chain on any repo change.** This handoff doc itself is a repo change — see the note below.

---

### Note on committing this handoff
This file is written to `docs/handoffs/` but is **uncommitted** as of handoff. If it should be persisted (recommended, so a fresh session can be pointed straight at it), run the full SEAM chain: append HISTORY, rebuild index, snapshot, verify ×4 + streams, bump `PROJECT_STATUS.md`, branch + PR. Left uncommitted deliberately so the operator can decide — a dirty `docs/` file otherwise looks like abandoned WIP to the next agent.
