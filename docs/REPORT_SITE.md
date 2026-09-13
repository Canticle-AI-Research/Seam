# Public SEAM report site

[Back to reports and evidence](REPORTS_AND_EVIDENCE.md)

The report site is intended to present new SEAM research and test records with
Canticle branding. Git remains the source of truth. The public HTML is a
reading view of explicitly selected public editions tied to revision-pinned
sources, not another place to edit results. See HISTORY#646 for setup and
HISTORY#647 for the stricter publication boundary. HISTORY#648 supersedes
the initial catalog and deployment-next instructions with a fresh empty
preview. The operator lifted that publication hold on September 13;
HISTORY#649 records the first M1 public edition and guarded deployment
candidate. The fresh-start boundary remains.

## Publication boundary

- Authorized destination: `https://canticle-ai-research.github.io/Seam/`.
- Site source: [`report-site/`](../report-site/README.md).
- Publication selection: [`report-site/catalog.json`](../report-site/catalog.json).
- Main-only publication after validation: [the workflow](../.github/workflows/reports-pages.yml).
- Canonical reports remain in `docs/audits/` or `tests/docs/`; the existing
  [report storage rules](REPORTS_AND_EVIDENCE.md) still govern those sources.
- Raw runs, local databases, credentials and internal session records are
  outside the publication input. Source checks are a backstop; a reviewer
  must still assess whether the selected content is suitable for public use.

