---
handoff_id: 2026-08-22-github-operations-restacked
supersedes: 2026-08-22-track-s-s6-third-review-repaired
handoff_status: current
history: HISTORY#582
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

## Next exact steps

1. Append HISTORY#582 and regenerate canonical history, stream, and snapshot
   state.
2. Create and verify a signed bookkeeping commit, scan the exact candidate,
   and push PR #224.
3. Mark the draft ready, require `repo-hygiene`, `chroma-real-smoke`, and
   `locomo-quickstart-bil2` on the pushed head, obtain exact-head review, and
   merge through protected `main`.
4. Publish a final protected-main status/handoff successor naming S7 as next;
   do not create backlog issues or releases unless the operator asks for them.
