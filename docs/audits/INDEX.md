---
schema: seam-audit-registry/v1
latest: 2026-08-19-track-s-s6-principal-tenancy-threat-model
policy_start: 2026-08-11
---

# SEAM Audit Registry

Canonical index of recorded SEAM reports. This directory is the durable,
tracked home for dated human-readable reports: whole-repository audits,
focused investigations, visual status reports, architecture assessments, and
interpreted benchmark reports. It contains no credentials, session URLs,
provider keys, or bulky raw artifacts. Reports cite repository evidence or
durable artifact paths and hashes; see
[Reports and Evidence](../REPORTS_AND_EVIDENCE.md). The `policy_start` field is
the prospective enforcement boundary: older reports retain their original
evidence contract, while reports dated on or after it must satisfy the current
registry and evidence-manifest rules.

**Newest first.** `scope` distinguishes a whole-repository health audit from a
narrow diagnostic. Whole-repo audits are the repeatable series and are expected
to be diffed against each other; the rest are one-off investigations kept for
the reasoning and measurements they record.

Add a new report at the top, advance `latest`, and link the latest governing
HISTORY entry for that report. Use
`docs/audits/<YYYY-MM-DD>-<short-slug>.md`.

| date | audit | scope | history |
| --- | --- | --- | --- |
| 2026-08-19 | [Track S S6 principal-tenancy threat-model delta](2026-08-19-track-s-s6-principal-tenancy-threat-model.md) | security / tenancy / deletion | `HISTORY#575` |
| 2026-08-18 | [Track S and deployment readiness audit](2026-08-18-track-s-deployment-readiness-audit.md) | Track S / surfaces / deployment | `HISTORY#571` |
| 2026-08-18 | [Graph benchmark readiness beyond LoCoMo](2026-08-18-graph-benchmark-readiness-research.md) | benchmark research | `HISTORY#571` |
| 2026-08-12 | [Full-repository audit](2026-08-12-full-repo-audit.md) | **whole-repo** | `HISTORY#560` |
| 2026-08-12 | [Complete project timeline](2026-08-12-seam-complete-timeline.md) | timeline | `HISTORY#560` |
| 2026-08-10 | [Track S visual status report](2026-08-10-track-s-visual-status-report.md) | status reconciliation | `HISTORY#553` |
| 2026-08-01 | [Full-repository audit](2026-08-01-full-repo-audit.md) | **whole-repo** | `HISTORY#525` |
| 2026-07-22 | [Parallel graph (G3→G4) and reasoning (R3) build](2026-07-22-graph-reasoning-parallel-build-architecture-task.md) | architecture task | — |
| 2026-07-21 | [Canonical graph fill preflight](2026-07-21-canonical-graph-fill-preflight.md) | graph | — |
| 2026-07-20 | [Memory competitor ratchet](2026-07-20-memory-competitor-ratchet.md) | competitors | — |
| 2026-07-20 | [LongMemEval / BEAM execution-contract repair](2026-07-20-longmemeval-beam-execution-contract.md) | benchmark | — |
| 2026-07-18 | [Mem0-harness cat1 non-count miss mining](2026-07-18-mem0-cat1-noncount-miss-mining.md) | retrieval | — |
| 2026-07-15 | [Champion problem scan (0.7689)](2026-07-15-champion-problem-scan.md) | retrieval | — |
| 2026-07-15 | [cat1/cat3 closeout: c4 negative + mem0 scoreboard](2026-07-15-c4-and-mem0-cat13-score.md) | benchmark | — |
| 2026-07-14 | [Per-case review of the #390 record](2026-07-14-post-temporal-per-case-review.md) | retrieval | — |
| 2026-07-11 | [cat1/cat3 private offline adjudication](2026-07-11-cat13-private-offline-adjudication.md) | benchmark | — |
| 2026-07-11 | [cat1/cat3 judge/2 paid replay](2026-07-11-cat13-judge2-paid-rejudge.md) | benchmark | — |
| 2026-07-08 | [cat1/cat3 generation-side paid confirmation](2026-07-08-cat13-generation-side-paid-confirmation.md) | benchmark | — |
| 2026-07-07 | [SQLiteVectorIndex full-scan search design](2026-07-07-sqlite-vector-scan-design-task.md) | design task | — |
| 2026-06-17 | [cat1 coreference + entity-aggregation blueprint](2026-06-17-cat1-coreference-graphrag-blueprint.md) | retrieval | — |
| 2026-06-15 | [Entity-aggregation retrieval (cat1)](2026-06-15-entity-aggregation-retrieval.md) | retrieval | — |
| 2026-06-15 | [cat1/cat3 multi-hop retrieval scope](2026-06-15-cat1-cat3-multihop-scope.md) | retrieval | — |
| 2026-06-12 | [MIRL compilation fidelity contract](2026-06-12-mirl-compile-fidelity.md) | compile | — |
| 2026-06-01 | [Semantic recovery policy experiment](2026-06-01-semantic-recovery-policy-experiment.md) | retrieval | — |
| 2026-06-01 | [Paid LoCoMo slice validation](2026-06-01-paid-locomo-slice-validation.md) | benchmark | — |
| 2026-05-31 | [cat4 single-hop miss attribution](2026-05-31-cat4-single-hop-attribution.md) | retrieval | — |
| 2026-05-28 | [LoCoMo / retrieval / memory audit](2026-05-28-locomo-retrieval-memory.md) | retrieval | — |
| 2026-05-28 | [Deep health audit](2026-05-28-deep-health-audit.md) | **whole-repo** | — |

## Running a whole-repo audit

Use the `/deep-audit` skill (`~/.claude/skills/deep-audit/`). It is read-only by
construction, fans out parallel lanes (architecture, correctness, persistence,
security, tests/CI, doc drift), and independently re-verifies every candidate
finding before reporting. File the result as
`docs/audits/<YYYY-MM-DD>-full-repo-audit.md`, add a row above, advance
`latest`, and record the HISTORY entry.

## What belongs in an audit record

- Every finding with **file:line evidence** and a concrete failure scenario.
- The **verification checklist** — what was run, including clean results and
  what could not be verified. An audit without this is an opinion.
- **Corrections to prior belief**, so a later reader does not re-derive a claim
  that was already falsified.
- An **Evidence manifest** declaring `Raw artifacts: none` or pairing every raw
  artifact path with its SHA-256 digest. This is enforced prospectively from
  the registry's `policy_start`; older reports are not rewritten retroactively.
- **Never** a credential, DSN with a password, provider session URL, or any
  copy-pasteable exploit payload. Describe a vulnerability precisely enough to
  fix; do not weaponize it. Repository rule, per `AGENTS.md` Security Rules.
