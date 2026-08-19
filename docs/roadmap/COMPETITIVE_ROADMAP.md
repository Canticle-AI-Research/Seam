# SEAM Competitive Roadmap

**Status:** Active strategic planning document. Added 2026-05-20.
**Track:** M — Competitive Position & Market Entry.
**Roadmap stream items:** `roadmap:track:M` and sub-items.

Priority order: what must exist first for anything downstream to matter.
Each item states what it unblocks. No new competitive positioning or benchmark-
based market claim ships until P0 is validated; existing releases are not P0
evidence.

## Positioning evidence (2026-07-18 snapshot; reconciled 2026-08-18)

This section preserves the July harness results as dated evidence, not as a
current market inventory or a universal superiority claim. Several memory
systems combine vector retrieval with graph, temporal, or other signals, and
the configurations below were not all matched on extraction, retrieval depth,
provider version, cost, or latency.

SEAM implements a versioned hybrid retrieval path over lexical, semantic,
graph, and temporal signals with provenance traces. Current LoCoMo, WANDR, and
G7/R6 evidence does not show graph-caused competitive lift. The governing claim
boundary and required matched causal portfolio are recorded in
`../audits/2026-08-18-graph-benchmark-readiness-research.md`.

### Historical field notes (not a matched comparison)

| Provider | Retrieval note at the snapshot | Extraction | Storage | Reported or observed LoCoMo |
|---|---|---|---|---|
| **Mem0** | Vector (semantic-only, LLM-ranked) | Paid LLM per message | Cloud (Qdrant/Weaviate) | ~66.9% paper / ~62% independent |
| **Zep** | Vector + graph edges | Paid LLM | Cloud (Zep) | No public LoCoMo; in-harness 0.5249 |
| **MemMachine** | Vector (semantic-only) | LLM extraction | Cloud | ~91.6% (own methodology, not comparable) |
| **Mnemosyne** | Vector (semantic-only) | None (raw text) | Local SQLite | Not published |
| **SEAM** | **Hybrid** (lexical + semantic + graph + temporal) | **Local MIRL** (no LLM) | **Local SQLite** | **88.1% historical internal run** (mem0 harness; unmatched retrieval depth) |

### Historical harness evidence

In SEAM's own harness, the answerer, judge, and 344 holdout cases were held
constant across adapters. Retrieval budgets and the systems' extraction and
service paths were not fully matched, so this is a dated system result rather
than R3-tier causal or efficiency evidence:

| System | Aggregate | Cat1 Multi-hop | Cat2 Temporal | Cat3 Open-domain | Cat4 Single-hop |
|---|---|---|---|---|---|
| **SEAM** | **0.6991** | **0.5410** | **0.6149** | **0.5238** | **0.8021** |
| Zep | 0.5249 | 0.4250 | 0.2500 | 0.4048 | 0.6791 |
| Mem0 | 0.0913 | 0.1441 | 0.0068 | 0.2381 | 0.0917 |

In Mem0's own harness (lenient binary judge, gpt-4o-mini, top-200):

| System | Cat1 Multi-hop | Cat3 Open-domain | Combined |
|---|---|---|---|
| Mem0 (arXiv:2504.19413 Table 1) | 51.15% | 72.93% | — |
| **SEAM** | **88.7%** | **86.5%** | **88.1%** (333/378) |

SEAM's result is numerically higher on both displayed metrics (open-domain
+13.6 points, multi-hop +37.6 points). The earlier
reading of this table — "matches on theirs, multi-hop -2.7 pts" — was derived
from a 91.3% Mem0 multi-hop figure that is not in the paper; see
`../kb/memory-systems/mem0.md`. Qualification: SEAM ran top_k=200 against the
paper's 10, so the result is not retrieval-depth matched. It establishes the
historical SEAM result under that configuration, not universal, graph-specific,
or efficiency superiority over Mem0 or the wider market.

### Working product thesis, not a benchmark conclusion

SEAM aims to differentiate through local-first canonical memory, hybrid
retrieval, and inspectable provenance. Whether that architecture is more
accurate or efficient than a named alternative must be established at the
exact tested scope with matched quality, latency, token, cost, and storage
evidence. Framework adapters expose the architecture; they do not prove the
competitive claim.

