# SEAM Improvement Roadmap & SOP Blueprint

**Last updated:** 2026-05-08
**Status:** Active planning document. This is the living roadmap for SEAM development beyond the stable v1 core.

## 2026-05-01 Functional Visual Memory Target

The next roadmap target is making the full SEAM visual-memory loop functional:

```
documents -> directly readable machine language -> SEAM-HS/1 image surfaces -> stored surface library -> direct image-surface query/context
```

This target is not just "save a screenshot." The image is the storage envelope
for SEAM machine language. The useful data inside the image must stay readable
by SEAM without restoring the original document, running OCR on the rendered
image, or importing the payload into SQLite first.

Required behavior:

- Document compression emits directly readable MIRL or `SEAM-RC/1` records with
  quote spans, headings, table cells, entities, claims, references, source
  hashes, and provenance.
- Surface packing stores that machine-language payload in a lossless
  `SEAM-HS/1` PNG using `rgb24` by default or explicit `rgba32` / `rgba64`
  for higher channel density.
- Surface storage keeps the generated `.seam.png` artifacts addressable as a
  surface library, with SQLite metadata for artifact path, payload format,
  PNG mode, source hash, payload hash, verification status, and import/query
  status.
- Direct read must decode the PNG pixel payload in memory, verify the payload
  hash, and answer query/search/context requests from the embedded MIRL or
  `SEAM-RC/1` records without rebuilding the original document.
- SQLite remains canonical for active imported memory. Stored surfaces are
  portable, immutable, directly readable artifacts; PACK remains derived
  prompt-time context, not the owner of raw image bytes.
- Benchmark proof must cover document-to-machine-language exactness,
  machine-language-to-surface hash preservation, stored-surface lookup, and
  direct query exactness, including stored query after original-output deletion
  and repaired redundant-copy query.

SOP:

1. Build a document compiler path that converts source documents into
   directly readable MIRL/RC records before any surface packing.
2. Add a surface library/store command that writes `.seam.png` files under a
   controlled artifact directory and records metadata in SQLite.
   - 2026-05-07 status: landed on `main`. `surface store|list|show|repair`,
     `compile --store`, `encode --store`, stable `hs:<hash>` IDs, redundant
     file-backed copies, and stored-ID verify/query/search/context/decode/import
     are available from the source-of-truth branch.
3. Add surface lookup commands for list, verify, query, search, context, import,
   and repair/rebuild-from-source when source material is still available.
4. Keep raw original documents optional and operator-controlled. They are
   useful for audits and rebuilds, but they must not be required for direct
   query once a verified MIRL/RC surface exists.
5. Add benchmark fixtures that prove exact answers can be read from the stored
   image surface itself.
   - 2026-05-07 status: landed on `main`. The release-blocking surface family
     includes stored lookup, stored query after original-output deletion,
     redundant-copy repair, and repaired-copy query rates at 100%.

Next resume target:

- Continue with the document compiler path for directly readable MIRL/RC records
  from richer source documents, then keep proving that direct query/context can
  read from stored HS/1 image surfaces without requiring the original document.
- Start the Agent Compiler workstream in `docs/roadmap/AGENT_COMPILER.md` when
  working on Claude/Codex/Gemini/Cursor/Aider operating skills. The goal is not
  one-off prompt patches; it is generated, benchmarked, auditable agent adapters
  from canonical SEAM protocol.

## 2026-04-30 Holographic Surface Integration

Holographic Surface is now a roadmap track for directly readable visual memory
snapshots:

- `SEAM-HS/1` is a lossless PNG-backed surface that stores MIRL, `SEAM-RC/1`,
  `SEAM-LX/1`, or raw bytes in pixel data.
- The surface stores machine language, not pictures of text. Direct read means
  SEAM reads pixel bytes into the embedded MIRL/RC payload in memory, then runs
  the normal parser, query, search, or context path.
- No OCR, natural-language recompilation, or SQLite import is required for
  direct surface query/context workflows.
- v1 supports `bw1` proof mode, `rgb24`/`rgb` default density mode, explicit
  `rgba32` high-density mode, and explicit 16-bit `rgba64`. JPEG and other
  lossy formats are rejected for exact memory.
- The automatic operator flow is `seam surface compile <source> --output
  <file.seam.png>`: compile source text into MIRL, then encode the MIRL bytes
  into a PNG surface using `rgb24` unless a denser mode is requested.
- The benchmark gate is `surface_exact_rate == 1.0`,
  `payload_hash_match_rate == 1.0`, direct query exactness, stored lookup,
  stored query after original-output deletion, repair success, and repaired-copy
  query exactness all at 100%.
- The claim is higher effective intelligence density for already-compiled SEAM
  machine language, not impossible free compression.

SOP:

1. Use `seam surface compile <source> --output <file.seam.png> --mode rgb24`
   for source text that should become MIRL-backed surface memory.
2. Encode existing RC/1 or MIRL with `seam surface encode <input> --output <file.seam.png> --mode rgb24`.
3. Use `--mode rgba32` only for explicit higher channel density; it stores 4
   bytes per pixel but alpha channels are easier for image tooling to mutate.
4. Use `--mode rgba64` only when 16-bit RGBA density is required; it stores 8
   bytes per pixel and should be verified after any image-tooling touch.
5. Verify with `seam surface verify <file.seam.png>`.
6. Query without import using `seam surface query`, `seam surface search`, or
   `seam surface context`.
7. Import only when the snapshot should become active SQLite memory.
8. Gate changes with `seam benchmark run surface`.

## 2026-04-28 Competitive Integration Update

The current competitive plan moves README/install/RAG work ahead of older
presentation polish:

- Product-first README and private-repo one-line install commands are now part
  of the active install track.
- RAG modes are `vector`, `graph`, `hybrid`, and `mix`, with `mix` intended as
  the agent default after benchmark validation.
- Progressive disclosure is a first-class agent memory pattern:
  `seam memory search` for compact results, then `seam memory get` for selected
  full records.
- Agent ecosystem compatibility should use thin CLI/REST/stdio wrappers over
  the Python runtime, not a runtime rewrite.
- LightRAG-style document status, graph expansion, vector cache/stale metadata,
  and future reranking belong in the RAG/scalability track.

---

## Track A0 — True Interactive TUI (foundation for all UI work)

### A0: Migrate Dashboard to Textual — Live Panels, In-Place Input, Scrollable Boxes

<!-- seam:item
id: roadmap:track:A0
status: done
status-since: 2026-04-21
status-by: history:063
supersedes: none
topics: dashboard, tui, textual
priority: 3
phase: 1
-->

**What:** Replace the current Rich-based re-render loop with a proper interactive TUI using **Textual**. The dashboard becomes a persistent session: input is handled at the bottom of the screen in-place, panels update reactively without flashing or reprinting, and every data panel is independently scrollable within its bordered box. A `seam-dash` CLI entrypoint launches it directly.

**Why first:** Every other Track A item (animations, graphs, chat tab, presentation mode) is easier and cleaner to build on a proper TUI framework than on top of a re-render loop. This is the foundation.

**How:**
> Implementation note: superseded by Textual migration; see HISTORY#108.
- Migrate from `Rich.Live` full-screen re-render → **Textual** widgets with reactive data bindings
- Each panel becomes a Textual `DataTable`, `ListView`, or custom `ScrollView` widget — independently scrollable
- Input bar at the bottom is a Textual `Input` widget; on submit it runs the existing `execute()` logic and updates only the affected panel
- Add `seam-dash = "seam_runtime.dashboard:main"` to `[project.scripts]` in `pyproject.toml`
- Keep `seam dashboard` as an alias; keep `--snapshot` (headless) mode working throughout

**Panels that get independent scroll:**
- Memory Records
- Search / Retrieval Results
- Benchmark Results
- Runtime Log / Event stream
- Chat (when Track A5 lands)

**SOP:**
1. Add `textual>=0.50` as optional extra (`seam-runtime[dash]`) or promote to base if dashboard is a primary interface
2. Port existing panels to Textual widgets one at a time — keep snapshot fallback working at every step
3. Wire `Input` widget at bottom; results update the relevant panel reactively
4. Add `seam-dash` console entrypoint to `pyproject.toml`
5. Test: `--snapshot` headless export must still pass; add ≥3 Textual widget tests
6. Gate: no full-screen flash on any input; all panels scroll independently; works on Windows terminal and Linux/WSL2

---

## Track A — Dashboard & UI Enhancement
History pointer: see `HISTORY#047` (interactive TUI baseline) and `HISTORY#024` (dashboard review stabilization).

### A-Web: IDE-Like Browser Dashboard / REST API GUI

<!-- seam:item
id: roadmap:track:A-Web
status: in-progress
status-since: 2026-05-10
status-by: history:163
supersedes: none
topics: dashboard, webui, command
priority: 0
phase: 1
-->

