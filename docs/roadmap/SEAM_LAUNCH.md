# SEAM launch plan

[Back to SEAM roadmaps](README.md)

**Direction:** documentation baseline, packaging migration preparation,
Product Core completion, Suite, hosted API/WebUI, then benchmark score work.
**Decision record:** HISTORY#634.
**Product definitions:** [SEAM products](../PRODUCTS.md).
**Current implementation state:** [project status](../../PROJECT_STATUS.md)
and the [current handoff](../handoffs/INDEX.md).

This is a bounded launch backlog. Acceptance conditions describe future work;
they are not test results. The root roadmap marker `roadmap:track:Launch`
owns overall status. Record completed slices through the normal history,
handoff, status, and derived-stream workflow.

## Delivery order and acceptance

| ID | Slice | Prerequisite | Complete when |
| --- | --- | --- | --- |
| L0 | Documentation baseline | Current-main and worktree reconciliation | Product definitions, current state, preserved work, distribution constraints, and this ordered plan agree; documentation and continuity gates pass |
| L1 | Packaging and SDK migration preparation | L0 | The packaging checklist has a concrete manifest, ownership/source map, compatibility plan, destination checks, and reviewed artifact candidates; unresolved release blockers remain explicit |
| L2 | Product Core and graph completion | L0; distribution decisions from L1 where relevant | R2 and the S8 freeze conditions pass; knowledge/reasoning workflows prove evidence, lifecycle, temporal, recovery, and retrieval behavior through supported interfaces |
| L3 | SEAM Suite operator experience | Stable L2 contracts; L1 distribution boundary | TUI workflows and the browser dashboard operate real data; all four sections load independently; approved renders and installation/upgrade evidence exist |
| L4 | SEAM API, SDK compatibility, and WebUI | Stable L2 contracts; shared L3 components where applicable | Customer isolation, authentication, supported SDK behavior, usage controls, real operator actions, and deployment recovery are qualified on the intended service topology |
| L5 | Benchmark qualification and score improvement | Product completion through L4; frozen eligible S8 baseline | S9 evidence identifies the exact benchmark/metric and conditions; the requested 90% target is measured on the agreed protocol, with failures and uncertainty retained |
| L6 | Launch qualification and publication | L1-L5 evidence for the offered product | S10 reproducibility and applicable deployment gates pass; release notes, support/upgrade instructions, artifacts, and public claims match the qualified candidate; operator authorizes publication |

