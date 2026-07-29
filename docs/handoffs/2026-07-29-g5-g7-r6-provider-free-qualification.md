---
handoff_id: 2026-07-29-g5-g7-r6-provider-free-qualification
supersedes: 2026-07-29-g4-r5-graph-products-reviewed-promotion
handoff_status: current
history: HISTORY#496
---

# Handoff: G5-G7 and R6 complete through the paid boundary

**Date:** 2026-07-29
**Branch:** `feat/g5-g7-r6-qualification`
**Base:** `origin/main` at `6225937aad95414cef92fd86d07af6c78831b8ec`
**Scope:** G5 context, G6 lifecycle/scale, R6 qualification, and provider-free G7

## One-line state

G5, G6, and R6 satisfy their provider-free structural contracts; G7's real
native/event-only qualification completed with an honest matched-budget parity
result, while matched Mem0/Zep scoring is frozen and intentionally stopped
before provider-paid execution.

## Completed contracts

- G5 `context-assembly/1` combines canonical facts, entities, episodes, and G4
  products with exact record/episode/product backtraces, trust/time/boundary
  gates, deterministic token accounting, and reserved grounded-fact capacity.
- G6 `lifecycle/2` provides immutable operation/event audit, exact scoped soft
  deletion, exact tenant authorization, deleted-record exclusion before
  retrieval graph seeding and stale G4/G5 context, configured external-vector
  cleanup through a recoverable `cleanup_pending` outbox, idempotent batch
  ingest, item checkpoints, reopen recovery, and concurrent idempotent planning
  through Store, Runtime, and SDK. Resumable batch text lives only in a
  tenant-authorized transient table, is digest-bound to the immutable audit,
  and is purged on successful completion.
- R6 `seam-qualification-adapter/1` fixes cross-agent boundary envelopes and
  deterministic retry/concurrency evidence.
- G7 `seam-graph-reasoning-manifest/1` keeps native SEAM, event-only, matched
  Mem0, and matched Zep separate. External lanes cannot contain measurements,
  provider calls, or publication claims before execution.
- Direct LoCoMo comparator, answerer, or real-judge runs now fail closed unless
  `--allow-paid` is explicit; dry-run and stub-only paths remain provider-free.

## Provider-free evidence

- `python -m benchmarks.graph_reasoning_qualification` ran three isolated
  tenants through real ingest, G4 rebuild, G5 assembly, event-only retrieval,
  concurrent context reads, and interrupted-read recovery.
- Native and event-only usefulness were both `1.0` under the same 2,000-token
  context budget and two-record result cap; graph-incremental evidence hits
  were zero. The run therefore establishes parity, not incremental graph value.
- Three concurrent requests completed, one interrupted request recovered, none
  failed, and provider call count was zero.
- Strict live-pgvector full suite: 2,061 collected; 2,059 passed; two established
  `compile_nl` xfailed; zero skipped and zero failed.

## Paid boundary

Do not run either command without explicit spend approval and the required
credentials/service state:

```bash
.venv/bin/python -m benchmarks.external.locomo.run \
  --dataset-path <locomo-dataset-path> \
  --adapter mem0 --answerer openai --judge openai --allow-paid

.venv/bin/python -m benchmarks.external.locomo.run \
  --dataset-path <locomo-dataset-path> \
  --adapter zep --answerer openai --judge openai --allow-paid
```

Mem0 requires provider-backed extraction plus the matched shared answerer and
judge. Zep additionally requires live-service credentials and completion of
its asynchronous graph processing. Until those lanes run, their score fields
must remain null and no competitive comparison may be published.

## Preserved boundaries

- RAW/MIRL remains canonical; context, lifecycle indexes, graph products, and
  qualification reports are derived/audit planes.
- Reasoning remains non-canonical except through the explicit R5 review/apply
  path.
- Public `seam-client` and opaque `/v1` boundaries are unchanged.
- No provider call, paid benchmark, package publication, deployment, or
  DigitalOcean mutation occurred.
- Unrelated `.ua/`, `dist/`, report images, and `seam_runtime/.ua/` remain
  untouched.

## Next

Push the branch, open a protected PR, resolve review/CI, and merge only when all
relevant checks are green. After explicit paid approval, run the two matched
lanes against the frozen manifest and keep their scoreboards separate.
