# Branch retirement and active lock qualification — 2026-10-14

Source recovery PR #303 merged at `efa7962efbcdcd394ee9e4d1dae4a7ac7a390cdd`,
with the exact tree of independently qualified final head
`18acce51ae4aff9420d44b31e1cc6c33aa263f5d`. All three required checks, package
CI, code analysis and registry planning passed. The advisory shared-runner PG
job failed at fixture startup before its actual tests; issue #293 retains that
unresolved integration condition. Managed-daemon qualification remains 47 real
cases with zero skips; it does not prove remote runner availability.

## Verified retirement

Eleven of the original 30 audited branches are absent: ten exact-lease deletions
and one image branch automatically removed after main admission. Every useful
slice is admitted or explicitly superseded, and every old tip remains reachable
through an exact pull ref or verified signed archive tag. No unresolved useful
branch was deleted. The temporary merged source/site recovery branches were
also cleaned; these are separate from the original 30-branch count.

| Repository / branch | Preserved exact tip | Preservation ref | Disposition |
| --- | --- | --- | --- |
| Seam / `blackhatshiftey-performance-improvements` | `4d2609e59ffca85eb2c4c6c4e995e62f545744ec` | `refs/pull/213/head` | Only missing useful slice was no-op invalidation, now rebuilt/qualified in PR303. Actual-vector fingerprints retained; weaker branch fingerprint rejected. |
| Seam / `dependabot/docker_compose/pgvector/pgvector-0.8.7-pg18-trixie` | `11ed444c32ee7663391748569fa59ee2f40f3f34` | `refs/pull/282/head` | Exact image bump admitted by PR303 with local47-case real qualification; remote runner startup remains explicitly tracked in293. |
| Seam / `dependabot/npm_and_yarn/archive/webui-vite-source/npm_and_yarn-501f592bae` | `34869048c0413bb57dad57aa51827a8dbf3645d3` | `refs/pull/280/head` | Only retired Vite lock input changes; current frontend is standalone and active Dependabot excludes npm. Superseded historical update archived through pull280; dependency triage remains262. |
| Seam / `docs/seam-product-license-boundary-20260829` | `0c0b77446f17e832961375d466ead2b9add9d4de` | `refs/pull/236/head` | Obsolete Shield/frontend licensing proposal explicitly superseded by settled first-launch Suite terms; current PRODUCTS preserves useful boundaries. Original closed PR236 retained. |
| Seam / `feat/latent-cachebridge-roadmap-20260917` | `24e1725134d476798992cc7ecaef7de299d27cc6` | `refs/pull/267/head` | Authored plan restored byte-for-byte in PR303 with planned-status routing; root stale chronology not imported. No implementation/performance qualification claimed. |
| Seam / `fix/pgvector-ci-volume-leak` | `23c999e6041917e54040a79dd55ab0c6270214a8` | `refs/tags/archive/20261014/fix-pgvector-ci-volume-leak` | PG18 parent tmpfs and owned lifecycle admitted/verified in PR303; original seven-path history preserved by signed archive tag. |
| Seam / `handoff/archive` | `6469d717c2a33c3976b67ccfedefa6b930a73e81` | `refs/tags/archive/20261014/handoff-archive` | Branding bytes and retrieval tests already preserved in main; no missing active implementation. Historical handoff/provenance retained by signed tag. |
| Seam / `refactor/unify-retrieval-paths` | `d769f2ce8e9e95a97e9073c0e4bad6e9bca6dc5b` | `refs/tags/archive/20261014/refactor-unify-retrieval-paths` | Exhaustive semantic audit found current equivalents/improvements for useful retrieval/provenance/fusion/trace work. Rejected stale behavior and incidental artifacts retained by signed tag. |
| Seam / `research/advanced-persistence-landscape` | `d69994491fef91abd4220016d64e322b0d106c11` | `refs/pull/221/head` | Both authored historical reports restored byte-for-byte in PR303; comparisons/experimental claims remain dated and unqualified. |
| Seam / `research/pcs-c2c-dlcm-roadmap` | `ab1bcd348d1a07e3546b77dfe67a5c923253cce7` | `refs/pull/268/head` | Authored plan restored byte-for-byte in PR303 with current-contract routing; future experiments remain planned. |
| Cantlicle / `fix/notify-bell-mobile-host` | `d74e03f219b36a9bbca739c18dc75e69e8d127f9` | `refs/pull/17/head` | Mobile notification helper fix already preserved by current main per full website semantic audit; original closed pull17 retains history. |

## Remaining original work

Nineteen unchanged audited tips remain: 13 source and six website branches.
Their exact current tips are in the frozen remaining-branches evidence and their
per-path recovery/acceptance conditions remain in the [plan](../roadmap/BRANCH_RECOVERY.md).
New delivery branches/worktrees for R5 source docs and R1 website facts are active
and are not part of that original-tip count. They must be finished and removed.

## Active lock qualification

Only the urllib3 record changes from 2.7.0 to 2.8.0; the other 158 package
records, root lock metadata and pyproject are unchanged. A fresh noneditable
locked install passes all eight supported Suite smoke cases, lock consistency
and dependency compatibility checks. Independent review passes. Exact command
vectors and successful exits are recorded; original per-command timestamps were
not captured and are not reconstructed. Runtime/legal/archive inputs stay
unchanged; the public-v4 wheel/sdist qualification remains applicable.

Historical audit requirements and their hashes are untouched. Current Dependabot
version configuration covers only docker-compose; the historical-evidence PR
was a security-update path, not a weekly pip version rule. This patch does not
pretend a broad package ignore or version-only exclusion fixes that separate
security-updater scope. Issues #290/#262 retain that follow-up and limited
integration access. No registry upload, paid provider call or operator database
change occurred. TestPyPI access and owner About reminder #287 remain open.

## Evidence manifest

- `docs/audits/evidence/2026-10-14-branch-recovery/retirement-results.json` — SHA-256: `957e37e45e93ffb78c104f9ea3b0add0e4e77d3fad9710d84b9a6c487a9639a4`
- `docs/audits/evidence/2026-10-14-branch-recovery/remaining-branches.json` — SHA-256: `5cc5b5c49c9a243d4505b04f88e88da4269aae77b9a78bfd7bce8e829379debd`
- `docs/audits/evidence/2026-10-14-branch-recovery/lock-qualification.json` — SHA-256: `224368561104e9cb15cf66ef7a76ec0ccc8881b227f1f56375b81c87619ac528`
- `docs/audits/evidence/2026-10-14-branch-recovery/lock-assurance.json` — SHA-256: `4d79824bb59a6a22af6d13172c75f784d83744986656b5c623a6f0bfa3c5f3ee`
- `docs/audits/evidence/2026-10-14-branch-recovery/source303-checks.json` — SHA-256: `c5ba660e547e40d94ae572c5dd5e7e3e379ec608c38eebe1e7272ef3abed7711`
