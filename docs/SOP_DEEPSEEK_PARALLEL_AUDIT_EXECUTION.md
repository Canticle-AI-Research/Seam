# DeepSeek Parallel Audit Execution SOP

## Purpose

This SOP gives DeepSeek a concrete execution blueprint for a SEAM debugging,
systematic audit, verification, and adversarial review pass. It is designed for
DeepSeek to run its own parallel workers while Codex stays out of agent
delegation. The output must be a merge-ready branch plus a final "check my
work" prompt for Codex.

Primary goals:

- Verify audit claims against current `main` before changing code.
- Fix confirmed bugs immediately, with focused regression tests.
- Run an adversarial review pass after implementation.
- Return a clean merge request that applies to current `main`.
- Produce a review prompt that lets Codex independently inspect, test, and
  merge the work.

## Operating Rules

1. Start from current `main`.
2. Read, in order:
   - `PROJECT_STATUS.md`
   - `REPO_LEDGER.md`
   - `HISTORY_INDEX.md`
   - `docs/CODE_LAYOUT.md`
   - `docs/DATA_ROUTING.md`
   - `docs/SOP_DEEP_AUDIT_REMEDIATION_BLUEPRINT.md`
3. Do not read all of `HISTORY.md`; use context packs:
   ```bash
   python3 -m tools.history.build_context_pack --topics audit verify benchmark security --latest 8 --token-budget 2200
   ```
4. Treat `archive/code/`, `docs/archive/`, `build/`, `.venv/`,
   `test_seam/`, caches, and generated artifacts as inactive unless a task
   explicitly targets them.
5. Do not commit secrets, local `.env` values, API tokens, provider session
   links, or private conversation links.
6. Do not stage `.vscode/`, local source drops, generated benchmark bundles,
   `node_modules/`, `dist/`, SQLite test artifacts, or unrelated files.
7. Use existing project patterns first. Prefer narrow fixes over broad
   refactors.
8. If context is missing and the answer cannot be discovered from the repo,
   invoke `ask_user` with the smallest concrete question before changing
   behavior.
9. Preserve the finished WebUI root flow:
   `experimental/webui/src/App.tsx` frames `/dashboard.html` from
   `experimental/webui/public/`. Do not replace the IDE-like dashboard shell
   with flat endpoint panes.
10. Every code fix needs a focused test. Every material pass needs SEAM history
    closeout.

## Anthropic Endpoint Sidenote

If DeepSeek is being run through an Anthropic-compatible endpoint, assume tool
calls may be mediated by a wrapper with stricter turn boundaries than native
DeepSeek execution. Structure work accordingly:

- Dispatch parallel workers as independent, bounded tasks with explicit file
  ownership.
- Avoid relying on long hidden interactive state in one shell session.
- Prefer deterministic commands and explicit artifacts over conversational
  memory.
- When a worker needs tool access, give it a minimal command list and expected
  output contract.
- Keep one coordinator responsible for staging, history protocol, and final
  merge-request text.
- If the endpoint serializes tool calls, keep the same worker split, but run
  the worker tasks in batches and preserve their outputs as written notes.

## Parallel-Agent Topology For DeepSeek

DeepSeek should use parallel agents. Codex should not.

Coordinator responsibilities:

- Own branch state, conflict handling, staging, history protocol, and final MR.
- Assign disjoint file ownership.
- Stop workers from editing the same file set at the same time.
- Make final decisions on stale vs valid findings.
- Ensure all checks pass after worker changes are integrated.

Worker lanes:

1. Runtime/Data Safety Worker
   - Scope: `seam_runtime/runtime.py`, `seam_runtime/storage.py`,
     `seam_runtime/vector.py`, `seam_runtime/vector_adapters.py`,
     runtime tests.
   - Focus: data loss, transactions, rollback paths, vector indexing,
     pagination, O(N) scans, stale index semantics.

2. API/Security Worker
   - Scope: `seam_runtime/server.py`, REST tests, auth/rate-limit/body-size
     checks, dashboard shell exposure policy notes.
   - Focus: auth defaults, rate limiter behavior, input bounds, remote bind
     guardrails, unsafe command surfaces.

