---
handoff_id: 2026-07-20-derived-facts-clause-scope-and-sentence-grounded-next
supersedes: 2026-07-20-derived-facts-landed-and-kb-scaffold
handoff_status: superseded
history: HISTORY#438
---

# Handoff: derived-facts free preflight built; grounded-clm/2 landed 0-flip; sentence-grounded is the next lever

- **Date:** 2026-07-20
- **Branch:** `agent/roadmap-zep-after-benchmarks` (PR #153, draft)
- **Pushed:** NO. HISTORY#438 + code committed locally only; awaiting operator "push it".
- **Spend:** $0 this session. All measurement was FREE (local qwen2.5-7b + local bge).

## The one-line state

The strict verbatim-grounded derived-facts mechanism is **~0-lift** on the #429
cat1/cat3 miss set, and this is now **measured, free**. `grounded-clm/2`
(clause-scoping) is correct/tested/landed but adds ~0 flips. The next lever the
operator chose is **sentence-grounded facts** (paraphrase + source-sentence
provenance), free-ceiling **60/63 (95%)** reachable — but VALIDATE THE REAL GATE
FREE before building (see the logged lesson).

## What landed this session (HISTORY#438)

1. **`benchmarks/external/mem0_harness/preflight_derived_facts.py`** — the free
   derived-facts coverage/precision/lift preflight (the #436 "highest-value next
   build"). Extracts grounded-clm facts from the GOLD turns of the stored matched
   misses via real `compile_nl`; reports yield, grounding precision, and a
   **bge-space** wording-closure delta. Run it:
   ```
   HF_HUB_CACHE=/media/terrabyte/T7/hf-cache HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
   SEAM_OLLAMA_TIMEOUT_S=600 \
   python -m benchmarks.external.mem0_harness.preflight_derived_facts \
     /media/terrabyte/T7/Proprietary/DATA/20260719-161639-mem0-harness-cat13-matched-final.json \
     --model qwen2.5-7b-1m:latest --policy grounded-clm/1 [--limit N] [--no-floor]
   ```
   Validated: reconstructed turn envelopes match the artifact's stored memory
   strings **417/417 verbatim** (reproduces the mem0-harness photo-tag + YYYY-MM-DD
   date). **Methodology gotcha baked in:** the artifact's stored `score` is SEAM's
   retrieval-PIPELINE score in an unrecorded embedding space (Pearson ~0.1 vs a
   plain bge cosine) — NOT reproducible — so the tool measures entirely in bge-small
   space (the embedder grounded-clm forces on) and reports the relative closure
   delta, not an absolute floor. Do not "fix" this to compare against the stored score.

2. **`grounded-clm/2`** (default-off, v1 byte-identical): relaxes the
   complete-clause gate to validate the S-R-O against its enclosing CLAUSE
   (`clause_window` in `nl_extract.py`) instead of the whole proposition. Files:
   `nl_extract.py` (helper), `nl.py` (`_candidate_claim_is_lossless(clause_scoped=)`),
   `derived_fact_context.py` (`GROUNDED_CLM_V2`/`GROUNDED_CLM_POLICIES`/`enabled`),
   `vector.py` (render generalized to `grounded-clm/*`), 4 new tests in
   `tests/fidelity/test_nl_extract.py`.

## The measured numbers (free, qwen2.5-7b, $0)

- **grounded-clm/1**: 7/63 misses reached, yield **0.043**/gold-turn, precision
  **1.00**, mean wording-closure **+0.085** (6/7 beat the raw gold turn). Works
  where it fires; fires on ~nothing.
- **grounded-clm/2**: ~0 additional facts. The dominant wall is NOT complete-clause;
  it's the OTHER strict guards — quoted objects (`"Little Women"`), adverbial S-R-O
  gaps, and genuinely non-first-person turns. Each real turn trips at least one.

## Why (the strategic fork — this is the real deliverable)

SEAM's **verbatim-grounding auditability** guarantee is in direct tension with the
fact **coverage** that makes mem0's derived facts win — mem0 stores loose
paraphrases. Free ceiling if we keep provenance to the exact source SENTENCE but
drop the verbatim-span rule (paraphrase fact): **60/63 misses (95%)** have a
first-person declarative gold sentence, vs 7 for the strict contract.

## NEXT (operator-chosen): sentence-grounded facts

- **Validate FREE first** (logged lesson: v2 was built on an optimistic regex
  ceiling before running the real gate). Before any policy plumbing, run the
  relaxed gate against the 60 candidate misses' gold turns and confirm real yield.
- Design intent: fact text = model paraphrase; provenance = exact source-sentence
  span (still auditable: the sentence must support the fact). Keep the ≤20% fact
  ceiling splice (#369 guard) and default-off.
- Then a paid answerer microgate only if free yield + closure clear the ratchet
  bar (~+3, aim +5). See [[feedback_ratchet_small_wins]] — winning by a little is winning.

## Infra notes

- **Extractor model:** imported the operator's on-T7 `Qwen2.5-7B-Instruct-1M-Q4`
  GGUF into Ollama as **`qwen2.5-7b-1m`** (4.7 GB, 100% GPU on the 8 GB RTX 2070,
  ~6 s/turn). `qwen2.5:14b` (9.9 GB) CPU-spills 69% → >300 s/turn; do not use it for
  corpus runs. Raise `SEAM_OLLAMA_TIMEOUT_S` above 300 for any CPU-spilling model.
- **Full local suite green** requires the T7 offline HF env AND `PGVECTOR_TEST_DSN`
  (pgvector container `seam-pgvector` on :55432, db/user `seam`, pw via
  `docker inspect`). Without the DSN the strict-no-skip guard fails on one pgvector
  test (env-gated, not a real failure).
- **PR #153** (draft, base `main`, 28 commits, mergeable) had one failing CI check
  `test-and-benchmark`/"Run tests" at #437 (pre-#438) — local full suite passes
  clean, so it's likely a self-hosted-runner env issue; confirm before any merge.
