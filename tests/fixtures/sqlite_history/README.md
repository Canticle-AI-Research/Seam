# Maintained SQLite history fixtures

These SQL fixtures are minimized, reviewable database snapshots used by the
central migration gate. They preserve the migration-relevant table shapes and
representative durable rows from released SEAM revisions without committing
opaque `.db` binaries.

| fixture | source revision | migration boundary |
| --- | --- | --- |
| `v1_2_0.sql` | tag `v1.2.0` (`b9132ac`) | pre-knowledge-graph core and legacy vector columns |
| `v2_4_0.sql` | tag `v2.4.0` (`01f3581`) | knowledge-graph/5 before the central schema spine |

Every file in this directory is enumerated by
`tests/audit/test_sqlite_migration_spine.py`; adding a fixture without an
upgrade expectation fails the test.
