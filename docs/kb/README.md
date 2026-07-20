# SEAM Retrieval Knowledgebase

A version-controlled, Leeroopedia-style knowledgebase for **improving SEAM's
retrieval and closing the gap to incumbent memory systems**. Every agent
working on SEAM (Claude, SOL, codex) should read the relevant page here before
proposing or building a retrieval/compile lever, and add to it after any
paid experiment.

It exists because the scarce inputs for improving SEAM are **not** raw coding
throughput. They are:

1. **Knowing how the competition actually architects ingest → store →
   retrieve** — so we build the right thing (e.g. the derived-facts direction
   came directly from understanding *why* mem0 wins).
2. **Knowing the ways memory benchmarks lie to you** — so we don't burn money
   confirming noise (see `eval-methodology/benchmark-traps.md`; several entries
   there each cost a real paid run to learn).
3. **Remembering what has already been tried and killed** — so we don't
   re-propose dead levers (`seam-internals/lever-graveyard.md`).

## Map

| Page | Use it when |
| --- | --- |
| `memory-systems/mem0.md` | Designing extraction/derived-facts; mem0 is the LoCoMo incumbent and the target to beat. |
| `memory-systems/zep-graphiti.md` | Working on temporal reasoning (cat2) or graph retrieval; Zep owns the temporal-graph design. |
| `memory-systems/langmem-letta-cognee.md` | Surveying memory-type taxonomies (semantic/episodic/procedural) and agent-managed memory. |
| `memory-systems/seam-positioning.md` | Deciding what to build/claim; where SEAM's real daylight is vs. table stakes. |
| `eval-methodology/benchmark-traps.md` | **Before any paid run.** The recurring ways LoCoMo/mem0-harness numbers mislead. |
| `eval-methodology/locomo-mem0-harness.md` | Running the mem0 harness or the facade; the contract, cutoffs, and gotchas. |
| `seam-internals/lever-graveyard.md` | Before proposing a lever. What's been tried, the measured result, and why. |
| `seam-internals/derived-facts-grounded-clm.md` | Working on `grounded-clm/1`; how it works and its next gate. |

## How to use it as an agent

- **Read before building.** Match your task to a page above; read it first.
- **Cite it in HISTORY.** When a lever choice is informed by a KB page, say so.
- **Update it after experiments.** A paid result — win or loss — must add or
  amend the relevant page in the same session. The graveyard and traps pages
  are only valuable if they stay current.

## Provenance / accuracy discipline

- Pages sourced from **SEAM's own runs** (traps, graveyard, derived-facts,
  positioning) are ground truth — they cite HISTORY entries and T7 artifacts.
- Pages describing **external systems** capture architecture *patterns* (stable)
  and are explicitly NOT a substitute for the vendor's current docs. Version-
  specific details drift; verify against primary docs before relying on a
  specific number or API (see `[[feedback-verify-docs-dont-guess-from-memory]]`).
- Knowledge cutoff for external-system pages: as written, 2026-07. Re-verify
  before quoting specifics.
