# Status Stream: Operations

> pgvector, Docker, CI, guardrails, and durable operator workflows

_Source of truth for current state in this area. History lives in `HISTORY.md`._

## Stable

- pgvector via Docker Compose: `docker compose --env-file <private-env> up -d pgvector`;
  container `seam-pgvector`; port **55432**; credentials stay outside the repo.
- Docker Desktop is a user service (no system `docker.service`); start via
  `~/.local/bin/docker-up`; auto-stops after 30 min idle.
- Self-hosted CI runner `seam-terrabyte` (systemd user service, docker wake hook)
  runs all Seam Linux CI. pgvector CI port 55433. Windows leg is manual-only.
- The protected-main required checks are `repo-hygiene`, `chroma-real-smoke`,
  and `locomo-quickstart-bil2`. The long `test-and-benchmark` suite runs after
  the short jobs but is advisory under the current live ruleset; Track S S10
  owns the proof required before making it a required merge check.
- Full-suite zero-skip local run requires the container up and `PGVECTOR_TEST_DSN`
  exported. CI runs `-m "not external"` plus a separate `-m external` job.
- No silent skips: any skip outside the curated allowlist fails the session.
- Memory guardrails: 82% warning, 90% hard limit.
- `scripts/run_guarded.ps1` and `scripts/run_real_adapters_guarded.ps1` for heavy
  local commands and end-to-end real-adapter checks.
- `scripts/windows/launch_dashboard.bat` (wraps `launch_dashboard.ps1`).
- `scripts/store_benchmark.ps1` archives benchmark runs with sequence+time folders,
  run index, and publication metadata/hashes.

## Track S operating state

- S1 routes real Uvicorn `--factory` startup through the same bind and worker
  safety validation as normal launch.
- `tools.security.secret_scan` owns the canonical secret/session patterns.
  Repository hygiene scans the working tree, while pre-push scans every new
  commit-range blob, including content added and deleted before the pushed tip.
- `pyproject.toml` owns the checked runtime dependency, installer mirror,
  convenience-extra, exclusion, and retired-extra contract. Frozen release
  lock/hash evidence remains S10 work.
- `seam doctor` requires only the canonical core imports `rich` and `tiktoken`.
  Chroma, pgvector, and sentence-transformers remain informational optional
  availability checks; an absent Chroma installation cannot fail doctor.
- S1's strict non-external suite and live pgvector external suite are locally
  green. The live external lane used pgvector 0.8.5 while Compose declares
  0.8.6; protected CI owns exact-image parity.
- S2's schema-version-2 migration spine is locally qualified. Empty, v1.2.0,
  v2.4.0, and supported intermediate-v1 paths upgrade through two transactional
  steps; each step is rollback-injected and integrity/foreign-key checked.
  Unknown/newer stores refuse byte-unchanged, and retained private backups have
  completed a real delete/restore/re-upgrade recovery. Current stores with
  missing registered tables fail closed rather than silently recreating them.
  Projection version changes now require exact registered callables with
  version-specific source/target table contracts. One exclusive migration owner
  revalidates the live plan under lock, takes the backup from that same
  connection, and retains writer exclusion across separately committed,
  resumable steps. Marker CAS, per-step integrity/foreign-key checks, rollback
  injection, backup restore, and populated-store table-add preservation are
  proved. Unregistered add/remove/change states still refuse before backup or
  mutation.
- The post-S2 audit's persistence, chat-credential, and trust-time findings are
  merged on protected `main`: canonical
  entity reconciliation locks before its read; built-in chat environment keys
  are host-bound and unavailable to loopback; malformed trust timestamps fail
  toward stale with content-free diagnostics. Automatic first-launch
  `SEAM_API_TOKEN` provisioning remains a separate authentication/UX policy
  decision; tokenless mode is trusted-local-only. Audit findings 7-10 and 12
  remain open.
- S3 is published through PR #194 at `main@9bd40cb`. Its exact KG/4-to-KG/5
  transition rebuilds disposable topology from canonical
  MIRL/lifecycle/document status, preserves the identity judgement ledger, and
  refuses damaged/newer inputs before publishing partial topology.
- S4 is published through PR #195 at `main@ea4e46e`. Closed typed-reference
  contracts replace colon inference; both
  edge endpoint types and source-record contributors are durable; exact
  `core-storage/1 -> /2` plus KG/5-to-KG/6 steps preserve S3's truthful resume
  point. Canonical inputs are processed in bounded batches, invalid identifiers
  produce digest-only diagnostics, current stores reject dangling canonical
  payloads and edge contributors, and 300-triple type checks replace per-edge
  migration queries. Reserved virtual metadata is unconditional, and hard
  deletes fail atomically if a surviving required reference would remain.
  Removed phantom nodes cannot leave searchable orphan vectors.
- S5 is published through PR #199 at `main@19b3a76`. One committed read snapshot,
  bound per request and keyed by database identity, now covers every
  SQLite-backed leg and visibility check -- including the SQLite vector index,
  which is opened on `store.path` and so was reading a second state even after
  the canonical legs were pooled. The snapshot carries an authorizer denying
  mutations, because a stray write would otherwise join the read transaction
  and be silently discarded by the closing rollback. A durable `vector_outbox`
  commits the intent to index in the same transaction as the canonical rows and
  replays on reopen, closing F7's process-loss window; deletes stay on
  lifecycle's existing `cleanup_pending` state rather than gaining a second
  source of truth. `PgVectorAdapter.search` no longer ensures schema (F14), and
  `SQLiteVectorIndex.ensure_schema` no longer re-runs per search -- that per-query
  DDL was also why warm retrieval kept opening connections despite the pool.
  Divergence (missing/stale/orphan) is detected and repaired on all three
  backends, with Chroma gaining the inspection methods it lacked.
- S6 (principal tenancy and opaque deletion) is the next stage and is unstarted.
  It must state explicitly whether tenancy terminates in a proxy ahead of `/v1`
  or in-process; that decision is written down nowhere, and `/v1` still has no
  tenancy binding and zero HTTP-level tests.
- The live pgvector lane is exercised locally by exporting `PGVECTOR_TEST_DSN`
  from the running `seam-pgvector` container (`SEAM_PGVECTOR_DSN`, port 55432).
  Without it, 4 external cases skip; with it the full suite is 2028 passed, 0
  skipped, 2 xfailed.
- The history advisory lock now resolves through a linked worktree's
  `gitdir:` pointer, so `python -m tools.history.new_entry` no longer leaves an
  untracked `HISTORY_INDEX.md.lock` inside a worktree's working tree where
  `git add -A` would commit it.
- Clean artifact/privacy proof remains mandatory on the frozen candidate, and
  every S10 gate must be rerun after S1-S9 even while the full suite is advisory
  in branch protection.

## Session-end verification

`python -m tools.history.verify_continuity` before ending a changed session;
`python -m tools.history.verify_routing` after changing classifications or ledgers.
The one-shot wrapper `python -m tools.history.closeout` performs the whole chain.