3. Tooling/History Worker
   - Scope: `tools/history/`, `tools/streams/`, history tests, continuity
     gates.
   - Focus: append-only safety, hash checks, route verification, stream
     atomicity, snapshot correctness.

4. Installer/Dashboard Worker
   - Scope: `seam_runtime/installer.py`, `seam_runtime/dashboard.py`,
     `experimental/webui/`, installer/dashboard tests.
   - Focus: shell/path injection, local env permissions, WebUI REST wiring,
     operator-only command semantics.

5. Benchmark Worker
   - Scope: benchmark commands, `seam_runtime/benchmarks.py`, benchmark docs,
     registry, quickstart flows.
   - Focus: reproducible smoke runs, gate/diff readiness, temp artifact cleanup,
     no generated bundle commits unless explicitly promoted.

6. Adversarial Reviewer
   - Scope: read-only review over the full integrated diff.
   - Focus: regressions, missed tests, security bypasses, rollback failure
     modes, flaky assumptions, incorrect history protocol, stale claims.
   - Must not implement first-pass fixes. It reports defects to the
     coordinator, who assigns fixes.

## Execution Phases

### Phase 0: Branch And Baseline

1. Confirm repo and branch:
   ```bash
   git status --short --branch
   git rev-parse --show-toplevel
   git rev-parse --abbrev-ref HEAD
   ```
2. Create a branch:
   ```bash
   git switch -c deepseek/audit-debug-benchmark-pass
   ```
3. Record current commit:
   ```bash
   git rev-parse HEAD
   ```
4. Run baseline gates:
   ```bash
   python3 -m tools.history.verify_integrity
   python3 -m tools.history.verify_routing
   python3 -m tools.history.verify_continuity
   python3 -m tools.streams.verify_streams
   ```
5. Run baseline tests with the repo venv if present:
   ```bash
   .venv/bin/python -m pytest test_seam_all/ tools/history/ tools/streams/ -q
   ```

If `.venv/bin/python` is unavailable, run:

```bash
python3 -m pytest test_seam_all/ tools/history/ tools/streams/ -q
```

If pytest is missing, stop and invoke `ask_user` for the intended test
environment.

### Phase 1: Claim Calibration

Each worker must produce a table:

| Claim | Current? | Evidence | Risk | Proposed Action |
|---|---|---|---|---|

Rules:

- Current means confirmed against current files, not copied from old audit text.
- Stale means already fixed or no longer applicable.
- Policy-dependent means the behavior is intentional but needs an operator
  decision before changing.
- Invalid means the claim does not match code or tests.

Recommended searches:

```bash
rg -n "persist_ir|rollback|delete_ir|BEGIN|COMMIT" seam_runtime tests test_seam_all
rg -n "RateLimiter|SEAM_API_TOKEN|Authorization|max_body|compile_text" seam_runtime/server.py test_seam_all
rg -n "subprocess.run|powershell|SHELL|shell" seam_runtime/dashboard.py seam_runtime/installer.py test_seam_all
rg -n "load_ir|select \\*|vector_index|cosine|stale_records" seam_runtime tests test_seam_all
rg -n "verify_integrity|verify_continuity|write_snapshot|append_event" tools/history tools/streams
```

### Phase 2: Fix Selection

Fix immediately when all are true:

- The claim is current.
- The blast radius is narrow enough for the current pass.
- A focused regression test can be written.
- The fix does not require changing operator policy.

Defer when any are true:

- It needs a product/security policy decision.
- It requires a large architecture replacement.
- It changes benchmark methodology without a baseline.
- It conflicts with another active branch.

For each deferred item, update the SOP or create a backlog note with:

- Current evidence
- Risk
- Blocking decision
- Suggested owner/file scope
- Minimal acceptance criteria

### Phase 3: Test-First Fixes

For each fix:

1. Add or identify a focused failing test.
2. Run the focused test and capture failure.
3. Implement the smallest code change.
4. Re-run the focused test.
5. Run nearby tests.
6. Run compile checks:
   ```bash
   .venv/bin/python -m py_compile <touched python files>
   .venv/bin/python -m compileall -q seam_runtime experimental tools scripts installers
   ```

