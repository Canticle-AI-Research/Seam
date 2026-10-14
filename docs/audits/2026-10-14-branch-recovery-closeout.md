# Branch audit and admitted recovery closeout — 2026-10-14

All30 original branches were inspected semantically, including84 distinct unique
commit objects. Useful missing work was mapped to12 recovery lanes/issues291–302
under master263. Two admitted recovery waves have retired15 original branches;
15 remain intentionally retained (11 source/four website). Every remaining live
tip equals the audited original tip; no additional unaudited branch remains at
this readback. Temporary delivery branches and the source worktree are finished.
No branch was removed merely because its PR was closed or old.

Source PR304 merged `ffd4e98cd28fb9054eb1669c6a2f7835538921f6`, exact tree of
independently qualified signed head `b5110c84b7a2941de4cfde3b8a7dbf3c98d5997d`.
All three required checks and package smoke pass; exact-state receipt is stored.
The source glossary/operator/wiki recovery passes73 targeted cases and all
canonical gates. The narrowly updated active urllib3 lock has independent fresh
locked-install qualification; dated requirements are unchanged. Original277/278
are closed as superseded and deleted only after main admission; exact old tips
remain reachable via their pull refs. Earlier11-retired/19-retained figures are dated snapshots,
not current counts; master263 and this final inventory govern current state.

Website PR35 merged `6b6ef1d88bd6789adee3afbe50742c2d1c52a8da`. Independent
successor review,44 focused tests and four actual released-SDK hostile/benign
mocked cases pass. All eight changed public resources match main after only
Cloudflare email-obfuscation normalization. Production Pages and email-worker
builds pass. Original14/31 branches are retired: closed pull14 predates its final
acronym correction, so exact9e31aa9051a3f612f6e59578d547235d8a0a49ad is retained
by signed tag `archive/20261014/website-current-interface-docs`;31's exact tip
survives its pull ref. Policy/pricing/auth/cohort/Vault/selector/shared assets
remain unchanged. The owned preview server is stopped. Six inherited homepage
failures are tracked in website issue36; the failed preview worker build in37
is intermittent, with successful production successor, not email-delivery proof.

Fresh public-v5 wheel/sdist qualification remains current:109 implementation
hashes, seven legal documents, all13 recorded checks and eight installed smokes
per format pass. No registry upload or paid provider call occurred. TestPyPI
access remains unavailable. Required source checks do not establish all-product
acceptance: advisory PG runner fixture startup still fails before real tests
(issue293); managed47-case real PG evidence remains separate. Security updater
scope/access290/262 and pinned owner About reminder287 remain explicit.

Remaining branches are preserved for useful batching, safe bootstrap/gates,
native-model planning, report exports, formation/benchmark qualification, skills,
comparator qualification and locked website design/data/feed proposals. The
[plan](../roadmap/BRANCH_RECOVERY.md) names dependencies and acceptance conditions;
this closeout completes the audit and admitted slices, not those future features.

## Evidence manifest

- `docs/audits/evidence/2026-10-14-branch-recovery-closeout/final-branch-inventory.json` — SHA-256: `dc919a477dae499763360a381e985e36a3c7895964271160ea462030715a2b02`
- `docs/audits/evidence/2026-10-14-branch-recovery-closeout/docs-retirement-results.json` — SHA-256: `a35bb087d01646b10bf57757c662012e00997d52d123836c984c590a102626aa`
- `docs/audits/evidence/2026-10-14-branch-recovery-closeout/source-docs-worktree-preservation.json` — SHA-256: `5e8e2b69f717ff1ab4f91ced898379ba6f028d45452bc86897373a0c5ca23308`
- `docs/audits/evidence/2026-10-14-branch-recovery-closeout/factual-docs-closeout-receipt.json` — SHA-256: `c34d477afb760f93251cf53c3a3edd1f7cd38ff8caeb659d22a3f8c58547b9af`
- `docs/audits/evidence/2026-10-14-branch-recovery-closeout/source304-checks.json` — SHA-256: `f2af3cc4c9e8fe22d41647790a9e97236cee5f1b7a1bff0611da85f02cc80701`
- `docs/audits/evidence/2026-10-14-branch-recovery-closeout/website-docs-repair-delivery.json` — SHA-256: `60d8929d5ca9506e42adef04cfe11ad09990d972548be45ec84f5a8f6ec25247`
- `docs/audits/evidence/2026-10-14-branch-recovery-closeout/website-docs-assurance-successor.json` — SHA-256: `77f95f2a57fb8e49cdb4d5530fa0612c72cd8c04d418c4d370beac1b9b07d03e`
- `docs/audits/evidence/2026-10-14-branch-recovery-closeout/website-docs-production.json` — SHA-256: `dc94047dafa29eaacf78c1dc9e4561ce5eebcaab25f0cf732be3aa5dac65ddf4`
