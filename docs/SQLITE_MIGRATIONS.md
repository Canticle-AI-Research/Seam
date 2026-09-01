# SQLite migration and recovery contract

SEAM opens its canonical SQLite store through one central migration spine in
`seam_runtime.migrations`. Durable component DDL remains next to the component
that owns it, but an existing database may only change through a registered,
ordered spine step.

## Current versions

- Central schema: `2`
- Step 1: `initialize-versioned-core`
- Step 2: `register-durable-projections`

Registered Track S S4 projection transitions are:

- `core-storage/1` -> `core-storage/2` (`typed-ir-edge-endpoints`), which
  rebuilds derived `ir_edges` with independently typed source and destination
  endpoints plus normalized canonical contributor ownership in
  `ir_edge_sources`;
- `knowledge-graph/5` -> `knowledge-graph/6`
  (`typed-knowledge-references`), which reprojects canonical MIRL through the
  closed reference contract and removes disconnected colon-heuristic nodes and
  their orphan vectors.

Both S4 rebuilds read canonical `ir_records` in deterministic 500-row batches
inside the migration owner's transaction. Reference-kind lookups and edge
writes are bounded to each batch; no transition materializes the entire
canonical corpus or all projected edges in memory. Rebuilt edge types are
checked in deterministic 300-triple queries using at most 900 SQLite variables,
not one query per edge. Invalid or mismatched canonical rows roll the step back
and report only a SHA-256 digest of the record identifier. The final
core-storage gate verifies endpoint columns, contributor primary/foreign keys,
that every projected triple has at least one canonical owner, that every
contributor still names both a canonical source record and a derived edge, and
that every canonical payload's required references and reserved virtual-
reference declaration remain closed.

`seam_schema_migrations` records the contiguous step history and a stable
identity checksum. `seam_projection_versions` records the expected versions of
canonical MIRL, core storage, the knowledge graph and node vectors, graph
products, lifecycle, workspace, reasoning graph/retrieval/verification/
patterns/promotion, and the SQLite vector projection.

Central steps and projection transitions are callable registries, not version
branches embedded in the executor. A projection transition is one exact
`projection_name` + `from_version` + `to_version` edge with a stable name and an
upgrade callable. Every edge also declares its source and target required-table
contracts, so a transition may add, rename, or retire projection-owned tables
without making its source database look invalid. Adjacent edges must have
matching table contracts, and the final edge must match the current projection
contract. Multi-step paths are resolved before mutation and execute in
projection-name order, then transition order. The registry is static so every
supported path is reviewable in source; SEAM never infers ordering from opaque
version strings.

Ordinary reopen validates both registries, the projection-owned tables, and
canonical reference payloads in deterministic bounded batches. A missing
required payload endpoint, wrong kind, malformed virtual-reference declaration,
or edge/contributor mismatch fails read-only before backup or mutation. Reopen
does not rerun idempotent DDL against a current database.

## Upgrade behavior

SEAM first inspects the database through a read-only connection and closes that
connection. It refuses an unknown schema, an unknown migration identity, a
newer central version, a missing or extra projection, an unregistered
projection-version change, or an unsupported knowledge-graph marker. This
initial refusal occurs before backup creation, locking-mode selection, DDL,
cleanup, or projection work, so the database file remains byte-unchanged.

When work is required, the migration owner selects and verifies SQLite
`locking_mode=EXCLUSIVE` as its first SQL operation, then acquires `BEGIN
EXCLUSIVE`. Under that lock it authoritatively rechecks the central migration
history, projection registry and exact plan, version-specific source tables,
knowledge-graph marker, SQLite integrity, and foreign keys. If any fact differs
from read-only preflight, SEAM refuses before creating a backup or applying a
migration. The owner commits this read-only bootstrap transaction but retains
the exclusive connection lock until final validation is complete and the
connection closes.

A fully registered projection path is a supported upgrade. Its callable gets a
narrow SQL facade, not the raw SQLite connection or a cursor exposing that
connection, and advances only that projection's marker with a compare-and-set.
The facade provides `execute`, `executemany`, and transactional
`execute_script`; it does not expose commit, rollback, close, cursor,
`executescript`, or authorizer control. While the callable runs, the spine's
SQLite authorizer also refuses SQL transaction/savepoint control and changes to
`locking_mode` or `journal_mode`. These controls prevent accidental ownership
violations by registered, reviewed internal migration code; they are not a
sandbox against malicious code already executing inside the SEAM process. The
spine rejects a callable that changes another projection marker or fails its
declared target-table contract. Knowledge-graph transitions must also advance
their internal `knowledge_graph_meta` marker before the common post-step gate.

