---
handoff_id: 2026-08-01-track-s-production-core-campaign
supersedes: 2026-07-30-wandr-zero-network-replay-lane
handoff_status: superseded
history: HISTORY#511
---

# Handoff: Track S production-core integrity campaign activated

**Date:** 2026-08-01
**Branch:** `fix/memory-guarantees-campaign`
**Semantic baseline:** `86a81e29507603b624138d3355413b99d43b7422`

## One-line state

The clean replacement and semantic integration baseline exists, and Track S now
holds the one authoritative F1-F22 verdict matrix plus dependency-ordered S0-S10
exit gates; no F1-F22 production defect is claimed fixed by this activation and
continuity slice.

## What is now canonical

- `docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md` is the only campaign plan. It
  defines the verdict vocabulary, authoritative F1-F22 routing, stage dependency
  graph, and exact stage exit gates. Do not create a duplicate audit/status
  document.
- `ROADMAP.md` registers `roadmap:track:S` at priority 0 / phase 1 and puts it
  first in the Recommended Course.
- Track S coordinates Track R, H2, E2, and K14. It supersedes none of them.
- `PROJECT_STATUS.md` and the retrieval/surfaces/operations streams describe the
  verified baseline and open campaign boundaries. Stable architecture policy
  is unchanged, so `REPO_LEDGER.md` was deliberately not edited.

## S0 baseline evidence

The semantic baseline commit changes exactly 27 paths: 26 semantic Python paths
plus `.github/workflows/ci.yml`. The integration retains:

- fail-closed exact-REL, same-boundary, canonical-ENT graph admission;
- the one-engine planner boundary, weighted-RRF/provenance work, and legacy
  enclosing `else`;
- pinned offline embedding/cache/provision checks and all-case vector coverage;
- explicit local relation extraction with environment extraction disabled by
  default and `scorer_eligible=false` at the measured 27/419 coverage.

Scoped verification, and only this scope:

- the exact 12-module semantic/offline-integrity slice collected 269 and passed
  269/269 after the required pinned-revision CI environment hunk was restored;
- Ruff passed over the original 26 changed Python paths;
- `git diff --check` passed;
- the exact 27-path allowlist contained zero history/status/handoff/roadmap,
  `.seam`, `.ua`, WANDR, or generated paths, and the `.ua` count was zero;
- a quiet secret/key/token/password/credential plus provider session/share URL
  scan over those same 27 candidate paths was clean.

The full suite was not run for this baseline and must not be inferred from the
focused result. The shared worktree's installed pre-commit hook was absent; no
hook bypass flag was used and no hook was installed. The canonical gates were
therefore run manually. Before HISTORY#511, integrity, routing, handoffs, and
streams were clean; continuity alone reported the known missing snapshot for
HISTORY#510. HISTORY#511 closeout owns that snapshot/continuity repair.

## Campaign boundary

- S0 is reconstructed but remains evidence-gated until every S0 clause passes,
  including the existing full suite and bounded review.
- S1-S10 are not implemented by this handoff.
- The current retrieval evidence remains +0.009628 overall against the
  reproduced legacy control, with cat3 -0.036775, ENT provenance 0.0000, and
  live-leg weights unvalidated.
- Default ingest remains relation-free. The explicit relation lane is research
  evidence, not a graph/scorer promotion.
- No provider, paid, or network benchmark ran. No package, deployment, PR,
  remote branch, publication, or external service state changed.
- The primary checkout and unrelated worktrees remain out of scope. Do not
  delete this worktree or any artifact without exact operator authorization.

## Exact next step

1. Reconcile the branch and this handoff, then satisfy the remaining S0 exit
   clauses without broadening the semantic baseline.
2. Begin S1 only after S0 is fully evidenced. Route each change by F-ID, keep
   non-tied retrieval output bitwise inert, and prove every S1 fail-closed gate.
3. Do not skip ahead to semantic/retrieval scoring: S2 migration durability,
   S3/S4 truth integrity, and S5/S6 storage/tenancy are dependencies.
4. Keep all provider-paid execution, publication, push/PR mutation, and cleanup
   behind fresh explicit authorization.
