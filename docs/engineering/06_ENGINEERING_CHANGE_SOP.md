# SEAM Engineering Change SOP

## Purpose

This SOP governs engineering work that changes SEAM code, schemas, interfaces, security posture, benchmarks, documentation policy, or architecture.

Documentation-only typo corrections may use a reduced path, but any change that alters what future engineers should believe is material and must preserve repository continuity.

## Phase 0 — Intake and classification

Record:

- request and intended outcome;
- change classes;
- affected users, agents, interfaces, and data;
- cost-bearing or external-service requirements;
- destructive or irreversible operations;
- known dirty files or parallel workstreams.

Use one or more classes:

- documentation;
- runtime behavior;
- MIRL or schema;
- persistence or migration;
- retrieval or ranking;
- PACK or compression;
- REST, MCP, dashboard, or CLI interface;
- external adapter;
- installer or platform;
- benchmark or evaluation;
- security-sensitive;
- architecture or durable policy.

## Phase 1 — Establish repository state

Before editing:

```bash
git status --short --branch
git fetch origin
git rev-parse HEAD
git rev-parse origin/main
```

Required actions:

1. Confirm the intended base and branch.
2. Identify unrelated dirty files and exclude them from scope.
3. Read the mandatory files in `AGENTS.md` and `skills/seam-engineer/SKILL.md`.
4. Use the latest verified snapshot or index-first context loading.
5. Do not load all of `HISTORY.md`.
6. Confirm active paths using `docs/CODE_LAYOUT.md`.

If the affected baseline is already broken, stop implementation and report the exact reproduction unless the task explicitly authorizes baseline repair.

## Phase 2 — Identify the governing contract

Create a contract table:

| Question | Required answer |
|---|---|
| What is the component supposed to do? | Specification or stable-policy pointer |
| What does active code do now? | Module, symbol, and caller paths |
| What do tests prove? | Named tests and scope |
| What is only planned? | Roadmap pointer |
| What historical decisions constrain it? | Ledger or surgical history refs |
| What remains unknown? | Explicit investigation item |

Do not call a component broken because it fails an invented property. It is broken only when it violates its actual contract or a newly approved requirement.

## Phase 3 — Trace the current architecture

Document the path from input to output:

```text
entrypoint
→ validation
→ shared runtime method
→ canonical read/write
→ derived-state operations
→ output projection
→ external side effects
→ tests and observability
```

For each step record:

- trust level;
- data type and scope;
- canonical versus derived state;
- transaction boundary;
- retry and idempotency behavior;
- failure and rollback behavior;
- logs and exposed errors;
- resource bounds.

## Phase 4 — State a falsifiable hypothesis

Use this form:

```text
Given: <measured baseline, data, environment, commit>
Changing: <one named mechanism>
Should improve: <named metric or failure behavior>
Without degrading: <invariants and guard metrics>
Verified by: <tests, benchmark cases, commands, hashes, artifacts>
```

Reject hypotheses that depend on vague outcomes such as “better memory,” “more intelligent,” or “production grade” without measurable definitions.

## Phase 5 — Establish the baseline

Run the smallest sufficient baseline first, then broader gates when justified.

Capture:

- commit SHA;
- command;
- environment and relevant configuration;
- dataset or fixture hashes;
- random seed and deterministic settings;
- passed, failed, skipped, and xfailed counts with command scope;
- benchmark metrics and artifact paths;
- known nondeterminism;
- elapsed cost where external services are involved.

Do not start a paid run until the operator explicitly confirms that specific run.

## Phase 6 — Write the failure specification

Prefer a red-green sequence:

1. Add or identify a test that fails for the target reason.
2. Confirm the failure is not caused by the test harness.
3. Preserve the smallest input that reproduces it.
4. Include malformed, boundary, negative, and rollback cases where relevant.
5. Avoid tests that only assert implementation details unless those details are part of the contract.

If a finding cannot be reproduced, stop and record the commands and actual outputs. Do not skip reproduction and implement a speculative fix.

## Phase 7 — Implement the smallest coherent change

Rules:

