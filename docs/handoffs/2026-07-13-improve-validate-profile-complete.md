---
handoff_id: 2026-07-13-improve-validate-profile-complete
supersedes: 2026-07-11-cat13-semantic-conversation-adapter-complete
handoff_status: current
history: HISTORY#387
---

# Handoff: paid-validation retrieval profile complete

- **Date:** 2026-07-13
- **Branch:** `agent/improve-validate-profile-386`
- **Base:** `6a9c219` (`origin/main` when the branch was created)
- **Implementation commits:** `d6a6ab1`, `99079f7`
- **State:** implementation, free validation, and the operator-authorized paid
  holdout validation are complete and published on draft PR #146. Branch
  `agent/improve-validate-profile-386` tracks the matching `origin` branch at
  reviewed head `8a77bad`; inspect GitHub live for current CI/review state.
- **Local exclusions:** `.playwright-mcp/`, `.wrangler/`, `gated-view.png`, and
  `visuals/` are unrelated local paths and remain untouched and excluded.
- **Service boundary:** the healthy `seam-pgvector` service is operator-owned
  and remains running.

## Delivered contract

`seam improve validate` now accepts `--profile {compact,broad}`. A named
profile overlays only the candidate's `search_top_k` and `context_budget`,
combines with explicit answer-policy `--flags` or the loop's applied state,
and leaves the stock baseline unchanged. The configuration knobs remain
deliberately unavailable as proposal fields inside `--flags`. Dry-run output
records the effective candidate flags and selected profile without building a
paid client or ingesting data; paid reports retain `candidate_profile`.

No default changed. This feature makes the already-validated retrieval profile
measurable through the supported operator-gated CLI; it does not turn on the
broad profile, `conversation/1`, or `inference/high-confidence/1` for ordinary
runtime surfaces.

The same branch makes the missing-Zep-SDK smoke hermetic by intercepting the
adapter module import itself. That keeps the no-optional-extra contract
testable even on a developer machine where `zep-cloud` happens to be installed.

## Paid validation evidence

The operator-authorized full 344-case LoCoMo holdout A/B completed at code
provenance `99079f7` with gpt-4o-mini as answerer and judge (`judge/1`). The
baseline was stock; the candidate combined `broad`, `conversation/1`, and
`inference/high-confidence/1`.

- Verdict: `improved`; aggregate `0.613372 -> 0.732558`, delta `+0.119186`
  against a `0.02` noise margin.
- Category scores: cat1 multi-hop `0.467213 -> 0.606557`; cat2 temporal
  `0.445946 -> 0.601351`; cat3 open-domain `0.476190 -> 0.500000`; cat4
  single-hop `0.740642 -> 0.850267`; cat5 `1.0 -> 1.0`.
- Candidate verdicts: 217 correct, 70 partial, 57 incorrect. Baseline: 168
  correct, 86 partial, 90 incorrect. Both arms had zero empty answers and zero
  judge retries.
- The candidate aggregate exactly reproduces HISTORY#385's one-off driver
  result (`0.732558`). The new stock baseline is `0.018895` below #385's
  `0.632267`, still inside the declared `0.02` noise margin.
- Actual record totals: 688 rows (344 per arm), 5,357,177 tokens, and
  `$0.817373`. The private artifacts remain on T7 as
  `20260713-174526-locomo-holdout.json` and its training JSONL. SHA-256:
  JSON `38ea1df8842f9d4eb7987146887114c0783cca791ae745de79cc5a99176e64db`;
  JSONL `2a56bae73b67086bac06eec53f776c9c8c6f6fa869d9061b7d6e5fe5e2f5ae47`.

No case text, provider credential, or session link is tracked in the repo.

## Free verification

- Focused profile/CLI tests passed before the paid run.
- Canonical non-external suite: 1,343 passed, two established xfails, zero
  failures, errors, or skips.
- External pgvector slice: 7/7 passed against the pre-existing operator-owned
  service.
- Ruff, byte-compilation, and `git diff --check` were clean.
- The paid pane exited status 0 and wrote exactly two artifacts with 688 JSONL
  rows and 344 unique case ids across two 344-row arms.

## Successor route

1. Treat the implementation and evidence as complete. Draft PR #146 is the
   publication route; inspect its live required checks and review threads, fix
   only current-head in-scope findings, and do not merge automatically.
2. Keep the new CLI path opt-in unless the operator separately decides which
   capable-answerer surfaces should default to the broad profile and semantic
   answer policies.
3. The measured next quality levers remain cat1 list-completeness synthesis and
   cat2 hard-incorrect diagnosis. Cat3's gain in this run was only one half-step
   across 21 cases (`+0.023810`), so do not claim the broad profile alone solves
   open-domain behavior.
4. Preserve the four unrelated local paths and leave the operator-owned
   pgvector service running.
