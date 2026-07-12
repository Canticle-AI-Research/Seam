---
handoff_id: 2026-07-11-cat13-semantic-conversation-adapter-in-progress
supersedes: 2026-07-11-cat1-cat3-success-contract-handoff
handoff_status: superseded
history: HISTORY#381
---

# Handoff: semantic conversation adapter and category-driven loop in progress

- **Date:** 2026-07-11
- **Branch:** `agent/cat13-semantic-conversation-adapter`
- **Base:** `f0c8ddb` (`main == origin/main` when the branch was created)
- **State:** deliberately dirty and uncommitted; focused collect succeeds but
  the executed slice has six known failures described below.
- **Paid boundary:** no provider call is authorized or needed for the next
  steps. No paid call was made in this session.
- **Unrelated local paths:** `.playwright-mcp/`, `.wrangler/`, and `visuals/`
  predate this workstream and remain out of scope.

## Operator decisions now governing the work

The operator selected the product-correct direction after the prior success-
contract gate. Raw benchmark scores remain visible and an adjudicated view is
reported separately; benchmark-specific guessing is not acceptable default
product behavior. Cat1 and cat3 must each reach at least `0.80` before a non-
developer operator surface is considered; `0.80` is a floor, not a stopping
point. The improvement loop must optimize those category outcomes rather than
retrieval aggregates alone.

Context handoffs should normally fire at **45%**, inside the operator's
`40-55%` band. A session may exceed 45% only to finish an atomic safety
boundary (for example, collect a running test or write the handoff) and should
never continue ordinary implementation beyond 55%. Run the context monitor
every 5-10 substantive tool calls.

## Diagnosis and competitive context

The remaining gap is an action-space mismatch: the existing loop can tune
retrieval flags, but the adjudicated failures require cross-turn evidence-set
completion, controlled inference, and honest score correction. The intended
product component remains the operator's **semantic conversation adapter**:
collect all relevant evidence, preserve provenance/temporal scope, resolve
aliases/coreferences, deduplicate, validate requested counts/dimensions, then
synthesize.

A live primary-source scan found that current public LoCoMo claims use mixed
protocols and cannot form one naive leaderboard. Relevant posted claims include
Mem0 managed v3 `92.5` overall / `72.7` open-domain; Zep `94.7` overall /
`79.2` open-domain with GPT-5.4; Hindsight up to `89.61`; MemHQ `83.2`;
Memori `81.95`; MemPalace `88.9 R@10` retrieval recall (not QA accuracy);
and no LoCoMo score in the official Claude-mem repo. EvolveMem's separate
Token-F1 loop independently found query decomposition, per-category answer
styles, cat3 inferential subtypes, and answer verification, which validates the
direction but not SEAM's implementation or scores.

## In-flight implementation

- `seam_runtime/conversation.py` (new): opt-in `conversation/1` readable
  evidence view, conservative query-intent routing, set-completion directive,
  and `inference/high-confidence/1` ambiguity-aware policy.
- `seam_runtime/retrieval.py`: adds versioned policy fields to the existing
  persisted apply/revert state; defaults remain `off` and `context-only`.
- `benchmarks/external/common/answerer.py` and
  `benchmarks/external/locomo/adapters/seam.py`: optional shared-policy prompt
  path plus diagnostics.
- `seam_runtime/self_improve.py` and `tools/h2/improvement_loop.py`: gated
  answer-policy candidates and category-floor progress in selection.
- `benchmarks/external/common/adjudication.py` (new): versioned overlay that
  retains the raw score report and emits a separately named corrected view.
- Scorer markers in `answer_quality_scorer.py` / `judged_scorer.py` and focused
  tests in `tests/audit/`.

This is a first vertical slice, not a completed feature. In particular, the
real CLI does not yet pass the cat1/cat3 `0.80` floors, free survivor-set
measurement has not run, and the design choice to store answer policy fields
inside `RetrievalFlags` needs review before it becomes durable architecture.

## Cut-off verification and known failures

`git diff --check` passed. Collect-only succeeded for 67 tests:

```bash
.venv/bin/python -m pytest --collect-only -q \
  tests/audit/test_semantic_conversation_adapter.py \
  tests/audit/test_improvement_loop.py \
  tests/audit/test_retrieval_flags.py \
  tests/audit/test_shared_answerer.py \
  tests/audit/test_judged_scorer.py \
  tests/audit/test_locomo_answer_quality_scorer.py
```

The same executed slice produced **61 passed, 6 failed**:

1. `tests/audit/test_improvement_loop.py` lacks `import pytest` for the new
   `pytest.approx` assertion.
2. Five `tests/audit/test_judged_scorer.py` cases inject legacy generator
   callables accepting `(question, context, diag_out=None)`. The adapter now
   unconditionally passes `flags=...`, breaking that established injection
   contract. Preserve compatibility by passing the keyword only when an opt-in
   answer policy is active, or by using a narrow compatibility dispatcher that
   does not swallow genuine provider `TypeError`s.

No full suite, ruff, py_compile, benchmark, or paid validation was run.

## Resume here

1. Inspect the live diff and fix only the six known failures first.
2. Rerun the exact 67-test slice; then run ruff and py_compile on touched code.
3. Prove the default answer prompt is byte-identical and comparator wrappers
   can receive the same policy for fair head-to-head runs.
4. Review whether answer policy belongs in `RetrievalFlags` or a generic
   applied-policy state before adding more levers.
5. Wire explicit cat1/cat3 `0.80` floors into the real CLI and add raw plus
   adjudicated reporting without running the underlying scorer twice.
6. Validate on free dev/survivor fixtures. Do not claim a score improvement
   from structure alone and do not spend without a new operator cost gate.
7. Run the affected and canonical non-external suites, complete continuity,
   and open a draft PR only after the slice is coherent and green.

The supplementary local compact handoff is
`.context-handoffs/context-handoff-20260711T225518Z.md`.
