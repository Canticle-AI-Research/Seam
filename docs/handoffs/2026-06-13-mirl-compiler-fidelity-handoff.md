---
handoff_id: 2026-06-13-mirl-compiler-fidelity-handoff
supersedes: 2026-06-08-h2-self-improvement-loop
handoff_status: superseded
history: HISTORY#306
---

# Handoff — MIRL compiler fidelity + governing-contract rule

Date: 2026-06-13
Author: Claude (Fable 5 / Opus 4.8)
Branch state: all work merged to `main` (`HEAD == origin/main`); no open PRs; working tree clean.

## TL;DR

This session found a real bug in `compile_nl`, then built the *measurement and
governance* needed to fix it correctly — but **the compiler itself is not yet
fixed**. The next agent's job is to finish the measurement (`qr`) and then do the
actual rewrite (Stage 2), measured by the spec contract that now exists.

Read first (now mandatory per HISTORY#304): `SEAM_SPEC_V0.1.md` (esp. §2 four-layer
stack, §8 loss model, §22 metrics, §24 promotion rule, §31 north star) and
`docs/MIRL_V1.md`. The audit `docs/audits/2026-06-12-mirl-compile-fidelity.md`
is the live source of truth for the compiler work.

## Honest progress assessment (the operator asked: "are we making measurable progress?")

Be honest with yourself about this. This session moved **foundations**, not the
product metric:

- **The MIRL ingest bug is NOT fixed.** `compile_nl` still fabricates
  `(project:SEAM, goal, <slug>)` for every real memory. `sr` is still `0.333`,
  `cr` is still `~0.03`. Zero functional change to the compiler shipped.
