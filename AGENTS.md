# AGENTS.md

Canonical multi-agent protocol for this repo. All models use the same rules.

## Session Start

Read in order:
1. `PROJECT_STATUS.md`
2. `REPO_LEDGER.md`
3. `HISTORY_INDEX.md`
4. `docs/CODE_LAYOUT.md`
5. `docs/DATA_ROUTING.md` when the task touches history, ledgers, maintenance records, routing, context budget, or auditability.
6. `SEAM_SPEC_V0.1.md` **and** `docs/MIRL_V1.md` when the task touches SEAM product behavior — compilation/`compile_nl`, MIRL/IR records, compression, PACK, retrieval, surfaces (HS/1), codecs (RC/1, LX/1), the symbol/improvement loop, benchmarks, or any design decision or measurement claim about how SEAM should behave. The spec is the **governing contract**: do not redesign, "improve", or declare a component broken without first checking the contract it is actually supposed to satisfy (see REPO_LEDGER "SEAM spec is the governing contract"). The process docs above tell you the repo's *state*; the spec tells you what SEAM *is*.

Then:
- Prefer latest valid snapshot in `.seam/snapshots/`.
- If snapshot verification fails, fall back to index-first reads.
- Use `python -m tools.history.build_context_pack` to load only the latest, route-relevant, topic-relevant, or supersedes-chain entries needed for the task.
- Never read all of `HISTORY.md`; pull only needed entries by indexed line/byte ranges.
- Treat `archive/code/`, `docs/archive/`, `build/`, `.venv/`, `test_seam/`, and generated/cache paths as inactive unless the user explicitly asks for historical, retired, or local test-artifact material.
- `test_seam/` is the ignored sink for isolated SQLite `test_seam_*.db` artifacts from test runs. Do not scan it for project source, runtime state, roadmap direction, or repo evidence unless investigating test-artifact cleanup.
- For normal code search, stay in active paths: `seam_runtime/`, `seam.py`, `experimental/`, `tools/`, `scripts/`, `installers/`, `docs/`, tests, and root status files.
- Test documentation and local test artifacts have fixed homes: tracked testing
  notes live under `tests/docs/`, and disposable generated test outputs live
  under ignored `test_seam/` subdirectories such as `test_seam/pgvector/`.
  Do not leave ad-hoc `Test*`, `test_*`, or `test_pgvector_*` scratch files in
  the repo root.

## Session End

If state changed:
1. Append one entry to `HISTORY.md`.
2. Rebuild `HISTORY_INDEX.md`.
3. Write one snapshot JSON.
4. Run `python -m tools.history.verify_continuity` and `python -m tools.streams.verify_streams`.
5. If `ROADMAP.md` changed: rerun `python -m tools.streams.roadmap_parser` to refresh the roadmap stream + state view; if any stream changed: rerun `python -m tools.streams.rebuild_cross_index` to refresh the derived global timeline.

