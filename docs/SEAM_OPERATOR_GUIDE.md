# SEAM Operator Guide

Practical runbook for interacting with SEAM, running tests, and validating the
live stack.

**Platform guides**

- **macOS** — [MACOS.md](MACOS.md) (install, Application Support layout, MCP, troubleshooting)
- **All platforms** — [setup.md](setup.md) (copy/paste installer flows)
- **Task runbooks** — [howto/README.md](howto/README.md)

**Command convention:** After a global install, use `seam` on PATH. From a
repo-local dev checkout, use `./.venv/bin/seam` (macOS / Linux) or
`.\.venv\Scripts\seam.exe` (Windows). Examples below show both the dev form
(`python seam.py` / `./.venv/bin/python seam.py`) and the installed shim (`seam`)
where they differ.

## 1. What SEAM uses

- SQLite for canonical truth, provenance, packs, and metadata
- SQLite `vector_index` by default for local vector search
- Optional Postgres + pgvector for a real external vector database (port 55432)
- Configurable embedding model:
  - default local deterministic hash model (no credentials needed)
  - optional OpenAI-compatible cloud embedding provider

## 2. Where the databases live

- **SQLite truth database** — whatever you pass to `--db` (e.g. `seam.db`, `seam_validate.db`)
- **SQLite vector index** — stored inside that same SQLite file unless pgvector is enabled
- **pgvector database** — separate Postgres container `seam-pgvector` on `localhost:55432`

**Default persistent database** (set automatically by the installer shims):

| Platform | Path |
|---|---|
| Windows | `%LOCALAPPDATA%\SEAM\state\seam.db` |
| macOS | `~/Library/Application Support/SEAM/state/seam.db` |
| Linux / WSL2 | `~/.local/share/seam/state/seam.db` |

Override any time with `SEAM_DB_PATH` in the shell or MCP client env.

## 3. Environment setup

### Install (first time)

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

Repo-local development bootstrap:

```bash
# macOS
sh ./installers/install_seam_macos.sh --dev

# Linux / WSL2
sh ./installers/install_seam_linux.sh --dev
```

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File .\installers\install_seam_windows.ps1 -Dev
```

Open a new terminal after a global install, then run `seam doctor`.

### Local deterministic baseline (no API key)

Windows (dev checkout):

```powershell
python seam.py doctor
python seam.py --db seam_validate.db stats
```

macOS / Linux (dev checkout):

```bash
./.venv/bin/python seam.py doctor
./.venv/bin/python seam.py --db seam_validate.db stats
```

Installed shim (all platforms):

```bash
seam doctor
seam --db seam_validate.db stats
```

### Live cloud + pgvector path

Credentials stay in a private env file outside the repo (for example
`~/.config/seam/.env` on macOS / Linux).

Windows PowerShell:

```powershell
$env:OPENAI_API_KEY="your-real-openai-api-key"
$env:SEAM_EMBEDDING_PROVIDER="openai-compatible"
$env:SEAM_EMBEDDING_MODEL="text-embedding-3-small"
$env:SEAM_PGVECTOR_DSN="host=localhost port=55432 dbname=seam user=$env:POSTGRES_USER password=$env:POSTGRES_PASSWORD"

python seam.py doctor
python seam.py --db seam_validate.db stats
```

macOS / Linux bash:

```bash
export OPENAI_API_KEY="your-real-openai-api-key"
export SEAM_EMBEDDING_PROVIDER="openai-compatible"
export SEAM_EMBEDDING_MODEL="text-embedding-3-small"
export SEAM_PGVECTOR_DSN="host=localhost port=55432 dbname=seam user=$POSTGRES_USER password=$POSTGRES_PASSWORD"