---

## P0 — Standard Benchmark Integration (BLOCKS EVERYTHING)

The benchmark suite exists to run standard evaluations, not replace them with
internal fixtures. LoCoMo, LongMemEval, and BEAM remain memory-quality and
scale lanes. Graph claims additionally require native conformance,
GraphRAG-Bench, STaRK, Memora/FAMA, LongMemEval-V2, and MemoryArena under the
2026-08-18 causal contract. Internal benchmarks validate engineering
correctness; matched standard benchmarks qualify a scoped competitive claim.

### P0.1 — Wire SEAM into mem0's open-source benchmark harness

**What:** Clone `github.com/mem0ai/memory-benchmarks`. Implement a SEAM adapter that
exposes `add()` and `search()` through the same interface the harness expects. This means
SEAM's retrieval interface must accept a query string and return ranked memory results in
the format the harness scores against.

**Why first:** Every other priority — marketing, integrations, MCP registry, migration
tools — depends on having a reproducible public comparison. Without matched,
sealed benchmark evidence, SEAM has no credible way to enter the conversation. Mem0's paper (arXiv
2504.19413) reports LoCoMo LLM-as-judge ≈ 66.9% (mem0-graph ~+2%), judged by gpt-4o-mini;
independent re-evals land ~62%. Zep publishes temporal scores. MemMachine publishes 0.9169
under its own methodology. SEAM's historical runs above are not a fully matched
competitive publication. **Vendor numbers are NOT apples-to-apples** (different
answerer/judge/categories); one defensible lane is Mem0 run through SEAM's own
harness with the answerer, judge, cases, retrieval/context budgets, and scorer
held constant (see `benchmarks/external/locomo/adapters/mem0.py` + the shared
answerer wrapper). The broader graph claim additionally requires the causal
portfolio in the 2026-08-18 graph-readiness report. The "91.6" this doc
previously cited for mem0 was wrong — likely conflated with MemMachine's 0.9169.

**Engineering prerequisite check:**
- [ ] Can `seam.recall(query)` return ranked results with scores right now?
- [ ] Can `seam.remember(messages)` ingest a conversation history in the format LoCoMo
      provides (multi-turn dialogue)?
- [ ] Is SQLite retrieval (vector + any hybrid signals) stable under the dataset size
      LoCoMo requires (~50 long conversations)?
- [ ] Is there a clean Python API entry point, or only CLI/REST/MCP?

If any of these are "no," that's the actual P0 engineering work — not the benchmark run
itself.

**Output:** Raw scores on LoCoMo (4 categories: single-hop, multi-hop, open-domain,
temporal) and LongMemEval (5 categories: information extraction, multi-session reasoning,
temporal reasoning, knowledge updates, abstention). Published with full methodology: which
embedding model, which LLM judge, which retrieval mode, exact SEAM version hash.

**Differentiator to include:** Attach a SEAM provenance trace to every benchmark
answer: raw input → MIRL record → retrieval path → selected answer evidence.
That makes the result more inspectable; it does not by itself make the score
better or establish that no competitor offers comparable tracing.

### P0.2 — Run LoCoMo

