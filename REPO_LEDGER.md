# SEAM Repo Ledger

Last updated: 2026-06-12

This ledger is the stable engineering memory for repo-level decisions only.
Detailed session history, milestones, and plan transitions now live in `HISTORY.md`
and `HISTORY_INDEX.md`.

## Startup Read Order

1. `PROJECT_STATUS.md` (current state)
2. `AGENTS.md` (cross-agent protocol)
3. `HISTORY_INDEX.md` (history map)
4. `HISTORY.md` only by surgical read using indexed line/byte ranges

## Project Identity

- `SEAM`: runtime/tool identity
- `MIRL`: canonical memory IR
- `PACK`: derived prompt-time context representation
- `SEAM-LX/1`: exact machine-text envelope for lossless workflows
- `SEAM-HS/1`: lossless PNG-backed Holographic Surface for visual memory snapshots

## Stable Decisions

- **The SEAM spec is the governing contract.** `SEAM_SPEC_V0.1.md` (the four-layer
  RAW/IR/PACK/LENS model, the north star "maximum durable intelligence per token",
  the loss model RAW=phrasing/IR=meaning/PACK=utility, the NL<->IR<->PACK<->NL
  translation directions, the symbol-table improvement loop, and the compression
  metrics `cr/rr/sr/pr/tr/qr` with the §24 "denser only when recovery is proven"
  promotion rule) together with `docs/MIRL_V1.md` (the Readable Lossless
  Compression Contract, MIRL record kinds/fields, RC/1, HS/1, the PACK
  Exact/Context/Narrative contracts) define what SEAM IS. Every change to SEAM
  product behavior is measured against them. Agents MUST read the spec before
  redesigning, "improving", or declaring a component broken (AGENTS.md Session
  Start item 6). A component is only "broken" if it fails the contract it is
  actually supposed to satisfy — e.g. RC/1's contract is lossless + directly
  queryable + exact rebuild (NOT token reduction; token reduction lives in PACK,
  the symbol loop, and the Track J codec); the former overfit `compile_nl` stub
  genuinely violated the §3.2 compiler responsibilities + §8 recoverable-meaning
  contract (fixed by the HISTORY#308 deterministic floor and unified into one
  faithful pipeline at #311; the rich S-P-O extractor is Stage 4). New fidelity
  or metric harnesses align to the spec's own metrics (§22/§24), not invented
  ad-hoc properties. This decision exists because the spec was historically
  absent from the mandatory read order, which let implementations drift from the
  design (the overfit `compile_nl` stub being the clearest case).
- This GitHub repo is the private source-of-truth home for SEAM runtime,
  tooling, docs, tests, and repo-owned fixtures. A separate repo will hold
  user-file surfaces or user-facing file sets when that workflow is created.
- SEAM is proprietary source-available software if any repo or artifact is
  later made public. Public repository visibility does not grant open-source
  rights; commercial, hosted, embedded, derivative, redistribution, or
  closed-source use is available only with separate written permission through
  a commercial license.
  The controlling files are `LICENSE` and `NOTICE`; `COMMERCIAL_LICENSE.md`
  is the plain-language commercial-use boundary.
- SEAM accepts contributions only under a contributor grant that lets the
  project owner keep developing, sublicensing, relicensing, and commercially
  licensing SEAM without later contributor permission. The contributor-facing
  summary lives in `CONTRIBUTING.md`.
- Security-sensitive reports should be handled privately through `SECURITY.md`;
  do not disclose private data, credential material, customer data, or exploit
  details in public issues.
- `docs/PROTECTION_MODEL.md` documents the public/private repo split and must
  not be added to the mandatory startup read list unless the task touches
  licensing, contribution policy, repo protection, or public/private separation.
- Protection-only changes must not silently alter runtime behavior, package
  metadata, CLI commands, installer behavior, dashboard behavior, API behavior,
  benchmark behavior, or history tooling behavior.
- SQLite is canonical source of truth.
- Vector stores (SQLite vector index, Chroma, PgVector) are derived retrieval layers. The SQLite vector adapter is the DEFAULT backend; `chromadb` and `psycopg` (pgvector) are OPTIONAL extras (`seam[chroma]`, `seam[pgvector]`), never core dependencies. All Chroma imports are lazy (`ChromaSemanticAdapter._client` raises a clear error if chromadb is absent). chromadb 1.0.0-1.5.9 (the whole current 1.x line) carries an UNPATCHED critical advisory GHSA-f4j7-r4q5-qw2c (pre-auth code injection in the Chroma SERVER); SEAM uses only the embedded `PersistentClient` so the server/auth surface is not reachable, but chromadb is kept OPT-IN ONLY: not in core `dependencies`, not in `requirements.txt` (installer/bootstrap path), and not in `all-extras` - only in the explicit `chroma` extra. Do not reintroduce it to any default/convenience path (guarded by `tests/audit/test_chroma_optional.py`).
- Document ingest status is canonical SQLite metadata. Source refs, source hashes, extraction status, index status, and deletion state belong in `document_status`, not only in derived vector stores.
- Agent-facing retrieval should use progressive disclosure where possible: compact search/index results first, then full MIRL records by selected IDs.
- Default agent RAG should prefer `mix` retrieval only after benchmark validation; the supported retrieval modes are `vector`, `graph`, `hybrid`, and `mix`.
- Agent ecosystem integrations should be thin wrappers over SEAM CLI/REST/MCP surfaces. Do not rewrite the Python runtime into Node just to fit Claude Code-style plugin ecosystems.
- Standard MCP stdio is the canonical agent-tool protocol for Gemini, Claude,
  Cursor, OpenCode, and future MCP clients: use `seam mcp stdio` or `seam-mcp`
  for JSON-RPC MCP discovery/calls. `seam mcp serve` remains only as the legacy
  JSON-lines bridge for older local wrappers.
- Agent clients that need the real pgvector adapter should launch MCP with
  `--ensure-pgvector`. That path starts the repo Docker Compose `pgvector`
  service, waits for container `seam-pgvector`, sets `SEAM_PGVECTOR_DSN` only
  in the MCP server process, and reads credentials only from ignored local env
  files such as `SEAM_LOCAL_ENV` or `~/OneDrive/Documents/SEAM/local/.env`.
- Lossless claims require exact reconstruction and integrity checks.
- SEAM compression must produce directly readable AI-native machine language as the primary artifact; opaque byte compression is only an optional reconstruction/integrity backing layer.
- A compressed SEAM artifact is not complete unless SEAM can answer detail questions from the compressed language without restoring the original source.
- Holographic surfaces are queryable visual containers for embedded MIRL or `SEAM-RC/1`; they are not a replacement for SQLite canonical truth and are not a claim of free compression.
- `seam surface compile` is the default source-to-surface operator flow: compile source text into MIRL, then encode MIRL into `SEAM-HS/1` with `rgb24` unless a denser mode is explicitly requested.
- Benchmark claims must be auditable (bundle hash, case hashes, fixture hashes, git SHA), diffed against a prior run, pass the benchmark gate, and stay separated from publish-only holdout runs.
- External memory benchmark claims require a non-stub judge plus passing BIL-2
  bundle verification before `validate_publication_readiness` can return
  publication-ready. Stub judge output is smoke-only even when it can be sealed
  with an explicit test override.
- GitHub PRs must keep no-paid benchmark integrity visible: CI runs a LoCoMo
  quickstart smoke with the stub judge, seals it as BIL-2 with the explicit
  stub override, verifies the bundle, and uploads the result/bundle/verify
  artifacts. CI also runs a real Chroma smoke through `chromadb`, `git diff
  --check`, and a non-printing secret/session URL scan. Paid answerer, judge,
  decomposer, or full LoCoMo runs remain operator-gated and must not be added
  to default PR CI.
- The self-improvement loop's paid judged validation tier
  (`benchmarks/external/locomo/judged_scorer.py` + `tools/h2/paid_validation.py`)
  is reachable ONLY via `seam improve validate --confirm-paid`. Without
  `--confirm-paid` the command is a zero-cost dry run (case/call-count estimate;
  no client constructed, no ingest). The judged scorer must never be added to
  the always-on improvement loop's scorer list, never auto-run by any agent, and
  every execution requires fresh explicit operator confirmation. It validates on
  the HOLDOUT split by default; the loop itself tunes on dev only and must never
  tune on holdout.
- GitHub `main` is protected by repository ruleset `Protect main (PR +
  hygiene gates)`: no bypass actors, no deletion, no non-fast-forward update,
  pull request required, and `repo-hygiene`, `chroma-real-smoke`, and
  `locomo-quickstart-bil2` required with strict latest-code status checks.
  Do not reintroduce direct-push bypass except as a time-boxed emergency
  with a follow-up HISTORY entry.
- `AGENTS.md` contains the cross-agent GitHub PR workflow: work through
  branches and draft PRs, isolate unrelated dirty files, keep PR bodies current,
  distinguish required checks from advisory matrix failures, and resolve stale
  PRs/branches as merged, closed, active, or concretely blocked instead of
  letting them accumulate.
- Benchmark evidence proves SEAM value but never expands license rights; hosted,
  SaaS, commercial, embedded, redistribution, customer-deployment, or
  closed-source use still requires a separate written commercial license.
- Compatibility CLI aliases are acceptable during naming transitions.
- Agent continuity is protocol-driven (`AGENTS.md`), not model-specific duplicate docs.
- Linux install has two supported flows: default `install_seam_linux.sh` creates
  global user command shims and persistent runtime state; `install_seam_linux.sh --dev`
  creates/reuses the repo-local Python `.venv`, handles the external-drive
  `lib64` venv fallback, installs Python dev dependencies, runs SEAM protocol
  verification, and deliberately leaves `experimental/webui/` untouched.
- Cross-file duplication is disallowed; use pointer cards (`see HISTORY#NNN`).
- Tracked testing documentation belongs under `tests/docs/`. Disposable local
  test outputs belong under ignored `test_seam/<area>/` subdirectories
  (`test_seam/pgvector/` for `test_pgvector_*` artifacts). Do not leave ad-hoc
  test notes, `Test*` scratch files, or generated `test_*` artifacts in the
  repo root.

## AI-Native Compression Policy

- The compressed language is the working document for AI question answering.
- Direct readability is mandatory for documents, text, images, audio, and video: quotes, table cells, OCR spans, image regions, timestamps, transcript spans, and provenance must be represented in machine-readable records.
- Opaque payload formats such as SEAM-LX/1 may be retained for exact rebuilds and hash checks, but they must not be the only artifact used for semantic read/query workflows.
- Future compression interpreters and codecs must optimize intelligence per token while preserving exact detail access through MIRL or a successor SEAM machine language.
- SEAM-HS/1 may carry MIRL, RC/1, LX/1, or raw bytes in lossless PNG pixels. MIRL and RC/1 payloads are directly queryable from the surface; LX/1 payloads are verify/decode only until converted into a readable payload.
- The planned surface library stores `.seam.png` artifacts as addressable visual memory surfaces with SQLite metadata, hashes, verification state, and lookup fields. Queries should read embedded MIRL/RC payloads directly from the lossless image bytes in memory; PACK remains derived prompt-time context and must not become the raw image store.
- The private runtime repo stores source and metadata code for surface-library
  adapters, not generated operator/user `.seam.png` artifacts by default.
  Generated surface files stay operator-controlled unless explicitly promoted
  as repo-owned fixtures or documentation assets.

## Handoff Policy

- Default: record state via `HISTORY.md` entries + `HISTORY_INDEX.md`.
- Session close writes one validated snapshot in `.seam/snapshots/`.
- `HISTORY_INDEX.md` and snapshots are derived artifacts; `HISTORY.md` is authoritative.
- The `handoff/archive` branch is reserved for PDF and handoff artifact publication, not primary runtime/source work.

## Temporal Continuity Policy

- Every material repo change must produce an append-only `HISTORY.md` entry, rebuilt `HISTORY_INDEX.md`, verified integrity, and one validated snapshot.
- History entries must preserve the temporal chain: previous state, new state, `supersedes` link when applicable, successes, failures, skipped verification, changed files, and unresolved next steps.
- Stable repo facts live here in `REPO_LEDGER.md`; detailed session chronology lives in `HISTORY.md`. Do not duplicate long prose across both files.
- Agents must update this ledger when changing stable repo policy, architecture, active/archive routing, runtime safety rules, durable operator workflows, benchmark publication rules, or cross-agent protocol.
- Agents must update `PROJECT_STATUS.md` when the current operating state or active focus changes.
- Model-specific guides such as `CLAUDE.md`, `GEMINI.md`, and `ANTIGRAVITY.md` must route back to `AGENTS.md` and must not create a competing protocol.
- Cross-agent commit gate: `tools/git-hooks/pre-commit` is the canonical pre-commit hook for this repo. It runs for every `git commit` regardless of who initiated it (Claude, Codex, Gemini, Aider, Cursor, OpenCode, human operator) because git itself enforces `.git/hooks/pre-commit`. The hook scope-blocks `.claude/`, `.opencode/`, `.agents/`, and `opencode.jsonc?` paths from staging, then runs `verify_integrity`, `verify_routing`, `verify_continuity`, and `verify_streams` against the SEAM history + streams protocols; non-zero gate exits non-zero and blocks the commit. Operators install the hook into `.git/hooks/pre-commit` with `bash tools/git-hooks/install.sh`, which symlinks where supported and falls back to a copy with a `CANONICAL_SHA` marker on filesystems that do not support symlinks (exFAT, FAT32, some Windows configurations). `seam doctor` reports the gate state under `commit_gate` and the streams substrate state under `streams`, and tells the operator how to repair drift.
- Recorded-fact discrepancy audit is part of `verify_continuity`. Checkable facts written into active docs or the latest history entry must include enough scope to verify them later. The initial typed checks cover scoped pytest count claims, ambiguous hard-coded test totals, current handoff pointers, latest history refs that point at missing files, and same-scope test-count precedence drops (for example a later `150 passed` claim after an earlier same-scope `180 passed`). Future fact types should be added as extractors under `tools/history/recorded_fact_audit.py` so continuity catches disappearing data instead of relying on manual review.
- Context Streams substrate (Track H1 implemented and measured): `tools/streams/` provides generic stream tooling that generalizes the single-stream history protocol into a multi-stream substrate. Root `HISTORY.md` + `HISTORY_INDEX.md` remain canonical; `.seam/streams/history/log.md` + `index.md` are byte-equivalent derived mirrors via `tools/streams/history_adapter.py`. The `roadmap` stream is populated for every track in `ROADMAP.md` via `seam:item` markers (34 items as of HISTORY#171). New `experience` stream lives entirely under `.seam/streams/`. `roadmap/state.md` is the compact agent-facing status view; `.seam/cross_index.md` is the derived global temporal join with two-tier indexing (200-event hot zone plus `.seam/cross_index_archive/` chunks). `tools/streams/build_context_pack.py` is the stream-aware pack builder; for `--stream history` it delegates to the canonical history pack so output is byte-equivalent. `tools/streams/bloat_report.py` measures the H1 reduction under the canonical cl100k_base tokenizer: roadmap status reads drop 88.4 percent (ROADMAP.md to state.md), history map reads drop 89.5 percent (HISTORY.md to HISTORY_INDEX.md), and cross-stream recent reads drop 88.6 percent (HISTORY.md plus ROADMAP.md to cross_index.md). Earlier-cited 93.5/90.5/91.0 numbers used a word-count heuristic that overstated savings; see HISTORY#216 for the tokenizer unification. The `verify_streams` gate enforces parseability, history-mirror byte-equivalence, per-stream index consistency, and cross-index presence; it runs in the canonical pre-commit hook and the Claude preflight as a fourth gate. Path canonicality flip for `history` (root → `.seam/streams/history/`) is explicitly deferred to a separate later HISTORY entry per `docs/roadmap/CONTEXT_STREAMS.md` §9. AGENTS.md "Context Loop" describes the bounded session-start read protocol that uses `roadmap/state.md` instead of full `ROADMAP.md` and `cross_index.md` for cross-stream temporal queries.
- Claude Code defense-in-depth: a per-operator-local `.claude/settings.json` may wire `tools/claude/preflight_protocol.sh` (PreToolUse Bash hook) and `tools/claude/session_start_brief.sh` (SessionStart hook) so Claude Code reproduces the same verify chain before invoking git and prints the AGENTS.md read order on session start. `.claude/` stays gitignored and is rejected by the canonical pre-commit hook; each Claude Code operator wires their own machine. The Claude hook is belt-and-suspenders to the canonical git hook; the git hook is the protocol enforcement, the Claude hook is the early warning. Equivalent wiring for Codex, Gemini, and other agents is open follow-up work tracked in HISTORY; the canonical git hook covers them today even without per-agent wiring.
- DeepSeek parallel audit execution is documented in `docs/SOP_DEEPSEEK_PARALLEL_AUDIT_EXECUTION.md` (see HISTORY#205). That SOP is the durable handoff for asking DeepSeek to use its own parallel workers for SEAM debugging, systematic audit, verification, adversarial review, and merge-request preparation. Codex review/merge handling remains local and non-agentic unless the operator explicitly changes that constraint.
- Advisor/executor execution is documented in `docs/SOP_ADVISOR_EXECUTOR_LOOP.md`. Codex or true Claude Opus may act as Advisor for strategy, planning, review, and final approval; `claude-ds`/DeepSeek acts as bounded Executor for Advisor-authored task packets, must escalate uncertainty with `ADVISOR_ESCALATION`, and does not own commits, pushes, history closeout, architecture, or scope expansion unless explicitly delegated.

## Context Budget Policy

- Full continuity is preserved in append-only history, but normal startup must not load full history.
- `HISTORY_INDEX.md` is the compact route map; `.seam/snapshots/` are bounded handoff packs; `tools.history.build_context_pack` builds topic/latest/supersedes packs under an explicit token budget.
- `tools.history.verify_continuity` is the quality gate for history/index/snapshot freshness, supersedes validity, and session-link/secret hygiene.
- Prefer task-specific context packs over broad scans. If a pack is insufficient, add targeted topics, explicit entries, or refs instead of reading all of `HISTORY.md`.

## Data Routing Policy

- `tools/history/routing_manifest.json` defines logical branches for AI-searchable history such as `maintenance/docker`, `maintenance/pgvector`, `protocol/context`, and `protocol/security`.
- Route classifications are mutable, but route mutations must remain reconstructable through `HISTORY.md`, manifest lifecycle fields, and stable topic ledgers under `docs/ledgers/`.
- `tools.history.verify_routing` checks route tree integrity, parent links, route lifecycle fields, ledger paths, and referenced history entries.
- Deleting a classification means removing it from active use through `status=retired` or `status=moved`; the audit trail must remain.

## Documentation Separation Policy

- Active operator and engineering docs live in `docs/` and are indexed by `docs/README.md`.
- Inactive docs, old handoffs, superseded setup notes, and historical coding artifacts live under `docs/archive/`.
- Archived docs are traceability records, not current instructions.
- When old prose is useful, rewrite the current part into an active doc and point to `HISTORY#NNN`; do not duplicate stale context across active docs.

## Code Separation Policy

- Active runtime code lives in `seam_runtime/` and `seam.py`.
- Active operator/dev tooling lives in `tools/`, `scripts/`, and `installers/`.
- `experimental/` is active prototype code: less stable than runtime code, but still importable and testable.
- Inactive or retired code lives under `archive/code/` and must not be imported, packaged, or used as current behavior.
- Generated build copies live in ignored paths (`build/` or `archive/code/generated-build*/`) and should not guide implementation decisions.
- The current code map is `docs/CODE_LAYOUT.md`.

## Runtime Service Safety Policy

- External services for real-adapter tests (for example Docker pgvector) must be started only for the active test window.
- Every service started for a test run must be explicitly stopped and removed at the end of that run.
- Prefer non-conflicting ports for temporary services and verify they are released after cleanup.
- Keep resource monitoring lightweight during runs (snapshot checks or low-frequency polling) to avoid adding load.
- If a run fails or exits early, perform the same shutdown/cleanup sequence before continuing.
- Default guardrail for local runs: warn around `82%` RAM usage and treat `90%` RAM as hard limit unless explicitly overridden for a task.
- Use `scripts/run_guarded.ps1` for heavy commands so CPU/RAM/disk are watched during execution.
- Use `scripts/run_real_adapters_guarded.ps1` for end-to-end real-adapter validation; it starts pgvector, runs guarded checks, and cleans up containers/artifacts on exit.
- Archive benchmarks with `scripts/store_benchmark.ps1` to keep publication-required hashes and reproducibility metadata in Documents; outputs are sequence+time indexed and blocked from writing inside the git repo by default.

## REST API Policy

- The REST API is optional and installed with the `server` extra.
- `seam serve` and `seam-server` run the FastAPI/Uvicorn surface against the configured SQLite database.
- Protected endpoints require `Authorization: Bearer <token>` when `SEAM_API_TOKEN` is set; leave that variable unset only for trusted local development.
- `/health` is unauthenticated for local service checks but still participates in the same rate limiter.
- Rate limiting is configured by `SEAM_API_RATE_LIMIT_PER_MINUTE` or `SEAM_API_RATE_LIMIT`; `0` or unset disables the limiter.
- Local browser dashboard origins `http://127.0.0.1:5173` and `http://localhost:5173` are allowed by default through CORS so the Vite WebUI can call the API during development. Override with `SEAM_API_CORS_ORIGINS` as a comma-separated list, or set it to `0`, `false`, `off`, or `none` to disable CORS.
- API handlers must use existing `SeamRuntime` behavior and public report `to_dict()` methods rather than inventing parallel response fields.
- POST/PUT/PATCH bodies are bounded by `SEAM_API_MAX_BODY_BYTES` (default `5000000`; `0` disables). Oversized requests return HTTP 413 before endpoint handlers run.
- Authenticated REST servers refuse non-loopback binds such as `0.0.0.0` unless the operator intentionally sets `SEAM_API_ALLOW_INSECURE_REMOTE=1` or places the API behind a TLS terminator. Bearer-token deployments should prefer loopback plus TLS reverse proxy for remote access.
- The built-in rate limiter is process-local. If `SEAM_API_RATE_LIMIT_PER_MINUTE` is enabled, `seam serve --workers` greater than 1 is refused unless `SEAM_API_ALLOW_PROCESS_LOCAL_RATE_LIMIT=1` is set after an external shared limiter is in front. `SEAM_API_RATE_LIMIT_MAX_KEYS` bounds tracked client keys.
- The `/chat` endpoint's outbound provider call is SSRF-guarded by a host allowlist: the caller-supplied `base_url` host must be a built-in provider (`_BUILTIN_CHAT_HOSTS`) or loopback (local Ollama); arbitrary hosts are rejected. Operators permit additional custom/self-hosted providers via `SEAM_CHAT_ALLOWED_HOSTS` (comma-separated) — an operator-set knob, never caller-set. The allowlist closes DNS-rebinding by construction; a resolved-IP range check (private/link-local/reserved/multicast/unspecified rejected, loopback exempt) is kept as defense-in-depth, and the outbound opener refuses 3xx redirects so a validated host cannot bounce to an internal address.

## Benchmark Publication Policy

Holographic Surface claims must report `surface_exact_rate`, payload hash match
rate, direct query exactness, stored surface lookup, stored surface query after
original-output deletion, repair success, repair query exactness, and the PNG
mode (`bw1`, `rgb`/`rgb24`, explicit `rgba32`, or explicit `rgba64`).

Published benchmark statements must include:

- command used
- bundle hash
- per-case hashes
- fixture hashes
- tokenizer/dependency state
- git SHA
- benchmark diff output comparing the claim run against its baseline
- benchmark gate output from `seam benchmark gate <bundle> [--baseline <run-a>]`
- holdout result bundle when the statement is an external or publication claim

Holdout benchmark fixtures live under `benchmarks/fixtures/holdout/` and are ignored by git by default. They must be run only with `seam benchmark run --holdout --confirm-holdout`, and default holdout result bundles are written separately under `benchmarks/runs/holdout/`.

## Benchmark Dataset Integrity Policy

The LoCoMo dataset was once lost because it lived only on the near-full root volume (`/`). To prevent silent recurrence, benchmark source datasets follow defense-in-depth:

- The canonical LoCoMo dataset is committed in-repo at `benchmarks/external/locomo/data/locomo10.json` (so it lives on T7 and offsite via the private GitHub repo), never only on the root volume.
- `benchmarks/external/locomo/data/locomo10.manifest.json` pins the source URL, SHA256, byte size, and sample/QA/category counts. Treat the SHA256 as the integrity authority — LoCoMo releases reuse `sample_id` labels across different content, so verify by hash, not by label.
- `python -m tools.benchmarks.restore_locomo` restores and SHA-verifies the dataset from, in priority order: the in-repo copy → the T7 durable copy (`.dataset_store/locomo/`) → the canonical network source. Use `--verify` before any run, `--ensure` to repair all standard locations, `--to <path>` for a specific target.
- The no-paid LoCoMo path (`--answerer none --judge none`) runs self-contained on the local `SQLiteVectorAdapter` with local `BAAI/bge-small-en-v1.5` embeddings; it does NOT require the Docker pgvector service. SQLite-vector and pgvector are score-equivalent for this workload (verified: both reproduce `context_recall_mean=0.528308`).
- `--keep-db` reuses per-scope SQLite DBs by `sample_id`; never reuse DBs ingested from a different dataset release on the same `--db-path`, or retrieval silently reads the wrong conversation. Use a fresh `--db-path` when the dataset version changes.
