---
handoff_id: 2026-08-22-github-operations-restacked
supersedes: 2026-08-22-track-s-s6-third-review-repaired
handoff_status: current
history: HISTORY#585
---

# GitHub Issues and private Releases — restacked candidate

## Current publication boundary

- Track S S6 PR #223 merged to protected `main@abd2a59` after exact-head
  required CI and a clean final Codex review.
- Draft PR #224 now targets `main`. Its branch-only history entries were
  renumbered to HISTORY#580/#581 after the protected S6 chain reached #579.
- Signed merge `b3d35ec` reconciles PR #224 with `main@abd2a59` without
  rewriting either published history or the branch's authored GitHub setup.
- The issue forms and release workflow are still branch-local until PR #224
  passes repeat exact-head checks and merges.

## Candidate scope

- Structured bug, feature, research/benchmark, and release issue forms with
  blank issues disabled and security reports routed to private advisories.
- A release checklist, generated-note categories, and a hardened manual private
  GitHub Release workflow with default-branch, version, tag, archive, smoke,
  checksum, and immutable-release gates.
- No PyPI publication permission, version bump, tag, release, issue, milestone,
  deployment, or paid provider call was added or performed.

## Verification

- Focused GitHub configuration/release tests pass, including their parameterized
  cases; Ruff and the dependency-contract verifier pass.
- Diff hygiene, the canonical working-tree secret/session scan, and all required
  history, routing, handoff, continuity, stream, and wiki gates pass locally.
- Exact-head GitHub CI and final review remain publication gates.

## Exact-head review repairs

- Credential-family filenames, Windows drive-qualified members, and nested
  archives now fail closed before release upload; focused regressions cover the
  concrete reviewed counterexamples.
- The release-proposal form records publication prerequisites without requiring
  a proposal author to claim that protected-main review already happened.
- The environment-gated publishing job rechecks both the live default-branch
  head and tag absence after approval, closing the wait-window race.
- `PROJECT_STATUS.md` and the workspace stream now consistently record merged
  S6 at `main@abd2a59` and PR #224 as the only remaining operational candidate.
- The second exact-head review expanded credential detection to embedded
  markers such as `client_secret`, detects nested containers by archive magic
  as well as suffix, classifies SemVer prereleases for GitHub, creates the tag
  atomically at the verified SHA before `--verify-tag` publication, keeps the
  proposal target optional until freeze, and reconciles the routed operations
  stream with merged S6.

## Next exact steps

HISTORY#584, its signed review-repair commits, exact candidate scan, initial
required checks, and the two prior local review cycles are complete. Continue
with:

1. Push the completed second exact-head review-repair successor.
2. Require `repo-hygiene`, `chroma-real-smoke`, and
   `locomo-quickstart-bil2` on the pushed head, obtain exact-head review, and
   merge through protected `main`.
3. Publish a final protected-main status/handoff successor naming S7 as next;
   do not create backlog issues or releases unless the operator asks for them.
