# SEAM Benchmark Log

This file tracks the historical performance of the SEAM runtime. All significant benchmark runs that involve architecture or model changes should be recorded here.

> **Verifiable run proofs:** for the specific validated LoCoMo runs (native
> judged holdout A/B and the mem0-harness competitive standing), with exact
> config, code provenance, reproduce commands, and record SHA-256 anchors, see
> [`RESULTS.md`](RESULTS.md).

## Storage Rule: Run Artifacts
- All benchmark run bundles are stored as JSON in `benchmarks/runs/`.
- Filename format: `YYYYMMDD_HHMMSS_[label]_projection.json`
- These artifacts contain full track traces, fixture summaries, and model metadata.

## Run History

| Date | Run ID | Git SHA | Family | Key Metric | Result | Model |
|------|--------|---------|--------|------------|--------|-------|
| 2026-04-17 | `bench:72814a1d67c5` | `6a8c49e` | retrieval | `machine_hybrid_recall` | 100% | `st:all-MiniLM-L6-v2` |
| 2026-04-17 | `bench:3aca820ceffc` | `6a8c49e` | retrieval | `machine_hybrid_recall` | 100% | `hash-bow-v1`* |

> [!NOTE]
> *Note: Hash-based embeddings achieved 100% hybrid recall but only 33% raw `machine_nat_query` recall. SBERT closed this gap to 100% across all tracks.*

## Comparative Analysis: Hash vs SBERT (2026-04-17)

| Track | Hash recall | SBERT recall | Delta |
|-------|-------------|--------------|-------|
| raw | 0.000 | 0.000 | = |
| vector | 0.889 | 1.000 | +0.111 |
| mirl | 1.000 | 1.000 | = |
| hybrid | 1.000 | 1.000 | = |
| machine_nat_query | 0.333 | 1.000 | +0.667 |
| machine_vector | 1.000 | 1.000 | = |
| machine_hybrid | 1.000 | 1.000 | = |