**Dataset:** the pinned 10-conversation corpus loads 1,542 answerable cases
(the four primary categories plus two answer-bearing category-5 rows).
**Scoring:** LLM-as-a-Judge (match mem0's methodology for direct comparison).
**Publish:** Per-category breakdown. Do not aggregate into a single number without showing
the components.

**What to watch for:**
- Temporal questions are where most systems bleed points. MIRL's timestamped records should
  help here — if retrieval actually uses timestamps during ranking.
- Multi-hop questions require combining information across multiple memories. This tests
  whether SEAM's retrieval returns the right *set* of memories, not just the single best
  match.
- Open-domain questions test abstention — knowing when the answer isn't in memory. False
  positives here (confidently wrong answers) are worse than low recall.

### P0.3 — Run LongMemEval

**Dataset:** 500 questions, 5 categories, multi-session with knowledge updates.
**Why separately:** LongMemEval tests knowledge updates and abstention, which LoCoMo does
not. If a user says "I moved to Berlin" after previously saying "I live in Tokyo," the
system must return Berlin and suppress Tokyo. This is where mem0's ADD/UPDATE/DELETE
pipeline is specifically designed to handle update/delete workloads.

**SEAM's angle:** MIRL records with timestamps and provenance should handle this by
returning the most recent assertion with full lineage. If SEAM doesn't currently have an
update/supersession mechanism, this benchmark will expose it immediately — which is exactly
what you need to know before shipping.

### P0.4 — Run BEAM (1M track)

**Dataset:** 100 conversations up to 10M tokens, 2,000 probing questions, 10 memory
capability categories.
**Why:** This is where the market is going. LoCoMo tops out at ~35 sessions. BEAM-1M tests
what happens when memory actually scales. Mem0 scores 64.1 here — well below their LoCoMo
numbers. An architecture with offline consolidation (`seam sleep`) should theoretically
perform better at scale because the search space has been refined. Prove or disprove that.

**Note:** BEAM-10M (mem0 scores 48.6) is aspirational for now. Run 1M first. If the
architecture holds, 10M is the long-term differentiator.

---

## P1 — Engineering Gaps Exposed by Benchmarks

These are the fixes that benchmark runs will likely surface. Sequence them as they appear
— don't pre-optimize for problems you haven't measured yet.

### P1.1 — Temporal retrieval ranking

If LoCoMo temporal scores are low: the retrieval layer needs to weight recency and temporal
ordering, not just semantic similarity. MIRL records already have timestamps — the question
is whether the ranking function uses them.

### P1.2 — Knowledge update / supersession handling

If LongMemEval knowledge-update scores are low: SEAM needs a mechanism where newer
assertions on the same entity/attribute suppress older ones at retrieval time. Not delete —
suppress. The old record stays (provenance), but retrieval returns the current state.

### P1.3 — Multi-hop retrieval

If LoCoMo multi-hop scores are low: single-query retrieval isn't enough. The system needs
to either retrieve broader context per query or do iterative retrieval (query → partial
answer → refined query → more memories). This is where consolidation helps long-term —
pre-linked memories reduce the need for multi-hop at query time.

### P1.4 — Abstention calibration

If LongMemEval abstention scores are low: the system is returning confident answers when
the memory store doesn't actually contain the information. This requires a confidence
threshold on retrieval — if no memory passes the threshold, return "unknown" instead of the
best-available guess.

---

## P2 — Ship the Product Surface

Treat this as new market-distribution work after P0 evidence and P1 gaps are
addressed. Existing product artifacts do not retroactively qualify P0.

### P2.1 — pip install seam-memory

Three-line quickstart. SQLite default, zero external deps, no Docker, no config.

```python
import seam
seam.remember("I prefer dark mode and use vim keybindings")
result = seam.recall("What are my editor preferences?")
```

MIRL compilation, retrieval mode selection, and compression happen silently. Power features
behind `seam[advanced]` extras.

### P2.2 — `seam mcp stdio` (MCP server on registry)

`seam mcp stdio` / `seam-mcp` starts the standards-compliant MCP JSON-RPC
server over stdio; `seam mcp serve` is the legacy JSON-lines bridge and
`seam serve` is the REST/WebUI server. Registry publication and each named
client remain separate compatibility and distribution proofs.

### P2.3 — seam trace (provenance as a feature)

`seam trace <memory_id>` shows complete lineage: raw input → MIRL compilation →
compression → every retrieval that touched this memory. Visual output in terminal. This is
the user-facing manifestation of the architectural advantage. Make it demoable in 30
seconds.

### P2.4 — seam import --from mem0

Read mem0 JSON exports. Wrap each memory in MIRL with `source: mem0-import` provenance.
Flag the provenance gap explicitly: "original input not available — memory was extracted by
mem0's lossy pipeline." Honesty about what's lost in the import is the marketing.

### P2.5 — seam import --from memory-md

Read MEMORY.md and USER.md files (the naive file-injection pattern). Parse into MIRL
records. This covers OpenClaw, Claude Code custom setups, and every team that built ad-hoc
memory on markdown files. Largest migration surface by user count.

---

## P3 — Differentiation Features

### P3.1 — seam sleep (offline consolidation engine)

The feature nobody else has. Offline batch process that:
- Promotes episodic MIRL records → semantic records (fact extraction across multiple
  episodes)
- Extracts procedural patterns as graph-structured MIRL types
- Resolves contradictions (flags or auto-resolves based on temporal ordering + provenance
  confidence)
- Compacts the retrieval index (fewer, higher-quality records = faster search + fewer
  tokens at query time)

Run BEAM-1M before and after consolidation. Publish the delta. If consolidation improves
BEAM scores, that's the headline result — it proves that memory systems need maintenance
cycles, not just accumulation.

Neuroscience grounding: hippocampal replay during sleep consolidates episodic memories into
neocortical semantic representations. SEAM sleep is the computational analog. Name it,
explain it, benchmark it.

### P3.2 — Framework integrations (three Python adapters)

Priority order defined 2026-07-18. Each adapter is a single-class integration
with a one-line-change pitch. All three prove adoption velocity by meeting the
dominant Python agent frameworks where they already wire memory.

#### P3.2.1 — LangGraph Extension (`seam-langgraph`)

**Method:** Custom `BaseCheckpointSaver` subclass.

**Pitch:** *"Swap your bulky SQL checkpointer for a local symbolic memory graph.
Change one line of code."*

**Why first:** LangGraph is the highest-volume Python agent framework. Every
LangGraph agent that uses checkpoints already imports a `CheckpointSaver` — a
SEAM saver drops into that exact slot. The `BaseCheckpointSaver` interface is
small and stable (`put`, `get_tuple`, `list`), so the adapter surface is
bounded. Each checkpoint write becomes a SEAM ingest; each checkpoint read
becomes a SEAM recall scoped to the thread's namespace. This gives LangGraph
agents persistent cross-turn memory without a Postgres or SQLite checkpoint
database — SEAM's MIRL graph replaces both the storage and the retrieval.

**Adoption signal:** A merged `seam-langgraph` package proves SEAM integrates
at the framework level, not just the application level. LangGraph's agent
builder population is the largest single pool of potential SEAM users.

#### P3.2.2 — CrewAI Wrapper (`seam-crewai`)

**Method:** Memory provider class implementing CrewAI's memory interface.

**Pitch:** *"Give your CrewAI agents instant, localized long-term memory without
API latency."*

**Why second:** CrewAI ships a pluggable memory provider contract. A SEAM
provider replaces their default in-process store with MIRL-backed persistent
memory. CrewAI's multi-agent orchestration means memory is shared across a crew
— SEAM's per-namespace scoping maps directly to crew/agent/task boundaries.
No API calls (Mem0 extracts per-message via OpenAI; SEAM compiles locally).

**Adoption signal:** CrewAI is the second-largest Python agent framework by
adoption. A `seam-crewai` package puts SEAM in front of every CrewAI user who
hits the limits of their default ephemeral memory.

#### P3.2.3 — AutoGen Hook (`seam-autogen`)

**Method:** Context-manager subclass that intercepts AutoGen conversation history
before it reaches the LLM context window.

**Pitch:** *"Compress AutoGen multi-agent chat history natively before it hits
your LLM context window."*

**Why third:** AutoGen 0.7+ uses a conversational context pipeline where
multi-agent chat history grows unbounded into the LLM prompt. A SEAM context
manager compresses that history by compiling raw conversation turns into MIRL
records, then injecting a compact memory summary instead of the full transcript.
This is SEAM's token-efficiency pitch applied at the framework level — fewer
tokens, lower cost, same agent performance. AutoGen's context-manager pattern
is a clean injection point that doesn't require forking the framework.

**Adoption signal:** AutoGen users feel context-window pressure acutely
(multi-agent chats grow fast). A `seam-autogen` package that demonstrably
cuts token usage while preserving task performance is a direct cost-savings
pitch — the kind of adoption driver that spreads through word of mouth.

#### P3.2.4 — OpenClaw Memory Backend (`seam-openclaw`)

**Method:** Custom memory plugin implementing OpenClaw's memory backend interface.

**Pitch:** *"Add SEAM as a provenance-traced, locally compiled memory option and
benchmark every plugin under the same workload."*

**Why fourth:** OpenClaw already has 6 memory plugins in its registry. Each one
is a direct competitive comparison point — SEAM can be benchmarked against every
existing plugin on the same workloads. OpenClaw's plugin architecture means a
SEAM backend is a drop-in that every OpenClaw user can try with zero code
changes. The historical 88.1% mem0-harness result does not transfer to this
plugin comparison; a listing must use a fresh matched run over the declared
plugin workload and disclose quality, latency, token, cost, and storage bounds.

**Adoption signal:** OpenClaw's memory plugin ecosystem is the densest
concentration of memory-system users. A SEAM plugin there is a direct
distribution channel to memory-conscious agent builders.

#### P3.2 — Deliverable contract

Each adapter ships as:
- One Python file (the adapter class), under 300 lines
- A `pyproject.toml` optional extra (`seam[langgraph]`, `seam[crewai]`,
  `seam[autogen]`, `seam[openclaw]`)
- A README with the one-line change and a 5-line quickstart
- Hermetic tests against the framework's interface (no live framework agent
  run required in CI)
