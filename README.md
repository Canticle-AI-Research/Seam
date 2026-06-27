# SEAM

Give your local AI agent persistent memory in one command.

SEAM is a local memory runtime for agents. It stores durable MIRL records in
SQLite, retrieves compact context with lexical, graph, temporal, and vector
signals, tracks provenance, exposes a dashboard/API, and gates benchmark claims
before they are treated as real progress.

## Install

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

Public release installer shape, for later release packaging:

```powershell
irm https://example.com/seam/install.ps1 | iex
```

```bash
curl -fsSL https://example.com/seam/install.sh | sh
```

Those public URLs are placeholders until SEAM has a published installer host.
Use the private `gh repo clone` commands above for this repo today.

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
