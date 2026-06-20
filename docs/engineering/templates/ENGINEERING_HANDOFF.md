# Engineering Handoff Template

Copy this template into the issue, audit, branch notes, or PR body when handing off engineering work. Remove unused prompts only after answering why they are not applicable.

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