- A measured quickstart: ingest N turns, recall, verify the round-trip

None of these adapters change SEAM core. Each is a thin wrapper over the
existing `SeamRuntime` API surface.

### P3.3 — Token efficiency benchmarking

Mem0 averages ~6,900 tokens per retrieval. Full-context approaches use 25,000+. Measure
SEAM's tokens-per-retrieval on the same datasets. MIRL compression should push this number
lower. If it does, publish. If it doesn't, the compression isn't delivering user-facing
value yet.

---

## P4 — Revenue Surface

### P4.1 — Enterprise provenance for regulated industries

Healthcare, legal, and financial-service teams often need audit trails on AI
memory. SEAM's provenance chain can support that auditability, but it is not by
itself evidence of HIPAA, SOC 2, GDPR, or product-level compliance. Any regulated
positioning requires a separate legal, security, deployment, and controls review.

### P4.2 — Paid support tier

Source-available core under BUSL-1.1 (free to self-host, converts to MPL-2.0
after four years). Paid tier for: priority support, custom MIRL type
definitions, deployment consulting, SLA on consolidation engine performance.

### P4.3 — Hosted consolidation service

For teams that want local storage but don't want to run the consolidation engine themselves.
SEAM data stays local (SQLite), but `seam sleep --cloud` sends anonymized MIRL records to
a consolidation endpoint and returns refined records. Preserves local-first while creating
a recurring revenue hook.

