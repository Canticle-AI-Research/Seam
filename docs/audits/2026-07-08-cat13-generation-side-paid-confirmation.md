# cat1/cat3 → 0.80: paid confirmation that the wall is (partly) generation-side

- **Date:** 2026-07-08
- **Status:** Diagnostic complete. Confirms the HISTORY#362 handoff's decision (c). No product code changed — productization is a gated decision (see "What NOT to conclude").
- **Spend:** operator-authorized; ≈ $1–1.5 (estimate — see Cost).

## Question

The HISTORY#362 handoff hypothesized (its decision **c**) that cat1 (enumeration)
and cat3 (open-domain inference) are **answerer/generation-bound, not
retrieval-bound**: a free recall-level compact-vs-broad A/B moved cat3 recall
almost not at all (0.402 → 0.379, 67/75 cases byte-flat), yet the *judged*
score sat far below target. The confirming test had to be **generation-side and
paid** (the free levers were exhausted). This is that test.

## Method

Answerer-**prompt** A/B, retrieval held **byte-identical** (same broad profile,
`search_top_k=300` / `context_budget=60000`, same ingested corpus). Only the
answerer prompt varied, via monkeypatch. Split: **dev**, all 10 LoCoMo
conversations, cat1 (221) + cat3 (75) = 296 cases. Answerer + judge both
`gpt-4o-mini`, temp=0 (deterministic), matching the rung-B harness. Clean run:
0 empty answers, 0 judge retries.

- **Baseline prompt** (current `benchmarks/external/common/answerer.py`):
  ends *"Reply with the shortest possible answer, no preamble."*
- **Improved prompt**: drops "shortest possible" (which truncates enumerated
  lists) and explicitly licenses enumeration + inference while staying concise:

  > Answer the question using ONLY the context. If the question asks for
  > multiple things (activities, items, examples, a list), include EVERY one
  > you find in the context, not just the first. If the question calls for a
  > judgment or inference, state the conclusion the context best supports (e.g.
  > yes/no plus the key reason). Return the best supported answer even when the
  > context also contains unrelated snippets. Say 'unknown' only when the
  > context contains no answer candidate. Be concise: give just the answer, no
  > preamble or explanation.

A **free** local-ollama (qwen2.5:14b) smoke first confirmed the plumbing and
showed *why* this needs the paid capable answerer: the local model ignores the
conciseness instruction entirely (both prompts produce near-identical rambling
answers), so the lever is only measurable on a model that actually follows the
prompt — the paid arm. (This matches the handoff's "token_f1 is
verbosity-confounded / the local ladder understates cat1" note.)

## Result (judge_score_mean)

| category | baseline | improved | delta |
|---|---:|---:|---:|
| cat1 single-hop | 0.5498 | 0.5905 | **+0.0407** |
| cat3 open-domain | 0.3600 | 0.3867 | **+0.0267** |
| aggregate | 0.5017 | 0.5389 | **+0.0372** |

Verdict shift (baseline → improved): **correct 76 → 91 (+15)**, partial
145 → 137 (−8), incorrect 75 → 68 (−7).

## What this confirms

**The wall is (at least partly) generation-side.** A pure prompt change, with
retrieval byte-identical, moved BOTH categories' judged scores. If the wall were
retrieval, the answerer couldn't have converted the *same* context into more
correct answers. The handoff's decision (c) is answered: generation-side levers
move the needle, and the "shortest possible answer" instruction was actively
costing correct answers (it suppresses cat1 enumeration and cat3
yes/no-plus-reason inference).

## What NOT to conclude (honest caveats)

- **Nowhere near 0.80.** cat1 is still ~0.21 short, cat3 still ~0.41 short. The
  prompt is a real, free, *fair* lever (the prompt is held constant across
  adapters, so it's not a SEAM-only trick) but **not sufficient** on its own.
- **cat3's +0.027 is only ~1.3× the ~0.02 rung-B noise margin.** cat1's +0.041
  and the aggregate / +15-correct-verdict shift are the robust signals; treat
  cat3's delta as suggestive, not established.
- **Dev split, not holdout.** The prompt was hand-designed (not tuned on dev),
  so overfitting risk is low, but a **holdout** number is required before
  productizing — and that is another paid run (operator-gated).
- One prompt design vs one baseline; a better prompt likely exists.

## Cost

Answerer + judge = 2 × 296 = 592 calls each. The naive call-count scale from
rung-B ($0.29 / 400 calls ⇒ $0.86) **underestimates**: the broad 60k-char
context makes answerer *input* tokens the cost driver (~15k tokens × 592 ≈ 9M
input tokens). Realistic spend ≈ **$1–1.5**. The driver did not capture exact
per-call usage; future paid diagnostics should log `usage` for an exact figure.

## Recommended next levers (operator decides; all but the first are paid/gated)

1. **Holdout-validate the improved prompt**, then productize into
   `benchmarks/external/common/answerer.py` if it holds. This is the
   highest-EV, lowest-cost next step and the natural way to bank the +0.04/+0.03
   without teaching to the test. (One paid holdout run.)
2. **Test a more capable answerer** (gpt-4o / a reasoning model) on cat3 — but
   note the answerer is the *agent's* model, not SEAM's to own, so this informs
   positioning more than it productizes.
3. **Probe cat3 retrieval *content* quality** (free): recall-token overlap can
   be flat while the specific evidence a correct inference needs is absent or
   buried. A free content audit could reveal whether cat3's remaining ~0.41 is
   generation ceiling vs missing evidence.

## Reproduce

Driver (session scratchpad, rebuild from this doc): `cat13_prompt_ab.py`
— `--smoke` (free, local ollama, no judge) validates plumbing; `--paid`
(gpt-4o-mini answerer+judge) runs the A/B. Wraps the tracked
`benchmarks/external/locomo/judged_scorer.py::build_locomo_holdout_scorer`
(with `split="dev"`, cases filtered to cat1/cat3) and monkeypatches
`_ANSWER_PROMPT`. **`unset SEAM_PGVECTOR_DSN`** first (per-scope SQLite;
a set DSN contaminates retrieval across scopes).
