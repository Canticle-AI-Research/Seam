# BEAM benchmark runner

Evaluates memory over long conversations with probing questions.

## Tracks

- **Whole BEAM release**: 100 conversations, 2,000 probing questions across
  128K, 500K, 1M, and 10M scales.
- **BEAM-1M**: 35 conversations, 700 probing questions (supported).
- **BEAM-10M**: 10 conversations, 200 questions; separately deferred and
  refused unless `--allow-10m` is explicit.

## Quickstart

```bash
# A directory scan validates counts only; an exported HF rows JSON additionally
# validates chat payloads, question types, and rubric nuggets.
.venv/bin/python -m benchmarks.external.beam.run \
    --track 1m --dataset-path /path/to/beam_rows.json --dry-run
```

## Dataset

The BEAM dataset is not bundled. Competitive execution is delegated to the
pinned upstream `mem0ai/memory-benchmarks` runner, which obtains the official
Hugging Face release and preserves BEAM's ten question types and nugget rubric.

BEAM-1M expected shape: 35 conversations and 700 total probing questions.

## Dry-run validation

Dry-run scans the dataset directory, counts conversations and questions, and
reports validation issues without executing the judge or adapter.

Directory scans are never executable: the older directory reader did not load
the chat payload and could otherwise evaluate questions against empty memory.

## Faithful execution

```bash
# Readiness only: does not import/download the dataset or launch the harness.
.venv/bin/python -m seam bench external beam \
    --track 1m \
    --harness-root /tmp/memory-benchmarks \
    --project-name seam-beam-1m-readiness \
    --dataset-cache-dir /data/beam \
    --predict-only --plan

# Terminal 1: SEAM under test
.venv/bin/python -m benchmarks.external.mem0_harness.seam_mem0_server \
    --db-path /tmp/seam-beam-1m --port 8900

# Terminal 2: free ingest + retrieval first
.venv/bin/python -m seam bench external beam \
    --track 1m \
    --harness-root /tmp/memory-benchmarks \
    --project-name seam-beam-1m-predict \
    --mem0-host http://127.0.0.1:8900 \
    --dataset-cache-dir /data/beam \
    --predict-only --workers 1
```

The isolated harness environment needs its own `datasets` dependency. A
missing dependency is reported as a readiness failure; SEAM does not mutate
that environment automatically. If `beam_1M.json` is absent from the selected
cache, execution also refuses the upstream automatic download unless the
operator separately approves it and passes `--allow-download`. Scored runs
additionally require explicit provider approval and `--allow-paid`.
