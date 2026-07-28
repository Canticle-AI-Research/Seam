# Retrieval Orchestrator

This is SEAM's active retrieval-planning layer for machine-first memory.

Purpose:

- classify a request as structured, semantic, or mixed retrieval
- build a retrieval plan before search runs
- execute canonical SQLite retrieval plus derived semantic retrieval
- normalize results into a consistent SEAM candidate shape
- rank-normalize, fuse, and optionally trace the run for glassbox inspection

Architecture stance:

- SQLite remains the canonical source of truth
- vector indexes, including Chroma, are derived retrieval layers
- retrieval output should stay traceable back to canonical records and exact payloads
- the public Python SDK is the stable integration boundary; CLI, REST, MCP, and
  framework adapters should stay thin over it
- graph retrieval remains a projection over canonical RAW/MIRL, never a second
  truth store

Current implementation:

- `planner.py` classifies requests and extracts lightweight filters such as `kind:CLM` or `scope:thread`
- `adapters.py` runs a structured SQLite leg and a semantic vector leg against the live SEAM runtime
- the SQLite leg pushes field filters, lexical gating, and ranking into SQL instead of relying on a weak in-memory pass
- `adapters.py` also includes an optional `ChromaSemanticAdapter` for a Chroma-backed semantic leg
- `merger.py` applies versioned reciprocal-rank fusion across incompatible raw
  leg-score domains
- `orchestrator.py` exposes `RetrievalOrchestrator.plan()`,
  `RetrievalOrchestrator.search()`, and the bounded decision trace used by R2
- `orchestrator.py` also exposes persistent index syncing plus `rag()` context retrieval that can feed `pack`, `prompt`, `evidence`, `summary`, or exact `records` views

Compatibility:

- the canonical package path is `seam_runtime.retrieval_orchestrator`
- the legacy class names `HybridOrchestrator`, `HybridSearchResult`, and `HybridCandidate` remain as aliases

Current qualification boundary:

1. `reciprocal-rank-fusion/2` is fixed and fingerprinted in new R2 decisions.
2. Graph paths, visible episode backtraces, graph time views, and per-leg/total
   latency are explicit.
3. `python -m tools.graph_retrieval_qualification` runs the provider-free
   corpus/query-shape fixture.
4. Entity/value/agent/symbol vectors and real-corpus quality qualification
   remain before G3 can be called complete.
