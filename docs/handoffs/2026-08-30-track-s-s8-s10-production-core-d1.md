---
handoff_id: 2026-08-30-track-s-s8-s10-production-core-d1
supersedes: 2026-08-29-grounded-research-acquisition-roadmap
handoff_status: superseded
history: HISTORY#620
---

# Track S S8-S10 production-core consolidation and D1

## Current boundary

The detailed execution authority is
`docs/roadmap/TRACK_S_S8_S10_PRODUCTION_CORE.md`. It reconciles the protected
Track S history with the 2026-08-29 deep audit, defers TUI, benchmark-surface,
graph-dashboard, WebUI-dashboard, and public-API presentation work, and
dependency-orders the remaining production-core work as controlled TDD
streams.

D1.1-D1.3 are a branch-local candidate on `feat/s8-s10-production-core`.
Supported file-backed stores now hold a cross-process lifetime lease. Restore validates
the backup before mutation, refuses while a supported store is live,
checkpoints recognized target WAL state, quarantines remaining sidecars before
the database replacement commit point, and fsyncs the replacement boundary.
Fork children preserve parent-owned locks, acquire child-owned locks for fresh
stores, and release inherited duplicate handles after the final inherited
logical store closes. The focused non-external recovery slice has 78 passing
tests. The staged CodeRabbit review covered the original candidate files with
zero findings, and independent assurance returned zero findings after the
final fork repairs.
The full 3,146-test non-external collection also exits zero when
`HF_HUB_CACHE` names the existing pinned-model cache, with two expected xfails
and no skips. The default machine cache variable currently points elsewhere;
the first full run therefore failed closed at model preflight rather than
silently downloading or scoring with a substitute.
The systematic filesystem-transition failure matrix remains D1.4 work, so the
whole D1 stream is not yet closed.

## Claim boundary

This is not protected-main fact until merged. It does not complete S8, start
S9 qualification, make S10 checks required, publish a package, deploy SEAM, or
qualify hosted production. The intended terminal claim after S8-S10 is
**production-core qualified**; hosted-production qualification additionally
requires the external topology and operator-controlled operational proof named
in the spec.

## Resume order

1. Merge and exact-head qualify the D1.1-D1.3 slice without weakening the three protected-main
   required checks.
2. Complete D1.4's systematic filesystem-transition failure matrix.
3. Execute D2 ingest atomicity, then D3 lifecycle exclusion and D4 snapshot
   consistency in red-green-refactor slices.
4. Close T1 temporal correctness before R1/R2 retrieval correctness and G1
   graph qualification.
5. Close S8's boundary-only SQL decision before any S9 promotion measurement.
6. Run S9 matched multi-benchmark qualification, then S10 reproducible build,
   release, and deployment-proof gates.

Do not resume the deferred operator surface as part of those streams. Preserve
canonical RAW/MIRL and provenance authority in SQLite; graph, vector, PACK,
surface, and benchmark views remain derived.
