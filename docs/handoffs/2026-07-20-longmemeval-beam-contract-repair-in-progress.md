---
handoff_id: 2026-07-20-longmemeval-beam-contract-repair-in-progress
supersedes: 2026-07-20-sentence-grounded-pass-and-competitor-ratchet
handoff_status: superseded
history: HISTORY#440
---

# Handoff: LongMemEval/BEAM execution-contract repair in progress

- **Date:** 2026-07-20
- **Branch:** `agent/roadmap-zep-after-benchmarks`
- **Head before WIP:** `5fb1562` (one local commit ahead of remote)
- **Pushed:** NO
- **Spend/download/install:** NONE
- **Detailed context handoff:**
  `.context-handoffs/context-handoff-20260721T033701Z.md`

## State

The audit found that SEAM's local LongMemEval and BEAM paths were safe as shape
validators but not faithful competitive runners. Both nominal real-run paths
used the generic LoCoMo scorer; LongMemEval dropped question-date/abstention
metadata, and BEAM's directory loader could build questions against an empty
conversation. BEAM documentation also confused the complete 100/2,000 release
with the 1M track's 35/700 contract.

The dirty WIP replaces scored execution with a revision-pinned bridge to the
unmodified `mem0ai/memory-benchmarks` LongMemEval/BEAM runners through SEAM's
existing loopback HTTP facade. Local parsers now fail closed and are structural
validators only. The bridge gates harness revision, isolated Python, loopback
URL, missing BEAM dependency, provider spend, and BEAM-10M.

## Verified so far

- Touched-code Ruff: clean.
- Touched modules compile.
- Focused LongMemEval/BEAM/upstream-bridge suite: 23 passed.
- `/tmp/memory-benchmarks` exists at the exact audited commit `4b61c5d`.
- No LongMemEval/BEAM data found; upstream BEAM venv lacks `datasets`.
- No full suite, pgvector suite, real readiness execution, install, download,
  provider call, benchmark score, commit, or push yet.

## Resume first

1. Read the detailed `.context-handoffs` file and inspect the live diff.
2. Preserve operator-owned untracked `report*.png` files.
3. Finish plan-only readiness checks; do not install/download without operator
   approval.
4. Review CLI forwarding and the sub-day timestamp question documented in the
   detailed handoff.
5. Run focused, collect-only, full non-external, and configured external
   pgvector verification.
6. Replace this in-progress handoff with a done handoff, complete HISTORY and
   stream/snapshot verification, and commit locally. Do not push without the
   operator.

The detailed defect ledger is
`docs/audits/2026-07-20-longmemeval-beam-execution-contract.md`.