L1 prepares package migration; it does not authorize an early public release.
R2 and the S8 gates now have a locally qualified freeze candidate (HISTORY#640). Interface specifications and
design reviews can proceed while core work is underway, but they cannot waive
core correctness. Existing regression, security, conformance, and CI smoke
checks continue throughout. Expensive score optimization follows product
completion; benchmark default changes remain subject to S9 Promotion.

The 90% target still needs an agreed benchmark family, metric, evaluation
split, model/judge, context budget, and execution budget. Record those before
any score campaign. Do not substitute retrieval recall, answer accuracy, or a
different benchmark for one another, and do not promise the result in advance.

## Current checkpoint and next product work

The [L1 candidate packet](../audits/2026-09-06-l1-packaging-migration.md)
contains source/ownership mapping, exact artifact inventories, installed
compatibility evidence, and explicit release blockers (HISTORY#635). It records
the operator clarification that SDK access is private and paid.

Follow [the packaging checklist](../status/packaging-licensing.md#next-packaging-task).
Its output is a reviewable artifact/source map and migration proposal. Verify
legacy package ownership, repository locations, and release access using the
CLI before changing coordinates. Preserve existing users' install and upgrade
paths. No rename alone proves distribution eligibility.

R2 and the S8 completion conditions now have local evidence in
[the gate matrix](../../tests/docs/s8-completion.md). Verify the protected
freeze through the current handoff before advancing L3 operator acceptance.
The next bounded product pass should select one real Suite/API/WebUI workflow,
inspect its current implementation, and record public-seam acceptance before
editing. L1 delivery blockers remain explicit; expensive benchmark score work
still follows product completion. [Track S](TRACK_S_S8_S10_PRODUCTION_CORE.md)
continues to own core qualification and Promotion.

## Operator workflow acceptance

| Workflow | Required evidence |
| --- | --- |
| Ingest and inspect | A real input produces canonical memory and inspectable source anchors; rejected/failed operations report their actual outcome |
| Retrieve and explain | UI, SDK, and API use the supported retrieval policy and return consistent scoped results with recoverable evidence |
| Correct and delete | Current reads respect lifecycle exclusion; retained history is explicit; a restart does not resurrect excluded content |
| Review reasoning | An operator can inspect recorded decisions, verification, disagreement, and final outcomes without inventing hidden model reasoning |
| Explore graphs | Diamond constellation overview and separate knowledge/reasoning sections support selection, filters, navigation to evidence, and useful empty/error states |
| Operate Suite | TUI supports scope, recall, review/curation, health, and settings; browser graph dashboard can open independently |
| Operate API | Customer-authorized WebUI actions receive real backend acknowledgements; credentials and tenant boundaries satisfy the service contract |
| Inspect benchmarks | Saved run configuration, case outcomes, traces, comparisons, and unrun states are available before score optimization begins |

The current TUI plan remains at [TUI Operator Surface](TUI_OPERATOR_SURFACE.md).
Extend it through bounded slices rather than creating a second list of the
same controls. The current WebUI prototype is implementation input; simulated
success and unsafe credential persistence must be resolved before acceptance.

## Keep the products synchronized

Use the existing repository workflow with this change-impact checklist:

| Change trigger | Required companion work |
| --- | --- |
| Product name, artifact name, or distribution boundary | Update product map, package manifest/metadata, install/upgrade docs, release destination, and compatibility matrix together |
| Runtime/API contract | Update affected SDK contracts, examples, and surface adapters; run interface and isolation checks |
| UI interaction | Verify backend acknowledgement and failure states; review real desktop/mobile renders and accessibility |
| Dependencies or package extras | Verify dependency bounds, installed combinations, and lock consistency in the intended environments |
| Completed milestone or changed priority | Append history, update the current handoff/status and roadmap marker, rebuild derived streams, and run continuity gates |
| Release candidate | Verify clean installation and upgrade, artifact contents and hashes, applicable qualification, and exact-head CI before publication |

Keep a compatibility matrix with runtime/API contract version, HTTP client,
local SDK, Suite, and WebUI version. Release owners update it as part of the
same reviewed slice that changes compatibility. A future machine-readable
product manifest can drive checks; this documentation change does not claim
that automation exists.

## Hook and workflow follow-up

The canonical Git hooks and required CI already enforce continuity, wiki,
audit-claim, and publication checks. Retain them while assessing targeted
improvements:

| Follow-up | Evidence required before adoption |
| --- | --- |
| Finish existing Codex hook candidate | Review its staged and unstaged differences, adversarial command coverage, active-worktree resolution, and fresh client trust/discovery; code presence is not activation |
| Enforce lock consistency in CI | Prove `uv lock --check` at the intended gate and preserve the intentional optional-extra conflict |
| Product and package consistency check | Fail on a mismatched artifact name, destination, documentation coordinate, or compatibility row using a reviewed manifest |
| API/SDK drift check | Exercise supported client requests against the intended runtime/API versions |
| Surface truthfulness smoke | Demonstrate successful, denied, unavailable, and failed actions through the real API boundary |

Use fast feedback in local hooks and the authoritative checks in required CI.
Avoid adding paid runs to commit hooks. Audit retired-path references and
duplicated rules by their actual owners; shared repository safety remains in
`AGENTS.md`, with model-specific orchestration in its own configuration.

## Scope discipline

Each delivery slice has one owner, explicit changed paths, acceptance
conditions, verification, exclusions, and a current handoff. New features enter
the backlog with a dependency and priority; they do not silently enlarge the
active slice. Existing hook work and unrelated dirty audit records remain
separate until deliberately reconciled.
