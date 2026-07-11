---
handoff_id: 2026-06-08-h2-self-improvement-loop
supersedes: none
handoff_status: superseded
history: HISTORY#291
---

# Handoff — H2 self-improvement loop (front half) — for GPT

Date: 2026-06-08
Author: Claude (Opus 4.8)
Branch: `feat/h2-self-improvement-loop` (NOT pushed, NOT PR'd; `main` is protected — branch+PR only)

## TL;DR

The back half of the H2 self-improvement loop is committed and green (#289, #290).
The front half (proposer + ratchet) is **half-built and UNCOMMITTED with NO tests
yet** — finish tests, wire a free-LoCoMo scorer, run the full suite, then SEAM-chain
+ commit as #291. Do NOT run any paid LoCoMo/BEAM/LongMemEval without explicit
operator confirmation.

## Mission / what the operator wants

Close the SEAM self-improvement loop so it **always tries to successfully improve
retrieval, for free**, and ALSO keep a paid validation path (operator chose "#1 AND
both"). Constraints (hard):
- A PAID run must NEVER be required to improve. Free signals drive the loop; paid is
  optional, operator-triggered validation only.
- Never auto-launch a paid run (answerer/judge = openai/claude). Confirm first.
- No "Co-Authored-By: Claude" / generation footers in commits.
- After any repo-state change: append HISTORY.md, rebuild index, snapshot, run
  verify_integrity + verify_routing + verify_continuity + streams.verify_streams.
- Final check is ALWAYS full `python -m pytest tests/` (never a -k subset).

## What is COMMITTED on the branch (durable, green)

- **#289** — the apply step (back half). `tools/h2/improvement_review.py apply`
  reconciles approved, non-holdout-violating proposals whose
  `proposed_change["flags"]` payload matches `RetrievalFlags` fields into a persisted
  `retrieval_flag_state` table (`seam_runtime/storage.py`:
  `iter_/upsert_/replace_retrieval_flag_state`; `replace_*` rewrites the table
  atomically = a pure projection of the approved set, so apply is REVERSIBLE not a
  ratchet). `seam_runtime/retrieval.py load_retrieval_flags(store, env)` layers
  defaults < persisted < env override. Baseline-invariant when empty. Gated on
  payload SHAPE not `kind`; newest-approval-wins per flag. 17 tests in
  `tests/audit/test_h2_apply.py`.
- **#290** — front-half FOUNDATION + a key NEGATIVE result.
  - `seam_runtime/self_improve.py`: free self-probe scorer. `Scorer` protocol,
    `ScoreReport`, `Probe`, `generate_probes` (cloze: mask the salient span of a
    record's text; query = remainder; gold = that record), `SelfProbeScorer` (binary
    recall = gold record id in the candidate set; not budget-gameable; deterministic).
  - `seam_runtime/runtime.py`: `search_ir(..., flags=)` ablation hook (run retrieval
    under explicit RetrievalFlags, bypassing the per-runtime cache/env).
  - `seam_runtime/retrieval.py`: fusion weights are now an apply target —
    `RetrievalFlags.w_lexical/.w_semantic/.w_graph/.w_temporal` (defaults
    .40/.35/.15/.10 = locked #273 baseline) + `weight_pairs()`; `_fuse_weighted`
    reads them; default tuple = byte-identical baseline. Shared `coerce_flag_value(key,
    value)` validator (int->float tolerance for weights, bool/int-cross rejected),
    used by both `load_retrieval_flags` and the apply step.
  - Tests: `tests/audit/test_self_probe_scorer.py` (7), `test_h2_apply.py` +2 weights.

### THE FINDING (recorded in #290 HISTORY — do NOT re-derive)

On a realistic no-paid corpus (LoCoMo conv-26 ingested via the seam adapter
`ingest_turn`, ~2000 records), **no apply-able lever (booleans OR fusion weights) has
free headroom on the self-probe signal**:
- `search_ir` surfaces **CLM** (compiled claims), never RAW — a RAW-keyed probe gold
  scores a structural 0.0. The probe gold MUST target the kind retrieval returns (CLM).
- With CLM gold: baseline self-probe recall 0.8917 at eval budget 20.
- Booleans flat or regressing (fusion=rrf and every rrf_k REGRESS — matches #273).
- NO weight vector moves recall UP at any eval budget (1,2,3,5,10,20). Best found
  anywhere = +0.008 at top-1 (within the ~±0.002 noise floor).
- Why: cloze-of-own-record is a lexical twin by construction → too easy →
  lever-insensitive. Free cloze-hardening can't fix it (only paid LLM paraphrase can).

So the bottleneck is the SIGNAL, not the levers. Two experiments (this + #273) agree
global retrieval levers are ~near-optimal on free signals. The signal with realistic
difficulty AND measured lever headroom is **free LoCoMo string-match**
(`--answerer none --judge none`; #273 measured `semantic_zero` +0.026 cat1, +0.018
cat3, -0.004 cat4, +0.0046 global — no judge, no paid).

### Operator decision (drives the rest)

Do **#1**: ship the loop as a free, always-trying improvement loop +
no-regression watchdog, AND keep paid as an optional tier ("we want both"). The
machinery is scorer-agnostic: FREE scorers (self-probe + free-LoCoMo) drive the
always-on loop; PAID scorers (judged) implement the same `Scorer` protocol and join
the scorer list only for operator-triggered validation. Free never requires paid.

## What is UNCOMMITTED / IN PROGRESS (you must finish this)

Working tree is DIRTY with these two pieces (no tests yet, not run):

1. `seam_runtime/self_improve.py` — added the proposer CORE (pure logic, no DB/apply):
   - `DEFAULT_NOISE_MARGIN = 0.005`, `DEFAULT_REGRESS_TOL = 0.005`
   - `@dataclass Candidate(label, change: dict, flags: RetrievalFlags)` — `change` is
     the minimal `{field: value}` overlay = the `proposed_change["flags"]` payload.
   - `@dataclass CandidateEvaluation(candidate, deltas, category_deltas, is_improvement, reason)`
   - `candidate_levers(baseline, *, weight_step=0.10)` — boolean/enum levers (when not
     already set) + single-channel weight +/- perturbations (skips negative weights).
   - `evaluate_candidates(runtime, scorers, candidates, baseline, *, noise_margin, regress_tol)`
     — scores each candidate vs baseline on every scorer; `is_improvement` = beats
     noise on ≥1 scorer AND no scorer aggregate and no per-category recall drops past
     `regress_tol`. (Eval budget = whatever each scorer was built with; hold fixed.)
   - `select_best_improvement(evaluations)` — improving candidate with the largest
     total aggregate gain, else None.
   - NOTE: changed the import — `from .retrieval import RetrievalFlags` is now a
     RUNTIME import (was TYPE_CHECKING) because `candidate_levers` uses
     `dataclasses.replace`. No import cycle (retrieval.py does not import self_improve;
     runtime.py imports load_retrieval_flags lazily).

2. `tools/h2/improvement_loop.py` — NEW FILE, the orchestration cycle (untested):
   - `run_improvement_cycle(runtime, store, scorers, *, auto_approve=False, actor="self_improve", noise_margin, regress_tol, weight_step)`
   - Flow: resolve baseline = `load_retrieval_flags(store)` → `candidate_levers` →
     `evaluate_candidates` → `select_best_improvement` → write ONE proposal via
     `store.write_improvement_proposal(kind="ranking_weight", proposed_change={"flags":
     change})` → if `auto_approve`: `record_proposal_decision(approved)` →
     `compute_apply_plan(store)` + `store.replace_retrieval_flag_state(desired)` →
     RE-MEASURE the reconciled state and AUTO-REVERT (reject + re-apply) if any scorer
     regressed past `regress_tol` vs the pre-cycle baseline.
   - Lives in tools/ (not seam_runtime/) on purpose: it orchestrates runtime + scorers
     + proposal store + the apply CLI (`compute_apply_plan` is in
     `tools/h2/improvement_review.py`). Keeps seam_runtime from depending on tools/.

## NEXT STEPS for you (GPT), in order

1. **Write tests** for the proposer core + the cycle. Suggested
   `tests/audit/test_improvement_loop.py`, using a SYNTHETIC `Scorer` that returns a
   controllable `ScoreReport` keyed off `flags` (ignore the runtime). Cover:
   - improvement found + `auto_approve` → proposal written, applied, NOT reverted,
     `load_retrieval_flags(store)` reflects the change.
   - no headroom (constant scorer) → `proposed is None`, nothing applied.
   - `auto_approve=False` → proposal written PENDING, NOT applied (state == baseline).
   - AUTO-REVERT path: this is the one that needs care — `evaluate_candidates` already
     rejects regressors, so a regressing candidate is never proposed. To exercise the
     revert branch, use a STATEFUL fake scorer that reports improvement during the
     candidate eval call but regression on the later post-apply confirm call
     (simulates a measurement that didn't hold). Assert `reverted is True` and the
     applied state is back to baseline.
   Also add a couple of unit tests for `candidate_levers` (skips already-set levers;
   no negative weights) and `evaluate_candidates` (per-category no-regression rejects a
   lever that helps one category but hurts another — the #273 R1 case).
2. **Run full suite**: `python -m pytest tests/` (expect prior 557 passed + your new
   tests; 4 skipped are pre-existing PGVECTOR_TEST_DSN-gated).
3. **Wire a free-LoCoMo `Scorer`** — the proposer over self-probe ALONE will idle (no
   headroom). Build a scorer that uses LoCoMo's real questions + gold-evidence ids and
   measures string-match retrieval recall via `runtime.search_ir(q, flags=...)`,
   `--answerer none --judge none` semantics (NO judge, NO paid). This is the signal
   with headroom. Same `Scorer` protocol; plugs straight into `run_improvement_cycle`.
   Dataset is present at `/home/terrabyte/seam_benchmarks/track_m/locomo/locomo10.json`
   (also `.dataset_store/locomo/locomo10.json`). Ingest path:
   `benchmarks/external/locomo/adapters/seam.py SeamLocomoAdapter.ingest_turn(scope, turn)`
   persists under `ns=f"locomo:{scope}"`; `benchmarks.external.common.dataset.load_locomo_cases(path)`
   returns cases with `.case_id` and `.conversation` (tuple of
   `ConversationTurn(speaker, text, timestamp)`).
4. **A thin CLI** for the cycle (optional this slice): e.g. `improvement cycle` in
   `tools/h2/improvement_review.py` or a new entry, with `--auto-approve`, `--db`,
   scorer selection. Keep propose-only the default; `--auto-approve` opts into the
   autonomous ratchet (operator's "propose-only by default, auto-approve opt-in").
5. **SEAM chain + commit (#291)**: append HISTORY.md (use
   `python -m tools.history.new_entry --agent <you> --status done --supersedes 290
   --topics ... --commits none --refs ... --body "$(cat bodyfile)"`), then
   `tools.history.rebuild_index`, `tools.history.write_snapshot --agent <you>
   --entries 291,290,289`, `tools.streams.rebuild_index --stream history`,
   `tools.streams.rebuild_cross_index`, update PROJECT_STATUS.md handoff (prepend #291,
   demote #290), and verify all four gates. Then branch-commit (do NOT push to main).

## Where PAID LoCoMo fits (answer to the operator's live question)

Paid LoCoMo is NOT the next step and is not required to build/validate the free loop.
It is the OPTIONAL validation tier: run it (operator-confirmed) to (a) confirm that an
accumulated set of free-validated changes is a real ANSWER-ACCURACY gain (not a
string-match artifact), and (b) probe the big levers that the free signal can't trust
— pack char-budget / `search_top_k` (+0.06..+0.14 per the audit doc) are gameable on
free `context_recall` and need a judged run to validate. It implements the same
`Scorer` protocol and is added to the scorer list only when the operator triggers it.

## Verification quick-reference

- Foundation/apply tests:
  `python -m pytest tests/audit/test_self_probe_scorer.py tests/audit/test_h2_apply.py tests/audit/test_retrieval_flags.py tests/audit/test_h2_improvement_review.py -q`
- Full suite: `python -m pytest tests/`
- Reproduce the no-headroom finding (no-paid, ~1 min ingest): ingest LoCoMo conv-26
  via `SeamLocomoAdapter.ingest_turn`, `generate_probes(rt, ns="locomo:<case>",
  kinds=(RecordKind.CLM,))`, score `SelfProbeScorer` under several `RetrievalFlags`
  weightings at a FIXED budget — baseline ties or beats every alternative.
- pgvector is NOT required (self-probe uses the local SQLite vector adapter). For the
  #273 free-LoCoMo lever measurement you'd want pgvector up (`~/.local/bin/docker-up`,
  container `seam-pgvector` :55432) since `semantic_zero` only bites with a live
  vector backend.

## Key files

- `seam_runtime/self_improve.py` — scorer + probes + proposer core (UNCOMMITTED additions)
- `tools/h2/improvement_loop.py` — orchestration cycle (UNCOMMITTED new file)
- `seam_runtime/retrieval.py` — RetrievalFlags (+weights), load_retrieval_flags, coerce_flag_value, _fuse_weighted
- `seam_runtime/runtime.py` — search_ir(flags=) hook, per-runtime flag cache
- `seam_runtime/storage.py` — retrieval_flag_state table + methods
- `tools/h2/improvement_review.py` — propose/approve/reject/apply CLI + compute_apply_plan
- `seam_runtime/improvement.py` — validate_proposal + proposal_blocks_promotion (the gate)
- `tests/audit/test_h2_apply.py`, `tests/audit/test_self_probe_scorer.py`

## Memory cards worth reading (operator's persistent notes)

`project_self_improvement_loop_design.md`, `project_next_audit3_and_drive.md`,
`project_benchmarks_functional_definition.md`, `feedback_no_paid_run_without_prompt.md`,
`feedback_no_claude_attribution.md`, `reference_locomo_audit_doc.md`.
