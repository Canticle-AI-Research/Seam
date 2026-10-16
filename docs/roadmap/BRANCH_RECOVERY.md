# Branch recovery integration plan

Status: active; audit complete, integration and retirement incomplete.

October 16 reconciliation: all eight remaining original source/site PRs are
closed without merging unsafe or deferred candidates. Exact branch/pull refs,
recovery issues and the private website preservation tag are recorded in
[the disposition receipt](../audits/evidence/2026-10-16-pr-closeout/original-pr-dispositions.json).
R1 preservation is complete in issue291; locked future website proposals remain
planned in issue302. The dated workstream order below describes recovery
dependencies, not current operator priority. Finish the finite current-built
docs/licensing review first, then conditional independent Doctor work; formation
and broader recoveries remain held for explicit resumption. Licensing PR286 and
TestPyPI publication were subsequently verified in HISTORY#680; the older access
blocker below is historical. No new publication is authorized by this plan.

The owner requires every branch to be inspected for missing useful work before deletion. This plan covers all 30 remaining branches at the captured exact tips, including 84 distinct unique commit objects. A closed PR or unique commit count is not a disposition. Detailed per-file, symbol and intermediate-commit evidence is retained in the [audit](../audits/2026-10-14-branch-recovery.md).

Use current main as the integration base. Rebuild useful slices with witnessed tests; never merge stale chronology, obsolete licensing or rejected UI wholesale. Keep unresolved branch tips until useful work is admitted or durably preserved with a tracked completion condition.

The default Suite release candidate must be rebuilt after runtime recovery. TestPyPI access remains an external blocker; previous package evidence does not qualify newly changed runtime bytes. Production registry publication and paid benchmark calls are outside this work.

## Ordered workstreams

### R1: Website publication safety and operator facts

Retire the legacy mirror/clobber/private-source publisher; correct Suite availability and naming; then qualify operator and client examples against current public interfaces. Preserve locked proposals verbatim.

Acceptance and dependencies: Safety slice is merged/live via PR34. Operator/client-doc recovery requires independent successor review and production verification.

