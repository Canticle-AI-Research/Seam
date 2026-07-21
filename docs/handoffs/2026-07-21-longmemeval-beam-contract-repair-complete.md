---
handoff_id: 2026-07-21-longmemeval-beam-contract-repair-complete
supersedes: 2026-07-20-longmemeval-beam-contract-repair-in-progress
handoff_status: superseded
history: HISTORY#441
---

# Handoff: LongMemEval/BEAM execution-contract repair complete

- **Date:** 2026-07-21
- **Branch:** `agent/roadmap-zep-after-benchmarks`
- **Pushed:** NO
- **Spend/download/install/BEAM-10M:** NONE

## Completed

SEAM's local LongMemEval and BEAM parsers are strict structural validators.
Real and predict-only competitive execution routes through the pinned clean
`mem0ai/memory-benchmarks` revision using its isolated Python and SEAM's
loopback Mem0 facade. The route fails closed on revision drift, dirty harness
state, non-loopback hosts, missing dependencies or data, implicit BEAM cache
downloads, provider spend without approval, and BEAM-10M without its separate
approval.

LongMemEval question date, abstention, evidence-session metadata, and source
history are preserved. BEAM chat, rubric/nugget, batch-dict, and plan encodings
are validated without constructing empty-conversation cases. Documentation now
uses the official BEAM track sizes and task-specific score contracts.

## Verification

- 51 touched tests collected and 51 focused tests passed.
- 1,627 strict non-external tests passed, two established xfails, zero skips.
- 10 external pgvector tests passed, zero skips.
- Touched Ruff and module compilation passed.
- Diff and candidate secret/private-session-link scans passed.
- No dependency install, dataset/model download, provider or paid call,
  benchmark score, BEAM-10M execution, or push occurred.

## Honest boundaries and next direction

RAW evidence preserves second-level LongMemEval/BEAM timestamps, but ordinary
turn ingest does not yet reliably populate MIRL event-time `t0`/`t1` or event
lifecycle; ingestion time is not event time. LongMemEval `question_date` does
not yet shape facade retrieval, and timestamp parsing remains narrower than the
real corpus variants.

Graph memory is the next measured competitive direction, not a completed win.
SEAM has the canonical MIRL-to-graph projector and graph retrieval substrate;
the next step is a free matched-harness evidence-presence and displacement
measurement before any score claim or paid gate.

Operator-owned `report*.png` files remain untracked, untouched, and excluded.
