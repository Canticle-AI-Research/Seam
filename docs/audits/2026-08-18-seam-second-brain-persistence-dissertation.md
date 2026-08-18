# SEAM as a Benchmark-Proven Second-Brain Persistence Architecture

**Status:** consensus draft for Claude and Grok

**Date:** 2026-08-18

**Repository revision inspected:** `48c544815771`

**Scope:** product identity, persistence architecture, proof standard, and benchmark program

**Companion research:** [Advanced agent persistence layers](2026-08-18-advanced-agent-persistence-layers.md)

## Consensus protocol

This document is a decision instrument. Claude and Grok should evaluate each
numbered proposition in §12 as `ACCEPT`, `REVISE`, or `REJECT`. A revision must
provide replacement wording. A rejection must identify contradictory evidence
or a concrete failure scenario. Architectural preference without evidence is
insufficient.

Consensus exists only when both reviewers:

1. use the definitions in §2;
2. distinguish implemented behavior from proposed behavior;
3. apply the benchmark rules in §9 without relaxing them for SEAM;
4. agree on every proposition, including identical replacement wording for any
   revised proposition; and
5. list unresolved empirical questions as experiments rather than settling them
   rhetorically.

The required response schema is in §13.

## Abstract

SEAM should be understood as the second brain's persistence architecture, not
merely a vector-backed memory utility and not the autonomous agent that speaks,
plans, or uses tools. Its intended job is to turn experience into durable,
compounding, inspectable intelligence: immutable evidence, canonical semantic
memory, temporal and contradiction-aware state, derived knowledge products,
task-bounded context, and audited reasoning state. A model or agent supplies
active cognition. Ghost may supply the user-facing agent experience. Neither
replaces SEAM's role as the durable cognitive substrate.

Karpathy's LLM Wiki is an important expression of this same persistence idea:
raw sources remain immutable while an LLM maintains a structured, interlinked,
compounding knowledge artifact. It is a pattern, not a benchmarked memory
runtime. SEAM should subsume its strongest idea as a derived, human- and
agent-readable knowledge projection while retaining stricter canonical truth,
provenance, temporal, lifecycle, isolation, and recovery contracts.

“Most advanced” cannot mean the longest feature list or the highest score on one
vendor-run benchmark. “Proven” requires a portfolio of frozen, reproducible,
matched evaluations covering recall, updates, contradiction handling, temporal
reasoning, million-token scale, experience reuse, multi-session action, context
efficiency, provenance, deletion, crash recovery, and tenant isolation. SEAM
earns the second-brain claim only when those layers and their composition are
measured against strong baselines under one auditable protocol.

## 1. Central thesis

The governing thesis is:

> **SEAM is a provenance-first, temporally governed persistence architecture
> that compiles raw experience into canonical memory, derived knowledge,
> bounded context, and audited reasoning state. It is the durable second brain;
> models and agents are replaceable active-cognition adapters above it.**

This thesis corrects two incomplete framings.

“SEAM is only a memory runtime with a reasoning layer” understates the target.
Storage and retrieval are necessary, but a second brain must also accumulate,
reconcile, reorganize, compress, and reuse knowledge over time.

“SEAM is the whole autonomous second-brain agent” overstates the target. SEAM
does not own personality, goals, general planning, tool choice, or conversation
policy. Those belong to an agent such as Ghost. SEAM persists the evidence,
knowledge, context, and inspectable reasoning products that let many agents
behave as if they share one continuously developing mind.

The dependency direction is therefore:

```text
human and environment
        |
        v
agent / model / tools              active cognition
        |
        v
SEAM SDK and retrieval interface   cognitive seam
        |
        v
RAW -> MIRL -> projections -> compiled knowledge -> PACK
             \-> reasoning state -> reviewed promotion
```

The agent depends on SEAM for durable cognition. SEAM does not depend on one
agent identity, model provider, orchestration framework, or user interface.

## 2. Definitions

These terms are normative for this dissertation.

### 2.1 Persistence architecture

The full system that decides what survives a turn, how it is represented, how
it changes, how it is retrieved, how it is verified, and how it is deleted or
recovered. A database is one implementation detail inside this architecture.

