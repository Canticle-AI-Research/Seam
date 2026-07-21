# LongMemEval and BEAM execution-contract repair

Date: 2026-07-20

Status: implementation and local validation complete

Scope: SEAM external-memory benchmark routing only

## Decision

Do not implement a second approximate LongMemEval or BEAM scorer inside SEAM.
Use SEAM's existing loopback Mem0-compatible HTTP facade as the memory system
and run the audited `mem0ai/memory-benchmarks` checkout unmodified. Keep the
in-repo LongMemEval and BEAM parsers as fail-closed structural validators.

This is the same position successful memory systems converge on: a shared
evaluation harness, benchmark-specific ingestion/prompt/scoring, and one memory
API under test. Mem0's current public harness exposes LoCoMo, LongMemEval, and
BEAM through the same OSS HTTP client. Downloading or running Mem0 itself is not
required for the SEAM arm.

Canonical external sources:

- LongMemEval official repository and cleaned data contract:
  https://github.com/xiaowu0162/longmemeval
- BEAM official repository and scale/question contract:
  https://github.com/mohammadtavakoli78/BEAM
- Mem0 evaluation harness:
  https://github.com/mem0ai/memory-benchmarks

## Defects found

### LongMemEval

1. Documentation collapsed five abilities and six official `question_type`
   values into an incorrect five-category schema.
2. The local parser discarded `question_date`, evidence-session ids, and the
   `_abs` abstention marker.
3. Dates, sessions, ids, roles, duplicate ids, and empty content were not
   validated strictly.
4. The fixture hash covered only ids/questions/answers, so different memory
   histories could share a hash.
5. The nominal real-run path used `SeamLocomoAdapter` without an answerer, then
   sent an empty prediction through the generic judge. It was not the official
   LongMemEval answer/judge contract and could not support a competitive score.

### BEAM

1. Documentation labeled the 1M track as the whole 100-conversation / 2,000-
   question release. The official 1M track is 35 / 700; 10M is 10 / 200.
2. The directory loader created benchmark cases with an empty conversation.
3. JSON-list roots failed because the loader called `.get()` before checking
   the root type.
4. Official batch-dict and 10M plan-shaped chat encodings were not normalized.
5. Rubric dictionaries/nuggets and empty chat/question/rubric failures were not
   validated.
6. The nominal real-run path used the generic LoCoMo answer judge, not BEAM's
   independent 0/0.5/1 nugget scoring or event-ordering evaluation.
7. The CLI described BEAM-10M as refused but did not have a real-execution gate.

### Shared routing and documentation

1. Active documentation still pointed to the retired
   `benchmarks.external.mem0_harness.adapter` module.
2. The benchmark README incorrectly said the stub judge always returns correct;
   the implementation correctly abstains and makes no score claim.
3. No common gate verified the audited harness revision, isolated harness
   Python, loopback-only facade URL, BEAM dependency, provider-spend approval,
   or separate 10M approval before execution.
4. Targeted CLI `--plan` was ignored and could proceed toward execution; a
   missing BEAM cache could also trigger an implicit large download.
5. The shared facade collapsed every upstream epoch to a date, losing the
   sub-day anchors used by LongMemEval and BEAM temporal questions.

## Repair

`benchmarks/external/mem0_harness/upstream_runner.py` now:

- pins `memory-benchmarks` at
  `4b61c5d31b9c668a12b4f5e78064248a02c82d2b`;
- requires the harness's isolated `.venv`;
- builds argv without shell interpolation or credentials;
- accepts only an explicit loopback Mem0 facade URL;
- maps LongMemEval to all 500 official questions by default;
- maps BEAM `1m` to `1M`, conversations `0-34`, top-k 200, and cutoffs 50/200;
- detects the missing `datasets` dependency before BEAM execution;
- reports targeted readiness through a no-execution `--plan` path;
- refuses a missing-cache BEAM download without `--allow-download`;
- refuses paid answer/judge execution without `--allow-paid`;
- refuses BEAM-10M without the separate `--allow-10m` gate.

