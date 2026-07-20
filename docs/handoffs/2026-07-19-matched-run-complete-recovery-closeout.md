---
handoff_id: 2026-07-19-matched-run-complete-recovery-closeout
supersedes: 2026-07-19-matched-run-inflight-and-cat2-lever-handoff
handoff_status: current
history: HISTORY#430
---

# Handoff: matched run complete, cut-off work recovered

- **Date:** 2026-07-19
- **Branch:** `agent/roadmap-zep-after-benchmarks`
- **Draft PR:** #153
- **Spend state:** no paid work is authorized by this handoff.

## Durable result

HISTORY#429 completed the matched-answerer cat1+cat3 run. The 95% projection
was falsified: SEAM scored 248/282 (87.94%) on cat1 and 67/96 (69.79%) on
cat3 under the matched gpt-4o answerer/judge contract. SEAM did not top Mem0
on either category. Do not revive the earlier in-flight instructions or run
another paid benchmark from this handoff.

## Recovered and verified scope

HISTORY#419 through #429 were already committed and pushed before the
cut-off. Recovery repaired only objective incompleteness in that attributable
slice:

- future `when will` questions no longer activate the past-event
  `temporal-instance/1` projection;
- `cost_report` rejects malformed evaluation payloads and does not fabricate
  a partial aggregate when a model is unpriced;
- the answerer-parity probe ignores invalid score rows, enforces the audited
  `memory-benchmarks` revision, and records its full revision;
- the cancelled `hc/3` paid command is removed from the live historical
  handoff;
- this handoff supersedes the stale tracked state that still said the matched
  run was in flight.

No benchmark or provider call was made during recovery.

## Explicit exclusion

The following pre-existing dirty files are the operator-rejected
`event-count/distinct/2` experiment. They are preserved locally for separate
inspection and are not part of PR #153:

- `seam_runtime/event_count_context.py`
- `seam_runtime/retrieval.py`
- `benchmarks/external/mem0_harness/preflight_event_count_context.py`
- `benchmarks/external/mem0_harness/README.md`
- `tests/audit/test_event_count_context.py`
- `tests/audit/test_event_count_preflight.py`
- `tests/audit/test_retrieval_flags.py`
- `tests/audit/test_seam_mem0_server.py`

Do not stage or ship those files without a new, explicit operator decision.

## Next decision

Keep paid work stopped. If product work resumes, choose a general
retrieval-side design against the mapped second-hop/naming and set-recall
misses, independently of the rejected benchmark-shaped count experiment,
then validate free and held-out evidence before any operator-gated spend.
