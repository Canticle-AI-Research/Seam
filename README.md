# SEAM

Give your local AI agent persistent memory in one command.

SEAM is a local memory runtime for agents. It stores durable MIRL records in
SQLite, retrieves compact context with lexical, graph, temporal, and vector
signals, tracks provenance, exposes a dashboard/API, and gates benchmark claims
before they are treated as real progress.

> **Documentation:** Start at the [SEAM Wiki](docs/README.md) for task-first
> routes into operator guides, architecture, current state, evidence, and plans.

## Install

Authorized private-repository install:

```bash
python -m pip install "seam-runtime @ git+ssh://git@github.com/BlackhatShiftey/Seam.git@main"
```

Install with REST API and dashboard extras:

```bash
python -m pip install "seam-runtime[server,dash] @ git+ssh://git@github.com/BlackhatShiftey/Seam.git@main"
```

Repository authorization is required. Once private release tags exist, replace
`@main` with a pinned tag. The clone-and-installer flows below remain the full
operator setup path for repo-local development, persistent state setup, and
platform shims.

## Public agent SDK

Custom agents should depend on the separate Apache-2.0 `seam-client` package,
not this private runtime package. The public SDK provides sync/async
`remember`, `recall`, and context hooks over the stable `/v1` API without
shipping MIRL, HS/1, storage, retrieval, graph, PACK, or benchmark internals.

```bash
python -m pip install seam-client
```

See [`docs/PUBLIC_SDK_API.md`](docs/PUBLIC_SDK_API.md). Hosted access and API
credentials remain separately provisioned.

## Private local Python SDK

Agents can use one local SDK for canonical knowledge and non-canonical public
reasoning records:

```python
from seam_runtime import SeamSDK

with SeamSDK("seam.db", allow_pgvector_env=False) as seam:
    run = seam.start_reasoning(
        "Choose the safest implementation path.",
        ns="my-project",
        scope="thread",
        agent_id="planner",
    )
    run.add_node("question", "Which option has verified rollback evidence?")
    retrieval = run.retrieve(
        "verified rollback evidence",
        mode="mix",
        budget=5,
        graph_hops=2,
    )
    reasoning_graph = run.graph()
```

Reasoning nodes are concise, typed, append-only public justifications—not
hidden chain-of-thought or canonical facts. Accepted conclusions require
explicit support, and nothing is promoted into MIRL automatically. See
[`docs/REASONING_GRAPH.md`](docs/REASONING_GRAPH.md).

`run.retrieve(...)` returns live selected records while atomically recording a
bounded decision and content-free candidate ledger: plan/policy/model identity,
selected and rejected record IDs, evidence fingerprints, scores, controlled
reason codes, and latency. It makes no provider call by default and does not
copy record payloads into the reasoning graph.

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
- If a command fails, stop and report the exact command and error. Check
  `docs/errors.md` for the symptom before giving up, and report whether that
  reference resolved it.

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
8. Test memory retrieval against the ingested docs:
   `seam memory search "current SEAM repo status"`
   `seam context "current SEAM repo status" --retrieval-mode mix --view prompt`
9. Prove write-then-read persistence with a fact this session creates, not a
   pre-existing doc:
   `seam remember "SEAM setup smoke test <unique token>"`
   `seam memory search "setup smoke test"`
   Confirm the exact fact just written comes back before treating memory as
   working.
10. If this agent supports MCP, configure it to launch:
   `seam-mcp`
   Or, when pgvector is needed and Docker is available:
   `seam-mcp --ensure-pgvector`
   Verify the server actually responds: issue an MCP tool-list/discovery call
   against the running process and confirm SEAM's tools (memory search/get,
   context, ingest) appear before reporting MCP as configured.
11. Report back with:
   - install path used
   - optional extras installed
   - whether `seam doctor` passed
   - whether API keys/local config were set in Web UI Settings or manually
   - whether memory search/context returned useful repo context
   - whether the write-then-read smoke test round-tripped correctly
   - whether MCP was configured and its tool list verified, or only CLI
     memory is available
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
seam knowledge search "durable memory" --hops 2
seam knowledge node ent:project:seam
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

Every persisted chat, ingest, MCP write, or MIRL batch automatically updates
SEAM's temporal all-agent knowledge graph. Open the dashboard's **Memory** tab
(or `/?view=knowledge`) to search entities and claims, traverse typed edges,
filter by contributing agent, inspect historical knowledge, and open graph-backed
pages with facts, backlinks, sources, confidence, and canonical MIRL. See
[`docs/KNOWLEDGE_GRAPH.md`](docs/KNOWLEDGE_GRAPH.md).

