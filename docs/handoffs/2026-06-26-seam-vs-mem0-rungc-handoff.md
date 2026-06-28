# Handoff: SEAM-vs-mem0 head-to-head (Strand C) — rung C needs a clean re-run

**Date:** 2026-06-26 · **From:** Claude (Opus) · **To:** next agent (GPT/Codex)
**Goal (operator's words):** "dependable = SEAM is as good or better than mem0." Operator wants a **CLEAN WIN** — beat mem0 in a fair, judged, apples-to-apples head-to-head where mem0 is NOT handicapped (not just beating mem0's *published* number, which we've already matched).

## Current state of main (all merged, clean, HEAD == origin/main)
- **#333 / PR #106** — shared-answerer wrapper (`benchmarks/external/common/answerer.py`: `build_answer_prompt`, `generate_short_answer`, `SharedAnswererAdapter`); `run.py:_maybe_wrap_answerer` wraps mem0/zep when an answerer is set; `seam.py:_generate_answer` single-sources the prompt. Makes the SEAM-vs-mem0 harness fair (same answerer over both).
- **#334 / PR #107** — `JudgedLocomoScorer.score()` now applies `context_budget` to `adapter.budget` (it was dropped → broad got compact's 8000-char context = a fake broad). +2 tests.
- **#335 / PR #108** — **mem0 adapter fixed for mem0ai 2.0.2**: `Memory.search()` now takes `filters={'user_id': scope}` + `top_k=` (was top-level `user_id` + `limit`). `add`/`delete_all` unchanged. Stub test + a money-leaking CLI test hardened.
- Last HISTORY id = **335**. Next = #336. Chain is green (integrity/continuity/routing/streams).

## Results so far (the A→B→C plan; A,B done)
- **Rung A (free, local Ollama):** broad COLLAPSES for weak local answerers (qwen2.5 3B and 14B): compact token_f1 ~0.34–0.36 vs broad ~0.03. → compact is right for local; broad needs a capable cloud answerer. Driver: `scratchpad/rung_a_ab.py`.
- **Rung B (paid ~$0.29, gpt-4o-mini, 100 holdout cases / all 10 convos):** **broad WINS +0.070** (compact 0.465 vs broad 0.535; 3.5× the 0.02 margin; win in cat1 +0.098). → broad validated for capable answerers. Driver: `scratchpad/rung_b_paid.py`.
- **Rung C (paid, IN PROGRESS — DIED):** SEAM(broad) vs mem0, HALF of LoCoMo-10 = first 5 convos / **764 questions** / 2760 mem0 ingest turns. Operator approved ~$4. Driver: `scratchpad/rung_c_paid.py`.
  - **SEAM(broad) side COMPLETED, banked:** `judge_score_mean = 0.674` (context_recall 0.862, 43min). Per-cat: cat1 0.528 / cat2 0.535 / cat3 0.293 / cat4 0.817 / cat5 0.75. Report saved at `scratchpad/rungc_seam.json`. **0.674 already matches/passes mem0's published paper number (~66.9% LLM-judge, gpt-4o-mini judge, arXiv 2504.19413).**
  - **mem0 side FAILED:** the process died early in mem0 ingest. Log `scratchpad/rung_c.log` shows only 2 `LLM extraction failed: 429` (TPM rate limit: gpt-4o-mini org limit **200000 tokens/min**), then the process ended with **no `RUNGC_EXIT` line and no mem0 result** (killed by signal, NOT a clean exception; NOT OOM — 20GB RAM free, no oom-killer entry; ollama not resident). Cause unconfirmed — likely a propagated 429 from mem0 ingest OR an external kill. **No mem0-in-our-harness number was obtained.**

## THE BLOCKER → what "a clean win" needs
mem0's per-turn LLM extraction (2760 adds, prompts that GROW as memory accumulates → ~9.5k tokens each late in a conversation) bursts past the 200k TPM limit. If mem0 drops facts on rate-limited turns, its memory is incomplete and it scores artificially low = an UNFAIR handicap. Operator explicitly does not want that.

## NEXT STEPS (do these)
1. **Diagnose the death** (quick): re-run a tiny mem0 slice and watch; confirm whether the kill was a propagated 429 (mem0's `add` normally catches extraction 429 and logs "LLM extraction failed" + continues, so ingest shouldn't crash — check the mem0 *search*/answer path and the shared-answerer `_openai_short_answer`, which does NOT catch 429 and would propagate → crash `run_benchmark_grouped`).
2. **Add rate-limit resilience for a FAIR mem0 run:**
   - The OpenAI SDK auto-retries 429 (2x) but sustained TPM pressure exhausts it. Options: (a) **pace mem0 ingest** — sleep/throttle so token rate stays < ~180k/min; (b) raise mem0's LLM `max_retries` via `config_overrides={'llm':{'provider':'openai','config':{'model':'gpt-4o-mini','max_retries':8}}}` (verify mem0 2.0.2 honors it); (c) wrap `adapter.answer`/the answerer in retry-with-backoff (the shared answerer + judge can also 429); (d) reduce slice to 2–3 convos (less memory accumulation → smaller prompts → under TPM) — but then RE-RUN SEAM on the SAME slice for apples-to-apples (SEAM 0.674 was on 5 convos).
   - **Make the run crash-resilient:** pass a `checkpoint` fn to `run_benchmark_grouped` and/or wrap each adapter run in try/except so a late crash doesn't lose the whole spend; save partial results.
3. **Re-run mem0's side cleanly** (SEAM 0.674 is banked — only mem0 needs re-running on the matching slice). Compare `judge_score_mean`. For a "complete" win, SEAM(broad) ≥ mem0 by a clear margin, mem0 run with ~zero failed extractions.
4. **Then:** consider the full LoCoMo-10 (~1540 Q) run; and **productize** the validated capable-answerer `broad` profile into core `RetrievalFlags` (operator rule: productize to core, not benchmark-only).
5. **SEAM chain:** this handoff doc + any fix is a repo change → append HISTORY #336, rebuild index, snapshot, bump PROJECT_STATUS handoff, verify integrity/continuity/routing/streams, commit on a branch + PR (operator: merge promptly, --squash). NO Claude/agent attribution in commits. NO secrets (the pgvector DSN password) in any committed file.

## How to run (environment)
- `cd /home/terrabyte/Documents/Projects/Seam && source .venv/bin/activate && export PYTHONPATH=$PWD`
- `OPENAI_API_KEY` is set in the env (gpt-4o-mini; **200k TPM limit** is the constraint). `SEAM_PGVECTOR_DSN` is set (pgvector :55432); tests want `PGVECTOR_TEST_DSN="$SEAM_PGVECTOR_DSN"`. **Never print/commit the DSN value.**
- mem0ai 2.0.2 + chromadb 1.5.7 installed; mem0 extraction PINNED to gpt-4o-mini via `config_overrides`. spaCy-absent warnings are harmless (mem0 falls back to the LLM extractor).
- Full canonical suite: `pytest test_seam_all/ tools/history/test_history_tools.py tools/streams/ tests/` with `PGVECTOR_TEST_DSN` set (strict no-skip; expect exit 0, 2 xfails, 0 failures).
- Run rung C: `python scratchpad/rung_c_paid.py` (SCOPES=5 hardcoded; edit for fewer convos). It runs SEAM first, then mem0; writes `rungc_seam.json` / `rungc_mem0.json`.

## Key memory files (operator's persistent memory)
`project_mem0_parity_goal.md` (the whole A→B→C log incl. rung A/B numbers + "dependable=beat mem0" vocab), `project_competitor_mnemosyne.md` (mnemosyne = positional twin), `feedback_no_paid_run_without_prompt.md`, `feedback_always_test_before_building.md`.

## Headline for the operator
SEAM(broad) = **0.674** on half of LoCoMo-10 (gpt-4o-mini judge) — already at/over mem0's published ~0.669. The fair mem0-in-our-harness number is NOT yet obtained (mem0 run died on rate limits). Getting that clean number is the one remaining task for the "complete win."
