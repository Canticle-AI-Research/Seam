---
handoff_id: 2026-07-20-second-hop-negative-and-count-lever-conflict
supersedes: 2026-07-19-matched-run-complete-recovery-closeout
handoff_status: superseded
history: HISTORY#432
---

# Handoff: second-hop lever killed at free gate; count-lever status CONFLICTS between chains

- **Date:** 2026-07-20
- **Branch:** `agent/roadmap-zep-after-benchmarks` (PR #153, draft)
- **Pushed:** `9903a1d` (HISTORY#432) is on `origin`.
- **Spend state:** no paid work authorized by this handoff.

## Unresolved conflict — read before touching event-count/distinct/2

Two chains disagree about the same uncommitted files
(`seam_runtime/event_count_context.py`, `seam_runtime/retrieval.py`,
`benchmarks/external/mem0_harness/preflight_event_count_context.py`, and
their four test files):

- **This chain (HISTORY#429, #432)** treated SOL's in-flight
  `event-count/distinct/2` (same-event grouping for count questions) as the
  **highest-EV queued lever** — the #429 miss autopsy found 14 of 63 matched
  misses are count errors (12 in cat1), the single biggest bucket, and both
  entries recommended microgating it the moment it lands.
- **HISTORY#430's handoff** (`2026-07-19-matched-run-complete-recovery-closeout`,
  written by a concurrent agent, now superseded by this one) calls the same
  work **"the operator-rejected `event-count/distinct/2` experiment"** and
  says explicitly: *"Do not stage or ship those files without a new,
  explicit operator decision."*

**I have no record of an operator rejection in this session.** I did not
reject it, and nothing in the conversation history available to me shows the
operator doing so either. This may be a real decision made outside this
thread, a miscommunication between concurrent agents, or a stale label
carried over from an earlier, different microgate (HISTORY#417's
`event-count/distinct/1`, which DID fail its flip gate 6/14 — that one is a
legitimate graveyard entry, and may be what #430 is actually referring to,
conflated with v2).

**Do not act on either framing without asking the operator which is true.**
The eight files remain uncommitted, untouched, and excluded from PR #153
either way — that part both chains agree on.

## What happened this session (HISTORY#431–#432)

1. Built `seam_runtime/second_hop_context.py` (`entity-bridge/1`): mines
   entity/title terms from primary retrieval results, runs up to 3 secondary
   searches, splices novel hits into a reserved tail (40/200 slots, scored
   below the primary floor). Facade-gated via `SEAM_SECOND_HOP_POLICY`,
   default off. 8 hermetic tests, full suite green. Committed at `63234ec`.
2. **Free preflight (zero spend) KILLED it**, per the always-test-before-build
   rule: rerunning the 48 matched misses with textual golds against the
   preserved `seam-cat13-matched` scratch store, off vs on, showed **0
   gained, 1 lost** to tail displacement. The design cannot work on these
   misses by construction — you cannot bridge from evidence you never
   retrieved in the first place. A follow-up query-reformulation probe
   confirmed 0/40 reachable. Committed at `9903a1d`.
3. **Root cause identified and verified directly** (after correcting an
   initial bad blanket-scan claim that evidence was missing from the store —
   it is not; targeted SQL and a direct query proved it): the wall is
   **query↔evidence wording distance** at embedding search. Example:
   querying `"surfing"` against the preserved store returns the gold turn at
   rank 1; the natural question ("what sports does John like besides
   basketball?") returns 40 sports turns and never that one, because SEAM
   serves raw conversational turns, not distilled facts.
4. **Strategic read (not yet scoped or built):** this is very likely part of
   why mem0's own extraction-at-ingest pipeline scores higher here — it
   stores distilled facts that lexically resemble questions. The on-goal
   SEAM answer is serving derived MIRL fact records (ENT/CLM-class, the
   compile layer) alongside retained RAW within the existing 200-slot
   budget — core product work, not a benchmark-only trick, and large enough
   headroom to avoid the RAW-displacement trap (#369 lesson). This needs a
   deliberate scoping pass, not a same-session build.
5. `entity-bridge/1` code stays in the tree, default-off, harmless — it is
   not wired into anything and costs nothing to leave.

## Standing miss map (HISTORY#429, unchanged)

Matched-conditions final: cat1 87.94% (248/282, mem0 91.3, gap −3.4), cat3
69.79% (67/96, mem0 72.7, gap −2.9). 63 misses, only 8 had gold text in
top-200. Bucket sizes: counts 14 (12 cat1), evidence-absent abstentions ~16,
open-domain naming ~13, wrong-instance ~6, incomplete sets ~7.

## Next decision (operator)

1. **Resolve the count-lever conflict above** — is `event-count/distinct/2`
   rejected or queued? This gates whether the 14-case count bucket (the
   single biggest lever target) is available at all.
2. If pursuing the derived-facts direction: scope it before building —
   which MIRL record kinds already exist and could serve as-is vs need new
   compile-time extraction, and how it composes with the existing
   count/temporal/second-hop facade projections (only one may fire per
   query today; that constraint may need revisiting).
3. cat4+cat2 parity probe (~$6) remains queued and operator-gated,
   independent of the above.

## Cost measurement (HISTORY#428)

`benchmarks.external.common.cost_report` now gives tokenizer-true (o200k
for the gpt-4o/4.1/5 families) single-pass cost from any stored mem0-harness
artifact — treat its output as a LOWER BOUND (invisible retry/rerun passes
bill on top) and reconcile against the provider dashboard for true spend.
