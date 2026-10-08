# SEAM Setup Commands

Copy and paste the section for your environment.

<a id="one-line-private-repo-install"></a>

## Source Checkout Install

Use a reviewed commit or release tag and the existing license terms. Authenticate
with `gh auth login` if access requires it. The Windows block stops on clone or
installer failure; run it as one block. Replace
`REPLACE_WITH_REVIEWED_COMMIT_SHA` with the full 40-character SHA you reviewed
before running any clone/install block. Leaving it unchanged stops before cloning.

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

Full macOS guide: [docs/MACOS.md](MACOS.md)

Verify in a new terminal:

```text
seam doctor
seam --help
seam dashboard --snapshot --no-clear
```

## Repo-Local Development Install

Windows PowerShell:

Open PowerShell in the reviewed SEAM checkout root containing `seam.py`,
`pyproject.toml`, and `requirements.txt`. If needed, use
`Set-Location -LiteralPath 'C:\path\to\Seam'`, replacing the placeholder with
your actual checkout path. Use Python 3.11 or newer.

```powershell
& {
    $ErrorActionPreference = "Stop"
    if (-not (Test-Path -LiteralPath .\seam.py -PathType Leaf) -or
        -not (Test-Path -LiteralPath .\pyproject.toml -PathType Leaf) -or
        -not (Test-Path -LiteralPath .\requirements.txt -PathType Leaf)) {
        throw "Run this block from the reviewed SEAM checkout root."
    }
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed; stop before dependency installation." }
    .\.venv\Scripts\python.exe -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed; stop before dependency installation." }
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "Requirements installation failed; stop before editable installation." }
    .\.venv\Scripts\python.exe -m pip install -e ".[dash]"
    if ($LASTEXITCODE -ne 0) { throw "Editable installation failed; stop before testing." }
    .\.venv\Scripts\python.exe -m pytest test_seam_all\test_seam.py tools\history\test_history_tools.py
    if ($LASTEXITCODE -ne 0) { throw "Scoped regression tests failed; stop before Doctor." }
    .\.venv\Scripts\python.exe seam.py doctor
    if ($LASTEXITCODE -ne 0) { throw "Doctor failed; inspect its output." }
}
```

macOS bash:

```bash
cd /path/to/Seam
sh ./installers/install_seam_macos.sh --dev
```

Linux / WSL2 bash:

```bash
cd /path/to/Seam
sh ./installers/install_seam_linux.sh --dev
```

The Linux development bootstrap installs Python dependencies only. It does not
install Node dependencies or build the `webui/` dev project; the runtime serves
the dashboard (`seam serve` / `seam webui`) directly with no build step.

If Debian/Ubuntu says `venv` is missing:

```bash
sudo apt-get update
sudo apt-get install -y python3-venv
```

## Resume Current Repo State On Fresh Linux

After cloning and running the Linux repo-local development install above, use
these extra Git state checks before making changes:

```bash
git fetch origin
git status --branch --short
git rev-parse HEAD
git rev-parse origin/main
./.venv/bin/python -m tools.history.build_context_pack --latest 5 --token-budget 1800
```

Healthy resume state:

- `main...origin/main` has no ahead/behind marker.
- `HEAD` and `origin/main` print the same SHA.
- The development bootstrap reports `doctor`, integrity, routing, snapshot,
  continuity, and stream checks as run.
- `write_snapshot` creates a local `.seam/snapshots/` handoff for the latest
  tracked history entries. Snapshot JSON files are intentionally ignored, so
  this step is required on a fresh clone.
- The latest context pack includes the newest `HISTORY.md` entry.

Then read:

1. `PROJECT_STATUS.md`
2. `REPO_LEDGER.md`
3. `HISTORY_INDEX.md`
4. `docs/CODE_LAYOUT.md`
5. `docs/DATA_ROUTING.md` for history, routing, audit, or context-budget work

## First Memory Flow

```powershell
seam ingest README.md --persist
seam memory search "persistent memory"
seam retrieve "persistent memory" --mode mix --budget 5
seam context "persistent memory" --retrieval-mode mix --view prompt
```

## Optional Extras

```powershell
python -m pip install -e ".[server]"
python -m pip install -e ".[pgvector]"
python -m pip install -e ".[sbert]"
python -m pip install -e ".[agent]"
python -m pip install -e ".[rerank]"
python -m pip install -e ".[all-extras]"
```

## Dashboard Chat Models With OpenRouter

Do not write raw API keys into this repo.

Windows temporary session:

```powershell
$env:SEAM_CHAT_BASE_URL = "https://openrouter.ai/api/v1"
$env:SEAM_CHAT_API_KEY = $env:OPENROUTER_API_KEY
$env:SEAM_CHAT_MODEL = "qwen/qwen3-coder"
seam dashboard
```

macOS / Linux / WSL2 temporary session:

```bash
export SEAM_CHAT_BASE_URL="https://openrouter.ai/api/v1"
export SEAM_CHAT_API_KEY="$OPENROUTER_API_KEY"
export SEAM_CHAT_MODEL="qwen/qwen3-coder"
seam dashboard
```

Switch models inside the dashboard:

```text
?models
?model qwen/qwen3-coder
?model deepseek/deepseek-v4-pro
?model x-ai/grok-code-fast-1
?model google/gemma-4-31b-it
```

Refresh dashboard state without restarting:

```text
reload
/reload
refresh
```

## Expected Healthy Output

- `SEAM doctor: PASS`
- `Compile smoke: PASS`
- `Required deps: OK`
- `seam dashboard --snapshot --no-clear` renders the console frame
- `seam memory search ...` returns compact record IDs
