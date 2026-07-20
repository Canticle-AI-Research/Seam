# LangMem · Letta/MemGPT · cognee — memory taxonomies & agent-managed memory

> Architecture patterns as understood at 2026-07. Verify specifics against each
> project's current docs. These are less direct LoCoMo competitors than
> mem0/Zep but define the vocabulary and the agent-managed-memory design space.

## LangMem (LangChain)

- **Memory-type taxonomy:** distinguishes **semantic** (facts/profiles),
  **episodic** (past events/interactions), and **procedural** (how-to / learned
  behavior) memory. Useful shared vocabulary when arguing about what a lever
  stores.
- **Mechanism:** memory tools an agent calls to store/search, plus a background
  **memory manager** that consolidates and updates memories out of the hot path.
- **Relevance to SEAM:** the semantic/episodic/procedural split is a clean way to
  reason about what `grounded-clm/1` produces (semantic facts) vs. what raw turns
  are (episodic). Consolidation-in-background is a pattern for the self-improve
  loop, not the benchmark lever.

## Letta / MemGPT

- **Core idea:** an **OS-inspired memory hierarchy** — a small in-context "core
  memory" (always in the prompt) + large "external" memory (archival + recall)
  that the agent **pages in/out via tool calls**. The agent edits its own memory.
- **Self-editing memory:** the model decides what to promote to core memory and
  what to archive, using function calls (memory as a set of tools).
- **Relevance to SEAM:** this is the **agent-managed-memory** design — closest to
  the "SEAM deep agent" idea. It's a *product/runtime* pattern (Track P), not a
  retrieval lever. Its lesson for benchmarks: giving the model memory tools does
  not by itself fix retrieval recall; the store still has to hold matchable
  units.

## cognee

- **ECL pipeline (Extract → Cognify → Load):** extracts structured data, builds a
  knowledge graph + vector index over typed "DataPoints", loads to a store.
  Graph+vector hybrid, similar family to Zep but more general-purpose.
- **Relevance to SEAM:** another data point that the field is converging on
  *structured/distilled representations + hybrid retrieval*, which is the same
  conclusion SEAM reached empirically (raw turns lose; derived facts win).

## The common thread

Every system that scores well stores **distilled or structured units** that
resemble queries, not raw dialogue — via extraction (mem0), graphs (Zep,
cognee), or agent self-editing (Letta). SEAM's differentiator is doing this
**losslessly and with provenance** (`../seam-internals/derived-facts-grounded-clm.md`,
`seam-positioning.md`), rather than as an opaque, lossy rewrite.
