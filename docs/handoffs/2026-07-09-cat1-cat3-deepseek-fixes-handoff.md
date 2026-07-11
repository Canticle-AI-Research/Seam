---
handoff_id: 2026-07-09-cat1-cat3-deepseek-fixes-handoff
supersedes: 2026-07-07-cat1-cat3-scoping-handoff
handoff_status: superseded
history: HISTORY#369
---

# Handoff: cat1/cat3 fix attempts with DeepSeek-v4-pro — 4 levers tried, 1 real fixable pattern found

- **Date:** 2026-07-09
- **From:** Claude (Fable)
- **To:** whoever picks up the cat1/cat3 → 0.80 thread next
- **Repo HEAD at handoff:** `88c1816` (`main`, == `origin/main`, tree clean)
- **Operator's standing goal:** LoCoMo cat1 AND cat3 judged score > 0.80 each (memory `project_cat1_coreference_parked_and_20pt_goal`, `project_mem0_parity_goal`).
- **This session's total paid spend:** ~$0.59 (all DeepSeek + gpt-4o-mini judge, all logged and recorded below).

---

## TL;DR

1. **Infrastructure built and shipped first** (HISTORY#366–368): full-fidelity run records (per-case answers, reasoning traces, judge rationale, `context_recall`, `failure_class`, exact token cost) written to a private external drive; a DeepSeek-v4-pro answerer with real reasoning-trace capture. A real bug was caught and fixed live before any paid spend: the `deepseek-reasoner` model id is a **deprecated alias** (DeepSeek retires it 2026-07-24) that silently reroutes to `deepseek-v4-flash` — fixed to explicit `deepseek-v4-pro`, with real live-fetched pricing.
2. **Four fix attempts run today, in order, on the real cat1/cat3 HOLDOUT split (82 cases: 61 cat1 + 21 cat3):**
   - Full run: DeepSeek-v4-pro + the HISTORY#365 improved prompt → cat1 0.6885, cat3 0.4286 (after fixing a token-budget truncation bug found mid-analysis — see below). **Statistically a wash** vs. the prior best cat1 holdout anchor (0.705, gpt-4o-mini, same 61-case set — within the established 0.02 noise margin).
   - A precision-constrained prompt rewrite, tested against the 17 known over/under-generation failures → **completely null: 0 improved, 0 regressed, 0 delta.** Prompt wording is not the lever controlling this behavior.
3. **The most important finding is not a score — it's a measurement correction.** Manually verifying failure cases against their real retrieved context (not the free `context_recall` proxy, which has a precision flaw — see below) found that **9 of 11 rigorously-checked "wrong" verdicts are not fixable answerer errors.** They're gold-label incompleteness (the model correctly reported real, verbatim-stated content the LoCoMo annotator just didn't capture) or genuine retrieval gaps the answerer correctly declined to guess on. **Only 2/11 are real, fixable errors — and both are the same pattern: incomplete search across a large packed context**, not imprecision or over-inclusion.
4. **This has NOT been tried yet:** a fix targeted at that one confirmed pattern (thorough-search, not precision-wording). Nothing else productizable has been found today.

---

## Repo / infrastructure state (all clean, all merged)

- `main` @ `88c1816`. HISTORY chain at **#368**. All four PRs from today (#127, #128, #130, #131, #132 — HISTORY#363–368) merged, checks green, branches pruned. Only pre-existing draft PR #121 (pgvector HNSW) remains open, unrelated.
- `DEEPSEEK_API_KEY` is set (verified live, not printed) in `~/.config/seam/seam.env`, sourced before any DeepSeek run. `SEAM_BENCH_RECORD_DIR=/media/terrabyte/T7/Proprietary/DATA` is also in that file — **not** in `~/.bashrc` (bashrc has an interactive-shell guard that hides exports from non-interactive runs; this bit a prior session, see memory).
- **`external_mount_ready()` guard** in `benchmarks/external/common/run_record.py` refuses to write if the T7 isn't mounted — checked before every run below.
- Full-record schema/how-to: `docs/BENCHMARK_RUN_RECORDS.md`.

---

## The real run + what it found

### Run 1: full holdout, DeepSeek-v4-pro + improved prompt

82 cases (61 cat1 + 21 cat3), broad retrieval (`top_k=300`/`budget=60000`), judge gpt-4o-mini. **Result had a bug**: 4 empty answers, all `finish_reason: length` with `reasoning_tokens: 2048` — the answerer's token budget (floored at 2048) was entirely consumed by DeepSeek's reasoning, leaving zero room for the visible answer. Not a capability failure — a budget bug (I set the floor too low).

**Raw (buggy) result:** cat1 0.6639, cat3 0.4048, aggregate 0.5976, cost $0.4598.
Record: `20260709-102349-locomo-holdout-cat1cat3-deepseek-v4-pro.json` (T7).

### Run 2: token-budget fix

Re-ran just the 4 stuck case_ids (`conv-41::q50`, `conv-42::q78`, `conv-43::q17`, `conv-50::q28`) at an 8192-token budget (4x). All finished cleanly (`finish_reason: stop`). One (the "describe John's attributes" case) needed 7,739 reasoning tokens — nearly maxed even the new budget; **a larger run could still hit this ceiling on similar questions.** Outcomes: 1 correct, 2 partial, 1 incorrect — real variance, not a clean win.

**Corrected combined result:** cat1 **0.6885** (61 cases), cat3 **0.4286** (21 cases), aggregate **0.6220**, fix cost $0.0144.
Record: `20260709-125547-locomo-holdout-cat1cat3-deepseek-v4-pro-tokenfix.json` (T7).

**Honest comparison:** cat1's gap to the prior best holdout anchor (0.705, gpt-4o-mini, memory `project_cat1_answerer_bound`, same 61-case split) narrowed from −0.041 to **−0.0165 — inside the 0.02 judged-noise margin.** DeepSeek-v4-pro + the improved prompt is statistically indistinguishable from the older gpt-4o-mini number on cat1. Not a win, not clearly a loss either — a wash. cat3 (0.4286) is roughly flat vs. the old compact-knee anchor (~0.42, different methodology, weaker comparison).

### Run 3: precision-prompt test (NULL RESULT)

**Hypothesis:** the current prompt's "include EVERY item you find" instruction causes over-generation on some cases while still under-generating on others — an unbalanced, uncalibrated instruction. Rewrote it to add an explicit precision constraint: *"include every item that is explicitly stated... do not add items that are only loosely or tangentially related."* Single-variable change, everything else (model, retrieval, judge) held constant.

**Targeted the 17 cases already diagnosed as over-generation (8) or under-generation (9)** from Run 1/2's failures (excluded the "unknown" bucket and entity-confusion cases — see below).

**Result: 0 improved, 0 regressed, 0 flat-to-different — literally all 17 scored identically to before (all still `partial`, 0.5).** Answers barely changed: `conv-41::q21` still includes "California," `conv-49::q49` still misses "Evan himself." **Prompt wording at this level of specificity is not the lever controlling this behavior.** Cost $0.1016.
Record: `20260709-152111-locomo-holdout-precision-v2-deepseek-v4-pro.json` (T7).

---

## The measurement correction (the actual finding worth acting on)

Before trusting Run 1's failure list, I spot-checked whether the model's "wrong" answers were really wrong, by reading the **real retrieved context**, not just the free `context_recall` proxy (which is a crude token-overlap metric — see the flaw below).

### Gold-label incompleteness is real and material
Checked whether flagged "extra" items the model added were actually **verbatim, explicitly stated** in the retrieved context:
- `conv-41::q21` ("What areas of the U.S. has John been to?"): model added "California" — the context literally says *"we had to California — a gorgeous sunset..."* **Real, true, explicitly stated.** Gold only lists "Pacific northwest, east coast."
- `conv-41::q47` ("What exercises has John done?"): model added "boot camps" and "taekwondo" — John literally says *"I just started going to boot camps"* and *"I'm off to do some taekwondo!"* **Both real.** Gold only lists 4 of his 6 stated exercises.
- Same pattern on `conv-50::q15` ("friends" as a reason Dave visits parks — literally stated, gold only captured "relaxes him").

**The model was correct. The LoCoMo gold answer is incomplete.** No prompt tuning can fix this — there's nothing broken. This directly explains why Run 3 (the precision prompt) produced zero effect: the model wasn't malfunctioning, it was reporting real content a strict judge marked down because gold didn't happen to include it.

### The free `context_recall` metric has a real precision flaw
`benchmarks/external/common/scoring.py`'s `context_recall` (crude gold-token-in-context overlap) **false-positives on generic tokens.** Spot-checked 4 "unknown"-verdict cases the classifier labeled `answerer_miss` (implying the answerer failed to use available evidence):
- `conv-26::q76`: gold "19 October 2023" — `context_recall=0.67` because "october" and "2023" appear elsewhere in the 46k-char conversation for unrelated reasons. The model's reasoning trace shows it actively searched, found no hike-after-roadtrip mention, and **correctly** said unknown.
- Same pattern on `conv-43::q28` (matched on "john"), `conv-44::q44` (matched on "national"+"park"), `conv-50::q7` (context_recall=1.0 with **zero** actual gold words found in context — pure false positive).

**All 4 were correct behavior, not failures.** This means the `failure_class` classifier's `retrieval_miss`/`answerer_miss` split (built in HISTORY#366, `_HIT_THRESHOLD=0.5`) **misattributes some real retrieval gaps as answerer failures.** Worth fixing in the tool itself before trusting `failure_class_counts` at face value on a future run — not fixed yet, flagged here.

### Systematic classification attempt — and its own limitation
Ran a heuristic script classifying all 44 `partial`/`incorrect` verdicts by word-overlap between the model's answer, gold, and context. **This heuristic inherited the same flaw as `context_recall`** (generic-word false positives) — confirmed when 3 of its "true-omission" flagged cases were cases I'd *already* manually verified as correct "unknown" responses. **Do not trust its raw output; script + output are saved for reference but need a real (non-heuristic) pass.**

### Manual re-verification of the remaining "true-error" candidates (7 more cases, via reasoning traces)
- `conv-42::q66`, `conv-43::q70`: correct "unknown" — genuine retrieval gaps or (for q70) a context-only-vs-world-knowledge task-design tension (gold requires knowing real Irish Star Wars filming locations, not something stated in the conversation).
- `conv-44::q53` — **genuine error.** Question needs an inference ("what career fits his love of animals/nature"); the model treated it as needing an explicit statement instead of making the inferential leap the prompt itself instructs for judgment questions.
- `conv-47::q40` — **genuine error.** Found tricks in one message, stopped searching, missed others scattered elsewhere in the same conversation. This is the classic cat1 attrition pattern (memory `project_cat1_answerer_bound`'s 92%→72%→45% funnel), now confirmed at the individual-case level.
- `conv-43::q48`, `conv-47::q22`, `conv-49::q49` — genuinely ambiguous, not resolved without a deeper per-case context check.

**Net, across 11 rigorously-hand-checked cases (not the full 44): 2 confirmed fixable errors, both the same pattern — incomplete search across a large packed context. 9 are not fixable answerer mistakes** (gold-incompleteness, correct retrieval-gap refusals, or task-design ambiguity).

---

## Levers tried across this whole thread — status, don't repeat

| lever | result | verdict |
|---|---|---|
| Retrieval tuning (top_k/budget/decomposition/entity-agg/coreference-scoring) | recall barely moves compact→broad | **exhausted** |
| Prompt v1 ("include EVERY item"), gpt-4o-mini, dev split | +0.041 cat1 / +0.027 cat3 | real but small, and causes new over-gen on holdout |
| Stronger/reasoning answerer (DeepSeek-v4-pro), same prompt, holdout | within noise margin of old anchor | **wash** |
| Prompt v2 (add precision constraint), DeepSeek-v4-pro, 17 known failures | 0/17 changed at all | **null** |

---

## What's genuinely still open (not yet tried)

1. **A fix targeted at the one confirmed pattern** — incomplete search across a large context — is different from "be more precise" (already null) or "include everything" (already causes over-gen). Something like an explicit multi-pass/re-scan instruction, or a structural change (e.g., re-test the already-built `entity_grounded_scoring`/entity-aggregation from HISTORY#321/#358 — parked because it didn't help *retrieval ranking*, but **never tested for generation quality with a capable answerer**). Not scoped or costed yet.
2. **Full classification of all 44 partial/incorrect cases** (only 11/44 rigorously hand-checked here) — would sharpen the true fixable-error percentage and tell you the real achievable ceiling before spending more.
3. **Fix the `failure_class` classifier's threshold** (tooling, not a benchmark lever) — `context_recall >= 0.5` is too loose; false-positives on generic-token overlap. Affects trust in `retrieval_miss`/`answerer_miss` counts on any future run.
4. **Strategic question, not a technical one:** given gold-label incompleteness is real and material here, is 0.80 achievable at all through answer-quality tuning alone on this dataset? Worth deciding before more spend — this is the operator's call, not a technical decision.

---

## Data (all on the private T7, none in the repo)

- `/media/terrabyte/T7/Proprietary/DATA/20260709-095906-...json` — 3-case wiring smoke.
- `/media/terrabyte/T7/Proprietary/DATA/20260709-102349-locomo-holdout-cat1cat3-deepseek-v4-pro.json` — the 82-case full run (buggy token-budget version, still the source of the failure-case analysis above).
- `/media/terrabyte/T7/Proprietary/DATA/20260709-125547-...-tokenfix.json` — the 4-case budget fix.
- `/media/terrabyte/T7/Proprietary/DATA/20260709-152111-...-precision-v2-...json` — the 17-case null-result precision test.
- Each `.json` has a matching `.jsonl` (training-corpus shape).
- Scratchpad driver scripts (session-local, **not committed**, would need to be rebuilt from this doc + `docs/BENCHMARK_RUN_RECORDS.md` if reused): `deepseek_holdout_run.py`, `deepseek_fix_stuck.py`, `deepseek_precision_test.py`, `gold_noise_classification.json` (the flawed heuristic's raw output — reference only, do not trust its tallies).

## Guardrails (do not skip)

- **No paid run without an explicit operator yes** — surface the exact command + cost estimate first, every time, even a $0.10 one (established this session, followed throughout).
- **Never delete anything** — hard rule from this session (memory `feedback_never_delete_without_confirmation`), after a real incident where an unprompted cleanup destroyed an unrelated file. Move aside or ask; never `rm`.
- **DeepSeek's token budget must be generous** (8192+, `SEAM_BENCH_DEEPSEEK_MAX_TOKENS`) — some questions trigger 7,000+ reasoning tokens; a tight budget silently truncates to an empty answer with no error, only `finish_reason: length` in the diagnostics.
- **Always request explicit `deepseek-v4-pro` or `deepseek-v4-flash`** — never the `deepseek-reasoner`/`deepseek-chat` aliases (deprecated, reroute silently, retire 2026-07-24).
- **`unset SEAM_PGVECTOR_DSN`** before any per-scope LoCoMo diagnostic (per-scope SQLite required, or cross-scope contamination).
