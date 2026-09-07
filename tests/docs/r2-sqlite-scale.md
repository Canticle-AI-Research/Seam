# R2 structured SQLite fixed-slice evidence

HISTORY#637 records this partial R2 implementation. The governing plan is
`docs/roadmap/TRACK_S_S8_S10_PRODUCTION_CORE.md`; recovery routes through
`docs/handoffs/INDEX.md`.

Evidence refresh (HISTORY#638): the original `/tmp` raw logs are no longer
available, and the old release receipt's independent authorship is unverified.
Fresh post-merge independent checks and retained evidence are recorded in
`tests/docs/r2-acquisition-parity.md`. The original observations below remain
historical; their hashes do not replace missing raw logs.

## Change and public contract

`_build_structured_sql` now looks up `max(source_text)` by canonical record ID
using the existing composite `vector_index` primary key. It no longer groups
the vector table across all namespaces before joining selected records.
No index or migration is added. MAX remains case sensitive and precedes
lowercasing; missing vectors use the canonical payload, while an empty source
stays empty. Existing filters, scores and ID ties are unchanged.

The public test seam is `SeamRuntime.retrieve(mode="hybrid")` with explicit
hash embeddings. There is no public `sql` mode. Synthetic vector model names
make the real semantic adapter return no hits. SQLite trace/progress callbacks
count instructions only during the structured SQL statement; an assertion
requires exactly one measured statement and positive work. Candidate payloads,
SQL-leg traces and candidate fingerprints must stay identical across growth.

## Witnessed red and green

Command, from the isolated worktree at baseline
`2f6e7478f38dad918bc448eaaf53e50764a69525`:

```bash
PYTEST_ADDOPTS=-rP PYTHONPATH=. /home/terrabyte/Documents/Projects/Seam/.venv/bin/python -m pytest -q tests/audit/test_s8_r2_sqlite_scale.py -m 'not external'
```

On 2026-09-06, red ran at 09:22:47–09:22:53 UTC (exit 1; two scale failures,
six behavioral passes). Green ran at 09:23:22–09:23:28 UTC (exit 0; eight
passes). The exact test file was unchanged. An earlier fixture-authoring error
omitted the required canonical ENT subject; it was corrected before the
recorded red run and is not evidence of the runtime defect.

Four selected CLM records remain fixed. Added records belong to another
namespace and each has two vector rows. The selected fixture has three vector
rows and one payload-fallback record.

| Unrelated records | Namespace: before / after instructions | Namespace + scope: before / after instructions |
| ---: | ---: | ---: |
| 0 | 765 / 1,156 | 824 / 1,215 |
| 256 | 11,519 / 1,164 | 11,578 / 1,223 |
| 4,096 | 172,799 / 1,164 | 172,858 / 1,223 |

The assertion permits at most the current baseline plus 128 instructions,
allowing small SQLite opcode variation while rejecting a pass through the
unrelated rows. The tiny initial slice costs more after the change; the
improvement removes work proportional to unrelated namespaces. Selected-slice
growth and more vectors attached to selected records remain proportional work.

SHA256 evidence:

- Unchanged red/green test file:
  `af0c219a7ee89c7749b71d6eeb0f32459a95567f359388d952e1b28470f0a721`
- Red output:
  `06033e60e7d5a0563710225ff215ceb70d50ada4200ce67af6c649869fa50c26`
- Green output:
  `d0ae7aa001afb03a44d85e9ac60ca5fe2620c4da0102b565f9028cd92204eb02`
- Candidate adapter file:
  `74cec5cfbbc97636871315158efe815e3ccd2edebb852b888a32cdde813ca68c`

Local raw logs and metadata are in `/tmp/seam-r2-evidence`; session-state TDD
records retain commands, times and output hashes. These are local evidence,
not part of the portable source artifact. The test reproduces the growth
measurement on the candidate source.

## Verification boundary and remaining work

Collection of `tests/audit/test_s8_r2_sqlite_scale.py` succeeds. The focused
selection of `tests/audit/test_s8_r1_retrieval_contract.py`,
`tests/audit/test_s8_retrieval_coherence.py`,
`tests/audit/test_temporal_semantics_contract.py` and
`tests/audit/test_retrieval_consolidation.py` passed outside the sandbox.
The initial sandbox run and its diagnostic rerun stalled at the existing REST
TestClient thread portal and were interrupted; the unrestricted rerun completed
with exit 0. This is an environment observation, not a runtime repair.
Ruff for the changed Python files and `git diff --check` pass.

The first complete non-external `tests/audit/` run failed only two tests in
`tests/audit/test_locomo_result_durability.py`, whose default-result assertions
require a repository outside `/tmp`. Moving the same worktree intact into the
primary repository's `.worktrees/r2-sqlite-scale-20260906` directory made that
module pass. No test or production change was used to avoid the constraint.
The complete audit selection is rerun there for final qualification.

Final audit-suite, independent assurance, canonical continuity and exact-head
CI results must be checked in the candidate PR and release receipt before
merge. The handoff retains remaining R2 tasks. This evidence does not establish
flat whole-request hybrid latency, temporal or compatibility acquisition
bounds, backend parity, S8 freeze, S9 promotion, or hosted readiness.
