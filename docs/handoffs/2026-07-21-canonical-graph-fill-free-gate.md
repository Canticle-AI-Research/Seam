---
handoff_id: 2026-07-21-canonical-graph-fill-free-gate
supersedes: 2026-07-21-longmemeval-beam-contract-repair-complete
handoff_status: current
history: HISTORY#443
---

# Handoff: canonical graph fill passes the free evidence gate

- **Date:** 2026-07-21
- **Branch:** `agent/roadmap-zep-after-benchmarks`
- **Pushed:** NO
- **Provider/paid calls:** NONE

## Completed

Generated fresh matched LoCoMo stores through the pinned upstream harness in
predict-only mode, rejected older incomplete stores, and measured SEAM's
canonical `knowledge_edges` retriever over all 378 cat1/cat3 questions.

The default-off `canonical-graph-fill/1` facade policy fills only unused
top-200 rows with unique graph-reached RAW provenance. It gained five exact
gold evidence references, made one case newly complete, and displaced zero
gold references. The free gate passed. The more aggressive reserved-tail
candidate gained five but lost one exact reference, so it failed and was not
promoted.

Graph score ties are now deterministic by record id. The reusable preflight
copies and validates stores before graph backfill, rejects remote retrieval
configuration, and emits no licensed text.

Full contract and aggregate counts:
`docs/audits/2026-07-21-canonical-graph-fill-preflight.md`.

## Boundaries

This is evidence presence, not an answer score or graph-memory benchmark win.
The policy remains off by default. No provider call, paid judge, package
install, model/dataset download, full scored rerun, push, or production-policy
promotion occurred.

Temporary matched stores and upstream output remain outside the repo under
`/tmp`; they are not durable evidence and were not committed. Operator-owned
`report*.png` files remain untracked, untouched, and excluded.

## Next step

Ask the operator whether to authorize a small same-day paired paid microgate
under the frozen matched `gpt-4o` answerer/judge contract. If approved, use one
fresh ingest for matched baseline/candidate arms, enable graph fill only on the
candidate, preserve sentinels, and stop before a full paid run unless the score
gate passes.
