# SEAM Installers

This folder is the direct install surface for SEAM.

## Source Checkout Installation

For these GitHub CLI commands, authenticate with `gh auth login` if needed.
Review the attached license terms before using the software.

Replace `REPLACE_WITH_REVIEWED_COMMIT_SHA` in each clone/install block with
the full 40-character commit SHA you reviewed. Leaving the placeholder stops
before cloning. The installer runs only after checkout of the selected SHA.

Windows PowerShell:

```powershell
& {
    $ErrorActionPreference = "Stop"
    $seamRevision = "REPLACE_WITH_REVIEWED_COMMIT_SHA"
    if ($seamRevision -notmatch '^[0-9a-fA-F]{40}$') {
        throw "Select a reviewed full commit SHA before cloning or installing."
    }
    gh repo clone Canticle-AI-Research/Seam Seam
    if ($LASTEXITCODE -ne 0) { throw "Clone failed; stop before installation." }
    git -C Seam checkout --detach $seamRevision
    if ($LASTEXITCODE -ne 0) { throw "Reviewed revision checkout failed; stop before installation." }
    Set-Location -LiteralPath Seam -ErrorAction Stop
    powershell -ExecutionPolicy Bypass -File .\installers\install_seam_windows.ps1
    if ($LASTEXITCODE -ne 0) { throw "Installer failed; inspect its output." }
}
```

macOS:

```bash
seamRevision="REPLACE_WITH_REVIEWED_COMMIT_SHA"
[[ "$seamRevision" =~ ^[0-9a-fA-F]{40}$ ]] || { printf '%s\n' 'Select a reviewed full commit SHA before cloning or installing.' >&2; exit 1; }
gh repo clone Canticle-AI-Research/Seam Seam &&
    git -C Seam checkout --detach "$seamRevision" &&
    cd Seam && sh ./installers/install_seam_macos.sh
```

Linux / WSL2:

```bash
seamRevision="REPLACE_WITH_REVIEWED_COMMIT_SHA"
[[ "$seamRevision" =~ ^[0-9a-fA-F]{40}$ ]] || { printf '%s\n' 'Select a reviewed full commit SHA before cloning or installing.' >&2; exit 1; }
gh repo clone Canticle-AI-Research/Seam Seam &&
    git -C Seam checkout --detach "$seamRevision" &&
    cd Seam && sh ./installers/install_seam_linux.sh
```

macOS repo-local development:

```bash
seamRevision="REPLACE_WITH_REVIEWED_COMMIT_SHA"
[[ "$seamRevision" =~ ^[0-9a-fA-F]{40}$ ]] || { printf '%s\n' 'Select a reviewed full commit SHA before cloning or installing.' >&2; exit 1; }
gh repo clone Canticle-AI-Research/Seam Seam &&
    git -C Seam checkout --detach "$seamRevision" &&
    cd Seam && sh ./installers/install_seam_macos.sh --dev
```

Linux / WSL2 repo-local development:

```bash
seamRevision="REPLACE_WITH_REVIEWED_COMMIT_SHA"
[[ "$seamRevision" =~ ^[0-9a-fA-F]{40}$ ]] || { printf '%s\n' 'Select a reviewed full commit SHA before cloning or installing.' >&2; exit 1; }
gh repo clone Canticle-AI-Research/Seam Seam &&
    git -C Seam checkout --detach "$seamRevision" &&
    cd Seam && sh ./installers/install_seam_linux.sh --dev
```

macOS operator guide: [docs/MACOS.md](../docs/MACOS.md)

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

macOS development bootstrap:

```bash
sh ./installers/install_seam_macos.sh --dev
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

The generated shims use these paths when `SEAM_DB_PATH` is unset or empty,
and preserve a nonempty value. Re-run the reviewed platform installer in default
mode to regenerate older shims; upgrading Python packages alone does not update
them. This changes path selection and does not migrate a database.
Follow [database path selection](../docs/SEAM_OPERATOR_GUIDE.md#database-path-selection)
for explicit `--db` precedence and direct-entrypoint defaults.

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

Base install mirrors the bounded core dependencies in `pyproject.toml` through
`requirements.txt`: `rich` and `tiktoken`. The dependency-source contract is
checked by `python -m tools.ci.verify_dependency_contract`.

| Extra | Package installed | When you need it |
|---|---|---|
| `dash` | `textual>=8.0,<9.0`, `httpx>=0.24,<1.0` | Textual dashboard |
| `server` | `fastapi`, `uvicorn`, `python-multipart` | REST API |
| `pgvector` | `psycopg[binary]>=3.0` | PostgreSQL PgVector backend |
| `sbert` | `sentence-transformers>=2.0` | Local neural embeddings |
| `chroma` | `chromadb>=1.0,<2.0` | Explicit opt-in embedded Chroma only; excluded from `all-extras` |
| `agent` | none yet | Reserved MCP-style agent bridge wrapper extra |
| `rerank` | `sentence-transformers>=2.0` | Optional reranker experiments |
| `bench-judge` | `anthropic`, `openai` | Explicit external judge integrations; running paid validation still requires confirmation |
| `bench-mem0` | `mem0ai`, pre-1.0 `chromadb` | Matched Mem0 benchmark lane |
| `bench-zep` | `zep-cloud` | Matched Zep benchmark lane |
| `all-extras` | supported non-Chroma runtime and benchmark extras | Full local setup without the explicit-risk Chroma extra |

Install an extra into the managed runtime:

Windows:

```powershell
& "$env:LOCALAPPDATA\SEAM\runtime\Scripts\python.exe" -m pip install -e "C:\path\to\Seam[all-extras]"
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
Initialize that file only if it is absent. Keep an existing file and its values;
review required settings locally before starting the service. If initialization
fails, stop and inspect the path before continuing.

```bash
localEnv="$HOME/.config/seam/.env"
mkdir -p "$HOME/.config/seam" || exit 1
if [ -e "$localEnv" ] || [ -L "$localEnv" ]; then
    [ -f "$localEnv" ] && [ -r "$localEnv" ] || { printf '%s\n' 'Local env path must be a readable file; stop here.' >&2; exit 1; }
else
    [ -f .env.example ] && [ -r .env.example ] || { printf '%s\n' 'Missing or unreadable .env.example; stop here.' >&2; exit 1; }
    (umask 077; set -C; cat .env.example > "$localEnv") || { printf '%s\n' 'Initialization failed; inspect the local env path before continuing.' >&2; exit 1; }
fi
# End private env initialization. Edit the file locally; never commit it.
```

Continue with [Local Pgvector](../docs/PGVECTOR_LOCAL.md#point-seam-at-it)
to resolve the selected settings, quote the DSN, start the `pgvector` service,
and check it with `doctor`. Do not source the Compose env file as shell code
or write the resolved configuration or DSN into repository files.

## Public Release Installer Shape

These placeholders are not active installer commands:

```powershell
irm https://example.com/seam/install.ps1 | iex
```

```bash
curl -fsSL https://example.com/seam/install.sh | sh
```

Use them only after a public installer host exists.