If you created a git worktree during the session: finish it. Either commit, push, and `git worktree remove` it, or remove the worktree even if abandoning the work. Never leave a dirty worktree on a stale base for the next agent to find — that pattern caused real regressions before (see HISTORY#223 worktree triage).

If you created a working branch: push it if the work is real, delete it locally if the work is fully merged. Stale branches accumulate across multi-agent sessions and look like active work to the next agent.

If you stashed anything: restore or drop it before ending. Stashes are invisible to `git status`, `git log`, and branch/PR listings, so an abandoned one lingers unnoticed (especially in this multi-agent repo, where stashing to clear a tree mid-context-switch is common). `git stash list` surfaces them, and `seam doctor` reports them as a non-blocking advisory so a cleanliness sweep catches orphaned local WIP.

Use `tools/history/*` scripts for the canonical history protocol and `tools/streams/*` scripts for the multi-stream substrate (history mirror, roadmap, experience, cross-index). Run `python -m tools.git.scan_stale_branches` on-demand to audit branch health; the repo has `delete_branch_on_merge` enabled on GitHub so merged PR branches auto-delete.

## Cut-off Recovery

This rule applies to every agent (Claude, Codex, Gemini, DeepSeek, Qwen, Aider, OpenCode, others). A session that stops mid-implementation without leaving a recovery breadcrumb is the failure mode this rule prevents.

Before stopping a session that has touched runtime code:

1. Run `pytest --collect-only` against the modules you touched. Any `ImportError`, `NameError` at module scope, or undefined symbol means the implementation does not match its tests; do not stop until that gap is closed or recorded.
2. Run the relevant test slice (`tests/audit/` plus any directly affected suite). New tests that import symbols must compile alongside the implementation they target.
3. If extraction or refactor was in progress, search for every reference to the renamed/extracted symbol and confirm it still resolves. Do not commit or hand off code that references undefined constants or helpers.
4. If the session ends with the working tree dirty, append a HISTORY entry marked `status: in-progress` that names: (a) the files touched, (b) any missing constants/helpers/methods the next agent must add, (c) any test-vs-implementation mismatches, and (d) what the next agent should run first to reproduce state. This is the cut-off breadcrumb; without it the next session cannot tell intentional in-flight work from abandoned code.
5. Never leave large binary artifacts (image tarballs, model weights, backups, datasets) inside the repo working tree. Move them to an external path before stopping.
6. No silent skips. The test suite enforces strict no-skip via `tests/conftest.py` (default on; opt out for ad-hoc runs only with `SEAM_STRICT_NO_SKIP=0`): any skip whose reason is not in the curated allowlist (wrong OS, deliberately-absent optional extra, no `origin/main`) FAILS the session. A test gated on a real service (pgvector) carries `@pytest.mark.external`; run it with the service up and `PGVECTOR_TEST_DSN` set, or deselect with `-m "not external"` — never let it skip. To run the full suite with zero skips locally, start the pgvector container (`~/.local/bin/docker-up`) and export `PGVECTOR_TEST_DSN`. CI: the main job runs `-m "not external"`; the pgvector job runs `-m external` against the live service. Resolve a new skip by running the service, not by ignoring it; if a skip is genuinely unavoidable, add it to the allowlist WITH a justification.

## GitHub PR Workflow

- `main` is the source-of-truth branch and is protected by the GitHub ruleset
  `Protect main (PR + hygiene gates)`. Do not direct-push to `main`. Use a
  branch and PR for repo changes unless the operator explicitly authorizes a
  time-boxed emergency bypass; record that bypass in `HISTORY.md` and remove it
  immediately after use.
- Before starting or resuming branch work, run `git status --short --branch`.
  If unrelated dirty files are present, name them in the handoff and keep them
  out of the PR unless the operator explicitly says to combine workstreams.
- Before starting new work from `main`, fetch/pull and verify local `HEAD`
  matches `origin/main`. When resuming an existing PR branch, verify the branch
  tracks the intended remote PR head and note any base drift or conflicts.
- Open or update a draft PR for material branch work once the branch has a
  coherent reviewable slice. PR bodies must summarize scope, verification,
  remaining risks, and any intentionally excluded dirty files or workstreams.
- Required merge checks for `main` are `repo-hygiene`, `chroma-real-smoke`, and
  `locomo-quickstart-bil2`. Treat `test-and-benchmark` matrix failures as
  advisory unless the ruleset changes; summarize advisory failures in the PR or
  history, and fix them in a separate CI cleanup branch unless they were caused
  by the current PR.
- Keep PRs moving. A PR should end in one of four states: merged, closed as
  superseded/abandoned, actively draft with a current handoff, or blocked with a
  concrete blocker recorded. Do not leave old draft PRs or remote branches
  ambiguous.
- Use the scheduled/manual repository-maintenance workflow, or locally run
  `GITHUB_TOKEN=$(gh auth token) python -m tools.ci.github_maintenance_report`,
  to audit open PRs, stale PRs, and stale branches without PRs. Stale branches
  should be deleted if merged/abandoned, turned into a PR if real, or recorded
  as intentionally retained.
- Before marking a PR ready to merge, ensure the session-end history/snapshot
  protocol is complete, required checks pass on the pushed head, and candidate
  files have been scanned for secret-shaped values and provider session URLs.

## Context Loop

Bounded reading protocol that keeps session-start cost flat as the repo grows. Three phases:

### Phase 1 — Session Start (do NOT read full HISTORY.md or full ROADMAP.md)

1. `PROJECT_STATUS.md` + `REPO_LEDGER.md` + `HISTORY_INDEX.md` + `docs/CODE_LAYOUT.md` (and `docs/DATA_ROUTING.md` when the task touches history/ledgers/routing/audit; and `SEAM_SPEC_V0.1.md` + `docs/MIRL_V1.md` — the **governing contract** — when the task touches SEAM product behavior: compilation, MIRL/IR, compression, PACK, retrieval, surfaces, codecs, the symbol/improvement loop, benchmarks, or any design/measurement claim).
2. `.seam/streams/roadmap/state.md` — derived view of the roadmap stream, grouped by status (`now`, `later`, `done`, etc.). Read this **instead of** `ROADMAP.md`. Only fall through to the prose in `ROADMAP.md` when the task is to edit the roadmap or to read a specific track's narrative.
3. `.seam/cross_index.md` hot zone — the temporal join across `history`, `roadmap`, `experience`, and any opted-in library streams. Use it for "what happened recently across the whole repo" without reading per-stream logs.
4. `tools.history.build_context_pack --topics <tags> --latest <n> --token-budget <budget>` for history entries the task actually needs. Never `cat HISTORY.md`.

### Phase 2 — During Work

- Surgical reads only. Pull a specific entry by id range, a specific roadmap item by marker, or a specific experience lesson by topic.
- `python -m tools.streams.rebuild_cross_index --help` (and per-stream `rebuild_index`) are safe to re-run at any time; outputs are derived.
- If you need to walk across streams (e.g. "what roadmap status changes happened the week of HISTORY#160"), use `cross_index.md` first, then drill into the per-stream log.

### Phase 3 — Session End

- Follow the Session End checklist above. Both `verify_continuity` and `verify_streams` must pass.
- If `ROADMAP.md` items changed status, re-run the roadmap parser so the stream and the derived `state.md` stay aligned with the authored prose.
- The cross-index always regenerates from the streams; never hand-edit it.

### What this prevents

- Full-file reads of `HISTORY.md` (still gated by `HISTORY_INDEX.md` and the context pack, now reinforced by `cross_index.md`).
- Full-file reads of `ROADMAP.md` (replaced by `roadmap/state.md` for status queries).
- Drift between roadmap prose and recorded status (the parser is rerun on every change).
- Loss of cross-stream temporal context as new dimensions (experience, library) come online — they fan out without bloating session-start reads.

## Temporal Chain

- Every material change must preserve a clear chain from previous state to new state. Record what changed, why, verification performed, failures or partial work, and the next unresolved step when one exists.
- Use `supersedes` to link follow-up work to the latest relevant entry. Do not overwrite or rewrite older history entries to make the timeline look cleaner.
- Update `REPO_LEDGER.md` when a change affects stable repo policy, architecture, active/archive routing, runtime safety rules, durable operator workflows, or cross-agent protocol. Routine implementation details belong in `HISTORY.md` with pointer cards from docs when needed.
- Update `PROJECT_STATUS.md` when the current operating state or active focus changes. Do not leave status files stale after changing what future agents should believe.
- Use concise refs to changed files, tests, commands, and snapshots. Record failures as failures, skipped verification as skipped, and assumptions as assumptions.
- Recorded facts must be scoped enough to audit. Counts, handoff pointers, file refs, and other checkable values must name the command/path/scope that produced them; `verify_continuity` audits recorded facts for current mismatches and precedence drops so data does not silently disappear between entries.
- Keep context packs bounded. Prefer `build_context_pack --topics <tags> --latest <n> --token-budget <budget>` over broad history reads.
- Use route-aware packs for durable areas: `build_context_pack --route maintenance/docker`, `--route protocol/context`, or another route from `tools/history/routing_manifest.json`.

## Classification Routing

- `tools/history/routing_manifest.json` is the mutable classification map for logical branches such as `maintenance/docker` and `protocol/context`.
- Classifications may be added, moved, retired, or recreated, but route decisions must remain auditable through `HISTORY.md` and manifest lifecycle fields.
- Delete a classification from active use by marking it `retired` or `moved`; do not erase the only record of why the route existed.
- Store stable route facts under `docs/ledgers/` when they are useful for future search. Keep chronology in `HISTORY.md`.
- Run `python -m tools.history.verify_routing` after changing classifications, ledgers, or route-aware context behavior.

## Security Rules

- Never commit API keys, passwords, tokens, private keys, local `.env` values, provider session links, chat/share links, thread links, or local agent transcript links.
- Do not put Claude/Codex/ChatGPT session URLs or generated conversation links in commit messages, `HISTORY.md`, snapshots, handoffs, docs, or comments. Summarize the useful state and point to repo files instead.
- Use placeholders such as `<local-password>` only in examples; real values must live in ignored local files or the operator environment.
- If a secret, credential-bearing DSN, private key, or private session URL is found in the working tree, delete the local file or redact the value immediately. Do not preserve it in another file, history entry, snapshot, commit message, or chat response.
- Before staging, scan tracked and untracked candidate files for secret-shaped strings and provider session URLs. If a secret or private session URL was committed, stop and ask for history-rewrite/rotation handling instead of copying it into another artifact.

## Invariants

- `HISTORY.md` is append-only.
- `HISTORY_INDEX.md` is derived state.
- Snapshot integrity must be verified before use.
- Status updates never edit old entries; use `supersedes`.
- Use pointer cards across docs (`see HISTORY#NNN`), not duplicated prose.
- Active docs/code and archived docs/code must stay separated; do not copy stale archive prose or code back into active paths without rewriting and verifying it.

## Entry Schema

Required fields per entry:
`id`, `date`, `agent`, `status`, `topics`, `commits`, `refs`, `supersedes`, `tokens`, and body.

Valid status values:
`planned`, `in-progress`, `done`, `changed`, `deferred`, `abandoned`.

## Topic Vocabulary

Only use tags from this controlled set:

`agent`
`alias`
`animation`
`atomicity`
`audit`
`beam`
`benchmark`
`bugfix`
`bundle`
`chat`
`chroma`
`ci`
`classification`
`codec`
`command`
`comparator`
`compile`
`compiler`
`compress`
`concepts`
`continuity`
`dashboard`
`demo`
`diff`
`docker`
`docs`
`doctor`
`experience`
`extras`
`fixture`
`git-hooks`
`gold-standard`
`graph`
`handoff`
`harden`
`history`
`holdout`
`installer`
`integrity`
`json`
`judge`
`ledger`
`lexical`
`linux`
`locking`
`locomo`
`longmemeval`
`lx1`
`macos`
`mcp`
`memory`
`mirl`
`models`
`multi-agent`
`naming`
`nl`
`operator`
`pack`
`persist`
`pgvector`
`plan`
`prompt`
`protocol`
`provenance`
`pyproject`
`quality`
`rank`
`readme`
`reconcile`
`registry`
`retrieval`
`retry`
`roadmap`
`roots`
`roundtrip`
`salvage`
`sbert`
`scripts`
`search`
`security`
`session`
`skills`
`snapshot`
`status`
`storage`
`streams`
`surface`
`test`
`tests`
`textual`
`tokenizer`
`trust`
`tui`
`vector`
`verify`
`webui`
`windows`
`wsl2`