The Memory workspace also exposes a conservative **5W1H+Then** lens, explicit
evidence-derived trust states, seven selectable graph/workspace layers, and an
append-only **LIVE** event replay. Chat asserts only supported or verified
memory; contested, model-only, stale, refuted, and superseded records remain
visible for inspection but fail closed at the answer-context boundary. Optional
local Qwen or authenticated remote J-lens workers require verified artifacts and
activation access; ordinary hosted-provider traces are labeled only as
structured workspace telemetry, never hidden reasoning or J-Space.

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

- [Operator guide](docs/SEAM_OPERATOR_GUIDE.md) - day-to-day commands, doctor checks, benchmark posture, and failure triage (Windows, macOS, and Linux).
- [macOS guide](docs/MACOS.md) - install paths, Application Support layout, Docker/pgvector, MCP, and macOS troubleshooting.
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

J-lens model weights, analyzers, cloud workers, provider credentials, and
pgvector remain operator-configured optional resources outside the repository.
With no `SEAM_JSPACE_BACKEND`, SEAM reports `structured_workspace_only`, performs
no model download/network call, and still provides the graph, trust gate,
structured SSE workspace, LIVE view, and replay.

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

Benchmark evidence is the proof layer for SEAM's commercial value. It does not
grant trademark rights, imply endorsement, or provide access to private hosted,
enterprise, customer-specific, or unreleased SEAM offerings.

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

## Package Releases

The manual **Package release** GitHub Actions workflow
([`.github/workflows/package-release.yml`](.github/workflows/package-release.yml))
is `workflow_dispatch`-only and takes one input: the exact `version` already set
in `pyproject.toml`. It has two jobs:

- **`build`** — verifies the requested version matches `pyproject.toml` and
  fails otherwise, builds the wheel and sdist, runs `twine check`, smoke-tests
  the wheel by installing it with the `[server,pgvector]` extras alongside
  `seam-client==2.0.0` and running `seam`, `seam-mcp`, and `seam-server`
  `--help`, then uploads the distributions as a 7-day artifact.
- **`private-github-release`** — gated on the `private-package-release`
  environment, downloads that artifact and runs `gh release create` against
  **this private repository only**.

**There is no PyPI path.** The workflow has no publish job, no target selector,
and no `id-token` permission, so it cannot publish to an index even by mistake.
The package is additionally marked `Private :: Do Not Upload` in
`pyproject.toml` as a tripwire against an accidental upload, and
`tools/release/verify_public_safe.py` blocks secret-shaped content and private
paths on push. Publishing anything public requires a separately built and
reviewed artifact — not this workflow and not this package.

The existing `seam-runtime` 1.3.1 release on PyPI and `server.json` describe the
legacy Apache-2.0 artifact. They remain pinned to that legacy public release.
Publishing a later PyPI version requires a clean public artifact with its own
license, package layout, and review; it does not authorize publishing this
repository.

## License

**Self-hosting SEAM is free.** The SEAM Distributed Runtime, version 2.4.0 or
later, is published under the Business Source License 1.1
([`LICENSES/BUSL-1.1.txt`](LICENSES/BUSL-1.1.txt)). You may run it on your own
hardware or on infrastructure you rent, for your own or your organization's
purposes — including internal commercial production use — at no charge, with no
limit on scale or number of users. Non-commercial research, education, and
publishing benchmark or evaluation results are permitted too.

The one thing the grant withholds is offering the Distributed Runtime to third
parties on a hosted or embedded basis as a *competitive offering*: a paid
product or service that significantly overlaps with a paid version of SEAM.
Free offerings are never competitive, and neither is internal use across
affiliates under common control. Each published version converts to MPL 2.0
four years after it is published.

Everything below concerns material outside the Distributed Runtime.

The rest of the SEAM repository and all non-public MIRL- and HS/1-related
material are proprietary. MIRL's specification text, source code, schemas as expressed,
documentation, examples, tests, diagrams, and other original works of
authorship are copyrighted and reserved. HS/1's specification, container
expression, visual designs, codecs, surface library, source, documentation,
examples, tests, and related original works are separately named copyrighted
and reserved materials. Repository access does not grant a right to copy,
publish, distribute, implement, host, commercialize, train on, or use that
material in another project.

Exact versions previously published at
<https://github.com/BlackhatShiftey/Seam_Runtime> under Apache-2.0 retain that
license. The legacy grant is not revoked, but it does not apply automatically
to later private versions, unpublished changes, or new MIRL or HS/1 material.
The private-to-public mirror is frozen pending a separately designed and
legally reviewed distribution boundary. The Apache text applicable to legacy
material is preserved at
[LICENSES/Apache-2.0.txt](LICENSES/Apache-2.0.txt).

The controlling terms are [LICENSE](LICENSE), [NOTICE](NOTICE), and
[COMMERCIAL_LICENSE.md](COMMERCIAL_LICENSE.md). Any external permission
requires a separate written agreement from the project owner.
