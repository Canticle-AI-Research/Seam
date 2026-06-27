# SEAM Installers

This folder is the direct install surface for SEAM.

## One-Line Private Repo Install

Run `gh auth login` first for private repo access.

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

Linux / WSL2 repo-local development:

```bash
gh repo clone BlackhatShiftey/Seam Seam && cd Seam && sh ./installers/install_seam_linux.sh --dev
```

Open a new terminal after install:

```text
seam doctor
seam --help
seam dashboard --snapshot --no-clear
```

## Platform Entrypoints

From an existing checkout:

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\installers\install_seam_windows.ps1
```

macOS:

```bash
sh ./installers/install_seam_macos.sh
```

Linux / WSL2:

```bash
sh ./installers/install_seam_linux.sh
```

Linux / WSL2 development bootstrap:

```bash
sh ./installers/install_seam_linux.sh --dev
```

If Debian/Ubuntu is missing Python `venv`:

```bash
sudo apt-get update
sudo apt-get install -y python3-venv
```

## What The Installer Does

Default mode:

- creates a dedicated SEAM runtime under the user home directory
- installs SEAM into that runtime with `[dash]`
- creates global `seam`, `seam-benchmark`, and `seam-dash` shims
- configures a persistent default database
- updates PATH or shell profile state
- runs `seam doctor`

Linux `--dev` mode:

- creates or reuses the repo-local `.venv`
- pre-creates `.venv/lib64` on POSIX filesystems so external drives that reject
  the `venv` `lib64` symlink still work
- installs `requirements.txt`, `.[all-extras]`, and `pytest`
- runs `seam.py doctor`, history integrity, routing, snapshot, continuity, and
  stream verification checks
- does not install Node dependencies or build the `webui/` dev project (the
  runtime serves the dashboard directly; no build step is required)

Default persistent database paths:

- Windows: `%LOCALAPPDATA%\SEAM\state\seam.db`
- macOS: `~/Library/Application Support/SEAM/state/seam.db`
- Linux / WSL2: `~/.local/share/seam/state/seam.db`

## First Memory Check

```text
seam ingest README.md --persist
seam memory search "persistent memory"
seam retrieve "persistent memory" --mode mix --budget 5
seam dashboard
```

Use `reload` inside the dashboard to refresh runtime panels, metrics, and chart
state without restarting.

## Optional Extras

Base install includes required runtime packages from `requirements.txt`,
including `rich`, `chromadb`, and `tiktoken`.

| Extra | Package installed | When you need it |
|---|---|---|
| `dash` | `textual>=0.50` | Textual dashboard |
| `server` | `fastapi`, `uvicorn` | REST API |
| `pgvector` | `psycopg[binary]>=3.0` | PostgreSQL PgVector backend |
| `sbert` | `sentence-transformers>=2.0` | Local neural embeddings |
| `agent` | none yet | Reserved MCP-style agent bridge wrapper extra |
| `rerank` | `sentence-transformers>=2.0` | Optional reranker experiments |
| `all-extras` | all of the above | Full local setup |

Install an extra into the managed runtime:

Windows:

```powershell
%LOCALAPPDATA%\SEAM\runtime\Scripts\python.exe -m pip install -e "C:\path\to\Seam[all-extras]"
```

Linux / WSL2:

```bash
~/.local/share/seam/runtime/bin/python -m pip install -e "/path/to/Seam[all-extras]"
```

macOS:

```bash
"$HOME/Library/Application Support/SEAM/runtime/bin/python" -m pip install -e "/path/to/Seam[all-extras]"
```

## PgVector

PgVector is optional. Keep credentials in a local env file outside git.

```bash
mkdir -p "$HOME/.config/seam"
cp .env.example "$HOME/.config/seam/.env"
docker compose --env-file "$HOME/.config/seam/.env" up -d seam-pgvector
set -a
. "$HOME/.config/seam/.env"
set +a
seam doctor
```

Set `SEAM_PGVECTOR_DSN` in your local shell/profile from those local env values
before running SEAM with PgVector. Do not write the DSN into repo files.

## Public Release Installer Shape

These are not active private-repo commands yet:

```powershell
irm https://example.com/seam/install.ps1 | iex
```

```bash
curl -fsSL https://example.com/seam/install.sh | sh
```

Use them only after a public installer host exists.
