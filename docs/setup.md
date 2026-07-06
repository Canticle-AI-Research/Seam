# SEAM Setup Commands

Copy and paste the section for your environment.

## One-Line Private Repo Install

Requires `gh auth login` first.

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

macOS repo-local development:

```bash
gh repo clone BlackhatShiftey/Seam Seam && cd Seam && sh ./installers/install_seam_macos.sh --dev
```

Linux / WSL2 repo-local development:

```bash
gh repo clone BlackhatShiftey/Seam Seam && cd Seam && sh ./installers/install_seam_linux.sh --dev
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

```powershell
cd C:\Users\iwana\OneDrive\Documents\Codex
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e ".[dash]"
.\.venv\Scripts\python.exe -m pytest test_seam_all\test_seam.py tools\history\test_history_tools.py
.\.venv\Scripts\python.exe seam.py doctor
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
