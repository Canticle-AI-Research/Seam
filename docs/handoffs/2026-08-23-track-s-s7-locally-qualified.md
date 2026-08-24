---
handoff_id: 2026-08-23-track-s-s7-locally-qualified
supersedes: 2026-08-23-track-s-s7-entity-evidence-in-progress
handoff_status: superseded
history: HISTORY#602
---

# Track S S7 locally qualified

## Authoritative state

- Protected `origin/main@1752532` contains finished S0-S6. S7 is locally
  qualified only on `track-s/s7-semantic-ingest` in draft PR #226; it is not
  protected-main behavior until that PR passes exact-head review and merges.
- The branch began exactly at protected `main@1752532`. The reused
  `/home/terrabyte/Documents/Projects/Seam-track-s-s6` directory owns S7 only.
- The dirty primary checkout, unrelated worktrees, sibling repositories, and
  operator artifacts remain outside this workstream.

## S7 qualification

- Functional and multivalued predicates reconcile deterministically by
  namespace, scope, event time, confidence, and stable identity. Equal or
  missing event time never fabricates temporal supersession.
- Reconciliation records have deterministic IDs and replay idempotently across
  concurrent runtime instances. Graph reads honor relation valid-time
  intervals for as-of traversal.
- Entity canonicalization is isolated by namespace and scope. Explicit stable
  identity keys keep same-name people separate, while repeated mentions merge
  their exact provenance and evidence onto the canonical entity.
- Canonical relations cannot cross namespace or scope boundaries. Open-
  vocabulary REL evidence remains preservable, but only the closed reviewed
  predicate registry may enter retrieval or public graph traversal.
- Compiled entities retain exact repeated-mention SPAN evidence, preserve
  multiword names, and reject stopword-only identity terms. A provider-free
  retrieved-ENT fixture returned five entities and all 5/5 resolved through
  complete exact SPAN-to-RAW provenance chains.

## Verification boundary

- The focused successor sanity slice passed 45 tests across S7 temporal,
  identity, evidence, relation qualification, handoff, and deep graph suites.
- The complete isolated non-external lane selected 3,007 of 3,030 collected
  tests and passed 3,005 with two established xfails and 23 external tests
  deselected. Ruff and `git diff --check` passed.
- The native LoCoMo ENT result remains 0.0000. The 5/5 fixture proves S7
  conformance only; native corpus freeze/review, scorer eligibility, full-
  corpus measurement, and promotion remain S9.

## Next boundary

1. Commit and push the S7 completion to PR #226.
2. Require exact-head required checks, advisory full-suite evidence, and review;
   repair any current-head finding before merge.
3. Merge through protected main, then publish one protected-main S8-next
   handoff through a bounded closeout PR.
4. Begin S8 only from that resulting protected head. Do not start it from the
   unmerged S7 branch.
