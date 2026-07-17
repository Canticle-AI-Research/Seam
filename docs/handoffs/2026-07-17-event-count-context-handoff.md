---
handoff_id: 2026-07-17-event-count-context-handoff
supersedes: 2026-07-17-hc3-open-domain-cat3-handoff
handoff_status: current
history: HISTORY#416
---

# Handoff: validate event-count/distinct/1 on the Mem0 cat1 lane

- **Date:** 2026-07-17
- **Branch:** `agent/roadmap-zep-after-benchmarks`
- **State:** built and structurally validated; not score-validated
- **Paid work:** none in this slice; the operator gates every provider call

## Why this is the next cat1 probe

The private Mem0-harness artifact from HISTORY#400 remains at 250/282 cat1
correct (88.65%), so more than 91% requires at least seven additional correct
cases. A free offline audit of its 32 misses found:

- 22 already have all gold evidence in the top-200 retrieval, 8 are partial,
  and 2 have none.
- 14 misses are count questions; 12 of those 14 contain all required evidence.

This points to a narrow context-assembly problem for repeated events/items, not
another broad retrieval rewrite. The native judge/1 and Mem0-harness
scoreboards remain separate co-primary evidence lanes.

## What was built

`event-count/distinct/1` is a default-off `RetrievalFlags.count_context_policy`
option. For count questions only, it constructs a bounded `SEAM-COUNT/1`
projection from retained RAW memories, classifies clauses as observed, mixed,
mentioned, reference-only, planned, or negated, ranks query-relevant observed
evidence first, and tells the answerer to count distinct occurrences/items
without double-counting repeated descriptions.

The projection is JSON-escaped, retains RAW provenance, discloses truncation,
and never cites a RAW memory omitted from the response capacity. Flag-off and
non-count behavior remain unchanged.

The Mem0 facade reads the flag through the normal runtime environment:

```bash
export SEAM_COUNT_CONTEXT_POLICY=event-count/distinct/1
```

## Mandatory local environment

The BGE embedder is cached on T7. These exports are mandatory before facade or
benchmark runs:

```bash
export HF_HUB_CACHE=/media/terrabyte/T7/hf-cache
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export SEAM_BENCH_RECORD_DIR=/media/terrabyte/T7/Proprietary/DATA
```

One focused invocation without these exports reproduced the known offline
embedder-load failure at zero provider calls. The exact 50-test slice passed
after rerunning with the required environment; the full non-external suite also
passed with two established xfails.

## Free structural preflight

This reads a private stored record, emits aggregate counts only, makes no
provider calls, and does not score answers:

```bash
.venv/bin/python -m benchmarks.external.mem0_harness.preflight_event_count_context \
  /media/terrabyte/T7/Proprietary/DATA/20260715-091018-mem0-harness-cat13.json \
  --summary-only
```

Observed aggregate result:

```text
selected_failed_cat1_count_cases: 14
projected_cases: 14
raw_candidates_preserved_in_projection: 2560
observed_rows_promoted: 96
non_qualifying_rows_demoted: 79
provider_calls: 0
```

This proves the structural lever fires on the intended misses; it is not a
quality claim.

## Next decision

Run an operator-approved, answerer-only stored-context microgate on the 14
selected failures. Green-light a matched full Mem0-harness validation only if
at least seven previously incorrect cat1 answers flip without regressions.
Report cat1 and cat3 separately and do not relabel this as movement on the
native judge/1 scoreboard.

The prior `inference/high-confidence/3` cat3 naming lever remains built,
default-off, and unvalidated. Its preserved runbook is
`docs/handoffs/2026-07-17-hc3-open-domain-cat3-handoff.md`; do not conflate or
drop that independent experiment.
