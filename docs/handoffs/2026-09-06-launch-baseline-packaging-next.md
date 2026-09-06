---
handoff_id: 2026-09-06-launch-baseline-packaging-next
supersedes: 2026-09-02-track-s-r1-protected-main-r2-next
handoff_status: superseded
history: HISTORY#634
---

# Launch documentation baseline; packaging migration next

## Objective and delivery boundary

The operator set the current name to Surface Encoded Agent Memory, with
Canticle SEAM Suite for self-hosting and Canticle SEAM API plus SEAM WebUI for
the paid service. Documentation comes first, packaging migration preparation
next, R2 is the first runtime slice, and expensive benchmark score work follows
product completion. Existing correctness, S9 Promotion, and S10 gates remain.

The candidate is documentation-only on `docs/launch-baseline-20260906`, based
on protected `88346018f47c75c49e19b90ea2321a6b0930e002`. It does not change
runtime code, package metadata, license texts, hooks, deployment, or published
artifacts. A pushed draft does not imply a protected-main merge.

## Canonical entry points

- [Product definitions](../PRODUCTS.md): names, roles, dashboard sections, and
  candidate artifact names.
- [Launch plan](../roadmap/SEAM_LAUNCH.md): bounded L0-L6 acceptance conditions,
  workflow triggers, and targeted hook follow-up.
- [Packaging status](../status/packaging-licensing.md): current coordinates,
  artifact constraints, and the L1 migration checklist.
- [Project status](../../PROJECT_STATUS.md): concise operating router.
- [Track S](../roadmap/TRACK_S_S8_S10_PRODUCTION_CORE.md): unchanged core
  qualification invariants; R2 remains required before S8 freeze.

## Reconciled evidence

On 2026-09-06, `git fetch origin`, `git rev-parse origin/main`, and
`gh api repos/Canticle-AI-Research/Seam/commits/main` agreed on `8834601`.
`gh pr list --state all` showed PRs #239-#248 merged, PR #236 closed without
merge, and dependency PR #249 open. The commit check-runs API reported the
required checks successful on that main SHA. This is hosted-check metadata;
no runtime test suite was rerun for this documentation slice.

`gh repo list Canticle-AI-Research` reported the canonical Seam repository
public and `Seam_SDK` private. Root `pyproject.toml` remains `seam-runtime`
2.4.0 with `Private :: Do Not Upload`. `gh release list` showed `v2.4.0` as an
existing release. PyPI JSON endpoints reported `seam-runtime` 1.3.1,
`seam-self-host` 1.1.2, and `seam-client` 2.0.0; `seam` belongs to an unrelated
API SDK. These are metadata checks, not fresh artifact or installation proof.

The legacy `BlackhatShiftey/Seam_Runtime` repository lookup returned HTTP 404;
its cause and owner access remain unverified. The separate SDK metadata
uses `seam-sdk` 0.1.0 with an older Git-pinned runtime coordinate. Candidate
Canticle package lookups returned HTTP 404, which proves neither registration
eligibility nor ownership. L1 must settle these before promising migration.

The original browser prototype was not present at the historical mounted
path during reconciliation. Locate the intended design reference before UI
implementation; do not silently substitute a terminal graph.

## Preserved work and exclusions

The primary `docs/deep-audit-20260829` checkout remains at `780b377` with:

- Modified `.seam/cross_index.md`, `.seam/streams/history/index.md`,
  `.seam/streams/history/log.md`, `HISTORY.md`, `HISTORY_INDEX.md`,
  `docs/audits/INDEX.md`, `docs/handoffs/INDEX.md`, and
  `docs/handoffs/2026-08-29-grounded-research-acquisition-roadmap.md`.
- Untracked `.codex/`, `.disposable/`, `.seam/orchestration/`,
  `.seam/cross_index_archive/0001-0477.cross.md`,
  `docs/audits/2026-08-29-full-repo-audit.md`, and
  `docs/handoffs/2026-08-30-deep-audit-findings.md`.

The clean locked audit-cleanup worktree is retained at `99c9d48`; PR #247 is
merged. The separate `fix/codex-pretool-hooks` worktree remains at `8834601`
with staged and unstaged changes to `.codex/hooks.json`, `tools/claude/` hook
files, `tests/audit/test_codex_pretool_hooks.py`,
`tests/audit/test_local_gates_match_ci.py`, its ledger/layout/orchestration docs,
and its history/derived streams. None belongs in this documentation PR.
Its provisional local history entry must be reconciled against the next
protected-main history ID when that candidate is resumed.

The validated primary closeout queue had no pending requests, and no stashes
were listed. The new worktree had no local snapshot, so startup used bounded
history entries and current handoff evidence; closeout creates its snapshot.

## Verification and resume

Pre-closeout checks are recorded in HISTORY#634; final gate and CI results
belong to the candidate qualification receipt and PR. TDD is not applicable
to this prose-only slice. Independently
review the candidate and require its own CI before any merge; existing main's
green checks do not qualify the branch.

After this baseline is accepted, prepare L1's package/source/ownership map and
migration candidate. Keep names provisional until registration and artifact
eligibility are checked. Then take R2 through its defined scale/parity slice.
Keep hook completion separate and preserve the existing audit work. Package
publication, deployment, paid benchmark calls, and protected merge require
their own operator authority.
