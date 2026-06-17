# SEAM Test and Benchmark SOP

## Purpose

This SOP defines how engineers establish evidence that a SEAM change works, improves the intended property, and does not silently regress fidelity, provenance, safety, isolation, or reproducibility.

## Evidence hierarchy

From weakest to strongest:

1. static inspection;
2. syntax or import success;
3. focused unit test;
4. negative and malformed-input test;
5. integration test across the real call path;
6. real-adapter or external-service smoke;
7. deterministic benchmark on fixed fixtures;
8. repeated evaluation with measured variance;
9. sealed, hash-verified holdout publication bundle.

Do not use a lower evidence class to claim a higher one. A smoke test does not establish production readiness. A stub judge does not establish answer quality. A benchmark aggregate does not prove every case improved.

## Test selection principles

Tests should verify contracts, not incidental implementation details.

For each change, include the smallest applicable set of:

- happy-path behavior;
- boundary values;
- malformed input;
- negative authorization or isolation;
- rollback and partial failure;
- retry and idempotency;
- concurrency;
- resource bounds;
- error redaction;
- exact round-trip or reconstruction;
- provenance and reference retention;
- backward compatibility or migration;
- shutdown and recovery.

## Baseline discipline

Before implementation, record:

- git SHA;
- command and selected tests;
- operating system and relevant dependency versions;
- configuration and environment variables, with secrets redacted;
- fixture, dataset, and bundle hashes;
- seed, temperature, top-k, and other determinism controls;
- pass, fail, xfail, and intentionally deselected counts with command scope;
- benchmark metrics;
- external cost and model/judge identifiers when applicable.

Do not compare results produced by different datasets, scopes, budgets, judges, or configuration and describe the difference as a code effect.

## Red-green protocol

1. Add or identify a case that fails for the target reason.
2. Run it before the fix and preserve the failure output.
3. Apply the smallest coherent change.
4. Run the same case and confirm the expected transition.
5. Run nearby regression tests.
6. Run the applicable system gates.

A test added only after implementation is weaker evidence unless the pre-change failure is reconstructed against the baseline commit.

## Benchmark classes

### Fidelity and exactness

Use for:

- MIRL compilation;
- readable compression;
- lossless envelopes;
- surfaces;
- exact PACK modes;
- source reconstruction.

Guard metrics include:

- exact text or byte equality;
- hash equality;
- quote/span/table-cell retention;
- direct-query exactness;
- record-reference coverage;
- provenance and evidence retention;
- corruption rejection.

Exactness gates are binary unless the governing contract explicitly defines tolerance.

### Retrieval

Use for lexical, vector, graph, temporal, hybrid, and mix changes.

Measure:

- recall at fixed candidate and context budgets;
- precision and irrelevant-context rate;
- rank of the first relevant record;
- displacement of relevant evidence;
- per-category and per-query deltas;
- trace correctness;
- scope isolation;
- latency and resource cost.

Recall alone can overstate quality when the context becomes larger or noisier. Measure whether the downstream answerer converts retrieved evidence without dilution.

### Context and PACK density

Measure:

- token count and compression ratio;
- semantic or task retention;
- reference, provenance, and evidence retention;
- reconstruction where required;
- answer quality at a fixed prompt budget;
- added metadata overhead;
- regressions on short and long inputs.

A denser representation is accepted only when recovery and utility remain within the governing gates.

### Answer quality

Record:

- answerer and judge identity;
- prompts or scoring rubric;
- deterministic settings;
- repeated-run agreement;
- abstention behavior;
- per-category scores;
- retrieval-miss versus answerer-miss classification;
- confidence intervals or observed variance when feasible.

Do not treat temperature zero as proof of determinism. Verify repeated outputs.

### Performance and resource bounds

Measure relevant dimensions:

- wall-clock latency;
- throughput;
- peak memory;
- disk growth;
- database query count;
- index rebuild time;
- context size;
- provider calls and cost;
- startup and shutdown behavior.

Use fixed workloads and report the environment.

## Tuning versus holdout

- Tune only on development data.
- Do not inspect holdout answers to select levers.
- Holdout runs require explicit publication intent and required authorization.
- Paid judged validation requires fresh operator confirmation for that run.
- Publication artifacts must identify the evaluated commit, data split, fixtures, judge, hashes, and gate output.

Any holdout leakage invalidates the affected publication claim and triggers incident review.

## Determinism

Engineers must identify and control:

- random seeds;
- model sampling parameters;
- model and embedding revisions;
- concurrent ordering;
- timestamps;
- filesystem iteration order;
- database row ordering;
- network-dependent responses;
- judge variance.

When deterministic control is impossible, repeat the evaluation and report variance. Do not present one favorable run as a stable result.

## Artifact integrity

Benchmark evidence intended for comparison or publication should include:

- result report;
- bundle hash;
- case hashes;
- fixture hashes;
- git SHA;
- configuration;
- diff output;
- gate output;
- holdout output when applicable;
- tool and model versions;
- cost record when external services were used.

Generated artifacts belong outside source paths or under the repository's designated ignored output directories unless explicitly promoted as fixtures.

## Regression analysis

After a benchmark run:

1. inspect every regression above the accepted threshold;
2. compare per-case additions and removals;
3. identify whether the cause is ingest, indexing, ranking, packing, or answering;
4. check whether larger budgets are masking ranking failures;
5. check whether the metric rewards duplication, leakage, or verbosity;
6. verify that a security or fidelity gate was not weakened;
7. record regressions that remain accepted and why.

## Claim language

Permitted claim form:

```text
On <named benchmark and split>, at commit <sha>, under <configuration>,
<change> moved <metric> from <baseline> to <after> across <scope>.
The required gates <passed/failed>, observed variance was <value or unknown>,
and the result does not establish <explicit limitations>.
```

Avoid unsupported words such as “best,” “solved,” “production proven,” “secure,” or “commercial grade.”

## Minimum command record

For each verification action, record:

```text
command:
working directory:
commit:
environment/config:
result:
artifact path:
limitations:
```

Never write “tests pass” without naming the command and scope.

## Failure handling

- A failing baseline blocks unrelated improvement work.
- A non-reproducible finding blocks speculative remediation.
- A flaky test must be diagnosed, not rerun until green and ignored.
- A benchmark harness bug invalidates results produced through that path until corrected and rerun.
- A paid run started without authorization must be stopped and recorded.
- A hash mismatch invalidates the artifact.
- Holdout leakage triggers `08_INCIDENT_RESPONSE.md`.
