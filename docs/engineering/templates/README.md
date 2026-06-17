# SEAM Engineering Templates

Copy the relevant template into the issue, audit, branch notes, or PR body. Remove unused prompts only after answering why they are not applicable.

## Change plan

```markdown
# Change Plan — <title>

## Request
<desired outcome>

## Change classes
- <class>

## Governing contracts
- `<path>#<section>` — <requirement>

## Current-state trace
`<entrypoint>` → `<validation>` → `<runtime>` → `<state>` → `<output/side effect>`

## Canonical and derived state
- Canonical:
- Derived:
- Generated/local-only:

## Affected invariants
- <invariant>

## Hypothesis
Given: <baseline and environment>
Changing: <mechanism>
Should improve: <metrics or failure behavior>
Without degrading: <guard metrics and invariants>
Verified by: <tests, commands, benchmarks, hashes>

## Baseline
- Commit:
- Commands:
- Results:
- Configuration:
- Artifacts/hashes:
- Known variance:

## Planned files
- `<path>` — <reason>

## Security and failure analysis
- New attacker-controlled inputs:
- Partial failures:
- Rollback:
- Scope/isolation effects:
- Resource bounds:
- Secret handling:

## Verification plan
- Focused:
- Full regression:
- Benchmark:
- Real adapter/service:
- Continuity:

## Exclusions
- <explicitly out of scope>
```

## Architecture decision

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

## Threat-model delta

```markdown
# Threat-Model Delta — <change>

## Changed entrypoints and boundaries
- <boundary>

## Assets newly read, written, transmitted, or exposed
- <asset>

## Attacker-controlled fields
- <field, origin, validation>

## Abuse cases
1. <abuse case>

## Partial-failure cases
1. <failure and resulting state>

## Controls
| Threat | Preventive | Detective | Recovery | Verification |
|---|---|---|---|---|
| <threat> | <control> | <control> | <procedure> | <test> |

## Prompt, memory, and agent authority
- Can retrieved text cause action?
- Can tool output enter a privileged instruction channel?
- Which side effects require operator confirmation?

## Secrets and privacy
- Credential source:
- Logging behavior:
- Artifact/history behavior:
- Scope isolation:

## Resource bounds
- Input/body:
- Context/candidates:
- Memory/disk:
- Timeouts/retries:
- External calls/cost:

## Residual risk and assumptions
- <risk>
```

## Engineering handoff

```markdown
# Engineering Handoff — <title>

## Scope and classification
- <scope>

## Governing contracts and affected invariants
- <pointer>

## Diagnosis
- Observed behavior:
- Root cause evidence:
- Reproduction:

## Hypothesis and baseline
- Hypothesis:
- Baseline commit/config:
- Baseline result:

## Implementation
- `<path>` — <change and reason>

## Verification performed
| Command | Result | Scope/limitations |
|---|---|---|
| `<command>` | pass/fail/not run | <details> |

## Benchmark evidence
- Baseline:
- After:
- Delta:
- Artifacts/hashes:
- Variance:
- Limitations:

## Security delta
- Trust boundaries:
- Negative tests:
- Residual risks:

## Documentation and continuity
- Docs updated:
- History entry:
- Index/snapshot/streams:
- Secret/session scan:

## Known failures and exclusions
- <item>

## First next command
`<exact reproduction or continuation command>`
```

## Incident report

```markdown
# Incident Report — <title>

Severity: SEV-0 | SEV-1 | SEV-2 | SEV-3
Status: investigating | contained | recovering | closed
Discovered: YYYY-MM-DD HH:MM TZ

## Executive summary
<what happened, impact, current status>

## Affected scope
- Versions/commits:
- Hosts/interfaces:
- Records/users/scopes:
- Credentials/providers:
- Benchmark claims/artifacts:

## Timeline
| Time | Event/action | Actor | Evidence |
|---|---|---|---|

## Root cause
<technical cause and contributing conditions>

## Impact
- Confidentiality:
- Integrity:
- Availability:
- Financial/evaluation:

## Containment
- <action and timestamp>

## Eradication and recovery
- <fix, rebuild, rotation, restore, verification>

## Evidence
- Commands:
- Hashes:
- Logs/artifacts:
- Last known good state:

## Detection and control gaps
- <why existing controls did not prevent or detect it>

## Corrective actions
| Action | Owner | Status | Verification |
|---|---|---|---|

## Claim or disclosure correction
- <affected public or internal claims and correction>

## Residual risk
- <risk>

## Continuity updates
- History:
- Ledger/status/manual:
- Snapshot/index/streams:
```
