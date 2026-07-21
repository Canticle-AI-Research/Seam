# SEAM Verified Benchmark Runs

This file is the canonical, verifiable record of **specific** SEAM benchmark
runs. Each entry states the exact code provenance, configuration, and results,
and is anchored by the **SHA-256 of the full per-case run record**.

## Why it is structured this way

The full per-case records (every question, gold answer, generated answer, and
judge verdict) are **not committed**: LoCoMo is a licensed dataset and dumping
the per-case rows would redistribute the evaluation set. Those records are
retained privately, byte-for-byte immutable, on the operator's external volume.

What is committed here is designed to be **independently checkable** three ways:

1. **Reproduce it.** Each run lists the exact command. Anyone with an API key
   can re-run from scratch and land on the same aggregate (within the stated
   noise margin).
2. **Recompute it.** Each aggregate is the plain mean of the per-case
   `judge_score` column in the record — not a separately-stored number — so it
   cannot drift from the underlying data.
3. **Anchor it.** The record's SHA-256 is published below. The operator can
   share the record out-of-band with an auditor keyed to that hash; if a single
   byte differs, the hash does not match.

All costs are exact token counts priced from a snapshot table; the numbers, not
the dollar figures, are the claim.

---

## Run 1 — SEAM on LoCoMo, judged holdout A/B (native, strict judge)

The paid answer-quality validation: SEAM's validated retrieval + answer-policy
stack vs. the stock SEAM baseline, same answerer and judge held constant, on the
344-case holdout split the improvement loop never tuned on.

| Field | Value |
| --- | --- |
| Record | `20260716-102125-locomo-holdout.json` (688 case-rows: 344 baseline + 344 candidate) |
| **SHA-256** | `af816aa1e228cb9d264e115f260112363937cd4f8f7f44f6fafc761613012716` |
| Code provenance | git `af5698b`, `seam_version` 1.3.1 |
| Date | 2026-07-16 (HISTORY#405) |
| Split | `holdout`, n=344 |
| Answerer | OpenAI `gpt-4o-mini` |
| Judge | OpenAI `gpt-4o-mini`, `judge/1` (default judge prompt) |
| Noise margin | 0.02 |
| Candidate stack | `--profile broad` (search_top_k=300, context_budget=60000) + `conversation/4` + `inference/high-confidence/2` + `temporal/1` |
| Baseline | stock (all `RetrievalFlags` defaults) |

**Result (aggregate judged score, mean of the per-case `judge_score`):**

| Arm | Aggregate | cat1 (multi-hop, n=61) | cat2 (temporal, n=74) | cat3 (open-domain, n=21) | cat4 (single-hop, n=187) | cat5 (n=1) |
| --- | --- | --- | --- | --- | --- | --- |
| Baseline (stock) | **0.633721** | 0.4918 | 0.4595 | 0.4048 | 0.7727 | 1.0 |
| Candidate | **0.776163** | 0.5738 | 0.7432 | 0.5952 | 0.8743 | 1.0 |
| Delta | **+0.142442** | +0.0820 | +0.2837 | +0.1904 | +0.1016 | 0.0 |

Verdict counts across both arms (688 rows): 402 correct / 166 partial / 120
incorrect. Usage: 5,224,647 tokens; cost $0.797634 ($0.001984 per correct
answer). Every category improved; the delta is ~7× the 0.02 noise margin.

**Reproduce** (operator-gated; `--confirm-paid` is required to spend — without it
the command prints the call-count estimate and makes zero API calls):

```bash
OPENAI_API_KEY=... seam improve validate \
  --locomo-dataset benchmarks/external/locomo/data/locomo10.json \
  --locomo-scopes 10 --split holdout \
  --answerer openai --answerer-model gpt-4o-mini \
  --judge openai    --judge-model    gpt-4o-mini \
  --profile broad \
  --flags '{"conversation_adapter":"conversation/4","inference_policy":"inference/high-confidence/2","temporal_policy":"temporal/1"}' \
  --confirm-paid
```

> Dry-run first (omit `--confirm-paid`) to print the exact call-count/cost
> estimate and make zero API calls; add `--confirm-paid` to spend. Records land
> in `$SEAM_BENCH_RECORD_DIR`.

**Honest caveats.** `0.776163` is the single highest verified native number, but
it is only **+0.0073 over the prior clean-stack run** (HISTORY#390, `0.768895`,
same answerer/judge, stack `conversation/2 + inference/high-confidence/1 +
temporal/1 + broad`) — inside a few noise margins. Per-case analysis
(HISTORY#405) found the `conversation/4` component in this run is net-negative on
cat1 (its 0.5738 is below the #390 stack's cat1 0.6148); `conversation/2` remains
the recommended base going forward. cat3's holdout n is only 21 here, so its
per-category number is high-variance. This is a **judge/1 (strict)** score and is
**not** on the same scale as Run 2's lenient binary judge below.

---

## Run 2 — SEAM on mem0's own harness (competitive standing, lenient judge)

The reverse test: SEAM answering **mem0's unmodified benchmark harness**
(`mem0ai/memory-benchmarks` @ `4b61c5d`) as a drop-in Mem0-OSS HTTP server (the
`seam_mem0_server` shim), scored by that harness's own lenient binary judge —
the basis on which the public mem0 LoCoMo table is reported.

| Field | Value |
| --- | --- |
| Record | `20260715-091018-mem0-harness-cat13.json` (378 evaluations) |
| **SHA-256** | `e93cc7a4cd2611bd7b68906d90d8ad0d63684a933ee637b50403fb74104c2b4f` |
| Harness | `mem0ai/memory-benchmarks` @ `4b61c5d`, unmodified |
| Date | 2026-07-15 (HISTORY#400) |
| Answerer / Judge | OpenAI `gpt-4o-mini` / harness lenient binary judge |
| Retrieval depth | top_k 200 |
| Scope | categories 1 & 3, 378 questions |

**Result (harness accuracy = correct / total):**

| Category | Correct / Total | Accuracy |
| --- | --- | --- |
| Multi-hop (cat1) | 250 / 282 | **88.65%** |
| Open-domain (cat3) | 83 / 96 | **86.46%** |
| Overall | 333 / 378 | **88.10%** |

Both categories clear 0.80 on mem0's own harness and judge. Zero empty answers.

**Reproduce:** stand up `seam_mem0_server` (the HTTP shim) with the champion
stack in env (`SEAM_CONVERSATION_ADAPTER`, `SEAM_INFERENCE_POLICY`,
`SEAM_TEMPORAL_POLICY`, `SEAM_RETRIEVAL_PROFILE=broad`), then run the mem0 harness
`locomo.run --backend oss --mem0-host <url> --categories 1,3`. See
`benchmarks/external/mem0_harness/README.md`.

**Honest caveats.** This is a **lenient binary judge** (correct/incorrect), which
scores materially higher than SEAM's native `judge/1` in Run 1 — the two numbers
are **not comparable** and must not be averaged or presented side by side as one
scale. Its value is that it is the *same* judge mem0 reports against, so it is the
fair basis for a head-to-head on the public LoCoMo table.

---

## Not yet validated

The `answer_contract=exact-answer/1` lever (HISTORY#408) is **built but has no
benchmark result** and therefore has no entry here. It will be added only after
its operator-gated holdout A/B runs. No result is claimed for it.
