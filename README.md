# SEAM

Give your local AI agent persistent memory in one command.

SEAM is a local memory runtime for agents. It stores durable MIRL records in
SQLite, retrieves compact context with lexical, graph, temporal, and vector
signals, tracks provenance, exposes a dashboard/API, and gates benchmark claims
before they are treated as real progress.

## Install

GitHub package install for the SEAM runtime:

```bash
python -m pip install "seam-runtime @ git+https://github.com/BlackhatShiftey/Seam_Runtime.git@main"
```

Install with REST API and dashboard extras:

```bash
python -m pip install "seam-runtime[server,dash] @ git+https://github.com/BlackhatShiftey/Seam_Runtime.git@main"
```

Once release tags exist, replace `@main` with a pinned tag such as `@v0.1.0`.
The clone-and-installer flows below remain the full operator setup path for
repo-local development, persistent state setup, and platform shims.

Private repo install requires an authenticated GitHub CLI session.

Windows PowerShell:

```powershell
gh repo clone BlackhatShiftey/Seam Seam; cd Seam; powershell -ExecutionPolicy Bypass -File .\installers\install_seam_windows.ps1
```

macOS:

```bash
gh repo clone BlackhatShiftey/Seam Seam && cd Seam && sh ./installers/install_seam_macos.sh
```

Linux / WSL2:

```bash
gh repo clone BlackhatShiftey/Seam Seam && cd Seam && sh ./installers/install_seam_linux.sh
```

Repo-local Linux development bootstrap:

```bash
gh repo clone BlackhatShiftey/Seam Seam && cd Seam && sh ./installers/install_seam_linux.sh --dev
```

## Agent Setup Prompt

After cloning SEAM, paste this prompt into your coding agent to have it install
SEAM, verify the local setup, and configure SEAM as persistent memory for the
workspace.

```text
You are setting up SEAM from this repository.

Goal:
Install SEAM completely for local development and operator use, then configure
it as persistent memory for this agent/workspace.

Rules:
- Read `AGENTS.md` first and follow repo-local instructions.
- Do not expose, print, copy, delete, or summarize secrets.
- Do not ingest secrets, `.env` files, credential files, private keys, provider
  session links, ignored local artifacts, or private chat/share links.
- API keys, local `.env` files, and local `.conf` files are operator-owned.
  The operator can set them in the SEAM Web UI Settings panel or maintain them
  manually in ignored local config files.
- Prefer project installers and documented commands over ad hoc setup.
- Do not install `bench-judge`, `bench-mem0`, or `bench-zep` unless the operator
  explicitly approves provider/API-key benchmark dependencies.
- If a command fails, stop and report the exact command and error.

Steps:
1. Confirm the current directory is the SEAM repo.
2. Run the platform installer:
   - Linux/WSL2: `sh ./installers/install_seam_linux.sh --dev`
   - macOS: `sh ./installers/install_seam_macos.sh --dev`
   - Windows PowerShell: `powershell -ExecutionPolicy Bypass -File .\installers\install_seam_windows.ps1 -Dev`
3. Install useful local extras for normal operator work:
   `python -m pip install -e ".[server,dash,pgvector,sbert,rerank]"`
4. Verify the install:
   `seam doctor`
5. Ask the operator to set any needed provider keys and local config before
   enabling paid/provider-backed features:
   - Web UI path: run `seam webui`, open Settings, enter provider keys,
     `SEAM_CHAT_API_KEY`, `SEAM_CHAT_BASE_URL`, `SEAM_CHAT_MODEL`,
     `SEAM_PGVECTOR_DSN`, `SEAM_API_TOKEN`, or `SEAM_LOCAL_ENV` as needed, then
     save the local env from the Settings panel.
   - Manual path: create or edit ignored local `.env` or `.conf` files, export
     the needed variables in the shell, and never commit or ingest those files.
6. Re-run:
   `seam doctor`
7. Ingest safe repo context as persistent memory:
   `seam ingest README.md --persist`
   `seam ingest AGENTS.md --persist`
   `seam ingest PROJECT_STATUS.md --persist`
   `seam ingest REPO_LEDGER.md --persist`
8. Test memory retrieval:
   `seam memory search "current SEAM repo status"`
   `seam context "current SEAM repo status" --retrieval-mode mix --view prompt`
9. If this agent supports MCP, configure it to launch:
   `seam-mcp`
   Or, when pgvector is needed and Docker is available:
   `seam-mcp --ensure-pgvector`
10. Report back with:
   - install path used
   - optional extras installed
   - whether `seam doctor` passed
   - whether API keys/local config were set in Web UI Settings or manually
   - whether memory search/context returned useful repo context
   - whether MCP was configured or only CLI memory is available
```

## 60-Second Demo

