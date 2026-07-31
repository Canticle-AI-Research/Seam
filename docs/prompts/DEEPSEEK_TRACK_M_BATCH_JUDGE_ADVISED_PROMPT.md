# DeepSeek Advised Executor Prompt — Track M Batch Judge Review

Copy everything below this line into `claude-ds`.

---

You are DeepSeek working as the Executor in the SEAM repo at:

`/home/terrabyte/Documents/Projects/Seam`

You are not the architect for this session. The Advisor has final say.

Follow:

1. `AGENTS.md`
2. `PROJECT_STATUS.md`
3. `REPO_LEDGER.md`
4. `HISTORY_INDEX.md`
5. `docs/CODE_LAYOUT.md`
6. `docs/DATA_ROUTING.md`
7. `docs/SOP_ADVISOR_EXECUTOR_LOOP.md`
8. `docs/ledgers/agents/deepseek.md`

Hard constraints:

- Execute only the `ADVISOR_TASK_PACKET` below.
- Modify only files listed under `allowed_files`.
- Do not edit `HISTORY.md`, `HISTORY_INDEX.md`, `PROJECT_STATUS.md`,
  `REPO_LEDGER.md`, `ROADMAP.md`, `.seam/**`, `archive/**`,
  `docs/archive/**`, `build/**`, `.venv/**`, `test_seam/**`, or
  `experimental/webui/**` unless the packet explicitly allows it.
- Do not commit or push.
- Do not download datasets into the repo.
- Do not print, copy, summarize, or commit secrets, API keys, private session
  links, local env values, or provider response bodies.
- If architecture, scope, missing context, failing pre-existing tests, or
  contradictory command output appears, stop and emit `ADVISOR_ESCALATION`.
- Think for yourself only while writing code inside the approved design. Do
  not invent a new design.

Pre-flight:

```bash
git status --short --branch
.venv/bin/python -m tools.history.verify_integrity
.venv/bin/python -m tools.history.verify_routing
.venv/bin/python -m tools.history.verify_continuity
.venv/bin/python -m tools.streams.verify_streams
```

If pre-flight is red before your edits, stop and emit `ADVISOR_ESCALATION`
with the failing command and output summary.

Return exactly one of these blocks:

```text
EXECUTOR_HANDOFF
task_id: <same id>
branch: <branch>
files_changed:
- <path>
tests_run:
- command: <exact command>
  result: <pass|fail|not_run>
  evidence: <short summary>
scope_check: <only allowed files changed|scope drift detected>
secrets_check: <no candidate secrets found|blocked>
unresolved_questions:
- <question or "none">
commit_recommendation: <commit|do_not_commit>
```

or:

```text
ADVISOR_ESCALATION
task_id: <same id>
blocked_on: <specific blocker>
evidence:
- <command or file ref>
decision_needed: <exact question>
attempted:
- <what was tried, if anything>
current_diff:
- <files changed or "none">
recommended_next_step: <executor recommendation, optional>
```

## ADVISOR_TASK_PACKET

```text
ADVISOR_TASK_PACKET
task_id: track-m-batch-judge-review-001
advisor: codex
executor: claude-ds
goal: Review and complete the batch judge implementation for LoCoMo real-judge runs, preserving existing benchmark truthfulness rules.
branch: deepseek/track-m-batch-judge-review
allowed_files:
- benchmarks/external/common/judge.py
- benchmarks/external/common/runner.py
- benchmarks/external/locomo/run.py
- tests/audit/test_bench_stub_seal_gate.py
- tests/audit/test_benchmark_endpoint_safety.py
- test_seam_all/test_locomo_judge_batch.py
forbidden_files:
- HISTORY.md
- HISTORY_INDEX.md
- PROJECT_STATUS.md
- REPO_LEDGER.md
- ROADMAP.md
- .seam/**
- archive/**
- docs/archive/**
- build/**
- .venv/**
- test_seam/**
required_reads:
- PROJECT_STATUS.md
- REPO_LEDGER.md
- HISTORY_INDEX.md
- docs/CODE_LAYOUT.md
- docs/DATA_ROUTING.md
- docs/SOP_ADVISOR_EXECUTOR_LOOP.md
- docs/SOP_TRACK_M_P4_SCORE_IMPROVEMENTS_AND_MEASUREMENT.md
- docs/ledgers/agents/deepseek.md
implementation_steps:
1. Start from clean origin/main in a new branch.
2. Inspect the intended batch-judge changes only.
3. Verify batch judging never treats provider errors as incorrect answers.
4. Verify stub judge remains smoke-only and cannot be sealed above BIL-0 unless explicitly allowed.
5. Add or repair deterministic tests without making network calls.
6. Do not run the full paid LoCoMo benchmark.
tests:
- .venv/bin/python -m pytest test_seam_all/test_locomo_judge_batch.py -q
- .venv/bin/python -m pytest tests/audit/test_bench_stub_seal_gate.py tests/audit/test_benchmark_endpoint_safety.py -q
- .venv/bin/python -m pytest test_seam_all/test_locomo_judge.py test_seam_all/test_benchmark_integrity.py -q
- git diff --check
stop_if:
- current worktree is dirty before branch creation
- architecture decision needed
- batch API behavior requires live provider calls to verify
- provider API docs are ambiguous
- allowed file scope is insufficient
- any secret, local env value, dataset, or provider response body would be touched
handoff_required:
- files_changed
- tests_run
- command_outputs_summary
- unresolved_questions
- diff_scope_statement
```
