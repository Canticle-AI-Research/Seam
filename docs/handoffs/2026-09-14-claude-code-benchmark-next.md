---
handoff_id: 2026-09-14-claude-code-benchmark-next
supersedes: 2026-09-12-memory-formation-roadmap
handoff_status: superseded
history: HISTORY#646
---

# Claude subscription benchmarks and chunking continuation

## Start here

The operator wants to start measuring memory formation before changing
chunking, use the money already on Claude.ai, and resume this work from
ChatGPT using the handoff on GitHub. The detailed execution authority remains
[Memory formation](../roadmap/MEMORY_FORMATION.md), including all fourteen
original requirements, Sleep/Daydream and the graph/reporting direction.

The provider funding assumption is corrected: the operator reported roughly
$50 on Claude.ai and deliberately unset the API key. This is not API Console
credit. Do not ask them to restore a key, purchase API credit, or paste secrets
into chat. This session's inherited API key was excluded from subscription
execution. The installed Claude Code authenticated as `claude.ai`, `firstParty`,
Pro with API credentials excluded. This proves the login route, not the
balance or its actual debit ledger.

The new explicit `claude-code` answerer/judge route uses supported Claude Code
noninteractive execution. The old `claude` choice still uses the API. Follow
[the exact setup and commands](../CLAUDE_CODE_BENCHMARKS.md); the two transports
must not be silently mixed in a baseline/candidate comparison.

## What this delivery covers

Provider transport and its integration into the existing LoCoMo benchmark
runner, with isolated prompts, subscription authentication checks, shared
process allowances, sanitized usage metadata, and hermetic behavioral tests.
No formation runtime, retrieval weights, identity policy, stored user memory,
website, DNS or API credential configuration is changed by this delivery.

The benchmark interfaces are `generate_short_answer`,
`SeamLocomoAdapter.answer`, `build_judge(...).score`, and
`python -m benchmarks.external.locomo.run`. Tests exercise these interfaces;
the fake CLI stands in for the external process, not the memory mechanism.
The real smoke must separately prove the installed CLI and real adapter path.

The transport has no tools, project instructions, user customizations or
saved-session continuation. Prompts use stdin in a temporary working directory.
It uses the intended stored subscription login; no OAuth token extraction or
API-key fallback is involved. Pin the requested model and retain the served
model and transport version. A missing CLI/login, malformed result or exhausted
allowance must remain a failure rather than a zero-quality result.

## Benchmark sequence from here

1. Verify this provider PR's merge and its exact required checks. Read the
   provider procedure and this handoff's verification evidence before spending.
2. Review M1's existing audit candidate on [PR #264](https://github.com/Canticle-AI-Research/Seam/pull/264).
   Its recorded examples include attribution mixing, repeated-event intake
   loss and segmentation coverage gaps. They remain scoped synthetic findings,
   not a generalization result. Resolve its independent acceptance condition.
3. Finish B1's formation metadata contract and E1's evaluation design: exact
   dataset/hash and development selection, held-out partition, baseline SHA,
   prompts, answerer/judge model, retrieval configuration, character/token
   budgets, metrics, uncertainty/no-change controls and campaign cost limits.
4. Run and retain a paid development baseline with unchanged formation before
   implementing the first candidate. Do not select only known misses; do not
   expose the locked holdout to tuning. A successful one-case transport smoke
   does not substitute for this baseline.
5. Freeze M2's examples and expected outputs; implement M3's bounded,
   context-preserving segmentation first, then M4's temporal entity views.
   Freshly re-ingest each formation arm. `--keep-db` would bypass the changed
   ingestion behavior and is unsuitable for that comparison.
6. Compare candidates against fresh matched baselines and unchanged controls;
   measure actual answer quality alongside formation/provenance/time fidelity.
   M5 still requires its E1/E2 and B2 reproducibility prerequisites. Website
   deployment is independent of this sequence.

Do not call the provider smoke a chunking baseline or mark the whole E1/E2
campaign complete from connectivity. BIL-3 metadata design/implementation,
M2-M5, Sleep/Daydream and product qualification remain separate roadmap exits.

## Spend and billing boundary