---

## Relationship to existing tracks

- **Track I** (done) — built the external benchmark registry and infrastructure
  (`seam bench external --quickstart locomo`). P0 consumes that infrastructure to run the
  full standard datasets for competitive publication.
- **Track K** — BIL sealing applies to P0 published results; P0 bundles should be sealed
  at the highest available BIL level at publish time.
- **Track J** — P3.3 token efficiency benchmarking uses the prompt codec layer for
  tokens-per-retrieval measurement.
- **Track L** — independent; skill-quality benchmarks live there, not here.

## Decision Log

| Date | Decision | Reason |
|------|----------|--------|
| 2026-08-18 | LoCoMo is a memory-quality lane, not sufficient graph-performance evidence | Current LoCoMo graph/non-graph arms are tied and graph-inert. Scoped top-level graph claims require the matched causal portfolio, sealed per-case and efficiency evidence, and independent reproduction defined by the graph-readiness report. |
| 2026-05-20 | Standard benchmarks (LoCoMo/LongMemEval/BEAM) are P0 | Internal benchmarks validate engineering. Standard benchmarks validate competitive position. Without public numbers on the same suites competitors use, SEAM cannot credibly enter the market. |
| 2026-05-20 | Engineering fixes sequenced AFTER benchmark runs, not before | Don't pre-optimize for problems you haven't measured. Let the benchmarks reveal the real gaps. |
| 2026-05-20 | Product surface (pip, MCP, imports) is P2, not P1 | Shipping a product that can't demonstrate competitive performance creates a first impression you can't undo. Numbers first, then distribution. |