**What:** Make the browser dashboard feel like an IDE/operator workspace, using
the prototype in `experimental/webui/` as the visual target. The shell should
keep an activity bar, explorer/files view, tabbed main editor/workspace, agent
pane, terminal/command surface, memory view, ingest view, benchmark view,
settings, and status bar.

**Role:** This is the future REST API GUI, not a replacement for the stable
Textual terminal dashboard yet. Textual remains the terminal-first dashboard;
the web dashboard becomes the richer browser surface served by or alongside
`seam serve`.

**Current prototype:** `experimental/webui/seam-dashboard-prototype.html`
contains the IDE-like SEAM dashboard mockup and supporting assets. It currently
uses demo state and must be wired to real SEAM endpoints before runtime
promotion.

**SOP:**
1. Keep the prototype under `experimental/webui/` until it has real API wiring,
   local build/test commands, and no CDN/Babel runtime dependency.
2. Split the single-file prototype into a maintainable app shell, API client,
   state stores, panes, and shared visual tokens.
3. Wire first to existing REST endpoints: `/health`, `/stats`, `/compile`,
   `/search`, `/context`, `/persist`, and `/lossless-compress`.
4. Add backend endpoints only when the GUI needs behavior that the REST API
   cannot currently provide: ingest file, benchmark run/gate, surface
   list/show/query/repair, event logs, and model/chat routing.
5. Keep secrets local. API keys and bearer tokens must be entered through local
   environment/config surfaces and must not be committed.
6. Package only after verification proves browser UI state matches real SEAM
   runtime state.

**Gate:** `seam serve` or a dedicated `seam web` command can open the IDE-like
dashboard, connect to a local SEAM API, show real health/stats/search/context
data, run at least one compile-or-search workflow, and pass browser smoke tests
without breaking `seam dashboard`.

### A-CLI: First-Class Agent CLI

<!-- seam:item
id: roadmap:track:A-CLI
status: in-progress
status-since: 2026-05-07
status-by: history:137
supersedes: none
topics: command, chat, dashboard
priority: 0
phase: 1
-->

**What:** Turn `seam` into a CLI product in the same family as Gemini CLI,
Claude Code, and Codex CLI: an interactive shell that can remember, retrieve,
reason over local SEAM memory, call SEAM tools, and eventually route model
requests without losing the existing precise subcommand surface.

**Current status:** `seam shell` / `seam chat` is the first slice. It provides a
REPL-style memory shell with slash commands for remember, search, context,
stats, doctor, and exit. Natural text defaults to prompt-ready context
retrieval.

**SOP:**
1. Keep existing `seam <subcommand>` behavior stable for scripts.
2. Make `seam shell` the interactive operator entrypoint.
3. Preserve slash commands as first-class controls: `/remember`, `/search`,
   `/context`, `/stats`, `/doctor`, `/exit`, then add `/model`, `/tools`,
   `/surface`, `/benchmark`, and `/web`.
4. Add model routing only after local memory/tool execution is stable. Provider
   keys must stay in local env/config, never in repo files.
5. Add command history, session transcript persistence, explicit tool-call
   confirmation, and project context loading from `AGENTS.md`/status/history.
6. Reuse the same runtime and REST/MCP surfaces; do not fork SEAM behavior into
   a separate CLI-only runtime.

**Gate:** A user can run `seam shell`, ask or paste natural text, persist useful
memory, retrieve context, inspect stats/health, and exit cleanly. The scripted
path `seam shell --once ...` must remain testable in CI.

### A1: NL→MIRL Compilation Animation

<!-- seam:item
id: roadmap:track:A1
status: done
status-since: 2026-04-25
status-by: history:068
supersedes: none
topics: dashboard, animation, mirl
priority: 3
phase: 1
-->

**What:** When a user runs `compile <text>` in the dashboard, show a live animation of the compilation process — text being parsed, records appearing one by one with their type labels (ENT, CLM, REL, ACT, OBJ) before the final summary.

**How:**
> Implementation note: superseded by Textual migration; see HISTORY#108.
- Use Rich `Live` context manager in `dashboard.py`
- On compile, stream record creation events from `compile_nl` by yielding intermediate batches
- Each record appears with a typewriter-style pop: `[green]ENT[/green] ent:project:seam → "SEAM"`
- Final frame shows the full compiled batch summary

**SOP:**
1. Add a `compile_nl_streaming` variant or hook to `seam_runtime/nl.py` that yields records as they are produced
2. Wire the stream into `DashboardApp.execute` for the compile command
3. Render each yield step via `Rich.Live` with a short frame delay (50ms)
4. Write a `--snapshot` test that captures the final frame

**Gate:** Animation must not break `--snapshot` mode or scripted `run_script` execution.

---

### A2: Benchmark Progress Bar & Live Metrics

<!-- seam:item
id: roadmap:track:A2
status: planned
status-since: 2026-04-18
status-by: none
supersedes: none
topics: benchmark, dashboard, animation
priority: 1
phase: 1
-->

**What:** During `seam benchmark run all`, show a live progress bar with per-family status, current scores, and elapsed time — not just a final JSON dump.

**How:**
- Rich `Progress` with one task per benchmark family
- Live-update recall@k, token savings, and pass/fail as each case completes
- Final frame shows the summary table

**SOP:**
1. Add an optional `progress_callback` parameter to `run_benchmark_suite` in `benchmarks.py`
2. Wire it into the CLI and dashboard benchmark command
3. Dashboard: use `Rich.Live` wrapping a `Progress` + results table

**Gate:** Must not change the benchmark output bundle format or break `benchmark verify`.

---

### A3: Benchmark History Graphs (ASCII sparklines)

<!-- seam:item
id: roadmap:track:A3
status: planned
status-since: 2026-04-18
status-by: none
supersedes: none
topics: benchmark, dashboard, graph
priority: 1
phase: 1
-->

**What:** In the Benchmark tab, show a sparkline graph of recall@k and token savings across the last N stored runs, so you can see whether the system is improving or regressing over time.

**How:**
- Query `benchmark_runs` table from SQLite for last 10 runs
- Compute per-family summary metrics per run
- Render as ASCII sparklines using a lightweight library (`sparklines`, `plotext`, or hand-rolled)
- Show in the Benchmark tab's third panel column

**SOP:**
1. Add a `load_benchmark_history(limit)` helper to `storage.py`
2. Add `_build_benchmark_history_graph()` to `DashboardApp`
3. Swap it into the Benchmark tab layout alongside the existing summary table
4. Sparkline renders as a single Rich `Text` object — no external rendering dependency

**Gate:** Must work with zero runs (show empty state gracefully) and with 1+ runs.

---

### A4: Vector Space Visualization

<!-- seam:item
id: roadmap:track:A4
status: planned
status-since: 2026-04-18
status-by: none
supersedes: none
topics: vector, dashboard, graph
priority: 1
phase: 1
-->

**What:** A new `vectors` command in the dashboard (or a standalone `seam vectors` CLI command) that projects stored embeddings to 2D using UMAP or t-SNE and renders a scatter plot colored by record kind.

**Do we need a separate tool?** No — but it needs optional dependencies. The projection math (`umap-learn` or `scikit-learn` for t-SNE) is heavy. Keep it behind an optional extra (`seam-runtime[viz]`). The rendering can be ASCII (via `plotext`) in the terminal or HTML canvas via a web artifact.

**How:**
1. Add `viz` optional extra to `pyproject.toml`: `umap-learn>=0.5`, `plotext>=5.0`
2. Add `seam_runtime/viz.py`: load vectors from SQLite, run UMAP, return 2D coordinates + kind labels
3. Add `vectors` command to dashboard and CLI
4. Render: ASCII scatter via `plotext` for terminal; HTML canvas artifact for richer view

**SOP:**
1. Implement `viz.py` with graceful `ImportError` guard (same pattern as `rich` guard)
2. Add `vectors` command to `_build_command_parser` in `DashboardApp`
3. ASCII render first; HTML artifact as a follow-on
4. Test: mock the embedding data, assert 2D projection output shape

**Gate:** Must degrade gracefully if `umap-learn` is not installed — show a clear install hint.

---

### A5: Chat Tab with Claude Model

<!-- seam:item
id: roadmap:track:A5
status: done
status-since: 2026-04-25
status-by: history:074
supersedes: none
topics: dashboard, chat, command
priority: 3
phase: 1
-->

**What:** Add a `Chat` tab to the dashboard. The user types a message; SEAM retrieves relevant context from the DB; the context + message is sent to Claude API; the response appears in the result panel. The model can also invoke SEAM operations as tool calls.

**How:**
> Implementation note: superseded by Textual migration; see HISTORY#108.
- New tab: `runtime | benchmark | chat`
- Chat history stored in `DashboardApp` as a deque
- On each message: run `search_ir` + `pack_ir` to get context, send as system prompt to Claude
- Claude can call tools: `compile`, `search`, `context`, `stats`
- Response streamed into the result panel via Rich `Live`

