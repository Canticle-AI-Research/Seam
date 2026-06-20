# Change Plan Template

Copy this template into the issue, audit, branch notes, or PR body when planning a change. Remove unused prompts only after answering why they are not applicable.

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
