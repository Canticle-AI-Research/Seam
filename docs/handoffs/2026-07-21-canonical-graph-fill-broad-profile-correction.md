---
handoff_id: 2026-07-21-canonical-graph-fill-broad-profile-correction
supersedes: 2026-07-21-canonical-graph-fill-free-gate
handoff_status: current
history: HISTORY#444
---

# Handoff: broad-profile correction cancels the graph paid gate

- **Date:** 2026-07-21
- **Branch:** `agent/roadmap-zep-after-benchmarks`
- **Pushed:** NO
- **Provider/paid calls:** NONE

## Correction

The operator authorized the paired `gpt-4o` graph-fill microgate. Its mandatory
provider-free dry run stopped before client initialization because live
baseline retrieval did not match the fresh predict-only checkpoint.

The root cause was in the free preflight: it forced search depth 200 and context
budget 8,000 instead of the frozen capable-answerer `broad` profile used by the
matched run (300 / 60,000, with the facade response truncated to top-200).
That compact baseline produced the apparent +5 exact-reference gain recorded in
HISTORY#442/#443.

After pinning the correct broad profile, live selected-case retrieval matched
the fresh checkpoint exactly. A repeated provider-free audit over all 378
cat1/cat3 questions measured:

- baseline: 353 any-evidence cases, 252 complete cases, 887 exact hits;
- fill-only: the same 353 / 252 / 887;
- graph fill added 32 unique rows, gained zero exact references, and lost zero;
- the declared free gate failed because it required at least one gain.

The earlier +5 matched-harness claim is retracted. The graph policy stays
default-off, and the paid microgate was canceled with zero provider calls and
zero spend. The guarded paired runner requires explicit gain ids from a newly
passing broad-profile preflight, so the retracted ids cannot authorize spend.

## Next step

Do not run a graph-fill paid gate or full benchmark from this handoff. Return to
a free architectural lever; reserved multi-scope packing remains the next rung
identified in HISTORY#439 unless the operator chooses another direction.

Temporary stores and predicted outputs remain outside the repo under `/tmp`.
Operator-owned `report*.png` files remain untracked, untouched, and excluded.
