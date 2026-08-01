---
handoff_id: 2026-08-01-track-s-s0-locally-qualified
supersedes: 2026-08-01-track-s-production-core-campaign
handoff_status: superseded
history: HISTORY#513
---

# Handoff: Track S S0 locally qualified

**Date:** 2026-08-01
**Branch:** `fix/memory-guarantees-campaign`
**Merge base:** `origin/main@512b35c86fe5ae51c2fff4e959c1a94ef2baa309`

## One-line state

Track S S0 is locally qualified on the clean replacement branch: the complete
repository suite, live external lane, bounded review, source/path/security
audit, and canonical continuity gates are green; protected-main CI and merge
are the remaining publication boundary, and S1 is the next implementation
stage.

## What S0 establishes

- The reconstructed retrieval head accounts for all 61 differences from
  `origin/refactor/unify-retrieval-paths`: 59 tracked `.ua` artifacts are
  excluded, while the only two non-`.ua` differences are the current
  `archive/webui-vite-source/package-lock.json` and `docker-compose.yaml`
  contracts from protected main.
- The replacement branch contains zero `.ua`, `dist/`, report-image,
  database, model, cache, private-session-link, or generated-source paths.
- Fail-closed exact-REL, same-boundary, canonical-ENT admission and the
  scorer-ineligible relation research lane from the semantic branch remain
  covered by the focused and full suites.
- `docs/roadmap/MEMORY_GUARANTEES_CAMPAIGN.md` remains the only F1-F22 plan.
  S0 qualification does not claim any production defect repaired.

## Review-hardening slice

The bounded branch review was converted into tests and narrow corrections:

- WANDR now uses one canonical URL contract, strict row shapes, hash embeddings,
  environment-extractor denial, pre-ingest lane reset, complete SQLite sidecar
  cleanup, post-success provenance marking, and explicit zero-network failure
  accounting.
- LoCoMo ingest-only refuses a non-pristine target before adapter construction
  or model preflight, and embedding preflight requires both the declared and
  loaded model to be `local_files_only=True`.
- Relation qualification requires at least 50 reviewed samples; missing or
  inaccessible ingest datasets produce the stable `dataset_not_file` reason.
- Temporal plans reject mixed timezone-awareness and normalize aware values to
  the store's UTC-naive contract. Memory-vector search now matches persistent
  backends by excluding non-positive cosine scores.
- Retrieval flags preserve explicit falsey values, leg-weight parsing rejects
  empty/duplicate names, extractor metadata fails closed unless strict JSON,
  and RAW provenance distinguishes missing content from missing identity.
- MIRL holographic query remains on the strict canonical persist/retrieve path;
  status-stream links, provenance tests, runtime fixture cleanup, and the
  retired self-host/public-sync policy text now match the live repository.

## Exact local evidence

- Frozen repository-wide non-external gate: **2,095 collected; 2,070 passed;
  2 expected xfails; 23 external deselected; zero failures, errors, or skips**
  in 555.99 seconds. The before/after 747-file manifest was identical at
  `d7b717c247eb8a386671c5d1c4530b967fca8f7866dcfb470f3fcd0d9f1d2936`.
- Live pgvector external gate: **23/23 passed**, zero skips/failures. The live
  loopback-only service used pgvector 0.8.5; Compose declares 0.8.6, so exact
  image parity belongs to protected CI.
- Focused post-review aggregate: 210/210 passed, plus the complete relation
  ingest file 15/15. Changed-Python Ruff and `git diff --check` passed.
- CodeRabbit moved from 50 initial findings to four on the second pass. Three
  were fixed or disproved; F22 dependency-source drift remains deliberately
  routed to S1/S10. The final pass reported one major and zero criticals; that
  major was disproved because the legacy planner and adapter apply the identical
  compatibility-kind set before limiting. Its three focused parity tests passed.
- Candidate audit covered current paths, newly reachable blobs, and commit
  messages with the CI, continuity, and public-safe patterns: zero secret,
  private-session, denied-path, binary, whitespace, or hidden-artifact findings.

## Boundaries and remaining risk

- No provider, answerer, judge, network, or paid benchmark ran.
- The final clean wheel/sdist, opaque-boundary, and privacy proof must be rerun
  from the frozen commit before push. This is publication evidence, not an S0
  defect claim.
- F22 is not fixed. There is no approved hash-locked dependency source to
  derive safely, so no improvised lock or release hash was added.
- PR #189 overlaps this branch and carries excluded `.ua` artifacts. Do not
  merge it first. Close it as superseded only after this branch merges and the
  semantic-admission coverage is confirmed on protected main.
- No release or destructive worktree/artifact cleanup is authorized by this
  handoff.

## Exact next step

1. Build and inspect the final artifacts from the frozen commit, then push the
   branch and open the ready replacement PR.
2. Require the exact PR head to pass required and advisory CI, including the
   full suite, pgvector, package, registry, and CodeRabbit lanes; squash-merge
   only that green head.
3. Begin S1 at F2/F6/F18/F19/F20/F22. Do not skip the migration spine or claim
   later-stage memory guarantees from this baseline.
