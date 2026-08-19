# Graph Benchmark Readiness Beyond LoCoMo

**Status:** research complete; no benchmark execution performed

**Date / source cutoff:** 2026-08-18

**Repository revision inspected:** `48c5448157711f6db74f4c24be06b9c563aef5c6`

**Question:** What portfolio and exact evidence would justify saying that
SEAM's knowledge and reasoning graphs are top-level, rather than merely
implemented?

## Decision

SEAM cannot make that claim today. The graph implementation is unusually broad
and auditable, but the available measurements establish structural operation,
parity, and provenance plumbing—not a graph-caused quality advantage.

No single benchmark can prove both graph planes:

- The **knowledge graph** needs evidence that typed topology, identity,
  temporality, and graph retrieval add value over the same canonical records
  without graph traversal.
- The **reasoning graph** is a public justification and reusable-pattern store,
  not an LLM reasoner or hidden chain-of-thought archive. It needs evidence that
  verified patterns improve later work, not merely that reasoning nodes can be
  written and queried.

The minimum defensible program is a six-lane claim portfolio: native graph
conformance, GraphRAG-Bench, STaRK, Memora, LongMemEval-V2, and MemoryArena.
BEAM-1M is a required companion scale lane before any broader “top-level memory
system” wording. EverMemBench-Dynamic, HaluMem, and MemoryAgentBench are
high-value triangulation lanes, not substitutes for the six claim-critical
lanes.

## What current SEAM evidence actually establishes

The governing architecture is defined by the [SEAM specification](../../SEAM_SPEC_V0.1.md),
[MIRL contract](../MIRL_V1.md), [knowledge-graph contract](../KNOWLEDGE_GRAPH.md),
and [reasoning-graph contract](../REASONING_GRAPH.md). Those contracts implement
many prerequisites for a strong graph system: canonical RAW/MIRL truth,
rebuildable graph projections, scoped temporal state, evidence paths, retrieval
decision records, verification, and reusable reasoning patterns.

The measurement boundary is much narrower:

| Existing evidence | Verified fact | What it does **not** establish |
| --- | --- | --- |
| [Matched LoCoMo retrieval](../status/retrieval.md) | On 1,542 QA cases, `hybrid`, `mix`, and `mix + graph=0` all scored `0.776048`. The snapshot had zero admissible semantic relation edges. | Any semantic-graph contribution. The graph arm was operationally inert. |
| [WANDR replay](../status/benchmarks.md) | Hash-pinned, zero-network native (`mix`) and event-only (`hybrid`) replay both reached `1.0`. | Discriminating graph quality; the small hand-authored corpus is saturated and lacks hard entity collisions and joins. |
| [G7/R6 qualification](../roadmap/GRAPH_MEMORY_MATURITY.md) | A three-case, three-tenant provider-free suite reached `1.0/1.0`, zero graph-incremental hits, and zero provider calls. Mem0 and Zep remain unrun. | Competitive ranking or incremental value. |
| [Synthetic G3 qualification](../../tools/graph_retrieval_qualification.py) | A deterministic 2,048-node chain checks five query shapes, isolation, path length, and latency. | External relevance, construction quality, or answer/task lift. |
| [LoCoMo graph-probe tool](../../tools/graph_real_corpus_qualification.py) | Defaults to one LoCoMo sample, two sessions, and internally generated probes; dev/holdout alternates probes from the same generated graph. | An external held-out graph benchmark or independent gold labels. |
| [Relation-extraction qualification](../../tools/relation_extraction_qualification.py) | The admission contract requires at least 50 reviewed labels, point precision at least `0.90`, and Wilson lower bound at least `0.80`. Current recorded evidence remains 27 relations across 419 turns and scorer-ineligible. | Qualified semantic graph construction. |
| Provenance audit | Claim and RAW chains measured `1.0`; entity provenance measured `0.0`. | Complete graph-evidence attribution for entity-driven answers. |

Therefore, “G1–G7/R1–R6 implemented” and “graph superiority proven” are separate
claims. The first is substantially supported; the second is not.

## Claim decomposition

A top-level claim must be stated at one of these scopes:

1. **Projection integrity:** SEAM constructs, updates, deletes, rebuilds, and
   scopes its graph correctly.
