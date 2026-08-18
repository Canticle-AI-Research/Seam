# Advanced Agent Persistence Layers — Architecture and Benchmark Audit

**Date:** 2026-08-18. **Research cutoff:** 2026-08-18.
**Scope:** primary-source review of advanced persistence architectures for LLM
agents and personal knowledge systems, filtered by public benchmark evidence.
**SEAM boundary:** this report does not audit the current SEAM implementation.
It defines what a benchmark-proven SEAM persistence architecture must contain
and prove. Ghost, a model, or another agent supplies active cognition; SEAM is
the durable, compounding second-brain substrate.

Primary sources here mean original papers, official documentation, official
source repositories, authored specifications, and checked-in benchmark
artifacts. A system author's own benchmark is primary evidence, but not
independent evidence. Marketing pages are used only when they are the system
author's canonical disclosure and are labeled accordingly.

---

## 1. Executive verdict

SEAM should play the second brain. It does not need a separate product called a
second brain. It does need a clean boundary between:

- **the persistence substrate:** evidence, canonical records, temporal state,
  memory lifecycle, derived indexes, compiled context, retrieval, provenance,
  permissions, and recovery; and
- **active cognition:** the model or agent that plans, reasons, acts, chooses
  tools, and decides when to read or propose writes.

No reviewed system is the proven universal winner. The current frontier is a
set of partially overlapping patterns:

1. Karpathy's LLM Wiki has the clearest **immutable sources -> maintained
   knowledge compilation** pattern, but no benchmark proof.
2. LangGraph has the clearest **execution checkpoint vs cross-thread store**
   separation, but does not supply or benchmark a memory policy.
3. MemGPT/Letta has the clearest **agent-controlled context paging** model, but
   its original comparative proof is now saturated.
4. Zep/Graphiti has the strongest explicit **episodic source + bi-temporal
   semantic graph** design and solid, though vendor-authored, LongMemEval proof.
5. Mem0 has the strongest current **production-style fact extraction and
   multi-signal retrieval** evidence at LoCoMo, LongMemEval, and BEAM scale, but
   its best pipeline is proprietary and its checked-in result artifacts do not
   currently reconcile with its README headlines.
6. A-MEM and EverMemOS are the strongest **self-organizing memory** references;
   A-MEM has meaningful external evaluation, while EverMemOS's best results
   remain author-produced.
7. MemOS is the broadest **memory operating-system proposal**—plaintext,
   activation/KV, parametric memory, ACLs, lifecycle, migration, and sharing—but
   its end-to-end benchmarks mainly prove the plaintext retrieval plane, not
   the entire OS design.
8. Hindsight has the clearest **world/experience/opinion/observation
   separation**, but its paper copies several comparator scores and leaves its
   retrieval budgets as literal placeholders.
9. MIRIX has the broadest demonstrated **multimodal personal-memory taxonomy**,
   but its ScreenshotVQA proof is only 87 questions from three users.

The benchmark frontier also invalidates a single leaderboard. LoCoMo and
LongMemEval are static conversational QA; EverMemBench stresses multi-party
attribution and evolving rules; EMemBench asks questions over agent-generated
text and visual trajectories; MemoryArena measures whether memory changes
future task success; LongMemEval-V2 measures multimodal context gathering over
up to 115 million tokens; BEAM tests ten abilities at 1 million and 10 million
tokens. A system can lead one and fail another.

The credible target is therefore not “highest LoCoMo score.” It is a layered
architecture with a preregistered, reproducible evaluation portfolio.

## 2. What “persistence layer” must mean

The field often calls all stored context “memory.” That collapses distinct
contracts and makes architecture and benchmark claims impossible to audit.

| Layer | Durable object | Required contract | Typical failure when conflated |
| --- | --- | --- | --- |
| Working execution state | Messages, tool state, graph state, pending writes | Atomic checkpoint, replay, fork, recovery, bounded retention | A semantic-memory score is used to imply crash recovery |
| Episodic memory | What happened, in order, with source payloads | Event identity, participants, occurrence time, transaction time, evidence backtrace | Summaries silently replace the episode |
| Semantic memory | Facts, entities, relations, current resolved state | Attribution, uncertainty, contradiction, version and evidence | Latest extraction becomes unqualified “truth” |
| Procedural memory | Workflows, rules, skills, successful/failed traces | Applicability, version, outcome evidence, rollback | A stale procedure is retrieved as a fact |
| Compiled knowledge/context | Wiki pages, profiles, runbooks, packs, manifests | Derived status, source coverage, build version, reproducible regeneration | A generated summary becomes canonical and self-cites |
| Retrieval indexes | Embeddings, BM25, graph projections, caches | Disposable and rebuildable from canonical records | Index corruption or deletion destroys memory |
| Reasoning provenance | Decisions, conclusions, public justifications, tool evidence | Claim-to-evidence lineage without hidden chain-of-thought | A model rationale is promoted to truth |
| Governance plane | Principal, tenant, namespace, ACL, retention, deletion | Enforced authorization, scoped erasure, audit, export, recovery | A naming convention is mistaken for tenant isolation |