After install, open a new terminal. The same commands work on Windows
PowerShell and Linux / WSL2 because `seam` is a platform-agnostic shim:

```bash
seam doctor
seam ingest README.md --persist
seam memory search "persistent agent memory"
seam retrieve "persistent agent memory" --mode mix --budget 5
seam context "persistent agent memory" --retrieval-mode mix --view prompt
seam dashboard --snapshot --no-clear
```

Inside the dashboard, use `reload` or `/reload` to refresh the visible runtime
state, metrics, panels, and chart surfaces without restarting.

To configure API keys and local runtime settings without editing files by hand,
run the browser Web UI and open Settings:

```bash
seam webui --host 127.0.0.1 --port 8765
```

Settings covers provider keys, chat/API settings, embedding settings, database
paths, pgvector DSNs, `SEAM_LOCAL_ENV`, REST API tokens, and save/reload local
env controls. Operators can also maintain ignored local `.env` or `.conf` files
manually; those files must not be committed or ingested as memory.

## Why SEAM

- Persistent local memory: SQLite is the canonical source of truth.
- Efficient RAG: `vector`, `graph`, `hybrid`, and `mix` retrieval modes.
- Progressive disclosure: `seam memory search` gives compact IDs first; `seam memory get <ids>` fetches full records only when needed.
- Agent bridge: `seam mcp stdio` / `seam-mcp` exposes a standard MCP server for Gemini, Claude, Cursor, and other agents. Gemini's project config starts it with `--ensure-pgvector` so Docker Compose pgvector is ready before MCP tool discovery. `seam mcp serve` remains available for legacy JSON-lines wrappers.
- Provenance: records keep refs, evidence, trace edges, and source document status.
- Benchmark discipline: benchmark bundles are hash-verified, diffed, gated, and separated from holdout publication runs.
- Operator surface: CLI, Textual dashboard, REST API, and installer shims all use the same runtime.

## Core Commands

Cross-platform (Windows PowerShell and Linux / WSL2 share the `seam` shim):

```bash
seam ingest path/to/file.txt --persist
seam remember "SEAM stores durable memory for agents."
seam memory search "durable memory"
seam memory get clm:1,sta:ent:project:seam --timeline
seam retrieve "durable memory" --mode mix --trace
seam context "durable memory" --retrieval-mode mix --view evidence
seam surface compile path/to/file.txt --output file.seam.png --mode rgb24
seam surface query file.seam.png "durable memory"
seam shell
seam index
seam reindex
seam dashboard
seam mcp stdio
seam-mcp --ensure-pgvector
seam mcp serve
seam serve --host 127.0.0.1 --port 8765
seam benchmark run all --persist
seam benchmark gate seam-benchmark-report.json
```

## RAG Architecture

SEAM takes the useful parts of graph RAG systems while keeping canonical memory
inside MIRL:

1. ingest text or files
2. compile semantic records into MIRL
3. persist canonical records and document status in SQLite
4. derive vector indexes and graph edges from record IDs
5. retrieve with `vector`, `graph`, `hybrid`, or `mix`
6. build a token-bounded PACK for the agent

Vector stores are acceleration layers, not source of truth. PgVector and the
SQLite vector table can be rebuilt from MIRL records.

See [docs/RAG_ARCHITECTURE.md](docs/RAG_ARCHITECTURE.md) for the LightRAG and
claude-mem comparison, retrieval mode details, and agent bridge notes.

## Setup Details

