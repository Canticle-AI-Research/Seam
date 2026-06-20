# Architecture Decision Record Template

Copy this template into the issue, audit, branch notes, or PR body when recording an architecture decision. Remove unused prompts only after answering why they are not applicable.

```markdown
# ADR — <decision>

Status: proposed | accepted | superseded | rejected
Date: YYYY-MM-DD
Decision owners: <names or roles>

## Context
<current architecture, problem, evidence, and constraints>

## Governing contracts and invariants
- <pointer and invariant>

## Decision
<precise architectural decision>

## Alternatives considered
### <alternative>
- Benefits:
- Costs:
- Reason rejected or deferred:

## Data and control-flow impact
- Entry points:
- Canonical state:
- Derived state:
- Interfaces:
- Failure domains:

## Security impact
- Trust-boundary changes:
- New abuse cases:
- Controls:
- Residual risk:

## Compatibility and migration
- Existing data:
- Existing clients:
- Rollback:
- Versioning:

## Measurement and acceptance
- Baseline:
- Target:
- Guard metrics:
- Tests/benchmarks:

## Consequences
- Positive:
- Negative:
- Operational:
- Documentation:

## Supersession
- Supersedes:
- Superseded by:
```
