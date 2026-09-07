# R2 acquisition and backend parity evidence

HISTORY#638 records this implementation; HISTORY#639 records the integrated
verification and corrects the earlier publication-status wording. They continue the structured SQLite slice in
`tests/docs/r2-sqlite-scale.md` from protected main
`ab9fe4b8d0d6a2c8bac4449fb683e2a50539cb03` (PR #252). The governing acceptance
criteria are in `docs/roadmap/TRACK_S_S8_S10_PRODUCTION_CORE.md`, section R2.
Implementation, qualification, protected merge, and S8 freeze are separate
states. The handoff registry owns the current resume pointer.

## Baseline evidence correction and refresh

On 2026-09-07, the earlier release worker reported that it had not authored
the stored PR #252 `QUALIFIED` receipt or completed all the checks attributed
to it. Receipt schema/scope validation alone does not establish independent
authorship. The historical receipt is retained unchanged; its independent
authorship remains unverified. The old `/tmp/seam-r2-evidence` raw-log path is
also no longer available. Its originally recorded hashes remain historical
references, not reconstructed raw logs.

A fresh independent review used a clean detached checkout of the exact merge
SHA above. It found no defect in the sole runtime SQL change against
`2f6e7478f38dad918bc448eaaf53e50764a69525`. It witnessed the public SQLite
scale regression and all six canonical continuity gates exit zero between
00:15:42 and 00:15:51 UTC on 2026-09-07. This establishes current post-merge
evidence, without retroactively establishing earlier review authorship.

Commands used the prefix `PYTHONPATH=.` and interpreter
`/home/terrabyte/Documents/Projects/Seam/.venv/bin/python`:

- `-m pytest -q tests/audit/test_s8_r2_sqlite_scale.py -m 'not external'`
- `-m tools.history.verify_integrity`
- `-m tools.history.verify_routing`
- `-m tools.history.verify_handoffs`
- `-m tools.history.verify_continuity`
- `-m tools.streams.verify_streams`
- `-m tools.docs.verify_wiki`

The portable source identities are adapter SHA256
`74cec5cfbbc97636871315158efe815e3ccd2edebb852b888a32cdde813ca68c` and
SQLite regression SHA256
`af0c219a7ee89c7749b71d6eeb0f32459a95567f359388d952e1b28470f0a721`.
The fresh independent manifest SHA256 is
`4a7301c40ac742bf3377bd167fa27a65d8a0e594147cde5bb68540cdafa8ecb4`;
the test-output SHA256 is
`06955fb47f16312e5d13266c774a2aa4648c46e423cbe6564a92e25b68e39131`.
The manifest and per-command logs are retained locally under the primary
checkout's `.seam/orchestration/completed/r2-sqlite-scale-20260906/independent-refresh/20260907T001542Z/`.

## Acquisition measurement boundary

The public seam for both regressions is `SeamRuntime.retrieve`. The temporal
tests use vector mode with a real, empty vector projection so temporal work is
isolated; the compatibility tests select `legacy-weighted/1` and compare with
the full-batch control. Both use local hash embeddings and fresh SQLite stores.

### Temporal red/green and repair

From the isolated worktree, the original growth regression command was:

```bash
PYTHONPATH=. /home/terrabyte/Documents/Projects/Seam/.venv/bin/python -m pytest -q tests/audit/test_s8_r2_temporal_scale.py -m 'not external'
```

On 2026-09-07 it failed the two growth cases at 00:13:33 UTC (exit 1), then
passed at 00:15:17 UTC (exit 0), with unchanged test SHA256
`8ac5fe568ddad77089b96fb4fdc68674e444f1fd879ada1363fc99fe698db01d`.
Red output SHA256:
`eeb145eb2ad9f3a2289f1ca42b283d46c6a5c614282c466d24f3b4502d877951`.
Green output SHA256:
`99db33d5c94c6f7da021687c7391181685cc33299c5435b1c861e2db3be3ec87`.
Initial invalid-fixture and incorrect trace-assertion attempts are separately
retained and excluded from this TDD evidence.

| Added rows in each boundary | Original temporal MIRL count | Candidate MIRL count | Reference SQL VM steps | Window SQL VM steps |
| ---: | ---: | ---: | ---: | ---: |
| 0 | 9 | 5 | 436 | 538 |
| 128 | 137 | 5 | 4,276 | 3,738 |
| 1,024 | 1,033 | 5 | 31,156 | 26,138 |

These VM counts were recorded before the subsequent timestamp-type repair;
they establish the distinct scan-work boundary, not final-source opcode
budgets. The new tests retain live measurement and require bounded MIRL counts
and zero unlimited temporal loads. The growth loop adds records in the same
boundary, another scope and another namespace while selected results remain
identical. Candidate payloads, scores and fingerprints are compared separately.

Independent review found that numeric payload `t0=20260101` became parseable
after SQLite TEXT affinity converted its column representation. The original
canonical parser rejected this nonstring payload. A dedicated repair preserved
payload type before scoring, with this public red/green command:

```bash
PYTHONPATH=. /home/terrabyte/Documents/Projects/Seam/.venv/bin/python -m pytest -q tests/audit/test_s8_r2_temporal_scale.py -k nonstring_payload_timestamp -m 'not external'
```

Both reference/window cases failed at 00:28:32 UTC and passed at 00:29:00 UTC
on 2026-09-07. The unchanged test SHA256 is
`d5cd8256ca803daf7a3f143c4200ca28cfca51516cd52eba2ee65717dc3d39b0`.
Repair red output SHA256:
`fbea1f8c9e585b1d38478e6da43c7a927ed8c29efab13bd8d70d367d41513ec4`.
The green output SHA256 is the same two-passing-cases output hash recorded
above; identical quiet output does not identify the source or command by itself.
Per-run manifests bind those independently. A final-source green ran at
00:30:05 UTC. The selected new, temporal-semantics and coherence modules
collected and passed 65 tests; exact commands and hashes are retained in
`test_seam/r2-temporal/repair-numeric/`.

Independent rereview reran the original numeric-type reproduction unchanged
and the new temporal plus temporal-semantics modules on 2026-09-07 between
00:32:05 and 00:32:14 UTC. The reproduction and all 39 selected tests passed;
the prior finding is resolved. The final temporal class SHA256 is
`317cca979dbe73fd68f49200869be9900592190e41128d747d87b6c307000bf8`.
The retained independent manifest SHA256 is
`5b1c31d6e3aad59eda0f75024663fa6953b89daf0b66ecac3c47ab858014c100`,
under `test_seam/r2-temporal/assurance/20260907T003205Z/`.

### Compatibility red/green and exact baseline comparisons

```bash
PYTHONPATH=. /home/terrabyte/Documents/Projects/Seam/.venv/bin/python -m pytest -q tests/audit/test_s8_r2_legacy_scale.py -m 'not external'
```

On 2026-09-07 the original two-case regression was red at 00:17:30 UTC and
green at 00:20:50 UTC. Unchanged test SHA256:
`4509186c62d87a90efcc02098724fd8d8bfb9180bf5d912ca1e1fd49f56d242f`.
Red output SHA256:
`1d3d79b0c60c647f3e98f0fd7a227fd0659e48d600ba90e3966d764b22191d07`.
Initial green output SHA256:
`99db33d5c94c6f7da021687c7391181685cc33299c5435b1c861e2db3be3ec87`.
The final expanded module passed 202 cases from 00:26:48 to 00:27:15 UTC;
output SHA256
`493bd3e24415bad8d0eff0d55385106e17d92ccda9dca7bfc14c166ad5fc5e59`.
Earlier fixture failures remain separately labeled, without replacing the
valid red evidence.

The largest non-BM25 fixture has 2,054 rows. Peak live MIRL records fell from
2,054 to 7; payload pages were at most 128 and unlimited acquisition fetches
were zero. Weighted scoring constructed 4,108 records across two scans, while
internal RRF constructed 6,162 across three. The BM25 fixture has 1,026 rows:
weighted peak live records were 8 and total construction 3,078; RRF peak was
7 and total construction 4,104. Its pages also stayed within 128.

Independent assurance loaded the original `ab9fe4b8` retrieval and BM25
implementations from Git and compared them with the extracted batch and stream
paths: 2,304 scoring cases and 288 BM25 cases matched exactly. This checks the
extraction against original code rather than relying only on two new paths
sharing a helper. Explicit iterator closure, scoring-exception cleanup with a
retained traceback, and one snapshot across all passes also passed. Replay
commands and output hashes are retained under
`test_seam/r2-legacy/assurance/`; final source hashes are in
`test_seam/r2-legacy/final-source-hashes.json`.

Temporal ranking can select winners inside SQLite before materializing MIRL
payloads. Timestamp scanning remains proportional to the selected namespace;
the measurement must distinguish SQL work from returned record materialization.

Compatibility scoring requires symbols, graph neighbors, entity labels, and
whole-corpus BM25 statistics. Bounded cursor pages and a weighted top-K heap
can remove retained full-namespace payload batches while preserving these
contexts. Total scoring work still grows with the selected corpus. Internal
RRF needs scalar candidate/channel metadata for exact global ranks; bounded
record materialization does not imply constant total memory.

## Integrated audit and publication boundary

On 2026-09-07, from 00:30:06 to 00:36:05 UTC, the final runtime and regression
sources passed the complete local audit slice:

```bash
PYTHONPATH=. SEAM_DB_PATH=test_seam/r2-closeout/audit-isolated.db /home/terrabyte/Documents/Projects/Seam/.venv/bin/python -m pytest tests/audit/ -m 'not external' -ra --durations=15 -o addopts=
```

The command used an absolute path to the same isolated database. It reported
2,929 passed, 23 explicitly deselected external cases, zero skips, and two
existing fork-with-threads deprecation warnings in migration-lease tests.
The manifest confirms unchanged hashes for all five changed runtime files and
both new test modules before and after the run. Output SHA256:
`baf507ff325db6757170547abb7aff6e35119191c0c73d16515c0f5f85ce470f`.
The command, timestamps and source hashes are retained in
`test_seam/r2-closeout/audit.json`, alongside `audit.log`.

Both independent runtime reviews passed after the temporal repair. Scoped
Ruff and collection of the directly affected modules also passed. The baseline
external pgvector suite separately passed 23 cases against an owned scratch
service; that refresh does not qualify new backend behavior. Required checks
on the pushed acquisition candidate, its release receipt and protected merge
remain pending at this checkpoint. Verify those live before asserting delivery.

## Backend decision boundary

HNSW query/index expression alignment can change exact PostgreSQL scans into
approximate retrieval. An approximate candidate set, including a larger or
reranked set, does not guarantee exact SQLite membership. Equal-score cutoff
direction also requires an explicit common contract: SQLite's historical heap
keeps larger IDs at the cutoff, while later ranking uses smaller IDs first.
The operator choices for exact-default versus optional approximation and the
common tie rule are pending. No default or tie behavior has been changed in
this working packet.
