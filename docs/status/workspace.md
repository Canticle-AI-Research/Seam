# Status Stream: Workspace Inventory

> Worktrees, branches, pull requests, local-only artifacts, and overlap between
> active workstreams

_Snapshot authority: live local Git and GitHub state reconciled on 2026-08-17
against `origin/main@7756240`. This page is current-state routing, not
chronology. Re-run the refresh commands before acting on it._

## Use this before creating work

Read this page before creating a branch or worktree, reviving an old branch,
or copying a feature into a new implementation. A logical work item may have a
different local branch name, remote branch name, and worktree directory. Match
by purpose, pull request, and commit before assuming two names are two pieces
of work.

No entry on this page authorizes deletion. Worktree removal, branch deletion,
artifact cleanup, PR closure, force-push, and history rewriting still require
an exact target decision. Ignored files are listed because `git status` can
report a worktree as clean while removal would still destroy local data.

## Current decision map

| Logical item | Physical identities | State | Unique purpose | Next action |
| --- | --- | --- | --- | --- |
| Protected main | primary checkout; local `main`; `origin/main` | HEAD and remote both `7756240`; tracked tree clean | Canonical published source for all new work | Preserve the untracked skill installation; stage only explicit inventory paths |
| Workspace inventory | `Seam-workspace-inventory`; `docs/workspace-inventory` | Active temporary documentation branch from `7756240` | This canonical anti-duplication map | Publish through a PR, then remove this temporary worktree and branch |
| Native-model and embodied roadmap | `Seam-native-model-roadmap`; local `docs/seam-native-model-roadmap-reconciled`; remote `origin/docs/seam-native-model-roadmap`; PR #207 | Clean; local and remote head `4a4f8d8`; 3 commits ahead and 3 behind main; PR is open, non-draft, and conflicting | Adds the SEAM-native model ladder, ESP32-S3/Galaxy Tab embodied roadmap, append-only future/plan/executed streams, training-eligibility boundaries, and roadmap lifecycle tooling | Rebase/rechain on current main, regenerate derived streams/history, rerun exact-head gates, then merge or close explicitly |
| Native-roadmap pre-reconcile backup | local `archive/native-model-roadmap-pre-reconcile` | Clean branch; 5 commits ahead and 15 behind main; not a second PR | Preserves the earlier unsigned/unreconciled roadmap lineage that PR #207 replaced | Keep only as a recovery source until PR #207 is resolved; never implement from it independently |
| Vector-cache replay repair | `Seam-pr213-repair`; local `repair/pr213-full-suite`; remote `origin/blackhatshiftey-performance-improvements`; PR #213 | Clean; local and remote head `4d2609e`; 2 commits ahead and 15 behind main; draft PR is conflicting | Preserves warmed SQLite vector matrices across no-op replay, detects supported cross-process changes, clears cache after rollback restore, and fixes the streaming fake | Rebase/rechain on current main, rerun vector plus full/external gates, then publish before S6 changes overlapping vector cleanup |
| Wiki publication | `Seam-wiki`; local `docs/seam-wiki`; merged PR #214 | Tracked tree clean; 0 commits ahead and 8 behind main; remote branch gone | Historical source work for verified CommonMark wiki navigation and audit registry rules, already published | Salvage or explicitly discard ignored local data before worktree removal; local branch is otherwise cleanup-eligible |
| TUI reload repair | `Seam-tui-reload-fix`; local `fix/tui-meta-digits-reload`; merged PR #216 | Tracked tree clean; 0 commits ahead and 4 behind main; remote branch gone | Historical source work for refreshing Alt-digit behavior after settings reload, already published | Cleanup-eligible after exact approval; only caches and ignored snapshots remain |
| Agent-skill layer rebuild | local `skills/rebuild-agent-layer-and-drift-gate` | Local-only commit `d2151ad`; 1 commit ahead and 1 behind main; no PR | Rebuilds the tracked agent layer, adds an audit profile and skill-drift verifier, and changes `.opencode` agent/skill material | Preserve as active local WIP; rebase and resolve its colliding HISTORY#566 before any publication decision |
| Retrieval consolidation source | local and remote `refactor/unify-retrieval-paths` | 10 commits ahead and 38 behind main; no PR | Historical source line for single-package consolidation, trace attribution, WANDR replay, and related repairs | Do not land wholesale: it contains the 59 tracked `.ua` artifacts excluded by Track S S0; compare only a named file or commit against current main |

