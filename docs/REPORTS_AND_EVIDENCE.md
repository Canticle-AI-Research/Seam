# SEAM Reports and Evidence

[Back to the SEAM Wiki](README.md)

This page fixes the storage rule for SEAM reports so they do not disappear
across branches, chats, handoffs, or local machines. It is a router, not a new
report store.

## Canonical report home

All durable, human-readable, point-in-time SEAM reports belong in
[`docs/audits/`](audits/INDEX.md). This includes whole-repository audits,
focused investigations, visual status reports, architecture assessments, and
interpreted benchmark reports.

Use `docs/audits/<YYYY-MM-DD>-<short-slug>.md`, add the report to the top of the
[audit registry](audits/INDEX.md), advance its `latest` field when appropriate,
and link the HISTORY entry that records the report. Do not leave the only copy
in a conversation, untracked file, branch description, or local export.

The registry's `policy_start` date is a prospective compatibility boundary.
Reports dated before it retain the evidence contract they were written under;
reports dated on or after it must include a non-placeholder HISTORY link and
an `## Evidence manifest` section. The manifest declares either
`Raw artifacts: none` or pairs every durable artifact path with its complete
SHA-256 digest. This strengthens new evidence without rewriting historical
records or pretending old hashes were captured when they were not.

## What belongs where

| Material | Canonical location | Boundary |
| --- | --- | --- |
| Dated human-readable report | [`docs/audits/`](audits/INDEX.md) | Tracked, indexed, scope-bound evidence; this is the default report destination. |
| Current operating state | [`PROJECT_STATUS.md`](../PROJECT_STATUS.md) and [status streams](status/index.md) | Mutable current belief, not a point-in-time report archive. |
| Chronology and change evidence | [History index](../HISTORY_INDEX.md) | Append-only temporal record; reports point to it instead of duplicating it. |
| Current recovery handoff | [Handoff registry](handoffs/INDEX.md) | One live recovery head, not a general report folder. |
| Verified benchmark claims | [Benchmark results](../benchmarks/RESULTS.md) | Durable record of specific verified runs; each claim retains its evidence boundary. |
| Machine benchmark bundles | `benchmarks/runs/*.json` | Hashable artifacts kept with benchmark evidence, not copied into narrative reports. |
| Rich/private run records | [Benchmark run records](BENCHMARK_RUN_RECORDS.md) | Full-fidelity artifacts use the configured record directory or ignored `benchmarks/runs/records/`. |
| Durable external research package | [`scripts/store_benchmark.ps1`](../scripts/store_benchmark.ps1) output | Defaults outside the repository at `Documents/SEAM/benchmarks` and stores the report, command, hashes, manifest, environment snapshot, and notes. |
| Human-scannable result rows | [Progress tables](progress_tables/README.md) | Derived summaries that cite history and raw evidence. |
| Research synthesis | [Retrieval knowledgebase](kb/README.md) | Interpretation and reusable lessons, not raw proof or current status. |
| Superseded or retired report | [`docs/archive/`](archive/README.md) or `docs/status_archive/` | Historical provenance only, explicitly non-current. |
| Vulnerability disclosure | [`SECURITY.md`](../SECURITY.md) | Follow the private security-reporting route; never put credentials or exploit payloads in a report. |

`benchmarks/BENCHMARK_LOG.md` and `docs/ENGINEERING_LOG.md` are historical
supporting summaries. Use the benchmark results, current status, repo ledger,
and active code for current claims.

## Filing checklist

1. Name the report with an ISO date and a short descriptive slug.
2. State its scope, inspected revision, evidence, verification performed, and
   anything not verified.
3. Register it in [`docs/audits/INDEX.md`](audits/INDEX.md), newest first.
4. Record the change in `HISTORY.md`; the registry's `history` cell identifies
   the latest governing entry for the report.
5. Add an `## Evidence manifest`. Write `Raw artifacts: none` when the report
   relies only on tracked repository evidence. Otherwise list every raw
   artifact path beside its 64-character SHA-256 digest; never copy bulky or
   secret-bearing data into Markdown.
6. Run `python -m tools.docs.verify_wiki` with the normal continuity gates.

A report is evidence for the revision and scope it names. It does not silently
become current product status, governing policy, or proof that a later commit
still behaves the same way.
