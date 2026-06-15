# Testing Documentation Index

Repo-owned testing documentation lives under this tree.

## Routing

- `tests/docs/artifacts/` - local test artifact routing, cleanup, and retention notes.
- `test_seam/` - ignored local artifact sink for generated SQLite databases and other disposable test outputs.

## Rule

Do not put ad-hoc test notes, test run logs, `Test*` scratch files, or
`test_pgvector_*` artifacts in the repo root. Route them to the narrowest
matching folder under `tests/docs/` for tracked documentation or `test_seam/`
for ignored generated output.