- **What DID ship is the apparatus to fix it correctly and prove it:** the
  fidelity contract + failing baseline (#303), the spec-metric reconciliation
  (#305), and the rule that prevents the drift that caused the bug (#304). Plus
  an unrelated maintenance closeout (#301) and the paid judged scorer (#302).
- **Two course-corrections cost cycles:** I mis-judged `SEAM-RC/1` as "broken"
  (it meets its lossless+queryable contract; I measured it against a
  token-reduction contract it was never meant to satisfy), and I worked without
  reading the spec until the operator stopped me. Both are now guard-railed by
  the #304 rule.

So: measurable progress on the ruler and the rules; **the number that matters
(`sr`/`cr` on real memories) has not moved yet.** It moves in Stage 2.

## What landed on `main` this session (all merged)

- **#301** — maintenance closeout: merged Dependabot webui PRs; fixed the weekly
  Dependabot docker job (`docker` → `docker-compose` ecosystem; it failed every
  run); recorded that PR #70 (SSRF) merged and all 10 CodeQL alerts are resolved.
  Repo is security-clean: 0 open CodeQL, 0 open Dependabot security alerts.
- **#302** — the PAID judged holdout scorer
  (`benchmarks/external/locomo/judged_scorer.py` + `tools/h2/paid_validation.py`
  + `seam improve validate`). Operator-gated: **dry-run by default; spends ONLY
  with `--confirm-paid`; never auto-run.** This was the last piece of the
  self-improvement stack from #292/#297. NOT yet run (no paid run this session).
- **#303** — MIRL compile fidelity harness + failing baseline
  (`benchmarks/fidelity/contract.py`, `golden.py`,
  `tests/fidelity/test_compile_fidelity.py`). 7 checks; the stub's violations are
  `xfail(strict=True)` = a ratchet (a fix flips xfail→XPASS→hard fail).
- **#304** — PROTOCOL: the SEAM spec is now a mandatory session-start read and the
  governing contract (AGENTS.md Session Start item 6 + REPO_LEDGER lead decision).
  This is the structural fix for *why* the bug existed: the spec was never in the
  read order, so implementations drifted from it.
- **#305** — reconciled the fidelity harness to the spec's own §22/§24 metrics
  (`benchmarks/fidelity/spec_metrics.py`): `cr/rr/sr/pr/tr` + the §24
  `passes_promotion` gate. `qr` deferred. Fixed a latent Stage-1 bug so the
  contract is satisfiable by a faithful compiler.

Full suite at handoff: **632 passed, 11 xfailed, 0 skipped** (`pytest tests/`
with `PGVECTOR_TEST_DSN` + strict no-skip).

## The bug, precisely (for the next agent)

`seam_runtime/nl.py:compile_nl` — behind `seam remember`, the shell, the dashboard
remember box, the MCP `ingest` tool, and REST `/ingest` — is a template overfit to
SEAM's own self-description. Root lines: `_extract_goal` falls back to
`_normalize_phrase(text)` (nl.py:~244); `_infer_project_name` returns `"SEAM"`
(nl.py:~278); `add_claim` hardcodes `subject=project_id` + default predicate
`"goal"` (nl.py:~48/59/64). So every memory → `(project:SEAM, goal, slug-of-input)`
with hardcoded `user:local_user` + `project:SEAM` entities. It violates the spec's
§3.2 compiler responsibilities + §8 recoverable-meaning. The LoCoMo benchmark path
DODGES it (it uses the richer `compile_conversation_turn`, nl.py:~96), but the
self-improvement loop's "tune on the user's own corpus" mode is poisoned by it.

## The spec-metric baseline (what a fix must beat)

```
case                                   cr     rr     sr     pr     tr   qr
single_fact_ownership               0.018  0.333  0.333  1.000  1.000 None
two_independent_facts               0.040  0.500  0.333  1.000  1.000 None
personal_event_with_place_and_date  0.024  0.500  0.333  1.000  1.000 None
schedule_change                     0.031  0.750  0.333  1.000  1.000 None
self_description_overfit            0.031  1.000  1.000  1.000  1.000 None
```

`sr` (semantic retention, structured triple match) is the clean discriminator;
`cr` (NL→PACK compression ratio) is the north-star density axis the stub tanks;
`pr`/`tr` are 1.0 and do NOT expose the stub (honest). The §24 gate rejects the
stub on every case.

## Resume point — do these in order

1. **Slice 2 — `qr` (retrieval quality).** Implement `retrieval_quality` in
   `benchmarks/fidelity/spec_metrics.py` (currently returns `None`): build a temp
   `SeamRuntime`, persist the compiled batch, `search_ir(golden.query)`, check the
   gold record is in top-k = `retrieval_success@k`. Add a golden `query` + gold
   field. This completes the §24 gate (`qr` is the "directly queryable" axis the
   spec and operator both require). It needs the embedder, so keep the golden set
   tiny or mark the qr test `@pytest.mark.external` if it slows CI.
2. **Stage 2 — the deterministic floor rewrite of `compile_nl`.** Segment input
   into propositions; verbatim RAW + per-proposition SPAN with real offsets;
   entities from high-confidence rules; **never fabricate a claim** (no
   `project:SEAM`/`goal` default). Target: raise `sr`→~1.0 and `rr`→1.0 on real
   memories, keep `pr=1.0`, improve `cr`. As properties pass, the Stage-1 xfails
   flip to XPASS (hard fail) → remove them from each golden's `baseline_failures`.
3. **Stage 3** — unify `compile_nl` and `compile_conversation_turn`; delete the
   stub. **Stage 4** — opt-in LLM extractor (local Ollama default) for rich
   triples. **Stage 5** — migrate existing degenerate records (keep RAW, replace
   derived ENT/CLM/STA) + re-validate the self-probe loop on a real corpus.

## Open decision (operator) — the free-floor backend

Recommended (operator not yet final): **honest-minimal, zero-new-dep floor**
(segment + verbatim RAW + entities only on high-confidence rules, never fabricate)
**+ opt-in local Ollama** for rich S-P-O triples; hold spaCy as a pluggable
offline-triples option, not default/core. A heavier hand-rolled extractor is RULED
OUT. The operator said dependencies are acceptable, so spaCy-as-default is on the
table if they prefer offline triples without an LLM. The fidelity contract is
invariant across this choice.

## Hard constraints (carry forward)

- Read the spec before touching SEAM product behavior (AGENTS.md item 6).
- A component is "broken" only if it fails ITS contract. RC/1 = lossless +
  directly-queryable + exact rebuild (token reduction is PACK + the symbol loop +
  Track J, NOT RC/1). Don't repeat the RC/1 misjudgment.
- Never auto-run a paid scorer; `seam improve validate` needs `--confirm-paid`.
- No "Co-Authored-By: Claude" / generation footers in commits.
- `main` is protected — branch + PR only. After any repo-state change: append
  HISTORY, rebuild index, snapshot, run verify_integrity/routing/continuity/streams.
- `backup/local-pgvector-bootstrap` is a deliberate backup — do NOT delete.

## Branch hygiene note

Cleaned up the merged branches from this session. Remaining non-`main` remote
branches not owned by this session and left for the operator:
`claude/confident-albattani-awIbm`, `feat/dashboard-functional` (PR #54 merged —
deletable), `handoff/archive` (infra), `backup/local-pgvector-bootstrap` (KEEP).
