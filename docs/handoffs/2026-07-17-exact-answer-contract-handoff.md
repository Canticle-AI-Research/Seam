---
handoff_id: 2026-07-17-exact-answer-contract-handoff
supersedes: 2026-07-15-cat1-cat3-scoreboard-closeout
handoff_status: current
history: HISTORY#409
---

# Handoff: exact-answer contract built + concurrent-chain reconciliation

- **Date:** 2026-07-17
- **Branch:** `agent/roadmap-zep-after-benchmarks` (checked out) — `main` points
  to the same commit (`85eb0bc`); they are identical, not diverged.
- **Head:** `85eb0bc` (HISTORY#408, the exact-answer contract build)
- **Push state:** `main` is a clean **fast-forward 2 commits ahead** of
  `origin/main` (`5c508e2` = HISTORY#406). Nothing is pushed yet. See
  "Push & merge" below.
- **Local exclusions:** `.playwright-mcp/`, `.wrangler/`, `visuals/`, and the
  loose screenshots/`page-snapshot.md` were gitignored in HISTORY#406 and are
  no longer untracked; the working tree is clean.

## What was done this session (all committed, durable)

Three things, in order:

1. **Concurrent-chain reconciliation (HISTORY#405).** This session opened while a
   `codex` chain landed **PR#152** (temporal knowledge graph + real auto-ingest)
   on `origin/main`, taking HISTORY ids **402–404**. A local `claude` closeout
   had been drafted as `#402` and collided (fork). Resolved by resetting local
   `main` to `origin/main` and re-chaining the claude closeout as **#405**
   (`supersedes: 404`) — one linear timeline, no forked ids, no lost work. The
   pre-reconcile state is preserved as branch `backup/history-402-claude`. The
   re-chained content (PR#121/#151 merges + the 0.776163 paid A/B) stands.
2. **Worktree hygiene (HISTORY#406).** Gitignored the untracked local artifact
   dumps; `git status` is clean.
3. **BUILT the exact-answer contract (HISTORY#408).** The #405-ranked next lever.

Note on numbering: **HISTORY#407** (commit `2c3755d`) is a *different* claude
session's ROADMAP planning entry (Track P: Agent Runtimes & Memory Profiles,
OpenClaw first; Track Q: SEAM Lite for Android). It committed on top of #406
while this session worked; it is **preserved**, and #408 chains correctly after
it (`#408 → #407 → #406`, continuity verified).

## The exact-answer contract (HISTORY#408) — the deliverable

New **orthogonal** `RetrievalFlags` field **`answer_contract`** (default `off`;
opt-in **`exact-answer/1`**). It composes *on top of* the `conversation/2`
champion base rather than replacing it — unlike a new conversation adapter
version.

It is a **single-pass draft-then-verify** directive appended after the
collection clauses (not a second model call — the A/B stays ~$0.80). After the
model drafts an answer it runs one verify pass:

- **Coverage** (set-completion intent only): re-scan and ADD any dropped
  supported set item → the recall misses.
- **Precision**: REMOVE anything the question did not ask for → the **23
  judge-docked partials** that carried full gold but padded extras.
- **Anchoring**: confirm the answer is drawn from the specific person/event/date
  the question refers to, not a look-alike → the **18 wrong-episode** cases.

**Why it should beat the dead `conversation/4`:** v4 pruned at *collection* time
and lost cat1 recall; exact-answer/1 keeps conversation/2's broad sweep and
prunes **post-draft**, so recall is preserved. The draft-then-verify sequencing
is the whole point, and why it is expected to beat set-completion-alone
(~+0.015). Realistic estimate ~+0.04–0.05 → ~0.82.

**Wiring (mirrors `temporal_policy` exactly):** field + `coerce_flag_value`
validation (fail-closed) + `SEAM_ANSWER_CONTRACT` env + `retrieval_flags_from_env`
/`load_retrieval_flags`; `seam_runtime/conversation.answer_method_directive`;
`benchmarks/external/common/answerer.py` (`build_answer_prompt` fast-path
preserved, `generate_short_answer`, `SharedAnswererAdapter`);
`benchmarks/external/locomo/run.py` (`build_adapter`, `_maybe_wrap_answerer`,
`--answer-contract` CLI arg, both call sites);
`benchmarks/external/locomo/adapters/seam.py` (constructor, flags gate,
`_generate_answer`, `diag_out`, `_runtime` overlay); registered as an
`answer_policy_lever` in `self_improve.candidate_levers`. `cli.py --flags` picks
it up automatically via `retrieval_flag_field_types`. **All defaults are
byte-identical** (test-pinned).

## Verification (free, no provider/paid call)

- 6-point functional smoke (default byte-identity, per-intent directive
  rendering, coercion, env load, fail-closed, lever registration) — all pass.
- 15 new regression tests across `test_semantic_conversation_adapter.py`,
  `test_retrieval_flags.py`, `test_shared_answerer.py`.
- Affected slice: **92 passed**.
- `ruff` clean on all touched files (2 pre-existing `I001` findings in the
  untouched `test_pgvector_real_adapter.py` are from PR#152's base, not this
  change).
- Full `pytest tests/`: **exit 0**, zero failures/errors, 2 established xfails,
  only the four environment-gated pgvector external skips (`PGVECTOR_TEST_DSN`
  unset locally).
- All four SEAM chain verifiers (integrity/continuity/routing/handoffs) green.

## THE NEXT STEP (operator-gated, not run)

The lever is **BUILT-NOT-YET-VALIDATED**. The decisive step is **one
operator-gated ~$0.80 344-case holdout A/B**, judge/1:

- **Candidate:** `conversation/2 + inference/high-confidence/2 + temporal/1 +
  broad + answer_contract=exact-answer/1`
- **Baseline (the #405 champion):** the same stack **without** `exact-answer/1`
  (i.e. `conversation/2 + inference/high-confidence/2 + temporal/1 + broad`).
- Run via `seam improve validate --flags '{...}' --profile broad` (the CLI picks
  up `answer_contract` automatically), or the locomo `run.py --answer-contract
  exact-answer/1` path.

**Optional de-risk first:** a cents-level functional pre-flight on the stored
#405 miss cases (the HISTORY#397 precedent) — gpt-4o-mini over each case's stored
`retrieved_context` (no re-retrieval), champion prompt vs exact-answer/1 prompt —
to confirm direction before spending the full ~$0.80. **Any paid run must be
operator-confirmed first.**

## Push & merge

`main` == `agent/roadmap-zep-after-benchmarks` == `85eb0bc`, a clean
fast-forward 2 commits ahead of `origin/main`:

```
85eb0bc  HISTORY#408  exact-answer contract lever  (this session)
2c3755d  HISTORY#407  ROADMAP Track P/Q            (other claude session, preserved)
5c508e2  HISTORY#406  = origin/main
```

To push+merge (no PR needed — linear fast-forward):

```
git checkout main && git push origin main
```

This sends **both** #407 and #408 up; both are chain-verified and clean. The
operator asked to confirm before the push fired, so it was **not run** in this
session.

## Guardrails reconfirmed

- No paid spend this session. No provider call.
- Do not clobber `backup/history-402-claude` (the pre-reconcile safety branch)
  or the other agent's `#407` commit.
- Never edit committed HISTORY entries; chain forward with `supersedes`.
