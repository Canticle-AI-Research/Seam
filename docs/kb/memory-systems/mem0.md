# mem0 — the LoCoMo incumbent and target to beat

> Architecture patterns as understood at 2026-07 (knowledge cutoff). Verify
> specifics against mem0's current docs / `mem0ai/memory-benchmarks` before
> relying on a number. This page is about *why mem0 wins on LoCoMo*, which is
> the load-bearing insight for SEAM's derived-facts work.

## The core design: LLM extraction at ingest

mem0's defining choice is that **memory is distilled by an LLM at write time**,
not stored raw:

1. **Add (`POST /memories`):** an LLM reads the incoming turn(s) and extracts
   salient, self-contained **facts / memories** as short natural-language
   statements ("John likes surfing", "User is allergic to peanuts").
2. **Reconcile:** a second LLM step compares each extracted fact against existing
   memories and decides **ADD / UPDATE / DELETE / NOOP** — deduping and keeping
   memory current instead of append-only.
3. **Store:** the distilled fact strings go into a vector store (embedded), often
   with metadata; a graph variant (**mem0g**) additionally stores entity/relation
   edges.
4. **Search (`POST /search`):** embed the query, return top-k distilled facts.

## Why this beats raw-turn retrieval on LoCoMo

The stored unit is a **distilled fact that lexically and semantically resembles
the question**. Ask "what sports does John like?" and the stored memory is
literally "John likes surfing" — a near-neighbor in embedding space. A raw-turn
store, by contrast, holds "Wow! How long have you been surfing?" which is *far*
from the question. This is the **query↔evidence wording-distance** advantage, and
it is exactly the wall SEAM hit in HISTORY#432.

## Costs / tradeoffs (SEAM's opening)

- **Ingest is expensive and lossy.** Every turn pays 1–2 LLM calls; the raw
  wording and anything the extractor drops are gone. Extraction errors are
  silent and unauditable.
- **No provenance by default.** A distilled fact is not linked back to the exact
  source span; you cannot cheaply prove *why* a memory exists.
- **Update logic is a correctness surface.** ADD/UPDATE/DELETE decisions can
  wrongly overwrite or drop.

SEAM's `grounded-clm/1` (`../seam-internals/derived-facts-grounded-clm.md`)
adopts the *winning* property (distilled facts that match queries) while keeping
losslessness + provenance + fail-closed-when-uncertain — the auditable version.

## Benchmark posture (see `../eval-methodology/`)

- mem0 publishes LoCoMo numbers using **their own answerer + judge** (gpt-4o
  family in the harness defaults; their headline table historically gpt-4o). The
  judge is **lenient** (partial credit, paraphrase, extra detail, ±14-day dates).
- Published LoCoMo (their harness, top-200): single-hop ~91.2, multi-hop ~91.3,
  open-domain ~72.7, temporal ~92.0 (averages across cutoffs; verify current).
- To claim "SEAM beats mem0," hold answerer + judge + dataset + cutoff constant
  and run SEAM through their unmodified harness via the facade
  (`../eval-methodology/locomo-mem0-harness.md`).

## Current matched standing (HISTORY#429)

Under the matched gpt-4o answerer+judge, SEAM is behind on all four categories
(cat1 87.94 / cat3 69.79 measured; cat4 87.16 / cat2 71.96 on the mini lane).
The derived-facts lever is the bet to close cat1/cat3; open-domain (cat3) and
counts overlap with mem0's own weak spots.
