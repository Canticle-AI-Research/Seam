# Claude.ai subscription benchmark transport verification

[Reports](INDEX.md) · [Procedure](../CLAUDE_CODE_BENCHMARKS.md) ·
[Next chunking work](../roadmap/MEMORY_FORMATION.md)

Chronology: HISTORY#646. Scope: provider wiring on top of runtime baseline
`614141c5aa96fd51d4dee2e09c186bb4035c0377`. The sanitized smoke summary pins
the actual source-file hashes used for the recorded run. A successful
quickstart is a connectivity/integration result, not a formation improvement,
paid development baseline, holdout evaluation or published comparator score.

## Question and method

Can the existing SEAM LoCoMo runner answer and judge through the operator's
funded Claude.ai account without an API key? The operator reported roughly
$50 on Claude.ai and explicitly authorized wiring, bounded paid verification,
push and protected merge. No account balance was independently verified.

The installed Claude Code 2.1.270 reported a Claude.ai Pro login with the
API-key environment excluded. Execution used safe mode, no tools, no MCP,
no conversation persistence, a temporary working directory, stdin prompts,
and pinned `claude-haiku-4-5-20251001` for both roles. The unchanged runner
retrieval configuration was `legacy-weighted`, search top-k 100 and context
budget 8000 characters. A real cached embedding preflight and SQLite store
were used; neither embedding nor retrieval was stubbed in the paid smoke.

The bundled quickstart selection was `conv-1::q0`, not a cherry-picked
development miss. Both answerer and judge were selected explicitly as
`claude-code`. The shared process had two call reservations of $0.10 each,
one worker, and provider retry attempts limited to one. Inference required
the existing `--allow-paid` gate. The local hermetic suite separately covered
retries, parallel reservations and failure behavior.

## Observed results and limits

The initial connection check returned its exact expected response. The
initial runner smoke, frozen-source smoke and post-review repaired-source
smoke all returned
`Japan (Tokyo, Kyoto, and Osaka)` and a `correct` judge verdict. The post-review run exited successfully with unchanged source hashes and
reported $0.008487 across answerer and judge. All seven inference calls in
this implementation session reported $0.027124 in total. These runs
exercise the same small fixture; they do not estimate benchmark variance.

Claude Code's top-level token usage differed from its per-model usage totals.
Both are preserved separately, along with `costBasis=list`. The evidence
records CLI-reported usage value; it is not a verified debit from Claude.ai
credits. The procedure explains process-local reservations, timeout behavior,
in-flight overshoot and the absence of an account-wide spending ceiling.

Independent review identified that failed verdict parsing could discard
otherwise-valid CLI usage. The repair preserves known usage on both primary
and cross-judge failures and keeps the runner exit nonzero. Failure tests
verify that malformed verdict text is not echoed into the diagnostic report.
An unsuccessful attempt with no valid accounting remains unknown; no cost is
invented for it.

## Reproduction and verification

Use the [one-case command](../CLAUDE_CODE_BENCHMARKS.md) with the pinned model
and recorded limits. The successful paid smoke is deliberately separate
from hermetic tests that invoke a fake external executable. The final
source hashes and usage totals are in the summary below; the detailed
handoff records the final test and GitHub delivery boundary.

```bash
python -m pytest tests/audit/test_claude_code_benchmark.py \
  tests/audit/test_shared_answerer.py tests/audit/test_run_record.py \
  tests/audit/test_openai_judge_gpt5.py tests/audit/test_judged_scorer.py \
  tests/audit/test_locomo_result_durability.py -q -o addopts=''
```

The six-module command above passed 97 tests after the accounting repair.
Independent assurance separately passed 58 tests across
`test_claude_code_benchmark.py` and `test_shared_answerer.py`, plus an
independent malformed-verdict reproduction for both judge roles. Eleven
witnessed red/green cycles cover the changed runtime paths; original evidence
and the subsequent repair cycle are preserved separately in the local
delivery evidence, with current source hashes in the summary.

Direct API behavior stays unchanged. CLI batch judging is rejected before
spending; judge-only and cross-judge subscription calls require paid opt-in.
Usage persists even without `--save-context`. Source collection, Ruff,
continuity, secret scanning, independent assurance and exact-head required CI
are part of the provider PR's closeout.

## Evidence manifest

| Artifact | SHA-256 |
| --- | --- |
| [Frozen-source quickstart result](evidence/2026-09-14-claude-code-benchmarks/final-quickstart-smoke.json) (`evidence/2026-09-14-claude-code-benchmarks/final-quickstart-smoke.json`) | `fe82305bcafc9f3b095354f1dcebd18b39e1a13552fed0f2f0a4e0d97f945e55` |
| [Post-review repaired-source quickstart result](evidence/2026-09-14-claude-code-benchmarks/reviewed-quickstart-smoke.json) (`evidence/2026-09-14-claude-code-benchmarks/reviewed-quickstart-smoke.json`) | `6d68b2aeac11c7854393e025910e534b5d2ee83927c6aa687c060fa6b2dbcd7f` |
| [Source and spend summary](evidence/2026-09-14-claude-code-benchmarks/smoke-summary.json) (`evidence/2026-09-14-claude-code-benchmarks/smoke-summary.json`) | `c67cf6a11fba0cac1691dee62f59075ef78c6c47e3a92a317312d1bcc54eb938` |