Do not batch unrelated fixes into one untested edit.

### Phase 4: Benchmark Readiness

Benchmark Worker should wire and run only smoke-level checks unless the
operator explicitly authorizes heavy runs.

Required smoke commands:

```bash
.venv/bin/python -m seam bench external --plan
.venv/bin/python -m seam bench external --quickstart locomo --adapter seam --judge stub
.venv/bin/python -m seam benchmark run long_context --format json
```

If a command differs from actual CLI syntax, fix the docs/SOP command examples
or report the mismatch. Do not fake benchmark success.

Benchmark claims must include:

- exact command
- git SHA
- bundle path if emitted
- bundle hash if emitted
- case/fixture hashes when available
- pass/fail/gate status
- skipped reason if not run

### Phase 5: Adversarial Review

After all first-pass fixes, the Adversarial Reviewer must inspect:

```bash
git diff --stat main...HEAD
git diff main...HEAD -- seam_runtime tools tests test_seam_all experimental docs
```

Review checklist:

- Does each bug fix have a regression test?
- Can a rollback failure still lose data silently?
- Can auth/rate limiting be bypassed by concurrency or config?
- Can command/file path inputs cross a trust boundary unexpectedly?
- Did any generated/local artifacts get staged?
- Did any WebUI change break the finished dashboard root?
- Did any benchmark command claim success without a bundle/gate where required?
- Did history/snapshot/cross-index updates match AGENTS.md?
- Are there stale claims presented as current facts?

Any blocker found by adversarial review must be fixed before returning the
merge request.

### Phase 6: Full Verification

Run:

```bash
git diff --check
.venv/bin/python -m pytest test_seam_all/ tools/history/ tools/streams/ -q
.venv/bin/python -m py_compile seam.py
.venv/bin/python -m compileall -q seam_runtime experimental tools scripts installers
npm --prefix experimental/webui run test
npm --prefix experimental/webui run build
python3 -m tools.history.verify_integrity
python3 -m tools.history.verify_routing
python3 -m tools.history.verify_continuity
python3 -m tools.streams.verify_streams
```

If WebUI dependencies are missing, report that explicitly. Do not install or
commit `node_modules/`.

Secret/session-link scan:

```bash
git diff -- . ':!docs/archive' ':!archive/code' \
  | rg -n "sk-[A-Za-z0-9_-]+|ghp_[A-Za-z0-9_]+|BEGIN (RSA |OPENSSH |EC |)PRIVATE KEY|share\\.openai|chatgpt\\.com/share|claude\\.ai/share|gemini\\.google\\.com/share|https://[^[:space:]]*(session|thread|conversation)"
```

No output is expected.

### Phase 7: SEAM Continuity Closeout

If state changed:

1. Append one `HISTORY.md` entry.
2. Rebuild `HISTORY_INDEX.md`.
3. Sync/rebuild streams:
   ```bash
   python3 -m tools.streams.history_adapter
   python3 -m tools.streams.rebuild_index
   python3 -m tools.streams.rebuild_cross_index
   ```
4. Write one snapshot:
   ```bash
   python3 -m tools.history.write_snapshot --agent deepseek --entries <newest>,<prior> --token-budget 2600
   ```
5. Run gates again.

Do not hand-edit derived cross-index or stream files except through the tools.

## Merge-Request Requirements

The MR must include:

- Summary of fixes.
- Valid/stale/deferred audit table.
- Tests and command results.
- Benchmark smoke results or skipped reasons.
- Adversarial review findings and fixes.
- Open policy questions for operator.
- Confirmation that generated/local artifacts were not staged.
- The "Codex check my work prompt" below, filled in with actual branch, commit,
  files, and command results.

## Prompt To Give DeepSeek

Copy this prompt to DeepSeek:

