# Repository Project Tracking

SEAM uses GitHub issues and pull requests to coordinate bounded work in this
repository. The roadmap and status pages remain authoritative for plans and
current project state; specifications define product behavior; `HISTORY.md`
preserves chronology. Closing an issue records coordination state. It does not
by itself prove that work is qualified, deployed, published, or released.

## Intake

Choose the issue form that matches the work: bug, feature, research, release,
or task. Each form applies one `type:*` label. The task form requires an
objective, scope and exclusions, acceptance evidence, dependencies, governing
references, and a verification plan. Link existing roadmap, status,
specification, and HISTORY items instead of copying their claims into an issue.

Maintainers assign priority deliberately:

- `priority:p0`: urgent incident or release blocker
- `priority:p1`: high near-term impact
- `priority:p2`: normal planned work
- `priority:p3`: low-priority or opportunistic work

The automation never guesses priority, assignees, or milestones.

## Lifecycle

New open issues receive `status:triage`. Maintainers move scoped work through
`status:ready`, `status:in-progress`, or `status:blocked`. Closing an issue sets
`status:closed`; reopening returns an issue without another maintainer-selected
open status to `status:triage`.

The [project-tracking workflow](../.github/workflows/project-tracking.yml)
reconciles the current issue state instead of relying on state captured in the
event payload. The read and label mutations are separate API requests, so a
concurrent change can still require a later event or manual rerun to reconcile.
The workflow creates missing catalog labels, reconciles their reviewed color
and description, and changes only the managed `status:*` labels on issues.
Existing legacy and unrelated labels are preserved. Manual workflow dispatch
reconciles the label catalog only; it does not sweep issues.

## Pull requests

Use `Closes #123` only when the PR completes the issue's accepted scope. Use
`Refs #123` for partial work, prerequisites, and follow-ups. Also link the
governing roadmap, status, specification, or HISTORY item in the PR template.
Repository history and continuity records still follow `AGENTS.md` regardless
of issue state.

## Local audit

The command defaults to a dry run. Supply a sanitized GitHub event payload and
an explicit repository:

```bash
python -m tools.ci.project_tracking \
  --repo Canticle-AI-Research/Seam \
  --event-name issues \
  --event-path /path/to/event.json
```

Only the trusted default-branch workflow passes `--apply`. The implementation
uses `gh api` with argument lists and JSON stdin; it does not read or print issue
bodies.
