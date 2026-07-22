# SEAM Code Layout

This file separates current code from inactive or generated code so agents do
not have to infer what works from directory names alone.

## Active Runtime

- `seam_runtime/` - packaged runtime, dashboard, storage, retrieval, model, and benchmark code.
- `seam_runtime/retrieval_orchestrator/` - multi-leg retrieval orchestrator (planner, adapters, merger) powering `seam retrieve`, the MCP tool, dashboard retrieval, and the benchmark suite. Promoted from `experimental/` in HISTORY#284.
- `seam_runtime/knowledge_graph.py` - canonical MIRL-to-graph projector, conservative 5W1H+Then lens, evidence-derived trust profiles/assertion gate, versioned existing-database backfill, temporal/source supersession, graph query, node-page, and statistics logic. `SQLiteStore.persist_ir` maintains it automatically (HISTORY#403).
- `seam_runtime/reasoning_graph.py` - append-only public reasoning nodes, edges, and state transitions anchored to workspace runs, with scoped knowledge/MIRL evidence references and no automatic canonical promotion.
- `seam_runtime/sdk.py` - stable local Python SDK over SEAM runtime, knowledge queries, and run-scoped reasoning sessions; CLI, REST, MCP, and framework packages can remain adapters rather than storage clients.
- `seam_runtime/workspace.py` - append-only structured workspace run/event schema, allowlisted telemetry sanitization, SSE framing/replay, and deterministic graph-activation projection. It explicitly excludes credentials, hidden chain-of-thought, and raw activation tensors.
- `seam_runtime/jspace.py` - optional J-lens capability boundary: unavailable/structured-only default, verified local Hugging Face Qwen adapter, and authenticated pinned remote worker. No model, lens, analyzer, download, or network dependency is enabled by default.
- `seam_runtime/self_improve.py` + `tools/h2/improvement_loop.py` / `improvement_review.py` - graph-derived probes and the strict multi-family propose-and-approve ratchet wired into the existing H2 proposal, decision, and applied-flag substrate.
- `seam_runtime/webui/` - the SEAM browser dashboard served by the REST API: `dashboard.html` (the IDE-style operator UI), `seam-api.js`, `tweaks-panel.jsx`, branding, and icons. `seam serve` and `seam webui` serve these at `/` on the same origin as the API; packaged with the wheel. This is the functional dashboard (HISTORY#285).
- `seam.py` - console entrypoint module for `seam` and `seam-benchmark`.
- `test_seam_all/test_seam.py` - primary regression suite. Local `test_seam_*.db`
  artifacts live in ignored `test_seam/` so root stays clean.
- `tests/docs/` - tracked testing documentation, including local artifact
  routing notes and test-run hygiene rules.

## Active Tooling

- `tools/history/` - canonical history, index, integrity, handoff-registry, and snapshot tools.
- `docs/handoffs/INDEX.md` - canonical tracked handoff head and supersession chain; dated handoff documents are valid only when registered there.
- `tools/git-hooks/` - canonical git hooks (`pre-commit`, `pre-push`) installed via `tools/git-hooks/install.sh`.
- `tools/release/` - public/private separation for the `seam-runtime` mirror: `public_manifest.py` (fail-closed allow-list of what's public), `sync_public_mirror.py` (builds the curated sync commit), `public_seed/` (one-time seed templates for the public repo's own independent bookkeeping), and `verify_public_safe.py` (deny-list + allow-list scanner invoked by the `pre-push` hook as a backstop).
- `tools/*.py` - active benchmark/projection helper scripts.
- `scripts/` - active operator scripts and guarded runners.
- `installers/` - active installation entrypoints and installer docs.

## WebUI

- `seam_runtime/webui/` - **the one and only webui.** A single self-contained
  `dashboard.html` (+ `seam-api.js`, `favicon.svg`, `icons.svg`, `branding/`),
  hand-authored with CDN React. `seam webui` / `seam serve` serves it at
  `http://127.0.0.1:8765/` (`server.py:webui_dir()`; override `SEAM_WEBUI_DIR`).
  The runtime needs no Node or build step.
- `archive/webui-vite-source/` - the **archived** Vite + React + TypeScript dev
  project (was top-level `webui/`). It had diverged from the served file (the
  canonical is hand-authored, not built from this tree), so it was archived in
  HISTORY#326 to end the "which webui is real?" confusion. See its `ARCHIVED.md`.
  Revivable via git history if the Vite shell is ever resumed.
  (`experimental/` was removed in HISTORY#285 — nothing in this repo is
  experimental.)

## Inactive Code

- `archive/code/` - retired code and local generated build copies. Nothing in
  this folder is active, imported, tested, or packaged.

## Generated / Local-Only Code

- `build/` and `archive/code/generated-build*/` are generated build copies and
  are ignored by git.
- `test_seam/` contains local isolated SQLite databases produced by test runs.
  It is not project source, runtime truth, roadmap evidence, or useful context
  for normal agent scans. Scoped subdirectories such as `test_seam/pgvector/`
  hold adapter-specific generated artifacts.
- `__pycache__/`, `.pytest_cache/`, `.venv/`, and `*.egg-info/` are local
  environment or packaging artifacts.

## Agent Rule

For normal development, read active runtime/tooling/prototype paths first. Do
not scan `archive/code/` unless the task explicitly asks for historical or
retired code.

Place new tracked testing documentation under `tests/docs/`. Place generated
test artifacts under ignored `test_seam/<area>/`, not in the repo root.

## Search Rule

`.rgignore` excludes inactive, generated, and cache-heavy paths from default
searches. Use explicit paths or `rg --no-ignore` only when investigating archive
or retired-code history on purpose.
