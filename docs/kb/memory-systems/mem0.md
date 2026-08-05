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
  family). CORRECTED 2026-08-04: the paper states "All language model operations
  utilized GPT-4o-mini as the inference engine" -- gpt-4o-MINI, not gpt-4o. The
  judge is **lenient** (partial credit, paraphrase, extra detail, ±14-day dates).
- Published LoCoMo (arXiv:2504.19413 Table 1, LLM-as-a-Judge): single-hop **67.13**, multi-hop
  **51.15**, open-domain **72.93**, temporal **55.51**. Mem0^g: 65.71 / 47.19 /
  75.71 / 58.13.
- **The figures 91.2, 91.3 and 92.0 previously recorded here are NOT in the
  paper.** Only open-domain ~72.7 was real. Three of the four numbers SEAM
  measured itself against were never Mem0's.
- To claim "SEAM beats mem0," hold answerer + judge + dataset + cutoff constant
  and run SEAM through their unmodified harness via the facade
  (`../eval-methodology/locomo-mem0-harness.md`).

## Current matched standing (HISTORY#429)

CORRECTED 2026-08-04 -- the previous claim here was inverted. Under the paper's
gpt-4o-mini contract SEAM LEADS all four: single-hop 87.16 vs 67.13, multi-hop
88.65 vs 51.15, open-domain 86.46 vs 72.93, temporal 71.96 vs 55.51. The gpt-4o
run below is a stricter-judge internal ratchet, not an incumbent-relative number.
(Superseded text:) Under the matched gpt-4o answerer+judge, SEAM is behind on all four categories
(cat1 87.94 / cat3 69.79 measured; cat4 87.16 / cat2 71.96 on the mini lane).
The derived-facts lever is the bet to close cat1/cat3; open-domain (cat3) and
counts overlap with mem0's own weak spots.

## Source-verified extraction contract (read `mem0ai/mem0` v2.0.12, 2026-07-21)

Read directly from `/home/terrabyte/BEAM/mem0` (Apache-2.0). This **corrects and
sharpens** the cutoff-era notes above; the mechanism is more precisely:

- **Current production extractor is `ADDITIVE_EXTRACTION_PROMPT`** (`mem0/configs/
  prompts.py`, wired at `mem0/memory/main.py:912`) — an **ADD-only** contract with
  `linked_memory_ids` (graph edges). The ADD/UPDATE/DELETE/NONE reconcile
  (`DEFAULT_UPDATE_MEMORY_PROMPT`) is the older v1.1 path, not the default V3 flow.
- **The precision model is a two-stage split, not a gate:** a **recall-biased
  extract** ("When in doubt, extract. A missed extraction means lost context";
  "typically extract 5–15 memories" per long conversation) followed by **downstream
  dedup / linking**. mem0 gets recall by extracting liberally and cleaning up after,
  the opposite of SEAM's single fail-closed ingest door.
- **Breadth (the load-bearing delta vs SEAM):** extracts from **every speaker**,
  including **third-person** facts attributed by name ("Maria got a cat named
  Bailey"), events, relationships, plans, milestones, entity attributes, and
  incidental facts stated as context. SEAM's live `sentence-grounded-clm/1` is
  **singular first-person only** — on the multi-speaker LoCoMo corpus that refuses
  most gold turns, the diagnosed cause of the 51/63 reach ceiling (HISTORY#439).
- **Shape:** contextually rich (15–80 words, fact + surrounding context), **not
  atomic**; temporally grounded **at ingest** against an Observation Date ("last
  week" → "week of May 15, 2023"); hard rules preserving proper nouns, exact
  numbers, and negation/meaning.
- **Search is hybrid:** vector + **BM25 keyword** (lemmatized, `mem0/utils/
  lemmatization.py`, `main.py:996`) + optional reranker (`main.py:480`). A cheap
  retrieval-side win independent of extraction.

### SEAM implication

The auditable translation is **not** to copy mem0's ungrounded paraphrase+reconcile
shape. It is to take the **recall breadth** (named third-party facts) while keeping
SEAM's precision mechanism as **grounding, not reconcile**. Sentence scope binds
names to one cited sentence; the turn-scope research probe permits only one unique
preceding antecedent and rejects ambiguity. Additional fail-closed checks preserve
ordered clause binding, tense, modality, numbers, and negation while refusing
quoted, reported, compound, or unsupported content. This is conservative
syntactic/lexical grounding, not proof of arbitrary semantic entailment.

Implemented as `seam_runtime/multi_speaker_facts.py`
(`multi-speaker-grounded/1`, default-off, preflight-first). See
`../seam-internals/derived-facts-grounded-clm.md`.
The hybrid BM25 signal is a separate, orthogonal lever worth its own free gate.
