# SQLite migration and recovery contract

SEAM opens its canonical SQLite store through one central migration spine in
`seam_runtime.migrations`. Durable component DDL remains next to the component
that owns it, but an existing database may only change through a registered,
ordered spine step.

## Current versions

- Central schema: `2`
- Step 1: `initialize-versioned-core`
- Step 2: `register-durable-projections`

`seam_schema_migrations` records the contiguous step history and a stable
identity checksum. `seam_projection_versions` records the expected versions of
canonical MIRL, core storage, the knowledge graph and node vectors, graph
products, lifecycle, workspace, reasoning graph/retrieval/verification/
patterns/promotion, and the SQLite vector projection.

Ordinary reopen validates both registries and the projection-owned tables. It
does not rerun idempotent DDL against a current database.

## Upgrade behavior

Before a writable connection is opened, SEAM inspects the database read-only.
It refuses an unknown schema, an unknown migration identity, a newer central
version, a changed projection registry, or an unsupported knowledge-graph
marker. Refusal occurs before backup creation, WAL selection, DDL, cleanup, or
projection work, so the database file remains byte-unchanged.

Supported file-backed upgrades create a private SQLite backup under
`<database>.seam-backups/` before the first migration step. Each step runs in its own
`BEGIN IMMEDIATE` transaction. Before commit, SEAM runs both
`PRAGMA integrity_check` and `PRAGMA foreign_key_check`; an injected or real
failure rolls back the active step. Backups are retained deliberately and are
never deleted automatically.

The maintained historical fixtures are documented under
`tests/fixtures/sqlite_history/`. A pre-graph store can build its first graph
from canonical MIRL inside the explicit migration transaction because it has no
graph-only state to lose. A stale existing graph projection such as
`knowledge-graph/4` remains refused: non-destructive reprojection and temporal
equivalence are Track S S3, not an implicit S2 open-time behavior.

## Recovery

Close every runtime and SQLite handle first, then restore the exact backup:

```python
from seam_runtime.migrations import restore_database_backup

restore_database_backup("seam.db", "seam.db.seam-backups/seam.pre-migration-v0-<id>.sqlite3")
```

Recovery validates the backup's SQLite integrity and foreign keys, copies it to
a same-directory temporary file, fsyncs it, removes only the target database's
stale SQLite sidecars, and atomically replaces the target. Reopening SEAM then
runs the supported upgrade again from the recovered version.

## Qualification

`tests/audit/test_sqlite_migration_spine.py` proves:

- empty and every maintained historical fixture upgrade;
- injected failure after every registered step rolls that step back;
- integrity and foreign-key checks run after every step and supported path;
- unknown/newer central and projection versions are refused byte-unchanged;
- a pre-migration backup restores deleted canonical truth and re-upgrades.
