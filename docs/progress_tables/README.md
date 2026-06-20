# SEAM Progress Tables

This directory stores tracked, human-readable data tables for scanning SEAM's
test, benchmark, and milestone progress without rereading the full append-only
history.

`HISTORY.md` remains authoritative. These CSVs are derived summaries: each row
must cite a `history_id`, command/result evidence where available, and the next
learning step when one exists.

## Tables

- `test_runs.csv` - test and verification runs worth tracking across sessions.
- `benchmark_results.csv` - benchmark, scorer, and diagnostic measurements.
- `milestones.csv` - durable progress claims and what they changed.

## Row Rules

- Prefer one row per distinct result or claim.
- Keep raw generated outputs out of this directory; use benchmark bundles,
  history entries, and audit docs as references.
- Use `unknown` instead of inventing counts or commands.
- If a later row supersedes a claim, add a new row. Do not rewrite older rows
  just to make the timeline look cleaner.
- Do not store secrets, provider session links, local env values, API keys, or
  credential-bearing DSNs.

