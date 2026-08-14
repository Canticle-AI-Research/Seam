# SEAM Complete Timeline — #001–#559 (2026-04-15 → 2026-08-12)

Generated 2026-08-12 by the whole-repository deep audit. Per-entry digests were extracted by bounded timeline lanes from HISTORY.md (the repo's append-only event stream, newest-first) and cross-checked against HISTORY.md directly for the four gap entries not covered by any lane (#133, #343, #439, #486). Companion document: `docs/audits/2026-08-12-full-repo-audit.md`. This file is derived documentation, not a protocol record — HISTORY.md stays authoritative; any conflict between this table and HISTORY.md resolves in favor of HISTORY.md.

Corrections carried: HISTORY#538 inverted the LoCoMo competitive standing — the mem0-paper numbers are gpt-4o-mini throughout (paper: 67.13/51.15/72.93/55.51 across the four categories), and SEAM leads all four reported metrics; the earlier #429 “matched run tops mem0 on NOTHING” framing is superseded, and the Era 4 ARC text below carries the corrected standing inline.

## Era 1 — Bootstrap, roadmap blitz, and compression pivots (#001–#133, 2026-04-15 → 2026-05-06)

<ARC: bootstrap era (retrieval orchestrator SQL+vector legs, SEAM-LX/1 lossless, installers, PgVector formally tested 54→62 green) → roadmap blitz (Tracks A-E, PLAN_LOG) → ~30-entry dashboard/Textual obsession (pane scrolling loops, palettes, chat models, PR-per-feature continuity bookkeeping) → protocol machinery (append-only HISTORY, context packs, verify_continuity, secret hygiene) → readable-compression pivot (SEAM-RC/1, 100% direct-read gates, LX/1 demoted) → Holographic Surface era (SEAM-HS/1 PNG surfaces, bw1/rgb/rgba32/rgba64, stored-surface gate 23/23 cases, 45/45 gates, source-available license).>

| # | date | status | summary |
|---|---|---|---|
| #001 | 2026-04-15 | done | Retrieval orchestrator: SQL+vector legs, merged ranking, RAG pack generation, optional Chroma backend; CLI terminology cleanup |
| #002 | 2026-04-15 | done | Renamed canonical package to experimental.retrieval_orchestrator; kept hybrid_orchestrator + legacy aliases as compat layers |
| #003 | 2026-04-15 | done | Runtime-connected dashboard command: compile/search/plan/retrieve/index/trace/stats actions; scripted smoke tests; bad paths contained |
| #004 | 2026-04-15 | done | SQLite retrieval leg moved to SQL-side filters (id/kind/ns/scope/predicate/subject/object), lexical gating, ordering, indexes |
| #005 | 2026-04-15 | done | Context views (pack/prompt/evidence/summary/records), ranked candidates + payloads in RAG shape; wired into CLI and dashboard |
| #006 | 2026-04-15 | done | SEAM-LX/1 lossless machine-text format: reversible codecs, SHA-256 roundtrips, token/byte-savings benchmarks; CLI + regression tests |
| #007 | 2026-04-16 | done | Packaging: pyproject editable install, seam/seam-benchmark scripts, demo lossless, PS1+Linux installers, seam doctor; Windows e2e verified |
| #008 | 2026-04-16 | done | Six-family glassbox benchmark engine: bundle/case/fixture hashes, SQLite persistence, run/show/verify CLI; tamper detection verified |
| #009 | 2026-04-16 | done | Refreshed CLAUDE.md + added GEMINI/ANTIGRAVITY guides; SEAM_BENCHMARK_BLUEPRINT_V1.md; aligned READMEs/memory with benchmark policy |
| #010 | 2026-04-17 | done | PgVector stabilization: fixed Postgres 18 volume/credential issues via docker-compose PGDATA; DSN URL-encoding for email usernames |
| #011 | 2026-04-17 | done | Multi-track eval engine + SBERT support; proved SEAM-LX/1 machine text keeps 100% neural retrieval recall; benchmark registry started |
| #012 | 2026-04-17 | done | FakePgVectorAdapter + PgVectorAdapterTests: DDL/index/upsert/search/roundtrip proven offline; 54 tests green |
| #013 | 2026-04-17 | done | SEAM_PGVECTOR_DSN env pickup; doctor checks live PgVector + psycopg/sentence_transformers deps; 55 tests green |
| #014 | 2026-04-17 | done | Added InstallerLinuxTests (shim, PATH/profile injection, dedup); doctor test updates; 62 tests green |
| #015 | 2026-04-17 | done | Fixed CRLF in install_seam_linux.sh (dash set -eu), added .gitattributes; full install verified on Ubuntu WSL2 Python 3.12.3 |
| #016 | 2026-04-17 | done | Plan closeout (sessions 1-10): compile-nl/dsl to MIRL, verify, SQLite persist, vector index, search/trace/pack/reconcile/transpile/export working |
| #017 | 2026-04-17 | done | Plan closeout: retrieval/context pipeline - structured+vector legs, merged ranking, context views, Chroma optional backend |
| #018 | 2026-04-17 | done | Plan closeout: SEAM-LX/1 lossless compression with SHA-256 integrity, codec search loop, demo lossless verified |
| #019 | 2026-04-17 | done | Plan closeout: PgVector formal testing (FakePgVectorAdapter, 6 tests), DSN env support, doctor status; 62 tests green |
| #020 | 2026-04-17 | done | Plan closeout: Windows installer e2e - commands, doctor smoke, launch/persistence/lossless demo/dashboard verified |
| #021 | 2026-04-17 | done | Plan closeout: Linux installer e2e - CRLF fix, .gitattributes eol=lf, python3.12-venv prereq, WSL2 Ubuntu install verified |
| #022 | 2026-04-18 | done | Added pyproject optional-dependencies: pgvector, sbert, all-extras groups; base install stays lean |
| #023 | 2026-04-18 | done | Dashboard review pass: fixed vector adapter/DSN rows, local (neural) mode, two-column command table, header/tab polish; 62 tests |
| #024 | 2026-04-18 | done | Created ROADMAP.md: 5-track improvement plan (UI, terminology, benchmark hardening, model skills, architecture) with SOPs |
| #025 | 2026-04-18 | done | Ledger update: all session milestones into REPO_LEDGER.md + next-session handoff block; commit cbc6aa4 |
| #026 | 2026-04-18 | done | ROADMAP recorded: Tracks A-E, 6-phase priority sequence, 10 SOP rules; commit cbc6aa4 |
| #027 | 2026-04-18 | done | Created PLAN_LOG.md append-only plan history, seeded with all plans from project start through 2026-04-18 |
| #028 | 2026-04-18 | planned | Roadmap A1: NL to MIRL compile animation - live streaming record creation with typewriter pops; must not break --snapshot |
| #029 | 2026-04-18 | planned | Roadmap A2: benchmark progress bars + live recall@k/token savings per family during benchmark run |
| #030 | 2026-04-18 | planned | Roadmap A3: ASCII sparkline graphs of last 10 benchmark runs per family from SQLite |
| #031 | 2026-04-18 | planned | Roadmap A5: chat tab with Claude model - SEAM context retrieval + Claude responses, SEAM tools callable; anthropic extra |
| #032 | 2026-04-18 | planned | Roadmap A6: presentation mode --present - full-screen animated benchmark score bars, auto-refresh from persisted runs |
| #033 | 2026-04-18 | planned | Roadmap B1: terminology audit - knowledge-OS naming (compile-nl to remember, search to find), keep compatibility aliases |
| #034 | 2026-04-18 | planned | Roadmap B2: argument consistency - consolidate backend flags to --backend, standardize --budget |
| #035 | 2026-04-18 | planned | Roadmap B3: README consolidation - installers/README operator entry, benchmarks/README, root index |
| #036 | 2026-04-18 | planned | Roadmap C1: holdout suites never used in dev; --holdout flag; separate benchmark_holdout_runs table |
| #037 | 2026-04-18 | planned | Roadmap C2: benchmark diff tooling - seam benchmark diff <a> <b> with per-case green/red deltas |
| #038 | 2026-04-18 | planned | Roadmap C3: gold-standard BEIR/MTEB/MS-MARCO benchmarks via adapters in benchmarks/external/ |
| #039 | 2026-04-18 | planned | Roadmap C4: adversarial suite - malformed MIRL, adversarial queries, Unicode edge cases, concurrent writes |
| #040 | 2026-04-18 | planned | Roadmap C5: cross-machine reproducibility - locked reference_run.json, benchmark verify --reference tolerance checks |
| #041 | 2026-04-18 | planned | Roadmap D1: SEAM as Claude tool set - seam_compile/search/context/compress/stats tool_use functions + SeamToolExecutor |
| #042 | 2026-04-18 | planned | Roadmap D2: auto-compression seam watch - watch dir to compress to compile to persist to index; watchdog extra |
| #043 | 2026-04-18 | planned | Roadmap D3: batch compile seam batch-compile <glob> via ThreadPoolExecutor + rich progress + summary JSON |
| #044 | 2026-04-18 | planned | Roadmap E1: PgVector migration helper seam migrate-vectors --to pgvector with row-count verification |
| #045 | 2026-04-18 | planned | Roadmap E2: multi-tenant namespacing - tenant_id column on ir_records + --tenant flag on CLI commands |
| #046 | 2026-04-18 | planned | Roadmap E3: REST API seam serve - FastAPI endpoints /compile /search /context /stats /health, bearer token auth |
| #047 | 2026-04-18 | planned | True interactive TUI plan: migrate Rich.Live dashboard to Textual - live panels, in-place input, independent scrollable boxes, seam-dash entrypoint |
| #048 | 2026-04-20 | done | Phase 1 context-memory migration: history tooling restored, HISTORY.md + indexed hash verification seeded, PLAN_LOG.md removed; startup under 2k tokens |
| #049 | 2026-04-20 | done | A0 Textual baseline: interactive dashboard with persistent input + scrollable panels; Rich snapshot kept; seam-dash entrypoint; tests |
| #050 | 2026-04-20 | done | A0 continued: tab bar rendering/refresh, side panel syncs to runtime/benchmark tabs, tab-switch tests, Track F docs roadmap |
| #051 | 2026-04-20 | done | Dependency/docs hardening: installed textual, pinned rich>=14.2,<16; added setup.md/errors.md/howto docs; doctor + Textual tests pass |
| #052 | 2026-04-20 | done | Dashboard expansion: logo header, chat panel, command history, MIRL animation, token/db bars; /model /cmd /hybrid + !/? shortcuts; chat client |
| #053 | 2026-04-20 | done | Dashboard polish: density, /savechat + /export-chat JSONL transcripts, command status badges with ms/s timing, empty-chat guards; tests |
| #054 | 2026-04-20 | done | Layout rework per request: clean engine header, chat full-width above input, per-panel scroll, runtime log in middle row; tests updated |
| #055 | 2026-04-20 | done | Visual loop: brighter cyan/blue SEAM brand header; chat row kept; focusable scrollable panels; new screenshot artifact |
| #056 | 2026-04-20 | done | Pane ergonomics: focus + keyboard scrolling (arrows/PgUp/j/k), auto-follow to latest, retention 200 to 2000 lines, compact layout |
| #057 | 2026-04-20 | done | Fixed pane scrolling: Static to Log scrollback panes, click-focus + key bindings, 2000-line retention; screenshot shows independent scrollbars |
| #058 | 2026-04-20 | done | Finalized Log-based pane scroll: pane-local keys, runtime event history 10 to 2000, teardown-safe timer guards; scroll_y proof run |
| #059 | 2026-04-20 | done | Added pane PageUp/PageDown scroll regression at realistic terminal size; snapshot integrity re-verified before handoff |
| #060 | 2026-04-20 | done | Hybrid chat-bar routing: bare commands execute, plain text chats, ! shell, ?? forced chat; ?agent/?shell/?seam/?model shortcuts; cwd helpers |
| #061 | 2026-04-21 | done | Published seam_runtime/ui/ primitives (theme/logo/bars/animations) + mature branding assets; dashboard wired to UI layer; snapshot verified |
| #062 | 2026-04-21 | done | Windows launcher audit: bat was launching repo .venv/DB; fixed to prefer seam-dash.exe + %LOCALAPPDATA%\SEAM DB; verified attach |
| #063 | 2026-04-21 | done | Global dashboard install fix: seam-dash shim (Win+POSIX), include_dashboard=True installs [dash]; 5 installer tests; 81 tests passing |
| #064 | 2026-04-25 | done | Added Codex-facing seam_runtime/config.toml: high reasoning, memories enabled, token-frugal standby policy, skills on demand |
| #065 | 2026-04-25 | done | Moved launch_dashboard.bat into scripts/windows/, repo-root aware, prefers .venv seam-dash.exe; README links; --help verified |
| #066 | 2026-04-25 | done | Brought pgvector online: docker pgvector:0.8.2-pg18-trixie, port moved 5432 to 55432, stale volume recreated; doctor reachable; real indexing verified |
| #067 | 2026-04-25 | done | Dashboard launcher propagates pgvector: PowerShell reads local .env to conninfo DSN (secrets not printed); snapshot shows pgvector adapter |
| #068 | 2026-04-25 | done | MIRL compression animation settles after completion: idle static, stable final frames; timer stops panel updates; unit test + snapshot |
| #069 | 2026-04-25 | done | Added prefix command palettes: / SEAM commands, ! shell helpers, ? mode shortcuts; typed filtering ranks prefix matches; tests |
| #070 | 2026-04-25 | done | Slash palette now real slash commands (/compile /retrieve /stats /agent /shell /model /savechat /quit) in multi-column grid; /stats executes |
| #071 | 2026-04-25 | done | Expanded dashboard chat defaults with OpenRouter agent models (Qwen, DeepSeek, MiMo, Kimi, GLM, Claude, Gemini, Pareto) |
| #072 | 2026-04-25 | done | Added Grok 4.20 / 4.20 Multi-Agent / 4.1 Fast / Grok Code Fast 1 to dashboard chat defaults + regression coverage |
| #073 | 2026-04-25 | done | Added Gemma 4 (31B/26B, free routes) to chat defaults; kept Grok + OpenRouter sets; regression tests; snapshot verified |
| #074 | 2026-04-25 | done | Documented OpenRouter model switching for Win PowerShell + Linux/WSL2: env vars, ?models/?model, SEAM_CHAT_MODELS override |
| #075 | 2026-04-25 | done | Split active docs (docs/README.md) from archive (docs/archive/): old UI handoff moved; Documentation Separation Policy in ledger |
| #076 | 2026-04-25 | done | Code separation: archive/ for inactive code, docs/CODE_LAYOUT.md active map, Code Separation Policy; generated build moved to archive |
| #077 | 2026-04-25 | done | Agent context boundaries: AGENTS.md startup reads + .rgignore skip archive/build/.venv/generated/cache paths; tests pass |
| #078 | 2026-04-26 | done | Repo hygiene: no-session-link/no-secret rules; POSTGRES_PASSWORD from local .env; throwaway guarded-runner passwords; repo scan clean |
| #079 | 2026-04-26 | done | Temporal Chain continuity rules + ledger/status update triggers; CLAUDE.md history duties; Temporal Continuity Policy recorded |
| #080 | 2026-04-26 | done | Token-bounded history tooling: build_context_pack (budgeted selection) + verify_continuity (integrity/supersedes/snapshot/secret checks) |
| #081 | 2026-04-26 | done | High-confidence secret/session scan across repo + local .env; neutralized .env to placeholders; verify_continuity OK |
| #082 | 2026-04-26 | done | Deleted local .env; new rule: delete/redact discovered secret artifacts immediately; rescan zero findings; continuity OK |
| #083 | 2026-04-26 | done | Moved PgVector credentials out of repo: launcher loads from SEAM_LOCAL_ENV or Documents\SEAM\local\.env; 108 tests credential-free |
| #084 | 2026-04-26 | done | Guarded real-adapter run on 55433 (sqlite/Chroma/PgVector/doctor/retrieval/full pytest passed); stopped stale seam-pgvector container freeing 55432 |
| #085 | 2026-04-26 | done | Added docker to controlled history topic vocabulary after stale pgvector container cleanup; AGENTS.md updated |
| #086 | 2026-04-26 | done | Data routing: routing_manifest.json, DATA_ROUTING.md + topic ledgers, verify_routing, context-pack --route, taxonomy in continuity gate |
| #087 | 2026-04-26 | done | Codified readable-lossless architecture direction: compressed artifact must be directly readable AI machine language; LX/1 demoted to integrity backing |
| #088 | 2026-04-26 | done | SEAM-RC/1 readable compression slice: META/CHUNK/ORDER/QUOTE/INDEX records, query without rebuild, CLI commands; 113 tests, exact QUOTE hit |
| #089 | 2026-04-26 | done | SEAM-RC/1 benchmark gate in run readable/all: exact rebuild/hash, quote spans, term coverage, direct readable-query; 115 tests |
| #090 | 2026-04-26 | done | Hardened RC/1 gate to 100% direct-read: recipe case direct_text/exact rate 1.0; query normalization; direct_text=direct_read=100% |
| #091 | 2026-04-27 | done | Dashboard wired to SEAM-RC/1 (compress/query/rebuild + palettes); fixed Windows path splitting (backslash-safe); 129 tests |
| #092 | 2026-04-27 | done | Benchmark diff + holdout: seam benchmark diff joins by case_hash, --holdout publish-only fixtures fail closed; 133 tests |
| #093 | 2026-04-27 | done | Fixed post-verification gap: restored write_holdout_benchmark_bundle export CLI imported but benchmarks lacked; 133 tests |
| #094 | 2026-04-27 | done | REST API: guarded FastAPI server.py, seam serve; /health /stats /compile /search /context /compress /persist; bearer auth + rate limit; 135 tests |
| #095 | 2026-04-28 | done | Benchmark gate finished: seam benchmark gate CLI + Windows CI workflow; 138 tests, 36/36 checks; removed lossless-savings rule from default gate |
| #096 | 2026-04-28 | done | Fixed first PR CI failure: Windows runner lacked pytest; workflow installs pytest explicitly before tests |
| #097 | 2026-04-28 | done | Added dashboard reload/refresh command: rebuilds orchestrator + metrics, refreshes surfaces, Reload payload; 140 tests; branch-local |
| #098 | 2026-04-28 | done | Committed dashboard reload locally as c0039fa; staged only publish scope (ALPHA-0-ARG left untracked); 140 tests |
| #099 | 2026-04-28 | done | Post PR #9 integration: README rewrite, ingest --persist, memory search/get, retrieve graph/vector/mix modes, MCP stdio serve, reindex stale detection |
| #100 | 2026-04-28 | done | Removed literal password-bearing DSN from installers README; operators set SEAM_PGVECTOR_DSN from private env; secret scan clean |
| #101 | 2026-04-28 | done | Repaired post-merge continuity hash drift for #099/#100 after PR #10; rebuilt HISTORY_INDEX + fresh snapshot |
| #102 | 2026-04-28 | done | Post-PR #11 merge at 2bc3e3c: rebuilt continuity metadata after #101 hash drift; 143 tests passed |
| #103 | 2026-04-28 | done | Repaired main continuity: backup-branch snapshot shadowed main's; rebuilt metadata; noted empty _imports/awesome-design-md leftover |
| #104 | 2026-04-29 | done | Fixed Textual/Dash reload blocker: removed call to deleted _refresh_explorer; regression asserts #explorer-tree; 143 tests |
| #105 | 2026-04-29 | done | Post-PR #7 merge bookkeeping: ExplorerTree/status-bar dashboard + reload fix on main; PROJECT_STATUS updated; continuity rebuilt |
| #106 | 2026-04-29 | done | Rebased SEAM-CC dashboard P0 polish onto origin/main: RichLog colored panels, Settings tab + API, store lists; kept explorer-tree |
| #107 | 2026-04-29 | done | Post-PR #12 merge 147210c: P0 polish (RichLog colored panels, Settings tab) on main; 145 tests; continuity rebuilt |
| #108 | 2026-04-29 | done | P1 focus-zoom: Ctrl+M toggles zoom overlay on panels/explorer; 146 tests; deferred batch-compile to DB-tree design question |
| #109 | 2026-04-30 | done | PR #13 merged d9645f9 via admin bypass (main ruleset): focus zoom on main; 146 tests pre-merge; continuity rebuilt |
| #110 | 2026-04-30 | done | SEAM-HS/1 Holographic Surface: PNG encode/decode/verify/query (rgb24/bw1), SHA-256 exactness; surface CLI + benchmark; suite moved to Test-Seam-All; 152 tests |
| #111 | 2026-04-30 | done | Fixed surface context UnicodeEncodeError on UTF-8 BOM payloads: pretty output via UTF-8 _print_text helper; 152 tests, 100% exactness |
| #112 | 2026-04-30 | done | Added seam surface compile (source to MIRL to PNG, --persist optional) + explicit rgba32 4-channel density mode; 154 tests; 3/3 cases 100% |
| #113 | 2026-04-30 | done | Post-PR #14 merge 63d1339: HS/1 flow on main; recorded index/snapshot drift for #109-#112 before rebuilding derived artifacts |
| #114 | 2026-04-30 | done | Recovered Claude settings-overhaul draft into real dashboard: new layout, Chat tab, expanded Settings (keys/embeddings/REST/pgvector/surface); 157 tests |
| #115 | 2026-04-30 | done | Fixed empty SEAM_LOCAL_ENV resolving to '.' (repo root as env file); shared local-env candidate helpers; 157 tests |
| #116 | 2026-04-30 | done | Replaced AGPL with SEAM Source-Available License (hosted/commercial use needs written license); contributor-grant clauses; benchmark-proof framing |
| #117 | 2026-04-30 | done | License wording clarified: commercial use available via separate written license, not permanently forbidden; LICENSE/NOTICE/README/ledger aligned |
| #118 | 2026-04-30 | done | Fixed Settings tab scroll (max_scroll_y=0): panel height to auto so container scrolls full form; regression proves scroll to end (149/149) |
| #119 | 2026-04-30 | done | Overview is now live health surface: color bars for DB/pgvector/API/REST/settings, pgvector status to Overview, scroll preserved; 26 Textual tests |
| #120 | 2026-04-30 | done | PROJECT_STATUS updated pre-publish: names live Overview health bars + scrollable Settings behavior |
| #121 | 2026-04-30 | done | PR #16 merged 4363298 via gh pr merge --admin: settings health Overview + source-available license on main; 160 tests pre-merge |
| #122 | 2026-05-01 | done | Track G visual-memory roadmap: docs to MIRL/RC to HS/1 PNG to direct surface query without restore/import; SQLite stays canonical for active memory |
| #123 | 2026-05-02 | done | Test artifacts routed out of repo root: test_seam/ uuid DBs ignored; moved 38 leftovers; root count 0 |
| #124 | 2026-05-04 | done | Merged PR #17 repo-protection (CODEOWNERS, license boundary, SECURITY.md) with visual-memory roadmap; conflict kept both; 160 tests |
| #125 | 2026-05-04 | done | Fixed CI path fallout: workflow still referenced retired Test-Seam-All path (0 tests collected); updated to test_seam_all; 160 tests |
| #126 | 2026-05-06 | done | HS/1 surface-library adapters: inspect PNGs into SQLite surface_artifacts (hs:<hash> IDs), store/list/show, stored-ID decode/query/import; 161 tests |
| #127 | 2026-05-06 | done | HS/1 redundancy + pixel modes: SurfaceFileAdapter redundant copies (.seam/surfaces), rgb alias, rgba64 16-bit; 163 tests; 4/4 exactness 1.0 |
| #128 | 2026-05-06 | done | Merged hs1-surface-adapters into main (10a6336+f754fc7): 4 pixel modes, redundant copies, metadata, CLI flows; 163 tests pre-merge |
| #129 | 2026-05-06 | done | HS/1 surface repair: seam surface repair hs:<id> restores missing/mismatched redundant copies; explicit FAIL/unavailable states; 165 tests |
| #130 | 2026-05-06 | done | Merged hs1-surface-repair into main (4d0a435+414f883); 165 tests, 4/4 benchmark surface exactness |
| #131 | 2026-05-06 | done | Stored-surface benchmark gate: store to delete original to query to repair to query at 1.0 rates; 23/23 cases, 45/45 gates; corrected surface-only gate SOP |
| #132 | 2026-05-06 | done | Merged stored-surface benchmark into main (d8cfb2c+8dd2ec3); 139 unit tests, 23/23 cases, 45/45 gates; fixed PowerShell && staging error |
| #133 | 2026-05-06 | done | Append-only correction to #132 bookkeeping: structured commits field accidentally repeated d8cfb2c; intended chain d8cfb2c+8dd2ec3 recorded; verification unchanged |

## Era 2 — Multi-agent surfaces, hardening engine, and the benchmark program (#134–#245, 2026-05-07 → 2026-05-25)

<ARC: multi-agent integration (MCP 3→12 tools, JSON-RPC stdio, Gemini CLI connects, pgvector bootstrap) → skill chains + commit gates + Track H1 Context Streams (88-94% bloat reductions measured) → visual-memory loop + WebUI (Kimi Vite rewrite audited, restored, bug passes) → audit/hardening engine (dedup sweeps, parallel agent audits, DeepSeek SOP loops) → external-memory benchmark program (Track I SOPs 0-4: LoCoMo adapter, LLM judges, Mem0/Zep comparators; BIL sealing; paid LoCoMo Step 0b recall 0.289; no-paid retrieval 0.359→0.528) → protocol governance (Advisor/Executor, stale-branch prevention).>

| # | date | status | summary |
|---|---|---|---|
| #134 | 2026-05-07 | done | Merged origin/main into local main (5b710bb); remote adds AGENT_COMPILER.md plan to compile SEAM protocol into agent adapters |
| #135 | 2026-05-07 | done | Repo handoff refresh for fresh Linux resume: status/roadmap/setup/README updated, Linux resume checklist added |
| #136 | 2026-05-07 | done | Correction: snapshot JSONs are gitignored local state; setup now regenerates snapshot before continuity verification |
| #137 | 2026-05-07 | done | Recorded dashboard+CLI product direction; landed `seam shell`/`seam chat` REPL with /remember /search etc + CI-testable --once; 166 tests |
| #138 | 2026-05-07 | done | MCP bridge expanded 3 to 10 agent-safe tools (stats/documents/context/doctor/surface/benchmark); 142/142 tests; pgvector error redaction |
| #139 | 2026-05-07 | done | MCP slice 2: doctor.py extracted, surface_query/decode tools, hs:hex-only refs, pagination wrappers, TOOL_METADATA; 144/144 tests |
| #140 | 2026-05-07 | done | Merged Claude worktree MCP expansion into main, tightened dispatcher validation (blank-search rejection, budget bounds); 170 tests |
| #141 | 2026-05-08 | done | Added .opencode/skills/seam-session-closeout skill defining the repo-changing session closeout workflow |
| #142 | 2026-05-08 | done | Built .opencode skill chain (navigator/executor/test-hardener/ledger-updater/sync-auditor) enforcing no-hand-edited-index rule |
| #143 | 2026-05-08 | done | Added seam-github-publisher skill: explicit path staging, secret scans, safe commit messages, push verification |
| #144 | 2026-05-08 | done | Docs refreshed after surface-gate audit: 7 release-blocking surface metrics, rgba64, public-fixture policy; G1 in-progress, G2/G3 done |
| #145 | 2026-05-08 | done | Visual-memory loop landed: _structural_quote_spans extractor + precision-aware gate, 3 richer fixtures; 174/174 tests, gate 45/45 |
| #146 | 2026-05-08 | done | Operator docs consistent with #145: paired Win/Linux runbooks, PgVector port 55432 fix, ROADMAP G1 implemented |
| #147 | 2026-05-08 | done | README polished: cross-platform command blocks, surface+mcp commands, measure-progress loop section; 174/174 tests |
| #148 | 2026-05-08 | done | Standards-compliant MCP JSON-RPC server (mcp_protocol.py) + `seam mcp stdio`; Gemini CLI connects; 175/175 tests |
| #149 | 2026-05-08 | done | pgvector_bootstrap auto-starts Docker pgvector (port 55432) for MCP server via --ensure-pgvector; 176/176 tests |
| #150 | 2026-05-08 | done | Documented ignored test_seam/ artifact sink (557 stray .db files) in AGENTS.md and CODE_LAYOUT; 176 tests collected |
| #151 | 2026-05-08 | done | Ran seam doctor + index status; fixed index staleness via seam index; reconciled PROJECT_STATUS to handoff #150 |
| #152 | 2026-05-08 | done | Bookkeeping supersede: holdout benchmark suites card from #036 marked done (implemented per #092) |
| #153 | 2026-05-08 | done | Bookkeeping supersede: benchmark diff tooling card from #037 marked done (`seam benchmark diff`, #092) |
| #154 | 2026-05-08 | done | Bookkeeping supersede: REST API surface card from #046 marked done (seam serve, #094); dashboard wiring deferred |
| #155 | 2026-05-08 | done | Repo hygiene: Recommended Course updated, 9 merged branches deleted, stale worktrees removed, snapshot retention policy |
| #156 | 2026-05-08 | done | Verified #155 closeout: integrity/routing/continuity OK, 176 tests collected; 3 dirty SEAM-CC worktrees intentionally kept |
| #157 | 2026-05-09 | done | Kimi converts experimental/webui CDN prototype to Vite+React+TS app wired to REST API; 7 vitest tests; prototype archived |
| #158 | 2026-05-09 | done | Audited Kimi conversion: added CORS, apiClient hardening (11 tests), headless Chrome smoke pass; removed scaffold leftovers |
| #159 | 2026-05-09 | done | Restored original IDE dashboard shell as prototype target; documented regression in RESTORE_NOTES; 11 tests |
| #160 | 2026-05-09 | done | WebUI Bug Pass 1: clickable provenance graph nodes with detail cards, working terminal command menu |
| #161 | 2026-05-09 | done | WebUI Bug Pass 2: / command palette overlay with WIRED vs CLI-ONLY labels; CLI-only commands blocked in browser |
| #162 | 2026-05-10 | done | Prepared WebUI restore branch codex/webui-restore-command-palette for publish; 177 tests; PR #20 merge planned |
| #163 | 2026-05-10 | done | Post-merge continuity repair after PR #20 (ce2a4b6): rebuilt index/snapshot because entry hashes 158-162 mismatched |
| #164 | 2026-05-13 | done | PR sorting audit: #22/#23 open-mergeable, #19 has private session-link material, #18 doc salvage; main clean vs origin |
| #165 | 2026-05-15 | done | Designed Context Streams Protocol (Track H): multi-stream generalization of history pattern; H1-H4 phases; ~480-line design doc |
| #166 | 2026-05-15 | done | Protocol catch-up: recorded #165 revision pass (cross-index derived, no Phase-1 path move) + commit 4cde6e5 push; howto count fix |
| #167 | 2026-05-15 | done | Claude Code commit gate: PreToolUse + SessionStart hooks run verify chain before git commit; ledger Temporal Continuity Policy |
| #168 | 2026-05-15 | done | Scope correction: .claude/settings.json stays operator-local (pre-commit blocks it); tracked scripts, per-operator wiring |
| #169 | 2026-05-15 | done | Canonical cross-agent git pre-commit hook + install.sh (symlink/copy fallback); seam doctor commit_gate field |
| #170 | 2026-05-15 | done | Track H1 implemented: tools/streams package, byte-equal history mirrors, roadmap parser, cross_index, verify_streams gate; 8/8 tests |
| #171 | 2026-05-15 | done | H1 gaps closed: 34 roadmap markers across all tracks, generic stream context pack; bloat reductions measured 93.5/90.5/91.0% |
| #172 | 2026-05-15 | done | Added recorded-fact discrepancy gate: scoped test-count claims audited (151+6 static); earlier 177 was different scope; 32 history tests |
| #173 | 2026-05-15 | done | Ubuntu .venv setup on exFAT drive (lib64 workaround); npm --no-bin-links scripts; 183 tests pass |
| #174 | 2026-05-16 | done | Audit findings resolved: sentence-scoped count claims, repo-root normalization, snapshot latest_entry_id, archive cleanup; 187 tests |
| #175 | 2026-05-16 | done | Final mixed-line count audit: active-claim-segment evaluation + regression coverage; 189 tests |
| #176 | 2026-05-16 | done | Session handoff: H1 substrate done, all 4 gates pass with recorded-fact audit; infinite-indexer decision deferred (extend H1) |
| #177 | 2026-05-16 | done | Cross-audit dedup sweep: 60 findings to 47, 8 dropped wrong, 22 fixed (WAL, sha256 pack_id, hmac compare, bind 127.0.0.1, --dev installer); 192 tests |
| #178 | 2026-05-16 | done | Merged PR #22 external memory benchmark registry + runner; fixed shlex/strict-policy/POSIX-skip bugs; CI widened; 202 tests |
| #179 | 2026-05-16 | done | Merged PR #18: salvaged 4 operator docs (PGVECTOR_LOCAL, BENCHMARK_SOP, OPERATOR_GUIDE, ENGINEERING_LOG) via rebase |
| #180 | 2026-05-16 | done | Merged PR #23 roadmap harvest: PR Track H renamed Track L (collision with Context Streams); added Tracks I/J/K/L |
| #181 | 2026-05-16 | done | Runtime/API hardening C1-C6: bounded trace, streaming vector search, rate-limiter purge, body limit 413, bind refusal, persist rollback; 162 tests |
| #182 | 2026-05-16 | done | H-track hardening via 9 parallel agents: model load lock, embed retry/backoff, reconcile tie-break, bounded memory_get, edge delete; 225 tests |
| #183 | 2026-05-16 | done | Corrected #182 false-positive claims: MCP lazy-imports retrieval_orchestrator; context pack refs now match budgeted entries |
| #184 | 2026-05-17 | done | Audit/closeout: committed HISTORY#183 patch (8bee677), pushed main, clean 0/0; 230 tests pass |
| #185 | 2026-05-17 | done | Track I SOP 0: `seam bench external` CLI (--plan/--strict/--scope/--quickstart reserved); 12 tests; registry pre-existing |
| #186 | 2026-05-17 | done | Cherry-picked SOP 1-4 handoff docs (LoCoMo adapter, LLM judge, Mem0, Zep comparators) from PR #24; docs-only |
| #187 | 2026-05-17 | done | SOP 1: SEAM LoCoMo adapter + shared scaffold + 10-case quickstart fixture (~5s, stable hash); 213 tests; string-match scoring |
| #188 | 2026-05-17 | done | SOP 2: optional LLM-as-judge (Stub/Claude/OpenAI judges) behind seam[bench-judge]; 224 tests; 60s quickstart gate kept |
| #189 | 2026-05-17 | done | SOPs 3+4: Mem0 + Zep/Graphiti comparator adapters behind optional extras; 3-way scoring reproducible; 252 tests; Track I complete |
| #190 | 2026-05-18 | done | Audit+merge closeout for SOPs 3+4: PR #29 squash-merged (dc9b09d); Track I SOPs 0-4 on main; 252 tests |
| #191 | 2026-05-18 | done | Production readiness remediation P1-P7: history file lock, conftest fixtures, Linux CI, 28 coverage tests (286), assertTrue scrub, 49 seam:items |
| #192 | 2026-05-18 | done | Closeout follow-up: verify_streams stale cross-index detection, 3 TDD tests, tracked untracked SOP ref file |
| #193 | 2026-05-18 | done | Filed Track F backlog card for ref-file existence continuity check (seam:item 50); 341 tests |
| #194 | 2026-05-18 | done | Windows CI fix: added process-local threading.Lock around OS lock in new_entry.py for same-process thread serialization |
| #195 | 2026-05-18 | done | Correction: Windows lock conflict was on HISTORY_INDEX.md itself; moved OS lock to .git/seam-history.lock sidecar path |
| #196 | 2026-05-18 | done | Track K memory-trust spine: K14-K18 roadmap cards + addendum; PR #30 squash-merged (decd1dd); 55 seam:items |
| #197 | 2026-05-18 | done | Deep-audit fixes: RateLimiter lock, LX1 unknown-status ValueError, lazy dashboard import, benchmark temp-DB cleanup; 345 tests |
| #198 | 2026-05-18 | done | Deep-audit follow-up: load_ir pagination, MIRL line-context errors, snapshot pack metadata, remediation blueprint SOP; 348 tests |
| #199 | 2026-05-18 | done | P1-12: SQLiteVectorIndex pragmas (WAL, busy_timeout=5000, foreign_keys, synchronous=NORMAL); 349 tests |
| #200 | 2026-05-19 | done | P0-5: file-locked append_event (flock/msvcrt) with concurrent-append race regression; 350 tests |
| #201 | 2026-05-19 | done | P0-6: atomic cross-index + per-stream index rebuild via tmp+os.replace 3-phase commit; 351 tests |
| #202 | 2026-05-19 | done | Review fix: repointed atomicity test patch to streams_lib.STREAMS_ROOT (original was no-op false-positive); cleaned leak |
| #203 | 2026-05-19 | done | Integrated finished WebUI dashboard drop: public/ as Vite publicDir, REST endpoint proxy, /dashboard.html framing; no agents |
| #204 | 2026-05-19 | done | Deep-audit fixes: rollback failure reporting, lock-release deadlock, PowerShell quoting, 16-char index hash, 0600 env files; 356 tests |
| #205 | 2026-05-19 | done | Added DeepSeek Parallel Audit Execution SOP (worker lanes, calibration, test-first, MR prep) + ledger pointer; docs-only |
| #206 | 2026-05-19 | done | DeepSeek parallel audit: sole fix LX1 int/float type preservation (test-first); 358 tests; other claims deferred |
| #207 | 2026-05-19 | done | Reviewed and landed DeepSeek audit branch (dc77124); corrected #206 topic vocab; 358 tests; gates green |
| #208 | 2026-05-19 | done | WebUI batch hardening W1-W4: /tree traversal+DoS caps, /benchmark policy gate, honest sys-metrics, record-kind symbols; +22 audit tests |
| #209 | 2026-05-19 | done | Audit quick-wins: streams write fsync durability, .cursor/ gitignore, TestCountFact rename to silence collection warning |
| #210 | 2026-05-19 | done | CI hardening: 4 SEAM verify gates in ci.yml, expanded pytest scope to tools/streams+tests/, MCP stdio smoke; 395 passed |
| #211 | 2026-05-19 | done | CI bench-gate prep: sys_metrics poll-loop stabilization, real-postgres pgvector CI job, MCP tools/call smoke; 398 tests |
| #212 | 2026-05-19 | done | Codex audit: real stale-record mutation test, MCP smoke 5s timeouts, pack_ir persist=False default, restored hybrid_orchestrator shims; 404 tests |
| #213 | 2026-05-19 | done | Correction: MCP seam_context kept strictly read-only (persist arg conflicted with readOnlyHint); 405 tests |
| #214 | 2026-05-20 | done | Authored Track K BIL Phase 1 SOP+prompt: BIL-0..2 (inspect, result hash, input-manifest hash); BIL-3..6 deferred |
| #215 | 2026-05-20 | done | BIL Phase 1 closed: added manifest-vs-result consistency check (BIL-2 4/4 checks); 416 tests |
| #216 | 2026-05-20 | done | Tokenizer unification Stage 1: 4 word-count heuristics to cl100k_base; bloat savings re-measured (93.5 to 88.4%); 416 tests |
| #217 | 2026-05-20 | done | Repaired DeepSeek BIL/baseline patch: stable result hashes excluding timing, stub-seal refusal gate, baseline policy module; 429 tests |
| #218 | 2026-05-20 | done | Parallel remediation 7 lanes (A-G): rate-limiter token hashing, MCP redaction, CLM edge fixes, pgvector composite PK, token-budget pack, Vite proxies; 463 tests |
| #219 | 2026-05-20 | done | Never-skip-tests audit found 4 bugs: missing pgvector schema migration (P0), stats vector_entries bug, DSN test isolation, text-opacity issue; 467 tests |
| #220 | 2026-05-21 | done | Track M P0 repairs: bench external target routing, LoCoMo evidence text (recall 0.963), BIL-2 required before publication; 503 tests |
| #221 | 2026-05-21 | done | Official LoCoMo dataset support: numbered-session parser, answerless adversarial rows skipped; 1542-case dry-run; 511 tests |
| #222 | 2026-05-21 | done | Reviewed P3 fixes 6-9, 4 commits: chroma sync_on_search default False, orphan edge sweep, MCP line-cap rewrite, surface path containment |
| #223 | 2026-05-21 | done | Track M P2/P3 in 7 commits: RAW indexable kind, conversation-turn compile, BEAM/LongMemEval shapes, GPT-5 judge pin, live dashboard stats |
| #224 | 2026-05-21 | done | Stale-branch prevention: GitHub auto-delete on merge, scan_stale_branches.py 6-class classifier, AGENTS.md worktree nudge |
| #225 | 2026-05-21 | in-progress | Security/benchmark remediation slice: StubJudge abstains, /benchmark HTTP 400, atomic snapshot, sessionStorage tokens, shell gating; 57 tests; SIGINT on broad run |
| #226 | 2026-05-21 | done | Status-pointer closeout: PROJECT_STATUS points at #225 + SOP; continuity had rejected the stale pointer |
| #227 | 2026-05-21 | done | Final pointer closeout correcting #226 sequencing mistake; no code fixes |
| #228 | 2026-05-21 | done | Authored Track M P4 SOP: baseline real-judge LoCoMo measurement, then temporal scoring / cross-encoder rerank / embedding upgrade |
| #229 | 2026-05-22 | done | Committed #225 remediation + continuity rebuild (cross-index rotated to 0001-0084, 284 events); 4 gates green |
| #230 | 2026-05-22 | done | Added Advisor/Executor loop protocol: ADVISOR_* packet formats, review gates, DeepSeek ledger C6 escalation rule |
| #231 | 2026-05-22 | done | Added paste-ready Track M batch-judge prompt with ADVISOR_TASK_PACKET pre-inserted |
| #232 | 2026-05-22 | done | Judge Batch API Phase A: Claude/OpenAI score_batch (Anthropic Message Batches, OpenAI Batch), --judge-batch; 16 no-network tests |
| #233 | 2026-05-22 | done | P4 temporal-distance scoring: temporal.py ISO+relative date parser, exponential decay, retrieval ranking; 11 tests; no paid calls |
| #234 | 2026-05-22 | done | Fixed gpt-5/o answerer bug (temperature=0 HTTP 400, reasoning-token burn); live Batch API baseline: gpt-5-mini EM 0.70, F1 0.905 |
| #235 | 2026-05-23 | done | P4 Step 2 cross-encoder reranker with LRU model cache, --rerank flag; advisor review tightened tests; 11 tests |
| #236 | 2026-05-24 | done | LoCoMo replay disproved pack_json hypothesis; less abstention-prone answerer prompt + --save-context diagnostics |
| #237 | 2026-05-24 | done | Added answerer_diagnostics (finish_reason, token usage, 120-char preview) to distinguish budget-exhaust vs policy-abstain |
| #238 | 2026-05-24 | done | Paid full LoCoMo Step 0b: 1542 cases, 6.7h wall, context_recall 0.289, EM 0.014, judge_score 0.195, 1245 unknown; BIL-2 sealed |
| #239 | 2026-05-24 | done | Closeout repair: rebuilt index/mirror/cross-index/snapshot after venv-python and CLI-flag misuse in closeout commands |
| #240 | 2026-05-24 | done | No-paid retrieval slice: 100-case context_recall 0.359 to 0.495 (search_top_k=20, rank-preserving evidence, runtime+model caches) |
| #241 | 2026-05-24 | done | --keep-db ingest cache: warm 100-case 70s to 32s (2.2x), 10-case 8.95s; identical recall; durable result archive |
| #242 | 2026-05-25 | done | Fixed SQLiteStore.load_ir id-order preservation (red-green); no-paid 100-case context_recall 0.495 to 0.528 at k=20 |
| #243 | 2026-05-25 | done | Roadmap pivot: H2 improvement stream later to now, scoped to Track M retrieval-feedback subset; guardrails on negative stake |
| #244 | 2026-05-25 | done | H2 slice 1: append-only retrieval_event table in SQLiteStore with read/count API, stale_source flag, validation; 9 tests |
| #245 | 2026-05-25 | done | GitHub PR gates: repo-hygiene job, chroma real smoke, locomo quickstart BIL-2 CI job, PR template; no-paid CI policy in ledger |

## Era 3 — Ruleset, H2 self-improvement, MIRL rewrite, and density (#246–#343, 2026-05-25 → 2026-06-29)

<ARC: GitHub ruleset enforcement + Windows CI green-making slog → H2 self-improvement substrate + free loop build-out (writer, backfill, dev/holdout split, proposer, apply, free-LoCoMo scorer; Track-K gate MET #312) → security wave (shell argv hardening, SSRF allowlist, chromadb GHSA removal, CodeQL clearing with honest correction #299) → MIRL compiler rewrite (stub overfit exposed #303, spec governing contract, floor rewrite, Ollama extractor sr 0.333→1.0) → density campaign (~3.8x packs) + budget-starvation root cause (knee 100/8000, +0.14 judged) → competitive/packaging era (mem0 head-to-head SEAM 0.674 vs mem0 0.084, macOS installer, GitHub packaging, chat auto-memory).>

| # | date | status | summary |
|---|---|---|---|
| #246 | 2026-05-25 | done | GitHub main ruleset 15143368 now enforcement: PRs required, strict checks repo-hygiene/chroma-real-smoke/locomo-quickstart-bil2, bypass actors removed |
| #247 | 2026-05-25 | in-progress | Repo-hygiene handoff: ruleset verified active; in-progress advisory repository-maintenance workflow + report tool (2 tests); dirty locomo seam.py kept out |
| #248 | 2026-05-25 | done | Finished PR #32 hygiene review: maintenance report renders stale PRs + redacts session links; redacted leak in PR #31; 4 tests; sbert/Windows matrix still red |
| #249 | 2026-05-25 | done | AGENTS.md gains GitHub PR Workflow section: main protected, draft-PR/stale-PR/branch rules, required checks listed |
| #250 | 2026-05-25 | done | Merged PR #32 (squash 52db6c0), closed superseded PR #31; PR list empty, only main remains |
| #251 | 2026-05-25 | done | H2 slice 2: LoCoMo adapter opt-in retrieval_event writer (rows per answer run) + runner CLI flags; 9 tests, 45 adjacent green, no paid calls |
| #252 | 2026-05-25 | done | Opened draft PR #34 for the H2 writer branch; stale-branch scan clean; continuity/verify housekeeping |
| #253 | 2026-05-25 | done | Maintenance-report token fix: GITHUB_TOKEN -> GH_TOKEN -> gh auth token fallback; 8 tests; report PASS without exported token |
| #254 | 2026-05-25 | done | Remediated PR #34 CI failures: install .[server,sbert,rerank]; fixed 8 stale/platform-fragile audit tests; bench gate PASS 45/45; full pytest exit 0 |
| #255 | 2026-05-25 | done | Windows CI fix: git-hooks bash via shutil.which; stream append wrapped in per-path threading.Lock |
| #256 | 2026-05-25 | done | Windows stream test: joins writers 30s and asserts both dead before leaving patched root |
| #257 | 2026-05-25 | done | Windows stream append: process-wide mutex replaces per-path lock; concurrency test uses isolated tempfile root |
| #258 | 2026-05-25 | done | Windows stream fix: append only the new event block under lock instead of read-modify-write of the whole log |
| #259 | 2026-05-25 | done | .gitattributes forces LF for HISTORY/streams/cross-index so Windows checkout keeps byte-hash integrity |
| #260 | 2026-05-25 | done | CI runs verify_continuity --no-snapshot in clean checkout (snapshot-presence check only); gate test pins contract |
| #261 | 2026-05-25 | done | CI verify-gates audit test updated to expect verify_continuity --no-snapshot; both gate tests pass |
| #262 | 2026-05-26 | done | H2 slice 3: tools/h2 backfill_bundle CLI rebuilds retrieval_event rows from LoCoMo bundles (stale by default); 11 tests; full audit green |
| #263 | 2026-05-26 | done | Cleanup: deleted local .env.local (OPENAI key unread), reinstalled pre-commit hook, removed dead experimental/hybrid_orchestrator + pycache |
| #264 | 2026-05-26 | done | Correction: GitHub never tracked .env.local (gitignored, only .env.example in history); PR #36 stays scoped to tracked cleanup |
| #265 | 2026-05-26 | done | H2 slice 4: deterministic dev/holdout split helper + JSON manifest (salt/ratio, --rewrite audit trail); 20 tests; smoke 8dev/2holdout |
| #266 | 2026-05-26 | done | H2 slice 5: improvement_proposal/decision store + validate_proposal holdout gate + improvement_review CLI; 22 tests; substrate complete (5 slices) |
| #267 | 2026-05-27 | done | Polish pass (5 commits): orphan-edge sweep all prefixes, batch_ir SQL limits, parse_iso, LIKE escaping, retention CLI; 341 audit + 181 tests green |
| #268 | 2026-05-28 | done | Completed Qwen's unrecorded hardening: ShutdownState/middleware, shell allowlists, pool check_same_thread, reverted merge-corrupted storage; 653 tests; AGENTS cut-off rule |
| #269 | 2026-05-29 | done | Audit slice: pool reset-on-return rollback, bench publish gate, HMAC seal signing, durable LoCoMo bundles+checkpoints; 905 pass, 20 new tests |
| #270 | 2026-05-29 | done | SQLite pool/retry hardening: off-lock validation, blocking-path validate, retry_db_operation wired to 6 write methods; 912 pass; 9 concurrency tests |
| #271 | 2026-05-29 | done | Recovered lost LoCoMo dataset (re-downloaded, sha256-verified, committed in-repo + manifest + restore tool); no-paid baseline reproduced 0.528308 exactly |
| #272 | 2026-05-29 | done | S1 shell hardening: shell=False executes validated argv directly, chaining/redirection impossible by construction; 64/64 shell tests; PoCs rejected |
| #273 | 2026-05-30 | done | Audit #3 levers default-OFF: R1 semantic-zero +0.0046 global (cat1 +0.026/cat3 +0.018); R2/R3/reranker regress; byte-inert flag plumbing measured on pgvector |
| #274 | 2026-05-30 | done | Sealed cross-namespace retrieval leak (ns filter on candidates + vectors); scoped pgvector == isolated SQLite oracle 0.623668; cat4 headroom ~+0.065 |
| #275 | 2026-05-31 | done | CI fix: mocked pgvector INSERT now unpacks 8 params (namespace col); lesson: run BOTH test roots (tests/ AND test_seam_all) before push |
| #276 | 2026-05-31 | done | Replayed G5 roadmap card (zero-ops multi-surface index + drift verifier) onto main instead of stale-branch merge; no runtime change |
| #277 | 2026-06-01 | done | Preserved cat4 audit doc; moved 8.8M diag_out artifacts out of tree + gitignored; pack char budget identified as dominant recall lever |
| #278 | 2026-06-01 | done | Semantic-recovery policy flags + no-paid grid: pack-budget-deep context_recall 0.758217 (+0.1345); judged validation gated |
| #279 | 2026-06-02 | done | Paid 100-case slice (gpt-4o-mini): pack-budget-deep judged 0.57 vs baseline 0.44 (+0.13 judge, +8 correct); supports larger pack + deeper candidates |
| #280 | 2026-06-02 | done | conftest autouse hides ambient SEAM_PGVECTOR_DSN except @external tests; deleted 2 stale branches; Track-K gate definition recorded |
| #281 | 2026-06-02 | done | Integrity-hash fix: exclude answerer_diagnostics so --save-context runs hash identically to default runs |
| #282 | 2026-06-02 | done | Windows WinError 32 fix: SeamRuntime.close()/adapter close()/mem0 try-finally across benchmark paths; ephemeral-path resolve fix |
| #283 | 2026-06-02 | done | Windows WAL fix: pool-concurrency test connections now journal_mode=WAL + busy_timeout=5000, matching production SQLiteStore |
| #284 | 2026-06-02 | done | Promoted retrieval_orchestrator out of experimental/ (15 refs across 9 files); packaging deferred to new Track N (seam-runtime name) |
| #285 | 2026-06-02 | done | Dashboard is THE webui: REST server mounts static dashboard; experimental/ deleted; fixed JS-comment bug; Playwright-verified rendering |
| #286 | 2026-06-04 | done | Dashboard chat wired through SEAM (/chat + memory injection); fixed 2 bugs (memory never injected; retrieval 500 degraded); 7 chat tests |
| #287 | 2026-06-05 | done | seam doctor Streams check fixed for console-script entry (repo-root fallback import); PASS from /tmp with clean env |
| #288 | 2026-06-06 | done | Security bundle: argv0 path hardening, PNG bomb guard, lossless ValueError, graph-adapter ns scoping, vector-mode leg fix, /chat SSRF guard; 16 tests |
| #289 | 2026-06-08 | done | H2 loop apply step: retrieval_flag_state table + layered load_retrieval_flags + improvement_review apply; reversible reconcile ratchet; 17 tests |
| #290 | 2026-06-08 | done | Self-probe scorer + fusion weights as apply target; measured NEGATIVE: no free headroom (CLM probe 0.8917); direction fork A/B to operator |
| #291 | 2026-06-08 | done | Proposer + no-regression ratchet complete: candidate_levers, evaluate_candidates, run_improvement_cycle with auto-approve + auto-revert; 8 tests |
| #292 | 2026-06-09 | done | FREE-LoCoMo scorer wired; loop auto-discovered semantic_zero +0.040 (no category regression); rrf correctly rejected by gate; 3 tests |
| #293 | 2026-06-09 | done | seam improve cycle CLI + chromadb moved to optional extra (lazy imports already guarded); 4 new tests; 572 pass |
| #294 | 2026-06-09 | done | Strict no-skip conftest hook + @pytest.mark.external; CI pgvector job now runs 4 previously-silently-skipped tests; AGENTS.md rule |
| #295 | 2026-06-09 | done | CI fix: chromadb removal dropped transitive httpx; explicit pytest httpx install; pgvector job runs 3 explicit test files |
| #296 | 2026-06-09 | done | SECURITY: removed chromadb (GHSA-f4j7-r4q5-qw2c pre-auth injection, no patch) from requirements.txt + all-extras; opt-in chroma extra only |
| #297 | 2026-06-09 | done | Multi-conversation dev gate: pooled dev scorer rejects semantic_zero as single-conv overfit; surfaces w_lexical+0.1; 581 tests |
| #298 | 2026-06-09 | done | Cleared 3 honest CodeQL findings: workflow permissions read, dsl ReDoS regexes replaced, dashboard logging level; 7 alerts left for operator |
| #299 | 2026-06-10 | done | CORRECTION: logging-level change did NOT clear CodeQL (sink is level-agnostic); now logs argv token count only, content never logged |
| #300 | 2026-06-10 | done | /chat SSRF hardened: built-in host allowlist + no-redirect opener + resolved-IP range check; 5 new tests; 586 pass |
| #301 | 2026-06-11 | done | Maintenance: verified #300 PR #70 merge + all 10 CodeQL alerts resolved/dismissed; merged Dependabot #71/#72; fixed docker->docker-compose ecosystem |
| #302 | 2026-06-11 | done | Paid judged holdout Scorer + seam improve validate with --confirm-paid gate (never auto-run); 10 tests; dry run: 165 cases/660 max calls |
| #303 | 2026-06-13 | done | compile_nl stub exposed as overfit template (same skeleton every memory); fidelity contract + goldens + strict-xfail ratchet: 25 pass/11 xfailed |
| #304 | 2026-06-13 | done | PROTOCOL: SEAM spec made governing contract + mandatory session-start read; recalibrated RC/1 misjudgment (it meets its own contract) |
| #305 | 2026-06-13 | done | Fidelity harness reconciled to spec §22/§24 metrics (cr/rr/sr/pr/tr + promotion gate); stub sr=0.333, cr 0.018-0.040; 11 tests |
| #306 | 2026-06-13 | done | Session consolidation + handoff doc; zero open PRs/CodeQL/Dependabot alerts; branch hygiene; prompt-merge operator preference recorded |
| #307 | 2026-06-13 | done | Slice 2: qr retrieval_quality metric implemented (hermetic persist+search_ir, deterministic); stub qr=1.0; §24 gate complete; 6 tests |
| #308 | 2026-06-13 | done | Stage 2: honest-minimal floor compile_nl (verbatim RAW, grounded claims, real offsets, no fabrication); sr 0.333->0.667; 9 xfails flipped to XPASS |
| #309 | 2026-06-13 | done | Fixed CodeQL ReDoS in floor sentence regex (linear scan) + reconciled 15 legacy test_seam_all tests; all roots 1064 pass |
| #310 | 2026-06-13 | done | Bumped PROJECT_STATUS continuity handoff bullet (CI recorded-fact audit caught gap local preflight skips); process fix recorded |
| #311 | 2026-06-14 | done | Stage 3: unified compile_nl + compile_conversation_turn into one pipeline; free LoCoMo 3-scope aggregate +0.0084 (operator accepted) |
| #312 | 2026-06-14 | done | Loop validation on faithful ingest: self-probe 0.298->0.609 (kind + ref fixes); full loop proposed/applied bm25_all (+0.0266); Track-K gate MET |
| #313 | 2026-06-14 | done | Stage 4: opt-in local-Ollama rich extractor behind grounding firewall; sr 0.667->1.0 with real S-P-O triples (qwen2.5:3b); 5 CI-safe tests |
| #314 | 2026-06-14 | done | Density slice 1: context pack drops repeated ids, subjects resolve to entity labels; 5896->4117 tokens (cr 0.019->0.028) + readable context |
| #315 | 2026-06-14 | done | Density slice 2: content-only packs (CLM/STA/EVT/REL only); 2375->862 tokens (cr 0.074); ~3.8x cumulative density gain |
| #316 | 2026-06-14 | done | Density slice 3: $N id-alias factoring for prov/evidence + CORRECTION to #315 (not moot); -6.3% multi-doc/-20% single-doc; §23 symbol loop dropped (token-neutral) |
| #317 | 2026-06-14 | done | Regex enrichment OFF by default: ~25% wrong labels, zero recall benefit (A/B -0.0007); flag-recoverable; 11 levers tapped out at 0.627 |
| #318 | 2026-06-15 | done | Scoped cat1/cat3 levers (L1 decomposition, L2 edge closure) + SEAM Query Engine SQL2 learnings doc; docs only |
| #319 | 2026-06-15 | done | Track O (Query Engine + BIRD harness) added; Phase 0 NEGATIVE result: decomposition hurts recall -0.169 (displacement) |
| #320 | 2026-06-15 | done | Root cause: retrieval budget starvation not multi-hop; knee top_k=100/budget=8000 judge ~0.53 (+0.14, reproduced); search_top_k flag + benchmark defaults |
| #321 | 2026-06-15 | done | Answerer ladder taps out ~0.60 (gpt-4o 0.595); cat1 needs cross-turn coreference rebuild; fixed o4-mini reasoning_effort env config |
| #322 | 2026-06-15 | done | Test-artifact cleanup: 80 root pgvector sidecar files moved to test_seam/pgvector/; tests/docs routing rule recorded |
| #323 | 2026-06-15 | done | Entity-aggregation retrieval MARGINAL (wash at answerer noise floor, free A/B); free Ollama answerer + seed determinism landed; ingest rebuild is the real lever |
| #324 | 2026-06-17 | done | seam doctor stash advisory (non-blocking) + AGENTS.md stash hygiene; found 3-week-old abandoned hardening stash |
| #325 | 2026-06-18 | done | CalibrationScorer + adversarial-loader fix: 444 cat5 cases were silently dropped by loader; qwen hallucination_rate 0.267; GraphRAG blueprint doc |
| #326 | 2026-06-18 | done | WebUI consolidation: 4 locations -> one canonical seam_runtime/webui; Vite source archived; running server verified healthy throughout |
| #327 | 2026-06-19 | done | Judge bug fix: gpt-5.x rejects reasoning_effort=minimal; env-configurable; cat1 with real judge 0.525->0.670 at capable-answerer knee |
| #328 | 2026-06-19 | done | CORE retrieval profiles compact(100,8000)/broad(300,60000); holdout-validated cat1 +0.139 with capable answerer; config knobs not levers |
| #329 | 2026-06-19 | done | Progress tables: docs/progress_tables CSV ledgers (test_runs 6, benchmark_results 8, milestones 9 seed rows); HISTORY remains authoritative |
| #330 | 2026-06-20 | done | CodeQL fix (py/insecure-temporary-file): mktemp() -> pytest tmp_path in retrieval_flags test; zero remaining mktemp uses |
| #331 | 2026-06-20 | done | SEAM engineering manual landed + finalized (PR #96): template links split into files, discoverability pointer; closes dangling 09 doc reference |
| #332 | 2026-06-21 | done | Strand B: profile knobs loop-tunable via free answer-quality scorer (profile_safe gate); broad collapses weak answerer 0.342->0.028 |
| #333 | 2026-06-26 | done | Strand C step 1: mem0 target corrected to ~66.9% (doc's 91.6 was wrong); shared-answerer fair-comparison harness for mem0/zep |
| #334 | 2026-06-26 | done | Judged scorer context_budget confound fixed; paid holdout rung B: broad WINS +0.070 (0.465->0.535, cat1 +0.098) with capable answerer |
| #335 | 2026-06-26 | done | mem0 2.x API fix (search filters/top_k); test hardened against accidental paid quickstart run; unblocks rung C |
| #336 | 2026-06-27 | done | Provider retry + crash-resilient grouped runner + mem0 pacing; clean 764-case rerun: mem0 0.084 vs SEAM broad 0.674 (mem0 mostly abstained) |
| #337 | 2026-06-27 | done | macOS installer support: POSIX wrapper, ~/Library/Application Support layout, docs + tests |
| #338 | 2026-06-27 | done | mem0 retrieval depth knob (--mem0-search-limit, default 8) for controlled post-rung-C diagnostics |
| #339 | 2026-06-27 | done | GitHub-first packaging: project URLs, README direct-install, MANIFEST.in, package-smoke CI job; clean wheel install verified |
| #340 | 2026-06-27 | done | README agent setup prompt + operator manual/error index discoverability; docs/errors.md promoted to Error Index |
| #341 | 2026-06-27 | done | README placeholder cleanup (example.com installer URLs removed); operator-manual help path clarified |
| #342 | 2026-06-28 | done | Dashboard chat auto-memory: /chat persists turns (local.chat/thread, persist_chat toggle); 31 related tests pass |
| #343 | 2026-06-29 | done | Tracked rung-C LoCoMo runner tools/benchmarks/rung_c_paid.py (SEAM broad vs mem0 plan/execute): --benchmark-dry-run + hard --confirm-paid gate; replaced missing scratchpad driver; handoff updated; 31 tests; no paid run launched |

## Era 4 — Release engineering, cat1/cat3→0.80 campaign, and the honest scoreboard (#344–#439, 2026-07-03 → 2026-07-21)

<ARC: release/security era (fail-closed public/private router, Apache-2.0 core, PyPI + MCP-registry publication, two merge-bypass incidents #349/#351 hardening merge discipline) → engineering hygiene (ruff 261 findings, Windows CI via real runner, numpy cosine byte-identical 7.5x) → cat1/cat3→0.80 program (DeepSeek answerer, measurement-integrity PRs, conversation/1 + high-confidence/1 → 0.6991, first SEAM-vs-Zep-vs-mem0 head-to-head) → native-judge champion climb (0.7326 → 0.7689; judge/1 scoring contract = binding constraint) → mem0-harness honest scoreboard (lenient-judge cat1 88.65%; matched gpt-4o run tops mem0 on NOTHING — LATER CORRECTED by #538: the paper's mem0 numbers are gpt-4o-mini throughout; SEAM leads all four reported metrics; operational firefighting: quota exhaustion, self-hosted CI migration, tokenizer-true cost accounting) → lever graveyard + derived-facts pivot (bridge inert, count levers exhausted, verbatim-grounded ~0-lift, sentence-grounded next; docs/kb seeded).>

| # | date | status | summary |
|---|---|---|---|
| #344 | 2026-07-03 | done | Built deny-by-default public/private push gate for seam-runtime remote (verify_public_safe path+content deny-list, pre-push hook); 30 gate tests + full suite green. |
| #345 | 2026-07-03 | done | Strengthened README Agent Setup Prompt (errors.md pointer, write-then-read persistence check, MCP discovery round-trip); doc-only. |
| #346 | 2026-07-03 | done | Ported Apache-2.0 public-core relicensing to private main via 3-way cherry-pick of b9132ac; LICENSE/NOTICE/README/ROADMAP/PROTECTION_MODEL updated; no runtime change. |
| #347 | 2026-07-03 | done | Version 0.1.0->1.3.0 + MCP registry manifest server.json + README ownership comment; fixed mcp_protocol serverInfo.version hardcoded '0.1.0'; PyPI token provided. |
| #348 | 2026-07-04 | done | Fixed server.json description to 96 chars after live registry HTTP 422 (hard 100-char limit); validate passes clean. |
| #349 | 2026-07-04 | changed | INCIDENT: PR#115 merged while required checks in progress via plain gh merge after misread --auto error; all checks later passed; new no-bypass merge discipline recorded. |
| #350 | 2026-07-06 | done | Published seam-runtime v1.3.1 to PyPI and MCP Server Registry (fixed io.github.BlackhatShiftey casing; immutable PyPI artifact forced version bump); live/active verified. |
| #351 | 2026-07-06 | changed | INCIDENT: gh --auto merged PR#117 instantly with 2 required checks in progress; root cause transient CLEAN mergeState; remediation: poll check-runs then plain merge. |
| #352 | 2026-07-06 | done | Added canonical docs/MACOS.md guide wired into README/setup/errors/howto/installers; audit test now requires the macOS link; 8 passed. |
| #353 | 2026-07-06 | done | Rewrote SEAM_OPERATOR_GUIDE.md from PowerShell-only to cross-platform runbook (DB-paths table, macOS/Linux install, pgvector, failure triage); 8 passed. |
| #354 | 2026-07-06 | done | Corrected stale pgvector tag 0.8.2->0.8.3 and wrong postgres/$PGPASSWORD DSN examples in three macOS docs; full non-external suite green. |
| #355 | 2026-07-06 | changed | Built fail-closed public/private router (public_manifest allow-list, sync_public_mirror single-commit sync, seed templates); fixed improvement.py unguarded tools.h2 import crashing wheel installs. |
| #356 | 2026-07-06 | done | Executed live public mirror sync (0f4b40aa, 175 files +1013/-29664); operator chose to leave pre-existing public history as-is; mirror thread closed. |
| #357 | 2026-07-06 | done | Repo-wide ruff lint (261 findings, 227 auto-fixed) + doc-drift fixes; restored --fix-deleted seam.py re-exports and monkeypatch-name imports; token-budget test bumped 200->4000. |
| #358 | 2026-07-06 | done | cat1 cross-turn entity coreference (storage reconcile) + REL emission + entity-grounded scoring; free A/B NULL/negative (cat1 0.642->0.620); coreference landed, flags parked default-off. |
| #359 | 2026-07-07 | done | PR bookkeeping + CI regression fix (throwaway git repos default to 'master' on runners); closed SAST false-positive PR#122; found #358 commit was never pushed to origin. |
| #360 | 2026-07-07 | done | Fixed 3 Windows CI bugs (text-mode universal-newline corrupting update-index; os.name-patched macOS-mock tests) via _is_windows_host refactor; deleted 8 stale branches. |
| #361 | 2026-07-07 | done | Confirmed Windows SSRF test as recurring WinError 10053 flake; applied repo's sanctioned win32 skipif convention (Linux coverage unchanged); 21 passed locally. |
| #362 | 2026-07-08 | done | Continuity placeholder entry ("-"); registers handoff docs/handoffs/2026-07-07-cat1-cat3-scoping-handoff.md for the cat1/cat3 retrieval thread. |
| #363 | 2026-07-08 | done | Fixed CI ENOSPC disk regression (double CUDA torch install; ~25-30GB free step) + numpy cosine fast path (1.3x end-to-end, JSON-bound) + SQLite vector-scan design task. |
| #364 | 2026-07-08 | done | Landed SQLiteVectorIndex numpy matrix cache with fingerprint invalidation; byte-identical parity (150/150, per-row gemv/norm rounding), 7.5x synthetic corpus speedup. |
| #365 | 2026-07-08 | done | Paid prompt A/B proves cat1/cat3 wall is generation-side: cat1 0.5498->0.5905, aggregate 0.5017->0.5389; 'shortest possible answer' instruction was costing correct answers. |
| #366 | 2026-07-08 | done | Full-fidelity run-record capture (per-case answers/usage/cost/failure_class, JSON+JSONL training output, <think> traces); pure instrumentation, scores byte-identical. |
| #367 | 2026-07-09 | done | Added DeepSeek API answerer (reasoning_content folded into <think> traces) + T7 private record storage with unmounted-mount guard preventing silent root-filesystem writes. |
| #368 | 2026-07-09 | done | Live-verified DeepSeek model ids: deepseek-reasoner/chat are deprecated aliases; switched to deepseek-v4-pro at real cheaper prices, added cache-hit costing + served_model capture. |
| #369 | 2026-07-09 | done | Paid DeepSeek-v4-pro cat1/cat3 holdout (cat1 0.6885/cat3 0.4286); key finding: gold-label incompleteness is real, context_recall has precision flaw; only 2/11 hand-checked misses fixable. |
| #370 | 2026-07-09 | done | Fixed advisory CI regression in test_run_record.py (fake openai module via sys.modules; /media guard POSIX-only); 9 passed. |
| #371 | 2026-07-10 | done | PR1 of cat1/cat3->0.80 program: conservative evidence/1 classifier (co-occurrence within one turn); 82-case replay yields zero clean answerer_miss (v1 had 33). |
| #372 | 2026-07-10 | done | PR2: JUDGE_PROMPT_V2 (alias/subset/extra-detail fixes) + groundedness side-channel + rejudge_record replay harness; dry-run 82/82 cases, est $0.0074; judge/1 stays byte-default. |
| #373 | 2026-07-10 | done | Hardened rejudge harness: SHA-256 provenance block + required fail-closed --max-cost-usd with two-layer pre-flight/mid-run guard; corrected guard docstring honesty. |
| #374 | 2026-07-10 | done | Fixed PR#136 review finding: ClaudeJudge now honors prompt_version (was silently judging with judge/1); 95-test affected slice green, zero CodeRabbit findings. |
| #375 | 2026-07-11 | done | Handoff for cat1/cat3 program: uncertain bucket is 100% cat1, roughly half judge-level false negatives (judge/2 may fix free), half answerer-side list/enumeration omissions. |
| #376 | 2026-07-11 | done | Paid judge/2 replay of 82 stored answers: combined 0.6220->0.6280, only 3/30 uncertain cases corrected (disproves half hypothesis); residual judge-contract defects documented. |
| #377 | 2026-07-11 | done | Free offline adjudication of 43 cases: cat1 = 8 answerer failures / 5 retrieval / 13 judge-gold defects; cat1 ceiling 0.7787-0.8033, cat3 honest ceiling 0.6905; operator choice recorded. |
| #378 | 2026-07-11 | done | Established canonical tracked handoff registry + verify_handoffs fail-closed verifier in pre-commit and CI; 63 focused tests, 1,310 canonical non-external pass. |
| #379 | 2026-07-11 | changed | Correction of #378: shell quoting had stripped inline identifiers from the entry text; re-recorded the same registry/verifier facts legibly. |
| #380 | 2026-07-11 | changed | Added verify_handoffs to the required repo-hygiene CI job (P2 review finding) with a pinning test; 19 focused tests. |
| #381 | 2026-07-11 | in-progress | Cut-off handoff: in-flight conversation/1 + inference/high-confidence/1 adapter build; 61/67 focused tests pass, 6 failures (generator kwargs contract) left for successor. |
| #382 | 2026-07-12 | done | Completed semantic conversation adapter + cat1/cat3 improvement loop (381e448); fixed 3 CodeRabbit boundary findings; 1,337 tests + 7/7 external pgvector. |
| #383 | 2026-07-12 | done | Merged PR#142; corrected cat1/cat4 label swap in old docs; first paid A/B: aggregate 0.6395->0.6991 (+0.0596) with conversation/1 + high-confidence/1; beats mem0 paper on 4 cats. |
| #384 | 2026-07-12 | done | First in-harness SEAM vs Zep vs mem0 head-to-head: SEAM 0.6991 / Zep 0.5249 / mem0 0.0913; Zep adapter rewritten for zep-cloud v3; caveat: unmatched retrieval budgets. |
| #385 | 2026-07-13 | done | Broad-profile stack A/B: 0.6323->0.7326 (+0.1003, ~5x noise margin), all categories up; $0.79 spent; mining: cat1's 34 partials = list-completeness signature. |
| #386 | 2026-07-13 | done | Productized --profile {compact,broad} in improve validate; A/B reproduces #385's 0.732558 exactly (0.6134->0.7326); record SHA-256s anchored on T7. |
| #387 | 2026-07-13 | changed | Published the profile slice after 'push it': pushed commits, opened draft PR#146; documents 1,343 non-external + 7 external test evidence. |
| #388 | 2026-07-14 | done | Reviewed and merged PR#146 (--profile productization) as squash 1eb33e1; CodeRabbit zero findings; 2 advisory P2 CLI dry-run findings recorded as follow-ups. |
| #389 | 2026-07-14 | done | Built temporal/1 (relative-date resolution) + conversation/2 (exhaustive set-completion) levers from #386 record mining; 13 new tests, 104 slice, 1,354 canonical pass. |
| #390 | 2026-07-15 | done | Fixed judge-path retry (no backoff, 429 aborted multi-dollar run) then paid A/B: 0.6337->0.7689 (+0.1352); cat2 0.4730->0.7230; ~0.031 short of 0.80 goal. |
| #391 | 2026-07-15 | done | Free per-case review: 24/115 misses contain full gold in answer text - judge/1 scoring contract is the binding constraint (list-format answers 14% vs 67% correct). |
| #392 | 2026-07-15 | done | judge/2 rejudge + conversation/3 + temporal/2 stacked revalidation: BOTH negative; judge/2 unusable as primary; terse-set contract regressed -0.0756; #390 champion stands. |
| #393 | 2026-07-15 | done | Built mem0-harness shim seam_mem0_server (HTTP POST /memories /search) replacing stale wrong-interface adapter.py; comparability note: mem0 lenient binary judge. |
| #394 | 2026-07-15 | done | Retired stale mem0_harness/adapter.py and its contract test; README rewritten to document the HTTP server as the supported path. |
| #395 | 2026-07-15 | done | Free mem0-harness predict-only smoke (99.3% questions retrieve >=1 memory, zero spend) + built conversation/4 cardinality-constraint lever; built-not-yet-validated. |
| #396 | 2026-07-15 | done | Champion problem scan: ~46 pts answerer-side headroom vs 10.7 needed to 0.80, but ~14.5 pts locked behind judge/1 defects; achievable ceiling low-0.90s. |
| #397 | 2026-07-15 | done | Built inference/high-confidence/2 (anti-abstention + enumerate-then-count); cents preflight recovers over-abstention but cat3 naming needs stronger lever; durable handoff for sol. |
| #398 | 2026-07-15 | done | c4 A/B 0.7544 (-0.0145 vs champion, parked) + mem0-harness scoreboard: cat1 250/282=88.65%, cat3 83/96=86.46% under lenient binary judge; separate honest scoreboard. |
| #399 | 2026-07-15 | changed | Corrected #398's refs routing (T7 artifact basename listed as repo-relative path); measured results, costs, hash unchanged. |
| #400 | 2026-07-15 | done | Post-score facade hardening: search now passes temporal window/reference into search_ir; SPAN raw_id expansion before RAW filtering; 38 tests; artifact stays pre-hardening record. |
| #401 | 2026-07-16 | done | Fixed facade per-user DB reset bug (POST /memories now additive across restarts per Mem0 semantics); PR#150 supersedes PR#149 as sole merge vehicle. |
| #402 | 2026-07-16 | in-progress | Temporal knowledge graph on uncommitted worktree: versioned MIRL projection, episodes, graph search + dashboard workspace; 18+44 focused tests; full suite interrupted, NOT a pass. |
| #403 | 2026-07-16 | done | Deep knowledge/workspace/improvement successor: 5W1H+Then lens, trust states, fail-closed /chat boundary, workspace telemetry, 7-layer Memory workspace; 533 compatibility tests; uncommitted. |
| #404 | 2026-07-16 | done | Dashboard Auto-ingest rewritten from simulated to real ordered browser-file queue (fingerprint dedupe, .env exclusion, 4.5MB cap); 24 tests; live 104-file acceptance. |
| #405 | 2026-07-17 | done | Merged pgvector PRs (#151, revived HNSW #121); paid A/B conversation/4+hc/2 stack = 0.7762 new best (+0.0073 over champion); Fable re-analysis corrects miss classification 52%->35%. |
| #406 | 2026-07-17 | done | Worktree hygiene: gitignored .playwright-mcp/, .wrangler/, visuals/ and loose artifacts (non-destructive); git status clean. |
| #407 | 2026-07-17 | done | ROADMAP Track P (per-agent memory profiles, OpenClaw first, 3-level ladder) + Track Q (SEAM Lite for Android, 1-3B push-based); doc-only planning. |
| #408 | 2026-07-17 | done | Built exact-answer/1 contract (draft-then-verify: coverage/prune/anchoring) as new answer_contract flag, not new adapter; 15 new tests; built-not-validated, ~$0.80 A/B gated. |
| #409 | 2026-07-17 | done | Registered exact-answer handoff in canonical registry; push state recorded (main 2 commits ahead of origin, unpushed pending operator confirmation). |
| #410 | 2026-07-17 | done | Posted benchmarks/RESULTS.md: two SHA-anchored runs (native 0.7762; mem0-harness 88.65/86.46/88.10); per-case rows not committed (licensed dataset); caveats load-bearing. |
| #411 | 2026-07-17 | done | Corrected non-runnable Run 1 reproduce command in RESULTS.md (wrong entrypoint, missing dataset/scopes); verified by free dry-run reporting cases=344. |
| #412 | 2026-07-17 | done | Paid exact-answer/1 A/B NEGATIVE: 0.7471 below both champions; precision-prune deletes gold (judge/1 rewards fuller answers); parked default-off; HF offline cache env fix. |
| #413 | 2026-07-17 | done | Built inference/high-confidence/3 open-domain naming clause with ambiguity guard (opposite of prune); built-not-validated; handoff for SOL with mandatory T7 env exports. |
| #414 | 2026-07-17 | planned | Recorded ROADMAP Track R (Zep-class temporal graph parity); native judge/1 primary standard; external gate = matched mem0-harness win with contract held constant. |
| #415 | 2026-07-17 | changed | Corrected #414 per operator rejection: native judge/1 and mem0-harness are co-primary evidence lanes (never averaged/relabeled); Track R gate unchanged. |
| #416 | 2026-07-17 | done | Built event-count/distinct/1 count projection for mem0-harness cat1 (22/32 misses have full evidence); 50 focused tests; free preflight on 14 count cases. |
| #417 | 2026-07-18 | done | Paid count microgate: candidate 6/14 vs baseline 1/14, net +5; >=7 flip gate NOT met so full run not green-lit; 8 remaining misses all wrong numbers. |
| #418 | 2026-07-18 | done | Competitive roadmap P3.2 framework adapters (LangGraph/CrewAI/AutoGen) + FRAMEWORK_ADAPTERS_PATH doc proving zero SEAM core changes needed. |
| #419 | 2026-07-18 | done | hc/3 cents preflight NEGATIVE: 14/21 changes are paraphrase noise, zero naming conversions - clues absent from retrieved context; full A/B cancelled, hc/3 parked. |
| #420 | 2026-07-18 | done | Free mining of 18 non-count cat1 misses (9 all/7 partial/2 none evidence); ranked levers; gpt-4o answerer-parity probe (~$2) recommended as cheapest next paid step. |
| #421 | 2026-07-18 | done | Free retrieval diff: post-#400 code changes effectively NEUTRAL (mean Jaccard 0.924, 44/45 misses unchanged); 88.65% baseline stays valid; re-baseline deferred. |
| #422 | 2026-07-18 | done | Built answerer-parity probe runner (frozen stored contexts, gpt-4o-mini vs gpt-4o, gpt-4o judge); handoff with decision thresholds (>=7 flips = matched full run). |
| #423 | 2026-07-19 | done | Parity probe result: 18/32 cat1 flips under gpt-4o (projected 95.0% matched cat1 vs mem0's 91); judge-drift 6/32; cat3 +1 net; next = ~$10-15 matched full run. |
| #424 | 2026-07-19 | done | cat2+cat4 recon on mem0 harness: cat2 71.96% vs mem0 92.0 (-20pt, wrong-instance dates), cat4 86.83%; survived TPM/RPD/quota failures; 21 cases stranded; OpenAI credit exhausted. |
| #425 | 2026-07-19 | done | Moved CI to self-hosted runner (seam-terrabyte, systemd user service, docker-wake hook) after Actions billing lock; workflow changes committed, push operator-gated. |
| #426 | 2026-07-19 | done | Recon final: cat4 87.16%, cat2 71.96% (cat2+cat4 82.96%); fixed stale HF token file breaking self-hosted CI (moved aside + systemd env). |
| #427 | 2026-07-19 | done | Matched-answerer run in flight (378 cases); built temporal-instance/1 cat2 lever (default-off, facade env-gated); self-hosted CI first run fully green. |
| #428 | 2026-07-19 | done | Built tokenizer-true cost_report (o200k_base for gpt-4o family); reconciliation: cat2+cat4 $3.1 real vs ~$2 quoted, day ~$18 vs ~$13; cost-before-quote practice set. |
| #429 | 2026-07-19 | done | Matched-answerer run NEGATIVE: cat1 87.94%/cat3 69.79% - SEAM tops mem0 on NOTHING matched; judge severity revoked corrects; miss buckets mapped to levers. |
| #430 | 2026-07-20 | done | Recovery closeout of #419-429: repaired temporal-instance/1 future-question handling, cost_report validation, parity-probe commit pinning; 28 focused tests; rejected-experiment files preserved. |
| #431 | 2026-07-20 | done | Built entity-bridge/1 second-hop retrieval lever (bridge terms, reserved 40/200 tail splice); 8 hermetic tests; free preflight gate: >=6 evidence-absent gains. |
| #432 | 2026-07-20 | done | entity-bridge/1 free preflight TESTED-INERT (0 gained, 1 lost); true root cause = query<->evidence wording distance at embedding search; derived-facts-at-ingest is the on-goal fix. |
| #433 | 2026-07-20 | done | Landed event-count/distinct/2 (recovered completed-but-uncommitted build; 'operator-rejected' disproven via mtimes/reflog); free preflight: 2600 candidates -> 2017 groups, 28 direct-match. |
| #434 | 2026-07-20 | done | Paid v2 count microgate NEGATIVE: net +1 (gate 7 not met); 6/13 miss-recovery on plain rerun = gpt-4o non-determinism; count bucket small under matched contract. |
| #435 | 2026-07-20 | done | Implemented grounded-clm/1 derived-facts lever (verbatim-grounded CLM + SEAM-FACT/1 serve with frozen manifests, raw-prefix-floor splice); 159/159 tests; real smoke extracts 'John likes surfing'. |
| #436 | 2026-07-20 | done | Tracked handoff + registry catch-up (#432-436): matched scoreboard (tops nothing), two facade levers exhausted, grounded-clm/1 as live architectural path. |
| #437 | 2026-07-20 | done | Scaffolded docs/kb/ memory-systems knowledgebase (9 pages: 8 benchmark traps, mem0/zep/langmem pages, lever graveyard, positioning) + local retrieval-specialist subagent. |
| #438 | 2026-07-20 | done | Free derived-facts preflight + grounded-clm/2 (clause-scoped guard): strict verbatim contract ~0-lift (7/63 misses); sentence-grounded facts chosen next (60/63 ceiling); qwen2.5-7b imported. |
| #439 | 2026-07-21 | done | Competitor ratchet: researched Mem0/Hindsight/Zep/Cognee under their real eval contracts; free-validated sentence-grounded-clm/1 (canonical source-sentence provenance, safety firewall); 51/63 misses reached, binding precision 0.9956; default-off; durable audit doc |

## Era 5 — Benchmark contract repair and the graph-first pivot (#440–#486, 2026-07-21 → 2026-07-28)

<ARC: benchmark/displacement era (LongMemEval/BEAM contract repair, graph-fill gate retracted #444, multi-scope PACK +10/0, non-displacing PACK ratchet, fact-free RAW ablation) → graph-first pivot (Track R re-scoped; G1-G2.x identity substrate; G3 fold falsified → lever-graveyard; R1/R2 reasoning plane + SeamSDK) → vector/render hardening (pgvector boundary resync, mirl-vector-text/2) → protection/licensing era (seam-client 0.1.0, compiled self-host v1, BUSL-1.1 after discovering MIRL already public via PyPI 1.3.1; identifier exposure 525→417 ratchet) → G3 completion + productization (rrf/2, entitlements optional, MCP as opaque 3-tool contract, zero added exposure) → distribution era (seam-self-host 1.0.0 + seam-client 2.0.0 both live).>

| # | date | status | summary |
|---|---|---|---|
| #440 | 2026-07-21 | in-progress | Handoff: pinned mem0 checkout found, no BEAM/LongMemEval data; fixed scorer-substitution bugs; WIP harness bridge; 23 tests, uncommitted |
| #441 | 2026-07-21 | done | LongMemEval/BEAM contract repair: fail-closed validators, upstream harness via loopback facade; 51/51 + 1,627 strict + pgvector 10/10 |
| #442 | 2026-07-21 | done | Free graph gate passed: fill gained 5 exact refs, lost 0 across 378 cat1/cat3; aggressive probe lost 1, rejected; 1,636 tests |
| #443 | 2026-07-21 | done | Correction to #442 arithmetic: 1,634 passed + 2 xfails of 1,636 collected; all claims unchanged |
| #444 | 2026-07-21 | changed | Retracted #442/#443 graph gain: profile was 200/8k not 300/60k; re-audit identical 353/252/887; paid microgate canceled, zero spend |
| #445 | 2026-07-21 | in-progress | In-progress breadcrumb: multi-scope PACK gained 10 refs/0 lost on 378 q (evidence only); local BEAM 100/2,000 found; 36/36 tests |
| #446 | 2026-07-21 | done | Completed #445: PACK keeps +10/0; local BEAM-1M validated 35 conv/700 q/74,630 turns; 61/61 + 1,415 strict; CodeRabbit fixes |
| #447 | 2026-07-21 | done | CI fixes: advisory job after 5 fast jobs; 9 LoCoMo subprocesses cut to 4; sentence-transformers 2.7 local-only pin; 20/20 |
| #448 | 2026-07-21 | done | GPT-4o multi-speaker probe: 1,968 calls, $2.11, 80.15% yield; fixed re-sort bug; no cap passed; suite interrupted 12% (319.99s/180s) |
| #449 | 2026-07-21 | changed | Correction to #448 verification: 90 + 4 test path breakdown supplied; results unchanged |
| #450 | 2026-07-22 | done | Non-displacing PACK: N=3 smallest passing cap, 130/130 counts, max 3,197 chars; both gold hits are aux RAW, fact lift 0; 38/38 |
| #451 | 2026-07-22 | changed | Correction to #450 verification: 38 tests across 4 paths (13/10/9/6); results unchanged |
| #452 | 2026-07-22 | changed | Fact-free RAW ablation reproduces #450 exactly (miss +1, sentinel +1, 0 lost): GPT-4o fact is dead weight; full suite green |
| #453 | 2026-07-22 | changed | Graph->source-RAW selector built (default-off); smoke exposed same-turn node over-count; distinct-token agreement fix; 64/64 + suite green |
| #454 | 2026-07-22 | done | Track R re-scoped to graph-first; built G1 identity index + ENT provenance binding; 1:1 token agreement; 200/200 affected, 1,327 full |
| #455 | 2026-07-22 | done | G2.1 reversible identity-merge ledger outside reprojection: propose/accept/conflict/split, survives rebuild; 9/9 new + 43 |
| #456 | 2026-07-22 | done | G2.2 merge-candidate generator (proposed-only, never auto-accept): shared-alias signal, homonym exclusion; 14/14 identity tests |
| #457 | 2026-07-22 | done | G2.3 ledger on store/MCP(read-only)/REST/CLI; live seam console round-trip; 18/18 identity + 116 surface tests; TUI deferred |
| #458 | 2026-07-22 | done | G3 slice-1: resolve_identity folds accepted merges into source-RAW retrieval (first retrieval-touching stage); no score claim |
| #459 | 2026-07-22 | done | G3 measurement falsified: zero alias fuel on LoCoMo (pairs_examined=0); banked in lever-graveyard; built closeout.py one-shot wrapper |
| #460 | 2026-07-22 | done | Graph not mature: fixed G2 split->proposed regression, PACK traceability set, MCP count; closeout.py +resume; 99 focused; run interrupted |
| #461 | 2026-07-22 | done | R1 reasoning graph + stable SeamSDK: append-only non-canonical reasoning, 20-writer locking; 1,793 non-external 100%; CodeRabbit limited |
| #462 | 2026-07-22 | done | R2 retrieval-decision plane + G3a 0-3 hop traversal; ns/scope enforced SQLite/pgvector/Chroma; 1,823 selected, 1,821 passed |
| #463 | 2026-07-23 | done | pgvector boundary-only resync w/o re-embed; found attrs dict-order hash instability (documented, not fixed); 1,821 passed |
| #464 | 2026-07-23 | done | Hardened #463: boundary_only raises NotImplementedError instead of silent full reindex; 11/11 resync tests |
| #465 | 2026-07-23 | done | mirl-vector-text/2 migration: stable field order/sorted keys, version stamps, legacy fail-closed; 1,406 + 189 + 23 pgvector |
| #466 | 2026-07-23 | done | R3 verification loops via SDK: append-only checks, transactional finalize_verified, no hidden CoT; 45 + 1,414 + 189 pass |
| #467 | 2026-07-24 | changed | License split prospective: MIRL/HS/1 proprietary, private 2.3.0; public mirror frozen 0f4b40aa; 99 licensing + 1,300 audit |
| #468 | 2026-07-24 | done | GitHub envs private-package-release + pypi created, protected branches only; wait-timer unsupported; nothing published |
| #469 | 2026-07-24 | done | Public agent SDK: opaque /v1 API + Apache-2.0 seam-client 0.1.0 in Seam_Runtime repo; 59 + 12 tests; nothing published |
| #470 | 2026-07-24 | done | Published seam-client 0.1.0 to PyPI via OIDC; PRs #163/#164 merged; private 2.3.0 stays blocked from PyPI |
| #471 | 2026-07-27 | done | Compiled self-host v1: Nuitka distroless 60.2MB image, Ed25519 entitlements, 4-route opaque API; boot fixed libz/libgcc; 1,313 |
| #472 | 2026-07-27 | done | Fixed PR #169 CI collection failure: advisory install missing selfhost extra; audit pins cryptography; 36 + 14 tests |
| #473 | 2026-07-27 | done | Fixed PR #169 worktree-name assertion: resolves build-context path vs repo root; 7 tests pass |
| #474 | 2026-07-28 | changed | Relicensed BUSL-1.1: MIRL already public via live PyPI 1.3.1 (57 modules); BUSL over FSL; LICENSE v2.1 carve-out; 103 tests |
| #475 | 2026-07-28 | changed | Pricing fix: Max unlimited contradiction resolved (100k writes cap; unlimited = self-host only); $0.0002/write basis flagged |
| #476 | 2026-07-28 | changed | Rebuilt public shim fail-closed: removed scanner-dodging __import__, submodule blocker, honest metadata; buildable + approved |
| #477 | 2026-07-28 | changed | Measured compiled self-host: 525 reserved-id occurrences; 18 exclusions cut 20% to 417; ratchet replaces impossible zero; 2.4.0 BUSL |
| #478 | 2026-07-28 | done | G3 exact-path + historical-view retrieval: shortest paths, view-visible episodes persisted on R2; 93 + 1,411 pass |
| #479 | 2026-07-28 | done | G3 reciprocal-rank-fusion/2 + qualification: 2,048-node synthetic p95 7.7-43.3ms vs 250ms gate; 1,418/1,420 |
| #480 | 2026-07-28 | changed | Re-measured post-G3: knowledge_graph 17->18 from one legit module path; budget 417->418 with cause recorded |
| #481 | 2026-07-28 | changed | Roadmap Track N2 self-host surface: 5 phases (MCP in flight, CLI costliest, benchmarks out); entitlement blocks free tier |
| #482 | 2026-07-28 | changed | Entitlement made OPTIONAL: 503 gates removed, forged-vs-lapsed split, dead stdout badge found in real container; 5 tests |
| #483 | 2026-07-28 | done | Wheel MCP as opaque contract: tool descriptions leaked 19 reserved strings; selfhost_mcp 3 tools, exposure 414/414, zero added |
| #484 | 2026-07-28 | changed | Renamed to seam-self-host 1.0.0; published seam-client 2.0.0 to PyPI; fixed rglob allow-list bug; publish needs operator action |
| #485 | 2026-07-28 | done | Published seam-self-host 1.0.0 to PyPI: case-sensitive invalid-publisher fixed; live .so-only install verified; image unpushed |
| #486 | 2026-07-28 | changed | Shipped seam-self-host 1.1.0: added psycopg dependency (published 1.0.0 returned 500 on first pgvector write); startup-validated vector/embedding config with 3-line summary; local-first hash embedder restored as default; full env reference in README; ratchet 414/414 |

## Era 6 — Package stability, graph completion, and Track S activation (#487–#526, 2026-07-29 → 2026-08-02)

<ARC: package-stability diversion (self-host 1.1.2 + private 2.4.0 released and live-verified, then distribution split retired for a single package #501) → G3-G7/R1-R6 graph/reasoning milestones completed provider-free → retrieval-unification A/B saga (quickstart parity falsified at full scale -0.010804; regression attributed to 87%-echo graph leg via traces; matched 4-arm ablation inverts to +0.009628; cat3 remains open loss; weighted-RRF landed) → honest negatives (promotion-content gate null n=98, WANDR 1.0 ceiling) → Track S Production-Core Integrity Campaign activated (S0/S1/S2 qualified at 2,000+ tests) → infrastructure/hygiene thread (881MB -wal/-shm leak reclaimed, dead T7 HF cache path causing silent 0.0, public-repo visibility caught, CI cache chain fixed).>

| # | date | status | summary |
|---|---|---|---|
| #487 | 2026-07-29 | done | Qualified package pair: self-host 1.1.2 + private runtime 2.4.0; entrypoint probes pgvector with retries; hardened /v1 boundary; 414/414 ratchet |
| #488 | 2026-07-29 | changed | Post-review hardening of 1.1.2/2.4.0: session_id blank-as-absent, pgvector check_ready ensure_schema, SQLite 0600 WAL pinned; 92/92 tests |
| #489 | 2026-07-29 | done | Final 1.1.2/2.4.0 candidates ready for protected PR CI; post-fix CodeRabbit clean; full suite green; rejects chmod of existing shared parent dirs |
| #490 | 2026-07-29 | done | Released self-host 1.1.2 to PyPI + private runtime 2.4.0 (PR #180 merged); independently live-verified installs/upgrades on both channels |
| #491 | 2026-07-29 | changed | G3 slice 1: graph-node vector projection (entity/value/agent/symbol); fixed attrs render + move-no-reembed regressions; 1,538 tests green |
| #492 | 2026-07-29 | changed | G3 slice 2: semantic node seeding for graph queries, DEFAULT-OFF; weak embedder scores noise-level (0.1336 vs 0.1066); A/B not yet run |
| #493 | 2026-07-29 | changed | Fixed fenced-JSON Ollama parse bug (gemma4:cloud 0.0->3.8 items/turn); re-measured extractor speeds 2.4s-17.6s/turn; blocker not cleared |
| #494 | 2026-07-29 | done | G3 graph_node fusion leg + R4 reasoning-pattern plane; LoCoMo dev recall 0.744->0.923 (+0.179), holdout +0.167; 1,565 tests |
| #495 | 2026-07-29 | done | G4 graph-products plane + R5 reviewed-promotion bridge; fail-closed proposal surface, nothing auto-applies; 1,577 collected, 1,575 passed |
| #496 | 2026-07-29 | done | G5 context assembly + G6 lifecycle + R6 envelopes + G7 provider-free lanes; native vs event-only parity 1.0/1.0; 2,061 collected |
| #497 | 2026-07-29 | done | Closed graph round into canonical handoff (PR #185/#186 merged); G1-G7/R1-R6 structurally complete; next: zero-network WANDR replay adapter |
| #498 | 2026-07-29 | done | Fixed Mem0 facade graph seeding + SDK default ns; graph r@1 0.196->0.301 (+0.105); promotion-content gate NULL, deltas within noise |
| #499 | 2026-07-30 | done | Qualified semantic graph leg on LoCoMo n=1977 (mix r@20 0.682->0.748); RETRACTED wrong default-path claim; promotion content negative |
| #500 | 2026-07-30 | changed | Metadata-only correction to HISTORY#499 uncontrolled topic labels promotion/sdk, re-scoped under approved vocabulary |
| #501 | 2026-07-30 | changed | Retired distribution split: single private package; removed 40 files/91 tests (1,626->1,494); kept leak gate; noted two retrieval paths diverge |
| #502 | 2026-07-30 | changed | RetrievalOrchestrator now sole retrieval engine; quickstart parity recall 0.963333; first query pays 5.9s BGE init; 1,500 tests |
| #503 | 2026-07-30 | changed | Full 1,542-case provider-free A/B falsified parity: legacy 0.766420 vs canonical 0.755616 (-0.010804); branch DO-NOT-LAND; ablation required |
| #504 | 2026-07-30 | in-progress | Materialized legacy-weighted/1 control; LoCoMo runner exposes 3 arms; smoke recall 0.963333; full 1,542-case ablation still required |
| #505 | 2026-07-30 | changed | Trace attribution plumbing + WANDR zero-network replay lane (synthetic corpus, 1.0 ceiling); status split 143 blocks -> 8 streams; 1,523 tests |
| #506 | 2026-07-31 | done | Fixed two SQLite artifact leaks: 7,051 orphan -wal/-shm pairs (858MB) + 118 root files; new hygiene guard red-green proven; 881MB reclaimed |
| #507 | 2026-07-31 | done | Fixed dead /media T7 HF cache path that produced clean-looking 0.0 across 200/200 cases; runner now exits 1 on total infra failure |
| #508 | 2026-07-31 | done | Attributed regression to graph leg from traces: mix-hybrid -0.023854; graph 87.43% duplicate, 0.1135% of unique selected; validates weighted-RRF |
| #509 | 2026-07-31 | done | Matched 4-arm ablation falsifies #503: canonical beats legacy +0.009628 overall, but cat3 -0.036775; graph leg 100% echo; arm C confounded |
| #510 | 2026-08-01 | done | Provenance chain resolve claim->SPAN->RAW with reason codes; completeness CLM/RAW 1.0, ENT 0.0; graph abstention fixed; lands weighted-RRF |
| #511 | 2026-08-01 | in-progress | Activated Track S Production-Core Integrity Campaign: F1-F22 findings, S0-S10 dependency-ordered stages; baseline 86a81e2, 269/269 tests |
| #512 | 2026-08-01 | done | Restored WANDR replay fixtures hidden by *.jsonl ignore; byte-verified against manifest; closed 7 missing-fixture failures in strict S0 gate |
| #513 | 2026-08-01 | done | Track S S0 locally qualified: 2,095 tests (2,070 passed, 0 skips); WANDR/LoCoMo hardening; CodeRabbit 50->0 findings; F22 routed to S1/S10 |
| #514 | 2026-08-01 | done | Fixed closeout: rebuild roadmap stream index before cross-index; verify_streams hash-mismatch fail-closed; resume-path regression; 25/25 |
| #515 | 2026-08-01 | done | Pre-push amendment: wheel privacy gate caught embedded absolute user-profile path in UI preview; replaced with generic example; 22/22 |
| #516 | 2026-08-01 | changed | Found origin repo PUBLIC against private policy; made private before any push; fixed CI HF offline-mode cache provisioning; PR #190 opened |
| #517 | 2026-08-01 | changed | CI cache fix: dead HF_HUB_CACHE path unwritable on runner; job-local writable root + explicit online/offline contract; 35 tests |
| #518 | 2026-08-01 | changed | Downstream full-suite job failed 44/6 on LocalEntryNotFoundError; now restores LoCoMo job's exact cache key and fails on miss; 36 tests |
| #519 | 2026-08-01 | changed | Fixed invalid runner.temp context in job-level env (workflow would fail validation); moved to $GITHUB_ENV step; regression rejects it; 36 tests |
| #520 | 2026-08-01 | done | Track S S1 guardrails locally qualified: explicit SQLite load order, rrf_k validation, unified secret_scan, dependency contract; 2,094 tests |
| #521 | 2026-08-01 | done | Reconciled dirty canonical checkout post PR #190/#191; 19 weighted-RRF regression tests; fixed operator HF cache env; 1,553 audit tests pass |
| #522 | 2026-08-01 | done | Track S S2 SQLite migration spine: schema v2 central+projection steps, integrity/FK checks, rollback/resume, backup restore; 2,130 tests |
| #523 | 2026-08-01 | changed | Clarification to #522 review evidence: final staged rerun refused by free-plan rate limit (28-min wait); no change to S2 evidence |
| #524 | 2026-08-01 | done | Fixed seam doctor falsely failing when chromadb absent; REQUIRED_DEPENDENCIES now rich+tiktoken only; hermetic import-blocker proof; 1,572 tests |
| #525 | 2026-08-02 | done | Full-repo audit record: 13 findings; CI fixed 13 orphaned external tests + ruff lane + pgvector image parity; docs corrected; 2,154 passed |
| #526 | 2026-08-02 | done | Recovered accidental-push branch; repaired 4 reproducers (persist_ir race, /chat env read, projection registry, time gate); 2,170 passed |

## Era 7 — Track S S3–S5, security hardening, and the operator surface (#527–#559, 2026-08-03 → 2026-08-12)

<ARC: Track S S3-S5 (durable supersession, typed-reference contracts, snapshot/pool/outbox, strict publication boundaries) → security/hygiene hardening (loopback echo primitive, docs bypass; repo hygiene a gated check; local-gate = CI-gate parity) → competitive correction (#538 debunks Mem0 numbers vs arXiv:2504.19413, inverting standing from "tops nothing" to leading all four) → operator-surface rebuild (Textual TUI supersedes dashboard, input modes, Memory/Provenance page, canticle-seam + canticle-cosmic-ui kits, WebUI Constellation 327 nodes/988 edges) → improvement-experiment loop (bounded AutoResearch-style, PR #208) + wiki-navigation slice (#556) → continuity/correction tail (545/546/552/553/555/557/559 self-correcting verification wording).>

| # | date | status | summary |
|---|---|---|---|
| #527 | 2026-08-03 | done | 2nd whole-repo audit post-S2 merge; fixes CRITICAL /chat loopback body-echo read primitive, docs-route auth bypass, graph-order tiebreak; 2,180 pass; retracts #525 fingerprint claim |
| #528 | 2026-08-03 | done | Registers handoff for merged audit-repair state; retires stale handoff still describing PR #193 as unmerged draft; docs/registry only, closeout chain green |
| #529 | 2026-08-03 | done | Rebuilt/requalified Track S S3 durable supersession on main@fa72c0c; positive known-good migration gate, identity ledger, malformed-doc fail-close; 1,630 audit tests; CodeRabbit zero findings |
| #530 | 2026-08-03 | done | Recovers cut-off S4 typed-reference candidate (33 dirty files, no breadcrumb); typed-reference contracts, write lock, restore-after-failed-projection; 2,400 pass; S5 unstarted |
| #531 | 2026-08-03 | done | Registers merged S4, opens S5, fixes history advisory lock landing untracked in git worktrees (gitdir: pointer parsing); 2,405 pass; PR #195 merged at main@ea4e46e |
| #532 | 2026-08-04 | changed | Track S S5 locally qualified: one read snapshot/request, durable vector outbox, no per-query DDL, divergence detect+repair on 3 backends; 2,024 pass; nothing published |
| #533 | 2026-08-04 | done | S5 published via PR #199 at main@19b3a76, all 8 checks green; corrects #532's skipped pgvector lane - enabled via PGVECTOR_TEST_DSN, 2,028 pass 0 skip; opens S6 tenancy decision |
| #534 | 2026-08-04 | done | Repo hygiene becomes a gate: worktree collection in maintenance report + pre-push refuses dirty linked worktrees; cleanup worktrees 4->1, branches 14->8; 9 new gate tests |
| #535 | 2026-08-05 | done | Closes audit finding 9: /v1 had zero HTTP tests; adds characterization suite (35 tests/75 cases) pinning current tenancy gap; discrimination via 4 injected breaks; S6 still blocked |
| #536 | 2026-08-05 | done | Local commit gates made identical to required repo-hygiene CI (removes --no-recorded-fact-audit from all 3 scripts); root cause of #535 push rejection; 2,118 pass |
| #537 | 2026-08-05 | done | Canticle-style Textual TUI becomes live dashboard (all 4 entry points); fixes mount crash (widget id) and export-prefix env parse silently dropping API key; 2,586 pass |
| #538 | 2026-08-05 | done | Correction: Mem0 LoCoMo numbers misquoted (91.2/91.3/92.0 vs paper 67.13/51.15/55.51) - SEAM leads all four; fixes inverted conclusion, -2.7->+37.6; records S6 decision: in-process, optional principal |
| #539 | 2026-08-05 | done | Fixes test-and-benchmark collection error: new TUI test imported optional textual at module scope killing whole CI run; lane installs dash extra, un-hides 28 skipped dashboard cases; 2,569 pass |
| #540 | 2026-08-06 | done | Memory tab rebuilt as composite page (records + provenance; row-select copies id and traces, y yanks); fixes log pushed off-screen at 110x32; writes TUI_OPERATOR_SURFACE roadmap; 35 tests |
| #541 | 2026-08-06 | done | Palette census: 104/153 commands lacked descriptions - reader defect (argparse help= never populates description), not missing metadata; writes 27 REST + 11 SDK summaries; 2,611 pass |
| #542 | 2026-08-07 | done | TUI input modes ! shell / ? chat / / seam; restores silently-removed shell security gate SEAM_DASHBOARD_ALLOW_SHELL; fixes palette race, tab command, alt+N nav; 2,680 pass |
| #543 | 2026-08-10 | done | TUI interaction repairs (! ? latch from any focus, settings provenance, clipboard discipline) + canticle-seam@1.0.0 branding kit, fail-closed verifier, 30 adversarial tests; 2,701 pass |
| #544 | 2026-08-10 | done | WebUI Constellation slice (operator-authorized): Topology/Constellation views, deterministic FNV-1a rings, no false edge-flow animation; Chrome renders 327 nodes/988 edges; 2,706 pass |
| #545 | 2026-08-10 | done | Continuity correction to #544: authoritative command scopes - focused 118 passed in 8.48s, repo 2,706 pass; all product facts remain current |
| #546 | 2026-08-10 | done | Marker-spelling correction to #545's repo command (-m "not external"); continuity/verify housekeeping |
| #547 | 2026-08-10 | done | Bounded AutoResearch-style improvement-experiment loop on H2 substrate: append-only SHA-256 event chain, SQLite triggers, 128-candidate cap, ratchets; 2,726 pass + 23 external |
| #548 | 2026-08-10 | done | #547 merged via PR #208 as squash 8e9a7c1; post-merge CodeRabbit on 20-path diff adds CLI boundary tests (max-candidates -1/0/129 vs 1/128); 7 exact-head jobs green |
| #549 | 2026-08-10 | done | canticle-cosmic-ui@1.0.0 expression layer over identity kit: tokens, SHA-256 manifest, Tailwind/Textual/Lip Gloss adapters, fail-closed verifier; 50 tests; 4 CodeRabbit issues fixed |
| #550 | 2026-08-11 | done | Addresses 2 P2 findings on PR #210: helper-text contrast token, verifier inventories symlink/non-regular paths once; 51 tests pass; no runtime surface changed |
| #551 | 2026-08-11 | done | Reconciles Track S campaign vs main@2f4af74: stages are S0-S10; S0-S5 merged, S6 tenancy+opaque delete unimplemented restart, S7-S10 dependency-blocked; Mermaid visual status report; docs drift found |
| #552 | 2026-08-11 | done | Corrects #551 report citation/verification wording: file-line evidence for drift findings; distinguishes #201 /v1 characterization from absent S6 guarantee; Mermaid 11.16.0 parses 4 diagrams |
| #553 | 2026-08-11 | done | Corrects S8/S9 "still missing" lists: legacy-policy plans isolated, identity merges reversible; S9 cites #509's four zero-error 1,542-question runs; neither stage promoted |
| #554 | 2026-08-11 | done | Fixes alt+N tab jump typing stray GBP sign on Alt-sends-Escape terminals: SeamInput declines to consume 9 meta digits; failed priority=True attempt recorded; 2,332 pass; real-TTY verified |
| #555 | 2026-08-11 | done | Supersedes #554's failure attribution: pre-push fails on Seam-wiki linked worktree's 23 uncommitted files, not own tree; predicted self-clear wrong; worktree untouched; correction 2026-08-11-001 |
| #556 | 2026-08-11 | done | Completes codex's wiki-navigation slice: two markdown-it fail-open defaults (validateLink suppress, normalizeLink encode) fixed via overrides; 10->31 tests; 215 docs reachable; test-lane pin |
| #557 | 2026-08-11 | done | Correction: #556 promised full-suite result "recorded below" but none was pasted; measures 2,372 pass / 2 xfailed / 0 skip at f9dd0a5; pre-push now exits 0; correction 2026-08-11-002 |
| #558 | 2026-08-12 | changed | Closes all actionable wiki review gaps pre-merge: fragment validation, dated-doc homes, policy-era audit citations, URI scheme rejection; 61 tests; test-and-benchmark gets full-ancestry checkout |
| #559 | 2026-08-12 | done | Settings Reload now refreshes cached meta-digit fallback (stale cache kept intercepting glyphs until restart); mounted regression proves literal GBP sign accepted; 19+12 tests pass |

## Coverage

- 001–133: 133 entries (2026-04-15 → 2026-05-06)
- 134–245: 112 entries (2026-05-07 → 2026-05-25)
- 246–343: 98 entries (2026-05-25 → 2026-06-29)
- 344–439: 96 entries (2026-07-03 → 2026-07-21)
- 440–486: 47 entries (2026-07-21 → 2026-07-28)
- 487–526: 40 entries (2026-07-29 → 2026-08-02)
- 527–559: 33 entries (2026-08-03 → 2026-08-12)
- Total: 559 entries (all of #001–#559, oldest-first, dates non-decreasing).
- Entries recovered directly from HISTORY.md (straddle/gap entries, compressed from their metadata blocks): #133, #343, #439, #486 (4 entries).
- All other 555 rows come from the seven bounded timeline-lane digests (HISTORY.md line ranges 1–2600, 2601–5200, 5201–7800, 7801–10400, 10401–13000, 13001–15600, 15601–18092), each lane cross-checked at its range boundaries against the adjacent lane and against HISTORY.md directly where a lane boundary split an entry.

## Evidence manifest

Raw artifacts: none

Every row derives from in-repo history; verification was performed live
and preserved no external files.
