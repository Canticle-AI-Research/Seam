# Zep / Graphiti — temporal knowledge graph

> Architecture patterns as understood at 2026-07. Verify against Zep/Graphiti
> current docs before relying on specifics. Relevant to SEAM's cat2 (temporal)
> gap and any graph-retrieval work.

## Core design: bi-temporal entity/relation graph

Zep's engine (Graphiti) builds a **temporal knowledge graph** from the
conversation rather than a flat fact list:

- **Extraction:** entities (nodes) and relationships/facts (edges) are extracted
  from messages, typically as subject–predicate–object triples with natural-
  language fact text on the edge.
- **Bi-temporal model:** each edge carries validity time (when the fact became
  true / stopped being true, `t_valid` / `t_invalid`) *and* ingestion time. When
  a new fact contradicts an old one, the old edge is **invalidated** rather than
  deleted — the graph remembers *when* things were true.
- **Structure:** episodes (raw messages) → semantic edges (facts) → entity nodes,
  plus higher-level **community/summary** nodes.

## Retrieval

Hybrid: **semantic (embedding) + BM25 (lexical) + graph traversal**, over both
edges (facts) and nodes (entities), often with a reranking pass and community
summaries for breadth. The graph lets it answer multi-hop and temporal questions
by traversing relationships and reading validity intervals, not just top-k
similarity.

## Why it's strong on temporal (cat2)

The explicit validity intervals mean "when did X happen" and "what was true at
time T" are first-class: the answer is a property of the edge, not something the
answerer must infer from scattered raw turns. This is the opposite of SEAM's cat2
failure mode (HISTORY#424/#426): SEAM serves raw turns and the answerer picks the
wrong *instance's* date.

## Costs / tradeoffs (SEAM's opening)

- Heavy ingest (entity + relation extraction + temporal reasoning per message).
- Graph construction is a correctness + latency surface.
- On LoCoMo open-domain, mem0's flat distilled facts have historically scored
  higher than Zep — graph structure isn't a free win on every category.

## Relevance to SEAM

- SEAM already has a temporal knowledge-graph surface (the dashboard KG, MIRL
  projection) and `temporal/1` (native) + `temporal-instance/1` (facade,
  #427) levers. Zep is the reference design for **Track R (Zep-class temporal
  graph parity)**, which is roadmap-gated behind native progress + a matched
  Mem0-harness win.
- The load-bearing idea to borrow for cat2 is **validity intervals on facts**, so
  the queried instance's date is stored explicitly rather than inferred. Fold
  this into the derived-facts work (`../seam-internals/derived-facts-grounded-clm.md`)
  before building a separate graph lever.