Pull requests: [#207](https://github.com/Canticle-AI-Research/Seam/pull/207),
[#213](https://github.com/Canticle-AI-Research/Seam/pull/213),
[#214](https://github.com/Canticle-AI-Research/Seam/pull/214), and
[#216](https://github.com/Canticle-AI-Research/Seam/pull/216).

## Physical worktree register

### `/home/terrabyte/Documents/Projects/Seam`

- Role: primary protected-main checkout.
- Branch/head: `main@7756240`, exactly aligned with `origin/main` after fetch.
- Tracked state: clean.
- Local-only state: `skills-lock.json` plus 35 untracked skill directories.
  These belong to one GitHub-sourced Matt Pocock skill installation and are
  not part of the `skills/rebuild-agent-layer-and-drift-gate` branch.
- Boundary: do not use `git add -A`; do not move, delete, or absorb the skill
  bundle into another PR without an explicit ownership decision.

### `/home/terrabyte/Documents/Projects/Seam-workspace-inventory`

- Role: temporary isolated branch for this inventory.
- Branch/head: `docs/workspace-inventory@7756240` at creation.
- Tracked state: active documentation changes only.
- Boundary: this worktree must be committed, pushed, and removed after its PR
  is complete; it is not a new long-lived workstream.

### `/home/terrabyte/Documents/Projects/Seam-native-model-roadmap`

- Role: active recovery checkout for PR #207.
- Branch/head: local `docs/seam-native-model-roadmap-reconciled@4a4f8d8`, now
  correctly tracking `origin/docs/seam-native-model-roadmap@4a4f8d8`.
- Tracked state: clean. Relative to main it is 3 commits ahead and 3 behind.
- GitHub state: open, non-draft, `CONFLICTING`/`DIRTY`; all recorded checks
  passed on the old 2026-08-12 head, which is not current-main qualification.
- Conflict boundary: only continuity/status outputs currently conflict
  (`HISTORY*`, history streams, cross-index/archive, and `PROJECT_STATUS.md`).
  The authored roadmap, lifecycle tool, run-record, and test changes merge
  structurally but still require review on current main.
- Ignored state: three local snapshots plus pytest/Ruff and Python caches;
  approximately 24 MB total checkout size.

### `/home/terrabyte/Documents/Projects/Seam-pr213-repair`

- Role: active recovery checkout for draft PR #213.
- Branch/head: `repair/pr213-full-suite@4d2609e`, tracking the differently
  named remote head `origin/blackhatshiftey-performance-improvements@4d2609e`.
- Tracked state: clean. Relative to main it is 2 commits ahead and 15 behind.
- GitHub state: open draft, `CONFLICTING`/`DIRTY`; all recorded checks passed
  on the old 2026-08-12 head, not on current main.
- Conflict boundary: current merge simulation reports conflicts only in
  history/cross-index derived state. The runtime/vector/test files merge
  structurally, but must be reviewed and requalified.
- Ignored state: one local snapshot, disposable `test_seam/`, and caches;
  approximately 24 MB total checkout size.

### `/home/terrabyte/Documents/Projects/Seam-tui-reload-fix`

- Role: merged PR #216 source checkout.
- Branch/head: `fix/tui-meta-digits-reload@b6da2a8`; remote branch is gone.
- Tracked state: clean; head is fully contained by main.
- Ignored state: two local snapshots and disposable caches only;
  approximately 24 MB total checkout size.
- Disposition: safe code-wise to remove after exact approval. No unique
  tracked work remains.

### `/home/terrabyte/Documents/Projects/Seam-wiki`

- Role: merged PR #214 source checkout with local evidence still present.
- Branch/head: `docs/seam-wiki@4bd08c0`; remote branch is gone.
- Tracked state: clean; head is fully contained by main.
- Ignored/local state: one 4,091-byte context handoff, three snapshots, a
  921,600-byte `seam.db`, two 17-byte zero-case LoCoMo quickstart records, and
  thirteen LoCoMo SQLite databases of roughly 2.3-2.8 MB each under
  `test_seam/locomo/`, plus caches. The checkout is approximately 64 MB.
- Disposition: do not remove until the handoff and database artifacts are
  either confirmed disposable or moved to an operator-approved durable path.

## Local branch register

The counts below are `branch...origin/main` on 2026-08-17. “Ahead” is not
proof of unpublished work: squash-merged PR heads can still appear unique.

| Local branch | Ahead / behind | Full description and ownership | Classification |
| --- | ---: | --- | --- |
| `agent/g3-finish-remaining-gaps` | 1 / 70 | Local-only commit `824467f` added exact returned graph paths and episode traces across the retrieval orchestrator and reasoning-retrieval tests. The commit is absent from GitHub and its HISTORY#463 collides with canonical main's unrelated HISTORY#463. Later graph work may subsume it, but that has not been proved file-by-file. | Preserve for bounded salvage audit; never cherry-pick wholesale |
| `agent/track-s-s3-reconcile` | 2 / 30 | Original durable-supersession/reprojection candidate for Track S S3. Tip `b68de0f` is associated with merged PR #194; protected main carries the published S3 contract through a different merge topology. | Merged logical work; local cleanup candidate |
| `archive/native-model-roadmap-pre-reconcile` | 5 / 15 | Backup of the initial SEAM-native model and ESP32 embodied-spatial roadmaps plus append-only roadmap lifecycle work before the reconciled PR #207 head. It is an archive source, not a parallel implementation. | Keep until PR #207 closes |
| `backup/history-402-claude` | 1 / 132 | Local chronology backup for the old HISTORY#402 status record around PR #121/#151 and retrieval attribution. It changes continuity/status files only and is superseded by later canonical history. | Protected backup; audit before any deletion |
| `backup/local-main-e9ab8d3-20260723` | 1 / 81 | Local backup of the fact-free auxiliary-RAW ablation. Commit `e9ab8d3` is associated with merged PR #157, while the backup retains its pre-merge topology and handoff state. | Published logical work; protected backup |
| `docs/audit-claim-gate` | 3 / 2 | Source head for the audit-claim verifier and initial brand asset renderer/fix. Tip `4116d57` is associated with merged PR #218; main also contains the later document renderer. | Squash-merged logical work; local cleanup candidate |
| `docs/seam-native-model-roadmap-reconciled` | 3 / 3 | Local alias for open PR #207's remote head. See the logical-item and worktree entries above. | Active open PR |
| `docs/seam-wiki` | 0 / 8 | Source branch for merged PR #214's wiki navigation and verification work. | Merged; branch cleanup candidate after worktree artifact decision |
| `fix/mem0-comparison-inversion` | 0 / 23 | Points at the merged PR #201 commit that added `/v1` HTTP coverage; it carries no work absent from main despite its older name. | On-main cleanup candidate |
| `fix/tui-meta-digits-reload` | 0 / 4 | Source branch for merged PR #216's settings-reload correction. | Merged; branch cleanup candidate with worktree |
| `record/selfhost-published` | 1 / 49 | Old publication-record commit for `seam-self-host`; tip `d07dce1` is associated with merged PR #179. The distribution path is now retired policy, so this branch is evidence history, not a release base. | Published logical work; local cleanup candidate after audit |
| `refactor/unify-retrieval-paths` | 10 / 38 | Contaminated reconstruction/source line for package consolidation, retrieval trace attribution, WANDR replay, infrastructure fail-fast, and provenance-chain work. It includes tracked `.ua` artifacts intentionally excluded by S0. | Historical source; explicit do-not-land hold |
| `repair/pr213-full-suite` | 2 / 15 | Local alias for open draft PR #213. See the logical-item and worktree entries above. | Active open PR |
| `skills/rebuild-agent-layer-and-drift-gate` | 1 / 1 | Local-only agent-layer rebuild with `.opencode` changes, an audit profile, skill verifier, and closeout/hook changes. Its HISTORY#566 conflicts with canonical main's report-renderer HISTORY#566. It is distinct from the primary checkout's untracked Matt Pocock skill bundle. | Recent local WIP; preserve and rechain before PR |
| `docs/workspace-inventory` | 0 / 0 at creation | Temporary branch that owns this page and its navigation/policy pointers. | Active current session; remove after publication |

## Remote branch register

Remote aliases already named in the logical-item table are not separate work:
`origin/docs/seam-native-model-roadmap` is PR #207,
`origin/blackhatshiftey-performance-improvements` is PR #213, and
`origin/refactor/unify-retrieval-paths` is the same historical source line as
its local branch.

| Remote branch | Relationship to main | Full description | Disposition boundary |
| --- | ---: | --- | --- |
| `origin/main` | canonical | Protected publication source at `7756240` | Never direct-push |
| `origin/backup/local-pgvector-bootstrap` | 2 ahead / 409 behind | Early local-pgvector bootstrap backup with Compose/init SQL, PowerShell setup, old project-map docs, an imported design source, and a PDF handoff artifact | Protected historical backup; never use as current pgvector setup without a file-by-file rewrite |
| `origin/copilot/agent-types-on-github` | 0 ahead / 3 behind | Remote pointer already fully contained by main at the PR #216 merge | Remote cleanup candidate; deletion needs exact approval |
| `origin/copilot/understanding-operations` | 0 ahead / 15 behind | Remote pointer already fully contained by main at the Track S visual-status merge | Remote cleanup candidate; deletion needs exact approval |
| `origin/handoff/archive` | 3 ahead / 459 behind | Protected historical artifact branch containing early branding previews, handoff files, and an obsolete experimental retrieval tree | Preserve as artifact history; never merge into active source |

## Primary-checkout skill bundle

`skills-lock.json` records one untracked installation from
`mattpocock/skills`; the tracked `skills/seam-engineer` is not part of that
bundle. These 35 directories are one local item, not 35 independent SEAM
features and not the same work as `skills/rebuild-agent-layer-and-drift-gate`.

| Skill | Purpose recorded in its frontmatter |
| --- | --- |
| `ask-matt` | Routes a request to the appropriate installed skill or workflow. |
| `claude-handoff` | Starts a fresh background Claude agent with a compact handoff. |
| `code-review` | Reviews a fixed diff against repository standards and its originating specification. |
| `codebase-design` | Supplies deep-module interface, implementation, seam, and depth vocabulary. |
| `diagnosing-bugs` | Runs a disciplined reproducer-first loop for hard bugs and regressions. |
| `domain-modeling` | Builds project terminology, a ubiquitous language, and architecture decisions. |
| `git-guardrails-claude-code` | Adds Claude Code hooks that block dangerous Git commands. |
| `grill-me` | Runs a relentless interview to sharpen a plan or design. |
| `grill-with-docs` | Runs the same interview while recording domain docs and ADRs. |
| `grilling` | Provides the underlying decision-tree stress-test interview. |
| `handoff` | Writes a compact conversation handoff for another agent or session. |
| `implement` | Implements a bounded piece of work from a specification or ticket set. |
| `improve-codebase-architecture` | Finds deep-module opportunities and presents them as a visual report. |
| `loop-me` | Iteratively grills workflow specifications in the current workspace. |
| `migrate-to-shoehorn` | Replaces TypeScript test assertions with `@total-typescript/shoehorn`. |
| `prototype` | Builds a disposable prototype to answer a design question. |
| `research` | Investigates primary sources and records findings in repository Markdown. |
| `resolving-merge-conflicts` | Guides an in-progress Git merge or rebase conflict resolution. |
| `scaffold-exercises` | Creates lint-compliant exercise, solution, and explainer structures. |
| `setup-matt-pocock-skills` | Configures issue tracking, triage labels, and domain-doc paths for this skill set. |
| `setup-pre-commit` | Configures Husky, lint-staged, formatting, type checking, and tests. |
| `setup-ts-deep-modules` | Uses dependency-cruiser to enforce TypeScript package entry-point boundaries. |
| `tdd` | Applies a behavior-first red-green-refactor development loop. |
| `teach` | Maintains a stateful teaching workspace and lesson record. |
| `to-questionnaire` | Produces an asynchronous questionnaire for missing external knowledge. |
| `to-spec` | Synthesizes the conversation into a specification on the configured tracker. |
| `to-tickets` | Splits a plan into dependency-linked tracer-bullet tickets. |
| `triage` | Moves issues and external PRs through explicit triage roles. |
| `wait-what` | Requests a clearer simplified-English restatement. |
| `wayfinder` | Maps a multi-session effort into decision tickets before execution. |
| `wizard` | Builds an interactive Bash guide for human-only setup or cutover steps. |
| `writing-beats` | Assembles fixed raw material into a grounded sequence of writing beats. |
| `writing-for-agents` | Provides conventions for skills and agent-consumed instructions. |
| `writing-fragments` | Captures unstructured writing fragments without imposing an outline. |
| `writing-shape` | Shapes fixed raw material into a separate article paragraph by paragraph. |

## Overlap and anti-duplication rules

1. PR #207's local branch, remote branch, worktree, and pre-reconcile archive
   are one feature lineage. Do not create a second native-model or embodied
   roadmap branch.
2. PR #213's local `repair/` branch, differently named remote head, and
   worktree are one vector-cache repair. Do not reimplement its no-op replay
   work on S6.
3. `agent/track-s-s3-reconcile`, `backup/local-main-e9ab8d3-20260723`,
   `docs/audit-claim-gate`, and `record/selfhost-published` look unique by
   commit topology but are associated with merged PRs. Check the PR mapping
   before calling them lost work.
4. Generated continuity files (`HISTORY_INDEX.md`, history stream mirrors,
   cross-index files, and snapshots) are never merged as authored feature
   content. Rebase the substantive files, append a new current HISTORY entry,
   then regenerate derived state.
5. Backup/archive branches preserve evidence; they are not valid bases for new
   implementation. Copy only a named, reviewed fact or file after comparing it
   with current contracts and main.
6. Ignored snapshots, databases, benchmark runs, handoffs, and caches are not
   evidence that code is unpublished. They are separate local artifacts with
   their own preserve/delete decision.

## Recommended resolution order before Track S S6

1. Publish this inventory so every subsequent branch decision has one route.
2. Resolve PR #207 on current main or explicitly close it while retaining its
   archive source. It overlaps the roadmap/status/history surfaces S6 must
   update.
3. Resolve draft PR #213 on current main or explicitly close it. Its vector
   cache and rollback paths overlap S6's recoverable deletion cleanup.
4. With exact operator approval, remove the merged TUI worktree/branch. For the
   wiki worktree, decide the handoff/database artifact disposition first.
5. Audit local-only `agent/g3-finish-remaining-gaps` and
   `skills/rebuild-agent-layer-and-drift-gate`; classify each as salvage,
   publish, archive, or abandon without copying it into S6 by default.
6. Start S6 from the resulting protected `origin/main`, not from any branch
   listed as backup, archive, merged, or do-not-land.

## Refresh commands

Run from the primary checkout before relying on counts or dispositions:

```bash
git fetch --prune origin
git status --short --branch
git worktree list --porcelain
.venv/bin/python -m tools.git.scan_stale_branches --json
gh pr list --state all --limit 100 --json number,title,state,isDraft,headRefName,headRefOid,mergedAt,url
```

For an active branch, recalculate main divergence and conflict paths:

```bash
git rev-list --left-right --count HEAD...origin/main
git merge-tree --write-tree --name-only HEAD origin/main
git clean -ndx
```

`git clean -ndx` is inspection only. Do not change it to `-fdx` without exact
authorization for every path it would remove.
