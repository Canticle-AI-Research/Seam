# SEAM on macOS

Operator guide for installing and running SEAM on macOS (Apple Silicon and Intel).
Commands use bash/zsh unless noted.

For day-to-day workflows after install, see [howto runbooks](howto/README.md).
For the full operator manual (commands, tests, failure triage on all platforms),
see [SEAM Operator Guide](SEAM_OPERATOR_GUIDE.md).
For failures by symptom, see [errors.md](errors.md).

## Prerequisites

- **macOS 12+** (Monterey or later recommended)
- **Python 3.11+** — check with `python3 --version`
  - If missing: install from [python.org](https://www.python.org/downloads/macos/) or `brew install python`
- **Git** and **GitHub CLI** (`gh`) for source checkout installs — `brew install gh` then `gh auth login`
- **Docker Desktop** (optional) — only if you want the Postgres + pgvector backend

## Install options

<a id="option-a--private-git-package"></a>
<a id="option-a-private-git-package"></a>

### Option A — Reviewed source package

Use a fresh virtual environment and a reviewed commit or release tag. Replace
`<reviewed-commit>` below with that exact revision. SSH access and source
visibility do not change the applicable [license terms](../LICENSE). This
installs from source; it is not a qualified PyPI release.

```bash
python3 -m pip install --upgrade pip
python3 -m pip install "seam-suite[server,dash] @ git+ssh://git@github.com/Canticle-AI-Research/Seam.git@<reviewed-commit>"
seam doctor
```

Add pgvector or local embeddings when needed:

```bash
python3 -m pip install "seam-suite[pgvector,sbert] @ git+ssh://git@github.com/Canticle-AI-Research/Seam.git@<reviewed-commit>"
```

<a id="option-b--private-repository-clone"></a>
<a id="option-b-private-repository-clone"></a>

### Option B — Source repository clone

Authenticate with `gh auth login` if access requires it. Replace
`REPLACE_WITH_REVIEWED_COMMIT_SHA` with the full 40-character SHA you reviewed.
Leaving the placeholder stops before cloning; the installer runs only after
checkout of the selected revision.

```bash
seamRevision="REPLACE_WITH_REVIEWED_COMMIT_SHA"
[[ "$seamRevision" =~ ^[0-9a-fA-F]{40}$ ]] || { printf '%s\n' 'Select a reviewed full commit SHA before cloning or installing.' >&2; exit 1; }
gh repo clone Canticle-AI-Research/Seam Seam &&
    git -C Seam checkout --detach "$seamRevision" &&
    cd Seam && sh ./installers/install_seam_macos.sh
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
- Preserves a nonempty `SEAM_DB_PATH` in each shim; unset or empty uses the managed database
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
| `~/.local/bin/seam` | Global command shim (supplies the default if `SEAM_DB_PATH` is unset or empty) |
| `~/.local/bin/seam-benchmark` | Benchmark shim |
| `~/.local/bin/seam-dash` | Textual dashboard shim |
| `repo/.venv/` | Repo-local dev venv (`--dev` mode only) |
| `~/.config/seam/.env` | Recommended location for local credentials (never commit) |

The installer-managed `seam`, `seam-benchmark`, and `seam-dash` shims preserve
a nonempty `SEAM_DB_PATH`. Unset or empty values use the managed state path above:

```bash
export SEAM_DB_PATH="$HOME/path/to/custom/seam.db"
seam memory search "persistent memory"
```

An explicit main CLI `--db` wins; put it before the subcommand:

```bash
seam --db "$HOME/path/to/custom/seam.db" memory search "persistent memory"
```

Direct console scripts in the managed runtime, and repo-local commands such as
`python seam.py`, use `SEAM_DB_PATH` or fall back to `seam.db` in their current
working directory when it is unset or empty. Use the same absolute database
path for CLI and MCP. Re-run the reviewed platform installer in default mode
to regenerate older shims; a Python-package upgrade alone leaves them unchanged.
No existing database is moved. See
[database path selection](SEAM_OPERATOR_GUIDE.md#database-path-selection),
including the limits of Doctor's `Default DB` field.

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
| `all-extras` | supported non-Chroma runtime and benchmark extras | Full local setup; Chroma remains a separate opt-in |

Into the **managed runtime** (default install):

```bash
"$HOME/Library/Application Support/SEAM/runtime/bin/python" -m pip install -e "/path/to/Seam[all-extras]"
```

Into the **dev venv**:

```bash
./.venv/bin/python -m pip install -e ".[all-extras]"
```

## PgVector with Docker Desktop

PgVector is optional. Docker Desktop must be running for the service start and
health check. Follow [Local Pgvector](PGVECTOR_LOCAL.md), including private env
initialization, the Bash configuration block, the selected Python environment,
and the health check. It preserves an existing env file and selected settings,
resolves Compose dotenv syntax without sourcing it, and quotes the DSN. The
service name is `pgvector`; `seam-pgvector` is the container name. The host port
defaults to `55432` and can be overridden. Native macOS qualification remains
separate from the runbook's Linux fixtures.

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

Provider keys for dashboard chat stay operator-owned. Export them in the launch
environment. The TUI can also read `~/.config/seam/seam.env` with mode 0600;
the server/WebUI does not load that file automatically. Do not enter
credentials in the prototype WebUI; never commit or ingest environment files.

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

For auto-start pgvector when Docker is available, launch the direct managed
MCP executable and select the default persistent database explicitly:

```bash
"$HOME/Library/Application Support/SEAM/runtime/bin/seam-mcp" \
    --db "$HOME/Library/Application Support/SEAM/state/seam.db" --ensure-pgvector
```

Typical Claude Desktop / Cursor MCP config uses a command like:

```json
{
  "command": "/Users/<you>/Library/Application Support/SEAM/runtime/bin/seam-mcp",
  "args": [],
  "env": {
    "SEAM_DB_PATH": "/Users/<you>/Library/Application Support/SEAM/state/seam.db"
  }
}
```

The installer does not create a global `~/.local/bin/seam-mcp` shim.
This config launches the direct console script, so its `SEAM_DB_PATH` default
is honored. Set that value to the same absolute database path used by your CLI,
or supply `["--db", "/absolute/path/to/chosen.db"]` in `args`.
For a repo-local dev install, use the full path to `repo/.venv/bin/seam-mcp`.
See [database path selection](SEAM_OPERATOR_GUIDE.md#database-path-selection).

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

Install Python 3.11+ and ensure `python3` is on PATH:

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
- Start the service: `docker compose --env-file "$HOME/.config/seam/.env" up -d pgvector`
- Export `SEAM_PGVECTOR_DSN` in the same shell session before `seam doctor`

### Gatekeeper / quarantine on downloaded repo

If macOS blocks scripts from a browser download:

```bash
xattr -dr com.apple.quarantine /path/to/Seam
```

More symptoms: [errors.md](errors.md).

## Uninstall

Stop SEAM and any agents writing to its database before uninstalling. For the
default managed installation, the removal targets are the runtime and its three
command shims. If you use a custom `SEAM_DB_PATH`, first confirm that the database
and any associated files are outside the removal targets below.

```bash
rm -rf "$HOME/Library/Application Support/SEAM/runtime"
rm -f "$HOME/.local/bin/seam" "$HOME/.local/bin/seam-benchmark" "$HOME/.local/bin/seam-dash"
```

These commands retain the default `state/` directory and its `seam.db` database.

Remove the `# >>> SEAM installer >>>` block from `~/.zprofile`, `~/.bashrc`, and `~/.profile` manually.

Repo-local dev only:

```bash
rm -rf .venv
```

### Intentional data deletion

Deleting persistent data is a separate destructive action. Identify the effective
`SEAM_DB_PATH` and any associated database files before deciding what to delete;
the default managed location is `~/Library/Application Support/SEAM/state/`.
Stop all writers, decide which data you intend to retain, and verify your
retention or backup procedure before deleting data. This guide does not provide
a verified backup or restore procedure. Data deletion requires an explicit
operator decision and is not part of the ordinary uninstall commands above.