**Required:** `anthropic` SDK installed. Add `chat` optional extra to `pyproject.toml`.

**SOP:**
1. Add `chat` optional extra: `anthropic>=0.40`
2. Add `_build_chat_context(query)` to `DashboardApp` — retrieves and packs relevant records
3. Add `ChatSession` dataclass: messages list, tool definitions
4. Add `chat` command to parser; wire into `execute()`
5. Define SEAM tools for Claude: `seam_search`, `seam_compile`, `seam_context`, `seam_stats`
6. Render streamed response using Rich `Live`
7. Add `Chat` tab to header tab switcher

**Gate:** Must not require `anthropic` for any non-chat operation. Chat tab shows "anthropic not installed — run pip install seam-runtime[chat]" if missing.

---

### A6: Dashboard as a Benchmarking Presentation Tool

<!-- seam:item
id: roadmap:track:A6
status: planned
status-since: 2026-04-18
status-by: none
supersedes: none
topics: dashboard, benchmark, animation
priority: 1
phase: 1
-->

**What:** A `--present` mode for the dashboard that locks into full-screen benchmark display — large metrics, color-coded pass/fail cells, animated score bars — suitable for showing SEAM benchmark results in a demo or presentation context.

**How:**
- `seam dashboard --present` launches in presentation mode
- Full terminal width used for benchmark summary table with large text
- Scores animate from 0 to actual value on load (progress bar fill)
- Auto-refreshes every 30s from the latest persisted run

**SOP:**
1. Add `--present` flag to the dashboard CLI parser
2. Add `run_presentation()` method to `DashboardApp`
3. Build a `_build_presentation_layout()` that uses Rich `Table` with larger cells and styled score columns
4. Auto-refresh: use `Rich.Live` with `refresh_per_second=0.033` (30s equivalent via manual control)

---

## Track B — Command Terminology & README Refinement
History pointer: see `HISTORY#002`, `HISTORY#024`, `HISTORY#033`.

### B1: Command Naming Audit

<!-- seam:item
id: roadmap:track:B1
status: planned
status-since: 2026-04-18
status-by: none
supersedes: none
topics: naming, alias, command
priority: 1
phase: 1
-->

**Current problems:**
- `compile-nl` / `compile-dsl` — "compile" is developer-speak for a memory tool
- `lossless-compress` / `compress-doc` — redundant aliases with inconsistent style
- `promote-symbols` — vague; users don't know what "promote" means here
- `rag-sync` / `rag-search` — internal jargon leaking into the surface
- `transpile` — very developer-specific
- `reconcile` — ambiguous to non-developers

**Proposed theme: "SEAM as a knowledge operating system"**

All commands should feel like natural operations on a memory system:

| Current | Proposed | Rationale |
|---|---|---|
| `compile-nl` | `remember` or `learn` | User is teaching SEAM something |
| `compile-dsl` | `script` | DSL is structured input — scripting feels right |
| `persist` | `store` | Plain English |
| `search` | `find` | Intuitive |
| `retrieve` | `fetch` | Consistent with find |
| `lossless-compress` | `compress` | Single clean verb |
| `lossless-decompress` | `restore` | Paired with compress |
| `promote-symbols` | `mint` | Symbols are being created/promoted into the system |
| `reconcile` | `sync` | Aligns state |
| `transpile` | `convert` | Plain English |
| `context` | keep | Already good |
| `pack` | keep | Already good |
| `doctor` | keep | Already great |
| `dashboard` | keep | Already great |

**SOP:**
1. Add new names as primary commands; keep all existing names as compatibility aliases
2. Update `--help` text to use the new names first, aliases in parentheses
3. Update `installers/README.md` and `CLAUDE.md` to use new names
4. Do NOT remove aliases — external scripts and muscle memory should never break
5. Gate: all existing tests pass unchanged (aliases still work)

---

### B2: Argument Consistency Pass

<!-- seam:item
id: roadmap:track:B2
status: planned
status-since: 2026-04-18
status-by: none
supersedes: none
topics: naming, alias, command
priority: 1
phase: 1
-->

**Current problems:**
- `--vector-backend` / `--semantic-backend` are the same flag with two names
- `--vector-path` / `--chroma-path` — leaks Chroma implementation detail
- `--pack-budget` vs `--budget` — inconsistent naming across commands
- `--min-savings` only appears in some benchmark commands

**Proposed fixes:**
- Consolidate to `--backend` (seam|chroma|pgvector) with `--semantic-backend` as alias
- Rename `--vector-path` → `--backend-path`
- Standardize `--budget` everywhere
- Document all flags in a single reference section in `installers/README.md`

---

### B3: README Consolidation

<!-- seam:item
id: roadmap:track:B3
status: done
status-since: 2026-05-08
status-by: history:147
supersedes: none
topics: readme, docs, command
priority: 3
phase: 1
-->

**Current state:** There are multiple README files (`installers/README.md`, `benchmarks/README.md`, `experimental/retrieval_orchestrator/README.md`) with overlapping and sometimes stale content.

**SOP:**
1. Audit all README files for stale content
2. Make `installers/README.md` the operator-facing entry point (install + quickstart)
3. Move benchmark operator docs to `benchmarks/README.md`
4. Move retrieval architecture docs to `experimental/retrieval_orchestrator/README.md`
5. Add a root-level `README.md` that links to all of the above

---

## Track C — Benchmark Hardening
History pointer: see `HISTORY#008`, `HISTORY#011`, and planned benchmark hardening items `HISTORY#036`-`HISTORY#040`.

### C1: Holdout Suites

<!-- seam:item
id: roadmap:track:C1
status: done
status-since: 2026-04-27
status-by: history:152
supersedes: none
topics: benchmark, holdout, fixture
priority: 3
phase: 1
-->

**What:** Cases that were never used during development and are only run at publish time. Results from holdout suites are the only ones that count as external claims.

**Status:** Implemented 2026-04-27. See `HISTORY#092`.

**SOP:**
1. `benchmarks/fixtures/holdout/` exists and local JSON files are ignored by git
2. `seam benchmark run --holdout` only loads fixtures from that directory
3. `--holdout` requires an interactive confirmation or `--confirm-holdout`
4. Default holdout JSON bundles are stored separately under `benchmarks/runs/holdout/`

---

### C2: Benchmark Diff Tooling

<!-- seam:item
id: roadmap:track:C2
status: done
status-since: 2026-04-27
status-by: history:153
supersedes: none
topics: benchmark, diff, verify
priority: 3
phase: 1
-->

**What:** `seam benchmark diff <run-a.json> <run-b.json>` — shows a structured delta between two runs: which cases improved, which regressed, by how much.

**Status:** Implemented 2026-04-27. See `HISTORY#092`.

**SOP:**
1. Use `seam benchmark diff <run-a> <run-b>` with bundle paths or persisted run ids
2. The diff verifies both bundles, joins exact matches on case hash, and falls back to `family::case_id` when the case hash changed
3. Numeric and boolean metrics get per-case deltas with green/red/gray indicators
4. JSON and pretty output include summary counts for improvements, regressions, added cases, and removed cases

---

### C3: Gold Standard Benchmarks

<!-- seam:item
id: roadmap:track:C3
status: planned
status-since: 2026-04-18
status-by: none
supersedes: none
topics: benchmark, gold-standard, retrieval
priority: 1
phase: 1
-->

**What:** Run SEAM's retrieval engine against publicly known benchmarks to get externally comparable numbers.

**Target benchmarks:**
- **BEIR** (Benchmarking IR): 18 diverse retrieval tasks — covers fact retrieval, argument mining, biomedical, financial
- **MTEB** (Massive Text Embedding Benchmark): evaluates embedding quality across classification, clustering, retrieval
- **MS-MARCO**: passage ranking at scale

**SOP:**
1. Add `benchmarks/external/` directory for gold standard fixture adapters
2. Write a BEIR adapter that converts BEIR datasets into SEAM retrieval fixtures
3. Run SEAM's hybrid retrieval (SQLite + SBERT) against BEIR tasks
4. Store results in `benchmarks/runs/` with a `source=beir` tag
5. Document results in `benchmarks/BENCHMARK_LOG.md`

**Note:** This requires downloading BEIR datasets (~GB scale). Keep adapters separate from the main fixture suite.

---

### C4: Adversarial Testing

<!-- seam:item
id: roadmap:track:C4
status: planned
status-since: 2026-04-18
status-by: none
supersedes: none
topics: benchmark, fixture, verify
priority: 1
phase: 1
-->

**What:** Deliberately try to break SEAM — malformed MIRL, adversarial queries, very long documents, Unicode edge cases, concurrent writes, empty databases.

