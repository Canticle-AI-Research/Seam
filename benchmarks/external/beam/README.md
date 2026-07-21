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
# Accepts the official checkout root, chats root, 1M scale root, or an
# exported Hugging Face rows JSON.
.venv/bin/python -m benchmarks.external.beam.run \
    --track 1m --dataset-path /path/to/BEAM --dry-run
```

## Dataset

The BEAM dataset is not bundled. Competitive execution is delegated to the
pinned upstream `mem0ai/memory-benchmarks` runner, which obtains the official
Hugging Face release and preserves BEAM's ten question types and nugget rubric.

BEAM-1M expected shape: 35 conversations and 700 total probing questions.

## Dry-run validation

For the official local layout, dry-run resolves
`chats/<scale>/<conversation>/chat.json` and the matching nested
`probing_questions/probing_questions.json`. It fully parses every chat and
question, requires nonempty conversations and rubric nuggets, validates all
ten question types and expected track totals, and emits a root-independent
content hash over the exact source files. It reads and hashes each source file
once instead of serializing a million-token conversation once per question.

Unknown legacy directory layouts remain structural-only and invalid for
execution because they cannot prove that questions are paired with their
official chat payloads. Competitive and predict-only execution still uses the
pinned upstream task-specific harness; local validation does not substitute a
generic scorer.

The audited local 1M release at `/home/terrabyte/BEAM/BEAM` validates as 35
conversations, 700 questions, 74,630 normalized turns, 70 questions in each of
the ten categories, and 70 hashed source files. This is corpus-readiness
evidence, not an answer score.

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
