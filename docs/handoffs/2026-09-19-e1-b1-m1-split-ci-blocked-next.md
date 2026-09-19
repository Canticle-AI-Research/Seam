---
handoff_id: 2026-09-19-e1-b1-m1-split-ci-blocked-next
supersedes: 2026-09-18-roadmap-fork-reconciliation-next
handoff_status: current
history: HISTORY#653
---

# E1 corrected, B1 specified, M1 split and unblocked; CI blocked on seam-box

## Start here

The [detailed formation roadmap](../roadmap/MEMORY_FORMATION.md) remains the
execution authority. The operator's working scope is **M0–M5** (not M0–M10;
PCS0–PCS10 is the unmerged research lane on `#268`, a different track).

Everything below lives on branch `claude/roadmap-implementation-4cn2al`,
open as draft **PR #269**, head `782820f`. Nothing has merged. No provider
call was made, no benchmark was run, and no score is claimed anywhere in this
work.

## The blocker, stated once

**`.github/workflows/ci.yml` runs all six of its jobs on
`runs-on: [self-hosted, seam-box]` — the operator's own machine, which is
offline.** Its header records the motive: "private-repo hosted minutes were
burning real money; see HISTORY#425."

This is not a GitHub outage and not runner starvation. On identical commits at
identical times, `external-memory-benchmarks.yml` (runs 645–648) and CodeQL
completed in 15–45s on `ubuntu-latest`; GitHub Actions status was Operational
with no incidents. Only `ci.yml` never starts a job. Run 35424767115 sat
`queued` from 05:44:43Z through at least 18:43Z. Earlier runs 709–712 were
cancelled by subsequent pushes (`cancel-in-progress: true`), not by starvation.

All three **required** checks — `repo-hygiene`, `chroma-real-smoke`,
`locomo-quickstart-bil2` — plus `pgvector-integration` and `package-smoke` run
only there, and `main` is protected. **No PR in this repository can merge until
seam-box is powered on with its Actions runner service running.** Waiting does
not help.

An earlier session characterised this as repo-wide runner starvation. That was
wrong and is corrected here; do not revert to it.

## What landed (HISTORY#650–#652)

| Commit | HISTORY | Substance |
| --- | --- | --- |
| `619a996` | #650 | E1 contract batch-judging row corrected; contract versioned |
| `24049e0` | #651 | LoCoMo checkpoint identity + resume-state reader (**runtime**) |
| `782820f` | #652 | M1 split out of `#264` + 24-test probe suite |