Only a small implementation smoke is authorized in this delivery; the roughly
$50 balance is not an instruction to consume it. The initial direct CLI check
returned the exact requested text and reported $0.001555 usage value. Its
per-model billing metadata identified list pricing. Reported CLI costs are
not verified subscription-account debits. A full campaign needs its own
documented bounded selection and allowance.

The procedure lists the four allowance/timeout settings. Reservations cover
both answerer and judge calls in a Python process; failed attempts consume
them, and a restarted Python process starts a fresh allowance. The CLI cap
is best effort and may overshoot for an in-flight request. Do not represent
these settings as an account-wide or cross-process hard dollar ceiling.

## Git and parallel work boundaries

This provider branch starts from protected main
`614141c5aa96fd51d4dee2e09c186bb4035c0377` (merged roadmap PR #261).
Its source branch is `feat/claude-code-benchmarks-20260914`.
The user explicitly authorized push, protected merge and this detailed handoff.
Observe GitHub before claiming those steps complete.

PR #264 remains a separate draft at its last inspected head
`18abe44236021ba0bfddb78f55d067754c0d42ef`. Its full scope remains
`TDD_UNPROVEN` for `tools/memory_formation_m1.py`; a new independent
`NOT_QUALIFIED` receipt was validated and stored for that exact state.
Passing new tests cannot invent the missing historical red phase. This provider
delivery neither waives that condition nor merges its site/audit helper.

The reports branch's newest handoff is
[reports/domain publication](https://github.com/Canticle-AI-Research/Seam/blob/feat/seam-reports-pages-20260912/docs/handoffs/2026-09-13-reports-domain-publication-next.md).
It is branch-local, with HISTORY through #653. Its chronology and registry
will require reconciliation against new main work before it can merge; never
replace main's HISTORY with its branch copy. Preserve its source commit
`e01284de37140b2d56a2c53e68d45f309f7e89e5` when integrating the pinned report.
The authorized future hostname remains `reports.canticle.cc`; the operator
owns `canticle.cc`, not `canticle.ai`. That domain work is still pending.

Preserve the dirty primary `docs/deep-audit-20260829` checkout: HISTORY/index,
cross-index/history-stream files, audit/handoff indexes and August audit/handoff
work are unrelated. Its untracked `.codex`, `.disposable`, orchestration data,
old cross-index archive, August audit/handoff and `error.log` are excluded.
Also preserve the audit-cleanup, pretool-hook, standalone M1 and sleep-learning
worktrees. No stash was created by this provider task.

## Verification checkpoint

The [verification report](../audits/2026-09-14-claude-code-benchmarks.md)
links the sanitized paid results, pinned source hashes and spend summary.
The final reviewed-code one-case quickstart exited successfully and answered
`Japan (Tokyo, Kyoto, and Osaka)` with a `correct` judge verdict. Its answerer
and judge reported $0.008487; all seven implementation inference calls
reported $0.027124 total. Actual subscription debits remain unverified.

The six-module regression command in that report passed 97 tests after the
accounting repair. Independent assurance passed 58 tests in
`tests/audit/test_claude_code_benchmark.py` and
`tests/audit/test_shared_answerer.py`, plus separate public-CLI reproductions
of primary/cross-judge malformed-verdict failures. Known costs survive those
failures, exit status remains nonzero and raw malformed text is excluded.
Eleven witnessed red/green cycles are recorded in canonical local session
state. Original logs and repair logs retain separate hashes; the combined
local delivery manifest pins current source and final regression evidence.

Local evidence is under
`/home/terrabyte/LLM-Logs/codex/benchmarks/20260914-claude-code/`.
The tracked report provides the portable smoke evidence for ChatGPT readers;
private CLI envelopes, authentication material and conversation links are not
part of the handoff. The release receipt is local orchestration evidence.

For delivery state, inspect the PR for source branch
`feat/claude-code-benchmarks-20260914` and confirm its merged commit is on
`main`; this authored checkpoint does not pre-claim that later merge action.
Required checks are `repo-hygiene`, `chroma-real-smoke` and
`locomo-quickstart-bil2` on the exact pushed head. The `test-and-benchmark`
matrix is advisory unless its failures are caused by this change. No report
site deployment or full benchmark campaign follows from this provider merge.