### 2.2 Second brain

A durable cognitive substrate that accumulates a person's or agent's evidence,
knowledge, experience, preferences, decisions, and reusable procedures across
sessions. It must improve future work without requiring the model to rediscover
the same synthesis from raw history on every query.

This definition concerns persistence and compounding knowledge. It does not
require the persistence layer itself to be an autonomous conversational agent.

### 2.3 Active cognition

The transient inference performed by a model or agent: interpreting the current
task, planning, selecting tools, generating hypotheses, and producing actions.
Active cognition may read from and write proposals to SEAM, but model output is
not canonical evidence merely because a model produced it.

### 2.4 Canonical truth

Durable records whose identity, provenance, lifecycle, and integrity are
governed by explicit contracts. In SEAM, immutable RAW evidence and canonical
MIRL records occupy this plane. “Canonical” means authoritative within SEAM's
data model, not metaphysically true.

### 2.5 Derived knowledge

Rebuildable products generated from canonical records: indexes, knowledge-graph
topology, summaries, communities, observations, wiki pages, retrieval packs,
and lenses. Derived knowledge may be useful and readable without becoming a
second truth store.

### 2.6 Reasoning state

Public, inspectable records of objectives, evidence selection, verification,
accepted outcomes, rejected attempts, decision dependencies, and reusable
procedures. Reasoning state excludes hidden chain-of-thought and raw model
activations. It explains why an outcome was accepted; it is not independent
evidence that the outcome is true.

### 2.7 Proven

Demonstrated by versioned code, frozen inputs, exact configuration, per-case
outputs, auditable metrics, strong matched baselines, and reproducible artifacts.
A paper result or vendor table is evidence about its reported configuration. It
is not automatically proof of SEAM behavior or proof under a different model,
judge, corpus, token budget, or retrieval depth.

### 2.8 Most advanced

Pareto-leading across the required capability and operational axes without
hiding a regression behind an aggregate. A system does not qualify by winning a
single recall benchmark while losing temporal correctness, cost, provenance,
deletion safety, or agentic task success.

## 3. The persistence stack SEAM must own

### 3.1 Evidence layer: immutable experience

RAW preserves the exact source: messages, documents, tool results, code, logs,
images, audio, and trajectories. It is append-only and provenance-first. It
must remain possible to identify the exact span, region, frame, or event that
supports a later claim.

This layer prevents the compounding system from becoming self-referential. A
derived summary may point to evidence; it may not become its own evidence merely
because it was written back into storage.

### 3.2 Canonical semantic layer: MIRL

MIRL represents entities, claims, events, relations, states, provenance, spans,
symbols, packs, and flows in a deterministic machine-readable form. It separates
meaning from original phrasing while retaining exact routes back to RAW.

Canonical memory must express uncertainty, source identity, temporal validity,
contradiction, correction, supersession, and soft deletion. New information
adds or reconciles records; it does not silently rewrite history.

### 3.3 Temporal and lifecycle layer

A durable second brain needs both current belief and historical belief. It must
answer:

- What is currently supported?
- What was believed at a prior time?
- Which evidence changed the state?
- Which records are stale, contradicted, superseded, or deleted?
- Can a correction be reversed and audited?

This requires explicit validity and lifecycle state, not timestamps attached to
otherwise timeless vector chunks.

### 3.4 Retrieval projections

Lexical indexes, semantic vectors, graph topology, temporal indexes, and entity
terms are disposable access paths over canonical memory. They must be versioned,
boundary-scoped, rebuildable, and detectable when stale or incomplete.

Retrieval is one coherent engine with one request snapshot and an inspectable
fusion trace. Each selected item must retain a path to canonical records and
evidence. A higher similarity score does not overrule trust, lifecycle, tenancy,
or temporal validity.

### 3.5 Compiled knowledge layer

This is where Karpathy's LLM Wiki belongs. SEAM should be able to compile
canonical memory into evolving, interlinked, readable artifacts such as entity
pages, topic pages, research syntheses, comparisons, decision pages, and
runbooks.

