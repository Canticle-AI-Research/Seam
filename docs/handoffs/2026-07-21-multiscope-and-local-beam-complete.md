---
handoff_id: 2026-07-21-multiscope-and-local-beam-complete
supersedes: 2026-07-21-multiscope-gate-and-local-beam-in-progress
handoff_status: current
history: HISTORY#446
---

# Handoff: multi-scope free gate and local BEAM ingestion complete

- **Date:** 2026-07-21
- **Branch:** `agent/roadmap-zep-after-benchmarks`
- **Publication:** PR #153; operator requested push and merge
- **Provider/paid calls:** NONE

## Completed scope

The default-off `reserved-multi-scope/1` candidate composes the retained RAW
tail with bounded grounded-fact, entity/relation, date-diverse temporal, and
deeper RAW content in one directly readable PACK row. Its corrected-profile
provider-free LoCoMo cat1/cat3 evidence gate covered all 378 questions:
baseline 353 any / 252 complete / 887 exact references; candidate 354 / 257 /
897. It gained ten exact references, lost zero, made five questions newly
complete and one newly evidenced, and produced a maximum 5,259-character PACK.
This is evidence-presence validation, not an answer-score win or a promotion.

SEAM now discovers and fully validates the official local BEAM repository,
`chats/` root, or scale root without copying corpus data. The validator parses
every chat and probing question, requires nonempty conversations and rubric
nuggets, checks all ten official categories and exact track totals, and hashes
each source chat/question file once using root-independent relative paths.
Unknown legacy directory layouts remain structural-only and invalid; scored
or predict-only execution remains delegated to the pinned upstream
task-specific harness.

The real local BEAM-1M checkout at `/home/terrabyte/BEAM/BEAM` passed dry-run:
35 conversations, 700 questions, 74,630 normalized turns, 70 questions per
category, 70 source files, and fixture hash
`74fdc646e27b1c380368f66cd6360ccf94e39bb5cc3627a14d58f32b3d692bef`.
No dependency install, dataset download, provider call, or BEAM-10M execution
occurred.

## Verification

- Affected collect-only: 61 tests across multi-scope, facade, BEAM routing,
  and upstream harness contracts.
- Affected execution: 61/61 passed.
- Strict non-external suite: 1,417 collected; 1,415 passed and two established
  xfailed, with zero skips.
- Live external pgvector slice: 6/6 passed with zero skips.
- Touched-file Ruff and `git diff --check`: clean.

## Next boundary

`reserved-multi-scope/1` stays default-off. Any paid answerer microgate or
promotion remains a separate operator decision. The clean local
Needle-in-a-Haystack checkout is the next provider-free adapter target; preserve
its native single, multi, UUID, and UUID-chain sweep/scoring contracts and do
not present its fake provider as SEAM evidence. LongMemEval, LongMemEval-V2,
and PersonaMem-v2 still require their separately released datasets. BEAM-10M,
downloads, installs, and provider-paid execution remain explicitly gated.