**SOP:**
1. Add `benchmarks/fixtures/adversarial/` with edge-case inputs
2. Write an `adversarial` benchmark family in `benchmarks.py`
3. Each case should either pass cleanly or fail with a specific known error — no silent corruption
4. Target: 100% cases either pass or raise a documented exception

---

### C5: Cross-Machine Reproducibility

<!-- seam:item
id: roadmap:track:C5
status: planned
status-since: 2026-04-18
status-by: none
supersedes: none
topics: benchmark, verify, windows, linux
priority: 1
phase: 1
-->

**What:** The same benchmark run on Windows and Linux should produce identical scores.

**SOP:**
1. Add a `reference_run.json` to the repo as a locked reference
2. `seam benchmark verify --reference reference_run.json` checks current scores against reference within a tolerance
3. CI-equivalent: run this check before any claim of benchmark improvement

---

## Track D — Model Skills & Automation
History pointer: see `HISTORY#041`-`HISTORY#043`.

### D1: SEAM as Claude Tool Set

<!-- seam:item
id: roadmap:track:D1
status: planned
status-since: 2026-04-18
status-by: none
supersedes: none
topics: mcp, chat, multi-agent
priority: 1
phase: 1
-->

**What:** Define SEAM operations as Claude tool_use functions so a Claude agent can use SEAM's memory as a live knowledge base during a conversation.

**Tools to define:**
- `seam_compile(text: str) → IRBatch` — compile and persist natural language
- `seam_search(query: str, budget: int) → SearchResult` — retrieve relevant records
- `seam_context(query: str) → Pack` — get a generation-ready context pack
- `seam_compress(text: str) → LosslessArtifact` — compress to machine text
- `seam_stats() → dict` — runtime health and record counts

**SOP:**
1. Create `seam_runtime/tools.py` — defines tool schemas as Anthropic tool_use dicts
2. Add `SeamToolExecutor` class that maps tool_name → runtime method call
3. Wire into the dashboard Chat tab (Track A5)
4. Document as a standalone integration guide

---

### D2: Auto-Compression Pipeline

<!-- seam:item
id: roadmap:track:D2
status: planned
status-since: 2026-04-18
status-by: none
supersedes: none
topics: compress, persist, compile
priority: 1
phase: 1
-->

**What:** A background process (or CLI command) that watches a directory, compresses new files with SEAM-LX/1, and persists the MIRL to the database automatically.

**SOP:**
1. Add `seam watch <directory>` command to CLI
2. Use `watchdog` library (new optional extra) to monitor file events
3. On new/modified file: compress → compile-nl → persist → index
4. Log each operation to a watch log in SQLite
5. Add `seam watch --once` for a single-pass scan without ongoing watch

---

### D3: Batch Compile

<!-- seam:item
id: roadmap:track:D3
status: planned
status-since: 2026-04-18
status-by: none
supersedes: none
topics: compile, persist, command
priority: 1
phase: 1
-->

**What:** `seam batch-compile <glob>` — compile and persist multiple files at once with a progress bar and summary report.

**SOP:**
1. Add `batch-compile` command to CLI
2. Accept a glob pattern or directory
3. Process files in parallel using `concurrent.futures.ThreadPoolExecutor`
4. Show Rich progress bar; write a summary JSON on completion
5. Gate: test with 1 file, 10 files, and an empty glob

---

## Track E — Architecture & Scalability
History pointer: see `HISTORY#012`, `HISTORY#019`, and planned scale tracks `HISTORY#044`-`HISTORY#046`.

### E1: PgVector as Configurable Default

<!-- seam:item
id: roadmap:track:E1
status: in-progress
status-since: 2026-04-30
status-by: history:121
supersedes: none
topics: pgvector, vector, docker
priority: 0
phase: 1
-->

**What:** When `SEAM_PGVECTOR_DSN` is set, PgVector is already used automatically. The next step is making it the explicit recommended backend for deployments with >10k records, and adding a migration path from SQLite vector index to PgVector.

**SOP:**
1. Add `seam migrate-vectors --to pgvector` command
2. Reads all vector embeddings from SQLite vector_index, writes them to PgVector
3. Verifies row counts match before and after
4. Marks the migration in a `migrations` table so it's idempotent

---

### E2: Multi-Tenant Namespacing

<!-- seam:item
id: roadmap:track:E2
status: planned
status-since: 2026-04-18
status-by: none
supersedes: none
topics: persist, vector
priority: 1
phase: 1
-->

**What:** SEAM already has namespaces (`ns`) and scopes (`scope`) on records. The next step is enforcing tenant isolation at the API level — a `tenant_id` that gates all queries.

**SOP:**
1. Add `tenant_id` column to `ir_records` and related tables (migration)
2. Add `--tenant` flag to all CLI commands
3. All queries filter by tenant_id unless `--all-tenants` is passed (operator-only)
4. Test: two tenants with overlapping record IDs — queries must not cross-contaminate

---

### E3: REST API Surface

<!-- seam:item
id: roadmap:track:E3
status: done
status-since: 2026-04-27
status-by: history:154
supersedes: none
topics: command, persist, retrieval
priority: 3
phase: 1
-->

**What:** Expose SEAM operations as a lightweight HTTP API so external systems can compile, search, and retrieve without running a full Python process.

**Status:** Implemented 2026-04-27. See `HISTORY#094`.

**SOP:**
1. `seam serve` runs FastAPI/Uvicorn through the optional `server` extra.
2. Endpoints: `POST /compile`, `POST /compile-dsl`, `GET /search`, `POST /context`, `POST /lossless-compress`, `POST /persist`, `GET /stats`, `GET /health`.
3. Auth: Bearer token through `SEAM_API_TOKEN` for protected endpoints.
4. Rate limiting: `SEAM_API_RATE_LIMIT_PER_MINUTE` or `SEAM_API_RATE_LIMIT`; `/health` is unauthenticated but still rate-limited.
5. Tests: FastAPI `TestClient` coverage for auth, compile/search/context/stats, and rate limiting.

---

## Track F — Docs, Setup Guides, and Error Playbooks

<!-- seam:item
id: roadmap:track:F:asserttrue-scrub
status: planned
status-since: 2026-05-18
status-by: history:PENDING
supersedes: none
topics: tests, quality
priority: 3
phase: 1
-->

**What:** Complete the remaining ~113 assertTrue→specific-assertion replacements in test_seam.py. Phase 1 addressed 15 highest-value cases; the remainder are mostly string-in-list and result-existence checks that benefit from better diagnostics.

### F-backlog: Production Readiness Backlog Items

<!-- seam:item
id: roadmap:track:F:backlog:security-md
status: planned
status-since: 2026-05-18
status-by: history:PENDING
supersedes: none
topics: docs, security
priority: 3
phase: 2
-->

<!-- seam:item
id: roadmap:track:F:backlog:installer-symlink
status: planned
status-since: 2026-05-18
status-by: history:PENDING
supersedes: none
topics: installer, linux
priority: 3
phase: 2
-->

<!-- seam:item
id: roadmap:track:F:backlog:git-hooks-macos-sha256
status: planned
status-since: 2026-05-18
status-by: history:PENDING
supersedes: none
topics: git-hooks, macos
priority: 3
phase: 2
-->

<!-- seam:item
id: roadmap:track:F:backlog:scoring-weights
status: now
status-since: 2026-05-25
status-by: history:243
supersedes: none
topics: retrieval, benchmark
priority: 0
phase: 1
-->

<!-- seam:item
id: roadmap:track:F:backlog:backoff-jitter
status: planned
status-since: 2026-05-18
status-by: history:PENDING
supersedes: none
topics: models, retry
priority: 3
phase: 2
-->

<!-- seam:item
id: roadmap:track:F:backlog:json-comparison-fragility
status: planned
status-since: 2026-05-18
status-by: history:PENDING
supersedes: none
topics: pack, json
priority: 3
phase: 2
-->

<!-- seam:item
id: roadmap:track:F:backlog:ps1-double-backslash
status: planned
status-since: 2026-05-18
status-by: history:PENDING
supersedes: none
topics: scripts, windows
priority: 3
phase: 2
-->

<!-- seam:item
id: roadmap:track:F:backlog:experience-stream-empty
status: now
status-since: 2026-05-25
status-by: history:243
supersedes: none
topics: experience, protocol
priority: 0
phase: 1
-->

<!-- seam:item
id: roadmap:track:F:backlog:superseded-phase-tree
status: planned
status-since: 2026-05-18
status-by: history:PENDING
supersedes: none
topics: roadmap, docs
priority: 3
phase: 2
-->

<!-- seam:item
id: roadmap:track:F:backlog:test-claude-judge-flaky
status: planned
status-since: 2026-05-18
status-by: history:PENDING
supersedes: none
topics: tests, judge
priority: 3
phase: 2
-->

