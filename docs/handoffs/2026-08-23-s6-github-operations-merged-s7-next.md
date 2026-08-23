---
handoff_id: 2026-08-23-s6-github-operations-merged-s7-next
supersedes: 2026-08-22-github-operations-restacked
handoff_status: current
history: HISTORY#598
---

# S6 and GitHub operations published — S7 next

## Protected publication state

- Protected-main authority is the commit containing this handoff; verify its
  ancestry before acting. At authoring, the branch is based exactly on
  `origin/main@1bb5adba69858a2267a9a764c917022925bc5460`.
- Track S S6 is published through PR #223 at merge commit `abd2a597a73b63dd5bf6af59f419abbd5c7fd67f`.
- GitHub operations PR #224 is published at merge commit
  `1bb5adba69858a2267a9a764c917022925bc5460`; exact source head
  `f47f5821f4c7f67dc21f1521d2e1731c18f2ad45` passed
  `repo-hygiene`, `chroma-real-smoke`, and `locomo-quickstart-bil2`, then an
  exact-head Codex review completed with no inline findings.
- The merged source branch was deleted remotely by repository policy, pruned,
  and deleted locally. This closeout uses `chore/github-operations-closeout`.

## Live GitHub state

- The default branch exposes `bug.yml`, `feature.yml`, `research.yml`,
  `release.yml`, and `config.yml` under `.github/ISSUE_TEMPLATE/`. Blank issues
  are disabled and sensitive reports route to private security advisories.
- The two-stage guarded private-release workflows and release checklist are
  live. The admin-controlled repository variable
  `PRIVATE_RELEASE_APPROVER=BlackhatShiftey` is present. The private-repository
  plan does not support an environment required-reviewer rule; the workflow
  therefore enforces the supported fresh-run original/triggering actor
  allowlist and must not be described as separately reviewer-approved.
- Only pre-existing issue #212 is open and no milestones exist. Structured
  intake is set up; a populated GitHub backlog is not. No issue or milestone
  was created by this work.
- No new tag, release, deployment, paid provider call, or publication was
  created. Existing releases are historical state, not outputs of PR #224.

## Next work: S7 admissible semantic memory

Start S7 only from the verified protected-main successor containing this
handoff. Before product changes, read the governing SEAM and MIRL contracts and
the S7 campaign section in `docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md`.

S7 must satisfy every campaign exit condition:

- every admitted REL has exact SPAN-to-RAW proof, unknown predicates never
  traverse, and cross-boundary edges cannot be created;
- functional/multivalued predicates and older/newer/equal/missing-time cases
  reconcile deterministically;
- concurrency, idempotency, and as-of retrieval are correct;
- retrieved ENT evidence has 100 percent exact source coverage; and
- multiword names survive, stopwords are rejected, and same-name people remain
  separable.

Freeze and independently review the native relation/entity corpus before
claiming the graph is scorer-eligible. Do not substitute more retrieval
machinery or another headline benchmark score for proof that graph construction
is correct.

## Preserve these boundaries

- PRs #207, #213, and #221 remain open and conflicting on older heads; none is
  qualified against current main.
- Preserve the primary checkout's unrelated operator assets, all linked
  worktree artifacts, and the separate generated `seam-records` repository.
- Issue state coordinates work; SEAM status, HISTORY, handoffs, snapshots, and
  exact evidence remain the implementation/publication authorities.