This distinction is not academic. LangGraph's official persistence guide calls
a checkpointer a thread-scoped graph-state snapshot and a store cross-thread
application-defined data; they solve different problems
([LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence)).
Its memory guide separately describes semantic facts, episodic experiences,
and procedural instructions
([LangChain memory concepts](https://docs.langchain.com/oss/python/concepts/memory)).

## 3. Architecture comparison

Legend: “proposed” means the primary paper specifies the capability but the
cited end-to-end benchmark does not establish it. “Addressing” means IDs or
namespaces exist; it does not mean authorization was tested.

| System/pattern | Canonical durable plane | Derived/working planes | Time and correction model | Provenance and lifecycle | Tenancy/governance | Benchmark status |
| --- | --- | --- | --- | --- | --- | --- |
| Karpathy LLM Wiki | Immutable raw sources | LLM-maintained Markdown wiki, index, synthesis | Git history and append-only operation log; no formal bi-temporal model | Strong source-of-truth split; promotion and deletion rules left to schema | Filesystem/repository boundary only | No system benchmark |
| LangGraph | Developer-defined Store data | Thread checkpoints and semantic indexes | Checkpoint history/time travel; app owns semantic correction | State replay strong; memory evidence model app-defined | Namespace addressing; deployment auth external | Persistence plumbing unbenchmarked |
| MemGPT/Letta | Conversation/archival stores and persistent blocks | Core in-context blocks and agent-managed paging | Agent edits memory; version/evidence semantics are application-dependent | Operational trace and block IDs; no canonical-vs-derived truth contract | Agents and shareable blocks; access policy is platform-level | DMR saturated; current leaderboard is mostly model-inside-Letta |
| Zep/Graphiti | Raw episode nodes | Entity/fact/community subgraphs and retrieval context | Event-valid and transaction timelines; contradictions invalidate fact edges | Bidirectional episode/fact indexes; hard CRUD exists | Graph group/namespace addressing; authorization not established by paper | Vendor LME proof; external EverMemBench and MemEval integrations |
| Mem0 v3 | Extracted ADD-only facts plus SQL history | Entity graph, embeddings, temporal metadata, ranked results | Old/new facts coexist; temporal metadata and soft recency rerank | History API and CRUD; best platform never overwrites during extraction but supports explicit delete | `user_id`, `agent_id`, `app_id`, `run_id`; platform/project auth | Strong vendor scale claims; exact v3 artifacts currently discrepant |
| A-MEM | Atomic notes retain original interaction content | LLM tags, context, embeddings, links | “Evolution” replaces derived note attributes; no version chain in paper | Original content retained, but evolution lineage/deletion/tenancy weak | Not a first-class paper concern | Author LoCoMo plus external EMemBench/LightMem |
| MemOS | Proposed MemoryCube payload plus metadata | Plaintext, activation/KV, parametric/LoRA memories; scheduler and caches | Proposed lifespan, decay, version chain, rollback, migration | Proposed origin, trace, ACL, compliance and access logging | Proposed ACL/read-write-share and cube isolation | Retrieval/personalization proof; whole heterogeneous OS not proven |
| EverMemOS | MemCells with episodic traces and atomic facts | MemScenes, profile, time-bounded foresight, reconstructed context | Self-organizing consolidation and validity-filtered foresight | Episodic-to-scene organization; profile/foresight mainly qualitative | Not a central evaluated property | Strong author LoCoMo/LME; no exact independent reproduction found |
| Hindsight | Extracted narrative facts in memory banks | World, experience, opinion, observation networks; summaries | Occurrence ranges; opinions have confidence and reinforcement | Evidence-bearing opinions are separated from world facts, but raw canonical retention is not the benchmark focus | Bank-level isolation; full erasure/ACL proof not shown | Vendor paper plus external MemEval integration |
| MIRIX | Six typed memory stores | Active topic retrieval and multi-agent routing | Managers can apply targeted corrections; formal bitemporal/version contract absent | Typed source fields and sensitivity labels; raw screenshots are discarded in the benchmark configuration | Multi-user product and sensitivity control claimed; not benchmarked | Author LoCoMo and small private ScreenshotVQA |

### 3.1 Karpathy's April 2026 LLM Wiki

Karpathy's authored gist is an architectural seed, not a product benchmark. It
specifies three layers: immutable raw sources as source of truth, an
LLM-maintained Markdown wiki, and an agent instruction/schema file. Ingestion
can update 10–15 pages, the index catalogs content, and `log.md` is an
append-only operational timeline
([primary gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)).

What SEAM should inherit:

- raw evidence is not edited by the compiler;
- compiled pages are derived products;
- the compiler has an explicit schema and maintenance protocol;
- all ingests and query/maintenance operations are logged; and
- compiled knowledge remains inspectable and diffable.

What SEAM must add: record-level evidence binding, typed contradictions and
supersession, reproducible coverage accounting, tenant/deletion semantics,
machine-verifiable regeneration, and benchmarks. Filing answers back into the
wiki is useful compounding only if the answer remains a derived claim whose
evidence and promotion state are explicit; otherwise the system can create a
self-citing feedback loop.

### 3.2 LangGraph persistence and Store

LangGraph is an important substrate reference, not an end-to-end second-brain
winner. Its checkpointer saves graph state for one `thread_id`; its Store holds
cross-thread JSON under developer-defined namespaces. Checkpoints enable
continuity, human-in-the-loop review, time travel and fault recovery. The Store
can support preferences, facts, shared knowledge, and optional semantic search
([official persistence guide](https://docs.langchain.com/oss/python/langgraph/persistence)).

The framework deliberately leaves memory schemas, admission, consolidation,
evidence, and retrieval policy to the application. Namespace tuples can encode
user or organization scope, but a namespace is addressing, not proof of access
control. Old checkpoints can grow without bound; the guide recommends an
application retention policy. No official end-to-end memory-quality benchmark
was found. EMemBench evaluates **LangMem**, which must not be reported as proof
of LangGraph's persistence layer.

### 3.3 MemGPT and Letta

MemGPT introduced OS-inspired virtual context: a model actively pages between
in-context memory and external recall/archival storage
([MemGPT paper](https://arxiv.org/abs/2310.08560)). Current Letta exposes
persistent editable blocks, archival/conversation memory, and blocks that can
be attached to multiple agents
([stateful agent docs](https://docs.letta.com/v1-sdk/concepts/stateful-agents),
[shared blocks](https://docs.letta.com/tutorials/attaching-detaching-blocks/)).

This is active memory management—valuable for Ghost or another cognitive
agent—but it is not by itself a canonical knowledge substrate. Agent-editable
blocks need source lineage, correction history, and promotion rules if used as
durable truth.

The original DMR result, 93.4% with GPT-4 Turbo versus 35.3% recursive
summarization, established that agent-managed hierarchical memory could work.
DMR has only 500 examples, five sessions and at most 60 messages per example;
Zep later measured a 94.4% full-context baseline and called the benchmark
saturated. Letta's current leaderboard tests which models can perform memory
operations inside Letta, not which persistence system is best
([archived leaderboard and protocol](https://github.com/letta-ai/letta-leaderboard)).
Letta's separate filesystem LoCoMo result, 74.0% with GPT-4o-mini, is a useful
agentic-search demonstration but not a matched comparison to later Mem0 or Zep
stacks
([Letta filesystem study](https://www.letta.com/blog/benchmarking-ai-agent-memory/)).

### 3.4 Zep and Graphiti

Graphiti's graph has three linked tiers: raw episodes; extracted entities and
facts; and community summaries. Episodes contain the original message, text or
JSON and maintain bidirectional indexes to derived facts. Its bi-temporal model
tracks both event validity and database transaction time. New contradictions
invalidate overlapping facts rather than erasing history. Retrieval combines
cosine search, BM25, graph traversal, reranking, and context construction
([Zep/Graphiti paper](https://arxiv.org/html/2501.13956),
[Graphiti source](https://github.com/getzep/graphiti)).

This is the best reviewed reference for temporal semantic projection with
episode provenance. Important boundaries remain:

- community summaries and extracted fact edges are derived, even when stored
  in the same graph;
- “non-lossy” means episodes remain, not that extraction is lossless;
- bulk episode ingestion explicitly omits edge invalidation
  ([episode documentation](https://help.getzep.com/graphiti/core-concepts/adding-episodes));
  and
- Graphiti supports hard deletion, but the papers do not benchmark dependent
  projection cleanup, authorization, or erasure completeness
  ([CRUD documentation](https://help.getzep.com/graphiti/working-with-data/crud-operations)).

### 3.5 Mem0 v3

Mem0's current managed pipeline performs related-context lookup, single-pass
ADD-only fact extraction, hash deduplication and embedding, entity linking, and
a separate temporal metadata pass. It stores facts in a vector database,
entities and links in a graph store, and ADD history plus a rolling message
window in SQL. Search fuses semantic, BM25, entity, and temporal scores; memory
decay is a soft rerank and does not hide or delete facts
([official evaluation architecture](https://docs.mem0.ai/core-concepts/memory-evaluation)).

This is a strong scalable fact-memory design. It is not a canonical raw-evidence
design: extracted memories are the primary retrieval objects, and the managed
platform's proprietary improvements prevent exact OSS equivalence. Explicit
CRUD, scoped delete and history APIs exist; the platform requires at least one
scope for bulk deletion and uses user, agent, app, and run identifiers
([delete contract](https://docs.mem0.ai/core-concepts/memory-operations/delete),
[OSS REST contract](https://docs.mem0.ai/open-source/features/rest-api)). Those
are useful lifecycle primitives, but tenancy strength must be judged by the
authorization implementation, not the filter names.

### 3.6 A-MEM

A-MEM builds Zettelkasten-style atomic notes containing original content,
timestamp, LLM-generated keywords/tags/context, an embedding, and links. It
retrieves nearest notes, asks an LLM to create links, and can “evolve” nearby
notes. The paper's evolution equation replaces the old note representation
with the evolved one, without a specified immutable version ledger
([A-MEM paper](https://arxiv.org/html/2502.12110),
[code](https://github.com/WujiangXu/A-mem)).

The self-organizing link pattern is valuable, especially for discovering
cross-episode structures. It must be kept derived: LLM-generated context,
tags, and links should never overwrite the evidentiary object, and each
evolution should be versioned and attributable.

### 3.7 MemOS

MemOS is the most ambitious reviewed systems architecture. Its paper proposes
MemoryCubes containing payload plus origin, semantics, timestamps, permissions,
lifespan, priority, compliance metadata, usage history, and version chains. It
unifies plaintext memory, activation/KV memory, and parametric/LoRA memory behind
a scheduler, lifecycle manager, governance layer, vault, loaders/dumpers, and a
controlled memory marketplace. It also proposes migration among hot, cold and
archival stores and permission-preserving export
([MemOS paper](https://arxiv.org/html/2507.03724),
[source](https://github.com/MemTensor/MemOS)).

That breadth is a design reference, not a fully proven bundle. The public
LoCoMo and LongMemEval results chiefly exercise text memory and retrieval. They
do not jointly prove ACL enforcement, KV/activation correctness, parametric
promotion and rollback, cross-type migration, licensed sharing, or deletion.
Each needs a separate conformance and adversarial benchmark.

### 3.8 EverMemOS

EverMemOS forms MemCells containing episodic traces, atomic facts and
time-bounded foresight, consolidates them into thematic MemScenes and profiles,
then uses scene-guided reconstructive retrieval with a sufficiency check. Its
retrieval combines dense and BM25 signals with RRF and reranking
([EverMemOS paper](https://arxiv.org/html/2601.02163),
[source](https://github.com/EverMind-AI/EverMemOS)).

The episode -> cell -> scene hierarchy is a strong consolidation pattern. The
paper explicitly says profile and foresight behavior is presented qualitatively
because existing reasoning benchmarks do not cover it. Therefore its headline
QA scores establish a retrieval/reasoning pipeline, not all claimed personal
memory behavior.

### 3.9 Hindsight

Hindsight separates four logical networks: world facts, first-person
experience, subjective opinions with confidence/evidence, and neutral
observations. TEMPR retrieves in parallel through semantic, BM25, graph and
temporal channels, fuses with RRF, reranks, and enforces a token budget. CARA
uses retrieved memory and a behavioral profile to form responses and update
opinions
([Hindsight paper](https://arxiv.org/html/2512.12818),
[source](https://github.com/vectorize-io/hindsight)).

The evidence/opinion separation is important: subjective belief must not be
collapsed into canonical world truth. However, its paper's LongMemEval and
LoCoMo retrieval budgets remain the literal string `<add>`, and several
competitor scores are copied from other reports using different judges. The
architecture is advanced; the paper's cross-system ranking is not a matched
leaderboard.

### 3.10 MIRIX

MIRIX uses six memory types: core, episodic, semantic, procedural, resource,
and a sensitive knowledge vault. A meta memory manager routes writes to
specialized managers, while active retrieval infers the topic and searches
each store. The paper describes targeted correction and sensitivity-based
access controls
([MIRIX paper](https://arxiv.org/html/2507.07957),
[source and public evaluation branch](https://github.com/Mirix-AI/MIRIX)).

It is a valuable multimodal second-brain reference. But in ScreenshotVQA it
stores extracted SQLite information rather than the raw screenshots. That
creates a 99.9% storage reduction relative to the paper's RAG baseline and a
35% accuracy gain, while also making unextracted visual details unrecoverable.
The evidence set is only 87 manually written questions across three private
personal screenshot collections, so the result is promising rather than broad
proof.

## 4. Benchmark evidence audit

### 4.1 Rules for reading every number

A benchmark claim is a tuple, not a scalar:

```text
(dataset hash and question scope,
 task protocol and metric,
 persistence build,
 ingestion/extraction model,
 embedding/reranker,
 retrieval top-k and token budget,
 answerer,
 judge and prompt,
 repeats/seeds,
 public per-item artifacts)
```

Changing any member creates a new result. In particular:

- LoCoMo is commonly reported as **1,540 non-adversarial questions** or
  **1,986 including adversarial questions**; these are not the same test.
- LLM-judge binary accuracy, token F1, BLEU, pass rate, and average rubric score
  cannot be ranked in one column.
- A result where a frontier answerer sees 200 memories is not evidence that the
  persistence layer alone improved.
- Commercial Zep is not OSS Graphiti; managed Mem0 v3 is not Mem0 OSS; LangMem
  is not LangGraph checkpointing.
- A benchmark author's integration is useful external evidence, but it is not
  an exact independent reproduction unless it pins and reproduces the claimed
  product build and protocol.

### 4.2 Claim ledger

| Claim | Dataset/task/metric | Comparator | Model, judge and budget coupling | Public artifacts and reproduction boundary | Classification |
| --- | --- | --- | --- | --- | --- |
| MemGPT 93.4 vs recursive summary 35.3 | DMR; 500 five-session conversations; answer accuracy | Recursive summary; later full context measured 94.4 | GPT-4 Turbo participates in agent memory operations; original grading protocol is model-coupled | [Paper](https://arxiv.org/abs/2310.08560) and [research artifacts](https://research.memgpt.ai/); no current exact reproduction found | Seminal author result; saturated benchmark |
| Zep 94.8 vs MemGPT 93.4 and full context 94.4 | DMR; LLM-judge accuracy | MemGPT score copied from its paper; Zep reran full context | GPT-4 Turbo; top 10 graph results; conversations fit context | [Paper and prompts](https://arxiv.org/html/2501.13956), [notebooks](https://github.com/getzep/zep-papers/tree/main/kg_architecture_agent_memory) | Vendor result; 0.4 point “win” not meaningful proof |
| Zep 71.2 vs full context 60.2 | LongMemEval-S; 500 QA; official binary judge | Matched full context | Graph build GPT-4o-mini-2024-07-18; answerer GPT-4o-2024-11-20; GPT-4o judge; BGE-m3; top 20; about 1.6K retrieved vs 115K full context | Public paper/notebooks; MemGPT could not be backfilled | Strong vendor-authored static-QA proof, not independently reproduced exactly |
| Mem0 v3 92.5 and 94.4 | LoCoMo 1,540 and LongMemEval 500; judge pass rate | No matched full-system table in current release | README defaults GPT-4o answerer/judge and top 200; checked-in platform artifacts identify GPT-5 answerer/judge | [Harness/README](https://github.com/mem0ai/memory-benchmarks), [LoCoMo artifact at audited commit](https://github.com/mem0ai/memory-benchmarks/blob/4b61c5d31b9c668a12b4f5e78064248a02c82d2b/results/platform/locomo_results.json), [LME artifact](https://github.com/mem0ai/memory-benchmarks/blob/4b61c5d31b9c668a12b4f5e78064248a02c82d2b/results/platform/longmemeval_results.json) | Vendor claim; artifact-discrepant and proprietary backend |
| Mem0 v3 BEAM 70.1% pass / .641 avg at 1M; 50.5% / .486 at 10M | BEAM; 700 1M and 200 10M questions; pass rate and average rubric score | Top-50 ablation, not a competitor | Top 200; checked-in stack is model-coupled; mean retrieved context reported around 6.7K/6.9K | Same public harness and per-question artifacts; managed memory backend proprietary | Best disclosed scale claim, not an independent system comparison |
| A-MEM GPT-4o-mini temporal F1 45.85 and 2,520 answer tokens | LoCoMo 7,512 QA including adversarial; F1/BLEU | LoCoMo, ReadAgent, MemoryBank, MemGPT | `all-MiniLM-L6-v2`; nominal top 10 adjusted by category; same prompts | [Paper](https://arxiv.org/html/2502.12110), [evaluation code](https://github.com/WujiangXu/A-mem) | Author result; category-tuned retrieval and lexical metric |
| A-MEM text overall 51.9; visual 36.3 with Qwen3 family | EMemBench; trajectory-conditioned programmatic QA; ACC/F1 | Same-backbone in-context, Mem0 and LangMem where supported | Qwen3-32B text; Qwen3-VL-32B visual; agent-generated trajectories and exact game ground truth | [Paper](https://arxiv.org/html/2601.16690), [official code](https://github.com/InternLM/EMemBench) | Strong external integration; not an exact reproduction of A-MEM's LoCoMo claim |
| MemOS 75.80 LoCoMo; 77.8 LongMemEval | LoCoMo LLM-judge and LME official judge | Multiple memory systems, configured to authors' best validation settings | GPT-4o-mini backbone; roughly 1.6K/1.4K context; exact judge identity unclear in main text | [Paper](https://arxiv.org/html/2507.03724), [repo](https://github.com/MemTensor/MemOS) | Same-organization result; proves text plane, not complete OS |
| EverMemOS 93.05 LoCoMo and 83.00 LME | LoCoMo 1,540 and LME 500; averaged judge accuracy | Zep/Mem0/MemOS/MemoryOS/MemU | GPT-4.1-mini operations/answerer for headline LoCoMo; GPT-4o-mini plus two auxiliary judges; about 2.3K/2.8K context | [Paper](https://arxiv.org/html/2601.02163), open repo; LME comparator scores copied from MemOS leaderboard | Strong author result; LoCoMo reruns more comparable than LME table; no exact independent reproduction found |
| Hindsight 83.6 LME with OSS-20B | LME 500; binary correctness | Published Full Context, Zep, Supermemory rows | GPT-OSS-20B memory and answerer; GPT-OSS-120B judge at temperature 0; retrieval budget unspecified due paper placeholders | [Paper](https://arxiv.org/html/2512.12818), [source](https://github.com/vectorize-io/hindsight) | Vendor result; comparator and budget defect prevent ranking |
| MIRIX 85.38 vs full context 87.52 | LoCoMo 1,540; GPT-4.1 judge accuracy | Matched GPT-4.1-mini reruns for some baselines; other table rows copied | GPT-4.1-mini backbone; judge GPT-4.1; baseline integration issues disclosed | [Paper](https://arxiv.org/html/2507.07957), public predictions/judgments in repo | Author result with three-run MIRIX outputs; no independent exact reproduction found |
| MIRIX .595 vs SigLIP .441 | ScreenshotVQA; 87 private-user QA; GPT-4.1 judge accuracy | Gemini long context and SigLIP@50 | Gemini-2.5-flash-preview-04-17 backbone | Aggregate results public; source screenshots private | Small vendor-only multimodal result, not reproducible end to end |

#### Mem0 artifact discrepancy

The current Mem0 README reports 1,425/1,540 = 92.5% on LoCoMo and 472/500 =
94.4% on LongMemEval. At repository commit `4b61c5d`, the checked-in platform
JSON reports 1,410/1,540 = 91.56% and 467/500 = 93.4%, and identifies GPT-5 in
the run metadata. Until the project links each headline to an immutable result
artifact or explains the replacement run, the scores are **artifact-discrepant
vendor claims**, not independently reproducible records. This does not refute
the architecture; it changes the confidence assigned to the exact numbers.

### 4.3 Strong external normalized evidence

The best available cross-system evidence is still imperfect:

1. **ProsusAI MemEval.** On all 1,986 LoCoMo questions, it uses GPT-4.1-mini as
   answerer, `text-embedding-3-small`, and GPT-5.2 as judge. Results were:
   full context F1 .542 / judge .709; Hindsight .489/.676; OSS Graphiti
   .416/.573; Mem0 .344/.497. It exposes 24.2M, 5.1M and 3.0M system-LLM token
   totals for Hindsight, Graphiti and Mem0 respectively
   ([repository and protocol](https://github.com/ProsusAI/MemEval)). This is an
   external matched integration for those systems, but the benchmark authors
   also develop PropMem, and OSS Graphiti is not commercial Zep.
2. **EverMemBench.** Official cloud APIs under default configurations, fixed
   GPT-4.1-mini answerer, top 10 for Zep/Mem0 and top 20 for MemOS: full context
   37.44 +/- 1.8, Mem0 37.09 +/- 1.9, Zep 39.97 +/- 1.9, MemOS 42.55 +/- 1.9.
   With Gemini-3-Flash, full context reaches 72.61 while the same retrieval
   systems degrade it. This is strong evidence of retrieval/reader coupling,
   not proof that full context scales beyond one million tokens
   ([paper](https://arxiv.org/html/2602.01313),
   [code/data](https://github.com/EverMind-AI/EverMemBench)).
3. **EMemBench.** It integrates Mem0, LangMem and A-MEM over programmatically
   generated QA grounded in each agent's own text/visual game trajectory.
   A-MEM improves Qwen2.5-32B text ACC 40.8 -> 51.4 and Qwen3-32B 44.9 ->
   51.9, but slightly reduces GPT-5.1 visual ACC 43.8 -> 42.1. This is evidence
   that text organization gains do not automatically transfer to visual
   episodic fidelity.
4. **LightMem's A-MEM rerun.** GPT-4o-mini judge accuracy 64.16 versus naive
   RAG 63.64 and full text 73.83, with about 21.7M construction-plus-QA tokens
   and 67,084 seconds disclosed
   ([LightMem repository](https://github.com/zjunlp/LightMem)). This is a useful
   cost counterweight to A-MEM's token-efficient answer contexts.

None of these is a universal independent leaderboard. They are the strongest
available checks against vendor-only claims.

## 5. The 2026 benchmark frontier

| Benchmark | What it actually tests | Scale and metric | Model/judge coupling | What it does not prove |
| --- | --- | --- | --- | --- |
| LoCoMo | Post-hoc QA over synthetic long conversations | 1,540 non-adversarial or 1,986 including adversarial; judge accuracy or lexical metrics | Extremely sensitive to answerer, judge, top-k and question scope | Agent task success, scale beyond about 9K tokens, tenancy/deletion |
| LongMemEval-S | Post-hoc QA over user-assistant histories | 500 questions; about 115K tokens; binary accuracy | Fixed question-specific judge prompts, but answerer and retrieval budget drive scores | Real interaction, multimodal environment use, 1M/10M scale |
| EverMemBench | Multi-party/multi-group attribution, updates, implicit rules and persona | 5 projects, 170 employees, 51,023 turns, 4.225M total tokens, 2,400 QA; accuracy with bootstrap CIs | Cloud memory APIs plus fixed reader; oracle reveals retrieval vs reasoning errors | Action-dependent consequences or production governance |
| EMemBench | Episodic recall/reasoning over the agent's own interactive text and visual trajectories | 15 text games and multi-seed Crafter; programmatic ACC/F1 | Same backbone with/without memory; trajectory differs by agent/seed | End-task benefit; it is post-hoc QA after interaction |
| MemoryArena | Memory -> action -> environment loop across interdependent sessions | 766 tasks, average 57 steps and >40K-token traces; Success Rate and Process Score | GPT-5.1-mini fixed task agent for memory-system comparison | Canonical truth, deletion, storage recovery, raw evidence completeness |
| LongMemEval-V2 | Memory as bounded multimodal context gathering over past web-agent trajectories | 451 curated questions; up to 500 trajectories and 115M tokens; accuracy/latency frontier | Returned context capped at 200K; fixed Qwen3.5-9B reader; GPT-5.2 judge; controller varies | Autonomous memory writes, personalization, lifecycle governance |
| BEAM | Static long-conversation QA across ten abilities at scale | 100 coherent conversations, 2,000 QA, 128K/500K/1M/10M; ability score | Generator, answerer, judge, embedding and retrieval depth all matter | Agent-environment task success or evidence governance |

### 5.1 MemoryArena: end-to-end utility

MemoryArena is the strongest reviewed test of whether persistent memory helps
future action. It includes bundled shopping, group travel, progressive search,
and sequential math/physics. Under the fixed GPT-5.1-mini task agent, all-task
Success Rate is .15 for Letta, .14 for Mem0, .12 for Mem0-g, .16 for
GPT-5.1-mini long context, and .23 for a plain embedding RAG system. Every
tested system scores 0 full success on group travel
([paper and reproducible setup](https://arxiv.org/html/2602.16313),
[project](https://memoryarena.github.io/)).

This prevents a static-QA winner from being declared a second-brain winner.
The result is not a stable universal ranking—task agent, integration and
latency matter—but it proves current memory systems are far from solved.

### 5.2 LongMemEval-V2: compiled procedural context

LongMemEval-V2 reframes memory as a context-gathering module. It inserts up to
500 multimodal web-agent trajectories, then requires a system to return a
length-bounded context to a fixed reader. Its 451 questions cover static state,
dynamic state, workflows, gotchas and premise awareness across public small and
medium tiers and private scale up to 115M tokens
([paper](https://arxiv.org/html/2605.12493),
[official repository](https://github.com/xiaowu0162/LongMemEval-V2)).

With a fixed Qwen3.5-9B reader and 200K returned-context cap:

| Memory controller | Small accuracy / latency | Medium accuracy / latency |
| --- | --- | --- |
| Query -> raw slice | .428 / .1s | .381 / .1s |
| Query -> slice + notes | .510 / .2s | .459 / .3s |
| AgentRunbook-R | .586 / 26.9s | .570 / 25.8s |
| Vanilla Codex | .699 / 177.2s | .687 / 185.8s |
| AgentRunbook-C | .749 / 108.3s | .701 / 139.9s |

AgentRunbook-C stores raw trajectories as files, generates manifest artifacts,
gives a coding agent a workflow and inspection helper, and returns selected
state spans plus a brief memory note. This independently reinforces Karpathy's
compiled-wiki idea: human/agent-readable files and manifests can be a powerful
derived context plane. It also shows that a strong active controller can cost
hundreds of seconds per query; SEAM must report accuracy-latency-cost frontiers,
not accuracy alone.

### 5.3 BEAM at 1M and 10M

BEAM contains 100 coherent conversations at 128K, 500K, 1M and 10M tokens and
2,000 validated questions over abstention, contradiction resolution, event
ordering, information extraction, instruction following, knowledge update,
multi-session reasoning, preference following, summarization and temporal
reasoning
([paper](https://arxiv.org/html/2510.27246),
[official repository](https://github.com/mohammadtavakoli78/BEAM)).

The paper's LIGHT method combines episodic memory, working memory and a
scratchpad. Its own ablations show only small average gains at 10M and failures
in temporal reasoning, event ordering and contradiction. These are author
ablations, not a cross-vendor result. Mem0's v3 BEAM results are presently the
most detailed system-scale disclosure, but because they use a proprietary
backend and model-coupled public artifacts they should be treated as a target
to reproduce, not an accepted leaderboard crown.

## 6. What a benchmark-proven SEAM second brain must contain

This is a target architecture derived from the evidence above. It is not a
claim about current code.

### 6.1 Required planes

1. **Immutable evidence plane.** Preserve original messages, documents, tool
   events and multimodal regions with content hashes and source coordinates.
   Deletion may tombstone or cryptographically erase authorized data, but no
   compiler or reasoning process silently rewrites evidence.
2. **Canonical memory IR.** Typed episodes, claims, entities, relations,
   procedures, preferences, states and public justifications. Every
   non-evidence record has exact evidence references, confidence, creator,
   model/config version, occurrence time and transaction time.
3. **Reconciliation plane.** Corrections, contradiction, corroboration,
   supersession, deprecation and uncertainty are additive transitions.
   “Current state” is a resolved view, not erased history.
4. **Derived temporal graph.** Project canonical records into entities,
   relationships, event-valid intervals and transaction history. Graph nodes,
   summaries, embeddings and communities are disposable rebuildable indexes,
   never a second source of truth.
5. **Episodic and procedural consolidation.** Retain exact episodes while
   building scenes, patterns, successful/failed procedures and applicability
   conditions. Compiled skills remain linked to the traces and outcomes that
   justified them.
6. **Compiled knowledge plane.** Generate wiki pages, profiles, project state,
   runbooks, manifests and token-budgeted packs. Each artifact has a build
   manifest, source coverage, omissions, compiler version and reproducible
   regeneration path.
7. **Working-state adapter plane.** Integrate with LangGraph/other runtimes for
   checkpoint, replay and fork without confusing transient graph state with
   durable semantic memory.
8. **Retrieval controller.** Hybrid lexical, vector, entity, graph and temporal
   candidate generation; rank fusion; optional reranking; query decomposition;
   sufficiency/abstention; bounded context construction; exact retrieval trace.
   A cheap deterministic path and an agentic controller path should share the
   same evidence contract.
9. **Reasoning provenance.** Persist conclusions, alternatives, decision
   inputs, tool results and public justification—not hidden chain-of-thought.
   Reasoning products remain derived until an explicit promotion process
   creates a canonical claim.
10. **Governance and tenancy.** Principal-bound authorization, tenant/workspace/
    agent/session scopes, ACLs, encryption and key rotation, retention, scoped
    export, soft deletion, hard deletion, dependent-index cleanup and erasure
    proof. Namespace strings alone are insufficient.
11. **Lifecycle and recovery.** Atomic writes across canonical data and outbox,
    migrations, backups, restore drills, deterministic index rebuild, cache
    invalidation, corruption detection and idempotent replay.
12. **Observability.** Per-memory lineage, write decisions, retrieval candidates,
    rank features, packed context, answer provenance, model/token/cost/latency,
    lifecycle operations and rejected writes.

### 6.2 Non-negotiable invariants

- Canonical truth and derived indexes have one-way authority.
- No LLM-generated summary, tag, link, state, profile, procedure or opinion is
  silently promoted.
- Every answer can return evidence or say that evidence is insufficient.
- Every correction preserves the prior assertion and its valid interval.
- Every derived artifact can be deleted and rebuilt from authorized canonical
  records.
- Every tenant boundary is enforced under adversarial direct-object and filter
  tests, not inferred from IDs.
- Every hard deletion produces a verifiable impact set across raw/canonical,
  graph, vector, cache, compiled context, backup and audit retention policy.
- Every benchmark run can be replayed from an immutable manifest without
  reusing another arm's store.

## 7. Proof program SEAM must run

### 7.1 Public benchmark portfolio

| Gate | Required comparison | Required disclosure |
| --- | --- | --- |
| LoCoMo | Full context, BM25, dense RAG, Mem0 OSS/current platform where licensed, Graphiti OSS, Hindsight, A-MEM | Both 1,540 and 1,986 scopes reported separately; judge accuracy and token F1; matched answerer/judge/top-k |
| LongMemEval-S | Same matched baselines plus no-memory and oracle evidence | 500/500; per-category; fixed reader; evidence recall; context tokens; provider latency/cost |
| BEAM | 128K, 500K, 1M and 10M curves | Same stack at every scale; all ten abilities; ingest/search/answer cost; failures and abstentions |
| EverMemBench | Official benchmark APIs or pinned adapters | Fixed answerer; top-k/token parity; single/multi/temporal/update/profile breakdown; oracle gap |
| EMemBench | Same-backbone in-context and memory arms | Text and visual; fixed seeds plus multiple seeds; ACC/F1 by ability; raw visual evidence retention |
| MemoryArena | Long context, BM25/dense RAG, leading memory integrations | Fixed task agent; SR, PS, sPS, latency and cost; memory updates/retrieval traces for every subtask |
| LongMemEval-V2 | Raw slice, slice+notes, AgentRunbook-R/C style controllers | Fixed reader/judge; 200K return cap; LAFS accuracy/latency frontier; selected multimodal spans |

### 7.2 SEAM-native conformance benchmarks

Public QA benchmarks do not prove persistence safety. SEAM also needs
operation-level tests with exact, programmatic oracles:

- **canonical round trip:** evidence -> IR -> pack/wiki -> referenced IR ->
  evidence, with field/provenance/temporal coverage;
- **correction:** conflicting updates in and out of order, bitemporal queries,
  current-state resolution, no stale compiled answer;
- **hallucinated extraction:** unsupported claim insertion, omitted fact,
  wrong speaker, wrong time, wrong entity merge, and false procedure promotion;
- **derived rebuild:** delete every vector/graph/wiki/cache projection and prove
  byte- or semantics-equivalent regeneration from canonical records;
- **deletion:** per-item, per-user, per-workspace and legal-hold cases, with
  dependent projection cleanup and declared backup boundary;
- **tenancy:** cross-tenant ID guessing, metadata filters, shared blocks,
  namespace confusion, graph traversal, caches, exports and background jobs;
- **atomicity/recovery:** process kill at every write phase, replay, duplicate
  delivery, migration interruption, corrupted index, backup/restore;
- **compiled-context safety:** coverage gaps, stale builds, cyclic/self-citing
  derivation, poisoned source, conflicting sources, and revoked evidence;
- **reasoning provenance:** conclusion-to-evidence reconstruction and explicit
  separation of public justification from hidden model reasoning;
- **cost/scaling:** ingest throughput, search p50/p95/p99, rebuild time, storage
  amplification, answer tokens, background consolidation cost and total dollars
  from 100K through 10M+ tokens.

HaluMem is a useful external starting point for extraction, update,
hallucination and omission measurement
([official repository](https://github.com/MemTensor/HaluMem)), but SEAM's
canonical/derived and deletion/tenancy contracts require additional native
oracles.

### 7.3 Run manifest required for every claim

Every published score should include:

- system commit, product version, container digest and migration version;
- dataset source, immutable hash, exact conversation/question IDs and scope;
- clean isolated store ID and tenant for each arm;
- ingestion/extraction, temporal parser, embedding, reranker, controller,
  answerer and judge model IDs—not family aliases;
- prompts, tool schemas, temperatures, reasoning effort and timeouts;
- top-k at every stage, token budget, returned-context tokens and truncation;
- reference-time rules, timezone and treatment of missing timestamps;
- seeds, repetitions, confidence intervals and failure/error counts;
- per-question writes, retrieval candidates/scores, selected context, answer,
  judge decision and evidence lineage;
- ingest/search/controller/answer/judge latency, tokens, calls and cost; and
- exact known limitations, proprietary components and independent reproduction
  status.

## 8. Decision

Build SEAM as the second-brain persistence architecture, not as a plug-in fact
store beneath another second brain. Its defensible differentiator should be:

> immutable evidence + canonical typed memory + temporal reconciliation +
> disposable derived graphs/indexes + compiled wiki/runbook context + public
> reasoning provenance + lifecycle/tenancy guarantees, proven across static QA,
> context gathering, multimodal episodic recall, agent task success and 10M+
> scale.

Karpathy's LLM Wiki should become one SEAM compiler target. LangGraph
checkpoints should become one runtime adapter. Ghost should be one cognitive
consumer. Graphiti, Mem0, A-MEM, MemOS, EverMemOS, Hindsight and MIRIX should be
benchmark comparators and sources of tested design patterns—not unexamined
architectural authorities.

The immediate proof criterion is not “more features than every competitor.” It
is one reproducible matched-stack evaluation where SEAM's quality/cost frontier
is competitive, every answer traces to evidence, corrections and deletion are
programmatically correct, and the entire derived layer can be rebuilt. Then add
MemoryArena and LongMemEval-V2 to prove that the persistence substrate improves
real agent behavior rather than only post-hoc conversational QA.

## 9. Uncertainty and exclusions

- Current product APIs and benchmark pages can change after the cutoff. Exact
  versions must be pinned before running comparisons.
- No exact independent reproduction was found for current managed Mem0 v3,
  commercial Zep's latest stack, MemOS's full OS claim, EverMemOS, or MIRIX.
- ProsusAI MemEval is external to the systems it reruns but develops its own
  comparator; EverMemBench is authored by the EverMemOS organization. Both are
  useful normalized evidence, not neutral certification bodies.
- Vendor-vendor disputes, such as prompt mismatches in later Zep/Mem0 LoCoMo
  claims, are not treated as resolved without a shared immutable harness.
- Current benchmarks barely test legal deletion, authorization, backup
  retention, migration safety, poisoning, or reasoning provenance. Architectural
  claims in those areas remain proposals until conformance tests exist.
- This landscape audit intentionally makes no claim that current SEAM code
  already implements or passes the target architecture and proof program.

## Evidence manifest

Raw artifacts: none