Tracking: [R1 issue #291](https://github.com/Canticle-AI-Research/Seam/issues/291).

### R2: Cache reuse and bounded embedding batching

Admit the witnessed no-op cache fix without weakening byte fingerprints. Then recover optional batch capability, bounded record batches and locked node batches with transaction, replay, order, near-tie and failure parity tests.

Acceptance and dependencies: P1 cache before batching; old GPU/performance claims remain unqualified.

Tracking: [R2 issue #292](https://github.com/Canticle-AI-Research/Seam/issues/292).

### R3: Owned PostgreSQL fixture and safe bootstrap

Replace automatic CI services with an explicitly probed local daemon and uniquely owned disposable fixture; coordinate 0.8.7/PG18 parent tmpfs and all six strict real-service tests. Rebuild Windows conveniences around current nondestructive bootstrap.

Acceptance and dependencies: Actual image, extension, adapter tests and cleanup must pass; no operator volume/container removal.

Tracking: [R3 issue #293](https://github.com/Canticle-AI-Research/Seam/issues/293).

### R4: Fail-closed workspace gate parity

Rebuild check-only workspace checks: propagate Git failures, select the right repository, include detached worktrees, and prohibit deletion of unknown ignored data.

Acceptance and dependencies: Meaningful public CLI RED/GREEN and canonical gate parity; no historical --fix implementation.

Tracking: [R4 issue #294](https://github.com/Canticle-AI-Research/Seam/issues/294).

### R5: Factual documentation and wiki navigation

Recover factual glossary/operator corrections with a terminology checker that accepts prose after correct expansion; then recover wiki/navigation increment. Preserve current licensing/install semantics.

Acceptance and dependencies: Documentation corrections before navigation; witnessed checker RED/GREEN.

Tracking: [R5 issue #295](https://github.com/Canticle-AI-Research/Seam/issues/295).

### R6: Native-model planning and safe audit exports

Preserve authored native-model/ESP32/Tab A7/dataset plans verbatim with planned-status routing; rebuild training_eligible=false quarantine and roadmap lifecycle tools; adapt company/model IP-readiness checklist to settled terms.

Acceptance and dependencies: No automatic model training or revival of obsolete Shield/ownership assertions.

Tracking: [R6 issue #296](https://github.com/Canticle-AI-Research/Seam/issues/296).

### R7: Offline report export and hardened probes

Recover revision/hash-pinned catalog and sanitized public editions with fail-closed privacy/allowlist checks. Combine optimized-mode explicit M1 assertions from PR264 with safer missing-record handling from PR269.

Acceptance and dependencies: Offline build first; automatic publication activation is a separate reviewed step.

Tracking: [R7 issue #297](https://github.com/Canticle-AI-Research/Seam/issues/297).

### R8: Opt-in formation and benchmark qualification

Recover context-segments/1 with exact Unicode anchors, conservative speaker handling, content-free diagnostics and configuration-bound replay identity. Reconcile E1/BIL3 protocol; finish ordered seeding, aggregate and identity validation before exposing checkpoint resume.

Acceptance and dependencies: Defaults/lifecycle preserved; no paid campaign. Two independent judges must differ from answerer under current protocol.

Tracking: [R8 issue #298](https://github.com/Canticle-AI-Research/Seam/issues/298).

### R9: Portable skills and Codex adapter

Recover registry/planner/atomic private window/escaped graph/CLI, then Codex inventory. Bind policy/rankings and frame digests/counts to source; fix nameless-file stable identity, bounded JSONL, directory ownership/mode and activation-policy replay.

Acceptance and dependencies: Core before adapter; witnessed security/correctness tests and exact Suite membership review.

Tracking: [R9 issue #299](https://github.com/Canticle-AI-Research/Seam/issues/299).

### R10: Dated persistence research preservation

Preserve authored CacheBridge, PCS/C2C/DLCM and comparative architecture plans verbatim, with current-contract crosslinks and explicit planned/unqualified status. Freeze LC0/PCS0 measurement before experimental implementation.

Acceptance and dependencies: RAW/MIRL durable, graph/PACK/LATENT derived; old numeric claims are not current qualification.

Tracking: [R10 issue #300](https://github.com/Canticle-AI-Research/Seam/issues/300).

### R11: Comparator dependency qualification

Freeze actual Mem0 comparator version/protocol and qualify adapter/stub behavior before considering beta dependency migration. Track active urllib3 separately in issue290.

Acceptance and dependencies: No blind dependency bump or falsification of dated evidence.

Tracking: [R11 issue #301](https://github.com/Canticle-AI-Research/Seam/issues/301).

### R12: Website design/data and feed migration backlog

Preserve authored style brief and benchmark Table/Trends ideas; rebuild truthful data/units before publication. Feed channel expansion needs product scope; banner SQL needs actual migration owner/schema/RLS/grants qualification. Existing mobile notification fix is already preserved.

Acceptance and dependencies: No automatic production SQL, entitlement changes or full redesign.

Tracking: [R12 issue #302](https://github.com/Canticle-AI-Research/Seam/issues/302).

## Retirement rule

Before each deletion: verify exact remote tip, current main preservation evidence, linked issue acceptance, PR state and worktree ownership. Preserve historical objects for branches without surviving pull refs. Rejecting unsafe implementation does not reject useful intent. Branches with unresolved useful work remain explicitly tracked.

## Current delivery state

- Audit complete:30original tips/84distinct unique commit objects inspected. Fifteen original branches retired;15remain (11source/fourwebsite), exact unchanged audited tips. No unresolved useful work discarded. Final inventory is in [closeout evidence](../audits/2026-10-14-branch-recovery-closeout.md).
- R1 safety/operator facts: website PR34/35 live; latest8changed resources match main and production Pages/worker builds pass. Original14/31 branches retired with exact pull/tag preservation. Locked proposals in PR29 remain to preserve verbatim. Site baseline six homepage tests tracked website36; intermittent preview worker build37 has successful production successor.
- R2 P1cache: source PR303 merged no-op invalidation fix, independently qualified. Original213 retired; optional bounded batching in230 remains next runtime recovery, with transaction/order/replay/failure parity required.
- R3 owned fixture/image: merged303;47managed real tests/19fixture cases pass. Original image/volume branches retired. Shared-runner startup still fails before real tests (293); safe Windows conveniences remain open.
- R5 facts/glossary/wiki: complete in PR304, mergedffd4e98;73targeted cases, independent successor and stored exact-state review pass, all3required checks/package smoke pass. Original277/278 retired only after main admission. Old draft preserved inactive exact-byte; source worktree finished safely.
- R10 preservation: four exact-byte authored plans/reports admitted303; originating branches retired. Future LC0/PCS0 measurement/implementation remains planned, not demonstrated.
- Active lock: urllib3-only2.7→2.8 admitted304, fresh locked installation/eight smokes and independent review pass. Historical evidence unchanged; security-updater scope remains290/262.
- Other useful slices remain unintegrated and branches intentionally retained until their named acceptance conditions hold. Public-v5 qualification passes; TestPyPI access remains external. Broad suites are not wholly green.

The current handoff is [indexed here](../handoffs/INDEX.md); live issue updates under [master263](https://github.com/Canticle-AI-Research/Seam/issues/263) supplement the durable exact-tip reports.
