# Status Stream: Benchmarks

> LoCoMo, WANDR, BEAM, harness, integrity levels, and recorded audits

_Source of truth for current state in this area. History lives in `HISTORY.md`._

## Stable

- External memory benchmark registry + `seam bench external` CLI alias.
- LoCoMo adapter with quickstart fixture: `seam bench external --quickstart locomo`,
  `--adapter {seam|mem0|zep}`.
- Dataset dry-run routing for `locomo|longmemeval|beam`; mem0 harness adapter contract.
- Benchmark Integrity Level Phase 1: `seam bench seal|verify|inspect`, BIL-0
  inspection plus BIL-1/BIL-2 sealing.
- Benchmark diff/gate tooling, publish-only holdout fixture routing, tracked CI.
- `seam benchmark diff <a> <b>` before claiming improvement; `seam benchmark gate`
  before merge/release.

## WANDR replay lane (landed 2026-07-30)

Non-official, zero-network. `benchmarks/external/wandr/` with hash-pinned synthetic
corpus. Provider/network/cost counters asserted at zero; runner exits non-zero if
any is non-zero. Native (`mix`) vs event-only (`hybrid`) ablation currently reports
**parity at a 1.0 ceiling** — mechanism evidence only, not graph lift in either
direction. The S0 hardening pass now pins hash embeddings, disables environment
extractors, canonicalizes source identity through one URL contract, resets every
lane before ingest, rejects incomplete replay rows and noncanonical stored
references, and fails closed on any attempted network fetch. Upstream's official
path is networked and paid and must not be run.

Corpus must be hardened (distractors, cross-member entity collisions, multi-source
joins) before the ablation can discriminate.

The local relation-extraction qualification lane remains research-only and
scorer-ineligible. A precision verdict now requires at least 50 sampled labels;
smaller perfect-looking samples return `insufficient_evidence`. This changes the
admission evidence contract, not the measured 27/419 coverage or graph-lift
status.

## Recorded audits

- `docs/audits/2026-05-31-cat4-single-hop-attribution.md`
- `docs/audits/2026-06-01-semantic-recovery-policy-experiment.md`
- `docs/audits/2026-06-01-paid-locomo-slice-validation.md`
- `docs/audits/2026-05-28-locomo-retrieval-memory.md`

## Hard rule

No paid benchmark run — including small smokes — without explicit operator approval.
