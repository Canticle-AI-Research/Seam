# Memory competitor audit: mechanisms worth stealing, score contracts to reject

Date: 2026-07-20

Scope: Mem0, Hindsight, Zep/Graphiti, and Cognee, compared against SEAM's
measured LoCoMo miss buckets. This is an architecture audit, not a blended
leaderboard. The only score-to-score claim SEAM should make is under a frozen,
matched harness.

## Bottom line

SEAM does not need another generic "hybrid retrieval" rewrite. It already has
lexical/BM25, semantic, graph, temporal, weighted/RRF fusion, optional
cross-encoder reranking, and query-time context projections. The meaningful
difference in the strongest current systems is the set of **representations
searched in parallel**:

- concise extracted facts;
- source episodes/raw turns;
- entities and relationship text;
- evidence-backed observations or summaries;
- temporal validity/current-state views.

The best immediate fit is therefore sentence-grounded fact indexing beside RAW,
followed by reserved multi-scope packing. The graph, reranker, and fusion
machinery should be reused, not rebuilt.

Execution status: the shared-code free sentence-grounded gate passed after this
audit (51/63 misses reached; 46/63 wording-closure wins; mean closure +0.1138;
exact source binding 0.9956; fact/evidence cosine 0.7147). The default-off
`sentence-grounded-clm/1` runtime slice is implemented with exact sentence and
fact hashes, source offsets, canonical speaker attribution, source-before-fact
ordering, and the existing 20% prefix ceiling. No paid judge/answerer call or
score claim was made.

## Keep the score contracts separate

### SEAM's matched comparator

The frozen Mem0 contract already used by SEAM is
`mem0ai/memory-benchmarks@4b61c5d`, top-200, `gpt-4o` answerer and judge. Under
that contract SEAM measured:

| Category | SEAM | Mem0 reference | Gap |
| --- | ---: | ---: | ---: |
| cat1 multi-hop | 87.94% (248/282) | 91.3% | -3.4 points / 10 cases |
| cat3 open-domain | 69.79% (67/96) | 72.7% | -2.9 points / 3 cases |
| cat2 temporal | 71.96% | 92.0% | -20.0 points |
| cat4 single-hop | 87.16% | 91.2% | -4.0 points |

Cat1+cat3 is 315/378 = 83.33%. Two net cases are +0.53 points on that slice;
one case is +0.26. This is the useful scale for the operator's half-point
ratchet.

### Current public numbers are research inputs, not direct opponents

| System | Public result | Why it is not directly comparable to SEAM |
| --- | --- | --- |
| Mem0 new algorithm | 92.5 LoCoMo, mean 6,956 tokens | New May-2026 algorithm and current harness, not the pinned `4b61c5d` comparator. |
| Hindsight v0.4.19 | 92.0 LoCoMo in AMB single-query mode | AMB artifact uses Gemini 3.1 Pro answerer, Gemini 2.5 Flash Lite judge, and averages 36,235 context tokens. |
| Zep | 94.7 LoCoMo, median 5,760 tokens | Reader and judge are GPT-5.4; retrieval is a hand-composed five-scope benchmark configuration. |
| Cognee | No current full comparable LoCoMo headline | Its public benchmark focus is BEAM; the AMB Cognee LoCoMo artifact currently contains only 152 questions, so it is not a full-run comparator. |

This distinction matters. Hindsight's benchmark authors explicitly warn that
answer prompt, judge prompt, and model changes can move accuracy by double
digits. Zep's older LoCoMo evaluation was also disputed over denominator and
prompt differences; its repository now reports a corrected older result of
75.14%, not the original 84% claim.

## What each system actually does

### Mem0: fact distillation plus three retrieval signals

The current Mem0 pipeline extracts facts at ingest, builds entity links, and
scores semantic similarity, BM25, and entity matching. Its new algorithm adds
agent-generated facts as first-class memories and uses a single-pass ADD-only
extraction path.

What fits SEAM:

- sentence-grounded fact text as an additional index surface;
- exact RAW/source-sentence provenance retained beside every paraphrase;
- entity text as an independent search signal, not only a graph bonus.

What does not need rebuilding:

- BM25, vector search, entity/graph storage, and fusion already exist;
- global RRF and cross-encoder variants already measured flat or regressive on
  the old representation set.

Why Mem0 still caps: its current category chart leaves open-domain at 82.3%,
well below its factual categories, and its own roadmap names temporal
abstraction and cross-session structure as unfinished. Fact distillation fixes
wording distance; it does not by itself solve external-knowledge naming,
temporal evolution, or every cross-session join.

Sources: [Mem0 research](https://mem0.ai/research),
[Mem0 benchmark repository](https://github.com/mem0ai/memory-benchmarks).

### Hindsight: fact extraction, four retrieval lanes, consolidation, optional agentic recall

Hindsight's published architecture separates world, experience, observation,
and opinion networks. Recall combines vector, keyword, graph, and temporal
retrieval. Newer releases add evidence-linked observations synthesized from
multiple facts; the project attributes its rise from the paper-era result to
better retention, observations, and a reworked retrieval algorithm.

What fits SEAM:

- derived facts must be accurate before retrieval tuning can help;
- evidence-backed observations/entity summaries are a second-stage index
  surface after facts are trustworthy;
- multi-query retrieval should be selectively invoked for multi-hop questions,
  not applied globally.

Why Hindsight caps: the current AMB single-query artifact is weakest on
multi-hop (70/96 = 72.92%), while Hindsight itself describes single-query
coverage as the tradeoff and agentic multi-query as more accurate but slower
and more expensive. Its 92.0 aggregate also uses a very large 36k-token average
context, so there is a substantial efficiency frontier left.

Sources: [ACL paper](https://aclanthology.org/2026.acl-demo.27/),
[Hindsight AMB explanation](https://hindsight.vectorize.io/blog/2026/03/23/agent-memory-benchmark),
[observations and mental models](https://hindsight.vectorize.io/blog/learning-capabilities),
[reproducible AMB output](https://github.com/vectorize-io/agent-memory-benchmark/blob/main/outputs/locomo/locomo-hindsight/rag/locomo10.json.gz).

### Zep/Graphiti: temporal context graph plus five-scope composition

Graphiti models entity relationships with validity intervals and provenance back
to raw episodes. Zep's current benchmark searches five scopes in parallel:
facts, entities, episodes, observations, and thread summaries. It then applies
cross-encoder reranking and client-side context composition.

What fits SEAM:

- explicit valid-from/valid-to/current-state handling for the cat2 wrong-instance
  date wall;
- reserved quotas across fact, RAW/episode, entity, observation, and temporal
  scopes so one dense lane cannot displace every other representation;
- source provenance remains mandatory for every derived scope.

Why Zep caps: its own current table is lowest on open-domain (79.2%). More
revealingly, its untuned single-call auto-search scores 86.5% while the
hand-composed five-scope setup scores 94.7%: 8.2 points depend on routing and
composition around the graph, not the graph alone. The 2026 result also uses
GPT-5.4 reader/judge, so it cannot establish that Graphiti alone beats SEAM's
matched contract.

Sources: [Zep current methodology](https://www.getzep.com/research/),
[Graphiti architecture](https://github.com/getzep/graphiti),
[older corrected Zep result](https://github.com/getzep/zep-papers/tree/main/kg_architecture_agent_memory/locomo_eval),
[benchmark-method dispute](https://github.com/getzep/zep-papers/issues/5).

### Cognee: graph/vector memory with search-strategy routing

Cognee's useful lesson is routing, not a comparable LoCoMo number. Its public
BEAM result is 0.79 at 100k and 0.67 at 10M, explicitly labeled directional;
the repository says per-question routing raises the 100k result above 0.8. Its
memory pipeline moves between graph structure, embeddings, sessions, and
metadata, and its public evaluation emphasizes graph-completion reasoning.

What fits SEAM:

- classify the query shape and route to a small set of proven retrieval/packing
  recipes;
- keep the recipe choice in the trace and promotion ledger;
- evaluate routing on held-out cases because benchmark-category labels are not
  available at inference time.

Why Cognee caps: the published delta from default 0.79 to above 0.8 with
per-question routing is direct evidence that one retrieval policy is not best
for every question. Its 10M result also shows that graph structure does not
remove the large-scale retrieval problem.

Sources: [Cognee repository and benchmark caveats](https://github.com/topoteretes/cognee),
[Cognee evaluation page](https://www.cognee.ai/research-and-evaluation-results).

## SEAM overlap and actual gaps

| Mechanism | SEAM today | Decision |
| --- | --- | --- |
| Semantic/vector retrieval | Present | Keep. |
| Lexical/BM25 retrieval | Present | Keep; no generic rewrite. |
| Graph retrieval | Present, including live MIRL projection | Reuse; improve indexed representations first. |
| Temporal scoring/projection | Present but cat2 remains 20 points short | Add validity/current-state and time-bucket coverage only behind a measured gate. |
| RRF | Present; measured regressive/noise-level globally | Do not retry until new lanes change the candidate distribution. |
| Cross-encoder rerank | Present; measured regressive on old candidates | Revisit only after multi-scope candidates exist. |
| Sentence-grounded paraphrase facts | Preflight in progress | Highest-EV immediate gate. |
| Evidence-backed observations/entity summaries | Not yet a benchmark lane | Second-stage, after fact precision. |
| Multi-scope reserved packing | Not present in competitor form | High-value small slice after facts. |
| Selective multi-query/agentic retrieval | Blind PRF second hop failed | Retry only as query-classified semantic decomposition. |
| Bitemporal fact validity | Partial temporal substrate, not Zep parity | Cat2 track after cat1/cat3 fact gate. |

## The ratchet queue

Every slice is default-off. A failed slice stays parked with its evidence; it is
not combined into a larger speculative stack.

1. **Sentence-grounded fact preflight (FREE, now).** Paraphrase for indexing,
   exact source sentence for provenance. Required: at least 30/63 misses reached,
   at least 95% exact sentence binding, at least 15 cases where fact wording is
   closer to the query than RAW, mean closure at least +0.02, and a local
   semantic-support proxy at least 0.50. This is a direction gate, not a score.
2. **Sentence-grounded runtime policy (FREE first).** Only if step 1 passes.
   Preserve RAW, cap derived facts at 20% of every result prefix, place source
   before fact, and measure gained/lost gold presence over all 63 misses plus
   stored-correct sentinels.
3. **Paid paired microgate (operator-gated).** Same-day baseline/candidate,
   frozen `gpt-4o` contract. Promote at net +2 cases on cat1+cat3 (+0.53 points)
   with zero candidate-caused sentinel losses. Do not pay for a full run first.
4. **Reserved multi-scope pack.** Allocate small protected quotas for RAW,
   grounded fact, entity/relation, and temporal evidence. Free gate: new gold
   evidence gained with zero existing gold displacement. This copies Zep's
   useful composition idea without copying its platform.
5. **Evidence-backed observation/entity-summary lane.** Consolidate only from
   accepted grounded facts; every sentence links to supporting fact IDs and RAW
   provenance. Target cat1 set/naming and cat3 naming misses. Free closure and
   contradiction tests precede any answerer call.
6. **Query-shape router.** Choose among factual, set/count, temporal,
   open-domain naming, and multi-hop recipes. Promotion requires a held-out
   confusion matrix and per-bucket no-regression, not access to gold category
   labels.
7. **Selective semantic multi-query.** For classified multi-hop/naming queries,
   generate bounded subqueries from entities/relations, then fuse results.
   Blind PRF remains rejected because it already gained 0/48.
8. **Temporal validity/current-state slice.** Add valid-from/valid-to and
   mentioned-at distinction, then time-window and bucket-spread retrieval for
   cat2. This is the Zep-class lever that attacks SEAM's largest measured gap.

## Promotion rule

The frozen matched comparator is the scoreboard. A candidate must pass, in
order:

1. hermetic unit and invariant tests;
2. free evidence-presence/closure gate;
3. free displacement regression gate over previously correct sentinels;
4. operator-approved paired paid microgate;
5. full matched run only after the microgate clears the cost-adjusted threshold.

No score claim may mix Mem0's new algorithm, Hindsight AMB, Zep GPT-5.4, Cognee
BEAM, SEAM native judge/1, or SEAM's pinned Mem0 comparator. Their architectures
are inputs; only the frozen contract decides whether a SEAM change ratchets.