<!-- seam:item
id: roadmap:track:F:backlog:verify-continuity-ref-existence
status: planned
status-since: 2026-05-18
status-by: history:PENDING
supersedes: none
topics: verify, continuity, history
priority: 3
phase: 2
-->

**What:** Add ref-file existence validation to `verify_continuity`. The gate currently validates structural integrity (hashes, supersedes chains, snapshots) but does not check that files listed in an entry's `refs:` field exist in the git index. HISTORY#191 referenced `docs/SOP_PRODUCTION_READINESS_REMEDIATION.md` in its `refs:` field before the file was tracked; the continuity gate did not catch the orphaned ref because it only validates hashes, chains, and snapshots — not ref-file presence.

**Proposed approach (design only; not implemented):**
1. Parse each entry's `refs:` field and classify each ref:
   - `http://` or `https://` prefix → skip (external URL, valid outside repo).
   - `HISTORY#NNN` pattern → validate the entry exists in HISTORY.md.
   - Path-like ref (contains `/` or `.`) → validate the file exists in the git index via a single `git ls-files` read per run (in-memory set lookup; no per-file shell-out).
   - Section-anchor ref (`file.md#section`) → validate the file exists; anchor validation is stretch.
2. Scope: only validate refs in the most recent N entries (default: 10). Historical entries often reference files that were deliberately renamed or archived; scanning all 192 entries would produce noise.
3. Output as warnings, not hard failures: `Continuity OK (2 ref-file warnings: docs/SOP_PRODUCTION_READINESS_REMEDIATION.md not in git index at entry #191)`. Operators triage warnings without the gate blocking a commit for a stale ref in an old entry.
4. Deterministic: one `git ls-files` call per run, in-memory set membership check per ref. No per-file shell-out. Runs in milliseconds.

Constraint satisfaction:
- Deterministic and fast: single `git ls-files` read + set lookups. No shell-out per ref.
- Distinguishes external (skip URLs) from internal (validate paths/HISTORY refs).
- No flood of historical noise: age-gated to recent N entries only.

### F1: Operator Setup Guide with Exact Commands

<!-- seam:item
id: roadmap:track:F1
status: done
status-since: 2026-04-28
status-by: history:099
supersedes: none
topics: readme, docs, installer
priority: 3
phase: 1
-->

**What:** Publish a single setup guide with exact copy/paste commands for Windows, Linux, and WSL2, including optional extras and verification commands.

**SOP:**
1. Add `docs/setup.md` with exact command blocks for:
   - creating virtual env
   - installing base deps
   - installing extras (`[dash]`, `[pgvector]`, `[sbert]`, `[all-extras]`)
   - running smoke checks (`seam doctor`, `seam dashboard --snapshot`, benchmark smoke)
2. Add a short "known good first run" section with expected command output fragments.
3. Link `docs/setup.md` from root `README.md` and `installers/README.md`.
4. Gate: a clean machine can reach `seam doctor: PASS` by following only this doc.

---

### F2: Documented Error Catalog and Fix Procedures

<!-- seam:item
id: roadmap:track:F2
status: done
status-since: 2026-04-28
status-by: history:099
supersedes: none
topics: docs, readme, doctor
priority: 3
phase: 1
-->

**What:** Create a troubleshooting catalog that maps common operator errors to exact recovery steps.

**SOP:**
1. Add `docs/errors.md` with one section per documented error:
   - symptom text (exact error snippets)
   - root cause
   - fix commands
   - verification command after fix
2. Include current high-frequency paths:
   - missing optional dependency (Textual/PgVector/SBERT)
   - pgvector DSN configured but unreachable
   - Chroma path/index sync failures
   - benchmark bundle verification failures
3. Add "do not proceed" blockers and escalation steps.
4. Gate: each documented error has at least one reproducible verification command.

---

### F3: How-To Runbooks for Daily Operations

<!-- seam:item
id: roadmap:track:F3
status: done
status-since: 2026-05-08
status-by: history:147
supersedes: none
topics: docs, readme, command
priority: 3
phase: 1
-->

**What:** Add task-oriented runbooks for common operator workflows so users can execute standard flows without source code spelunking.

**SOP:**
1. Add `docs/howto/` with runbooks:
   - ingest and retrieve memory
   - run guarded real-adapter checks
   - archive benchmark bundles to Documents
   - recover from interrupted runs
2. Keep runbooks command-first with short explanation blocks.
3. Add a top-level index file `docs/howto/README.md`.
4. Gate: every runbook has prerequisites, exact commands, and a success checklist.

---

## Track G — Functional Visual Memory System

History pointer: see `HISTORY#112` and `HISTORY#113` for the first HS/1
surface flow.

### G1: Document-to-Machine-Language Compiler

<!-- seam:item
id: roadmap:track:G1
status: done
status-since: 2026-05-08
status-by: history:145
supersedes: none
topics: compile, mirl, surface
priority: 3
phase: 1
-->

**What:** Convert documents into directly readable MIRL or `SEAM-RC/1` records
that preserve facts, quote spans, headings, table cells, references, and source
provenance.

**Status:** Implemented in HISTORY#145 for the first wave of structural
primitives. `seam_runtime/lossless.py:_structural_quote_spans` is the single
extractor; both the readable compiler and the benchmark gate verifier delegate
to it so the compiled records and the verifier records cannot drift out of
sync. Records currently emitted:

- quoted strings (`"..."`) → `text` is the raw quote span
- markdown headings (`# ... ######`) → `text` is `heading:<title>`
- markdown 2-column table data rows → `text` is `cell:<col1>=<col2>`
- inline bracket citations (e.g. `[Smith2024]`) → `text` is `citation:[Key]`
- reference list phrases (split on `. `) → `text` is `ref:<phrase>`

The release-blocking `surface` benchmark family at
`benchmarks/fixtures/surface_cases.json` covers all five via richer document
cases for heading recall, table cell lookup, and citation/reference extraction.
`seam benchmark gate` enforces `direct_query_exactness_rate == 1.0` on those
cases. Adding a new structural primitive means appending to
`_structural_quote_spans` plus a fixture case exercising it. Future primitives
to consider: lists, code blocks, dates, key-value blocks, links.

**Gate:** SEAM can answer detail questions from the emitted machine language
without opening the original document.

### G2: Stored Surface Library

<!-- seam:item
id: roadmap:track:G2
status: done
status-since: 2026-05-06
status-by: history:117
supersedes: none
topics: surface, ledger, persist
priority: 3
phase: 1
-->

**What:** Add a managed library for `.seam.png` surfaces. The PNG stores the
payload bytes; SQLite stores only metadata, hashes, status, and lookup fields.

**Status:** Implemented and merged to `main` on 2026-05-06.

**Gate:** A stored surface can be listed, verified, queried, searched, used for
context, imported, and audited by hash.

### G3: Direct Image-Surface Query

<!-- seam:item
id: roadmap:track:G3
status: done
status-since: 2026-05-06
status-by: history:117
supersedes: none
topics: surface, retrieval, command
priority: 3
phase: 1
-->

**What:** Make the stored image artifact itself a readable memory source.
Queries decode PNG pixels into MIRL/RC bytes in memory, verify hashes, then run
the normal parser/search/context path.

**Status:** Implemented for MIRL and RC/1 payloads. Continue expanding the
document-structure records that RC/1 exposes to the query path.

**Gate:** Query/search/context works from a stored surface path or surface id
without OCR, source-document restoration, or prior SQLite import.

### G4: Surface Store Benchmarks

<!-- seam:item
id: roadmap:track:G4
status: done
status-since: 2026-05-06
status-by: history:117
supersedes: none
topics: surface, benchmark, fixture
priority: 3
phase: 1
-->

**What:** Add benchmark cases for the full functional loop:
document -> machine language -> surface -> stored surface -> direct answer.

**Status:** Implemented and merged to `main` on 2026-05-06.

**Gate:** `surface_exact_rate`, `payload_hash_match_rate`, stored-surface lookup
rate, stored-surface query rate after original-output deletion, repair success
rate, repaired-copy query rate, and direct query exactness all stay at 100% for
release-blocking fixtures.

### G5: Zero-Ops Multi-Surface Library Index with Drift Verification

<!-- seam:item
id: roadmap:track:G5
status: planned
status-since: 2026-05-31
status-by: none
supersedes: none
topics: surface, search, verify, integrity
priority: 2
phase: 1
-->

**What:** Add a portable, zero-ops index over a folder of `.seam.png` HS/1
surfaces plus a drift verifier that catches index/surface disagreements.
Bundled because shipping the index without the verifier is shipping a silent
skip lane: a stale index lies without warning. This closes the gap between
"we can store an HS/1 surface" (G2) and "you can ship a folder of `.seam.png`
files and it behaves like a queryable, verifiable store" -- the missing piece
for portable memory to be production-grade.

