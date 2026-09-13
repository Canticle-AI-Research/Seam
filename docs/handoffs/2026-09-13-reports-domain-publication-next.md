---
handoff_id: 2026-09-13-reports-domain-publication-next
supersedes: 2026-09-13-m1-report-publication-benchmark-prep
handoff_status: current
history: HISTORY#653
---

# Reports publication and owned-domain continuation

## Resume here

The operator asked to fix the existing reports website, then requested this
handoff. The page already exists on the reports branch; do not replace it with
a new site or confuse it with the main Canticle website, design library or
research wiki. This pass located the exact source and checked live publication
state. It did not deploy the site or modify Pages/DNS configuration.

**Domain authorization:** the operator clarified that `canticle.ai` was only a
name entered in GitHub Pages; they did not establish ownership of that domain.
They then explicitly confirmed ownership of `canticle.cc` and authorized using
it for this page. The proposed operating hostname is **`reports.canticle.cc`**.
Use that subdomain for the report library while preserving the existing apex
website and mail. Do not repeat the ownership question or ask again for the
already-granted use of `canticle.cc`. Actual DNS account access and record
inventory remain to be verified before making changes.

The free staging/publication address remains
`https://canticle-ai-research.github.io/Seam/`. First obtain an honestly
qualified merge and verified Pages deployment there, then configure the
custom hostname with matching site paths and HTTPS. The custom domain is not
required to prove the initial static deployment works.

## Exact source and branch boundary

