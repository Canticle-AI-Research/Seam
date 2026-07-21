---
handoff_id: 2026-07-21-multiscope-gate-and-local-beam-in-progress
supersedes: 2026-07-21-canonical-graph-fill-broad-profile-correction
handoff_status: superseded
history: HISTORY#445
---

# Handoff: multi-scope free gate passed; local BEAM ingestion next

- **Date:** 2026-07-21
- **Branch:** `agent/roadmap-zep-after-benchmarks`
- **Pushed:** NO
- **Provider/paid calls:** NONE
- **Detailed recovery:**
  `.context-handoffs/context-handoff-20260721T194544Z.md`

## In-progress implementation

The default-off `reserved-multi-scope/1` candidate is implemented in dirty
local files. It folds the final retained RAW row and bounded grounded-fact,
entity/relation, date-diverse temporal, and deeper RAW items into one directly
readable context PACK row. Exact RAW bodies remain verbatim inside the PACK,
so adding protected lane content does not discard the displaced baseline tail.

Full provider-free LoCoMo cat1/cat3 evidence gate under the corrected matched
profile (retrieval 300 / context 60,000 / response top-200) passed across 378
questions: baseline 353 any / 252 complete / 887 exact references; candidate
354 / 257 / 897. The candidate gained 10 exact references and lost zero. It
emitted 377 PACK rows with a maximum 5,259 characters. This is evidence
presence only, not an answer-score or benchmark-win claim.

Focused collect-only found 36 tests; the focused suite passed 36/36. Touched
Ruff, compileall, and diff checks passed. Full-suite, external-pgvector,
documentation, and final promotion work remain undone.

## New operator request and local corpus

The operator placed benchmark checkouts under `/home/terrabyte/BEAM` and asked
SEAM to use them for improvement. Read-only inventory found one complete
released corpus: `/home/terrabyte/BEAM/BEAM` contains all 100 conversations and
2,000 questions. Its supported 1M tier is exactly 35 conversations / 700
questions / ten types; the 10M tier is 10/200 and remains separately gated.
LongMemEval, LongMemEval-V2, and PersonaMem-v2 are code checkouts without their
released datasets. Needle-in-a-haystack contains synthetic test assets.

SEAM's current BEAM directory scanner cannot parse the official nested local
layout (`chats/<scale>/<id>/chat.json` plus nested probing questions), even
though the existing JSON-row parser already understands the chat and rubric
shapes. This is the next implementation target.

## Resume exactly here

1. Inspect the dirty diff and the detailed context handoff; keep the five
   operator-owned untracked `report*.png` files excluded.
2. Teach `benchmarks/external/beam/run.py` to validate/load the official local
   BEAM repository layout without copying dataset content into SEAM.
3. Add hermetic tests and dry-run the real local 1M path, requiring 35
   conversations, 700 questions, all ten categories, nonempty chats, and rubric
   nuggets.
4. Plan a local cache/export route for the pinned upstream predict-only harness
   without installs, downloads, provider calls, or 10M execution.
5. Finish full verification and only then decide whether the multi-scope lever
   merits an operator-gated paid microgate.