**Zero-ops contract:** the index must be derivable from any folder of valid
`.seam.png` files via one command, with no external service, no schema-managed
DB, and no out-of-band state. Preferred form is an HS/1 surface itself
(`INDEX.seam.png` or a manifest surface) so the library stays a single artifact
type; a sidecar SQLite is acceptable only if it is fully rebuildable from the
surfaces and never the source of truth.

**Coverage:** surface id, payload hash, format, plus claim / entity /
quote-span tokens needed for fast surface discovery without decoding every PNG.
Index only verified-hash surfaces; failed-hash surfaces are evicted, not
silently shadowed.

**Verifier (`seam surfaces verify-index`, module `verify_index`):** reports
`missing_on_disk`, `missing_in_index`, `hash_mismatch`, and
`format_unreadable` by default (cheap, no full decode); `payload_drift`
(decoded payload disagrees with what the index claims) is opt-in via `--deep`.
Exits non-zero on any conflict so pre-commit and CI can gate. Names align with
the existing `verify_integrity` / `verify_continuity` / `verify_routing` /
`verify_streams` pattern.

**Gate:** A folder of N surfaces can be (1) indexed in one command with no
external services, (2) queried for "which surfaces contain X" without decoding
every PNG, (3) verified for index/surface consistency with non-zero exit on any
drift, and (4) repaired by rebuilding the index from scratch. Deep verification
of payload claims is available but opt-in. Default verifier run must complete on
a 10k-surface library in seconds, not minutes.

---

## Track H — Context Streams Protocol

Generalize the single-stream `HISTORY.md` + `HISTORY_INDEX.md` pattern into a
multi-stream protocol so roadmap, experience, and library content scale
independently without bloating session context. Full design captured in
`docs/roadmap/CONTEXT_STREAMS.md`.

### H1: Multi-Stream Substrate (Phase 1)

<!-- seam:item
id: roadmap:track:H1
status: done
status-since: 2026-05-15
status-by: history:170
supersedes: none
topics: protocol, history, plan, roadmap
priority: 0
phase: 1
-->

**What:** Add a multi-stream substrate alongside the current history protocol
without disturbing it. Root `HISTORY.md` / `HISTORY_INDEX.md` stay canonical;
a compatibility adapter surfaces them as the `history` stream and produces
byte-equivalent derived mirrors under `.seam/streams/history/`. Bootstrap new
`roadmap` and `experience` streams; add a derived (not append-only) global
`cross_index.md`; add generic tooling under `tools/streams/` alongside
existing `tools/history/`; add `verify_streams` gate. No symlinks. Path
canonicality flip for `history` is explicitly deferred to a separate later
HISTORY entry once every consumer is proven to read from either path.

**Status:** Planned (now). Design locked in `docs/roadmap/CONTEXT_STREAMS.md`.

**Gate:** Root `HISTORY.md` + `HISTORY_INDEX.md` unchanged byte-for-byte;
adapter mirrors verify byte-equivalent; existing supersedes chains and hashes
still verify; `seam doctor` returns PASS with the new `verify_streams` gate;
the existing test suite passes unchanged; `tools.streams.build_context_pack
--stream history --latest 3` produces output equivalent to
`tools.history.build_context_pack --latest 3`; cross-index regenerates
deterministically from stream logs.

### H2: Improvement Streams (Phase 2)

<!-- seam:item
id: roadmap:track:H2
status: now
status-since: 2026-05-25
status-by: history:243
supersedes: none
topics: protocol, history, plan
priority: 0
phase: 2
-->

**What:** Add a fifth stream `improvement` that captures retrieval-signal,
outcome-delta, repeated-hit, protocol-drift, and propose-rule events. Add a
trust gradient for experience (L1 hypothesis → L2 pattern → L3 codified) and
an auto-propose / manual-approve guardrail for protocol edits.

**Status:** Start now for the Track M retrieval-feedback subset. The earlier
"wait for ~4 weeks of H1 operational data" trigger is superseded by existing
Track M evidence: BIL-2 LoCoMo result bundles with query/context/gold/judge
outcomes, the warm `--keep-db` iteration path, and current no-paid retrieval
slices after HISTORY#240-HISTORY#242. First implementation slice:

1. add an append-only retrieval-event substrate (`query`, scope, candidate ids,
   ranks, scores/reasons, context hash, gold answer, derived gold-hit ids,
   context_recall, judge score, answer, run id, timestamp);
2. backfill from existing result bundles, explicitly marking pre-HISTORY#240
   or pre-HISTORY#242 bundles as stale diagnostic data;
3. generate fresh no-paid labels from the current code path and split them into
   dev/holdout before tuning;
4. write structured experience events for Track M attempts (`lever_tried`,
   baseline, result, conclusion) so failed score levers are not rediscovered;
5. expose proposals through `seam improvement review` before any protocol or
   ranking-policy promotion.

Scoring-weight tuning (`roadmap:track:F:backlog:scoring-weights`) is now
blocked on this substrate rather than on new paid runs. Do not tune weights on
the full 1542-case official set and then claim improvement on the same set.

**Gate:** SEAM never writes to `AGENTS.md`, `REPO_LEDGER.md`, or
`PROJECT_STATUS.md` autonomously. All protocol edits flow through
`seam improvement review` operator approval. Skill Factory integration uses
this stream as its data substrate.

### H3: Retrieval Integration (Phase 3)

<!-- seam:item
id: roadmap:track:H3
status: later
status-since: 2026-05-15
status-by: history:165
supersedes: none
topics: protocol, retrieval, search
priority: 2
phase: 3
-->

**What:** Wire stream filters into retrieval. `seam memory search --stream X`,
`build_context_pack --include history,roadmap,experience`, default exclusion
of `status=done`/`status=superseded`/`status=rejected` items, `--around <event_id>`
cross-index walking.

**Status:** Deferred until Phase 1 substrate is stable.

**Gate:** Default context pack excludes completed roadmap items and superseded
experience without explicit opt-in. Cross-stream temporal queries return
correct ordering across all streams.

### H4: Generalized Library Streams (Phase 4)

<!-- seam:item
id: roadmap:track:H4
status: later
status-since: 2026-05-15
status-by: history:165
supersedes: none
topics: protocol, retrieval, search, vector
priority: 3
phase: 4
-->

**What:** `seam-protocol ingest <path> --ns library.<name>` walks markdown by
heading and source by AST symbols, creates MIRL records with `raw_spans` byte/
line ranges, populates `document_status` + `projection_index` + library stream
events. Hash-gated re-runnable command (not a daemon). Promote `tools/streams/`
to a pip-installable `seam_protocol/` package for templating into other repos.

**Status:** Deferred until Phases 1-3 are stable.

**Gate:** Re-ingestion of unchanged content is a no-op (hash skip). Library
namespaces (`ns=library.*`) stay separate from canonical `local.default`.
Template scaffolds cleanly into a fresh repo with `seam-protocol init`.
## Track L — Agent / Skills Compiler

<!-- seam:item
id: roadmap:track:L
status: planned
status-since: 2026-05-15
status-by: history:180
supersedes: none
topics: agent, compiler, skills
priority: 2
phase: 1
-->

**Status:** Planned major workstream. Foundation specs already on `main`.
**Canonical specs:** `docs/roadmap/AGENT_COMPILER.md`, `docs/roadmap/SKILL_FACTORY.md`.
**Execution plan:** `docs/roadmap/SKILLS_COMPILER.md`.

Compile structured SEAM skill specs into target-specific agent instruction artifacts (Claude, Cursor, Codex, Gemini, Aider, generic). Audit installed copies for drift. Eventually wrap each artifact as a SEAM-HS/1 holographic surface with embedded provenance. The adaptive identification / observation / proposal / promotion loop sits on top of the compiler and is specified in `SKILL_FACTORY.md`.

Phase work (see `SKILLS_COMPILER.md`):

1. SkillIR + first canonical source spec (`session-end`)
2. First renderer (Claude profile) + provenance header
3. `seam skills compile` CLI
4. Second renderer (Cursor profile)
5. `seam skills audit` (read-only)
6. `seam skills apply` (gated)
7. HS/1 attestation wrap + `seam skills verify`
8+. H4 optimizer, H3 benchmark suite, Track K integration (deferred)

---

## Track I — External Memory Benchmarks (Comparator Gate)

<!-- seam:item
id: roadmap:track:I
status: done
status-since: 2026-05-17
status-by: history:189
supersedes: none
topics: benchmark, retrieval, comparator
priority: 1
phase: 1
-->

**Status:** Planned major workstream. Concept-only on main; implementation lives on `bench/add-memory-benchmark-registry`.
**Canonical spec:** `docs/roadmap/MEMORY_BENCHMARKS.md`.

