# Threat-Model Delta Template

Copy this template into the issue, audit, branch notes, or PR body for every security-sensitive change. Remove unused prompts only after answering why they are not applicable.

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
