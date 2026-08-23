---
handoff_id: 2026-08-22-github-operations-restacked
supersedes: 2026-08-22-track-s-s6-third-review-repaired
handoff_status: current
history: HISTORY#593
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
- The follow-up CodeRabbit review's archive-magic evidence gap is closed with
  an unrecognized `payload.bin` ZIP fixture. Its timestamp suggestion was
  rejected: the cited canonical HISTORY entries contain date-only values, so
  derived cross-index rows correctly preserve them without invented instants.
- The third exact-head review added password-family filenames, Zstandard/LZ4
  container detection, Unicode-normalized case-fold collision rejection,
  direct PyYAML test dependencies, live-head validation adjacent to atomic tag
  reservation, and recoverable exact draft/tag cleanup on failed publication.
  A real 2.4.0 wheel and sdist built from the repaired working tree pass the
  hardened verifier and `twine check`.
- The fourth exact-head review closed binary-member secret scanning and
  Windows trailing-dot/space path collisions, reconciled every active S6
  authority to merged protected-main state, and left generated release notes
  in a draft for explicit operator review before manual publication.
- A follow-up local CodeRabbit pass found and removed the last stale
  pre-merge S6 sentence in the active surfaces status; the audit now rejects
  that pending-publication wording.
- The fifth exact-head review added token/auth filename families, Windows
  reserved-device rejection, ordinal-only archive-member reporting, and a
  separate guarded publish workflow that revalidates the mutable reviewed
  draft immediately before publication.
- A focused local follow-up requires that reviewed tag to remain the current
  protected-main head and explicitly rejects annotated tags because the
  preparation workflow owns one atomic lightweight tag.
- The sixth exact-head review added final protected-head revalidation, reviewed
  notes digest binding, exact manifest coverage, artifact filename/metadata
  identity, UTF-16 secret scanning, safe archive-read failures, concatenated
  token/auth stems, complete Windows-invalid character rejection, and README
  documentation for both guarded stages.

## Next exact steps

HISTORY#592, its signed review-repair commits, exact candidate scan, initial
required checks, and the prior review cycles are complete. Continue with:

1. Push the completed sixth exact-head review-repair successor.
2. Require `repo-hygiene`, `chroma-real-smoke`, and
   `locomo-quickstart-bil2` on the pushed head, obtain exact-head review, and
   merge through protected `main`.
3. Publish a final protected-main status/handoff successor naming S7 as next;
   do not create backlog issues or releases unless the operator asks for them.