These artifacts should compound: new evidence updates the relevant synthesis,
surfaces contradictions, and strengthens or weakens existing conclusions. They
remain derived products with exact record and evidence backtraces, immutable
revisions, and deterministic eligibility gates.

A file-based wiki is one adapter for this layer. Graph products and structured
knowledge pools are other adapters. The persistence architecture should not
force every agent to use the same presentation.

### 3.6 Context and working-memory layer

PACK is the bounded, task-specific context delivered to active cognition. It
selects current evidence and derived products under explicit task, trust, time,
and token constraints. PACK is disposable and reproducible from canonical state.

The quality target is not maximum compression. It is maximum durable
intelligence per token, subject to semantic, provenance, temporal, and retrieval
non-regression gates.

### 3.7 Reasoning and procedural layer

SEAM's reasoning graph persists public justification: which objective was
pursued, which evidence was retrieved, which checks passed, why an outcome was
accepted, and how later evidence affects it. Verified successful structures may
be distilled into reusable procedures or reasoning recipes.

The bridge back into canonical knowledge is explicit and reviewed. An accepted
reasoning outcome may propose a MIRL claim; it does not silently create one.

This layer is how the second brain remembers not only **what** it knows but
**why**, **how it learned**, **what worked**, and **when reconsideration is
required**.

### 3.8 Governance and isolation layer

Every operation must carry principal, namespace, scope, and session identity as
appropriate. Admission, retrieval, promotion, correction, export, and deletion
must fail closed across those boundaries. Recovery must preserve canonical and
derived state together or clearly report divergence for repair.

Without this layer, the system may be an impressive personal prototype but it
is not a dependable shared or hosted persistence architecture.

## 4. What Karpathy's LLM Wiki contributes

Karpathy's April 2026 [LLM Wiki idea file](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)
defines three layers: immutable raw sources, an LLM-maintained Markdown wiki,
and a schema document that governs maintenance. Its essential insight is that
knowledge should be compiled and maintained once rather than rediscovered from
raw chunks on every query.

That insight matters. A persistence system should accumulate synthesis, links,
contradictions, and useful answers instead of acting as a stateless search
front-end over an ever-growing archive.

The idea file also defines valuable operational practices:

- ingest updates multiple relevant pages rather than adding one isolated chunk;
- query results can become durable derived pages;
- lint detects contradictions, staleness, orphans, missing links, and gaps;
- an index provides progressive disclosure before deeper file reads;
- a chronological log records the artifact's evolution; and
- Git provides human-readable revision history.

However, the idea file explicitly leaves implementation to the user's agent. It
does not define a canonical semantic record contract, transactional admission,
typed provenance, temporal validity, identity reconciliation, tenant isolation,
crash recovery, deletion semantics, or a benchmark suite. Its moderate-scale
claim is an observation, not a controlled evaluation.

SEAM should therefore **subsume, harden, and measure** the pattern:

| LLM Wiki concept | SEAM placement |
| --- | --- |
| immutable sources | RAW and exact SPAN provenance |
| generated wiki pages | derived graph products / compiled-knowledge adapter |
| schema instructions | MIRL contracts, lens recipes, admission policy |
| `index.md` | progressive-disclosure index over derived products |
| `log.md` | append-only lifecycle and reasoning events |
| wiki lint | integrity, contradiction, staleness, provenance, and orphan gates |
| Git revision history | immutable projection versions linked to canonical fingerprints |
| optional hybrid search | canonical retrieval orchestrator |

The result is not “RAG versus wiki.” It is canonical memory plus several
derived access and synthesis forms, selected by workload and measured under a
shared protocol.

## 5. What SEAM is not

SEAM is not one vector database. Vector rows are disposable retrieval
projections.

SEAM is not one knowledge graph. Graph topology is a versioned projection of
canonical MIRL.

SEAM is not a pile of chat summaries. Summaries are derived products that must
retain exact support.

SEAM is not hidden chain-of-thought storage. It preserves public reasoning
state, evidence, checks, outcomes, and procedures.

SEAM is not Ghost. Ghost may provide personality, conversation, planning,
tools, and proactive behavior over SEAM.

