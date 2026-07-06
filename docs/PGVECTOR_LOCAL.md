# Local Pgvector

Use this when you want a real Postgres + pgvector database behind SEAM without
waiting on Cloud SQL or another hosted Postgres service.

## Start the database

SEAM ships a Docker Compose service. Use the private env file that holds your
credentials (never committed to git):

```powershell
docker compose --env-file <path-to-private-env> up -d seam-pgvector
```

Current image: `pgvector/pgvector:0.8.3-pg18-trixie`
Container name: `seam-pgvector`
Port: `55432` (mapped from container's 5432)

If you want to start an existing stopped container directly:

```powershell
docker start seam-pgvector
```

## Point SEAM at it

Set the DSN in your shell session (credentials stay outside the repo):

```powershell
$env:SEAM_PGVECTOR_DSN="host=localhost port=55432 dbname=seam user=$env:POSTGRES_USER password=$env:POSTGRES_PASSWORD"
python seam.py doctor
```

`doctor` runs a lightweight install-health check and smoke test, including the
pgvector connection path.

## Use it for runtime commands

```powershell
python seam.py --db seam_live.db compile-nl "We need durable memory."
python seam.py --db seam_live.db index
python seam.py --db seam_live.db search "translator natural language" --budget 3
python seam.py --db seam_live.db stats
```

## Database locations

- **SQLite truth store** - the `--db` file you pass (`seam_live.db`, etc.)
- **pgvector store** - the separate Postgres container `seam-pgvector` on `localhost:55432`
- SQLite and pgvector are separate processes; pgvector is not stored inside the SQLite file

## Stop and remove the container

```powershell
docker stop seam-pgvector
docker rm seam-pgvector
```

## Troubleshooting

- `doctor` says pgvector DSN missing: set `SEAM_PGVECTOR_DSN` in the same shell session
- `doctor` says connection refused: run `docker ps` and check `seam-pgvector` is listed
- Port conflict on 55432: run `docker ps -a` to find a stopped container on that port
