# Local Pgvector

Use the optional local Postgres + pgvector backend from a reviewed SEAM source
checkout. SQLite remains the canonical truth store; pgvector is a separate,
rebuildable index. Docker Compose must support `config --format json` and the
selected SEAM Python environment must include the `pgvector` extra. These are
operator commands; configuration checks below do not prove retrieval quality.

## Prepare the private env file

Initialize a missing file with the no-clobber procedure in
[troubleshooting](errors.md#error-pgvector-configured-but-unreachable) or
[installers](../installers/README.md#pgvector). Preserve existing bytes and
values, then edit locally. The examples use `~/.config/seam/.env` on POSIX and
the Documents/SEAM/local/.env path on Windows. Never commit or ingest that file.

The tracked `docker-compose.yaml` defines service `pgvector`, container
`seam-pgvector`, image `pgvector/pgvector:0.8.6-pg18-trixie`, and the mapping
`127.0.0.1:${SEAM_PGVECTOR_PORT:-55432}:5432`. The host port defaults to `55432`;
database and user default to `seam`; password is required. Keep custom settings.
Changing these variables does not migrate an existing Postgres data volume or
change roles/passwords already initialized in it.

## Point SEAM at it

Run from the checkout with a Python environment that contains SEAM. The blocks
show the repo-local `.venv`. For a managed install, replace `seamPython` with
its Python path: Linux `~/.local/share/seam/runtime/bin/python`, macOS
`~/Library/Application Support/SEAM/runtime/bin/python`, or Windows
`%LOCALAPPDATA%\SEAM\runtime\Scripts\python.exe`. Install the `pgvector`
extra into that same environment if absent, using the
[extra installation instructions](../installers/README.md#optional-extras).

Compose resolves dotenv syntax, interpolation and current-shell overrides. The
blocks derive the DSN from that resolved service model, so they do not hardcode
the database, user or chosen host port. Bash uses the runtime's existing pure
`build_pgvector_dsn` helper; PowerShell applies the same libpq quoting rules
with string replacement. Neither calls the `ensure_pgvector` bootstrap.
Keep the shell settings unchanged between
resolution and service start. Do not echo the DSN, enable command tracing, save
the JSON, or paste either into logs: they contain credentials.

Interpolated `config` output doubles literal dollar signs so it can be reused
as Compose input. The blocks undo that rendering escape before building the
DSN. This behavior was verified against Compose `v5.5.1` and its
[versioned config renderer](https://github.com/docker/compose/blob/v5.5.1/cmd/compose/config.go#L191-L193).
An alternate Compose implementation/version needs the same behavior check.

Linux / WSL2 / macOS, in Bash:

```bash
localEnv="$HOME/.config/seam/.env"
seamPython="./.venv/bin/python"
seamDsn="$(
    set -o pipefail
    docker compose --env-file "$localEnv" config --format json |
    "$seamPython" -c '
import json, sys
from seam_runtime.pgvector_bootstrap import build_pgvector_dsn
service = json.loads(sys.stdin.read().replace("$$", "$"))["services"]["pgvector"]
values = dict(service["environment"])
ports = [p for p in service["ports"] if int(p["target"]) == 5432]
if len(ports) != 1 or ports[0].get("host_ip") != "127.0.0.1":
    raise SystemExit("Expected one loopback pgvector port; inspect configuration locally.")
port = str(ports[0]["published"])
if not port.isdecimal() or not 1 <= int(port) <= 65535:
    raise SystemExit("Choose a single explicit host port between 1 and 65535.")
values["SEAM_PGVECTOR_PORT"] = port
print(build_pgvector_dsn(values))
'
)" || { printf '%s\n' 'Configuration resolution failed; stop here.' >&2; exit 1; }
export SEAM_PGVECTOR_DSN="$seamDsn"
unset seamDsn
docker compose --env-file "$localEnv" up -d pgvector || exit 1
"$seamPython" seam.py doctor || exit 1
```

Windows PowerShell (run as one block):

```powershell
& {
    $ErrorActionPreference = "Stop"
    $localEnv = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "SEAM\local\.env"
    $seamPython = ".\.venv\Scripts\python.exe"
    $resolvedJson = docker compose --env-file $localEnv config --format json
    if ($LASTEXITCODE -ne 0) { throw "Configuration resolution failed; stop here." }
    $resolvedJson = ($resolvedJson -join [Environment]::NewLine).Replace('$$', '$')
    $service = ($resolvedJson | ConvertFrom-Json -ErrorAction Stop).services.pgvector
    $ports = @($service.ports | Where-Object { $_.target -eq 5432 })
    if ($ports.Count -ne 1 -or $ports[0].host_ip -ne "127.0.0.1") {
        throw "Expected one loopback pgvector port; inspect configuration locally."
    }
    $pgPort = 0
    if (-not [int]::TryParse([string]$ports[0].published, [ref]$pgPort) -or $pgPort -lt 1 -or $pgPort -gt 65535) {
        throw "Choose a single explicit host port between 1 and 65535."
    }
    function ConvertTo-SeamConninfoValue([string]$value) {
        "'" + $value.Replace('\', '\\').Replace("'", "\'") + "'"
    }
    $pgEnv = $service.environment
    if (-not $pgEnv.POSTGRES_PASSWORD) { throw "A database password is required." }
    $env:SEAM_PGVECTOR_DSN = "host=localhost port=$(ConvertTo-SeamConninfoValue ([string]$pgPort)) dbname=$(ConvertTo-SeamConninfoValue $pgEnv.POSTGRES_DB) user=$(ConvertTo-SeamConninfoValue $pgEnv.POSTGRES_USER) password=$(ConvertTo-SeamConninfoValue $pgEnv.POSTGRES_PASSWORD)"
    Remove-Variable resolvedJson, service, ports, pgEnv, pgPort
    docker compose --env-file $localEnv up -d pgvector
    if ($LASTEXITCODE -ne 0) { throw "Service start failed; inspect Docker locally." }
    & $seamPython seam.py doctor
    if ($LASTEXITCODE -ne 0) { throw "Doctor command failed; inspect its execution error locally." }
}
```

Require the explicit `PgVector: reachable` line in the Doctor report before
continuing. A nonzero Doctor exit catches command execution failure; a zero
exit does not prove reachability. In this source revision, Doctor can print
`configured but unreachable` and still exit zero.

`docker compose ... up -d` starts containers in the background and does not
wait for a healthy service. If the first Doctor check is unreachable, check
Docker and startup health/timing first with the service's `ps` status and
local logs, then rerun Doctor after startup completes. Inspect logs locally;
do not paste credentials. Only then investigate the selected port, roles or
existing-volume credentials. Changing the env file does not change initialized
roles/passwords. Do not delete the data volume as a generic repair.

Compose parsing and the command exit checks alone do not qualify a live
service or retrieval quality. The Bash preparation/DSN commands have disposable
Linux fixture coverage; native macOS and Windows PowerShell qualification
remain separate. No platform or live-service qualification is inferred.

## Use it for runtime commands

From the same configured shell, after successful health checks:

```text
seam --db seam_live.db compile-nl "We need durable memory."
seam --db seam_live.db index
seam --db seam_live.db search "translator natural language" --budget 3
```

Standalone `seam ... stats` is not implemented in this source revision,
although the parser registers the name. Interactive `/stats` is a separate
command; these examples do not substitute it for a standalone CLI action.

Use the selected environment's SEAM executable if the global shim selects a
different environment. The `--db` path is SQLite; the pgvector connection uses
the selected localhost port and separate Docker volume.

## Stop the service

From the same checkout and with the same private env path:

```bash
docker compose --env-file "$localEnv" stop pgvector
```

Compose takes the service name `pgvector`. Direct container commands, such as
`docker start seam-pgvector`, take the container name. They are distinct names.

## Troubleshooting and source contracts

- A missing DSN: configure the same shell that launches SEAM.
- Connection refused: check Docker, the `pgvector` service and the selected port.
- Authentication failure after changing env values: inspect existing database
  roles and volume history; changing the file does not update initialized data.
- [Troubleshooting](errors.md#error-pgvector-configured-but-unreachable)
- [Compose configuration resolution](https://docs.docker.com/reference/cli/docker/compose/config/)
- [libpq connection-string quoting](https://www.postgresql.org/docs/current/libpq-connect.html#LIBPQ-CONNSTRING)
