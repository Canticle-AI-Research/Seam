---
handoff_id: 2026-07-18-answerer-parity-probe-handoff
supersedes: 2026-07-17-event-count-context-handoff
handoff_status: current
history: HISTORY#422
---

# Handoff: run the answerer-parity probe on the Mem0 cat1 lane

- **Date:** 2026-07-18
- **Branch:** `agent/roadmap-zep-after-benchmarks` (PR #153, draft)
- **State:** runner built, hermetically tested, free-dry-run verified; paid run
  awaiting execution. **The operator has approved this spend** (~$1.10 cat1,
  ~$1.35 with cat3).
- **Executor:** run it exactly as written; do not modify selection or models.

## Why this probe is next (the evidence chain)

1. **HISTORY#400**: SEAM scored 250/282 cat1 (88.65%) inside mem0's unmodified
   harness — but with a **gpt-4o-mini** answerer/judge, while mem0's published
   table uses their **gpt-4o** defaults. The "beat 91%" comparison is
   therefore cross-answerer.
2. **HISTORY#420** mining: 21 of the 32 cat1 misses have all/most gold
   evidence already retrieved — answer-side failures are exactly what a
   stronger answerer fixes.
3. **HISTORY#421** free retrieval diff: current code is neutral vs the stored
   retrieval (miss-set evidence unchanged 44/45), so the FROZEN stored
   contexts remain representative — a stored-context probe is valid and a
   fresh $0.70 judged re-baseline was explicitly deferred as noise.

If a large fraction of misses flip under gpt-4o, matched-answerer conditions
likely clear 91% with **zero new code**, and the #420 levers become margin.

## What the runner does

`benchmarks.external.mem0_harness.parity_probe_answerer` (committed, 3
hermetic tests): for every stored top-200 **miss**, it re-answers the frozen
stored context with **both** gpt-4o-mini and gpt-4o same-day, and judges both
arms with **gpt-4o** (the published judge contract) through the verbatim
upstream prompts. This isolates the answerer variable: baseline-arm vs
parity-arm delta is answerer strength alone; baseline-arm vs stored-artifact
delta is judge-model drift. It imports no SEAM runtime module (safe while
event-count/distinct/2 is being edited) and never re-runs retrieval.

## Mandatory setup

```bash
export HF_HUB_CACHE=/media/terrabyte/T7/hf-cache HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export SEAM_BENCH_RECORD_DIR=/media/terrabyte/T7/Proprietary/DATA
# OPENAI_API_KEY comes from ~/.secrets (source it in the run shell)

# pinned upstream harness (prompts are loaded from this clone by file path)
git clone https://github.com/mem0ai/memory-benchmarks.git /tmp/memory-benchmarks
git -C /tmp/memory-benchmarks checkout 4b61c5d
```

## Free verification first (zero spend)

Already verified this session, rerun if anything changed: the runner with a
fake call selects **32 cat1 misses** (45 with `--categories 1,3`) and renders
~2.8M answer-prompt chars. Any other selection count means the artifact or
code drifted — stop and investigate.

## The paid run

```bash
. ~/.secrets
.venv/bin/python -m benchmarks.external.mem0_harness.parity_probe_answerer \
  /media/terrabyte/T7/Proprietary/DATA/20260715-091018-mem0-harness-cat13.json \
  --harness-root /tmp/memory-benchmarks \
  --categories 1,3
```

Cost estimate from the dry run: mini arm ~$0.07 + gpt-4o arm ~$1.22 + judges
~$0.05 ≈ **$1.35** (cat1-only: ~$1.10). Aggregate summary prints to stdout;
the full per-case record lands beside the source artifact (private, never
commit it).

## Reading the result

- **`parity_correct` (cat1) ≥ 7**: answerer parity alone would clear 91%
  (250 + 7 = 257/282). The next paid step is the full matched-answerer
  harness run (~$10–15, operator-gated separately) — no new code first.
- **3–6**: parity is real but insufficient — combine with SOL's
  `event-count/distinct/2` microgate result before deciding on a full run.
- **≤ 2**: the gap is genuinely memory-layer — proceed straight to the #420
  levers (evidence-digest projection, second-hop retrieval assembly).
- Also read `baseline_rerun_correct`: if the mini arm under the gpt-4o judge
  scores well above 0, part of the published gap is **judge**-model drift,
  not answerer strength — report the two effects separately.
- Watch conv3_q61 / conv5_q36 in any future full run (#421: the only two
  correct cases whose evidence regressed).

## Standing context

- SOL's `event-count/distinct/2` (same-event grouping) is **uncommitted and
  in-flight** in the working tree — do not touch those files; its microgate
  rerun (existing runner, ~$0.08) fires once it lands.
- hc/3 is tested-and-parked (#419 preflight negative; cat3 naming wall is
  retrieval-side). exact-answer/1 parked (#412). Full Mem0-harness rerun for
  event-count/distinct/1 NOT green-lit (#417, 6/14 flips).
- Scoreboards stay separate and are never averaged (#415).