SEAM is not proven merely because its architecture is broader than a
competitor's. Every claimed advantage must survive matched evaluation.

## 6. Lessons from advanced persistence systems

The companion research report provides the detailed source matrix. The
architectural lessons to test are:

1. **Hierarchical control:** MemGPT/Letta treats context as tiered memory and
   lets the agent decide when to move information between tiers.
2. **Selective consolidation:** Mem0 extracts and reconciles salient facts,
   reducing answer context and latency relative to full-history prompting in
   its reported configuration.
3. **Temporal graph memory:** Zep/Graphiti emphasizes episodes, entities, facts,
   temporal validity, and hybrid graph retrieval.
4. **Agentic organization:** A-MEM creates linked notes whose attributes evolve
   as new memories arrive.
5. **Self-organizing scenes:** EverMemOS separates episodic traces, semantic
   consolidation, and reconstructive recollection.
6. **File-system memory controllers:** LongMemEval-V2's AgentRunbook-C stores
   trajectories as files and uses a scaffolded coding agent to gather evidence,
   outperforming its reported RAG baselines at higher latency.
7. **Memory as learned policy:** newer agentic-memory work treats store,
   retrieve, update, summarize, and discard operations as actions learned with
   task reward rather than fixed heuristics.

SEAM should not copy all mechanisms. It should expose clean seams that allow
matched adapters or policies to compete while canonical truth, provenance,
governance, and evaluation remain fixed.

## 7. The benchmark frontier

No single benchmark proves a second brain.

### 7.1 LoCoMo: conversational recall and reasoning