- Command cookbook: [docs/setup.md](docs/setup.md)
- Fresh Linux resume checks: [docs/setup.md#resume-current-repo-state-on-fresh-linux](docs/setup.md#resume-current-repo-state-on-fresh-linux)
- Installer reference: [installers/README.md](installers/README.md)
- Troubleshooting: [docs/errors.md](docs/errors.md)
- Task runbooks: [docs/howto/README.md](docs/howto/README.md)
- Active/inactive code layout: [docs/CODE_LAYOUT.md](docs/CODE_LAYOUT.md)

## Operator Manual

For help beyond the quickstart, use these docs as the operator manual:

- [Operator guide](docs/SEAM_OPERATOR_GUIDE.md) - day-to-day commands, doctor checks, benchmark posture, and failure triage.
- [Setup guide](docs/setup.md) - platform setup, installer flows, dashboard chat model configuration, and supported command shapes.
- [Task runbooks](docs/howto/README.md) - short workflows for common operator tasks.
- [Engineering manual](docs/engineering/README.md) - architecture, security, change/test/incident SOPs, and verification discipline.
- [Troubleshooting and error index](docs/errors.md) - look up failures by symptom or error type before changing code.

### Error Index

Start with [docs/errors.md](docs/errors.md). Current indexed failure types include:

- `ModuleNotFoundError: No module named 'textual'`
- `SEAM doctor: FAIL`
- `PgVector: configured but unreachable`
- Chroma path/index sync failure
- Benchmark bundle verification failure
- `HTTP 429` provider quota or rate-limit symptoms

Default persistent database paths:

- Windows: `%LOCALAPPDATA%\SEAM\state\seam.db`
- macOS: `~/Library/Application Support/SEAM/state/seam.db`
- Linux / WSL2: `~/.local/share/seam/state/seam.db`

## Optional Extras

```powershell
python -m pip install -e ".[dash]"
python -m pip install -e ".[server]"
python -m pip install -e ".[pgvector]"
python -m pip install -e ".[sbert]"
python -m pip install -e ".[agent]"
python -m pip install -e ".[rerank]"
python -m pip install -e ".[all-extras]"
```

Extras keep the base install focused:

- `dash`: Textual dashboard
- `server`: FastAPI/Uvicorn REST API
- `pgvector`: PostgreSQL PgVector adapter
- `sbert`: local sentence-transformer embeddings
- `agent`: reserved agent bridge extra; current stdio bridge has no extra dependency
- `rerank`: reranker model dependencies

## REST API

Install the server extra:

```powershell
python -m pip install -e ".[server]"
```

Run locally:

```powershell
seam serve --host 127.0.0.1 --port 8765
```

Useful endpoints:

- `GET /health`
- `GET /stats`
- `POST /compile`
- `POST /compile-dsl`
- `GET /search?query=durable+memory&budget=5`
- `POST /context`
- `POST /lossless-compress`
- `POST /persist`

Set `SEAM_API_TOKEN` to require `Authorization: Bearer <local-token>` for
protected endpoints.

## Benchmark Glassbox

```bash
seam benchmark run all --persist --output seam-benchmark-report.json
seam benchmark show latest
seam benchmark verify seam-benchmark-report.json
seam benchmark gate seam-benchmark-report.json
seam benchmark diff <baseline-report.json> seam-benchmark-report.json
```

### Measure Progress (Or Regression)

The visual-memory loop is a measurable iteration engine. To prove a change
improves SEAM rather than regressing it:

```bash
# 1. capture baseline
seam benchmark run all --persist --output baseline.json

# 2. make the change

# 3. capture after-state and compare
seam benchmark run all --persist --output after.json
seam benchmark diff baseline.json after.json
seam benchmark gate after.json
```

`benchmark diff` shows per-case green/red/gray deltas and added/removed cases.
`benchmark gate` enforces the release-blocking minimums across all eight
families. To extend coverage of structured document features, add a fixture
case to `benchmarks/fixtures/surface_cases.json`; if the underlying extractor
does not exist yet in `seam_runtime/lossless.py:_structural_quote_spans`, the
gate fails and the fix is local. See [docs/howto/README.md](docs/howto/README.md)
section 4 for the failing-case-driven extension runbook.

### Publication Discipline

Benchmark evidence is the proof layer for SEAM's commercial value; it does not
grant commercial, hosted, SaaS, API, managed-service, embedded, redistribution,
or closed-source rights.

Publication claims must include bundle hash, case hashes, fixture hashes, git
SHA, diff output, gate output, and holdout output when the claim is external.
Do not claim "best", "production proven", or "commercial-grade" unless the
benchmark bundle supports that exact claim.

## Machine-First Layer

The product entrypoint is simple: install SEAM, persist memory, retrieve
context. Under that surface, SEAM is still machine-first:

- `MIRL`: canonical memory IR
- `PACK`: prompt-time context view
- `SEAM-LX/1`: exact machine-text envelope for lossless workflows
- `SEAM-RC/1`: directly readable compressed machine language
- `SEAM-HS/1`: lossless PNG-backed surface for MIRL, RC/1, LX/1, or raw bytes

The design stance is unchanged: SQLite is canonical, derived indexes are
rebuildable, lossless claims require exact reconstruction, and compressed
artifacts must remain useful to an agent without hiding provenance.

## License

SEAM is proprietary source-available software under the SEAM Source-Available
License. The repository is public for review, evaluation, and contribution; no
open-source license is granted.

You may review, evaluate, fork for contribution, and use SEAM locally for
personal, educational, research, or non-commercial purposes. You may not host,
SaaS, sell, embed, redistribute, deploy for customers, commercialize, or use
SEAM in a closed-source or commercial project without a separate written
commercial license from the copyright holder.

Commercial use is available with permission: get a separate written commercial
license from the copyright holder before using SEAM in a paid product, hosted
service, customer deployment, closed-source product, or business offering.

Contributions grant the project owner rights to keep developing SEAM and to
commercially license SEAM without needing later contributor permission.

See [LICENSE](LICENSE) and [NOTICE](NOTICE).
