# SEAM Engineering Verification Matrix

Use this matrix after classifying a change. It provides the minimum review dimensions, not a substitute for engineering judgment or the current canonical commands in repo documentation.

Legend:

- **R**: required.
- **A**: required when applicable to the changed path.
- **—**: normally not required.

| Change class | Contract review | Focused tests | Full regression | Benchmark delta | Threat-model delta | Migration/rollback | Real adapter/service | Manual/ledger review | Continuity gates |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| Documentation typo | A | A | — | — | — | — | — | A | A |
| Durable documentation or policy | R | A | A | — | A | — | — | R | R |
| Runtime behavior | R | R | R | A | A | A | A | R | R |
| MIRL record or parser | R | R | R | R | A | R | — | R | R |
| Persistent schema or storage | R | R | R | A | R | R | A | R | R |
| Retrieval or ranking | R | R | R | R | A | — | A | R | R |
| PACK or context | R | R | R | R | A | A | — | R | R |
| Lossless/readable codec | R | R | R | R | R | R | — | R | R |
| Holographic surface | R | R | R | R | R | R | — | R | R |
| REST API | R | R | R | A | R | A | A | R | R |
| MCP tool or protocol | R | R | R | A | R | A | A | R | R |
| Dashboard/WebUI | A | R | R | A | R | — | A | A | R |
| Vector adapter | R | R | R | R | R | R | R | R | R |
| Provider/model integration | R | R | R | R | R | A | R | R | R |
| Installer or platform script | R | R | R | A | R | R | R | R | R |
| Benchmark harness | R | R | R | R | R | A | A | R | R |
| Paid evaluation path | R | R | A | R | R | — | R | R | R |
| History/stream tooling | R | R | R | — | R | R | — | R | R |
| Architecture change | R | R | R | R | R | R | A | R | R |
| Incident remediation | R | R | R | A | R | R | A | R | R |

## Verification dimensions

### Contract review

Identify the governing specification, MIRL contract, stable ledger policy, interface contract, and historical constraints. Explicitly separate current implementation from roadmap intent.

### Focused tests

Run the new or previously failing case, directly affected module tests, and relevant negative or malformed-input cases.

### Full regression

Run the current canonical full-suite scope appropriate to the branch. Record the exact command and counts; do not copy an old hard-coded total.

### Benchmark delta

Use identical baseline and after-state data, budgets, judges, seeds, and configuration. Inspect per-case regressions and guard metrics.

### Threat-model delta

Complete `templates/THREAT_MODEL_DELTA.md`. Required whenever an entrypoint, parser, persistence path, provider call, network surface, agent tool, credential path, or trust boundary changes.

### Migration and rollback

Document format compatibility, schema versioning, partial failure, transaction boundaries, restore procedure, and idempotency.

### Real adapter or service

Use the real external dependency when the change claims compatibility with it. A stub can establish local logic but not real-service behavior.

### Manual and ledger review

Update the narrowest authoritative document. Stable policy or architecture changes require ledger review; current operating-state changes require project-status review.

### Continuity gates

When repository state changes, follow `AGENTS.md`: history append, index rebuild, snapshot, integrity/routing/continuity/stream verification, and derived roadmap/cross-index regeneration when applicable.

## Security-specific negative checks

Select applicable cases:

- unauthenticated request;
- unauthorized scope;
- non-loopback bind without required controls;
- hostile CORS origin;
- oversized body or allocation;
- malformed JSON, MIRL, codec, or surface header;
- path traversal;
- shell metacharacters;
- secret-shaped exception text;
- provider URL to loopback, private, metadata, or redirect target;
- concurrent update and forced rollback failure;
- stale derived record after canonical deletion;
- stored prompt injection retrieved into context;
- tool request sourced only from retrieved text;
- holdout or fixture contamination;
- shutdown during in-flight work.

## Evidence record

For each required cell, record one of:

- command and result;
- artifact and hash;
- code/test pointer;
- documented operational control;
- `not applicable` with a technical reason;
- `not run` with the blocking reason.

Never use an empty checkbox as evidence.
