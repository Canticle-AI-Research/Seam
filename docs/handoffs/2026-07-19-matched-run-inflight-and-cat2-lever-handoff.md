---
handoff_id: 2026-07-19-matched-run-inflight-and-cat2-lever-handoff
supersedes: 2026-07-19-matched-answerer-full-run-handoff
handoff_status: superseded
history: HISTORY#427
---

# Handoff: matched run IN FLIGHT, cat2 lever BUILT, parity probe queued

- **Date:** 2026-07-19
- **Branch:** `agent/roadmap-zep-after-benchmarks` (PR #153, CI fully green on
  the new self-hosted runner)
- **Spend state:** operator approved "run paid benchmarks" broadly; OpenAI and
  GitHub billing both restored this session.

## 1. The matched-answerer cat1+cat3 run is EXECUTING right now

The #423-gated ~$10–15 run (gpt-4o answerer + gpt-4o judge, mem0 harness @
`4b61c5d`, top-200, single cutoff) is running detached on this box:

- Facade: `seam_mem0_server` from a clean worktree @ `db47740` (runtime
  byte-identical to current HEAD), port **8902**, scratch DB, #400 env
  (broad + conversation/2 + hc/1 + temporal/1 + T7 offline HF).
- Free predict pass completed cleanly first: 378/378 questions, median 200
  search results, zero empties.
- Paid evaluate: `--max-workers 2 --rpm 8`, self-throttling against the org's
  **30K TPM gpt-4o cap** at ~2.4 cases/min (~1.2% empty-answer corruption
  rate, strip-and-rerun at the end). ~241/378 were judged at handoff time;
  log: scratchpad `cat13-matched-resume.log`.

**To finish/verify after it completes** (also run if it died mid-way — the
per-case checkpoints make every step idempotent):

1. Strip any empty-answer cases and relaunch the same command until zero
   remain (proven recipe, three uses today):
   `cutoff_results` deleted for any case whose
   `cutoff_results.top_200.generated_answer` is blank, then rerun
   `python -m benchmarks.locomo.run --project-name seam-cat13-matched
   --backend oss --mem0-host http://127.0.0.1:8902 --dataset-path
   ~/seam_benchmarks/track_m/locomo/locomo10.json --categories 1,3 --top-k
   200 --top-k-cutoffs 200 --answerer-model gpt-4o --judge-model gpt-4o
   --max-workers 2 --rpm 8 --evaluate-only` from `/tmp/memory-benchmarks`
   (its `.venv`, `. ~/.secrets` first). If the facade on :8902 is down it is
   NOT needed for evaluate-only.
2. Assemble the complete artifact to T7 (never commit) and compute per-cat
   scores from `cutoff_results.top_200.score >= 1`.
3. **The claim being tested:** stored-mini cat1 was 250/282 = 88.65%; the
   #423 parity probe projects ~95.0% matched vs mem0's published 91.3%.
   Watch conv3_q61 / conv5_q36 (#421 fragile pair). cat3 published bar is
   72.7% (already topped at 86.46% mini).
4. Chain the result (HISTORY, status, scoreboards stay separate per #415).

## 2. NEXT PAID after the matched run: cat4+cat2 answerer-parity probe

Committed runner, zero code needed (~$6 both cats, ~$3.2 cat4-only — the
"~$1" earlier estimate was wrong, 198 misses not 45):

```bash
. ~/.secrets
.venv/bin/python -m benchmarks.external.mem0_harness.parity_probe_answerer \
  /media/terrabyte/T7/Proprietary/DATA/20260719-114500-mem0-harness-cat24-recon-final.json \
  --harness-root /tmp/memory-benchmarks --categories 2,4
```

Reading: cat4 (108 misses, gap 4.0 pts to 91.2) — ≥34 net flips ⇒ matched
conditions top mem0's single-hop with zero code. cat2 (90 misses, gap 20 pts)
— if gpt-4o alone fixes most, the new lever below is margin; if not (expected,
the failure is instance-selection in context), the lever is the path.

## 3. cat2 lever BUILT this session: `temporal-instance/1` (default OFF)

- `seam_runtime/temporal_instance_context.py` (new, self-contained; no import
  from `event_count_context` — SOL edits that module) + facade hook in
  `seam_mem0_server.py` (`_apply_temporal_context_policy`, runs only when the
  count policy did not project).
- Enablement is facade-scoped by design while unvalidated:
  `SEAM_TEMPORAL_CONTEXT_POLICY=temporal-instance/1` env var, NOT a
  RetrievalFlags field (SOL is editing retrieval.py; core productization
  follows a measured win).
- Mechanism: for temporal questions, prepends a disposable `SEAM-TEMPORAL/1`
  date→observations index parsed from the `[Speaker YYYY-MM-DD]` stamps, with
  instance-matching + relative-wording-resolution instructions — the
  retrieval-side twin of native `temporal/1`, which cannot reach this lane.
- 8 hermetic tests in `tests/audit/test_temporal_instance_context.py` (new
  file, not SOL's); full suite exit 0 with SOL's WIP in tree; ruff clean.
- **Not yet validated.** Validation ladder: free structural preflight over the
  90 stored cat2 miss contexts, then an answerer-only microgate (mini, ~$0.4)
  projection-on vs off, gated by the probe result in §2.

## 4. Standing state

- CI: all 6 jobs green on the self-hosted runner `seam-terrabyte`
  ([[reference-self-hosted-ci-runner]]); windows leg manual-only
  (`ci-windows.yml`). Stale HF token moved to
  `~/.cache/huggingface/token.stale-2026-07-19`.
- Scoreboard (mini answerer, mem0 harness): cat3 86.46 (topped, bar 72.7),
  cat1 88.65 (bar 91.3, matched run above decides), cat4 87.16 (bar 91.2),
  cat2 71.96 (bar 92.0). Native champion 0.7762 unchanged.
- SOL's `event-count/distinct/2` still uncommitted in-tree — untouched.
- Operator-flagged open item: quoted-cost vs actual-spend divergence
  (deferred by operator; note the cost-estimate misses today were mine, not
  `pricing.py`'s — its usage-token path is sound, the mem0 lane just never
  captures usage).