2. **Knowledge-graph retrieval:** graph topology retrieves better evidence than
   flat retrieval from the same canonical memory.
3. **Temporal knowledge:** graph state resolves identity, updates,
   contradiction, expiry, and deletion more safely than flat memory.
4. **Reasoning-pattern reuse:** verified public patterns improve later task
   performance or evidence gathering.
5. **Competitive system:** the complete SEAM stack is Pareto-leading against
   pinned alternatives under a matched protocol.

Success at a lower scope must not be silently promoted to a higher one. In
particular, an imported gold graph proves retrieval over topology, not SEAM's
graph construction; a system-level win proves the bundle, not the graph
representation; and an answer win without graph-incremental evidence does not
prove the graph caused it.

## Benchmark-to-evidence matrix

“Current support” refers to code and tracked evidence at the inspected revision,
not planned roadmap text.

| Priority / benchmark | Capability isolated | Required graph-specific ablation | Current SEAM support | Missing work |
| --- | --- | --- | --- | --- |
| P0 — **SEAM native conformance corpus** | Relation construction, identity/coreference, bitemporal state, correction/deletion, provenance, tenant isolation, rebuild parity, reasoning verification and promotion/reversal | Gold relations and entity links: full graph vs no semantic REL; identity on/off; temporal validity on/off; clean rebuild vs incremental projection; R-pattern eligible/stale/rejected | Most storage and graph contracts exist; synthetic and focused tests exist; relation lane is below admission and ENT provenance is incomplete | Freeze independent gold labels; exceed admission size; add adversarial aliases, entity collisions, contradictions, deletions, cross-tenant negatives, and reasoning-pattern misuse cases |
| P0 — **[GraphRAG-Bench](https://arxiv.org/abs/2506.05690)** ([official code](https://github.com/GraphRAG-Bench/GraphRAG-Benchmark)) | End-to-end graph construction, retrieval, and generation across fact, complex-reasoning, summary, and creative tasks; explicitly asks when graph RAG beats vanilla RAG | Same corpus, reader, prompt, and context budget: flat RAG vs SEAM extracted graph; add oracle graph, semantic-edge shuffle, and graph-retrieval-disabled controls | No adapter or result | Implement official dataset/evaluator adapter; preserve stage metrics; publish construction, retrieval, and answer deltas separately |
| P0 — **[STaRK](https://arxiv.org/abs/2404.13207)** ([official code](https://github.com/snap-stanford/stark)) | Retrieval requiring both text and relations in Amazon, MAG, and PrimeKG semi-structured KBs | Same node text/candidates and top-k: flat text retrieval vs gold topology traversal; then gold graph vs SEAM-imported graph. Shuffle only relational edges as a negative control | Graph query primitives exist; no STaRK import, adapter, or score | Build typed import and answer-ID mapping; report MRR, Hit/Recall@k, relation-hop strata, graph-incremental IDs, latency, and memory size |
| P1 — **[Memora](https://arxiv.org/abs/2604.20006)** ([official code/data](https://github.com/geniesinc/Memora)) | Weeks-to-months remembering, reasoning, recommendation, and correct forgetting under updates/deletions; FAMA penalizes obsolete memory use | Full temporal graph vs flat canonical memory; disable validity edges, deletion filters, and identity resolution one at a time while keeping retrieval budget fixed | Temporal/lifecycle semantics exist; no adapter or run | Map benchmark update/delete events into event time and lifecycle state; record obsolete-evidence selections and current-state path traces |
| P1 — **[LongMemEval-V2](https://arxiv.org/abs/2605.12493)** ([official harness](https://github.com/xiaowu0162/LongMemEval-V2)) | Static/dynamic environment state, workflows, gotchas, and premise awareness over up to 500 trajectories / 115M tokens; accuracy-latency frontier | Same histories, controller, reader, and memory-token cap: raw/flat retrieval vs knowledge graph vs knowledge + eligible reasoning patterns; add a matched-budget pattern-slot placebo control | Original LongMemEval validator/upstream route exists; no V2 trajectory adapter or reasoning-pattern arm | Implement `insert/query` backend, multimodal evidence routing, question-type traces, fixed context cap, and latency accounting |
| P1 — **[MemoryArena](https://arxiv.org/abs/2602.16313)** ([project/data](https://memoryarena.github.io/), [preview code](https://github.com/ZexueHe/MemoryArena)) | Memory acquired from earlier actions guiding interdependent later subtasks in shopping, travel, search, mathematics, and physics | Same agent/controller/tools: no durable memory vs flat episode memory vs eligible reasoning patterns; add shuffled-pattern, stale-pattern, and verification-gate-disabled arms | Reasoning graph and pattern APIs exist; no environment adapter or result | Instrument exact pattern retrieval/use, later-subtask success, process scores, failed-reuse events, token/cost/latency; pin the still-preview upstream code |
| P2 — **[BEAM](https://arxiv.org/abs/2510.27246)** ([official code/data](https://github.com/mohammadtavakoli78/BEAM)) | 128K–10M coherent histories and ten abilities including contradiction, ordering, update, multi-session and temporal reasoning | At 1M first: same ingest and reader, flat vs semantic graph; temporal-edge and identity ablations; graph-shuffled control | Official 1M shape validator and pinned upstream execution route exist; 35 conversations / 700 questions validated locally. No scored graph ablation exists | Run free ingest/retrieval traces first, then approved scored matched arms; do not infer graph value from scale accuracy alone |
| P2 — **[EverMemBench-Dynamic](https://arxiv.org/abs/2602.01313)** ([official dataset](https://huggingface.co/datasets/EverMind-AI/EverMemBench-Dynamic)) | Multi-party/group identity, evolving decisions, temporal multi-hop reasoning, memory awareness, and profiles over million-token dialogue | Identity/role/temporal graph on/off; cross-member identity-edge shuffle; same source evidence and reader | WANDR exercises scoped members only in a tiny synthetic replay; no official adapter | Add speaker/group/entity resolution, reference-snippet scoring, and explicit cross-member collision failures |
| P2 — **[HaluMem](https://arxiv.org/abs/2511.03506)** ([official code/data](https://github.com/MemTensor/HaluMem)) | Operation-level hallucination in extraction, updating, and QA over persona, event, and relationship memory | Score extracted relations before retrieval; full graph vs flat update policy; inject/delete/update one relation at a time and trace downstream error propagation | Generic extraction and relation qualification exist; no HaluMem adapter | Preserve memory-point gold labels; report extraction/update/QA separately and attribute each QA error to the first bad memory operation |
| P2 — **[MemoryAgentBench](https://openreview.net/forum?id=DT7JyQC3MR)** ([official code](https://github.com/HUST-AI-HYZ/MemoryAgentBench)) | Incremental accurate retrieval, test-time learning, long-range understanding, and conflict resolution | Same incremental chunks and reader: flat vs graph; disable conflict/identity edges; knowledge-only vs knowledge + reviewed patterns | No adapter or result | Implement dataset mappings and fixed metric parsing; separate topology lift from chunking, model, and prompt effects |

The P2 lanes are not all required for an initial component claim. They become
required when wording expands to million-token scale, multi-party memory,
operation-level reliability, or general incremental learning.

## Prioritized minimal portfolio

### Gate 1 — Make the graph admissible

Build one frozen, independently reviewed native corpus before spending on
external QA. It must include at least 50 labeled extracted relations (the
current floor, not an aspirational quality target), multiple predicates,
cross-turn multi-hop paths, hard aliases/coreference, same-name entities,
contradictions, event-time updates, deletions, failed verifications, and
cross-tenant negatives. Require complete entity/claim-to-RAW provenance.

This gate answers: did SEAM build the right graph, and can it maintain it?

### Gate 2 — Prove knowledge-topology value

Run GraphRAG-Bench and STaRK. Together they separate two questions:

- GraphRAG-Bench tests SEAM's extracted graph through construction, retrieval,
  and generation against vanilla RAG.
- STaRK supplies an external semi-structured graph and therefore tests graph
  retrieval without making SEAM extraction the bottleneck.

If STaRK improves but GraphRAG-Bench does not, graph retrieval may be capable
while construction is not. If both improve only against weak flat retrieval
but not a matched dense+lexical baseline, a top-level claim still fails.

### Gate 3 — Prove temporal correctness

Run Memora/FAMA with per-operation traces. A graph that retrieves more facts but
reuses deleted or invalidated ones is not top-level. The primary metric is FAMA,
with obsolete-use rate and update/delete path correctness as mandatory
secondary metrics.

### Gate 4 — Prove reasoning-pattern reuse

Run LongMemEval-V2 and MemoryArena. LongMemEval-V2 directly probes workflows,
gotchas, dynamic state, and premise awareness under an explicit memory-context
cap. MemoryArena tests whether retained experience changes later action and
task success. Both must compare eligible reasoning patterns with the same
underlying knowledge memory and agent stack.

### Gate 5 — Prove scale without changing the claim

Run BEAM-1M using SEAM's existing pinned route. This is a scale and long-history
ability test, not inherently a graph benchmark. It supports the broad system
claim only after a graph-on/off trace shows active, attributable graph use.
BEAM-10M remains a later cost and infrastructure gate.

## Exact causal ablation contract

Every external corpus must be ingested once into a canonical source snapshot,
then cloned into fresh, isolated stores. Changing models, prompts, chunking,
record content, or answer context between arms invalidates a representation
claim.

### Knowledge-graph arms

| Arm | Allowed memory behavior | Purpose |
| --- | --- | --- |
| K0 flat | RAW/canonical records, identical lexical+dense retrieval; no graph candidates | Strong same-stack baseline |
| K1 structural | Provenance/source/episode topology only; semantic REL traversal disabled | Negative control for “a graph exists” |
| K2 semantic | K1 plus extracted semantic relations and graph retrieval | Candidate mechanism |
| K3 oracle | K2 retrieval over benchmark-gold relations | Separates retrieval capacity from graph construction |
| K4 shuffled | K2 with semantic edge endpoints permuted within boundary/degree strata | Detects gains caused by extra text, candidates, or budget rather than correct topology |
| K5 temporal-minus | K2 with validity/current-state resolution disabled | Measures temporal mechanism |
| K6 identity-minus | K2 with alias/coreference resolution disabled | Measures identity mechanism |

K0 and K2 must use the same source records, embeddings, reader, model version,
prompt, top-k, answer-facing token cap, tokenizer, query set, seed set, and
timeout. K3 and K4 are diagnostics, never deployable competitors.

### Reasoning-graph arms

| Arm | Allowed memory behavior | Purpose |
| --- | --- | --- |
| R0 episodes | Current task plus flat prior episodes; no reusable pattern retrieval | Same-stack baseline |
| R1 slot placebo | The same retrieval call, prompt slot, and token budget carry a schema-matched neutral recipe with controlled operations masked; pattern-use recording is disabled | Controls for extra context, latency, and salience |
| R2 pattern | Eligible verified pattern retrieval and use enabled | Candidate mechanism |
| R3 shuffled/stale | Wrong-task or stale patterns matched for length and rank | Detects generic prompting and unsafe reuse |
| R4 verification-minus | Pattern reuse enabled without freshness/evidence/verification admission | Measures the safety value of SEAM's gates |

R2 must log the exact pattern ID, source outcome, current verification IDs,
knowledge/evidence fingerprints, retrieval rank, whether it was used, the later
outcome, and any rejection. A task improvement with no attributable pattern use
is a system result, not reasoning-graph evidence.

## Required metrics and artifacts

### Construction and retrieval

- Relation and temporal-edge precision/recall/F1 on frozen human labels;
  entity-link/coreference F1; update, delete, and current-state accuracy.
- Recall@k, full evidence recall, MRR/NDCG where the benchmark defines them,
  graph-incremental hit rate, graph path precision, hop-stratified results, and
  abstention when no supporting path exists.
- Claim/entity-to-RAW provenance completeness and precision. A retrieved entity
  with no evidence backtrace cannot support a provenance-first graph claim.

### Answers and actions

- Official benchmark primary metric, per category and per case; FAMA and
  obsolete-use rate for temporal memory; task success and process/later-subtask
  gain for agentic work.
- Unsupported-answer rate, contradiction error, stale/deleted evidence use,
  failed-pattern reuse, and verification-gate rejection rate.
- Retrieval and end-to-end p50/p95 latency, ingest time, provider calls, tokens,
  dollar cost, peak memory, index/storage size, and rebuild time.

### Statistical decision rule

Pre-register one primary metric per benchmark and a smallest effect worth
claiming. Use paired case-level bootstrap 95% confidence intervals (and paired
binary tests where appropriate), report absolute deltas and denominators, and
correct for the predeclared family of primary comparisons. “Positive” means the
interval for K2−K0 or R2−R0 excludes zero and exceeds the practical threshold;
an aggregate point win is not enough. Report every category even when the
overall metric improves.

### Frozen run bundle

Each arm must publish or retain, subject to dataset licenses:

1. benchmark name/version, license, exact source URLs, commit IDs, dataset file
   hashes, split IDs, exclusions, and case count;
2. SEAM commit, schema/migration versions, graph projector and retrieval-policy
   fingerprints, clean-store lineage, ingest order, and store hash/manifest;
3. exact model/embedding/reader/judge IDs, prompts, tokenizer, temperatures,
   seeds, top-k, hop depth, token/context budgets, timeouts, retries, and pricing
   snapshot;
4. per-case question, gold/reference IDs, retrieved ordered evidence, per-leg
   scores/ranks, graph paths, provenance chain, selected context, answer/action,
   judge output, error class, timing, tokens, and cost;
5. aggregate and category metrics, confidence intervals, paired arm deltas,
   graph-incremental cases, failures/timeouts counted in denominators, and
   untouched raw logs/checkpoints;
6. one-command reproduction instructions, environment lock/container, hardware
   description, integrity seal, and public claim text generated only from the
   sealed result.

Provider or vendor results remain attributed claims unless SEAM reruns the
same pinned implementation. A blocked or unavailable comparator is `NOT_RUN`,
never zero and never silently omitted.

## Reproducibility tiers R0–R4

| Tier | Evidence available | Claim language allowed |
| --- | --- | --- |
| **R0 — reported** | Paper, leaderboard, or vendor headline only; configuration or per-case evidence is insufficient for audit | “The source reports …” only |
| **R1 — inspectable** | Pinned source/dataset identity, complete config/manifest, aggregate and per-case outputs, and code or interface description; not rerun by SEAM | “Inspectable reported result,” not reproduced |
| **R2 — internally reproduced** | SEAM reruns a frozen public benchmark from clean stores with sealed per-case artifacts and obtains the stated result | “Reproduced by SEAM under configuration X” |
| **R3 — matched causal comparison** | SEAM and pinned competitors/controls run on the same cases, model/reader/judge, prompts, budgets, seeds, and scorer; paired graph ablations and confidence intervals are complete | Component/system advantage may be claimed at the exact tested scope |
| **R4 — independently reproduced** | An unaffiliated party reproduces the released R3 protocol and verifies the sealed artifacts and claim boundary | Public “top-level” wording may cite independent confirmation |

R4 does not mean universal superiority. It confirms a specific frozen claim.
Model, dataset, or harness changes create a new result requiring requalification.

## Admission rule for “top-level”

SEAM may make a scoped **top-level knowledge-graph** claim only when all of the
following hold:

1. native construction/provenance/lifecycle conformance passes;
2. R3 matched K2−K0 evidence is positive on both GraphRAG-Bench and STaRK, with
   active graph-incremental evidence and edge-shuffle failure;
3. Memora shows no material FAMA or obsolete-use regression and demonstrates a
   temporal mechanism contribution;
4. SEAM is best or statistically tied for best among the predeclared runnable
   comparator set on the primary metric, within disclosed latency/cost/storage
   constraints; and
5. at least the central claim has one R4 reproduction.

SEAM may make a scoped **top-level reasoning-graph persistence** claim only when
R3-tier evidence for R2−R0 is positive on both LongMemEval-V2 and MemoryArena, the
attributed patterns are eligible and actually used, shuffled/stale controls do
not reproduce the gain, verification-minus exposes the expected safety loss,
and one central result reaches R4.

Until then, accurate wording is: **SEAM implements a provenance-first knowledge
graph and an inspectable reasoning/pattern graph; current provider-free
qualifications show structural operation and parity, while graph-specific
incremental and competitive value remain unproven.**

## Primary sources and source-specific limits

- [GraphRAG-Bench paper](https://arxiv.org/abs/2506.05690) and
  [official repository](https://github.com/GraphRAG-Bench/GraphRAG-Benchmark):
  directly designed to compare GraphRAG with vanilla RAG across construction,
  retrieval, and generation. Its domains do not test persistent user-memory
  lifecycle by themselves.
- [STaRK paper](https://arxiv.org/abs/2404.13207) and
  [official repository](https://github.com/snap-stanford/stark): large-scale
  textual-plus-relational retrieval with official splits. Because it supplies
  semi-structured KBs, it principally tests retrieval over a graph, not SEAM's
  conversation-to-graph compiler.
- [Memora paper](https://arxiv.org/abs/2604.20006) and
  [official repository](https://github.com/geniesinc/Memora): introduces
  remembering, reasoning, recommendation, and FAMA for obsolete/invalidated
  memory. It is end-to-end unless SEAM retains operation traces.
- [LongMemEval-V2 paper](https://arxiv.org/abs/2605.12493) and
  [official repository](https://github.com/xiaowu0162/LongMemEval-V2): 451
  manually curated questions over web/enterprise trajectories, with an
  explicit memory `insert/query` interface and accuracy-latency evaluation.
- [MemoryArena paper](https://arxiv.org/abs/2602.16313),
  [project/dataset](https://memoryarena.github.io/), and
  [official repository](https://github.com/ZexueHe/MemoryArena): directly tests
  earlier experience guiding later action. As of the cutoff, the repository
  labels itself a preview and has a very short history, so pinning and local
  validation are mandatory.
- [BEAM paper](https://arxiv.org/abs/2510.27246) and
  [official repository](https://github.com/mohammadtavakoli78/BEAM): 100
  conversations and 2,000 validated questions over four scales up to 10M
  tokens and ten memory abilities. It is graph-agnostic without SEAM's ablation.
- [EverMemBench paper](https://arxiv.org/abs/2602.01313) and
  [official Dynamic dataset](https://huggingface.co/datasets/EverMind-AI/EverMemBench-Dynamic):
  multi-party/group conversations with evolving information and reference
  snippets; useful for identity and temporal graph stress.
- [HaluMem paper](https://arxiv.org/abs/2511.03506) and
  [official repository](https://github.com/MemTensor/HaluMem): operation-level
  extraction, update, and QA ground truth; useful for localizing graph-build
  error propagation rather than reporting only final QA.
- [MemoryAgentBench paper](https://openreview.net/forum?id=DT7JyQC3MR) and
  [official repository](https://github.com/HUST-AI-HYZ/MemoryAgentBench):
  incremental interactions across retrieval, test-time learning, long-range
  understanding, and conflict resolution; broad but less graph-isolating than
  the P0/P1 lanes.

## Facts, inferences, and uncertainty

**Facts from tracked SEAM artifacts:** the current matched LoCoMo graph arm had
no semantic relation edges and tied the non-graph arms; WANDR and the native
qualification are parity results; relation extraction is below its recorded
admission threshold; matched Mem0/Zep graph qualification has not run; the
reasoning graph stores public justification and patterns rather than hidden
reasoning.

**Facts from primary external sources:** the listed benchmark purposes, task
families, dataset sizes, interfaces, and released code/data status come from the
linked author-owned papers, repositories, project pages, or datasets.

**Research inference:** the six claim-critical lanes are the smallest portfolio
that separately tests graph correctness, graph retrieval, temporal invalidation,
workflow knowledge, and future action. The exact ablation arms, statistical
threshold policy, R0–R4 definitions, and “top-level” admission rule are proposed
for SEAM; they are not standards declared by the benchmark authors.

**Uncertainty:** no benchmark or competitor was executed in this research pass,
and no current leaderboard ranking was adopted. Fast-moving 2026 repositories,
especially preview releases, can change after the cutoff. Dataset licenses and
provider costs may constrain public per-case redistribution or full-scale runs;
those constraints change artifact publication, not the causal evidence needed.

## Evidence manifest

Raw artifacts: none

Research actions were read-only apart from this report. No datasets were
downloaded, no providers or vendor services were called, no benchmark was run,
and no score was generated. Evidence consists of the linked tracked SEAM files
at revision `48c5448157711f6db74f4c24be06b9c563aef5c6` and the primary external
sources linked above, inspected through 2026-08-18.
