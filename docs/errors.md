# SEAM Troubleshooting (Documented Errors)

Use this as the first-stop error playbook. Each section explains the symptom,
corrective steps and verification boundaries.

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

`seam doctor` reports a missing required dependency: `rich` or `tiktoken`.
Chroma is optional; diagnose a missing Chroma adapter separately if you
intentionally selected it.

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

The current `docker-compose.yaml` mapping is
`127.0.0.1:${SEAM_PGVECTOR_PORT:-55432}:5432`. It binds to loopback and defaults
to host port `55432`; `SEAM_PGVECTOR_PORT` can override that host port. Use the
selected host port in `SEAM_PGVECTOR_DSN`.

Initialize the local env file only if it is absent. Preserve an existing file
and its values; review settings locally before starting the service. If
initialization fails, stop and inspect the path before continuing.

### Fix (Windows)

```powershell
$localEnv = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "SEAM\local\.env"
try {
    New-Item -ItemType Directory -Force -Path (Split-Path $localEnv) -ErrorAction Stop | Out-Null
    if (Test-Path -LiteralPath $localEnv) {
        if (-not (Test-Path -LiteralPath $localEnv -PathType Leaf)) {
            throw "Local env path must be a file."
        }
    } else {
        $template = (Resolve-Path -LiteralPath .env.example -ErrorAction Stop).Path
        [System.IO.File]::Copy($template, $localEnv, $false)
    }
} catch {
    throw "Initialization failed; inspect the local env path before continuing."
}
# Edit $localEnv locally first; do not commit it. Set SEAM_PGVECTOR_PORT=55432.
docker compose --env-file $localEnv up -d pgvector
Get-Content $localEnv | Where-Object { $_ -and $_ -notmatch '^\s*#' } | ForEach-Object {
    $name, $value = $_ -split '=', 2
    Set-Item -Path "Env:$name" -Value $value
}
$env:SEAM_PGVECTOR_DSN="host=localhost port=55432 dbname=seam user=$env:POSTGRES_USER password=$env:POSTGRES_PASSWORD"
.\.venv\Scripts\seam.exe doctor
```

### Fix (Linux / WSL2)

```bash
localEnv="$HOME/.config/seam/.env"
mkdir -p "$HOME/.config/seam" || exit 1
if [ -e "$localEnv" ] || [ -L "$localEnv" ]; then
    [ -f "$localEnv" ] && [ -r "$localEnv" ] || { printf '%s\n' 'Local env path must be a readable file; stop here.' >&2; exit 1; }
else
    [ -f .env.example ] && [ -r .env.example ] || { printf '%s\n' 'Missing or unreadable .env.example; stop here.' >&2; exit 1; }
    (umask 077; set -C; cat .env.example > "$localEnv") || { printf '%s\n' 'Initialization failed; inspect the local env path before continuing.' >&2; exit 1; }
fi
# Edit the env file locally; do not commit it. Set SEAM_PGVECTOR_PORT=55432.
docker compose --env-file "$localEnv" up -d pgvector
set -a
. "$localEnv"
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

Preserve the failing bundle. Record its original path, SHA-256, provenance and
verification report, then diagnose the reported bundle or case hash failure
before using that run for a claim. Do not overwrite it or recompute its stored
hashes to turn the failure into a pass.

If a separate rerun is authorized, write it to a unique output path and retain
the original. A new bundle is a separate run; its result does not repair or
validate the failing original.

Use `seam benchmark verify <bundle>` for ordinary suite bundles and
`seam bench verify <bundle>` for sealed BIL bundles. They have different formats
and verification checks.

### Verify

For the exact file being checked, retain its identity and the individual
verification results. `seam benchmark verify` checks bundle and case hashes;
`PASS` does not establish scientific correctness or validate a different file.
Published claims tied to the failing original remain blocked until their
evidence is resolved.

## Error: `HTTP 429` provider quota or rate limit

### Symptom

Provider-backed commands, dashboard chat, embeddings, or judged benchmark runs
fail with `HTTP 429`, rate-limit, quota, or billing errors.

### Fix

Set or rotate the provider API key in an operator-owned location: export it in
the launch environment. The TUI can also read
`~/.config/seam/seam.env` with mode 0600; the server/WebUI does not load that
file automatically. Do not enter credentials in the prototype WebUI. Never
commit or ingest environment files.

If the operator intentionally keeps shell-safe assignments in that file,
source it explicitly before starting a server command:

```bash
set -a
. ~/.config/seam/seam.env
set +a
seam webui --host 127.0.0.1 --port 8765
```

If the key is valid, check provider quota, billing, model access, and request
rate. Paid benchmark dependencies such as `bench-judge`, `bench-mem0`, and
`bench-zep` should only run after explicit operator approval.

### Verify

After the operator confirms provider access, run `seam doctor`, then repeat the
command that originally failed.

## Do-Not-Proceed Blockers

Stop and resolve before continuing:

- `SEAM doctor: FAIL`
- Lossless roundtrip failures
- Benchmark verification hash mismatch for published claims
- PgVector configured but unreachable when pgvector is the selected backend