seam doctor
seam --db seam_validate.db stats
```

### Start the local pgvector database

Windows PowerShell:

```powershell
docker compose --env-file <path-to-private-env> up -d seam-pgvector
```

macOS / Linux bash:

```bash
docker compose --env-file "$HOME/.config/seam/.env" up -d seam-pgvector
```

Image: `pgvector/pgvector:0.8.3-pg18-trixie` | Container: `seam-pgvector` | Port: `55432`

If the container exists but is stopped:

```bash
docker start seam-pgvector
```

On macOS, Docker Desktop must be running before `docker compose` or `seam doctor`
pgvector checks.

## 4. CLI surface

```bash
seam --help
```

Key command groups:

| Command | What it does |
|---|---|
| `compile-nl` / `remember` | Compile natural language into MIRL and persist |
| `compile-dsl` | Compile SEAM DSL into MIRL and persist |
| `ingest` | Store raw text from a file or stdin |
| `verify` | Verify MIRL from a text file |
| `persist` | Persist MIRL from a text file |
| `search` | Combined search over persisted MIRL |
| `retrieve` / `hybrid-search` | Run retrieval and rank results |
| `memory` | Progressive-disclosure memory tools |
| `context` / `rag-search` | Retrieve context for generation |
| `index` / `rag-sync` | Sync persisted records into vector indexes |
| `pack` | Build a pack from persisted record IDs |
| `decompile` | Decompile persisted record IDs |
| `trace` | Trace provenance for an object ID |
| `reconcile` | Reconcile claims and emit relation/state updates |
| `stats` | Run the glassbox benchmark summary |
| `doctor` | Check install health and run smoke test |
| `benchmark` | Run or inspect SEAM benchmark suites |
| `surface` | Read/write SEAM-HS/1 holographic memory surfaces |
| `shell` / `chat` | Start an interactive SEAM memory REPL |
| `dashboard` | Launch the Textual terminal dashboard |
| `serve` / `webui` | Run the REST API server and browser dashboard |
| `mcp` | Run the SEAM agent MCP bridge |

## 5. How to interact with SEAM

Examples use the installed `seam` shim. Substitute `python seam.py` or
`./.venv/bin/python seam.py` when working from a dev checkout.

### Compile natural language into MIRL and persist

```bash
seam --db seam.db compile-nl "We need a translator back into natural language for memory workflows."
```

Use `--no-persist` to compile without storing.

### Search persisted memory

```bash
seam --db seam.db search "translator natural language" --budget 3
seam --db seam.db search "thread memory mode" --scope thread --budget 5
```

### Retrieve with ranking

```bash
seam --db seam.db retrieve "translator natural language" --mode mix
seam --db seam.db retrieve "translator natural language" --mode vector
seam --db seam.db retrieve "translator natural language" --mode graph
```

### Sync vector indexes

```bash
seam --db seam.db index
```

### Build packs

```bash
seam --db seam.db pack clm:2,sta:ent:project:seam --mode context --budget 128
seam --db seam.db pack clm:2,sta:ent:project:seam --mode exact --budget 128
```

### Decompile and trace

```bash
seam --db seam.db decompile clm:2,sta:ent:project:seam
seam --db seam.db trace clm:2
```

### Check install health

```bash
seam doctor
```

### Interactive shell

```bash
seam shell
```

### Browser dashboard and REST API

```bash
seam serve --host 127.0.0.1 --port 8765
# or
seam webui
```

### MCP stdio bridge (Cursor, Claude Desktop, other MCP clients)

```bash
seam mcp stdio
# or, with pgvector auto-start when Docker is available:
seam-mcp --ensure-pgvector
```

On macOS, global shims live in `~/.local/bin/`. Point your MCP client at
`seam-mcp` and set `SEAM_DB_PATH` if you use a non-default database. See
[MACOS.md](MACOS.md) for a sample client config.

## 6. Testing SEAM

### Run the full suite

Windows:

```powershell
python -m pytest test_seam_all\test_seam.py -q
```

macOS / Linux:

```bash
./.venv/bin/python -m pytest test_seam_all/test_seam.py -q
```

### Run one specific test

Windows:

```powershell
python -m pytest test_seam_all\test_seam.py -k "test_retrieval_benchmark_uses_gold_fixtures" -v
```

macOS / Linux:

```bash
./.venv/bin/python -m pytest test_seam_all/test_seam.py -k "test_retrieval_benchmark_uses_gold_fixtures" -v
```

### Run with strict ResourceWarning detection

Windows:

```powershell
python -W error::ResourceWarning -m pytest test_seam_all\test_seam.py -k "test_symbol_export_and_query_expansion" -v
```

macOS / Linux:

```bash
./.venv/bin/python -W error::ResourceWarning -m pytest test_seam_all/test_seam.py -k "test_symbol_export_and_query_expansion" -v
```

### Recommended operator test loop

Windows:

```powershell
python -m pytest test_seam_all\test_seam.py -q
python seam.py doctor
python seam.py --db seam_validate.db stats
```

macOS / Linux:

```bash
./.venv/bin/python -m pytest test_seam_all/test_seam.py -q
./.venv/bin/python seam.py doctor
./.venv/bin/python seam.py --db seam_validate.db stats
```

Use the local baseline when changing core logic. Use the cloud path when
validating real embedding behavior.

## 7. Worked example

### Step 1: compile and persist

```bash
seam --db seam_demo.db compile-nl "We need a translator back into natural language for memory workflows."
```

SEAM emits `RAW`, `SPAN`, `PROV`, `ENT`, `CLM`, and `STA` records. Key retrieval
records include `clm:2` (predicate `translator`) and `sta:ent:project:seam`.

### Step 2: search

```bash
seam --db seam_demo.db search "translator natural language" --budget 3
```

Top result should include `clm:2`. Results show lexical, semantic, graph, and
temporal contribution reasons. Evidence chain includes `span:1`.

### Step 3: run one benchmark test

macOS / Linux:

```bash
./.venv/bin/python -m pytest test_seam_all/test_seam.py -k "test_retrieval_benchmark_uses_gold_fixtures" -v
```

Windows:

```powershell
python -m pytest test_seam_all\test_seam.py -k "test_retrieval_benchmark_uses_gold_fixtures" -v
```

Should pass and confirm the hardened fixture benchmark loads and checks current
success gates.

## 8. How to connect your own embedding model

SEAM expects a model with:

```python
name: str
dimension: int
embed(text: str) -> list[float]
```

Minimal example:

```python
from seam import SeamRuntime


