---
handoff_id: 2026-08-02-track-s-audit-recovery-locally-repaired
supersedes: 2026-08-01-track-s-s1-doctor-policy-corrected
handoff_status: current
history: HISTORY#526
---

# Track S audit recovery locally repaired

**Date:** 2026-08-02

**Branch:** `feat/track-s-s2-migration-spine`

**Base:** `origin/main@94375e8`

**Publication:** draft PR #193; protected `main` is unchanged

## Current state

The S2 spine plus the HISTORY#525 audit remediation form one local recovery
candidate. Audit findings 2-5 are repaired and independently reviewed. S2 is
locally requalified under a positive forward-projection migration gate; this is
not merge, release, or hosted-production evidence.

## Repairs

- Canonical entity reconciliation acquires `BEGIN IMMEDIATE` before its first
  identity read unless the caller already owns a transaction. Eight concurrent
  writes preserve one ENT and remap all eight claims to it.
- Both chat endpoints share one credential resolver. Only the exact environment
  key bound to a built-in provider host may resolve; custom hosts require an
  explicit caller-owned key, and loopback always uses the local placeholder.
- Projection transitions declare exact versions and source/target table sets.
  One exclusive owner reruns authoritative preflight, creates a validated and
  durably published same-owner backup, and retains writer exclusion across
  separately committed, resumable steps. Callback and failure-hook facades deny
  transaction, authorizer, journal, and locking control through supported APIs.
- Malformed or incomparable trust timestamps emit no timestamp content and
  fail toward expired/stale.

## Accidental-push reconciliation

- The recovery branch is based directly on `b53b1f7`; accidental HTML commit
  `65aaa35` is not an ancestor and the generated HTML file is absent.
- The live ruleset is restored to the canonical three required contexts:
  `repo-hygiene`, `chroma-real-smoke`, and `locomo-quickstart-bil2`. The full
  `test-and-benchmark` lane remains advisory.
- Repository visibility is private. No Pages publication, deploy, package
  release, or provider-paid operation occurred.

## Evidence

- Exact-tree strict non-external scope: 2,172 selected; 2,170 passed, two strict
  expected failures, zero skips, zero failures.
- Exact live pgvector CI invocation: 30/30 passed; its disposable container was
  removed after the run.
- Focused migration spine: 43/43 passed, including populated table-add,
  restore/re-upgrade, DELETE/WAL writer contention, TOCTOU refusal, callback
  escapes, backup publication failure, per-step resume, and honest transaction
  outcome reporting.
- Four repaired-finding files: 65/65 passed; 112 adjacent storage, graph,
  server, workspace, and reasoning tests passed before the final whole-tree run.
- Ruff, Python compilation, diff hygiene, the canonical secret/session scan,
  and independent adversarial review passed. CodeRabbit's valid findings were
  fixed; its last suggestion was already satisfied by Python `>=3.11` metadata.

## Honest boundaries

- `SEAM_API_TOKEN` remains optional for trusted-loopback development. Automatic
  first-launch token provisioning and principal tenancy are separate S6 work.
- Audit findings 7-10 and 12 remain open. Unrelated worktrees and their changes
  were inspected but left untouched.
- No provider-paid benchmark, retrieval-score measurement, artifact build,
  publish, deploy, merge, or release was run.

## Exact next move

Publish the rewritten draft head, wait for fresh exact-head required and
advisory CI, and keep PR #193 draft until review evidence is current. After
protected merge, begin S3 durable supersession and guarded reprojection; S4 may
proceed in parallel.
