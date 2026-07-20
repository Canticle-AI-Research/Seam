---
handoff_id: 2026-07-17-hc3-open-domain-cat3-handoff
supersedes: 2026-07-17-exact-answer-contract-handoff
handoff_status: superseded
history: HISTORY#413
---

# Handoff (for SOL): validate inference/high-confidence/3 (open-domain cat3 naming)

- **Date:** 2026-07-17
- **Branch:** `agent/roadmap-zep-after-benchmarks` (== `main`)
- **Task for SOL:** run the paid A/B for the new `inference/high-confidence/3`
  lever and report cat1/cat2/cat3/cat4 separately. **Operator gates every paid
  run** — surface cost and get an explicit go first.

## Context: why this lever exists

The exact-answer contract (`answer_contract=exact-answer/1`, HISTORY#408) was
**A/B-tested and REJECTED** (HISTORY#412): 0.7471, below both champions; its
precision-prune *deleted gold* (judge/1 rewards fuller answers). Parked
default-off.

The free per-case scan of the #390 champion's 11 cat3 misses that followed found
the real open-domain gap: ~4–5 cases where the model **abstained/described
instead of naming** a well-known entity the clues uniquely identify — composer
**John Williams** (plays Star Wars tunes), **Voyageurs** National Park, Star
Wars Ireland locations, **Exploding Kittens**. That is the OPPOSITE of pruning:
completeness + naming.

`inference/high-confidence/3` (HISTORY#413) builds on hc/2 and licenses naming a
well-known real-world entity from uniquely-identifying clues, with an ambiguity
guard (don't guess when clues fit several entities). Opt-in, default-off,
defaults byte-identical; affected tests + smoke green, ruff clean, full suite
green except 2 embedder-env mem0-server tests that pass with the HF env below.

## ⚠️ MANDATORY env (the cause of two prior zero-spend run failures)

The bge embedder is cached on T7; a non-interactive shell must export this or the
run dies loading `BAAI/bge-small-en-v1.5`:

```bash
export HF_HUB_CACHE=/media/terrabyte/T7/hf-cache HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export SEAM_BENCH_RECORD_DIR=/media/terrabyte/T7/Proprietary/DATA
```

## Step 1 (optional, ~$0.05): cheap cat3 preflight — isolates the naming clause

Reuses the champion's STORED cat3 contexts (no re-retrieval); compares hc/2 vs
hc/3. Green-light the full A/B if the naming misses flip Unknown/described →
named. Save this as `scratchpad/preflight_hc3_cat3.py` and run it:

```python
#!/usr/bin/env python
"""Cheap cat3 preflight for inference/high-confidence/3."""
import json
from benchmarks.external.common.answerer import build_answer_prompt
from benchmarks.external.locomo.adapters import seam as _seam
RECORD = "/media/terrabyte/T7/Proprietary/DATA/20260714-192938-locomo-holdout.json"  # #390
MODEL = "gpt-4o-mini"
def answer(p): return _seam._openai_short_answer(MODEL, p)
def main():
    rec = json.load(open(RECORD))
    cat3 = [c for c in rec["cases"] if c["arm"] == "candidate" and c.get("category") == "3"]
    print(f"cat3 cases: {len(cat3)}\n"); flips = 0
    for c in cat3:
        base = dict(conversation_adapter="conversation/2", temporal_policy="temporal/1")
        p2 = build_answer_prompt(c["question"], c["retrieved_context"], inference_policy="inference/high-confidence/2", **base)
        p3 = build_answer_prompt(c["question"], c["retrieved_context"], inference_policy="inference/high-confidence/3", **base)
        a2, a3 = answer(p2), answer(p3); changed = a2.strip() != a3.strip(); flips += changed
        print("="*70); print(f"Q: {c['question'][:95]}{'  <-- CHANGED' if changed else ''}")
        print(f"GOLD : {str(c['gold_answer'])[:80]}"); print(f"hc/2 : {a2[:110]}"); print(f"hc/3 : {a3[:110]}")
    print("="*70); print(f"\ncat3 changed by hc/3: {flips}/{len(cat3)} — check the CHANGED cases name the correct entity.")
if __name__ == "__main__": main()
```

Run: `OPENAI_API_KEY=... .venv/bin/python scratchpad/preflight_hc3_cat3.py`

## ❌ Step 1 RESULT (2026-07-18, operator-approved, ~$0.04): PREFLIGHT NEGATIVE — do not run Step 2

The 21-case stored-context preflight ran (gpt-4o-mini, hc/2 vs hc/3, same
contexts both arms). 14/21 answers changed, but **every change is paraphrase
noise — zero of the target naming cases converted**: John Williams still
"unknown", Voyageurs still unnamed, Exploding Kittens still a generic
description, Star Wars Ireland unchanged. The ambiguity guard held (no wrong
names licensed on the Mafia case), and byte-level prompt diffing confirmed the
hc/3 clause renders correctly — the lever is inert, not broken.

Root cause (verified against the source dataset, free): **this handoff's
premise was wrong — the identifying clues are not in the retrieved context**,
and for 3 of the 4 flagship cases they cannot be:

- John Williams: no "Star Wars + piano" turn exists; the chain needs the
  separate "definitely Star Wars! my favorite" turn (2 Jan 2024), which exists
  and retrieves for OTHER questions but has no lexical/semantic overlap with
  the composer question. Multi-hop retrieval gap.
- Voyageurs: the conversation only ever says "a beautiful national park";
  only "kayak" reached the context.
- Exploding Kittens: "played a game, I don't remember what it's called";
  only "cat" reached the context.
- Skellig/Ireland: clues WERE retrieved, but the gold is a 4-item location
  list and hc/3's single-entity license correctly refuses list-guessing.

**Decision: the ~$0.80 full A/B is cancelled.** The cat3 naming wall is
retrieval-side — the second-hop entity-preference turn must reach the context
(graph closure / entity-preference aggregation; note query decomposition was
already measured harmful). hc/3 stays built, default-off, tested-and-parked.

## Step 2 — CANCELLED, HISTORICAL, NON-EXECUTABLE

The proposed paid command and success criteria were removed from this live
handoff after the Step 1 preflight falsified the lever. Do not reconstruct or
run that experiment: `hc/3` is tested-and-parked, and HISTORY#419 supersedes
the original plan.

## Not this lever

cat1 → 91% on the mem0 harness is a SEPARATE track: native cat1 misses are mostly
incomplete-SET partials that the mem0 lenient judge already credits, so the mem0
headroom (+7 cases) is the genuinely-wrong multi-hop cases → a retrieval-side
lever (graph closure / decomposition), not this answer-side naming lever.

## Champions unchanged

#405 conv/4 stack 0.7762 (highest) / #390 conv/2 stack 0.7689 (cleaner base).
Advisor/Fable was unavailable this session; the analysis above was done directly.
