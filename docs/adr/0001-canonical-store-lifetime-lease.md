# Canonical stores hold a lifetime lease

Status: accepted

Every supported file-backed `SQLiteStore` holds a shared cross-process lease
for its entire lifetime, while byte-replacing recovery requires the same
database's exclusive nonblocking maintenance lease. This is separate from the
transient runtime persistence lock: reusing that lock would serialize active
writes but would not detect an idle store with cached SQLite pages, which is
the state that caused acknowledged rows to disappear across restore. The lease
is a sidecar lock rather than a row in the database because recovery replaces
the database file itself.