The facade keeps LoCoMo's pinned date-only envelope unchanged while preserving
full UTC second-level timestamps for audited LongMemEval/BEAM ids.

The local validators now preserve the missing metadata, validate complete
conversation/rubric structure, and hash the actual memory corpus represented by
the cases. Their old generic scored execution path is removed. The `seam bench
external` CLI exposes the upstream route without repurposing the LoCoMo scorer.

## Current machine readiness

- Pinned harness checkout: present at `/tmp/memory-benchmarks`, exact revision.
- Harness isolated environment: present.
- SEAM Mem0 facade: implemented and contract-tested.
- LongMemEval cleaned dataset: not present in the checked paths.
- BEAM dataset/cache: not present in the checked paths.
- BEAM harness `datasets` dependency: not installed in the isolated harness
  environment.
- Mem0 itself: `mem0ai==2.0.2` is already available in SEAM's environment, but
  it is not required to run SEAM through the upstream harness.

No package installation, large dataset download, provider call, or benchmark
score occurred during this repair.

## Temporal capability boundary

This repair preserves the benchmark evidence that exists without claiming a
broader temporal model than SEAM currently has. LongMemEval and BEAM RAW turn
envelopes now retain second-level UTC timestamps; the pinned LoCoMo date-only
envelope remains unchanged. MIRL, storage, and the graph schema can represent
`t0`, `t1`, validity windows, supersession, and created/updated timestamps, but
ordinary conversation ingest does not reliably populate event-time `t0`/`t1`
or classify ongoing, completed, and historical lifecycle at collection time.
Ingestion `created_at` is not a substitute for event time.

LongMemEval `question_date` reaches the upstream answer contract but is not yet
part of the facade retrieval request, and `seam_runtime.temporal.parse_iso`
accepts fewer timestamp variants than the real benchmark corpora contain.
Those are explicit future product/measurement gaps; they were not silently
expanded into a core temporal rewrite in this benchmark-routing repair.

## Graph-memory measurement boundary

Graph memory remains a vital competitive direction. SEAM already maintains a
canonical MIRL-to-graph projection and supports graph retrieval, but this
repair does not add benchmark-specific graph composition and does not prove a
graph score gain. The next graph step must be a free matched-harness evidence
presence and displacement measurement against the current facade output. Only
an observed gain with bounded regressions should advance to a paid score gate.

## Final local verification

- Touched collect-only: 51 tests resolved.
- Focused LongMemEval/BEAM/upstream/facade slice: 51 passed.
- Strict non-external suite: 1,627 passed, two established xfails, zero skips.
- External pgvector suite: 10 passed, zero skips after binding both documented
  DSN variable names to the same existing local service without printing it.
- Touched Ruff, module compilation, `git diff --check`, and the candidate
  secret/private-session-link scan: clean.

The first external attempt intentionally exposed the environment boundary:
setting only `PGVECTOR_TEST_DSN` ran four tests while six strict no-skip checks
failed because the real-adapter module also gates on `SEAM_PGVECTOR_DSN`. The
corrected run passed all ten. No service install, dataset/model download,
provider call, paid work, BEAM-10M execution, or push occurred.

## Safe execution sequence

1. Validate/download LongMemEval outside the repo, then run a small stratified
   upstream predict-only smoke before all 500 questions.
2. Install `datasets` only in the isolated upstream-harness environment after
   operator approval; download BEAM to an external cache with adequate space.
3. Run one BEAM conversation predict-only before the 35-conversation 1M track.
4. Measure ingestion time, retrieved-evidence presence, scope isolation, and
   pack displacement before any answerer/judge call.
5. Only then approve a matched scored run. Never compare a local generic score
   with Mem0's published task-specific score.

LongMemEval-S represents roughly 115K tokens per question-specific history.
BEAM-1M contains 35 approximately million-token conversations. These are not
small follow-up commands; checkpoint/resume, external storage, and persistent
shell execution are mandatory.
