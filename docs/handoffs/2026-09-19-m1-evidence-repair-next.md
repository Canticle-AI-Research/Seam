---
handoff_id: 2026-09-19-m1-evidence-repair-next
supersedes: 2026-09-19-e1-b1-m1-split-ci-blocked-next
handoff_status: current
history: HISTORY#654
---

# M1 observation verification repaired; local CI restored

## Concrete scope

Continue memory formation M0-M5 using
[the governing roadmap](../roadmap/MEMORY_FORMATION.md). This slice repairs the
observation instrument and verifies retained M1 findings on draft PR #269;
formation behavior and retrieval defaults remain unchanged. Main remains
`66fd3f9` at reconciliation. The isolated repair starts at PR head `2133d60`.

## Findings and acceptance boundary

Independent review verified the retained artifact hashes and found support for
the narrow M1 findings: mixed first-person attribution, repeated-event identity
loss and dropped captions, segmentation limitations, and missing structured
temporal intervals. These synthetic diagnostics support M2 design work; they
do not demonstrate answer-quality gains.

The new tests had not checked all those claims. Their claimed size bound
accepted a single 9,999-character span from a 10,000-character input: trailing
space trimming, not bounded segmentation. The repair states that limitation,
checks semantic observations and source support, runs the local model offline,
and reports an orphaned SPAN as inexact instead of crashing. Original evidence
JSON and its hash remain unchanged.

HISTORY#652 claimed that copying an existing probe after an import-failure test
resolved its original `TDD_UNPROVEN` condition. This session does not adopt that
claim. Later tests establish subsequent verification, not historical test-first
development. The current observer repair has its own witnessed red/green cycle;
full PR release qualification and protected-main acceptance remain separate.

## CI operational correction

The registered `seam-terrabyte` runner was on this machine. Its enabled
`seam-actions-runner.service` repeatedly exited because both versioned
executable directories were missing. The host did not need to be powered on.
Root restored only `bin.2.337.0` and `externals.2.337.0` from the official
`actions/runner` release, checking archive SHA-256
`70920811a4f8ad4328818682bca5c6469c1c942fab52448868071d0063816613`.
Existing registration, credentials, work directory and workflow routing were
preserved. GitHub reports the runner online and a queued PostgreSQL integration
job started. This proves execution resumed, not that required checks passed.
The queued PR #269 run `35467297264` was cancelled and rerun after restoration.
New pushes require checks on their own exact head.

The broader regression run also exposed two stale checkpoint expectations from
the earlier PR #269 fixture-hash addition. They now independently hash the
selected quickstart fixture and retain exact payload/preflight assertions for
both worker modes. The complete affected adapter test module passes.

## Verification and next action

HISTORY#654 records completed commands and outcomes. The pinned embedding model
loads offline with sentence-transformers 2.7.0, transformers 4.57.6 and
huggingface-hub 0.36.2 in an isolated test environment. Model revision remains
`5c38ec7c405ec4b44b94cc5a9bb96e735b38267a`. No paid provider call, benchmark
campaign, release, deployment or merge is part of this slice.

1. Verify the pushed PR #269 head, independent review and required checks.
2. Keep inherited E1/B1/checkpoint changes and M1 release qualifications
   explicit; this repair does not qualify the entire mixed PR.
3. Finish M2 interface and example review against B1 and E1 using the accepted
   diagnostic findings. M3/M4 remain unimplemented.
4. Benchmark resume needs grouped-runner seeding, safe resume identity and
   rate-limit handling in a separate slice before a paid run.
5. Reconcile overlapping research-roadmap PRs and duplicate M1 assets on PR #264
   separately; they were not modified here.
6. Track the existing `test_preflight_gates_match_canonical_commit_hook` failure
   in `tests/audit/test_history_closeout.py` as separate CI cleanup. Its parser
   counts only `run_gate` lines and misses the explicit staged agent-config
   check. The same mismatch reproduces from protected-main Git objects; this
   repair does not weaken or change any gate.

## Preserved work

The primary `docs/deep-audit-20260829` checkout remains untouched, including its
dirty HISTORY/index/history streams/cross-index, audit/handoff indexes, August
handoff and untracked orchestration, audit, archive and log paths. Existing
worktrees and stashes were preserved; no stash was created. Remove the repair
worktree after its reviewed commit is safely pushed, retaining verification
evidence outside the repository.
