# SEAM report library

Jekyll presentation templates and an explicit public report catalog. Operator
and publication policy: [public report site](../docs/REPORT_SITE.md).

The catalog starts empty. Include only new work from the operator's September
12 fresh-start request onward; do not import earlier repository reports.
The operator authorized publication on September 13. Main-branch builds may
upload and deploy only after validation, with at least one admitted report.
Pull requests and empty catalogs validate without publishing. The first M1
edition is prepared; source commit, catalog admission and qualification remain
pending. The earlier private-link staging blocker was resolved with the
operator's explicit approval; see the operator policy for current status.

## Local validation

From the repository root, using its Python environment:

```bash
python -m pytest tests/audit/test_report_site.py tests/audit/test_report_publication_safety.py tests/audit/test_report_deployment_boundary.py -q -o addopts=
python -m tools.reports.prepare_site --output test_seam/report-site/source
```

The destination must not exist; select a fresh ignored directory for another
export. Build the resulting directory with the GitHub Pages Jekyll engine
(`actions/jekyll-build-pages@v1`). The workflow defines the exact source and
destination and verifies generated pages, source hashes, the Atom feed and
local links. Run `python -m tools.reports.publication_safety --site DIRECTORY`
on the built artifact before serving it locally. The workflow's upload and
deployment both depend on this gate and a nonempty admitted catalog.

When serving the artifact locally, mount it at `/Seam/` to match `baseurl`.
Check both narrow and wide viewports, search, report-type filters, context
notes and source downloads. Nothing outside this directory's explicit template
inputs, canonical branding and pinned catalog reports is copied to the site.

## Catalog

`catalog.json` has schema version 1 and a `reports` array, which may be empty.
An empty catalog exports no report pages or downloads, even if other records
exist in the repository. Every future admitted report contains
exactly `id`, `title`, `date`, `kind`, `summary`, `context`, `source`, `revision`,
`sha256`, `edition` and `edition_sha256`. The original source must be Markdown
in `docs/audits/` or `tests/docs/`. Its complete commit and digest are mandatory.
The public edition must be `report-site/editions/<id>.md` and match its separate
digest. Downloads contain the public edition, never the raw original source.
`report_id` is generated separately because Jekyll reserves its own `id` field.

Markdown, ordinary links, tables and code blocks suit this initial text-only
library. Runtime configuration, inline active HTML and private/local references
fail publication. Additional binary formats require a separate inspection path.
Use inline Markdown links for repository references; inspect any reference
links or raw HTML carefully in the rendered preview before adding a report.

`feed.xml` and `manifest.json` are public metadata. No PDF generator, benchmark
execution, provider credentials or main Canticle website deployment is included.
