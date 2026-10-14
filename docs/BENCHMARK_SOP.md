# Benchmark SOP

Use this SOP when you want to validate whether SEAM memory retrieval is
actually getting better.

## What it measures

`python seam.py --db <file> stats` runs the versioned gold benchmark in
`docs/retrieval_gold_fixtures.json`.

It compares:

- raw overlap baseline
- vector-only baseline
- MIRL structured retrieval
- hybrid retrieval
- pack quality under budget

This is the in-memory fixture comparison in `seam_runtime/evals.py`; it does
not measure the persisted runtime retrieval path or exercise pgvector SQL.
Configuring a pgvector DSN does not turn this report into real-adapter proof.
Use the dedicated real-service tests for that separate property.

The hardened fixture set covers:

- fact retrieval
- workflow intent recovery
- relation-heavy graph queries
- temporal freshness and supersession
- contradiction handling
- scope isolation
- namespace and symbol inheritance

## Database setup

- **SQLite truth store** - the `--db` file you pass (`seam_validate.db`, etc.)
- **pgvector store** - optional Postgres container on `localhost:55432`, database `seam`

Use the [local pgvector runbook](PGVECTOR_LOCAL.md) to preserve an existing
private env file, start Compose **service** `pgvector`, and resolve the actual
user, database, password and selected port into `SEAM_PGVECTOR_DSN`. The
container name `seam-pgvector` is not a Compose service name. Do not assume the
user is `postgres`, or that a Compose env file automatically exports variables
into the benchmark process. Keep credential values out of logs.

## Run the local deterministic baseline

Uses the hash model, no cloud credentials required:

```powershell
python seam.py doctor
python seam.py --db seam_validate.db stats
```

Use this when:

- you want reproducible local tests
- you are changing MIRL, retrieval, or pack logic
- you do not want cloud calls during development

## Run the provider-backed fixture comparison

Uses your configured embedding provider:

```powershell
$env:OPENAI_API_KEY="your-key"
$env:SEAM_EMBEDDING_PROVIDER="openai-compatible"
$env:SEAM_EMBEDDING_MODEL="text-embedding-3-small"
# Configure SEAM_PGVECTOR_DSN first using docs/PGVECTOR_LOCAL.md.

python seam.py doctor
python seam.py --db seam_validate.db stats
```

Use this when:

- you want to compare a chosen provider under matched fixtures and settings
- you are comparing local models against a cloud baseline
- you have explicitly authorized the provider calls and their costs

## How to read `stats`

Look at `summary.tracks` first:

- `raw` is the raw-overlap comparison baseline
- `vector` shows pure embedding retrieval
- `mirl` shows structured retrieval without vector help
- `hybrid` reports the combined comparison path; an improvement must be measured

Then look at `summary.success_checks`:

- `mirl_beats_raw_on_fact_or_relation`
- `hybrid_beats_vector_on_relation`
- `exact_packs_reversible`
- `context_packs_traceable`

Finally inspect per-fixture results:

- `expected_ids` are the records that should come back
- `tracks` reports each retrieval track (raw, vector, mirl, hybrid,
  machine_nat_query, machine_vector, machine_hybrid) ranked against
  `expected_ids`
- `packs` reports the exact/context/narrative pack aggregation per fixture

## How to harden the benchmark

Add a fixture to `docs/retrieval_gold_fixtures.json` when you add a new memory
behavior that SEAM should guarantee.

Good hardened cases:

- stale vs current truth
- contradicted vs asserted truth
- project vs thread scope collisions
- parent-namespace symbol expansion
- provenance and evidence retention through packs

Each fixture should include:

- `query`
- `expected_ids`
- `name`, `source`, and `category`; `format` defaults to `dsl`
- optional `budget` (selected records) and `pack_budget` (tokens)

The loader does not consume `rejected_ids`, `rejection_rate`, `scope`, or
`notes`. Explanatory notes can document intent, but they do not become a
scored rejection or scope gate. Add a named executable check before claiming
one of those guarantees.

## Test workflow

When you change retrieval, MIRL fields, packs, or model adapters:

```powershell
python -m pytest test_seam_all\test_seam.py -q
python seam.py --db seam_validate.db stats
```

If you changed cloud or pgvector wiring, also run:

```powershell
python seam.py doctor
```

## Benchmark diff and gate tooling

Before claiming a retrieval improvement:

```powershell
python seam.py benchmark diff <run-a> <run-b>
python seam.py benchmark gate <bundle>
```

For publish-time audits only:

```powershell
python seam.py benchmark run --holdout --confirm-holdout
```
