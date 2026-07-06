# SEAM on macOS

Operator guide for installing and running SEAM on macOS (Apple Silicon and Intel).
Commands use bash/zsh unless noted.

For day-to-day workflows after install, see [howto runbooks](howto/README.md).
For the full operator manual (commands, tests, failure triage on all platforms),
see [SEAM Operator Guide](SEAM_OPERATOR_GUIDE.md).
For failures by symptom, see [errors.md](errors.md).

## Prerequisites

- **macOS 12+** (Monterey or later recommended)
- **Python 3.10+** — check with `python3 --version`
  - If missing: install from [python.org](https://www.python.org/downloads/macos/) or `brew install python`
- **Git** and **GitHub CLI** (`gh`) for private-repo clone installs — `brew install gh` then `gh auth login`
- **Docker Desktop** (optional) — only if you want the Postgres + pgvector backend

## Install options

### Option A — PyPI package (public runtime)

When you only need the runtime, not the full private development repo:

```bash
python3 -m pip install --upgrade pip
python3 -m pip install "seam-runtime[server,dash]"
seam doctor
```

Add pgvector or local embeddings when needed:

```bash
python3 -m pip install "seam-runtime[pgvector,sbert]"
```

### Option B — One-line private repo install

Requires `gh auth login` first.

```bash
gh repo clone BlackhatShiftey/Seam Seam && cd Seam && sh ./installers/install_seam_macos.sh
```

Open a **new terminal** (or `source ~/.zprofile`) so PATH picks up the installer changes, then:

```text
seam doctor
seam --help
seam dashboard --snapshot --no-clear
```

### Option C — From an existing checkout

```bash
cd /path/to/Seam
sh ./installers/install_seam_macos.sh
```

### Option D — Repo-local development bootstrap

Use this when you are hacking on SEAM itself. Creates `.venv` in the repo, installs
`[all-extras]` + `pytest`, and runs doctor plus history/stream verification gates.

```bash
cd /path/to/Seam
sh ./installers/install_seam_macos.sh --dev
```

After `--dev`, call SEAM through the repo venv until you install global shims:

```bash
./.venv/bin/python seam.py doctor
./.venv/bin/seam ingest README.md --persist
```

Install useful operator extras into the dev venv:

```bash
./.venv/bin/python -m pip install -e ".[server,dash,pgvector,sbert,rerank]"
```

The dev bootstrap does **not** install Node or build the `webui/` Vite project.
The shipped browser dashboard is served directly by `seam serve` / `seam webui` with
no build step.

## What the installer does

**Default mode** (`install_seam_macos.sh` without `--dev`):

- Creates a dedicated runtime under `~/Library/Application Support/SEAM/`
- Installs SEAM into that runtime with the `[dash]` extra
- Writes global command shims to `~/.local/bin/` (`seam`, `seam-benchmark`, `seam-dash`)
- Sets `SEAM_DB_PATH` in each shim to the persistent database
- Appends a marked `PATH` block to `~/.profile`, `~/.bashrc`, and/or `~/.zprofile`
  (skipped if already present)
- Runs `seam doctor`

**`--dev` mode:**

- Creates or reuses `repo/.venv` (pre-creates `lib64` for external-drive compatibility)
- Installs `requirements.txt`, editable `.[all-extras]`, and `pytest`
- Runs `seam.py doctor`, history integrity/routing/snapshot/continuity, and stream checks
- Does not install global shims

## Directory layout

| Path | Purpose |
|---|---|
| `~/Library/Application Support/SEAM/runtime/` | Managed Python venv (default install) |
| `~/Library/Application Support/SEAM/state/seam.db` | Default persistent SQLite database |
| `~/.local/bin/seam` | Global command shim (sets `SEAM_DB_PATH`) |
| `~/.local/bin/seam-benchmark` | Benchmark shim |
| `~/.local/bin/seam-dash` | Textual dashboard shim |
| `repo/.venv/` | Repo-local dev venv (`--dev` mode only) |
| `~/.config/seam/.env` | Recommended location for local credentials (never commit) |

Override the database path any time:

```bash
export SEAM_DB_PATH="$HOME/path/to/custom/seam.db"
seam doctor
```

## PATH and shell profiles

The installer adds a block like this to your shell profiles:

```bash
# >>> SEAM installer >>>
export PATH="$HOME/.local/bin:$PATH"
# <<< SEAM installer <<<
```

If `seam` is not found after install:

```bash
source ~/.zprofile   # zsh (default macOS shell)
# or
source ~/.bashrc
```

Confirm:

```bash
which seam
echo "$PATH" | tr ':' '\n' | grep '.local/bin'
```

## First memory check

```bash
seam ingest README.md --persist
seam memory search "persistent memory"
seam retrieve "persistent memory" --mode mix --budget 5
seam context "persistent memory" --retrieval-mode mix --view prompt
seam dashboard
```

Inside the Textual dashboard, type `reload` to refresh panels without restarting.

## Optional extras

Base install pulls `requirements.txt` (`rich`, `tiktoken`; `chromadb` is optional via the `chroma` extra).

| Extra | Installs | When you need it |
|---|---|---|
| `dash` | `textual` | Textual terminal dashboard |
| `server` | `fastapi`, `uvicorn` | REST API and browser Web UI |
| `pgvector` | `psycopg[binary]` | Postgres pgvector backend |
| `sbert` | `sentence-transformers` | Local neural embeddings |
| `chroma` | `chromadb` | Chroma vector backend (opt-in) |
| `all-extras` | all of the above | Full local setup |

Into the **managed runtime** (default install):

```bash
"$HOME/Library/Application Support/SEAM/runtime/bin/python" -m pip install -e "/path/to/Seam[all-extras]"
```

Into the **dev venv**:

```bash
./.venv/bin/python -m pip install -e ".[all-extras]"
```

## PgVector with Docker Desktop

PgVector is optional. Keep credentials in a local env file outside git.

```bash
mkdir -p "$HOME/.config/seam"
cp .env.example "$HOME/.config/seam/.env"
# Edit ~/.config/seam/.env with your local password values — never commit this file.

docker compose --env-file "$HOME/.config/seam/.env" up -d seam-pgvector
set -a
. "$HOME/.config/seam/.env"
set +a
export SEAM_PGVECTOR_DSN="host=localhost port=55432 dbname=seam user=$POSTGRES_USER password=$POSTGRES_PASSWORD"
seam doctor
```

Image: `pgvector/pgvector:0.8.3-pg18-trixie` · Container: `seam-pgvector` · Port: `55432`

Stop when done:

```bash
docker compose --env-file "$HOME/.config/seam/.env" down
```

See [PGVECTOR_LOCAL.md](PGVECTOR_LOCAL.md) for more detail (command shapes are the same as Linux once translated from PowerShell).

## Web UI and REST API

Install the server extra, then serve the bundled dashboard on the same origin as the API:

```bash
python3 -m pip install -e ".[server]"   # or use a managed/runtime pip as above
seam serve --host 127.0.0.1 --port 8765
```

Open `http://127.0.0.1:8765/` in a browser, or:

```bash
seam webui
```

Provider keys for dashboard chat stay operator-owned. Set them in the Web UI Settings
panel or export them in your shell — never commit or ingest `.env` files.

Temporary OpenRouter session example:

```bash
export SEAM_CHAT_BASE_URL="https://openrouter.ai/api/v1"
export SEAM_CHAT_API_KEY="$OPENROUTER_API_KEY"
export SEAM_CHAT_MODEL="qwen/qwen3-coder"
seam dashboard
```

## MCP (Cursor, Claude Desktop, other MCP clients)

Stdio bridge:

```bash
seam mcp stdio
```

With auto-start pgvector when Docker is available:

```bash
seam-mcp --ensure-pgvector
```

Typical Claude Desktop / Cursor MCP config uses a command like:

```json
{
  "command": "/Users/<you>/.local/bin/seam-mcp",
  "args": [],
  "env": {
    "SEAM_DB_PATH": "/Users/<you>/Library/Application Support/SEAM/state/seam.db"
  }
}
```

Adjust paths if you use a custom `SEAM_DB_PATH` or a dev venv entrypoint
(`./.venv/bin/seam-mcp`).

## Fresh clone resume (developers)

After `sh ./installers/install_seam_macos.sh --dev` on a new machine:

```bash
git fetch origin
git status --branch --short
git rev-parse HEAD
git rev-parse origin/main
./.venv/bin/python -m tools.history.build_context_pack --latest 5 --token-budget 1800
```

Healthy state:

- `main...origin/main` with no ahead/behind drift
- `HEAD` matches `origin/main`
- Dev bootstrap printed doctor, integrity, routing, snapshot, continuity, and streams checks
- Latest context pack includes the newest `HISTORY.md` entry

Then read `PROJECT_STATUS.md`, `REPO_LEDGER.md`, `HISTORY_INDEX.md`, and `docs/CODE_LAYOUT.md`.

## Troubleshooting

### `command not found: seam`

```bash
source ~/.zprofile
which seam
```

Re-run the installer if `~/.local/bin/seam` is missing.

### `Python 3 is required to install SEAM`

Install Python 3.10+ and ensure `python3` is on PATH:

```bash
python3 --version
```

### `ModuleNotFoundError: No module named 'textual'`

```bash
./.venv/bin/python -m pip install -e ".[dash]"          # dev venv
# or
"$HOME/Library/Application Support/SEAM/runtime/bin/python" -m pip install -e "/path/to/Seam[dash]"
```

### `SEAM doctor: FAIL` (missing deps)

```bash
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python seam.py doctor
```

### PgVector unreachable

- Confirm Docker Desktop is running: `docker ps`
- Start the service: `docker compose --env-file "$HOME/.config/seam/.env" up -d seam-pgvector`
- Export `SEAM_PGVECTOR_DSN` in the same shell session before `seam doctor`

### Gatekeeper / quarantine on downloaded repo

If macOS blocks scripts from a browser download:

```bash
xattr -dr com.apple.quarantine /path/to/Seam
```

More symptoms: [errors.md](errors.md).

## Uninstall

```bash
rm -rf "$HOME/Library/Application Support/SEAM"
rm -f "$HOME/.local/bin/seam" "$HOME/.local/bin/seam-benchmark" "$HOME/.local/bin/seam-dash"
```

Remove the `# >>> SEAM installer >>>` block from `~/.zprofile`, `~/.bashrc`, and `~/.profile` manually.

Repo-local dev only:

```bash
rm -rf .venv
```