---
handoff_id: 2026-07-23-reasoning-verification-r3
supersedes: 2026-07-22-reasoned-retrieval-g3a
handoff_status: current
history: HISTORY#466
---

# Handoff: reasoning verification loops (R3)

**Date:** 2026-07-23
**Branch:** `agent/r3-verification-loops`
**Spend:** zero provider or paid model calls, installs, or downloads.

## One-line state

R3 is implemented as a bounded append-only verification ledger and atomic
verified-outcome path through `SeamSDK`; R1-R3 are now implemented, while
reasoning retrieval/reuse, reviewed promotion, and qualification remain R4-R6.

## What changed

- `seam_runtime/reasoning_graph.py` adds versioned
  `reasoning_verification` and `reasoning_outcome_verification` ledgers with
  update/delete guards, same-run/scope guards, and startup schema validation.
- A verification records controlled check kind and verdict, stable check
  reference, bounded public summary, optional exit code/duration, exact scoped
  knowledge/MIRL evidence references, agent attribution, and only the SHA-256
  plus UTF-8 length of supplied result text.
- `retry_of` is a same-run, same-subject, same-check linear chain. Failed and
  superseded attempts remain immutable; readers derive `superseded_by`.
- `finalize_verified` validates all checks before writing, accepts only current
  passed attempts from the same run, links checked subjects as support, records
  the exact verification IDs, and accepts the outcome in one transaction.
- Store wrappers and `ReasoningSession.verify`, `verification`,
  `verifications`, and `finalize_verified` expose the slice without making
  SQLite the integration contract. Existing R1 `finalize` remains compatible.

## Verification

- R1/R2/R3 focused contract: 45 passed;
- new R3 acceptance file: 7 passed, covering failed-to-passed retry,
  immutability, result redaction, stale/failed/cross-run/fork rejection,
  atomic rollback, evidence isolation, bounded iterables, and retry identity;
- touched-file Ruff, compileall, and `git diff --check`: pass;
- full non-external and monolithic compatibility results are recorded in
  HISTORY#466 and the draft PR.

## Guardrails

- Verification records public check provenance, not hidden reasoning, raw tool
  output, commands, credentials, provider payloads, or canonical truth.
- A passed check supports an outcome only at explicit verified finalization.
  There is no automatic MIRL promotion.
- Preserve the existing R1/R2 SDK behavior and keep future CLI, REST, MCP, and
  framework surfaces as thin adapters over `SeamSDK`.

## Next stages

1. Build R4 search/reuse of prior reasoning patterns with task/run, freshness,
   trust, and provenance gates that prevent conclusion laundering.
2. Build R5 reviewed and reversible promotion only behind explicit approval
   and exact evidence; never infer promotion from a passed verification.
3. Finish G3 independently with historical path/episode evidence, calibrated
   fusion, and scale/latency qualification before claiming graph maturity.
