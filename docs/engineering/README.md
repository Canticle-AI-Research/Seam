# SEAM Engineering Architecture and Change-Control Manual

This manual is the canonical engineering entrypoint for understanding, modifying, securing, validating, and maintaining SEAM.

It is written for software engineers, AI architects, security engineers, benchmark engineers, infrastructure engineers, and autonomous engineering agents operating on the repository.

It does not replace the governing specification, MIRL contract, repo ledger, history stream, tests, or operator runbooks. It identifies those sources, defines their authority, and explains how to use them together without duplicating them.

## Authority order

When sources disagree, resolve the conflict in this order:

1. `SEAM_SPEC_V0.1.md` and `docs/MIRL_V1.md` for product behavior and representation contracts.
2. Active code and tests for implemented behavior.
3. `REPO_LEDGER.md` for stable engineering policy and architectural decisions.
4. `PROJECT_STATUS.md` for current operating state and active focus.
5. `HISTORY.md`, read surgically through `HISTORY_INDEX.md` or context-pack tooling, for chronological evidence.
6. `ROADMAP.md` and derived roadmap state for planned behavior.
7. Archived documents and code only for historical analysis.

A roadmap statement is not implementation evidence. A historical entry is not proof that the behavior still exists. A test proves only the property and scope it actually exercises.

## Evidence labels

Use these labels in architecture reviews and documentation:

- **Contract**: required by a governing specification.
- **Implemented**: present in current active code.
- **Tested**: covered by a named automated test.
- **Measured**: supported by a reproducible benchmark or experiment.
- **Operational policy**: required engineering or operator procedure.
- **Planned**: approved direction not yet implemented.
- **Experimental**: implemented for evaluation but not accepted as canonical.
- **Known gap**: desired or required behavior not currently satisfied.
- **Historical**: retained for provenance but no longer active.
- **Unknown**: not yet verified.

Never promote a planned, experimental, historical, or unknown property into a statement of current behavior.

## Epistemic rule

A correct, justified abstention is better than an unsupported answer. Fabricated evidence, invented test results, and false certainty are integrity failures.

However, abstention is not rewarded unconditionally. Engineers and agents must perform the bounded investigation required by the task before declaring something unknown. See [Epistemic calibration and abstention](09_EPISTEMIC_CALIBRATION.md) for the required states, scoring matrix, hard gates, and benchmark design.

## Manual map

- [Architecture](01_ARCHITECTURE.md): system boundaries, canonical state, data and control flow, component ownership, and invariants.
- [Security architecture](05_SECURITY_ARCHITECTURE.md): assets, trust boundaries, AI-memory threats, agentic threats, controls, and secure review procedure.
- [Engineering change SOP](06_ENGINEERING_CHANGE_SOP.md): mandatory workflow for understanding, changing, and handing off SEAM.
- [Test and benchmark SOP](07_TEST_AND_BENCHMARK_SOP.md): evidence hierarchy, baseline discipline, regression gates, and publication claims.
- [Incident response and recovery](08_INCIDENT_RESPONSE.md): containment, preservation, eradication, recovery, and post-incident evidence.
- [Epistemic calibration and abstention](09_EPISTEMIC_CALIBRATION.md): rewards justified uncertainty, penalizes unsupported certainty, and defines executable calibration metrics.
- [Verification matrix](VERIFICATION_MATRIX.md): change classes mapped to required checks.
- [Templates](templates/README.md): change plan, architecture decision, threat-model delta, incident report, and handoff forms.
- [`skills/seam-engineer/SKILL.md`](../../skills/seam-engineer/SKILL.md): compact routing skill for engineers and agents.

## Core engineering rule

No component may be redesigned, optimized, removed, or declared defective until the engineer has:

1. identified the governing contract;
2. reproduced the current behavior or recorded a failed reproduction;
3. located canonical and derived state;
4. identified affected architectural and security invariants;
5. established a measurable baseline;
6. defined the expected improvement and permitted regressions;
7. selected tests and benchmarks capable of falsifying the claim.

## Definition of done

A material change is complete only when:

- the intended contract is identified;
- current behavior and baseline are recorded;
- the relevant failure is reproduced;
- regression coverage exists;
- focused and applicable full tests pass;
- benchmark impact is measured when behavior or performance changes;
- security impact is reviewed;
- canonical and generated state remain distinguishable;
- documentation matches implementation;
- limitations, conflicts, blockers, and unverified claims are explicit;
- history, indexes, streams, and snapshots are updated and verified when required;
- the PR contains reproducible evidence and remaining risks.

## Documentation maintenance rule

This manual should primarily contain stable models, decision procedures, and pointers. Volatile counts, benchmark scores, active priorities, and one-session implementation details belong in project status, history, benchmark artifacts, or focused audits. Avoid copying long passages from those sources into this manual.
