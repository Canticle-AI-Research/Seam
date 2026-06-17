# SEAM Incident Response and Recovery SOP

## Purpose

This SOP governs security, integrity, privacy, benchmark-evidence, and operational incidents affecting SEAM.

## Incident triggers

Enter this process when there is evidence or credible suspicion of:

- committed or logged credentials, private keys, DSNs, tokens, or private session URLs;
- unauthorized non-loopback exposure;
- cross-scope memory disclosure;
- canonical-state corruption, unexplained deletion, or failed rollback;
- poisoned or spoofed provenance;
- malicious retrieved content causing tool execution or state mutation;
- compromised installer, dependency, adapter, or provider path;
- malformed artifacts causing unsafe allocation or execution behavior;
- benchmark holdout leakage or tampered publication evidence;
- published claims that cannot be reproduced;
- loss of history, stream, routing, or snapshot integrity.

## Severity

| Severity | Definition | Examples |
|---|---|---|
| SEV-0 | Active compromise or broad sensitive-data exposure | Live credential abuse, remote unauthorized access, destructive canonical corruption |
| SEV-1 | Confirmed high-impact incident with contained scope | Cross-scope disclosure, committed secret, invalid published benchmark bundle |
| SEV-2 | Integrity or security control failure without confirmed exploitation | Non-atomic rollback loss in test, auth bypass found before release |
| SEV-3 | Near miss, policy violation, or low-impact defect | Secret-shaped test value in an uncommitted artifact, stale recovery instructions |

Severity may rise as evidence develops.

## Roles

- **Incident commander**: coordinates scope, decisions, and status.
- **Technical lead**: diagnoses and remediates the failure.
- **Evidence custodian**: preserves logs, hashes, commits, artifacts, and timelines.
- **Communications owner**: handles private reports, contributor notices, or claim correction.

One person may fill several roles in a small project, but the responsibilities must still be explicit.

## Phase 1 — Contain

1. Stop affected services, agents, automation, or provider calls when continued operation increases harm.
2. Revoke or rotate exposed credentials using the provider's control plane.
3. Remove unauthorized network exposure.
4. Disable the affected interface or adapter if isolation is uncertain.
5. Freeze destructive cleanup until evidence is preserved.
6. Prevent additional paid or publication runs when benchmark integrity is affected.
7. Do not copy sensitive material into issues, chat, history, snapshots, or remediation docs.

For committed secrets, treat deletion from the working tree as insufficient. Rotation is mandatory; history rewrite is a separate controlled action.

## Phase 2 — Preserve evidence

Record:

- discovery time and reporter;
- affected commit, branch, release, host, database, interface, and scope;
- exact reproduction commands;
- relevant logs with sensitive values redacted;
- hashes of affected files and artifacts;
- current database and index state;
- process and network state when relevant;
- credential rotation or service-disable timestamps;
- who performed each action.

Preserve evidence in an access-controlled location. Repository history should contain a redacted summary and pointers, not the secret or private dataset.

## Phase 3 — Scope

Determine:

- entrypoint and root cause;
- first known affected version;
- last known good version;
- records, scopes, users, fixtures, or claims affected;
- whether canonical state, derived state, or both are compromised;
- whether provenance can still be trusted;
- whether data left the machine or trusted boundary;
- whether the incident is reproducible;
- whether related paths share the same defect.

Do not assume a derived-index problem is isolated until canonical records and document status are verified.

## Phase 4 — Eradicate

Use a red-green remediation:

1. Create the smallest safe reproducer.
2. Add a regression or abuse test.
3. Correct the root cause, not only the observed symptom.
4. Remove poisoned derived state.
5. Rebuild indexes from verified canonical records.
6. Repair or restore canonical state only from verified evidence.
7. Rotate all potentially exposed credentials.
8. Update dependencies, installer paths, or provider controls when compromised.
9. Correct invalid benchmark artifacts and withdraw unsupported claims.

Do not erase historical evidence to make the incident appear cleaner.

## Phase 5 — Recover

Recovery must be staged:

1. verify canonical database integrity;
2. verify document status, provenance, and scope boundaries;
3. rebuild derived indexes;
4. run focused regression and security tests;
5. run applicable full repository gates;
6. run representative retrieval and context checks;
7. restore interfaces locally first;
8. restore external exposure only after authentication, binding, limits, and logging are verified;
9. monitor for recurrence.

A service returning `200 OK` is not proof that memory integrity is restored.

## Phase 6 — Validate evidence and claims

When benchmarks or published claims are affected:

- quarantine invalid reports and bundles;
- determine whether fixtures, holdout data, judge configuration, or hashes were exposed or altered;
- rerun from a clean commit and clean artifact directory;
- publish a correction that identifies affected claims and replacement evidence;
- do not silently overwrite prior artifacts.

## Phase 7 — Post-incident review

Complete `templates/INCIDENT_REPORT.md` with:

- timeline;
- impact;
- root cause and contributing conditions;
- detection gap;
- containment and recovery actions;
- evidence and commands;
- why existing tests or controls did not prevent or detect it;
- corrective actions with owners and status;
- architecture, security, test, manual, ledger, and continuity updates;
- residual risk.

## Recovery verification matrix

| Incident type | Required verification |
|---|---|
| Secret exposure | Rotation proof, repository scan, log/artifact scan, history-remediation decision |
| Canonical corruption | Database integrity, record counts by scoped command, provenance sampling, restore diff |
| Derived-index corruption | Canonical verification, full rebuild, deletion parity, retrieval comparison |
| Cross-scope disclosure | Negative isolation tests, affected-scope audit, index-scope verification |
| Prompt/tool injection | Reproducer, authority-boundary test, tool-side-effect audit, prompt-channel review |
| Network exposure | Bind/auth/CORS/rate/body/SSRF tests, port and process inspection |
| Benchmark leakage | Split audit, artifact quarantine, clean rerun, public-claim correction |
| Installer/supply chain | Hash/signature review, dependency audit, clean install test, credential review |
| History/stream corruption | Integrity, routing, continuity, stream verification, snapshot validation |

## Communications

Security-sensitive details must remain private until a fix and disclosure plan exist. Public summaries should state impact, affected versions, remediation, and operator action without exposing credentials, private data, or weaponized exploit detail.

## Closure criteria

An incident can close only when:

- containment is complete;
- affected credentials are rotated;
- root cause is remediated;
- regression coverage exists;
- canonical and derived state are verified;
- applicable claims are corrected;
- continuity and evidence are preserved;
- residual risks and follow-up actions are explicit.