[LoCoMo](https://github.com/snap-research/locomo) remains useful for factual,
temporal, multi-hop, and open-domain questions across long multi-session
conversations. It is valuable for continuity with published memory systems and
for per-category diagnosis.

It is insufficient alone. Scores are highly dependent on answerer, judge,
retrieval depth, context budget, and prompt. Its small number of conversations
also makes it vulnerable to overfitting and aggregate masking.

### 7.2 LongMemEval: updates, abstention, and sustained interaction

[LongMemEval](https://github.com/xiaowu0162/LongMemEval) evaluates information
extraction, multi-session reasoning, temporal reasoning, knowledge updates, and
abstention across 500 questions. It provides a stronger test of changing memory
than a pure static recall set.

### 7.3 BEAM: degradation at one to ten million tokens

BEAM tests ten memory abilities at scales where full-context prompting is not a
practical escape hatch. The important result is the degradation curve from
smaller histories through 1M and 10M tokens, broken down by temporal reasoning,
event ordering, contradiction resolution, multi-session reasoning, preference
and instruction following, and abstention.

SEAM must report accuracy, retrieved tokens, ingest cost, query latency, and
storage growth at each tier. A flat token budget with collapsing temporal
accuracy is not success.

### 7.4 EverMemBench: evolving, interleaved, multi-party memory

[EverMemBench](https://arxiv.org/abs/2602.01313) introduces multi-party and
multi-group conversations exceeding one million tokens, with evolving
information, interleaved topics, and role-specific personas. It is relevant to
identity resolution, temporal updates, and isolation between overlapping social
contexts.

### 7.5 MemoryArena: memory that changes future action

[MemoryArena](https://arxiv.org/abs/2602.16313) tests interdependent,
multi-session agent-environment tasks across web navigation, constrained
planning, progressive information search, and formal reasoning. It exposes the
gap between remembering an answer and using experience to complete later work.

SEAM's reasoning recipes and experience memory should be evaluated here under
the same agent, model, tools, and task order, with only the persistence policy
changed.

### 7.6 LongMemEval-V2: becoming an experienced operator

[LongMemEval-V2](https://arxiv.org/abs/2605.12493) evaluates static state,
dynamic state, workflows, environment gotchas, and premise awareness over up to
500 multimodal web-agent trajectories and roughly 115M tokens. Its `Insert` and
`Query` interface, fixed reader, bounded returned context, answer accuracy, and
latency are directly relevant to a memory runtime.

It also supplies a serious compiled-file baseline: AgentRunbook-C packages
manifests, workflow guidance, helper tools, and raw trajectories for a coding
agent to inspect. This is the benchmarked relative of Karpathy's unbenchmarked
wiki pattern.

### 7.7 EMemBench: interactive multimodal episodic memory

[EMemBench](https://arxiv.org/abs/2601.16690) generates verifiable questions
from an agent's own text and visual game trajectories. It covers recall,
induction, temporal, spatial, logical, and adversarial memory. It is the right
direction for testing whether SEAM's multimodal evidence contracts improve
future interaction rather than merely preserve bytes.

### 7.8 HaluMem: operation-level memory correctness

[HaluMem](https://github.com/MemTensor/HaluMem) tests the memory-writing side:
whether extraction and updates preserve supported facts without hallucinating,
omitting, duplicating, or corrupting them. This is a necessary counterweight to
end-to-end question answering, where a strong answerer can sometimes recover
despite a defective memory or conceal how the stored state became wrong.

SEAM should evaluate compile/admission and retrieval/answering separately, then
report the composed result. A high final QA score does not excuse a memory layer
that persistently invents or loses canonical facts.

### 7.9 SEAM-native invariant benchmarks

External suites do not sufficiently test provenance and operational safety.
SEAM therefore also needs public, generated, answer-keyed suites for:

- exact `PACK -> MIRL -> RAW` evidence closure;
- correction and supersession without historical erasure;
- current, historical, and point-in-time answers;
- source independence and prevention of derived self-citation;
- principal, namespace, and scope isolation;
- selective forgetting and authorized deletion;
- concurrent ingest and retrieval snapshot consistency;
- crash recovery and derived-index replay;
- deterministic rebuilds across SQLite, pgvector, and other adapters;
- malicious or contradictory source admission; and
- reasoning-promotion review and reversal.

These are conformance gates, not substitutes for usefulness benchmarks.

## 8. Required experimental arms

Every major benchmark should compare at least:

1. **No persistent memory** — current task context only.
2. **Full context** — where physically and economically possible.
3. **Lexical retrieval** — a strong BM25 baseline.
4. **Vector RAG** — fixed chunking, embedding, and top-k.
5. **Hybrid retrieval** — matched lexical/vector fusion.
6. **Compiled file/wiki** — maintained derived Markdown plus agentic search.
7. **SEAM canonical only** — MIRL retrieval without compiled products.
8. **SEAM compiled** — canonical memory plus derived knowledge/runbooks.
9. **SEAM full** — compiled knowledge, temporal graph, reasoning/procedural
   memory, and governed context assembly.
10. **Named external systems** — only where exact versions, permissions, cost,
    and compatible interfaces permit a matched run.

Component claims require ablations. If `SEAM full` wins, separate runs must
remove graph traversal, compiled knowledge, temporal policy, procedural memory,
and answer-policy changes one at a time. Otherwise the result proves a bundle,
not the claimed mechanism.

## 9. Evidence constitution

These rules govern every “advanced,” “better,” or “state of the art” claim.

### 9.1 Freeze the experiment

Record source commit, dependency locks, dataset hashes, split assignment,
prompts, model and revision, embedding model, answerer, judge, retrieval depth,
context budget, random seed, hardware class, and environment-affecting flags.

### 9.2 Isolate the changed variable

Use pristine, independently cloned stores for each arm. Keep the agent, model,
tools, task order, answerer, judge, and budgets fixed unless the experiment is
explicitly a system-level comparison. Label system-level and representation
ablations separately.

### 9.3 Preserve per-case evidence

Retain every input identity, retrieved record identity, ranking trace, packed
context fingerprint, generated answer, metric, judge output, token count,
latency, and failure. Publish what licensing permits and hash the rest.

### 9.4 Report the whole shape

Report per-category scores, confidence intervals or repeated-run variation,
failure counts, abstentions, empty answers, timeouts, cost, ingest time, query
latency, retrieved tokens, storage growth, and index rebuild cost. Averages do
not erase a failed category.

### 9.5 Keep scales separate

Do not compare scores produced by different judges or prompts as if they share
one scale. Do not mix provider-free retrieval recall with paid answer quality.
Do not call a synthetic conformance fixture a competitor benchmark. Do not call
a native/event-only parity run a graph-value win.

### 9.6 Require reproduction tiers

- **R0 — claimed:** prose or table without runnable artifacts.
- **R1 — inspectable:** code and configuration are public.
- **R2 — internally reproduced:** SEAM operators reran the exact configuration.
- **R3 — matched reproduced:** multiple systems ran under SEAM's frozen harness.
- **R4 — independent:** an external party reproduced the artifact and aggregate.

“Proven against competitors” requires at least R3. “Independently proven”
requires R4.

An independent normalized rerun is stronger evidence than unrelated vendor
headlines even when its absolute scores are lower. Conversely, if a published
README aggregate disagrees with committed per-case artifacts, the artifact
aggregate governs until the discrepancy is explained and a corrected immutable
run is released.

### 9.7 Protect holdouts

Development cases may select policies. Holdout cases may validate a frozen
candidate. A failed holdout informs a new candidate but cannot be repeatedly
tuned until it becomes development data. Publication sets and external private
fixtures remain operator-gated.

## 10. Definition of benchmark-proven second-brain readiness

SEAM may claim **benchmark-proven second-brain persistence** only when all of
the following are current on the same release candidate:

1. External recall and update suites pass declared non-regression gates.
2. BEAM reports a competitive 1M-to-10M degradation curve under fixed budgets.
3. MemoryArena shows that persistence improves later task success over matched
   no-memory and retrieval-only baselines.
4. LongMemEval-V2 shows competitive experience retrieval and workflow/gotcha
   retention within declared latency and context budgets.
5. A compiled-wiki/runbook arm proves whether compounding derived knowledge adds
   value beyond canonical retrieval.
6. Temporal, provenance, lifecycle, recovery, and tenancy conformance suites
   pass exactly.
7. At least one external system comparison reaches reproduction tier R3.
8. Every promoted mechanism has an attributable ablation or is described only
   as part of a system-level bundle.
9. The complete artifacts satisfy SEAM's benchmark integrity and secret/privacy
   gates.
10. Known failures and non-comparable results remain visible beside wins.

Until then, the truthful claim is narrower: SEAM implements a sophisticated
second-brain persistence architecture with specific verified results, while
frontier-wide superiority remains an open empirical program.

## 11. Recommended build and proof sequence

### Stage A — Freeze the comparison contract

Add versioned benchmark adapters and manifests for LongMemEval, BEAM,
EverMemBench, MemoryArena, LongMemEval-V2, and EMemBench. Make dataset
availability, licensing, expected provider calls, model requirements, and cost
explicit before any paid run.

**Completion criterion:** every suite can dry-run, validate its corpus, estimate
cost, and emit a frozen no-call manifest.

### Stage B — Implement compiled knowledge as a derived adapter

Generate versioned Markdown or equivalent structured pages from canonical MIRL.
Every sentence or field retains exact supporting record and evidence IDs. New
evidence produces a new immutable projection version. Lint detects stale,
contradictory, unsupported, orphaned, and self-citing products.

**Completion criterion:** deterministic rebuild, exact provenance closure,
current/history views, and no derived artifact admitted as independent evidence.

### Stage C — Implement experience and runbook memory

Persist state transitions, failed attempts, successful procedures, environment
gotchas, and verification outcomes. Provide progressive disclosure: manifests
and compact procedures first, exact trajectories and evidence on demand.

**Completion criterion:** fixed `Insert`/`Query` interface passes SEAM-native
workflow, update, premise-awareness, and abstention fixtures.

### Stage D — Run provider-free and local gates

Run conformance, retrieval, deterministic replay, scale smoke, and open-model
answering where possible. Reject mechanisms that cannot pass exact provenance
and lifecycle gates regardless of usefulness score.

**Completion criterion:** reproducible R2 artifacts with zero silent skips and
all failures retained.

### Stage E — Run matched frontier evaluations

After explicit cost approval, run frozen SEAM arms and permitted external
systems with the same answerer, judge, task sequence, budgets, and pristine
stores. Publish per-case artifacts or license-compatible hashes.

**Completion criterion:** at least one full R3 comparison plus component
ablations and uncertainty analysis.

### Stage F — Independent reproduction

Package the harness, manifests, public fixtures, expected hashes, and one-command
verification path for an external evaluator.

**Completion criterion:** R4 reproduction of at least one major external suite
and all SEAM-native conformance gates.

## 12. Propositions requiring consensus

**P1. Product identity.** SEAM is the second brain's persistence architecture;
Ghost or another agent is an active-cognition and user-experience adapter.

**P2. Canonicality.** RAW and MIRL are canonical. Vectors, graph topology,
summaries, wiki pages, runbooks, PACK, and lenses are versioned, rebuildable
projections.

**P3. Compounding knowledge.** SEAM must maintain derived synthesis across
ingests so valuable organization and reasoning are not rediscovered from raw
history on every query.

**P4. Karpathy relationship.** The LLM Wiki is a useful compiled-knowledge
pattern that SEAM should subsume as a derived adapter; it is not a separate
second brain and not sufficient proof of a persistence architecture.

**P5. Reasoning boundary.** SEAM persists public justification, verification,
decisions, and reusable procedures while excluding hidden chain-of-thought and
preventing automatic promotion into canonical truth.

**P6. Retrieval boundary.** One coherent retrieval engine may combine lexical,
vector, graph, temporal, and compiled-product evidence, but trust, lifecycle,
time, provenance, and principal scope gate relevance scores.

**P7. Governance.** Principal identity, namespace/scope isolation, correction,
deletion, crash recovery, and deterministic migration are defining properties
of advanced persistence rather than later deployment polish.

**P8. Benchmark portfolio.** LoCoMo alone cannot prove the target. The minimum
frontier portfolio includes recall/update, scale, agentic action, experience
reuse, multimodal episodic memory, and SEAM-native provenance/operations gates.

**P9. Comparability.** Scores with different models, judges, prompts, budgets,
or task scopes remain separate unless a matched rerun establishes comparability.

**P10. Mechanism attribution.** A system-level win proves the bundle. A claim
about graphs, compiled knowledge, temporal policy, or procedural memory requires
a matched ablation of that mechanism.

**P11. Proof threshold.** Competitor superiority requires R3 matched
reproduction; independent proof requires R4.

**P12. Honest present claim.** Before the full portfolio passes on one release
candidate, SEAM may claim advanced implemented architecture and named verified
results, but not universal state of the art.

## 13. Required Claude and Grok response

Each reviewer should return exactly these sections:

```markdown
# Reviewer and model

## Proposition verdicts
| Proposition | Verdict | Evidence or replacement wording |
| --- | --- | --- |
| P1 | ACCEPT / REVISE / REJECT | ... |
...
| P12 | ACCEPT / REVISE / REJECT | ... |

## Missing architecture
- Only capabilities absent from the proposed stack.

## Missing proof
- Only experiments required before the stated claim is justified.

## Strongest falsifier
- The single result that would most strongly disprove the central thesis.

## Recommended first experiment
- One bounded experiment, changed variable, baselines, metrics, and stop rule.

## Final position
CONSENSUS-READY / REVISION-REQUIRED / THESIS-REJECTED
```

Reviewers should cite a repo path, primary source, runnable reproducer, or
specific logical contradiction for every `REVISE` or `REJECT` verdict.

## 14. Conclusion

SEAM's ambition is larger than durable chat recall and more disciplined than an
LLM-maintained notebook. It is a persistence architecture for compounding
intelligence: exact evidence, canonical meaning, temporal truth, derived
knowledge, efficient context, and inspectable reasoning state.

Karpathy's LLM Wiki clarifies why compiled knowledge matters. Newer benchmark
work clarifies why compilation alone is not enough. The best system must remember
facts, updates, procedures, failures, decisions, and evidence; use those memories
to improve future action; remain correct as truth changes; operate at large
history scale; and preserve provenance, recovery, deletion, and isolation.

The architecture is credible. The supremacy claim is not granted by design.
SEAM must earn it through the evidence constitution above.

## Evidence manifest

Raw artifacts: none
