# SEAM Troubleshooting (Documented Errors)

Use this as the first-stop error playbook. Every section includes exact fix and verify commands.

## Error Index

- [`ModuleNotFoundError: No module named 'textual'`](#error-modulenotfounderror-no-module-named-textual)
- [`SEAM doctor: FAIL` with missing required deps](#error-seam-doctor-fail-with-missing-required-deps)
- [`PgVector: configured but unreachable`](#error-pgvector-configured-but-unreachable)
- [Chroma path/index sync failure](#error-chroma-pathindex-sync-failure)
- [Benchmark bundle verification failure](#error-benchmark-bundle-verification-failure)
- [`HTTP 429` provider quota or rate limit](#error-http-429-provider-quota-or-rate-limit)

## Error: `ModuleNotFoundError: No module named 'textual'`

### Symptom

Running `seam-dash` or Textual tests fails with missing `textual`.

### Fix (Windows)

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dash]"
```

### Fix (macOS / Linux / WSL2)

```bash
./.venv/bin/python -m pip install -e ".[dash]"
```

Managed macOS runtime:

```bash
"$HOME/Library/Application Support/SEAM/runtime/bin/python" -m pip install -e "/path/to/Seam[dash]"
```

### Verify

Windows:

```powershell
.\.venv\Scripts\python.exe -m pip show textual
.\.venv\Scripts\python.exe -m pytest test_seam_all/test_seam.py::SeamTests::test_textual_dashboard_mounts_core_panels -q
```

macOS / Linux / WSL2:

```bash
./.venv/bin/python -m pip show textual
./.venv/bin/python -m pytest test_seam_all/test_seam.py::SeamTests::test_textual_dashboard_mounts_core_panels -q
```

## Error: `SEAM doctor: FAIL` with missing required deps

### Symptom

`seam doctor` shows missing `rich`, `chromadb`, or `tiktoken`.

### Fix (Windows)

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\seam.exe doctor
```

### Fix (macOS / Linux / WSL2)

```bash
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/seam doctor
```

### Verify

Look for:

- `SEAM doctor: PASS`
- `Required deps: OK`

macOS-specific install help: [MACOS.md](MACOS.md)

## Error: `PgVector: configured but unreachable`

### Symptom

`seam doctor` shows PgVector is configured but not reachable.

SEAM's documented operating port for the local pgvector container is `55432`
(set via `SEAM_PGVECTOR_PORT=55432` in your local env file). The default
`docker-compose.yaml` mapping is `${SEAM_PGVECTOR_PORT:-5432}:5432`, so the host
port follows your env var. Use the host port (typically `55432`) in
`SEAM_PGVECTOR_DSN`.

### Fix (Windows)

```powershell
$localEnv = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "SEAM\local\.env"
New-Item -ItemType Directory -Force -Path (Split-Path $localEnv)
Copy-Item .env.example $localEnv
# Edit $localEnv locally first; do not commit it. Set SEAM_PGVECTOR_PORT=55432.
docker compose --env-file $localEnv up -d seam-pgvector
Get-Content $localEnv | Where-Object { $_ -and $_ -notmatch '^\s*#' } | ForEach-Object {
    $name, $value = $_ -split '=', 2
    Set-Item -Path "Env:$name" -Value $value
}
$env:SEAM_PGVECTOR_DSN="host=localhost port=55432 dbname=seam user=$env:POSTGRES_USER password=$env:POSTGRES_PASSWORD"
.\.venv\Scripts\seam.exe doctor
```

### Fix (Linux / WSL2)

```bash
mkdir -p "$HOME/.config/seam"
cp .env.example "$HOME/.config/seam/.env"
# Edit the env file locally; do not commit it. Set SEAM_PGVECTOR_PORT=55432.
docker compose --env-file "$HOME/.config/seam/.env" up -d seam-pgvector
set -a
. "$HOME/.config/seam/.env"
set +a
export SEAM_PGVECTOR_DSN="host=localhost port=55432 dbname=seam user=$POSTGRES_USER password=$POSTGRES_PASSWORD"
seam doctor
```

### Verify

Look for: `PgVector: reachable`.

## Error: Chroma path/index sync failure

### Symptom

`seam index --vector-backend chroma` fails due to path or permissions.

### Fix (Windows)

```powershell
New-Item -ItemType Directory -Force .seam_chroma | Out-Null
.\.venv\Scripts\seam.exe index --vector-backend chroma --vector-path .seam_chroma
```

### Fix (Linux / WSL2)

```bash
mkdir -p .seam_chroma
./.venv/bin/seam index --vector-backend chroma --vector-path .seam_chroma
```

### Verify

The index command completes without an error and reports synced ids.

## Error: Benchmark bundle verification failure

### Symptom

`seam benchmark verify <bundle>` reports hash mismatch or failed validation.

### Fix

Re-run benchmark and produce a new verified bundle from current environment:

```powershell
.\.venv\Scripts\seam.exe benchmark run all --persist --output seam-benchmark-report.json
.\.venv\Scripts\seam.exe benchmark verify seam-benchmark-report.json
```

### Verify

Benchmark verification output indicates `PASS`.

## Error: `HTTP 429` provider quota or rate limit

### Symptom

Provider-backed commands, dashboard chat, embeddings, or judged benchmark runs
fail with `HTTP 429`, rate-limit, quota, or billing errors.

### Fix

Set or rotate the provider API key in one of two operator-owned places:

- Web UI: run `seam webui`, open Settings, set the provider key or
  `SEAM_CHAT_API_KEY`, and save the local env.
- Manual: export the needed key in the current shell or edit an ignored local
  `.env`/`.conf` file. Never commit or ingest those files.

If the key is valid, check provider quota, billing, model access, and request
rate. Paid benchmark dependencies such as `bench-judge`, `bench-mem0`, and
`bench-zep` should only run after explicit operator approval.

### Verify

Re-run the failed command after the operator confirms provider access. For chat
or API setup, run:

```bash
seam doctor
seam webui --host 127.0.0.1 --port 8765
```

## Do-Not-Proceed Blockers

Stop and resolve before continuing:

- `SEAM doctor: FAIL`
- Lossless roundtrip failures
- Benchmark verification hash mismatch for published claims
- PgVector configured but unreachable when pgvector is the selected backend
