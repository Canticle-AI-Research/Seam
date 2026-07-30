# Status Stream: Protocol Continuity

> History protocol, streams, routing, and context budget

_Source of truth for current state in this area. History lives in `HISTORY.md`._

## Stable

- Durable history protocol: `AGENTS.md`, `HISTORY.md`, `HISTORY_INDEX.md`.
- `HISTORY.md` is append-only. Never edit old entries; use `supersedes`. Never
  `cat HISTORY.md`.
- Token-bounded context loading via snapshots and
  `python -m tools.history.build_context_pack --topics <tags> --latest <n> --token-budget <budget>`.
- Route-aware data classification via `tools/history/routing_manifest.json` and
  `docs/ledgers/`.
- Active/inactive separation: `docs/CODE_LAYOUT.md` maps live vs archived paths;
  `.rgignore` gates code search.
- Streams live under `.seam/streams/<name>/`.

## Status streams (added 2026-07-30)

`PROJECT_STATUS.md` had accumulated 143 stacked `Current update:` blocks across
~1,037 lines (348 KB) and could no longer be opened by a standard file read, despite
being step 1 of the mandatory session-start read order. It is now a thin router over
`docs/status/`. The full prior file is preserved verbatim at
`docs/status_archive/2026-07-30-project-status-full.md`; all 234 `HISTORY#` entries
it cited remain present in `HISTORY.md`.

## Active

- Reduce startup context overhead via compact index + surgical reads.
- Preserve near-complete temporal history without loading it all into context.
- Keep maintenance, security, context, and runtime facts logically routed for AI
  search without duplicating chronology.
- Keep roadmap execution tied to history entries and supersedes chains.
- Continue feature delivery without reintroducing duplicated continuity text.