Make external memory benchmarks (LoCoMo, ConvoMem, MemBench, LongMemEval, BEAM, PerLTQA, EverMemBench, Memora, Mem2ActBench) a release gate for SEAM memory claims, with required comparator coverage (Mem0, Zep/Graphiti, Letta/MemGPT, MemPalace, Hindsight, MemMachine).

**60-second install-and-run gate:** a new user can `pip install seam[bench]` and `seam bench external --quickstart locomo` on a clean Linux/WSL machine and get a JSON report with score, comparator deltas, and an integrity hash, end to end, in under 60 seconds.

Phase work:

1. Registry + validation + runner plan + command harness + tests + CI artifact upload
2. `seam bench external` CLI alias + `--quickstart` LoCoMo path
3. Adapters under `benchmarks/external/<benchmark>/`
4. Comparator runners
5. Promote `--strict` into release CI
6. Prompt codec benchmark layer (see Track J)

---

## Track J — Prompt Codec Optimization

<!-- seam:item
id: roadmap:track:J
status: planned
status-since: 2026-05-15
status-by: history:180
supersedes: none
topics: codec, compress, prompt, benchmark
priority: 2
phase: 1
-->

**Status:** Planned roadmap track.
**Canonical spec:** `docs/roadmap/PROMPT_CODEC.md`.

Evaluate TOON, compact JSON, SEAM-RC/1, SEAM-LX/1, and markdown-table encodings as *derived* prompt transports. Canonical storage (MIRL, JSON, SQLite) does not change. Codec selection is restricted to prompt-bound payloads (PACK, retrieval results, benchmark case matrices, comparator scorecards, etc.). Auto-selection only promotes a codec that beats compact JSON on measured token count under the active tokenizer and round-trips losslessly.

---

## Track K — Trust, Security, Lineage, and Auditability

<!-- seam:item
id: roadmap:track:K
status: planned
status-since: 2026-05-15
status-by: history:180
supersedes: none
topics: security, audit, trust, benchmark
priority: 2
phase: 1
-->

**Status:** Planned major workstream.
**Canonical spec:** `docs/roadmap/TRUST_SECURITY_AUDITABILITY.md`.

Trust evidence on demand from the runtime, CLI, contracts, audit ledger, validation reports, provenance, and benchmark bundles. The dashboard becomes the visualization layer for that evidence, not the source of it.

Items: threat model (K0), capability and permission model (K1), tamper-evident audit ledger (K2), secrets scanning and redaction (K3), optional encrypted SQLite store (K4), versioned contracts (K5), unified `seam trust report` (K6), operation validation reports (K7), OpenLineage export (K8), OpenTelemetry correlation (K9), supply-chain proof / SBOM / release attestation (K10), security test suite (K11), incident response and vulnerability disclosure (K12), verified benchmark bundles with **Benchmark Integrity Levels BIL-0 through BIL-6** (K13), store-aware contradiction reports (K14), provenance stress tests (K15), diagnostic JSON evidence mode (K16), session-root manifests/signatures (K17), and stake-weighted memory signals (K18).

Track I (external memory benchmarks) and Track L (Skills Compiler) consume Track K primitives in their later phases.

### K-Spine: Memory Trust and Causal Integrity

<!-- seam:item
id: roadmap:track:K14
status: planned
status-since: 2026-05-18
status-by: history:196
supersedes: none
topics: verify, audit, retrieval
priority: 1
phase: 1
-->

**K14 — Second Inspector / store-aware contradiction report.** Add a validation layer above structural MIRL verification that compares a new batch against existing SQLite records before persistence. First scope: direct `STA target + field` conflicts and simple `CLM subject + predicate` conflicts. Output a machine-readable report with `collision`, `existing_record_id`, `new_record_id`, `severity`, `reason`, and provenance/evidence refs. Default behavior should report/mark contested records; hard blocking belongs behind an explicit strict flag.

Track M note: do not assume contradiction is the reason for LoCoMo cat-3 or
answerer abstention failures. Pull this ahead of the broader Track K sequence
only if the H2 retrieval-event audit shows conflicting retrieved facts are a
material failure mode.

<!-- seam:item
id: roadmap:track:K15
status: planned
status-since: 2026-05-18
status-by: history:196
supersedes: roadmap:track:K14
topics: verify, audit, provenance
priority: 1
phase: 2
-->

**K15 — Provenance Stress Test.** When K14 finds a high-severity collision against high-confidence or high-evidence records, require a raw-data audit before accepting the new fact as verified. The stress test should compare evidence spans, source refs, source hashes, timestamps, and agent/provenance records; unresolved collisions remain contested rather than silently overwriting older truth.

<!-- seam:item
id: roadmap:track:K16
status: planned
status-since: 2026-05-18
status-by: history:196
supersedes: roadmap:track:K14
topics: verify, command, audit
priority: 1
phase: 2
-->

**K16 — Diagnostic JSON evidence mode.** Add strict machine-readable reporting for trust-critical commands (`verify`, `persist`, `reconcile`, future `trust report`) using JSON/MIRL-shaped evidence objects: record ids, proofs, error codes, collision ids, and provenance refs. This is a CLI/reporting contract, not a claim that model reasoning can be made non-linguistic.

<!-- seam:item
id: roadmap:track:K17
status: planned
status-since: 2026-05-18
status-by: history:196
supersedes: roadmap:track:K2,roadmap:track:K7
topics: integrity, audit, snapshot
priority: 2
phase: 3
-->

**K17 — Causal handshake / session-root manifests.** After the audit ledger and validation reports exist, compute a canonical session-root manifest over database state, latest audit event, schema/version metadata, and relevant stream roots. Optional signing should sign the manifest/root hash, not raw SQLite bytes, and must keep key identity/declassification boundaries explicit.

<!-- seam:item
id: roadmap:track:K18
status: planned
status-since: 2026-05-18
status-by: history:196
supersedes: roadmap:track:K14,roadmap:track:K15
topics: retrieval, rank, audit
priority: 2
phase: 4
-->

**K18 — Stake-weighted memory signals.** Add a retrieval/ranking signal that records operational merit from successful task completions, but never treats merit as truth. Weight must be penalized by unresolved collisions, missing provenance, stale evidence, and failed stress tests. It is a ranking feature consumed after K14/K15, not an integrity substitute.

Track M note: the immediate H2 work may implement a narrow feedback-weighted
ranking experiment from retrieval events, but negative stake must be reserved
for clearly irrelevant, stale, contradicted, or judge-confirmed wrong evidence.
Do not penalize records merely because an answerer returned `unknown` despite
high recall; that may be an answerer failure, not a retrieval failure.

---

## Track N — Packaging, Release, and Distribution

<!-- seam:item
id: roadmap:track:N
status: planned
status-since: 2026-06-02
status-by: history:284
supersedes: none
topics: packaging, release, distribution
priority: 3
phase: 1
-->

**Status:** Planned, deferred (operator decision 2026-06-02 — not a current priority). Build the release/distribution plumbing for `seam-runtime`.

**Distribution target:** public core now targets `BlackhatShiftey/Seam_Runtime` under Apache-2.0. PyPI distribution remains a separate release decision; package name `seam-runtime` is the intended package name (`seam` is taken). Build plumbing should be target-agnostic so switching to public PyPI later is a one-line change.

**License gate:** resolved for the public core: Apache-2.0. Hosted services, enterprise modules, private benchmark holdouts, customer integrations, support/warranty/indemnity, and unreleased methods remain outside the public core unless intentionally released.

Phase work:

1. Complete project metadata (authors, `project.urls`, keywords, long-description content type); confirm `seam_runtime*` packaging only (experimental promoted out — see HISTORY#284).
2. `python -m build` + `twine check` validation in CI on every tag.
3. Private-distribution release workflow: build sdist+wheel on a `v*` tag, `twine check`, attach artifacts to a GitHub Release (private repo). Keep `Do Not Upload`.
4. When/if the license flips and the operator approves public release: remove `Do Not Upload`, wire Trusted Publishing (OIDC) to PyPI, publish `seam-runtime`.

---

## Track O — SEAM Query Engine (execution-verified NL querying)

<!-- seam:item
id: roadmap:track:O
status: planned
status-since: 2026-06-15
status-by: history:319
supersedes: none
topics: query, sql, retrieval, benchmark, bird
priority: 3
phase: 1
-->

**Status:** Planned / consider — a future major workstream, AFTER the cat1/cat3
retrieval-quality work (the measured current bottleneck; a query engine is a
different, additive axis). Operator interest: text-to-SQL (Google Gemini-SQL2,
80.04% on BIRD) is a strong product direction for SEAM.
**Canonical design:** `docs/roadmap/SEAM_QUERY_ENGINE_SQL2_LEARNINGS.md` (the
SQL2 learnings + what to take vs leave).

A model-independent, provenance-preserving, **execution-verified** natural-language
query interface over SEAM's store (MIRL records, relational metadata, semantic
indexes, trace graphs). The kernel — already SEAM's DNA (extractor grounding
firewall, §24 gate, glass-box): **a generated query is not trusted until execution
+ semantic verification succeed.** Pipeline: NL → **typed query plan** →
deterministic compilation → verified execution → provenance-backed result (the model
emits *plans*, never raw executable authority).

