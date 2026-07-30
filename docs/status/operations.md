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
- Full-suite zero-skip local run requires the container up and `PGVECTOR_TEST_DSN`
  exported. CI runs `-m "not external"` plus a separate `-m external` job.
- No silent skips: any skip outside the curated allowlist fails the session.
- Memory guardrails: 82% warning, 90% hard limit.
- `scripts/run_guarded.ps1` and `scripts/run_real_adapters_guarded.ps1` for heavy
  local commands and end-to-end real-adapter checks.
- `scripts/windows/launch_dashboard.bat` (wraps `launch_dashboard.ps1`).
- `scripts/store_benchmark.ps1` archives benchmark runs with sequence+time folders,
  run index, and publication metadata/hashes.

## Session-end verification

`python -m tools.history.verify_continuity` before ending a changed session;
`python -m tools.history.verify_routing` after changing classifications or ledgers.
The one-shot wrapper `python -m tools.history.closeout` performs the whole chain.
