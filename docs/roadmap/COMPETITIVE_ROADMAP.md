# SEAM Competitive Roadmap

**Status:** Active strategic planning document. Added 2026-05-20.
**Track:** M — Competitive Position & Market Entry.
**Roadmap stream items:** `roadmap:track:M` and sub-items.

Priority order: what must exist first for anything downstream to matter.
Each item states what it unblocks. Nothing ships to users until P0 is validated.

---

## P0 — Standard Benchmark Integration (BLOCKS EVERYTHING)

The whole benchmark suite exists to run the actual LoCoMo, LongMemEval, and BEAM
evaluations — not as a replacement for them. Internal benchmarks validate engineering
correctness. Standard benchmarks validate competitive position. These are different things.

### P0.1 — Wire SEAM into mem0's open-source benchmark harness

**What:** Clone `github.com/mem0ai/memory-benchmarks`. Implement a SEAM adapter that
exposes `add()` and `search()` through the same interface the harness expects. This means
SEAM's retrieval interface must accept a query string and return ranked memory results in
the format the harness scores against.

**Why first:** Every other priority — marketing, integrations, MCP registry, migration
tools — depends on having a public number. Without a LoCoMo score run on the standard
harness, SEAM has no credible way to enter the conversation. Mem0's paper (arXiv
2504.19413) reports LoCoMo LLM-as-judge ≈ 66.9% (mem0-graph ~+2%), judged by gpt-4o-mini;
independent re-evals land ~62%. Zep publishes temporal scores. MemMachine publishes 0.9169
under its own methodology. SEAM publishes nothing comparable yet. **Vendor numbers are NOT
apples-to-apples** (different answerer/judge/categories); the only defensible target is
mem0 run through SEAM's own harness with the answerer + judge held constant (see
`benchmarks/external/locomo/adapters/mem0.py` + the shared answerer wrapper). The "91.6"
this doc previously cited for mem0 was wrong — likely conflated with MemMachine's 0.9169.

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

**Differentiator to include:** Attach SEAM provenance trace to every benchmark answer. No
other system does this. The trace shows: raw input → MIRL record → retrieval path → answer
derivation. Even if the score is lower than mem0's, provenance-traced answers are a
fundamentally stronger claim.

### P0.2 — Run LoCoMo

**Dataset:** 1,540 questions, 50 long-term chat histories, 4 categories.
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
pipeline was specifically designed to win.

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

Only after P0 numbers exist and P1 gaps are addressed.

### P2.1 — pip install seam-memory

Three-line quickstart. SQLite default, zero external deps, no Docker, no config.

```python
import seam
seam.remember("I prefer dark mode and use vim keybindings")
result = seam.recall("What are my editor preferences?")
```

MIRL compilation, retrieval mode selection, and compression happen silently. Power features
behind `seam[advanced]` extras.

### P2.2 — seam serve (MCP server on registry)

`seam serve` starts MCP on stdio or HTTP. One command. Registers on the MCP registry for
discoverability. This makes SEAM work with Claude Code, Codex, Gemini CLI, OpenClaw,
Hermes, and every other MCP-speaking agent.

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

### P3.2 — Framework integrations (pick 3)

1. **LangGraph** — highest leverage, largest agent builder population
2. **OpenClaw** — 6 memory plugins already exist, direct competitive comparison possible
3. **One TypeScript framework** (Mastra or Vercel AI SDK) — covers the JS/TS agent builder
   segment

### P3.3 — Token efficiency benchmarking

Mem0 averages ~6,900 tokens per retrieval. Full-context approaches use 25,000+. Measure
SEAM's tokens-per-retrieval on the same datasets. MIRL compression should push this number
lower. If it does, publish. If it doesn't, the compression isn't delivering user-facing
value yet.

---

## P4 — Revenue Surface

### P4.1 — Enterprise provenance for regulated industries

Healthcare, legal, financial services need audit trails on AI memory. SEAM's provenance
chain is literally a compliance feature. Target: teams building AI agents in
HIPAA/SOC2/GDPR environments who need to prove what their agent "remembers" and where it
came from.

### P4.2 — Paid support tier

Open source core. Paid tier for: priority support, custom MIRL type definitions, deployment
consulting, SLA on consolidation engine performance.

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
| 2026-05-20 | Standard benchmarks (LoCoMo/LongMemEval/BEAM) are P0 | Internal benchmarks validate engineering. Standard benchmarks validate competitive position. Without public numbers on the same suites competitors use, SEAM cannot credibly enter the market. |
| 2026-05-20 | Engineering fixes sequenced AFTER benchmark runs, not before | Don't pre-optimize for problems you haven't measured. Let the benchmarks reveal the real gaps. |
| 2026-05-20 | Product surface (pip, MCP, imports) is P2, not P1 | Shipping a product that can't demonstrate competitive performance creates a first impression you can't undo. Numbers first, then distribution. |
