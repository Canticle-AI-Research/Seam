# Pgvector Test Artifacts

`test_pgvector_*` SQLite sidecar files belong in:

```text
test_seam/pgvector/
```

These files are local test output. They are ignored by git, not project source,
not runtime state, and not continuity evidence. Clean or recreate them as needed
for local pgvector tests.

Tracked notes about pgvector testing belong in this `tests/docs/artifacts/`
tree unless they are operator-facing setup docs, in which case they stay in
`docs/`.

