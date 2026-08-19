# SEAM Code Layout

This file separates current code from inactive or generated code so agents do
not have to infer what works from directory names alone.

## Active Runtime

- `seam_runtime/` - packaged runtime, dashboard, storage, retrieval, model, and benchmark code.
- `seam_runtime/storage.py` - canonical SQLite persistence owner. New and
  historical stores enter through the central migration spine before the
  connection pool opens; current stores are validated rather than mutated.
- `seam_runtime/migrations.py` - ordered transactional schema/projection
  registries, read-only then exclusive-owner preflight, same-owner retained
  backups, separately committed integrity/foreign-key-gated steps, and explicit
  atomic recovery.
- `seam_runtime/retrieval_orchestrator/` - the single canonical multi-leg
  retrieval engine (planner, SQL/vector/graph/temporal adapters, and fixed
  rank-normalized merger) powering runtime `retrieve`, compatibility
  `search_ir`, CLI, MCP, REST, opaque `/v1`, dashboard, SDK, LoCoMo,
  self-improvement probes, and HS/1 MIRL queries. Promoted from `experimental/`
  in HISTORY#284 and made the sole live execution path in HISTORY#502.
- `seam_runtime/knowledge_graph.py` - canonical MIRL-to-graph projector, conservative 5W1H+Then lens, evidence-derived trust profiles/assertion gate, explicit migration-registry backfill, temporal/source supersession, graph query, node-page, and statistics logic. `SQLiteStore.persist_ir` maintains it automatically (HISTORY#403).
- `seam_runtime/graph_products.py` - G4 append-only, rebuildable entity/community summaries and multi-episode observations; every sentence retains exact supporting MIRL record and episode IDs, and latest reads are namespace/scope isolated.
- `seam_runtime/context_assembly.py` - G5 storage-agnostic deterministic context PACKs over facts, entities, episodes, summaries, and observations, with exact backtraces, trust/time gates, and grounded-fact non-displacement.
- `seam_runtime/lifecycle.py` - G6 append-only lifecycle operation/event ledger, scoped soft deletion, idempotent batch-ingest progress, and crash-recovery primitives.
- `seam_runtime/qualification.py` - R6/G7 versioned cross-agent envelopes, frozen native/event-only/paid-comparator manifests, concurrent recovery evidence, and fail-closed usefulness/latency/attribution scoring.
- `seam_runtime/reasoning_graph.py` - append-only public reasoning nodes, edges, state transitions, and bounded R2 retrieval-decision ledgers anchored to workspace runs, with scoped knowledge/MIRL evidence references and no automatic canonical promotion.
- `seam_runtime/reasoning_patterns.py` - R4 structural reasoning recipes distilled from verified accepted outcomes, same-boundary/freshness/provenance-gated retrieval, explicit use records, and verified success/failure feedback.
- `seam_runtime/reasoning_promotion.py` - R5 append-only proposals, separate human/policy reviews, exact-provenance eligibility, application fingerprints, and reversible audit; Store performs the only explicit approved-assertion MIRL transaction and never auto-applies.
- `seam_runtime/retrieval_policy.py` - versioned provider-free retrieval planner/fusion identities, controlled reason-code vocabulary, ordered content-free candidate-set fingerprints, and canonical MIRL evidence fingerprints shared by runtime and reasoning persistence.
- `seam_runtime/sdk.py` - stable local Python SDK over SEAM runtime, knowledge queries, run-scoped reasoning sessions, and atomic reasoned retrieval; CLI, REST, MCP, and framework packages can remain adapters rather than storage clients.
- `seam_runtime/public_api.py` - private implementation of the opaque public
  `/v1` agent-memory boundary. It maps SDK-only namespaces, validates public
  partitions, and returns user-facing text plus opaque identifiers without
  exporting MIRL, HS/1, PACK, storage, graph, or ranking structures. The
  Apache-2.0 client implementation lives separately in
  `BlackhatShiftey/Seam_Runtime/sdk`.
- `seam_runtime/workspace.py` - append-only structured workspace run/event schema, allowlisted telemetry sanitization, SSE framing/replay, and deterministic graph-activation projection. It explicitly excludes credentials, hidden chain-of-thought, and raw activation tensors.
- `seam_runtime/jspace.py` - optional J-lens capability boundary: unavailable/structured-only default, verified local Hugging Face Qwen adapter, and authenticated pinned remote worker. No model, lens, analyzer, download, or network dependency is enabled by default.
- `seam_runtime/improvement_experiments.py` - H2 immutable experiment definitions and append-only SHA-256 event chains, with bounded structured evidence and raw-content rejection.
- `seam_runtime/self_improve.py` + `tools/h2/improvement_loop.py` / `improvement_review.py` - graph-derived probes and bounded retrieval-policy candidates wired through durable baseline/candidate experiments, the strict multi-family proposal ratchet, explicit operator approval, applied-flag reconciliation, and revert. See `docs/IMPROVEMENT_EXPERIMENTS.md`.
- `tools/graph_retrieval_qualification.py` + `tools/graph_real_corpus_qualification.py` - synthetic scale/query-shape and pinned LoCoMo development/holdout qualification for G3 node-vector fusion and safe policy selection.
- `benchmarks/graph_reasoning_qualification.py` - provider-free real-runtime G7/R6 native-versus-event-only ablation, concurrent recovery probe, exact graph attribution, and matched Mem0/Zep paid-boundary plans.
- `seam_runtime/webui/` - the shipped single-file browser prototype served by
  the REST API: `dashboard.html`, `seam-api.js`, `tweaks-panel.jsx`,
  branding, and icons. `seam serve` and `seam webui` serve these at `/` on
  the same origin as the API; packaged with the wheel. It currently mixes live
  calls with simulated/browser-local behavior and is not an operator beta; see
  `docs/status/surfaces.md`.
- `seam_runtime/tui/` - the live terminal dashboard (`app.py` shell and `/`
  palette, `commands.py` catalog derived at runtime from the backend's own
  parser, `panels.py` worker-backed structured views, `settings_screen.py`,
  `brand.py`, `theme.tcss`). Presentation only: `dashboard.DashboardApp`
  remains the backend that executes commands. Reached by `seam dashboard`,
  `seam-dash`, and `seam-tui`, which all route through
  `dashboard.run_dashboard`. Superseded the in-`dashboard.py`
  `TextualDashboardApp` UI in HISTORY#537.
- `seam_runtime/dashboard.py` - `DashboardApp`, the surface-independent
  dashboard backend (command parser, command implementations, Rich snapshot
  and script modes, runtime access), plus the retired `TextualDashboardApp`
  UI class it used to own.
- `seam_runtime/config.py` - declarative registry of operator-settable
  environment variables behind the Settings tab, with masked secrets and
  provider keys. Persists to `~/.config/seam/seam.env` at 0600 and never to
  the repo `.env`; the process environment always wins over the file, and the
  file is treated as an untrusted source of names because operators hand-edit
  it (shell `export FOO=bar` lines included).
- `seam.py` - console entrypoint module for `seam` and `seam-benchmark`.
- `test_seam_all/test_seam.py` - primary regression suite. Local `test_seam_*.db`
  artifacts live in ignored `test_seam/` so root stays clean.
- `tests/docs/` - tracked testing documentation, including local artifact
  routing notes and test-run hygiene rules.

## Active Tooling

- `tools/history/` - canonical history, index, integrity, handoff-registry, and snapshot tools.
- `docs/README.md` - single canonical human-facing SEAM Wiki home; it routes to
  existing authorities without duplicating their volatile facts.
- `docs/REPORTS_AND_EVIDENCE.md` - canonical rule for filing human-readable
  reports and routing raw artifacts, current state, chronology, and archives.
- `tools/docs/verify_wiki.py` - fail-closed wiki coverage and rendered-link
  verifier. It uses the dev-only `markdown-it-py` dependency for CommonMark
  links, handles raw HTML anchors, rejects unsafe local paths and symlinks,
  validates every reachable page and the prospective report-registry contract,
  and can export the exact Git index for the commit hook. Working-tree mode
  runs in closeout, agent preflight, and required CI.
- `branding/kit/` - canonical Canticle/SEAM identity assets and tokens;
  `branding/canticle-cosmic-kit/` is its versioned UI expression layer with
  framework adapters and a local component gallery. `tools/branding/` verifies
  both contracts without changing a running surface.
- `docs/handoffs/INDEX.md` - canonical tracked handoff head and supersession chain; dated handoff documents are valid only when registered there.
- `docs/audits/INDEX.md` - canonical registry of recorded audits, newest first.
  `docs/audits/` is also the tracked home for all dated, human-readable SEAM
  reports. Whole-repo audits are a repeatable series produced by the
  `/deep-audit` skill and are meant to be diffed against each other; read the
  latest before concluding that a known defect is new. The registry's
  `policy_start` makes HISTORY/evidence-manifest enforcement prospective, so
  older evidence is preserved rather than silently rewritten. Reports cite
  repo files or hashed durable artifacts and never carry credentials or session
  URLs.
- `tools/git-hooks/` - canonical git hooks (`pre-commit`, `pre-push`) installed via `tools/git-hooks/install.sh`.
- `LICENSES/BUSL-1.1.txt` - controlling text and filled parameters for the SEAM
  Distributed Runtime, published under Business Source License 1.1 by Section 7A
  of `LICENSE`. Change Date is four years per published version; Change License
  is MPL 2.0. Membership in the Distributed Runtime is decided by publication
  plus a conspicuous per-file notice, never by path.
- `tools/release/` - secret and reserved-material push gate only.
  `verify_public_safe.py` inspects every object newly reachable by a push and
  blocks secret-shaped content and private paths; `public_manifest.py` supplies
  the path classification it depends on. This gate exists because a `seam.db`
  snapshot once leaked into another repository's history (HISTORY#344) and is
  retained for that reason alone, independent of any distribution split.
- SINGLE PACKAGE. `seam-runtime` (root `pyproject.toml`) is the only package
  definition: the full private runtime with readable MIRL and HS/1 source, used
  to operate the hosted service. The separate compiled `seam-self-host`
  distribution, the API-only `public_pkg/` shim, their build/verify tooling, and
  the boundary audit suite were removed after the retrofitted split proved to be
  the wrong shape. A public edition will be built separately, from the ground up,
  with separation as an architectural property rather than a gate bolted on
  afterward. `Private :: Do Not Upload` is retained as the tripwire against an
  accidental PyPI upload of a full-MIRL runtime.
- `.github/workflows/package-release.yml` - `workflow_dispatch`-only private
  release: a `build` job (version-matches-pyproject check, wheel+sdist,
  `twine check`, wheel smoke install, 7-day artifact) and a
  `private-github-release` job gated on the `private-package-release`
  environment that creates a GitHub Release in this private repo. It has **no
  PyPI job, no publish target selector, and no `id-token` permission**, so it
  cannot publish to an index. `Private :: Do Not Upload` (above) is the
  independent tripwire.
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
