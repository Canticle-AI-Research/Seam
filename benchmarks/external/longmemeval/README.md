# LongMemEval benchmark runner

LongMemEval has 500 questions covering five core abilities: information
extraction, multi-session reasoning, temporal reasoning, knowledge updates, and
abstention. The official JSON uses six `question_type` labels because
single-session memory is split into user, assistant, and preference types;
abstention cases retain their underlying type and carry an `_abs` question-id
suffix.

## Quickstart

```bash
# Validate a local dataset without executing:
.venv/bin/python -m benchmarks.external.longmemeval.run \
    --dataset-path /path/to/longmemeval_s_cleaned.json --dry-run
```

## Dataset

The LongMemEval dataset is not bundled. Download it from the public LongMemEval
release and point `--dataset-path` at the JSON file.

Expected official `question_type` values:
`single-session-user`, `single-session-assistant`,
`single-session-preference`, `multi-session`, `knowledge-update`, and
`temporal-reasoning`.

## Dry-run validation

Dry-run prints case counts, category breakdown, fixture hash, and validation
issues without executing the judge or adapter. Use it to verify dataset
integrity before committing to a real run.

## Faithful execution

The in-repo path is deliberately a validator, not a second implementation of
LongMemEval's answer and judge contract. Scored and predict-only execution uses
the pinned `mem0ai/memory-benchmarks` checkout against SEAM's loopback Mem0
facade:

```bash
# Readiness only: validates the pinned checkout and local dataset, then exits.
.venv/bin/python -m seam bench external longmemeval \
    --dataset-path /data/longmemeval_s_cleaned.json \
    --harness-root /tmp/memory-benchmarks \
    --project-name seam-longmemeval-readiness \
    --predict-only --plan

# Terminal 1: SEAM under test
.venv/bin/python -m benchmarks.external.mem0_harness.seam_mem0_server \
    --db-path /tmp/seam-longmemeval --port 8900

# Terminal 2: free ingest + retrieval first
.venv/bin/python -m seam bench external longmemeval \
    --dataset-path /data/longmemeval_s_cleaned.json \
    --harness-root /tmp/memory-benchmarks \
    --project-name seam-longmemeval-predict \
    --mem0-host http://127.0.0.1:8900 \
    --predict-only --workers 1
```

Omit `--predict-only` only after explicit provider-spend approval, specify a
real `--judge`, and add `--allow-paid`. The harness revision is fixed in
`upstream_runner.py`; a mismatch fails closed.