- Change only active, relevant paths.
- Keep unrelated workstreams out of the diff.
- Reuse shared runtime behavior rather than duplicate it in interfaces.
- Preserve canonical/derived separation.
- Keep transactions atomic at the claimed failure boundary.
- Keep optional dependencies optional.
- Do not weaken validation, fidelity, provenance, or gates for a metric gain.
- Do not silently change defaults without measured evidence and documentation.
- Add compatibility or migration handling when persistent formats change.
- Keep error messages useful to operators but safe for untrusted clients.

## Phase 8 — Focused verification

Run:

1. the new or previously failing test;
2. directly affected module tests;
3. relevant audit tests;
4. syntax, import, or collection checks;
5. real-adapter smoke when an adapter contract changed;
6. security negative tests when a boundary changed.

Record actual commands and outputs. Never report an unrun check as passing.

## Phase 9 — System verification

Select applicable gates from `VERIFICATION_MATRIX.md` and `07_TEST_AND_BENCHMARK_SOP.md`.

Typical repository gates include:

```bash
python -m pytest test_seam_all/test_seam.py -q
python -m pytest tests/audit -q
python -m pytest tools/history tools/streams -q
python -m tools.history.verify_integrity
python -m tools.history.verify_routing
python -m tools.history.verify_continuity
python -m tools.streams.verify_streams
git diff --check
```

Use the current canonical commands from repo documentation rather than hard-coding obsolete test totals. External tests must run against the required service or be intentionally deselected according to repository policy; do not hide a missing service as a silent skip.

## Phase 10 — Benchmark and adversarial review

When behavior, fidelity, retrieval, density, latency, resource use, or answer quality changes:

1. run the same baseline and after-state cases;
2. compare per-case and aggregate deltas;
3. inspect regressions, not only the mean;
4. test displacement and precision as well as recall;
5. verify determinism or quantify variance;
6. keep tuning and holdout publication separate;
7. verify artifact hashes and gates;
8. record cost and judge/model versions;
9. perform adversarial inputs targeted at the changed mechanism.

A metric improvement is rejected when it is purchased by reduced provenance, exactness, isolation, safety, or holdout discipline.

## Phase 11 — Security review

Complete the threat-model delta when any trust boundary, write path, parser, provider call, interface, credential flow, or agent tool changes.

At minimum answer:

- What new input can an attacker control?
- What new state can be read or written?
- Can the change cross scopes?
- Can retrieved text trigger action?
- Can failures leak secrets or corrupt canonical state?
- Are resource bounds enforced before allocation or external calls?
- Is rollback correct under partial failure?
- What negative tests prove the controls?

See `05_SECURITY_ARCHITECTURE.md`.

## Phase 12 — Documentation and durable state

Update the narrowest authoritative source:

- product contract: spec or MIRL contract only with explicit approval;
- stable architecture or policy: `REPO_LEDGER.md` and relevant manual page;
- current state and active focus: `PROJECT_STATUS.md`;
- current code routing: `docs/CODE_LAYOUT.md`;
- commands and operator workflow: focused runbook;
- chronological evidence: append `HISTORY.md`;
- roadmap status: roadmap source and regenerated derived state;
- tests: tracked notes under `tests/docs/`;
- generated test artifacts: ignored `test_seam/<area>/`.

Use pointers instead of copying long, volatile prose into several files.

## Phase 13 — Continuity and handoff

When state changed:

1. append one history entry with previous state, new state, verification, failures, and next steps;
2. rebuild the history index;
3. write one snapshot;
4. run integrity, routing, continuity, and stream verification;
5. regenerate roadmap and cross-stream derived views when their sources changed;
6. scan candidate files for secrets and provider-session URLs;
7. update the draft PR with scope, evidence, risks, and exclusions.

If work stops incomplete, leave an explicit in-progress breadcrumb naming touched files, missing pieces, test mismatches, and the first reproduction command.

## Required handoff format

Use `templates/ENGINEERING_HANDOFF.md`. Every handoff must include:

- scope and classification;
- governing contracts;
- diagnosis and causal evidence;
- hypothesis and baseline;
- implementation summary;
- exact verification commands and results;
- benchmark delta or non-applicability;
- security delta;
- documentation and continuity updates;
- known limitations, failures, and next action.

## Completion criteria

Do not mark the change complete unless code, tests, benchmarks, security analysis, documentation, and continuity records agree. A clean diff without evidence is not completion; neither is a benchmark gain without fidelity and safety gates.