Predecessors `0a23f2a` (#647), `12a4c9f` (#648) and `fad0f89` (#649) are
described in the superseded handoff and in the PR body.

**E1 correction.** §4 recorded `--judge-batch` as "permitted for full runs
(50% judge discount)". The runner rejects exactly that command:
`benchmarks/external/locomo/run.py:534-535` calls `parser.error("claude-code
does not support --judge-batch; no paid calls were made")`; `ClaudeCodeJudge`
is documented "deliberately has no batch method"; `tests/audit/
test_claude_code_benchmark.py:176` asserts the exit-2 rejection. Reproduced
live: exit 2, no artifact, no spend. The Batch-API discount exists only on the
separately billed `claude` route, which §4 already excludes. No cost figure
changed — `$0.008487/case` was necessarily measured on the synchronous path.

A second defect surfaced while fixing it: the amendment rule demanded "a new
contract version" and §3 demanded each run record "this contract's version",
but **no version string was ever defined**. The contract is now
`e1-evaluation/1.1`; the original text is retroactively `1.0`. Nothing ran
under `1.0`.

**M1 unblocked.** `TDD_UNPROVEN` on `tools/memory_formation_m1.py` was not a
paperwork technicality: grepping `memory_formation_m1` across `tests/` and
`test_seam_all/` on `#264`'s head returns **nothing**. The 195-line probe
behind M1's entire evidence base had zero test coverage, and its correctness
claims lived only as bare `assert`s that `python -O` strips and no CI job ever
ran. The suite was written first against a checkout without the probe (red:
`ImportError` at collection), then the probe, audit and evidence manifest were
brought over from `origin/feat/seam-reports-pages-20260912` and green reached.

**The evidence reproduces across commits.** With the declared sbert extra at
2.7.0 (inside the `pyproject` pin `>=2.0,<3.0`, not the 6.1.0 pip resolves by
default) and the pinned `BAAI/bge-small-en-v1.5` at revision `5c38ec7c…`, the
probe ran end to end and matched the committed observations exactly:
`painting`=1, `museum`=1, `M1_CAPTION_CEDAR`=0, `M1_UNSTATED_SENTINEL`=0,
`graph_edge_count`=74, `canonical_relation_rows`=0, `loaded_turns_equal`=true,
identical model identity. Evidence was recorded at `614141c5`; the rerun is
several commits later.

The reproduced findings are M1's substance: `blip_caption` metadata never
reaches storage (with the `painting`/`museum` controls proving that negative
check is not vacuous); two rows with distinct `dia_id`s but identical text load
as equal turns; and the direct-runtime control shows distinct source refs *do*
stay distinct, **localizing the collapse to the loader rather than storage**.

M1's blocking cause is removed. Formal acceptance remains an independent
review decision.

## Deliberately withheld, with reasons

**`--resume` is not exposed.** `common/runner.py` indexes `case_results` by
position over the full case list and computes aggregates from it, so filtering
cases in `run.py` would emit a report *missing* the skipped cases with scores
over the remainder only. The correct fix is a `prior_results` parameter in
`run_benchmark_grouped` and `run_benchmark_grouped_parallel` that pre-populates
`case_results` by index and skips seeded cases. A test asserts the flag is
absent so the withheld state stays explicit rather than forgotten.

What *did* land is the safety half: checkpoints now carry `fixture_hash`, and
`_resume_state` fails closed on a missing file, malformed JSON, a non-object
payload, an absent hash, or a hash naming a different case set. Without this,
no checkpoint written could ever be safely resumed.

## Recorded, not repaired

- `SEAM_BENCH_CLAUDE_CODE_MAX_CALLS` defaults to **10**
  (`benchmarks/external/common/claude_code.py:45`); a dev baseline needs ~2,396.
- The `claude-code` transport has **no retry or rate-limit backoff**, so a
  limit response is indistinguishable from any other failure.
- `tests/conftest.py`'s strict-no-skip allowlist enumerates the `fastapi`
  extra but **not `sbert`**, though both are declared extras. The M1 suite
  therefore imports directly and must not be skip-gated.
- `describe()`'s `span_text_exact` calls `next()` without a default, so a SPAN
  with no matching claim raises `RuntimeError` rather than reporting a failed
  observation.
- `_build_report` still emits no `judge_batch` field, so batched and
  synchronous runs produce indistinguishable artifacts (recorded in
  `BIL_3_SPEC.md` §4 as a B2 deliverable).

## Do not do these

- **Do not build OAuth token extraction** for benchmarks. `REPO_LEDGER.md` and
  the transport doc forbid it. Subscription routing already exists: the
  `claude-code` transport shells out to the authenticated CLI. The operator's
  `$50` credits are gone, so the constraint is now rolling **rate limits**, not
  dollars — which is what the resume work is for.
- **Do not move CI to hosted runners unilaterally.** HISTORY#425 moved it off
  hosted minutes deliberately to stop spending, and the operator is short on
  money. If seam-box stays down, the narrow option to *propose* is moving only
  `repo-hygiene` to `ubuntu-latest` so docs/continuity PRs can merge while the
  heavy chroma/pgvector/locomo legs stay local. Operator decides.
- **Do not weaken the strict-no-skip gate** to make the M1 suite pass. If CI
  lacks the pinned model, adding an `sbert` allowlist entry is the operator's
  call.
- **Do not write Claude session URLs** into commits, PR bodies or comments.
  One was auto-appended to the PR body on creation and removed; commits on this
  branch deliberately carry none.

## Operator decisions outstanding

1. Which research lane carries the registration: `#267` or `#268`. They insert
   at the identical `ROADMAP.md` position, so the second to merge conflicts.
2. Whether `#264` now drops `tools/memory_formation_m1.py`, the M1 audit and
   its evidence manifest — they live on this branch as of `782820f` and would
   otherwise conflict.
3. Whether to split `#269`, which now mixes E1/B1 docs, runtime code and the M1
   audit. Its body carries a four-way split recommendation.
4. Whether to delete two fully-merged stale branches
   (`origin/codex/s8-r2-spec`, `origin/hackerone`, both 0 unique commits).

## Next unresolved step

Ordered by what unblocks the most:

1. **Bring seam-box online.** Nothing merges until then.
2. Add the `prior_results` seed to the grouped runners, then expose `--resume`
   on top of it; raise the call allowance; add rate-limit-aware backoff. That
   trio is what makes a subscription-limited baseline actually runnable, and
   none of it needs CI.
3. M1 acceptance review → **M2 design freeze**, which is otherwise ready:
   B1 (`docs/BIL_3_SPEC.md`) and E1 (`docs/E1_EVALUATION_CONTRACT.md`) both
   landed.
4. The operator runs the E1-authorized ten-case dev smoke on their own machine
   and reports the measured per-case rate. Expect dev fixture hash prefix
   `75132ee187e058b2` and `case_count` 1198; a mismatch means the split moved
   and the contract is invalid.

M3, M4 and M5 remain unstarted. B2 is implementable now for §3–§7 and §9–§10 of
the BIL-3 spec, which depend on nothing from M2; only §8 does. A CI/CD review
and repo hygiene pass were requested and never delivered as written artifacts —
the seam-box finding came out of that review.
