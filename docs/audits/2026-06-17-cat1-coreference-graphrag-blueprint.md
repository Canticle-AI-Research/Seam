# cat1 Coreference + Entity-Aggregation Retrieval — External Blueprint

- **Date:** 2026-06-17
- **Status:** findings / blueprint (NOT a committed build spec — the build spec is gated on the Phase 0 diagnostic below)
- **Route:** retrieval / ingest
- **Supersedes nothing; complements** `docs/audits/2026-06-15-entity-aggregation-retrieval.md` (the #323 marginal-lever audit) and the LoCoMo retrieval audit.

## Why this doc exists

The campaign wall toward the 80% milestone is **cat1** (LoCoMo single-hop, 282 q / ~32% of cases, stuck at ~0.46). Per #321/#323 it moves for *no* answerer (gpt-4o, o4-mini reasoning, rerank all flat on cat1), which is the signature of a **retrieval-architecture** gap, not an answerer/budget gap. Root cause (#319): `compile_nl` ingests per-turn and emits **zero `ir_edges`** — each turn's "Melanie" is a different entity id — so there is nothing to aggregate over and no graph to traverse.

Two external sources independently describe the fix as a *solved, documented pattern*. This doc records that grounding and maps it onto SEAM, so the eventual build follows a known-good blueprint instead of being invented.

## External grounding (Web mode — Leeroopedia KB unavailable, citations from official docs)

1. **understand-anything plugin** (read locally, MIT, Egonex) — a working reference implementation of the two primitives SEAM lacks:
   - **Ingest dedup → edge remap** (`merge-knowledge-graph.py`): `normalize_entity_name = lower + collapse-whitespace` → first occurrence is canonical → `dedup_remap[dup_id] = canonical_id` → **every edge's source/target is rewritten through the remap, then validated (drop dangling)**. Crucially the *floor uses no model*; the LLM only adds implicit edges on top.
   - **Retrieval = 1-hop expansion** (`context-builder.ts`): match nodes for the query → expand 1 hop via edges → return the connected subgraph + its edges. This is structural entity-aggregation.
2. **Microsoft GraphRAG — Local Search** ([docs](https://microsoft.github.io/graphrag/query/local_search/)): the canonical formalization. Query → semantically-related **entry-point entities** → expand to **connected entities, relationships, covariates, text units** → **Ranking + Filtering** of each candidate set → fit a **single context window of predefined size**. Local search is explicitly "well-suited for questions that require understanding of specific entities" — i.e. cat1.
3. **GraphRAG (From Local to Global)** ([overview](https://microsoft.github.io/graphrag/), [paper](https://www.microsoft.com/en-us/research/publication/from-local-to-global-a-graph-rag-approach-to-query-focused-summarization/)): distinguishes **local** (entity-centric, specific facts) from **global** (community-summary, corpus-wide themes). cat1 is a *local* problem; do **not** over-build global/community machinery for it.
4. **Multi-fact accuracy gap** ([GraphRAG vs Vector RAG](https://tianpan.co/blog/2026-04-19-graphrag-vs-vector-rag-architecture-decision), third-party, web-sourced): graph retrieval ~86% vs vector ~32% on multi-hop; vector accuracy degrades toward 0% past ~10 entities while graph holds >70%. This is the EV case: aggregation questions are exactly where flat/vector retrieval collapses.
5. **LoCoMo** ([Snap Research](https://snap-research.github.io/locomo/)): five categories (single-hop, multi-hop, temporal, open-domain/world-knowledge, adversarial); ~35 sessions / ~300 turns / ~9k tokens per conversation; **answers scored by F1**. Confirms the cat framing and that the SEAM gate must be answer-level (token_f1), not recall.
6. **Hybrid (graph disciplines vector)** ([LLMs + KGs for QA survey](https://arxiv.org/pdf/2505.20099)): the graph can pre-filter/constrain vector candidates rather than replace them — maps onto layering entity-aggregation over SEAM's existing `search_ir`, not ripping it out.

## The blueprint, mapped to SEAM

Two coupled halves. Both are needed; which one is the *lever* is decided by Phase 0.

### A. Ingest coreference (the linking half) — `compile_nl` / a reconcile pass
- Within a **conversation scope** (never global — see caveats), key entities by `normalize(name)`; first occurrence is the canonical entity id.
- Map subsequent mentions to the canonical id; emit `ir_edges` from each claim to the canonical entity (subject grounding already exists per #311 — this makes the subject a *stable* id).
- Deterministic floor first (exact/normalized name match, no model); neural/LLM coreference is the *escalation* only if the floor proves the concept but leaves precision on the table. (Same floor→opt-in-Ollama discipline as #308/#313.)
- Result: SEAM's "zero `ir_edges`" becomes a real per-conversation entity graph.

### B. Entity-aggregation retrieval (the aggregation half) — `search_ir` / `RetrievalFlags`
- Identify query **entry-point entities** (the question's named entities).
- **Expand 1 hop over `ir_edges`** to gather claims grounded to those entities (SEAM's `_collect_closure_ids` follows evidence/prov ids today but **not** `ir_edges` — #318; this adds that traversal).
- **Rank + filter** the expanded set before packing — this is the documented GraphRAG step and the direct fix for the #323 dilution failure (string-match aggregation recovered recall but the answerer couldn't convert it because junk diluted the window).
- Fit the ranked subset into the context budget. Layer over existing `search_ir` (hybrid), don't replace it.

## Open question — Phase 0 decides the build (FREE, do before writing the build spec)

Split cat1 dev questions into **needle** (single gold turn) vs **aggregation** (gold = union across turns); for each, measure whether the gold turns are in top-k at the knee budget (top_k=100/budget=8000), and bucket failures:
- **gold-not-retrieved** → linking/ranking-bound → half **A** + ranking is the lever.
- **gold-retrieved-but-answer-wrong** → synthesis/packing-bound → half **B**'s consolidated subgraph (an entity "dossier" in one window) is the lever.

The blueprint covers both outcomes; Phase 0 only decides emphasis and ordering.

## Caveats (these govern the build)
1. **Scope boundary.** Coreference is **per-conversation**. Global entity merging would re-open the #274 substream leak ("John" in two unrelated conversations must not collapse).
2. **Deterministic floor, not an LLM-heavy index.** GraphRAG's *indexing* is LLM-per-community; SEAM keeps the cheap deterministic floor at ingest and borrows GraphRAG's *retrieval* pattern. Don't import the community-summary global machinery for cat1.
3. **Rank+filter is mandatory, not optional.** The #323 evidence is that aggregation without ranking dilutes the answerer. GraphRAG ranks/filters before fitting the window — match that.
4. **The gate is token_f1 over sets, paid last.** Graph construction improving ≠ answer quality (#323). Free deterministic recall A/B → local-Ollama token_f1 A/B over multiple scopes → paid judged only to confirm, operator-gated.

## References
- [GraphRAG — Local Search](https://microsoft.github.io/graphrag/query/local_search/) — entry-point entities → 1-hop expansion → rank+filter → fit window
- [GraphRAG — Overview](https://microsoft.github.io/graphrag/) — local vs global search distinction
- [From Local to Global: A Graph RAG Approach (MS Research)](https://www.microsoft.com/en-us/research/publication/from-local-to-global-a-graph-rag-approach-to-query-focused-summarization/) — foundational method
- [LoCoMo — Evaluating Very Long-Term Conversational Memory](https://snap-research.github.io/locomo/) — categories, scale (~300 turns/9k tokens/35 sessions), F1 eval
- [GraphRAG vs Vector RAG (multi-fact accuracy gap)](https://tianpan.co/blog/2026-04-19-graphrag-vs-vector-rag-architecture-decision) — graph ~86% vs vector ~32% multi-hop; vector→~0% at 10+ entities [web-sourced]
- [LLMs Meet Knowledge Graphs for QA: Synthesis and Opportunities](https://arxiv.org/pdf/2505.20099) — hybrid: graph disciplines vector retrieval
