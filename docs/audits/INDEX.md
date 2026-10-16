---
schema: seam-audit-registry/v1
latest: 2026-10-16-protocol-retrospective
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
| 2026-10-16 | [Two-week protocol retrospective](2026-10-16-protocol-retrospective.md) | 15 merged PRs, chronology enforcement, corrected current records and explicit historical gaps | `HISTORY#685` |
| 2026-10-14 | [Branch recovery closeout](2026-10-14-branch-recovery-closeout.md) | admitted source/live website,15 verified retirements and15 retained exact tips | `HISTORY#675` |
| 2026-10-14 | [Factual documentation recovery](2026-10-14-factual-doc-recovery.md) | PR277/278 current facts, fail-closed glossary/wiki and successor package qualification | `HISTORY#674` |
| 2026-10-14 | [Verified branch retirement and active lock qualification](2026-10-14-branch-retirement-and-lock.md) | main admission, 11 exact original-tip retirements and narrow urllib3 lock update | `HISTORY#673` |
| 2026-10-14 | [Branch CI validation repair](2026-10-14-branch-ci-validation-repair.md) | job-context validation and corrected exact-state test references | `HISTORY#671` |
| 2026-10-14 | [Exhaustive branch recovery](2026-10-14-branch-recovery.md) | 30 exact branch tips, semantic preservation and ordered integration | `HISTORY#670` |
| 2026-10-14 | [Suite release-candidate readiness](2026-10-14-suite-release-readiness.md) | default install, exact archives, prerelease/MCP controls and verified branch cleanup | `HISTORY#668` |
| 2026-10-14 | [Current Suite licensing reconciliation](2026-10-14-licensing-reconciliation.md) | first-launch terms, current implementation membership and package metadata | `HISTORY#665` |
| 2026-09-14 | [Claude.ai subscription benchmark transport verification](2026-09-14-claude-code-benchmarks.md) | subscription transport, bounded real smoke and failure accounting | `HISTORY#646` |
| 2026-09-06 | [L1 packaging and SDK migration preparation](2026-09-06-l1-packaging-migration.md) | package/source/ownership map and scoped artifact evidence | `HISTORY#635` |
| 2026-08-29 | [Full-repository audit](2026-08-29-full-repo-audit.md) | whole-repo health audit | `HISTORY#632` |
| 2026-08-19 | [Track S S6 principal-tenancy threat-model delta](2026-08-19-track-s-s6-principal-tenancy-threat-model.md) | security / tenancy / deletion | `HISTORY#575` |
| 2026-08-18 | [SEAM second-brain persistence dissertation](2026-08-18-seam-second-brain-persistence-dissertation.md) | recovered verbatim historical architecture research; not newly qualified | `HISTORY#571` |
| 2026-08-18 | [Advanced agent persistence layers](2026-08-18-advanced-agent-persistence-layers.md) | recovered verbatim historical comparative research; not newly qualified | `HISTORY#571` |
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

## Verbatim recovered historical research

The following authored reports are restored from PR #221, exact tip
`d69994491fef91abd4220016d64e322b0d106c11`. They retain their original text,
including historical comparisons and proposed experiments. Their claims are
not newly validated by the branch audit. Preservation evidence is recorded in
the October 14 branch-recovery report; current contracts remain authoritative.