- Repository: `Canticle-AI-Research/Seam`.
- Existing branch: `feat/seam-reports-pages-20260912`.
- Draft PR: [#264](https://github.com/Canticle-AI-Research/Seam/pull/264).
- Inspected source head before this documentation update:
  `99d0ffa0e12982b14eaee33241151bfc052bf8e9`.
- Inspected main: `614141c5aa96fd51d4dee2e09c186bb4035c0377`, the merged
  roadmap/handoff from PR #261. The reports branch was three commits ahead
  with no main-only commits at that inspection.
- Existing worktree: `.worktrees/seam-reports-pages-20260912`; it was clean at
  the beginning of this pass. Root is appending this handoff to that existing
  branch, not creating a parallel publication branch or altering runtime code.

The PR contains more than a website: M1 audit, diagnostic helper, tests,
evidence and chronological records are part of its existing source slice.
Preserve them. The source report is pinned to commit
`e01284de37140b2d56a2c53e68d45f309f7e89e5` in the catalog; use a **merge commit**
and preserve that ancestry. Do not squash/rebase away the source or invent a
replacement revision. If main advances, merge the updated base and reconcile
chronology without rewriting the older append-only evidence.

Current source paths:

| Purpose | Path |
| --- | --- |
| Site, layouts and assets | `report-site/` |
| Jekyll URL settings | `report-site/_config.yml` |
| Admitted report and revision hashes | `report-site/catalog.json` |
| Reviewed first public edition | `report-site/editions/2026-09-13-memory-formation-m1.md` |
| Exporter | `tools/reports/prepare_site.py` |
| Public-artifact safety scanner | `tools/reports/publication_safety.py` |
| Build/deployment workflow | `.github/workflows/reports-pages.yml` |
| Operator procedure | `docs/REPORT_SITE.md` |
| Canonical first audit/evidence | `docs/audits/2026-09-13-memory-formation-m1.md` and its evidence directory |

The existing Jekyll site supplies search, report-type filters, source links,
public-edition downloads, Atom feed, manifest, About and 404 pages. It is a
static site and needs no persistent application server or database. GitHub
Actions builds the curated artifact and GitHub Pages serves it.

## Live findings and the publication blocker

At exact source head `99d0ffa0`, `gh pr checks 264` reported:

- `reports-site-build`, `repo-hygiene`, `chroma-real-smoke` and
  `locomo-quickstart-bil2`: successful.
- Package smoke and PostgreSQL integration: successful.
- `reports-site-deploy`: skipped by the intended PR-only validation boundary.
- Advisory `test-and-benchmark`: failed. The prior handoff points to inherited
  hook-test issue #260; this pass did not re-diagnose the full failure log.

This evidence applies to that inspected head. A documentation push creates a
new head; discover and qualify its actual check results before merge.

The workflow publishes only from main with an admitted nonempty catalog and
successful complete-artifact validation. The site/workflow are absent from
main. The Pages API reported workflow publishing, no custom domain, and the
free site URL above. The deployments API returned no `github-pages` deployment.
A direct HTTPS request to the free URL returned HTTP 404 with the GitHub Pages
“Site not found” title. A successful PR build is not a public deployment.

The existing release request is **TDD_UNPROVEN** for
`tools/memory_formation_m1.py`: the diagnostic helper lacks a recorded
red-before-green cycle. The publisher modules have recorded cycles. The
release protocol defines a runtime path without such evidence as unproven and
requires TDD proven or not required for a QUALIFIED receipt. See
`docs/SOP_AGENT_ORCHESTRATION.md` under TDD and receipt meaning.

Do not invent historical failing output, claim that today's green tests prove
a past red phase, or move code simply to evade path classification. Independent
release must resolve that evidence condition honestly before merging the full
PR. The earlier side conversation could not delegate. This original root session
obtained and canonically stored an independent **NOT_QUALIFIED** disposition
for exact head `99d0ffa0` and fingerprint
`7e023d93071f9c1bd32553d5cf867846783b83220681e08f6ef9b6e49a0c936d`.
The local request and receipt are under `.seam/orchestration/session-end/`
`requests/` and `receipts/`, with filenames ending `-7e023d93071f9c1b.json`.
Receipt validation and live-scope matching passed; unexecuted release checks
were explicitly NOT_RUN. This is completed rejection evidence, while remediation
and a qualified successor remain pending. These local records are not Git-tracked;
the next host must generate a fresh exact-state request for qualification.
The diagnostic helper's release condition has not been repaired.

## Domain findings and authorized configuration plan

The operator's clarification supersedes the earlier assumption that
`canticle.ai` was an owned custom domain. Read-only observations:

- `canticle.ai` and `www.canticle.ai` resolved to `2.57.91.91`; nameservers were
  `ns1.dns-parking.com` / `ns2.dns-parking.com`. HTTPS failed with a TLS alert.
  That address was outside GitHub's live published Pages IP ranges. No further
  registration, DNS editing or ownership investigation is needed for this name.
- `canticle.cc` nameservers were `dane.ns.cloudflare.com` and
  `hope.ns.cloudflare.com` when queried in this pass.
- Queries for `reports.canticle.cc` returned no A or CNAME answer. This is a
  DNS observation, not proof of access to the Cloudflare account or a complete
  inventory of its records. Inspect live records before a write.
- No credential value was viewed or copied. No DNS account authorization,
  zone-write permission or Pages custom-domain certificate was verified.

Concrete sequence for the authorized `reports.canticle.cc` target:

1. Resolve PR #264's outstanding release condition and independent assurance;
   store an exact-state qualified receipt, pass current required checks and
   merge with source ancestry intact.
2. Observe the main-only reports workflow. If needed, use its main manual
   dispatch after inspecting the workflow/ref. Verify successful deployment,
   expected report, manifest pin, public-edition download digest, feed and links
   at the free Pages URL. Keep publication inputs restricted to the reviewed
   catalog and artifacts.
3. Inspect the accessible Cloudflare account, `canticle.cc` zone and existing
   `reports` records using a usable CLI first. Credentials stay private. If DNS
   write scope is missing, finish the exact record/configuration plan and name
   that specific blocker; do not ask the operator to paste a token into chat.
4. Prepare coordinated site changes for the custom hostname: Jekyll `url` to
   `https://reports.canticle.cc`, `baseurl` to an empty string, and the workflow's
   hard-coded `/Seam/` local-link assertions to the corresponding root paths.
   Verify report links, assets, feed/manifest and edition downloads in a real
   build and through the privacy gate before deploying the changed artifact.
5. Configure the repository's Pages custom hostname and a DNS CNAME for
   `reports` targeting `canticle-ai-research.github.io` (a hostname, not a URL
   or `/Seam/` path). Verify current GitHub/Cloudflare requirements first; do
   not alter apex A/AAAA, MX, SPF, mail routing or the existing main site.
6. Verify authoritative and public DNS, GitHub domain validation/certificate
   state, HTTPS redirects and the actual served report. Enable/enforce HTTPS
   when the certificate is available. Record the exact deployment and hostname
   evidence; DNS propagation alone is not deployment proof.

This is the authorized plan, not a claim those changes have happened. No paid
hosting service, domain purchase, API benchmark call or main-site redesign was
requested or performed as part of this discovery/handoff.

## Preserved context and next action

The predecessor handoff retains the full M1 audit findings, report source and
edition hashes, local preview evidence, prior publication/redaction approvals,
benchmark prerequisites and preserved work. Use its relevant sections rather
than reconstructing that work. The detailed roadmap remains
`docs/roadmap/MEMORY_FORMATION.md`; the original R01-R14 requests, chunking,
BIL-3, Sleep/Daydream and graph/reporting direction remain intact.

Do not confuse the SEAM report site with `canticle-lilbrary` (a React/Vite
design kit) or `Canticle-Research-Wiki` (a separate Python-generated encyclopedia).
Neither is the source of this requested Jekyll page.

Preserve the dirty primary deep-audit checkout and independent audit-cleanup,
pretool-hook, sleep-learning and standalone M1 worktrees. This handoff changes
only documentation/continuity on the existing reports branch. Do not claim
main was updated merely because this successor was pushed to draft PR #264.

**Next concrete action:** resume the latest PR #264 head in the existing reports
worktree, inspect the stored rejection and resolve the diagnostic
helper's unproven test-first evidence under policy. Then qualify the merge,
verify free Pages deployment, and implement the authorized
`reports.canticle.cc` configuration with current DNS-account evidence.