The first catalog entry pins the M1 source at
`e01284de37140b2d56a2c53e68d45f309f7e89e5`, with independent source and public-edition
digests (HISTORY#651). New reports cover work beginning with
the operator's September 12 fresh-start request; do not backfill earlier audit
or testing records. The two initial historical public editions were removed
from this site candidate. Their canonical repository sources remain intact.
The first new source is the [M1 formation audit](audits/2026-09-13-memory-formation-m1.md).
Its [public edition](../report-site/editions/2026-09-13-memory-formation-m1.md)
is written and privacy-checked. This is a synthetic diagnostic investigation,
not a benchmark-score improvement or evidence that the gaps are fixed.

Publication is authorized but not live. On September 13 the local preview
returned HTTP 200, the public Pages URL returned HTTP 404, and the GitHub API
listed no Pages deployments. After explicit operator approval, exactly one
private session URL was redacted from the unrelated primary checkout's
`error.log`, preserving all surrounding content. Its follow-up secret scan
found no remaining findings (HISTORY#650). The earlier staging blocker is
resolved; do not ask for that same authorization again or copy the removed
value into any record.

Independent assurance and protected-merge qualification remain open. No
delegated review may run in this side conversation. The source commit and
complete source/edition hashes are now recorded in the catalog; publication
still awaits review and protected merge.
The work is pushed in draft PR #264. The closeout assessment also reports
`TDD_UNPROVEN` for the diagnostic helper `tools/memory_formation_m1.py`, which
has no recorded red-before-green cycle. The publisher modules are covered.
This concrete condition must be resolved under the release protocol; a green
test run is not historical TDD evidence. See HISTORY#652 and the indexed handoff.
The source audit is recorded here by HISTORY#649; its separate audit branch
has a local HISTORY#646. Preserve both append-only histories; the publication
branch's existing #646-648 are the report-site preparation chain.

## Report publication process

1. File and review the source under its canonical evidence policy, then commit
   it through the protected PR workflow.
2. Add a catalog entry in a new publication PR. Supply an ISO date, unique
   date-slug ID, title, `research` / `benchmark` / `test` kind, summary, context,
   repository source path, complete commit SHA and SHA-256 of the exact Git
   blob. `git show COMMIT:PATH | sha256sum` computes that digest. Also provide
   a reviewed public edition at `report-site/editions/<id>.md`, its path and
   its own SHA-256. Omit runtime configuration, environment references,
   local artifact paths, credentials and session links from that edition.
3. Keep previously published entries pinned. Publish substantive corrections
   as a new dated ID with a context note linking the prior report. Do not
   silently replace historical evidence. Urgent removal of sensitive material
   follows the repository's security process.
4. Run the exporter and focused checks described in the site README. Review
   the built HTML, source download and context note in a local preview.
5. Complete the repository's independent assurance and release qualification,
   then merge through the protected PR path. The authorized workflow uploads
   and deploys only on main, after all build/privacy checks pass and at least
   one report has been admitted. An empty catalog or pull request cannot
   publish. Keep the source-commit and catalog-admission changes in dependency
   order; never substitute an uncommitted or invented revision pin.

The exporter verifies the pinned original even if the working file has changed.
Only the reviewed public edition is copied into the website and downloadable
Markdown. The manifest carries separate original-source and public-edition
digests; the download is never described as the original. A missing commit,
hash mismatch, duplicate ID, unsafe input or existing destination fails export.

## Confidential-content gate

Publication uses an explicit list of template and asset files. Arbitrary files
inside the asset/template directories are rejected; unselected repository
files are never copied. Each public edition, metadata record, template, asset
and branding SVG is scanned before the export writes its output.

After Jekyll, `python -m tools.reports.publication_safety --site DIRECTORY`
scans every output file, including HTML, JavaScript, CSS, SVG, feed, manifest
and Markdown downloads. It blocks recognized credential formats, generic
credential assignments, environment references, private paths, session links,
credential-bearing URLs and common encoded forms. Unexpected files, symlinks,
binary content and oversized files fail closed; no files are silently excluded.
Any future preview or Pages upload must depend on this gate succeeding.

The publisher does not read local environment files or interpolate process
environment values into report content. This initial text-only publication
contract excludes PDFs, image binaries, archives, logs and database files.
Adding such formats requires an explicit review and inspection mechanism.
Pattern detection remains a backstop to reviewing the public edition; it is
not a proof that every possible unknown secret can be recognized automatically.
Rejected content and values are never echoed in scanner diagnostics.

## GitHub Pages and Canticle integration

In repository **Settings → Pages**, the publishing source must be **GitHub
Actions**. Setup on 2026-09-12 confirmed `build_type: workflow` and HTTPS
enforcement through the GitHub Pages API. That earlier configuration does not
establish a deployment. The operator's subsequent hold removed deployment
from the preview workflow. September 13 authorization restores deployment in
the local candidate; no live Pages setting is changed by that edit.
Pull requests validate only. Eligible main pushes and main manual dispatches
upload the scanned site directory, then deploy in the `github-pages`
environment. Only deployment has Pages write and identity-token permissions;
the build has contents/read and Pages/read. The deployment concurrency group
`pages` allows one deployment at a time without cancellation.

The current action versions were verified against their official GitHub
release metadata: configure-pages 6.0.0, upload-pages-artifact 5.0.0 and
deploy-pages 5.0.1. These are workflow dependencies, not evidence of a run.

The site links to `https://canticle.cc`. The main Canticle website can add a
Reports link to the default destination once the first deployment is live.
The generated `feed.xml` and `manifest.json` provide structured report listings
for a future website integration; no main-site integration or DNS change is
part of this setup. A later custom domain requires Pages/DNS configuration
and coordinated changes to `url`, `baseurl` and the workflow's local-link check.

GitHub Pages serves public static content. Client-side search and report
navigation work without a backend. Private reports, authenticated dashboards,
API handlers and large raw benchmark bundles need their own appropriate home.

## Recovery and operating checks

The first publication is complete only when a qualified deployment succeeds
and the public URL serves the expected revision. A passing local build alone
is not deployment evidence.

The **SEAM reports on GitHub Pages** workflow's manual dispatch on main
publishes only an admitted, nonempty catalog after validation. Use the site
README for local export and preview. Check the library, About page, feed,
manifest, report routes and public-edition downloads. Recheck public HTTP
responses and manifest pins after deployment before reporting that it is live.
Git source plus the catalog is the durable reconstruction record.
