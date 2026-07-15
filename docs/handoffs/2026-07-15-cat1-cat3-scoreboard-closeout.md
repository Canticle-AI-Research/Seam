---
handoff_id: 2026-07-15-cat1-cat3-scoreboard-closeout
supersedes: 2026-07-15-cat1-cat3-past-80-handoff
handoff_status: current
history: HISTORY#399
---

# Handoff: cat1/cat3 scoreboard closeout

- **Date:** 2026-07-15
- **Branch:** `agent/cardinality-constraint`
- **PR:** #150 (`agent/cardinality-constraint` -> `main`)
- **Pre-closeout head:** `96117b5`
- **Local exclusions:** `.playwright-mcp/`, `.wrangler/`, `gated-view.png`, and
  `visuals/` are unrelated operator/local paths and remain untouched and
  excluded.

## Outcome

The mission has two deliberately separate answers.

1. **SEAM native holdout / judge/1:** the #390 champion still stands at
   `0.768895`. Conversation/4's full 344-case candidate scored `0.754360`,
   regressing `-0.014535`; cat1 stayed `0.614754` and cat3 stayed `0.595238`.
   Neither category crossed 0.80 on judge/1.
2. **mem0-harness scoreboard:** both categories crossed 0.80 using SEAM as a
   drop-in Mem0-OSS retrieval server inside unmodified
   `mem0ai/memory-benchmarks` commit `4b61c5d`, with explicit gpt-4o-mini
   answerer/judge overrides and one top-200 cutoff. Cat1 multi-hop =
   **250/282 (`0.886525`)**; cat3 open-domain = **83/96 (`0.864583`)**;
   combined = 333/378 (`0.880952`).

Never present the second number as a judge/1 improvement. The external harness
owns answer generation and its binary lenient judge; it accepts partial lists,
extra detail, and tolerant dates. The facade was started with the #390 policy
environment, but `SeamLocomoAdapter(answerer=None)` means SEAM's conversation,
inference, and temporal answer directives do not enter the harness prompt. This
is the correct public-table-style retrieval scoreboard, not a rerun of #390's
native answer stack.

## Measured evidence

### c4 judge/1 negative

- Candidate vs fresh stock: `0.754360` vs `0.629360`, still improved over stock.
- Candidate vs #390 champion: `-0.014535`; cat1 and cat3 exactly unchanged.
- 5,200,972 exact tokens, `$0.793850` actual cost, 0 empty answers, 0 judge
  retries, no provider-error lines.
- Record: external `20260715-071132-locomo-holdout.json`.

### Prompt-only microgate negative

Uncommitted `conversation/5` and `inference/high-confidence/3` proposals were
tested against stored #390 contexts before any full run. Across an 18-case pass
and a 10-case final-question-tail pass, cat1 kept one pet-name recovery but
retained broad false positives; cat3 recovered only Exploding Kittens in the
tail pass while the other canonical entities stayed wrong. Estimated combined
cost: `$0.053650`. The unsupported runtime/test changes were removed with
`apply_patch`; no v5/inf3 code remains.

### mem0-harness result

- Calibration: 38/40 overall; cat1 15/15, cat3 5/5, estimated `$0.078264`.
- Full category run: cat1 250/282, cat3 83/96, combined 333/378.
- All 378 answers non-empty. The harness logged 27 retry-attempt warnings at
  the 200K TPM edge; all recovered within the five-attempt budget.
- Reconstructed full-run usage: 4,545,540 input + 24,512 output tokens;
  estimated `$0.696538`. The harness does not retain provider usage objects, so
  this is intentionally labeled reconstructed, not exact.
- Private artifact: external
  `20260715-091018-mem0-harness-cat13.json` (24,392,640 bytes), SHA-256
  `e93cc7a4cd2611bd7b68906d90d8ad0d63684a933ee637b50403fb74104c2b4f`.
- Known successor-slice roll-up: `$1.622302` (c4 actual; prompt microchecks and
  mem0 calls reconstructed). The earlier inference/2 functional microcheck did
  not retain usage and is excluded rather than guessed.

Full transition analysis and the scorer boundary are in
`docs/audits/2026-07-15-c4-and-mem0-cat13-score.md`.

## Code and decision state

- `conversation/4` remains opt-in/default-off and is now tested-and-parked as a
  non-champion.
- `inference/high-confidence/2` remains opt-in/default-off. It has a positive
  stored-context functional check but no decisive full holdout result in
  isolation; do not promote it by inference from the mem0 score.
- `conversation/5` and `inference/high-confidence/3` do not exist in committed
  runtime code; their negative evidence is documentation-only.
- No ordinary runtime default changed.
- PR #150 had all nine checks green at pre-closeout head `96117b5`. The
  closeout commit updates only status/audit/history/handoff artifacts; inspect
  the fresh pushed-head checks before merge.
- PR #149 supplies the Mem0-OSS facade. Its required checks were green when
  inspected; one advisory Ubuntu test matrix check was failing. Treat that
  advisory separately unless a fresh check shows a facade-caused failure.

## Verification and process state

- The inherited canonical non-external pytest log at head `96117b5` contains
  1,362 pass dots and two established xfails through 100%, with no failure,
  error, or skip markers. The terminal summary/exit code was not independently
  captured, so preserve that qualification rather than upgrading it to a new
  exit-code claim.
- Run the focused shim + conversation-policy tests after this documentation
  closeout, then run the complete history/handoff/continuity/streams chain.
- The scored harness process exited normally. The temporary facade on port
  8902 was stopped cleanly. No process or worktree created by this successor
  remains active.

## Successor route

1. Do not spend on another judge/1 full holdout without a new free
   stored-context result that shows broad, non-regressing movement.
2. Keep native judge/1 and mem0-harness numbers side by side and labeled; never
   splice their category scores into one trend line.
3. Decide PR #150 on its actual contents: useful opt-in research levers plus a
   complete negative/scoreboard record, not a new native champion.
4. Inspect PR #149/#150 live before merge. Required checks and the no-default-
   change contract remain the merge gates.