Supported file-backed upgrades create a private SQLite backup under
`<database>.seam-backups/` after locked revalidation and before the first
migration step. The exclusive owner creates the backup from its same,
autocommit connection, so no competing writer can commit between the validated
snapshot, the backup, and migration completion. Each central or projection step
then runs in its own `BEGIN IMMEDIATE` transaction under the retained exclusive
lock. Before each step commits, SEAM runs `PRAGMA integrity_check` and `PRAGMA
foreign_key_check`; an injected or real failure rolls back only the active
step. Earlier committed steps remain durable and the next open resumes from the
recorded step. A backup is copied to a private temporary name, validated,
file-fsynced, atomically published, and directory-fsynced; a failed copy is
never left under a recoverable final name. Backups are retained deliberately
and are never deleted automatically.

The maintained historical fixtures are documented under
`tests/fixtures/sqlite_history/`. A pre-graph store can build its first graph
from canonical MIRL inside the explicit migration transaction because it has no
graph-only state to lose. `knowledge-graph/4` now has one exact registered
transition to `knowledge-graph/5`. The callable atomically discards only
derived topology, rebuilds from canonical `ir_records`, reapplies soft-delete
cleanup from canonical MIRL status, and reapplies source supersession from
`document_status.deleted_at`. It does not copy stale episode or edge lifecycle
rows through the rebuild. Explicit identity-merge decisions remain in their
separate durable judgement ledger and are revalidated against rebuilt nodes.
The S4 `knowledge-graph/5` -> `/6` typed-reference transition follows that S3
boundary exactly; stores at `/4` advance through both registered steps rather
than skipping the guarded supersession rebuild.

## Recovery

Quiesce writers and close every runtime and `SQLiteStore` first, then restore
the exact backup. Every supported file-backed store holds a lifetime shared
lease; restore takes the corresponding exclusive maintenance lease without
waiting and raises `DatabaseInUseError` instead of crossing a live store:

On POSIX, forked children do not share lease-registry ownership with their
parent. A child that opens its own store acquires its own process-local lease,
while closing an inherited parent store in the child cannot unlock the
parent-owned lease.

```python
from seam_runtime.migrations import DatabaseInUseError, restore_database_backup

restore_database_backup("seam.db", "seam.db.seam-backups/seam.pre-migration-v0-<id>.sqlite3")
```

Recovery validates the backup's SQLite integrity and foreign keys, copies it to
a same-directory temporary file, and fsyncs it. Recognized live WAL/journal
state is checkpointed into the old target; every remaining old sidecar is moved
to a non-SQLite quarantine name and directory-fsynced before the restored file
becomes the single replacement commit point. A crash can therefore reopen the
self-contained old target or the restored target, but an old WAL cannot attach
to the restored bytes. Reopening SEAM then runs the supported upgrade again
from the recovered version. Restore is an explicit rollback to the
pre-migration snapshot: it intentionally discards any commits made after that
backup was captured.

## Qualification

`tests/audit/test_sqlite_migration_spine.py` proves:

- empty and every maintained historical fixture upgrade;
- injected failure after every registered step rolls that step back;
- integrity and foreign-key checks run after every step and supported path;
- an explicit projection-version bump upgrades a populated current store,
  creates a newly required table, preserves canonical and projection data, and
  advances only its own marker;
- projection failure rolls back both callable DDL and the registry marker;
- projection callables cannot expose or end the spine-owned transaction, clear
  its authorizer, or downgrade its locking/journal mode through supported APIs;
- locked preflight refuses central-history or projection-registry TOCTOU drift
  before backup or migration mutation;
- competing writers remain blocked after backup and across per-step commits in
  both SQLite DELETE and WAL journal modes;
- failed backup creation cleans its partial file, while atomic publication and
  directory durability are verified before migration begins;
- failure after a later step preserves the earlier committed resume point;
- restoring the pre-projection backup and reopening repeats the upgrade safely;
- the KG/4-to-KG/5 rebuild has zero superseded-to-live flips, preserves current,
  point-in-time, and full-history graph semantics, and retains a shared edge
  while another active episode supports it;
- injected rebuild failure restores every relevant table hash, while an
  unsupported newer projection request refuses with the same hashes;
- unknown/newer central and projection versions are refused byte-unchanged;
- missing, extra, and changed unregistered projection states remain
  byte-unchanged and create no backup;
- a pre-migration backup restores deleted canonical truth and re-upgrades.
- a live supported store refuses restore in-process and across processes,
  without changing the target; restore succeeds after the final lease closes;
- sidecar quarantine failure occurs before the replacement commit point and
  leaves the old database active.
