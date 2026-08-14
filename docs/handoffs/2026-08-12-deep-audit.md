---
handoff_id: 2026-08-12-deep-audit
supersedes: 2026-08-05-tui-rebuild-canticle
handoff_status: current
history: HISTORY#560
---

# Whole-repository deep audit + complete project timeline

## State

Two durable artifacts landed in `docs/audits/`:

- `2026-08-12-full-repo-audit.md` — whole-repo audit (HISTORY#560): 0
  CRITICAL, 1 HIGH (docs-only, repaired in this entry), 15 MEDIUM, ~33 LOW.
  All four critical/high reproducers from the prior audits are verified fixed
  in code. Full suite: 2382 passed / 0 skipped / 2 xfailed.
- `2026-08-12-seam-complete-timeline.md` — complete project timeline, 559
  entries across 7 eras, verified row-by-row against `HISTORY.md`.

Documentation drift repaired in the same entry: the PROJECT_STATUS.md
headline and open-item bullets (suite count, /v1 tenancy decision, IN
expansion sites, never-audited list), `docs/status/operations.md`, the
campaign doc's latest-evidence and publication boundary, and the audit and
handoff registries.

## Key open items

- MEDIUM runtime cluster, in the audit's resolution order: chat response
  buffering (F-5), REST /persist caller-supplied ids (F-6), applied-policy
  divergence across surfaces (F-7), process-lifetime flag cache (F-8),
  unbounded SQL IN expansion (F-9), outbox soft-delete replay (F-10), plus
  the graph/trust/pattern-flag findings.
- The audit's §8 next step is one PR fixing F-5 and F-6.

## Next stage

S6 — principal tenancy and opaque deletion. Termination decision recorded:
in-process with an optional principal (2026-08-05, HISTORY#538).
