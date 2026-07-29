---
handoff_id: 2026-07-29-package-stability-release-candidate
supersedes: 2026-07-28-seam-node-wheel
handoff_status: superseded
history: HISTORY#489
---

# Handoff: stable self-host and hosted API release candidates

**Date:** 2026-07-29
**Base:** `origin/main` at `5db9b2aaad6c`
**Branch:** `fix/selfhost-1.1.2-stability`
**Publication state:** qualified locally; not published by this handoff

## One-line state

The compiled self-host 1.1.2 and private hosted API 2.4.0 candidates are
implemented and qualified; merge, protected release workflows, and live
clean-install verification are the only remaining package steps before
returning to G3 and R4.

## Distribution boundary

- `seam-client` 2.0.0 is the live Apache-2.0 public HTTP client.
- `seam-self-host` 1.1.2 is the BUSL compiled package for customer-operated
  nodes. Its public console commands are `seam-self-host` and `seam-mcp`.
- Private `seam-runtime` 2.4.0 is the hosted `/v1` server package intended for
  the future subscriber service. Its release target is a private GitHub
  Release, not PyPI.
- `public_pkg/` is only the fail-closed API compatibility shim. It is not the
  hosted server and is not part of this release.
- DigitalOcean provisioning and deployment remain deliberately deferred until
  the packages are live and clean-install verified.

## Stability repairs

- Pgvector is connected and probed before startup completes, with bounded
  retries and no credential-bearing DSN in failures.
- `GET` and `HEAD` readiness are backed by live storage and vector checks, use
  a five-second cache, and return 503 while degraded.
- Public remember, recall, and context inputs reject non-string identifiers and
  text instead of coercing arbitrary objects.
- Self-host CLI `--host`, `--port`, and `--db` override environment defaults;
  `SEAM_SERVER_DB` wins over `SEAM_DB_PATH`; empty paths fail cleanly.
- No-argument `seam-mcp` falls back to
  `${XDG_DATA_HOME:-~/.local/share}/seam/seam.db` outside a writable container
  layout.
- Expected startup failures are one line unless `SEAM_DEBUG` is enabled.
  Invalid provider and retrieval-profile selections fail before serving.
- Request failures remain opaque, 429 responses include `Retry-After`, and
  unexpected exceptions return generic JSON 500 responses.
- New SQLite parents and files are 0700 and 0600 respectively on POSIX systems.

## Final artifact evidence

Private hosted API:

- Wheel:
  `seam_runtime-2.4.0-py3-none-any.whl`, 818,620 bytes,
  SHA-256 `366467f560c857ac2ad2b896f5ba786fa850d1a873e404aa651af0138ecf01f2`.
- Sdist:
  `seam_runtime-2.4.0.tar.gz`, 790,653 bytes,
  SHA-256 `91848cf869588e5b15198e35cbb5f7ef167b4c24ed1739547ce92d107371fe29`.
- Both pass `twine check` and the exact private-GitHub distribution boundary.
- A clean virtual environment installed the wheel with `server` and `pgvector`
  extras plus released `seam-client==2.0.0`; dependency checks and real
  remember/recall/context calls passed with SQLite and live pgvector.

Compiled self-host:

- Wheel:
  `seam_self_host-1.1.2-cp312-cp312-manylinux_2_28_x86_64.whl`,
  3,623,685 bytes,
  SHA-256 `36d67629dbd97c74634f61c3bbadc2f37d768ac21bfe599216ee89a19153d362`.
- `twine check`, exact name/version/license verification, source/privacy scans,
  and the clean-container runtime proof pass.
- The payload is one compiled `seam_runtime` extension and no runtime source.
  Every reserved marker remains exactly at its existing budget: 414/414 total,
  with no allowance raised.
- Clean installs passed SQLite and live pgvector API calls through
  `seam-client==2.0.0`, no-argument MCP/XDG permissions, and six one-line
  startup-failure modes.
- Real PyPI upgrades from 1.0.0 and 1.1.0 to this exact wheel removed the legacy
  payload and passed the installed API proof.

Repository verification:

- The canonical full suite exited 0 with zero skips and the two established
  xfails against live pgvector.
- The touched audit modules collect together; touched-file Ruff and
  `git diff --check` pass after final formatting.
- Earlier CodeRabbit passes drove fixes for exact metadata checks,
  database-path normalization, environment precedence, health throttling, and
  proof-process handling. The terminal 34-path pass added three valid fixes:
  blank optional-session compatibility, precise `agent_id` bounds, and real
  pgvector schema readiness. Its SQLite-sidecar concern was disproved by a
  permissive-umask regression showing 0600 WAL/SHM files; its history findings
  conflicted with the canonical pre-commit closeout protocol or the actual
  controlled topic list. The post-fix pass found only the already-disproved
  request to chmod/reject operator-selected existing parents and two findings
  against intentionally bounded generated cross-index rows; canonical stream
  verification passes. HISTORY#488 and #489 record the full disposition.

## Release sequence

1. Complete canonical history/snapshot/continuity/stream closeout.
2. Push the branch, open the PR, and keep every relevant check green.
3. Merge to protected `main`.
4. Run the private package release for `seam-runtime` 2.4.0 and verify its
   GitHub tag, release, and artifacts.
5. Run the self-host release for 1.1.2 and verify live PyPI metadata plus a
   clean network install and API/MCP proof.
6. Record the live release facts in a superseding closeout.

## Graph/reasoning restart point

- G3 remains partial despite its synthetic 2,048-node scale gate and
  `reciprocal-rank-fusion/2`. Resume with a versioned, derived graph-node vector
  projection for entity, value, agent, and symbol nodes; preserve
  namespace/scope prefiltering and explicit-reindex migration, then qualify it
  on a predeclared real corpus and backend-specific scale.
- R1-R3 are implemented. Start R4 as retrieval and reuse of prior reasoning
  patterns with task/run compatibility, freshness, trust, and exact provenance
  gates so a prior conclusion cannot launder itself into evidence.
- Keep G3 and R4 independent until each contract passes; do not blend their
  measurements or treat one as evidence for the other.