class MyEmbeddingModel:
    name = "my-local-model"
    dimension = 768

    def embed(self, text: str) -> list[float]:
        raise NotImplementedError("Replace with your model call")


runtime = SeamRuntime("seam.db", embedding_model=MyEmbeddingModel())
```

For the OpenAI-compatible cloud path:

Windows PowerShell:

```powershell
$env:OPENAI_API_KEY="your-real-openai-api-key"
$env:SEAM_EMBEDDING_PROVIDER="openai-compatible"
$env:SEAM_EMBEDDING_MODEL="text-embedding-3-small"
```

macOS / Linux bash:

```bash
export OPENAI_API_KEY="your-real-openai-api-key"
export SEAM_EMBEDDING_PROVIDER="openai-compatible"
export SEAM_EMBEDDING_MODEL="text-embedding-3-small"
```

## 9. What to do when something fails

| Symptom | Fix |
|---|---|
| `command not found: seam` (macOS / Linux) | `source ~/.zprofile` or open a new terminal; confirm `~/.local/bin` is on PATH — see [MACOS.md](MACOS.md) |
| `doctor` says API key missing | Set `OPENAI_API_KEY` in the same shell session |
| `doctor` says pgvector DSN missing | Set `SEAM_PGVECTOR_DSN` |
| `doctor` reports `HTTP 429` | Provider is reachable; check quota/billing — see [errors.md](errors.md) |
| `stats` regresses | Inspect fixture-level `expected_ids`, `rejected_ids`, `rejection_rate` |
| Search returns stale results | Add or strengthen a benchmark fixture |
| Port 55432 refused | Run `docker ps` and check `seam-pgvector` is running; on macOS confirm Docker Desktop is up |
| `ModuleNotFoundError: textual` | `pip install -e ".[dash]"` in the active venv — see [errors.md](errors.md) |

## 10. Files worth knowing

- `README.md`
- `docs/MACOS.md` — macOS install, layout, MCP, troubleshooting
- `docs/setup.md`
- `docs/errors.md`
- `docs/howto/README.md`
- `docs/BENCHMARK_SOP.md`
- `docs/PGVECTOR_LOCAL.md`
- `docs/ENGINEERING_LOG.md`
- `docs/RETRIEVAL_EVAL_V1.md`
- `docs/SOP_MODEL_INTEGRATION.md`
- `docs/retrieval_gold_fixtures.json`
- `test_seam_all/test_seam.py`