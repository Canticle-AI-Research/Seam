---
handoff_id: 2026-07-15-cat1-cat3-past-80-handoff
supersedes: 2026-07-13-improve-validate-profile-complete
handoff_status: current
history: HISTORY#397
---

# Handoff: push cat1 + cat3 past 0.80 (operator paid-authorized)

- **Date:** 2026-07-15
- **Active branch:** `agent/cardinality-constraint`
- **Mission (operator):** get cat1 (multi-hop) AND cat3 (open-domain) each past
  0.80. Champion #390: cat1 **0.6148**, cat3 **0.5952**. Operator granted blanket
  paid permission to verify/validate.

## Where main is

`main` @ `96e20ba` (PR#148 merged): the validated champion stack
conversation/2 + inference/high-confidence/1 + temporal/1 + broad = **0.7689**,
plus parked negatives (conversation/3, temporal/2) and both 429-backoff fixes.
Two PRs OPEN awaiting merge: **PR#149** (mem0-harness HTTP shim + retirement of
the stale adapter.py, HISTORY#393/#394 — CI should be green) and this branch's
work (not yet PR'd).

## What is BUILT on `agent/cardinality-constraint`

1. **conversation/4** (COMMITTED, HISTORY#395, pushed): cardinality constraint —
   keeps v2's exhaustive scan, replaces completeness pressure with precision
   (include directly-responsive items, exclude adjacent ones). Targets the
   over-generation that judge/1 penalizes. Opt-in, default off. Also on this
   branch: the mem0 predict-only smoke result and the #396 problem scan.
2. **inference/high-confidence/2** (BUILT, TESTED, functionally verified, NOT
   YET COMMITTED — uncommitted in working tree: `seam_runtime/conversation.py`,
   `seam_runtime/self_improve.py`, `tests/audit/test_semantic_conversation_adapter.py`):
   extends inference/1 with (a) anti-over-abstention (don't answer 'unknown'
   when one clear answer exists) and (b) enumerate-then-count for 'how many'.
   Targets the cheapest 6.5-pt bucket from the #396 scan.

## FUNCTIONAL VERIFICATION (done, ~cents) — levers work, not a wasted test

Ran gpt-4o-mini on the real #390 miss cases using each case's STORED
retrieved_context (no re-retrieval), champion prompt vs new-lever prompt
(`scratchpad/microverify.py`):
- "Gina's favorite dance style" (gold Contemporary): champion → **Unknown**,
  new levers → **"contemporary"** ✓ (inference/2 anti-abstention FIRES correctly)
- "How many tournaments has Nate won" (gold seven): champion → "4",
  new levers → "5" ✓ (counting moves toward gold, not all the way)
- Harder cat3 (composer→John Williams, park→Voyageurs): still Unknown even with
  new levers — genuinely hard world-knowledge, inference/2 alone insufficient.

**Read:** inference/2 is functional and recovers over-abstention + improves
counting. conversation/4's effect is being measured by the paid A/B below. The
hard cat3 world-knowledge cases will need a STRONGER open-domain licensing lever
(inference/2 is too cautious for "name the specific real-world entity from
clues").

## IN-FLIGHT paid run (check first on resume)

**c4 A/B running** at handoff (PID was 1929451, ~19 min elapsed of ~40):
`seam improve validate --profile broad --flags conversation/4 +
inference/high-confidence/1 + temporal/1` vs stock, judge/1, 344 holdout.
Log: `scratchpad/paidrun-c4.log`; record lands on T7
`/media/terrabyte/T7/Proprietary/DATA/2026071?-*locomo-holdout.json`. This
measures **conversation/4 alone** (champion inference, not inference/2). Read
its candidate cat1/cat3 vs champion 0.6148/0.5952.

## RESUME STEPS (in order)

1. Read `scratchpad/paidrun-c4.log` for the conversation/4 result (or the newest
   T7 record). Note candidate cat1/cat3.
2. Confirm the full suite is green (a run was launched: `scratchpad/fullsuite-inf2.log`),
   then COMMIT inference/high-confidence/2 with HISTORY#397 + full chain
   (rebuild_index, streams mirror, cross-index, snapshot, verify_* — and do NOT
   edit the entry after rebuilding; that bug bit twice, see incident log).
3. Launch the DECISIVE cat1/cat3 A/B (paid-authorized): candidate =
   conversation/4 + inference/high-confidence/2 + temporal/1 + broad vs stock,
   judge/1, 344 holdout, with `SEAM_BENCH_PROVIDER_RETRY_BASE_SECONDS=8
   SEAM_BENCH_PROVIDER_MAX_RETRIES=10` and `SEAM_BENCH_RECORD_DIR=/media/.../DATA`.
   Read candidate cat1/cat3 absolute vs 0.80.
4. HONEST CEILING WARNING (from #396 scan): cat1 has ~10 misses where the full
   gold is already in the answer but judge/1 marks partial — unfixable by us
   (judge/2 rejudge confirmed). cat1 *past 0.80 on judge/1* is near that wall;
   if blocked, cat1 clears 0.80 honestly only under the mem0-harness lenient
   judge (shim on PR#149, predict-only proven, scored calibration stalled in
   THEIR answer/judge phase — retry cleanly).
5. If cat3 still short after step 3: build a stronger open-domain world-knowledge
   licensing lever (inference/high-confidence/3 or an open-domain conversation
   directive) — inference/2 is too cautious for "name the entity from clues".

## Guardrails / gotchas

- Launch detached runs with setsid; the parent PID exits immediately — the real
  worker is the SECOND seam PID (grep `[s]eam --db.*paidrun`).
- HISTORY `--body` via a FILE (stdin), never inline: backticks and `$` get
  shell-substituted (corrupted #395; fixed).
- Never edit a HISTORY entry after rebuilding the index/snapshot without
  re-running the full chain (broke the streams test once; logged).
- mem0 harness clone + venv live in `scratchpad/memory-benchmarks` +
  `scratchpad/mbvenv`; their default answerer/judge is now **gpt-5** (pricey) —
  override to gpt-4o-mini for cheap calibration.