```text
You are DeepSeek working in the SEAM repo at /home/terrabyte/Documents/Projects/Seam.

Follow docs/SOP_DEEPSEEK_PARALLEL_AUDIT_EXECUTION.md exactly. Use your own parallel agents/workers; Codex will not use agents. Start from current main, create a branch named deepseek/audit-debug-benchmark-pass, and assign disjoint worker lanes:

1. Runtime/Data Safety
2. API/Security
3. Tooling/History
4. Installer/Dashboard
5. Benchmark
6. Adversarial Reviewer

Read PROJECT_STATUS.md, REPO_LEDGER.md, HISTORY_INDEX.md, docs/CODE_LAYOUT.md, docs/DATA_ROUTING.md, and docs/SOP_DEEP_AUDIT_REMEDIATION_BLUEPRINT.md. Do not read all of HISTORY.md; use tools.history.build_context_pack.

Your job:

- Calibrate audit claims against current code.
- Fix confirmed bugs immediately when the fix is narrow and testable.
- Add focused regression tests for each fix.
- Run an adversarial review after implementation and fix blockers before returning.
- Run the full verification chain from the SOP.
- Preserve experimental/webui root behavior: the Vite root frames /dashboard.html from public/.
- Do not stage .vscode/, node_modules/, dist/, local source drops, test_seam artifacts, generated benchmark bundles, secrets, local .env values, or private session links.
- Invoke ask_user only for missing context that cannot be discovered from repo files and would materially change behavior.

Anthropic-endpoint sidenote: if this session is mediated through an Anthropic-compatible endpoint, keep worker tasks bounded and explicit. Do not rely on hidden long-lived tool state. Parallelize by independent worker outputs and integrate through one coordinator.

Return a merge-ready branch/MR. Your final response must include:

1. Branch name and HEAD commit.
2. Valid/stale/deferred audit table.
3. Files changed.
4. Tests and exact command outputs.
5. Benchmark smoke results or skipped reasons.
6. Adversarial review summary and any fixes made after review.
7. Open questions.
8. A filled-in "Codex check my work prompt" using the template in docs/SOP_DEEPSEEK_PARALLEL_AUDIT_EXECUTION.md.
```

## Prompt DeepSeek Must Return For Codex

DeepSeek must fill this in at the end of its work:

```text
Codex, review DeepSeek's SEAM audit/debug branch.

Repo: /home/terrabyte/Documents/Projects/Seam
Base branch: main
Work branch: <branch>
HEAD commit: <sha>
Merge request / PR: <url or local branch>

Operator constraints:
- Do not use agents.
- Follow AGENTS.md and seam-repo-policy.
- Do not read all of HISTORY.md.
- Preserve unrelated local files and untracked artifacts.
- If you lack context for a merge decision or policy change, ask the user.

DeepSeek claims fixed:
- <item 1: file refs, tests>
- <item 2: file refs, tests>

DeepSeek claims deferred:
- <item 1: reason, policy blocker or scope blocker>

DeepSeek claims stale/invalid:
- <item 1: evidence>

Files changed:
- <path>
- <path>

Verification DeepSeek ran:
- <command> -> <result>
- <command> -> <result>

Benchmark smoke:
- <command> -> <result or skipped reason>

Adversarial review:
- Reviewer found: <findings>
- Fixes after adversarial review: <fixes>
- Remaining risk: <risk>

Requested Codex review:
1. Fetch/check out the branch without overwriting unrelated local files.
2. Inspect git diff against current main.
3. Verify every claimed fix has a focused test.
4. Re-run focused tests, full active suite, WebUI tests/build if touched, and SEAM gates.
5. Check for generated artifacts, secrets, private links, and stale history claims.
6. Resolve merge conflicts against main if any.
7. If clean, merge into main seamlessly and run final gates.
8. If not clean, patch the branch or ask the operator for missing policy context.

Do not trust this summary blindly; verify it from the code and tests.
```

## Codex Merge Handling When DeepSeek Returns

When Codex receives DeepSeek's MR/prompt:

1. Do not use agents.
2. Read current status docs and use bounded history context.
3. Check local dirty state before fetching or checking out.
4. Fetch the branch or inspect the MR.
5. Diff against current `main`.
6. Re-run focused and full verification.
7. Fix merge conflicts or small integration issues directly.
8. Ask the user only when a missing policy decision blocks a safe merge.
9. Merge only when tests, SEAM gates, and artifact/secret scans are clean.
10. Record the merge in `HISTORY.md`, rebuild derived files, write a snapshot,
    and run final gates.
