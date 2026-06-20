# Incident Report Template

Copy this template into the incident issue, audit, or post-incident record. Remove unused prompts only after answering why they are not applicable.

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
