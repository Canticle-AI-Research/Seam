# E1 evaluation contract (memory-formation campaign)

**Contract version:** `e1-evaluation/1.1`. The originally frozen text
(HISTORY#648) is retroactively `e1-evaluation/1.0`; it defined no version
string, which made both the amendment rule below and §3's per-run version
record unexecutable. Amended before any run, so no result exists under 1.0.
**Status:** frozen contract for the memory-formation baseline/candidate campaign.
**Chronology:** HISTORY#648, amended HISTORY#650. **Stream:** E1 of [Memory formation](roadmap/MEMORY_FORMATION.md).
**Transport procedure:** [Claude Code benchmarks](CLAUDE_CODE_BENCHMARKS.md).
**Traps that shaped this contract:** [benchmark traps](kb/eval-methodology/benchmark-traps.md).

This document freezes the evaluation conditions **before** any paid campaign run,
so a later formation change is measured against fixed conditions rather than
conditions chosen after seeing a result. Freezing the contract is not a result:
no benchmark has been run under it, and no score is claimed here.

Changing any frozen value below requires a new HISTORY entry and a new
contract version. A changed contract invalidates cross-version comparison;
capture a fresh baseline rather than comparing across contract versions.

## 1. Dataset

| Field | Frozen value |
| --- | --- |
| Dataset | LoCoMo, `benchmarks/external/locomo/data/locomo10.json` |
| Dataset SHA-256 | `79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4` |
| Size | 2,805,274 bytes; 10 conversations; 1,986 QA pairs |
| Runner case set | 1,542 cases after runner validation |
| Full-set fixture hash | `405308a9159b88dd0675b798f59a3af16cdcc7061c31a6fcccc1638fe7f86d36` |
| Upstream | `snap-research/locomo`, recorded in `locomo10.manifest.json` |

Category counts over the 1,542 runner cases: `1`=282, `2`=321, `3`=96,
`4`=841, `5`=2. Category 5 is effectively absent and no category-5 claim may
be made from this dataset.

## 2. Split

The dev/holdout partition is pinned by a committed manifest so it cannot drift
silently. Before this contract the split existed only as the runner's default
salt and ratio, reproducible by convention but not recorded in git.

| Field | Frozen value |
| --- | --- |
| Manifest | `benchmarks/external/locomo/holdout_assignment.json` |
| Manifest schema | `seam-holdout-split/v1` |
| Manifest SHA-256 | `ea3e481ee052c620cc22aef4127a423e9b2e1c5d95f720911c8627ec4ccbfad4` |
| Salt | `seam-locomo-v1` |
| Ratio | 0.8 dev |
| Assignments | 1,542 |
| Dev | 1,198 cases, fixture hash `75132ee187e058b2…` |
| Holdout | 344 cases, fixture hash `35df739c70d7a781…` |

Generating the manifest reproduced the previously implicit split exactly
(`dev=1198 holdout=344 added=1542 unchanged=0`), and the runner's `--split`
fixture hashes are unchanged by its introduction. Committing it pins current
behavior; it does not alter any past result.

**Holdout rule.** The holdout partition is not read, tuned against, inspected
per-case, or used to select a candidate. It is exposed once, at the end of a
campaign, to confirm a result already established on dev. Any holdout
exposure is recorded in HISTORY with its reason.

## 3. Baseline identity

The baseline is captured from an identified commit **before** the first
behavior-changing formation commit exists. Every run records:

- exact git SHA and dirty-state (a dirty tree disqualifies a baseline)
- this contract's version
- dataset, split-manifest and fixture hashes from §1-§2
- answerer/judge identity and served model from §4
- retrieval configuration from §5

A baseline reconstructed after a candidate exists is not a baseline.

## 4. Answerer and judge

| Field | Frozen value |
| --- | --- |
| Transport | `claude-code` (Claude.ai subscription, API credentials excluded) |
| Answerer | `--answerer claude-code`, model `claude-haiku-4-5-20251001` |
| Primary judge | `--judge claude-code`, model `claude-haiku-4-5-20251001` |
| Cross-judge | off for baseline; enabled only for a declared agreement study |
| Batch judging | **Not available on this transport.** The runner rejects `--judge-batch` when the judge is `claude-code` (`benchmarks/external/locomo/run.py`: "claude-code does not support --judge-batch; no paid calls were made"). `ClaudeCodeJudge` has no `score_batch` method by design. The 50% Batch-API discount exists only on the separately billed `claude` API route, which this contract excludes. All judging is synchronous, one call per case. |

The `claude` choice is the separately billed API route. The two transports are
never mixed inside one baseline/candidate comparison.

**Declared limitation — answerer strength.** Benchmark trap 2 records that a
context-assembly lever scored net +5 against a weak answerer and net +1
against a strong one. Formation changes are context-assembly-adjacent, so a
gain measured on `claude-haiku-4-5` may shrink or vanish on a stronger
answerer. Haiku is chosen here for cost, and is valid for the internal
question "did formation change behavior under fixed conditions". It is **not**
sufficient for an external quality claim: any positive dev result must be
re-confirmed on a stronger answerer before it leaves this repository.

**Scoreboard separation.** Benchmark trap 4: this subscription lane is a named
separate lane. Its numbers are never averaged with, or quoted against, the
mem0-harness lenient-judge scoreboard or any published comparator table.

## 5. Retrieval configuration

Held **fixed** across every arm, so a measured delta is attributable to
formation rather than ranking:

| Field | Frozen value |
| --- | --- |
| Retrieval policy | `legacy-weighted` (current compatibility default) |
| Search top-k | 100 |
| Context budget | 8,000 characters |
| Embeddings | real cached local embeddings; never stubbed |
| Store | SQLite |

Retrieval weights are not tuned during the formation campaign. A retrieval
change and a formation change may not ship in the same measured arm.

## 6. Metrics

**Primary:** judged answer correctness over the dev split, reported overall
and per category, with the judge from §4.

**Secondary, free, never promoted:** string-match scoring and retrieval
recall. Benchmark trap 5 records that token-overlap recall inflated an
"answerer had evidence" bucket from ~35% to 52%. Free metrics triage and rank;
they never establish a win.

**Also recorded per run:** ingest time and cost, storage growth, retrieval
latency, provenance coverage, per-case answer deltas, and counts of
unchanged/failed cases.

Retrieval recall and answer quality are reported as separate measurements. A
recall increase alone is not an answer-quality result and does not qualify a
promotion.

## 7. Uncertainty and no-change control

Required before any candidate delta is interpreted.

Benchmark trap 1 records that re-answering 13 stored misses with the same
model, same context and no lever recovered 6/13 — roughly 46% of that miss set
was unstable. A single-run delta is therefore not evidence on its own.

**Control procedure.** Re-run a fixed 300-case dev subset with zero changes,
same commit, same configuration. The observed flip rate is the noise floor for
this contract, recorded with the baseline.

**Interpretation rule.** A candidate-versus-baseline delta smaller than the
recorded noise floor is reported as *no detected change*, never as an
improvement or a regression. A lever's isolated effect is candidate-arm minus
baseline-arm **within the same rerun**, never candidate-arm minus a stored
label.

## 8. Re-ingest policy

Each formation arm is **freshly re-ingested**. `--keep-db` is forbidden for
formation comparisons because it bypasses the changed ingestion behavior that
is under test.

Benchmark trap 8 records that a fresh re-ingest shifted 316/378 top-200 lists
(mean Jaccard 0.924) while remaining miss-set-neutral, with two already-correct
cases losing partial evidence. Expect ±1-2 cases of ranking churn from
re-ingest alone; that churn is part of the noise floor, not a formation
result. Frozen-context and fresh-reingest experiments answer different
questions and carry separate labels.

## 9. Cost, ceilings and abort criteria

| Field | Value |
| --- | --- |
| Observed per-case cost | $0.008487 (answerer + judge, one quickstart case) |
| Nature of that figure | **lower bound** — a small synthetic fixture, not a full-context case |
| Projected dev run (1,198) | ~$10.17 at the observed rate, before context growth |
| Projected holdout run (344) | ~$2.92 |
| Projected full set (1,542) | ~$13.09 |

No batch discount is assumed in any figure above: the observed rate is the
synchronous `claude-code` rate, which is the only rate this transport has. The
projections were never inflated by an unavailable discount and do not shrink
now that the row is corrected.

**Authorized now:** a bounded ~10-case dev smoke, ceiling $0.50, whose purpose
is to measure the true per-case cost on real cases. No full run is authorized
by this contract; the full-run budget is set from the smoke's measured rate in
a separate operator decision.

**Abort criteria.** Stop and report rather than continue when: measured
per-case cost exceeds twice the projection; the provider login or allowance
fails; malformed judge verdicts exceed 2% of cases; or any run would touch the
holdout without a recorded decision.

**Accounting honesty.** Benchmark trap 7: result artifacts retain only the last
clean pass per case, so aborted and retried calls bill without leaving a trace.
Every reported total is a **lower bound** on real spend. CLI-reported usage is
list value, not a verified subscription debit. Reservations are process-local
and a restarted process starts a fresh allowance; these settings are not an
account-wide ceiling.

## 10. Evidence retention

Every run seals a BIL-2 bundle via `seam_runtime/benchmark_integrity.py` and
files it per [reports and evidence](REPORTS_AND_EVIDENCE.md).

**Known BIL-2 limitations**, recorded as B1 input in the
[reconciliation audit](audits/2026-09-18-roadmap-fork-reconciliation.md) and
scheduled for repair under B2: keyless verification of a signed bundle can
return `PASS` on altered content; the HMAC seal is symmetric so it cannot
support third-party attestation; latency fields are excluded from the result
hash and are therefore unsigned; and the git SHA, fixture hash and dataset
name are caller arguments never bound into the signed block. Until B2 lands,
a BIL-2 bundle from this campaign is integrity evidence for this repository's
own use, not an external attestation, and its timing numbers carry no seal.

## 11. Commands

Dry-run inspection, free:

```
python -m benchmarks.external.locomo.run \
  --dataset-path benchmarks/external/locomo/data/locomo10.json \
  --split dev --dry-run
```

The authorized bounded smoke, paid, ceiling $0.50:

```
python -m benchmarks.external.locomo.run \
  --dataset-path benchmarks/external/locomo/data/locomo10.json \
  --split dev --limit 10 \
  --answerer claude-code --answerer-model claude-haiku-4-5-20251001 \
  --judge claude-code --judge-model claude-haiku-4-5-20251001 \
  --allow-paid --output <run-artifact.json>
```

Follow [the transport procedure](CLAUDE_CODE_BENCHMARKS.md) for login checks,
allowance settings and timeouts. `--limit` caps cases within the split, so the
smoke draws from dev and never from holdout.

## 12. What this contract does not establish

It fixes conditions only. It does not report a score, does not establish a
baseline, does not demonstrate that memory formation is deficient, and does
not authorize a full campaign. The chunking hypothesis remains a hypothesis
until M1's audit is accepted and a measured comparison exists.
