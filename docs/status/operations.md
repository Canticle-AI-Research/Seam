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
- S1's strict non-external suite and live pgvector external suite are locally
  green. The live external lane used pgvector 0.8.5 while Compose declares
  0.8.6; protected CI owns exact-image parity.
- S2 must add the transactional migration spine before any durable layout
  change or guarded reprojection work begins.
- Clean artifact/privacy proof remains mandatory on the frozen candidate, and
  every S10 gate must be rerun after S1-S9 even while the full suite is advisory
  in branch protection.

## Session-end verification

`python -m tools.history.verify_continuity` before ending a changed session;
`python -m tools.history.verify_routing` after changing classifications or ledgers.
The one-shot wrapper `python -m tools.history.closeout` performs the whole chain.