**Start here (measurement-first, the forcing function): the BIRD harness.**
BIRD evaluates *executable results, not query strings* — the standard yardstick for
text-to-SQL. Build it as the FIRST deliverable of this track (the way the `compile_nl`
fidelity contract preceded the compiler fix): a new query-benchmark slot (separate
from the conversational `memory_benchmarks.json` registry), the **execution-accuracy
scorer** (run gold + predicted SQL on a BIRD SQLite db, compare result sets), a `bird`
CLI target with `--dry-run`/plan, dataset registration (not bundled — `--dataset-path`
to a local BIRD release, like `beam`), and a tiny fixture so the scorer is tested
before any generator exists. The SEAM SQL **generator** stays `NOT_CONFIGURED` until
the engine can emit SQL — the harness measures nothing until then, so it is built
*with* this track, not before it (it becomes useful at Phase 1, fully at Phase 2).

Phase work:

1. **Deterministic foundation (no LLM):** `seam_runtime/query/` — typed `SEAMQueryPlan`,
   semantic schema registry, deterministic plan→operation compiler (over the existing
   hybrid retrieval + structured SQLite filters), read-only AST-validated sandbox
   (scope/namespace predicates injected by trusted code; SQLite authorizer + timeout +
   row limits; deny ATTACH/PRAGMA/extension-load), query-trace persistence. **+ the BIRD
   execution-accuracy benchmark.** `seam query --plan-only`.
2. **Model-assisted planning:** NL→plan adapters (Ollama default; openai/claude/gemini
   opt-in), schema linking, ambiguity detection, single-candidate verification. Now the
   BIRD harness can score SEAM end-to-end.
3. **Verification scaling (only if a measured variance problem appears):** failure-aware
   repair, confidence-gated abstention, cost/latency budgets. NOT the SQL2 candidate-
   consensus ensemble by default — a deterministic plan compiler removes the variance it
   tames (see the learnings doc).
4. **Specialization:** mine successful traces into a gold-query dataset + hard negatives
   + optional local-model distillation, reusing the existing self-improvement + benchmark
   loop.

Overlaps Track K (the read-only sandbox + provenance query traces share K's audit
ledger). Do not start before the retrieval-quality work lands.

---

## Recommended Course — Priority Order

Use this section for current priority. Older planned entries `HISTORY#028`-
`HISTORY#047` are append-only planning cards; implemented items are superseded
by later done entries and status notes.

Current sequence:

```
Done - functional visual memory + foundational polish
- G1: Document-to-machine-language compiler (implemented; see HISTORY#145)
- G2: Stored surface library (implemented; merged 2026-05-06)
- G3: Direct image-surface query (implemented for MIRL and RC/1 payloads)
- G4: Surface store benchmarks (implemented; merged 2026-05-06)
- B3: README consolidation (implemented; see HISTORY#147)
- C1: Holdout suites (implemented; supersedes HISTORY#036)
- C2: Benchmark diff tooling (implemented; supersedes HISTORY#037)
- E3: REST API surface (implemented; supersedes HISTORY#046)

Now - retrieval feedback loop + browser dashboard / REST API GUI + context streams substrate
- H2: Track M retrieval-feedback substrate (retrieval_event data, stale-bundle backfill, current no-paid labels, improvement review guardrail)
- F:backlog:scoring-weights: tune retrieval weights only after H2 provides dev/holdout labels
- F:backlog:experience-stream-empty: start structured Track M lesson events for lever/result/conclusion handoffs
- A-Web: wire experimental/webui to real REST endpoints
- A-Web: split the single-file prototype into maintainable app shell modules
- A-Web: add browser smoke tests for real health/stats/search/context data
- A-CLI: keep seam shell aligned with MCP and REST surfaces
- H1: Multi-stream substrate (design locked; see docs/roadmap/CONTEXT_STREAMS.md and HISTORY#165)

Next - dashboard and agent ergonomics
- A2: Benchmark progress bar
- A3: ASCII sparkline graphs
- A6: Presentation mode
- D1: SEAM as Claude/Gemini/Codex tool set

Next plug-and-play target - external memory benchmark credibility
- I1: External memory benchmark registry + runner (landed via PR #22)
- I2: `seam bench external --quickstart locomo` — 60-second install-and-run gate
- I3: First three required adapters (LoCoMo, ConvoMem, MemBench)
- I4: First three required comparators (Mem0, Zep/Graphiti, Letta/MemGPT)

Later - benchmark credibility, scale, and adaptive context loop
- H3: Retrieval integration with stream filters (after H1 substrate stable)
- H4: Generalized library streams + seam_protocol templating (after H1-H3)
- C5: Cross-machine reproducibility
- C4: Adversarial testing
- C3: Gold standard benchmarks (BEIR/MTEB)
- D2: Auto-compression pipeline
- D3: Batch compile
- A4: Vector visualization
- E1: PgVector migration helper
- E2: Multi-tenant namespacing

Major workstreams scheduled after the plug-and-play target lands
- Track L: Agent / Skills Compiler (reconcile from `claude/seam-trust-security-manual-8mhEL`)
- Track J: Prompt codec optimization (TOON / SEAM-RC / SEAM-LX evaluation)
- Track K: Trust, security, lineage, auditability (capabilities, audit ledger, BIL benchmark bundles)
- Track O: SEAM Query Engine (execution-verified NL→typed-plan→SQL; starts with the BIRD execution-accuracy harness; after the retrieval-quality work)
```

Snapshot archival policy: do not delete or compress `.seam/snapshots/` ad hoc.
Keep the latest verified continuity snapshot available. If snapshot count or
size becomes a problem, add an explicit local-only retention tool that archives
older verified snapshots outside normal git-tracked source and records the
policy in `REPO_LEDGER.md`.

Superseded 2026-04-18 sequence retained below only as historical context:

```
Phase 1 (Now — functional visual memory + foundational polish)
├── G1: Document-to-machine-language compiler
├── G2: Stored surface library
├── G3: Direct image-surface query
├── G4: Surface store benchmarks
├── B1: Command naming audit + aliases
├── B3: README consolidation
└── C2: Benchmark diff tooling (done; see HISTORY#092)

Phase 2 (Dashboard enhancement)
├── A2: Benchmark progress bar
├── A3: ASCII sparkline graphs
├── A1: NL→MIRL compilation animation
└── A6: Presentation mode

Phase 3 (Benchmark credibility)
├── C1: Holdout suites (done; see HISTORY#092)
├── C5: Cross-machine reproducibility
├── C4: Adversarial testing
└── C3: Gold standard benchmarks (BEIR/MTEB)

Phase 4 (Model integration)
├── D1: SEAM as Claude tool set
├── A5: Chat tab in dashboard
└── D2: Auto-compression pipeline

Phase 5 (Scalability)
├── D3: Batch compile
├── A4: Vector visualization
├── E1: PgVector migration helper
└── E3: REST API surface

Phase 6 (Architecture)
└── E2: Multi-tenant namespacing
```

---

## SOP: Approach Rules for Every Track

These rules apply to every piece of work on this repo, regardless of track.

1. **Tests before merge.** Every new feature needs at least one test before it lands. No exceptions.

2. **No benchmark claims without bundle verification.** Any improvement to retrieval or compression must be backed by a verified JSON bundle in `benchmarks/runs/`.

3. **SQLite stays canonical.** PgVector, Chroma, and any future vector store are derived retrieval layers. The source of truth is always SQLite.

4. **Aliases before removals.** When renaming a command, add the new name and keep the old as an alias. Only remove old names after a deprecation cycle with a warning.

5. **Optional extras for heavy dependencies.** ML libraries, Postgres drivers, watch daemons — all go behind optional extras. The base install must stay lean.

6. **Update the ledger.** Every session that changes direction or completes a milestone must update `REPO_LEDGER.md` and `PROJECT_STATUS.md`.

7. **Handoff block.** Every session that ends mid-work must leave a handoff block in `REPO_LEDGER.md` so the next Claude session can resume without re-reading the full conversation.

8. **Lossless is sacred.** The lossless roundtrip must always pass SHA-256 verification. Any change to compression/decompression must re-run `seam demo lossless` and verify the output.

9. **Doctor must pass.** After any install-path change, `seam doctor` must return PASS. If it doesn't, that's a blocker.

10. **Benchmark diff before claiming improvement.** Use `seam benchmark diff` before publishing any improvement claim. Numbers alone are not enough — show the delta.
