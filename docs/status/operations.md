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

## Verified Track S gaps

- Real Uvicorn `--factory` startup does not yet share every normal server-safety
  guard (S1).
- Secret-scanner copies and commit-range push coverage can drift; the central
  scanner must cover provider key/session URL fixtures and added-then-deleted
  content (S1).
- `server.json`'s legacy 1.3.1/URL is intentional compatibility, but the private
  MCP handshake's 1.3.1 report is stale (S1).
- Dependency declarations and lock/source expectations drift across active
  install and CI paths (S1/S10).
- S0's strict non-external suite, live pgvector external suite, focused campaign
  suites, candidate security audit, and canonical history gates are locally
  green. The live external lane used pgvector 0.8.5 while the Compose contract
  declares 0.8.6; protected CI owns exact-image parity.
- Clean artifact/privacy proof remains mandatory on the frozen candidate, and
  every S10 gate must be rerun after S1-S9 even while the full suite is advisory
  in branch protection.

## Session-end verification

`python -m tools.history.verify_continuity` before ending a changed session;
`python -m tools.history.verify_routing` after changing classifications or ledgers.
The one-shot wrapper `python -m tools.history.closeout` performs the whole chain.
