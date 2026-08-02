---
handoff_id: 2026-08-01-track-s-s1-locally-qualified
supersedes: 2026-08-01-track-s-s0-locally-qualified
handoff_status: superseded
history: HISTORY#520
---

# Handoff: Track S S1 locally qualified

**Date:** 2026-08-01
**Branch:** `fix/track-s-s1-guardrails`
**Base:** `origin/main@778de2c`

## One-line state

Track S S1 is locally qualified: all immediate fail-closed guardrails and the
immediate dependency-source contract are implemented, the complete local suite
is green, and S2's transactional migration spine is the next dependency.

## What changed

- SQLite record loading and all retrieval/fusion tie boundaries now use stable
  record-ID ordering, including tied budget-1 output after an unrelated rewrite.
- `rrf_k` is validated as a positive integer at construction, coercion, and
  environment loading, so invalid input cannot reach division.
- Real Uvicorn factory startup derives the same host/worker settings and runs
  the same remote-bind and process-local-rate-limit safety checks as normal
  startup.
- Ordinary knowledge-graph initialization reads the projection marker before
  graph DDL or deletion and refuses missing, stale, or newer versions without
  mutation. Explicit migration/reprojection remains S2/S3 work.
- `tools.security.secret_scan` centralizes the CI, continuity, public-safe, and
  pre-push patterns. Range scanning walks every newly introduced blob, including
  content deleted before the pushed tip; oversized text is fail-closed except
  for the exact hash-pinned canonical LoCoMo dataset.
- The private MCP handshake derives its version from installed package metadata
  with an explicit `unknown` fallback. The legacy `server.json` compatibility
  value is intentionally unchanged.
- `[tool.seam.dependency-contract]` now defines and verifies the runtime source,
  installer mirror, convenience-extra union, exclusions, and retired extras.
  `selfhost` is retired from CI; S10 still owns frozen release lock/hash proof.

## Exact local evidence

- Repository-wide non-external scope: **2,094 selected; 2,092 passed; 2 expected
  xfails; 23 external deselected; zero failures, errors, or skips**.
- Live pgvector external scope: **23/23 passed**, zero failures or skips, against
  the healthy loopback `seam-pgvector` service (`pgvector/pgvector:0.8.5`).
- Projection/migration/identity focused slice: **48/48 passed**.
- Changed-Python Ruff, compile/collection checks, dependency-contract verifier,
  central working-tree secret scan, and `git diff --check` passed.
- Three bounded CodeRabbit passes produced actionable findings around factory
  parsing, scanner range coverage/fail-closed behavior, and test isolation; all
  validated findings were corrected. A final clean rerun was unavailable at
  closeout because the free-plan review limit had been reached.

## Boundaries

- No paid provider, answerer, judge, release, or retrieval-score benchmark ran.
- S1 does not supply the central transactional migration spine, durable outbox,
  principal tenancy, semantic qualification, surface parity, promotion, or
  release proof owned by S2-S10.
- The canonical checkout's unrelated dirty work remains untouched; all S1 work
  is isolated in this dedicated worktree and branch.
- The interrupted-suite database was moved recoverably to
  `/tmp/seam-s1-stray.eZ6DoD/`; nothing material was deleted.

## Exact next step

Implement S2 as one central schema/projection migration spine. Start with empty
and maintained historical fixtures, then prove per-step rollback, SQLite
integrity/foreign-key checks, byte-unchanged refusal of unknown/newer stores,
and demonstrated backup recovery before starting S3-S5.
