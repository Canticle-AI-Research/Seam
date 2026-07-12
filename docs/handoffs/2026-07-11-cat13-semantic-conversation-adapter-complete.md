---
handoff_id: 2026-07-11-cat13-semantic-conversation-adapter-complete
supersedes: 2026-07-11-cat13-semantic-conversation-adapter-in-progress
handoff_status: current
history: HISTORY#382
---

# Handoff: semantic conversation adapter complete

- **Date:** 2026-07-11
- **Branch:** `agent/cat13-semantic-conversation-adapter`
- **Base:** `f0c8ddb` (`origin/main` at final local verification)
- **Implementation commits:** `5629e84`, `381e448`
- **State:** implementation and local review complete; check GitHub live for the
  current draft PR and CI state because publication state can change after this
  tracked closeout commit.
- **Paid boundary:** no benchmark generation, provider call, or paid validation
  was made for this slice.
- **Local exclusions:** `.playwright-mcp/`, `.wrangler/`, and `visuals/` are
  unrelated local paths and remain untouched and excluded.

## Delivered contract

The product-correct direction selected after HISTORY#377 is now represented as
an opt-in semantic conversation policy rather than benchmark-specific guessing.
`conversation/1` projects readable, provenance-preserving cross-turn evidence;
set completion and `inference/high-confidence/1` remain separate capabilities,
and the default answer prompt remains unchanged when the policy is off.

The same policy can flow through SEAM, Mem0, and Zep comparison paths. The
improvement CLI accepts and validates explicit cat1/cat3 floors, proposes gated
answer-policy candidates, and reports both raw-regression and category-floor
progress. A versioned adjudication overlay retains the raw `ScoreReport`, emits
a separately named corrected view from the same scorer execution, and rejects
corrections whose case ids do not match the raw report. Raw benchmark results
remain visible and authoritative for raw-regression gates.

This slice does **not** claim cat1 or cat3 reached `0.80`. Reaching those floors
still requires a separately authorized, provenance-complete measurement run;
no new paid run is implied by the code or this handoff.

## Review and verification

- The affected pre-review slice passed 101 tests; ruff, byte-compilation, and
  `git diff --check` were clean.
- CodeRabbit's first committed-diff review found three valid issues: isolate
  inference-only from set completion, reject unmatched adjudication ids, and
  validate floors inside `[0,1]`. Commit `381e448` fixes all three.
- The post-fix focused slice passed 46/46 tests. CodeRabbit's second
  committed-diff review returned zero findings.
- The reviewed head collected 1,337 canonical non-external tests and exited
  zero with only two established xfails and no failures, errors, or skips.
- The first external pgvector invocation produced 4 passed / 3 skipped and
  failed strict-no-skip because only `PGVECTOR_TEST_DSN` was present while
  three real-adapter tests gate on `SEAM_PGVECTOR_DSN`. The corrected rerun
  supplied both variables without printing credentials and passed 7/7.
- The healthy pgvector service predated this work and remains running; it is
  operator-owned and must not be stopped as part of branch cleanup.

## Successor route

1. Inspect the live draft PR, current head SHA, CI checks, and review threads.
2. Fix only a current-head in-scope failure; rerun the proportional local slice
   after any code change and append a new HISTORY entry rather than rewriting
   HISTORY#382.
3. Do not merge automatically. Keep raw and adjudicated claims separate and
   require a new operator cost gate before any provider-backed measurement.
4. Keep the three unrelated local paths out of staging, retain one worktree,
   and leave no stashes.
