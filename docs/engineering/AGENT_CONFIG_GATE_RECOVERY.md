# Agent-Configuration Required-Gate Recovery

## Request

Close the four unresolved agent-configuration findings from PR #258 as one
security-sensitive CI and policy slice. The change must reject forbidden
tracked agent-local paths even when the staged diff is empty, keep the exact
root Claude memory pin guarantees, make the validator an unconditional part of
the required `repo-hygiene` check, and prove parity across every canonical
local enforcement surface.

This plan was stacked on PR #273 at
`efb30b73f97011e887a29e94c40e2167cb627e73`. Both stacked PRs (#273 and #274)
have since merged through the protected path; see the current handoff in
[the handoff registry](../handoffs/INDEX.md) for the landed state.

## Change classes

- Security boundary and repository policy.
- Required CI gate.
- Local/CI parity regression coverage.
- Operator documentation and continuity.

## Governing contracts

- `AGENTS.md#Security Rules` — agent-local state and secrets must not enter
  tracked history; required local gates cannot be weaker than CI.
- `REPO_LEDGER.md#Repository safety and agent-local configuration` — the root
  Claude memory pin is the only tracked Claude configuration object.
- `docs/CLAUDE_MEMORY.md` — the pin has an exact object, path, size, mode, and
  staged-object contract.
- `tools/git/verify_agent_config.py` — canonical executable policy.
- `tools/history/closeout.py#PREFLIGHT_GATES` — canonical local gate inventory.

## Current-state trace

`git index` -> `tools.git.verify_agent_config` -> Claude preflight, canonical
pre-commit hook, closeout, and GitHub Actions -> required repository hygiene
status.

At the baseline, the validator applies its non-Claude rejection only to paths
returned by `git diff --cached`. A forbidden path already present in `HEAD`
therefore passes both validator modes when the staged diff is empty. The
required `repo-hygiene` job omits the validator, while the advisory
`test-and-benchmark` job runs it. The local parity audit recognizes only
`run_gate` shell invocations, so it cannot express or preserve the intentionally
stronger early bare-abort invocation in the pre-commit hook.

## Canonical and derived state

- Canonical: validator policy, required CI workflow, local wrapper source,
  audit tests, this plan, ledger policy, and operator documentation.
- Derived: `HISTORY_INDEX.md`, history/roadmap stream indexes, cross-index, and
  session snapshot.
- Generated/local-only: pytest output, `.context-handoffs/`, orchestration
  request/receipt state, and GitHub check logs.

## Affected invariants

- `verify(repo, *, staged=False) -> list[str]` and its CLI remain unchanged.
- `.claude/settings.json` remains the one required root pin with exact JSON,
  regular nonexecutable stage-zero metadata, bounded staged blob reads, and
  working-tree versus staged-object semantics.
- Every index path is classified independently of commit history and staged
  diff metadata.
- Only the nine exact tracked `.opencode/skills/*/SKILL.md` paths already in
  the repository are compatible. They are optional project documentation, not
  required files. The literal set lives in the validator rather than copied
  prose.
- A compatible path must have regular, nonexecutable, stage-zero index
  metadata. Symlinks, unresolved entries, case variants, renamed siblings,
  arbitrary `SKILL.md` files, and nested variants are forbidden.
- Other paths containing case-insensitive `.claude`, `.opencode`, or `.agents`
  directory components are forbidden, as are case-insensitive root
  `opencode.json` and `opencode.jsonc` names.
- The pre-commit hook keeps the `--staged` validator as an early, immediately
  aborting scope block before merge/rebase early exits.
- Required `repo-hygiene` runs the validator unconditionally. No new check name
  or ruleset is introduced.

## Hypothesis

Given the baseline at `efb30b73f97011e887a29e94c40e2167cb627e73`,
changing path classification from staged-diff membership to deterministic
inspection of every index entry should close the committed-file bypass without
weakening the root pin or admitting broader OpenCode state. Adding the existing
validator to required hygiene and extending structural parity tests should make
future omissions or conditional suppression fail locally and in CI.

The hypothesis is falsified by any accepted forbidden path, rejected exact
compatibility path, weakened pin guarantee, missing local/required-CI
invocation, or regression outside this policy slice.

## Baseline and TDD evidence

- Commit: `efb30b73f97011e887a29e94c40e2167cb627e73`.
- Live branch basis: PR #273 exact head; `origin/main` was
  `66fd3f93081712871ff827e756026c3e73c71790` at branch creation.
- Existing focused audit baseline supplied by the approved architecture review:
  45 passed.
- RED regressions: the focused collection found 101 tests. The unchanged
  implementation then produced 27 failures and 74 passes: 26 failures covered
  committed forbidden paths, near-miss paths, invalid compatibility metadata,
  unresolved index state, and working-tree symlinks; the remaining failure
  proved `repo-hygiene` omitted the validator. Parser and mutation controls
  passed, including removal, advisory-only, staged-argument, abort-strength,
  early-placement, and CI suppression/conditional cases.
- Configuration: shared repository virtual environment; no paid or product
  benchmark.

## Planned files

- `tools/git/verify_agent_config.py` — deterministic all-index classification
  and the literal compatibility set.
- `tests/audit/test_claude_memory_pin.py` — real temporary-repository path and
  metadata regressions.
- `tests/audit/test_local_gates_match_ci.py` — parser and mutation-based parity
  regressions.
- `.github/workflows/ci.yml` — unconditional required-hygiene invocation.
- `docs/SOP_PRODUCTION_READINESS_REMEDIATION.md` — correct the absolute
  prohibition.
- `docs/CLAUDE_MEMORY.md` and `REPO_LEDGER.md` — canonical policy pointers and
  narrow compatibility rule.
- `docs/engineering/README.md` — navigation to this plan.
- Continuity and handoff files generated at closeout.

## Security and failure analysis

- New attacker-controlled inputs: none. Existing Git index path, mode, stage,
  and blob metadata remain untrusted and are inspected without following
  symlinks.
- Partial failures: malformed index output, unreadable staged blobs, duplicate
  pin entries, unresolved stages, nonregular modes, and oversized pin blobs
  fail closed with actionable validation errors.
- Rollback: revert this focused branch. No schema, persistent runtime state, or
  external administration changes are involved.
- Scope/isolation effects: this closes repository-scope and CI-bypass findings
  only. Runner isolation and general content safety remain separate work.
- Resource bounds: pin reads retain the existing size bound; compatibility
  classification is linear in tracked index entries.
- Secret handling: candidate files and the committed range receive content-free
  secret/session scans; no credential-bearing output is recorded.

## Verification plan

- RED: temporary Git repositories prove committed forbidden paths with empty
  staged diffs; exact compatibility and near-miss metadata/path cases prove the
  allowlist; copied/mutated wrappers and workflow prove removal, advisory-only,
  scoping, abort, order, and conditional-bypass failures.
- Focused: collection plus the five relevant audit modules, both validator
  modes, Ruff, and `git diff --check`.
- Full regression: all active test roots with the real pgvector service through
  the established local guard, with `HF_HUB_CACHE` preserved and no unapproved
  skips.
- Benchmark: not applicable; no product behavior or performance change.
- Continuity: append-only history superseding #648, rebuilt derived state,
  snapshot, all six unsuppressed gates, wiki audit, and working-tree/range
  secret scans.
- Delivery: normal pre-commit, focused draft stacked PR, exact-head CI evidence,
  independent closeout receipt, and a tracked indexed handoff.

## Verification evidence

| Command/scope | Result | Notes |
|---|---|---|
| `pytest --collect-only tests/audit/test_claude_memory_pin.py tests/audit/test_local_gates_match_ci.py tests/audit/test_history_closeout.py` | 101 collected | Collection succeeded before implementation. |
| `pytest tests/audit/test_claude_memory_pin.py tests/audit/test_local_gates_match_ci.py tests/audit/test_history_closeout.py` on the baseline implementation | RED: 27 failed, 74 passed | The failures covered the all-index/metadata bypasses and missing required-CI invocation. |
| The same three-file audit command after implementation | GREEN: 101 passed | Exact RED-to-GREEN witness. |
| `pytest tests/audit/test_claude_memory_pin.py tests/audit/test_local_gates_match_ci.py tests/audit/test_history_closeout.py tests/audit/test_public_safe_gate.py tests/audit/test_github_pr_gates.py` | 158 passed | Required focused audit slice. |
| Both `tools.git.verify_agent_config` modes, `ruff check .`, and `git diff --check` | passed | Working tree, staged index, lint, and whitespace checks. |
| Full approved pytest scope with `PGVECTOR_TEST_DSN` bound and the existing `HF_HUB_CACHE` preserved | First attempt invalid: 48 failed, 19 errors, 3,678 passed, 2 xfailed | `docker-up` had started only the engine; the project pgvector service was absent and failures were connection-refused cascades. This is not qualification evidence. |
| `pytest test_seam_all/ tools/history/test_history_tools.py tools/streams/ tests/ -ra --durations=25 -o addopts= -p no:cacheprovider` with healthy Compose pgvector | 3,732 passed, 2 expected xfailed, 0 skipped | Two existing multiprocessing/fork deprecation warnings; no failures. |

The first protocol request,
`01a0ecb1-cde0-7b23-887b-ed4a420e27f8-2c698ba8182a816b`, was independently
reviewed and preserved as `NOT_QUALIFIED`. The underlying RED and GREEN runs
were valid, but the initial session-state command semicolon-joined multiple
test and implementation references into one literal list element. Exact-path
coverage therefore reported `TDD_UNPROVEN`. The immutable receipt was admitted
before correction. A second cycle records the same witnessed timestamps,
commands, exits, and fingerprints with one repeated CLI option per literal
path. The successor exact-state request must supersede the failed request and
qualify this corrected evidence independently.

## Exclusions and escalation

Excluded: runner isolation, core test lanes, packaging, release workflows,
workspace hygiene, `.gitignore`, runtime and benchmark behavior, dependencies,
existing OpenCode document contents, SkillDB, unrelated worktrees, paid calls,
admin changes, merge, and publication.

Stop for changed prerequisite heads, new scope-bearing review evidence,
additional tracked agent paths, broader compatibility requests, weakened pin
guarantees, public-interface or wrapper changes, unrelated failures, missing
push authority, unresolved mandatory closeout conditions, secret exposure, or
any destructive/admin/publish/merge action.
